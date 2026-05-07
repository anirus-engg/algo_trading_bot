"""
Strategy Agent: Scores watchlist stocks for EMA pullback + RSI + momentum setups.
Reads strategy memory (cached) and outputs ranked candidates.
"""
import json
import pandas as pd
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from anthropic import Anthropic
import config
from strategy.signals import add_all_indicators, score_setup, calculate_entry_levels
from logger import get_logger

log = get_logger("strategy")


def load_watchlist() -> list:
    with open(config.WATCHLIST_PATH, "r") as f:
        data = json.load(f)
    return [item["symbol"] for item in data["watchlist"]]


def load_research_brief() -> dict:
    with open(config.RESEARCH_BRIEF_PATH, "r") as f:
        data = json.load(f)
    return data["brief"]


def load_strategy_memory() -> dict:
    try:
        with open(config.STRATEGY_MEMORY_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"trades": [], "strategy_notes": "No trades yet.", "signal_performance": {}}


def fetch_bars_batch(symbols: list, days: int = config.BARS_LOOKBACK_DAYS) -> dict:
    """Fetch daily bars for all symbols in a single API call."""
    log.info(f"Fetching {days}-day bars for {len(symbols)} symbols (single batch call)...")
    client = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    end = datetime.now()
    start = end - timedelta(days=days)

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end
    )

    bars = client.get_stock_bars(request)
    multi_df = bars.df if hasattr(bars, 'df') else bars

    result = {}
    if isinstance(multi_df, pd.DataFrame) and not multi_df.empty:
        for symbol in symbols:
            try:
                df = multi_df.xs(symbol, level=0).copy() if multi_df.index.nlevels > 1 else multi_df.copy()
                if not df.empty:
                    result[symbol] = df
            except KeyError:
                pass

    log.info(f"Bar data received for {len(result)}/{len(symbols)} symbols")
    return result


def score_candidates(watchlist: list, brief: dict, memory: dict) -> list:
    """Score all watchlist stocks and return qualified candidates."""
    candidates = []
    disqualified = []

    bars_by_symbol = fetch_bars_batch(watchlist)

    log.info(f"Scoring {len(watchlist)} stocks against strategy rules...")

    for symbol in watchlist:
        try:
            df = bars_by_symbol.get(symbol)
            if df is None or df.empty:
                log.debug(f"{symbol}: no bar data — skipping")
                disqualified.append((symbol, "no_data"))
                continue

            if len(df) < 52:
                log.debug(f"{symbol}: only {len(df)} bars (need 52) — skipping")
                disqualified.append((symbol, f"only_{len(df)}_bars"))
                continue

            df = add_all_indicators(df)

            sentiment = "neutral"
            if isinstance(brief, dict) and symbol in brief:
                val = brief[symbol]
                sentiment = val.get("sentiment", "neutral") if isinstance(val, dict) else val

            score_result = score_setup(df, news_sentiment=sentiment)

            if not score_result.get("qualified"):
                reason = score_result.get("reason", "score_too_low")
                score = score_result.get("score", 0)
                log.debug(f"{symbol}: disqualified — {reason} (score={score})")
                disqualified.append((symbol, reason))
                continue

            entry_levels = calculate_entry_levels(score_result, config.MAX_POSITION_SIZE)
            if not entry_levels:
                log.debug(f"{symbol}: entry level calculation failed")
                disqualified.append((symbol, "entry_calc_failed"))
                continue

            candidate = {
                "symbol": symbol,
                "score": score_result["score"],
                "signals": score_result["signals"],
                "entry": entry_levels["entry"],
                "stop_loss": entry_levels["stop_loss"],
                "take_profit": entry_levels["take_profit"],
                "shares": entry_levels["shares"],
                "notional": entry_levels["notional"],
                "risk_per_share": entry_levels["risk_per_share"],
                "trailing_stop_activation_price": entry_levels["trailing_stop_activation_price"],
                "sentiment": sentiment,
            }

            log.info(
                f"{symbol}: QUALIFIED score={score_result['score']} "
                f"entry=${entry_levels['entry']} stop=${entry_levels['stop_loss']} "
                f"target=${entry_levels['take_profit']} shares={entry_levels['shares']} "
                f"notional=${entry_levels['notional']} sentiment={sentiment}"
            )

            # Log which signals fired
            for sig_name, sig_data in score_result.get("signals", {}).items():
                if isinstance(sig_data, dict) and sig_data.get("points", 0) > 0:
                    log.debug(f"  {symbol} signal [{sig_name}]: {sig_data}")

            candidates.append(candidate)

        except Exception as e:
            log.warning(f"{symbol}: unexpected error — {e}")
            disqualified.append((symbol, f"error: {e}"))
            continue

    log.info(f"Scoring complete: {len(candidates)} qualified, {len(disqualified)} disqualified")

    if disqualified:
        reason_counts = {}
        for _, reason in disqualified:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        log.info(f"Disqualification reasons: {reason_counts}")

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def add_claude_reasoning(candidates: list, memory: dict) -> list:
    """Add Claude reasoning to each candidate (batched call)."""
    if not config.ANTHROPIC_API_KEY or not candidates:
        for c in candidates:
            c["reasoning"] = f"Score {c['score']}: Technical setup with {c['sentiment']} sentiment."
        return candidates

    log.info(f"Requesting Claude reasoning for {len(candidates)} candidates...")
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system_prompt = f"""You are a swing trading strategist. Based on our trading history, provide brief reasoning for each trade candidate.

Strategy Memory:
{json.dumps(memory, indent=2)}

For each candidate, explain in 1-2 sentences why this setup looks promising based on the signals and our past performance."""

    prompt = f"""Here are today's trade candidates:

{json.dumps(candidates, indent=2)}

Add a "reasoning" field to each candidate with 1-2 sentences.
Return the full candidates array as valid JSON."""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }]
        )

        content = response.content[0].text
        enriched = json.loads(content)
        for c in enriched:
            log.info(f"{c.get('symbol')}: {c.get('reasoning', '')[:100]}")
        return enriched

    except Exception as e:
        log.warning(f"Claude reasoning failed: {e}")
        for c in candidates:
            c["reasoning"] = f"Score {c['score']}: Technical setup with {c['sentiment']} sentiment."
        return candidates


def run():
    """Main strategy agent logic."""
    log.info("=" * 60)
    log.info("STRATEGY AGENT STARTING")
    log.info("=" * 60)

    watchlist = load_watchlist()
    brief = load_research_brief()
    memory = load_strategy_memory()

    log.info(f"Watchlist: {watchlist}")
    log.info(f"Strategy memory: {len(memory.get('trades', []))} historical trades")
    if memory.get("strategy_notes"):
        log.info(f"Strategy notes: {memory['strategy_notes'][:200]}")

    candidates = score_candidates(watchlist, brief, memory)

    if candidates:
        log.info(f"Adding Claude reasoning to {len(candidates)} candidates...")
        candidates = add_claude_reasoning(candidates, memory)

    output = {
        "generated_at": datetime.now().isoformat(),
        "candidates": candidates,
    }

    with open(config.CANDIDATES_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info(f"Candidates saved to {config.CANDIDATES_PATH}")
    if candidates:
        log.info(f"Top candidates: {[c['symbol'] for c in candidates[:5]]}")
    else:
        log.info("No qualified candidates today")

    log.info("STRATEGY AGENT COMPLETE")
    return candidates


if __name__ == "__main__":
    run()
