"""
Strategy Agent: Scores intraday watchlist stocks for VWAP reclaim setups on 5-min bars.
Reads intraday_watchlist.json + research_brief.json + strategy_memory.json.
Outputs ranked candidates to candidates.json.
Runs every 5 minutes during trading hours (9:45 AM – 3:50 PM ET).
"""
import json
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from anthropic import Anthropic
import config
from strategy.signals import add_all_indicators, score_intraday_setup, calculate_entry_levels
from logger import get_logger

log = get_logger("strategy")

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_intraday_watchlist() -> list:
    """Load the pre-market filtered intraday watchlist."""
    try:
        with open(config.INTRADAY_WATCHLIST_PATH) as f:
            data = json.load(f)
        stocks = data.get("stocks", [])
        log.info(
            f"Intraday watchlist loaded: {len(stocks)} stocks "
            f"(stage={data.get('stage', 'unknown')})"
        )
        return stocks
    except FileNotFoundError:
        log.warning("intraday_watchlist.json not found — falling back to daily watchlist")
        return _load_daily_watchlist_fallback()


def _load_daily_watchlist_fallback() -> list:
    """Fallback: use daily watchlist if intraday watchlist not yet generated."""
    try:
        with open(config.WATCHLIST_PATH) as f:
            data = json.load(f)
        return [{"symbol": s["symbol"]} for s in data.get("watchlist", [])]
    except FileNotFoundError:
        return []


def load_research_brief() -> dict:
    try:
        with open(config.RESEARCH_BRIEF_PATH) as f:
            data = json.load(f)
        return data.get("brief", {})
    except FileNotFoundError:
        return {}


def load_strategy_memory() -> dict:
    try:
        with open(config.STRATEGY_MEMORY_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"trades": [], "strategy_notes": "No trades yet.", "signal_performance": {}}


# ---------------------------------------------------------------------------
# 5-min bar fetching
# ---------------------------------------------------------------------------

def fetch_intraday_bars(symbols: list) -> dict:
    """
    Fetch 5-min bars for all symbols.
    Lookback: INTRADAY_BARS_LOOKBACK_DAYS (10 days) to have enough bars
    for EMA20 and volume averages.
    """
    if not symbols:
        return {}

    log.info(
        f"Fetching {config.INTRADAY_TIMEFRAME_MINUTES}-min bars "
        f"({config.INTRADAY_BARS_LOOKBACK_DAYS} days) "
        f"for {len(symbols)} symbols..."
    )

    client = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    end = datetime.now(tz=ET)
    start = end - timedelta(days=config.INTRADAY_BARS_LOOKBACK_DAYS)

    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame(config.INTRADAY_TIMEFRAME_MINUTES, TimeFrameUnit.Minute),
            start=start,
            end=end,
            feed=config.INTRADAY_DATA_FEED,
        )
        bars = client.get_stock_bars(request)
        multi_df = bars.df if hasattr(bars, "df") else bars

        result = {}
        if isinstance(multi_df, pd.DataFrame) and not multi_df.empty:
            for symbol in symbols:
                try:
                    df = (multi_df.xs(symbol, level=0).copy()
                          if multi_df.index.nlevels > 1 else multi_df.copy())
                    if not df.empty:
                        result[symbol] = df
                except KeyError:
                    pass

        log.info(f"5-min bar data received for {len(result)}/{len(symbols)} symbols")
        return result

    except Exception as e:
        log.error(f"5-min bar fetch failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_candidates(watchlist_stocks: list, brief: dict, memory: dict) -> list:
    """Score all intraday watchlist stocks and return qualified VWAP reclaim candidates."""
    if not watchlist_stocks:
        log.info("No stocks in intraday watchlist to score")
        return []

    symbols = [s["symbol"] for s in watchlist_stocks]
    candidates = []
    disqualified = []

    bars_by_symbol = fetch_intraday_bars(symbols)

    log.info(f"Scoring {len(symbols)} stocks for VWAP reclaim setups...")

    for stock in watchlist_stocks:
        symbol = stock["symbol"]
        try:
            df = bars_by_symbol.get(symbol)
            if df is None or df.empty:
                log.debug(f"{symbol}: no 5-min bar data — skipping")
                disqualified.append((symbol, "no_data"))
                continue

            if len(df) < 25:
                log.debug(f"{symbol}: only {len(df)} bars (need 25) — skipping")
                disqualified.append((symbol, f"only_{len(df)}_bars"))
                continue

            df = add_all_indicators(df)

            # Get news sentiment
            sentiment = "neutral"
            if isinstance(brief, dict) and symbol in brief:
                val = brief[symbol]
                sentiment = val.get("sentiment", "neutral") if isinstance(val, dict) else val

            score_result = score_intraday_setup(df, news_sentiment=sentiment)

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
                "vwap": score_result["vwap"],
                "ema_fast": score_result["ema_fast"],
                "ema_slow": score_result["ema_slow"],
                "rsi": score_result["rsi"],
                "atr": score_result["atr"],
                "sentiment": sentiment,
                # Pre-market context from watchlist
                "gap_pct": stock.get("gap_pct"),
                "open_vol_ratio": stock.get("open_vol_ratio"),
            }

            log.info(
                f"{symbol}: QUALIFIED score={score_result['score']} "
                f"entry=${entry_levels['entry']} stop=${entry_levels['stop_loss']} "
                f"target=${entry_levels['take_profit']} shares={entry_levels['shares']} "
                f"notional=${entry_levels['notional']} "
                f"vwap=${score_result['vwap']} rsi={score_result['rsi']} "
                f"sentiment={sentiment}"
            )

            for sig_name, sig_data in score_result.get("signals", {}).items():
                if isinstance(sig_data, dict) and sig_data.get("points", 0) > 0:
                    log.debug(f"  {symbol} [{sig_name}]: {sig_data}")

            candidates.append(candidate)

        except Exception as e:
            log.warning(f"{symbol}: unexpected error — {e}")
            disqualified.append((symbol, f"error:{e}"))
            continue

    log.info(f"Scoring complete: {len(candidates)} qualified, {len(disqualified)} disqualified")

    if disqualified:
        reason_counts = {}
        for _, reason in disqualified:
            # Normalise reason key for counting
            key = reason.split(":")[0]
            reason_counts[key] = reason_counts.get(key, 0) + 1
        log.info(f"Disqualification reasons: {reason_counts}")

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def add_claude_reasoning(candidates: list, memory: dict) -> list:
    """Add Claude reasoning to each candidate (batched call)."""
    if not config.ANTHROPIC_API_KEY or not candidates:
        for c in candidates:
            c["reasoning"] = (
                f"Score {c['score']}: VWAP reclaim setup with "
                f"{c['sentiment']} sentiment."
            )
        return candidates

    log.info(f"Requesting Claude reasoning for {len(candidates)} candidates...")
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    system_prompt = f"""You are an intraday day trading strategist specialising in VWAP reclaim setups on 5-minute charts.
Based on our trading history, provide brief reasoning for each trade candidate.

Strategy Memory:
{json.dumps(memory, indent=2)}

For each candidate, explain in 1-2 sentences why this VWAP reclaim setup looks promising,
referencing the signals and any relevant patterns from our past performance."""

    prompt = f"""Here are today's intraday trade candidates (VWAP reclaim setups):

{json.dumps(candidates, indent=2)}

Add a "reasoning" field to each candidate with 1-2 sentences.
Return the full candidates array as valid JSON."""

    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
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
            c["reasoning"] = (
                f"Score {c['score']}: VWAP reclaim setup with "
                f"{c['sentiment']} sentiment."
            )
        return candidates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    """
    Main strategy agent logic.
    Called every 5 minutes during trading hours by main.py.
    """
    now_et = datetime.now(tz=ET)
    log.info("=" * 60)
    log.info(f"STRATEGY AGENT — {now_et.strftime('%H:%M ET')}")
    log.info("=" * 60)

    watchlist_stocks = load_intraday_watchlist()
    brief = load_research_brief()
    memory = load_strategy_memory()

    log.info(f"Intraday watchlist: {[s['symbol'] for s in watchlist_stocks]}")
    log.info(f"Strategy memory: {len(memory.get('trades', []))} historical trades")

    candidates = score_candidates(watchlist_stocks, brief, memory)

    if candidates:
        log.info(f"Adding Claude reasoning to {len(candidates)} candidates...")
        candidates = add_claude_reasoning(candidates, memory)

    output = {
        "generated_at": now_et.isoformat(),
        "candidates": candidates,
    }

    with open(config.CANDIDATES_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info(f"Candidates saved to {config.CANDIDATES_PATH}")
    if candidates:
        log.info(f"Top candidates: {[c['symbol'] for c in candidates[:5]]}")
    else:
        log.info("No qualified VWAP reclaim setups at this time")

    log.info("STRATEGY AGENT COMPLETE")
    return candidates


if __name__ == "__main__":
    run()
