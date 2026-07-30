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
from strategy.signals import (
    add_all_indicators, score_intraday_setup, score_orb_setup,
    calculate_entry_levels,
)
from logger import get_logger

log = get_logger("strategy")

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_watchlist() -> list:
    """Load intraday watchlist if available, falling back to daily watchlist."""
    try:
        with open(config.INTRADAY_WATCHLIST_PATH) as f:
            data = json.load(f)
        stocks = data.get("stocks", [])
        if stocks:
            log.info(f"Intraday watchlist loaded: {len(stocks)} stocks")
            return stocks
    except FileNotFoundError:
        pass

    try:
        with open(config.WATCHLIST_PATH) as f:
            data = json.load(f)
        stocks = data.get("watchlist", [])
        log.info(f"Daily watchlist loaded: {len(stocks)} stocks")
        return stocks
    except FileNotFoundError:
        log.warning("watchlist.json not found — no stocks to score")
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
# Daily bar fetching + trend gate
# ---------------------------------------------------------------------------

def fetch_daily_bars(symbols: list) -> dict:
    """
    Fetch daily bars for all symbols — used for the daily EMA trend gate.
    Batches API request for efficiency with fallback per symbol.
    """
    if not symbols:
        return {}

    client = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    end = datetime.now()
    start = end - timedelta(days=config.DAILY_BARS_LOOKBACK_DAYS)

    result = {}
    try:
        from alpaca.data.timeframe import TimeFrame as TF
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TF.Day,
            start=start,
            end=end,
        )
        bars = client.get_stock_bars(request)
        multi_df = bars.df if hasattr(bars, "df") else bars
        if isinstance(multi_df, pd.DataFrame) and not multi_df.empty:
            for symbol in symbols:
                try:
                    df = (multi_df.xs(symbol, level=0).copy()
                          if multi_df.index.nlevels > 1 else multi_df.copy())
                    if not df.empty:
                        result[symbol] = df
                except KeyError:
                    pass
    except Exception as e:
        log.warning(f"Batched daily bar fetch failed ({e}) — trying individual fetches")
        for symbol in symbols:
            try:
                from alpaca.data.timeframe import TimeFrame as TF
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=TF.Day,
                    start=start,
                    end=end,
                )
                bars = client.get_stock_bars(request)
                raw = bars.df if hasattr(bars, "df") else bars
                df = raw.xs(symbol, level=0).copy() if isinstance(raw.index, pd.MultiIndex) else raw.copy()
                if not df.empty:
                    result[symbol] = df
            except Exception:
                pass

    log.info(f"Daily bars fetched: {len(result)}/{len(symbols)} symbols")
    return result


def is_daily_uptrend(daily_df: pd.DataFrame) -> tuple[bool, str]:
    """
    Check if the stock is in a daily uptrend using EMA9 > EMA20 on daily bars.
    Returns (is_uptrend: bool, detail: str).
    Falls back to True (allow) if insufficient data.
    """
    if daily_df is None or len(daily_df) < config.DAILY_EMA_SLOW:
        return True, "insufficient_daily_bars"

    df = daily_df.copy()
    df["ema_fast"] = df["close"].ewm(span=config.DAILY_EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=config.DAILY_EMA_SLOW, adjust=False).mean()

    row = df.iloc[-1]
    uptrend = row["ema_fast"] > row["ema_slow"]
    detail = f"daily_ema{config.DAILY_EMA_FAST}={row['ema_fast']:.2f}_ema{config.DAILY_EMA_SLOW}={row['ema_slow']:.2f}"
    return uptrend, detail


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
    """
    Score all watchlist stocks for both VWAP Reclaim and ORB Breakout setups.
    A stock can qualify via either setup. If both qualify, the higher-scoring
    setup wins. Returns ranked list of qualified candidates.

    Daily EMA trend gate: stocks where daily EMA9 <= daily EMA20 are rejected
    before intraday scoring. This is more stable than the 5-min EMA gate.
    """
    if not watchlist_stocks:
        log.info("No stocks to score")
        return []

    symbols = [s["symbol"] for s in watchlist_stocks]
    candidates = []
    disqualified = []

    # Fetch daily bars once for the trend gate, then intraday bars for scoring
    daily_bars = fetch_daily_bars(symbols)
    bars_by_symbol = fetch_intraday_bars(symbols)

    log.info(f"Scoring {len(symbols)} stocks (VWAP Reclaim + ORB Breakout)...")

    for stock in watchlist_stocks:
        symbol = stock["symbol"]
        try:
            # --- Daily EMA trend gate (hard gate, runs before intraday scoring) ---
            uptrend, trend_detail = is_daily_uptrend(daily_bars.get(symbol))
            if not uptrend:
                log.debug(f"{symbol}: REJECTED — daily downtrend ({trend_detail})")
                disqualified.append((symbol, f"daily_downtrend"))
                continue
            else:
                log.debug(f"{symbol}: daily uptrend confirmed ({trend_detail})")

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

            # News sentiment
            sentiment = "neutral"
            if isinstance(brief, dict) and symbol in brief:
                val = brief[symbol]
                sentiment = val.get("sentiment", "neutral") if isinstance(val, dict) else val

            # --- Run both setups ---
            vwap_result = score_intraday_setup(df, news_sentiment=sentiment)
            orb_result = score_orb_setup(df, news_sentiment=sentiment)

            # Pick the best qualifying setup
            best_result = None
            if vwap_result.get("qualified") and orb_result.get("qualified"):
                # Both qualify — take higher score
                best_result = vwap_result if vwap_result["score"] >= orb_result["score"] else orb_result
                log.info(f"{symbol}: BOTH setups qualified — using {best_result['setup_type']} (score={best_result['score']})")
            elif vwap_result.get("qualified"):
                best_result = vwap_result
            elif orb_result.get("qualified"):
                best_result = orb_result
            else:
                vwap_reason = vwap_result.get("reason", "score_too_low")
                orb_reason = orb_result.get("reason", "score_too_low")
                log.debug(f"{symbol}: neither setup qualified — vwap={vwap_reason} orb={orb_reason}")
                disqualified.append((symbol, f"vwap:{vwap_reason}|orb:{orb_reason}"))
                continue

            entry_levels = calculate_entry_levels(best_result, config.MAX_POSITION_SIZE)
            if not entry_levels:
                log.debug(f"{symbol}: entry level calculation failed")
                disqualified.append((symbol, "entry_calc_failed"))
                continue

            setup_type = best_result["setup_type"]
            candidate = {
                "symbol": symbol,
                "setup_type": setup_type,
                "score": best_result["score"],
                "signals": best_result["signals"],
                "entry": entry_levels["entry"],
                "stop_loss": entry_levels["stop_loss"],
                "take_profit": entry_levels["take_profit"],
                "shares": entry_levels["shares"],
                "notional": entry_levels["notional"],
                "risk_per_share": entry_levels["risk_per_share"],
                "vwap": best_result["vwap"],
                "ema_fast": best_result["ema_fast"],
                "ema_slow": best_result["ema_slow"],
                "rsi": best_result["rsi"],
                "atr": best_result["atr"],
                "sentiment": sentiment,
                "daily_trend": trend_detail,
            }

            # Add ORB levels if applicable
            if setup_type == "orb":
                candidate["orb_high"] = best_result.get("orb_high")
                candidate["orb_low"] = best_result.get("orb_low")

            log.info(
                f"{symbol}: QUALIFIED [{setup_type.upper()}] score={best_result['score']} "
                f"entry=${entry_levels['entry']} stop=${entry_levels['stop_loss']} "
                f"target=${entry_levels['take_profit']} shares={entry_levels['shares']} "
                f"notional=${entry_levels['notional']} rsi={best_result['rsi']} "
                f"sentiment={sentiment}"
            )

            for sig_name, sig_data in best_result.get("signals", {}).items():
                if isinstance(sig_data, dict) and sig_data.get("points", 0) > 0:
                    log.debug(f"  {symbol} [{sig_name}]: {sig_data}")

            candidates.append(candidate)

        except Exception as e:
            log.warning(f"{symbol}: unexpected error — {e}")
            disqualified.append((symbol, f"error:{e}"))
            continue

    log.info(f"Scoring complete: {len(candidates)} qualified, {len(disqualified)} disqualified")

    if candidates:
        vwap_count = sum(1 for c in candidates if c["setup_type"] == "vwap_reclaim")
        orb_count = sum(1 for c in candidates if c["setup_type"] == "orb")
        log.info(f"  Setup breakdown: {vwap_count} VWAP reclaim, {orb_count} ORB breakout")

    if disqualified:
        reason_counts = {}
        for _, reason in disqualified:
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

    system_prompt = f"""You are an intraday day trading strategist specialising in VWAP reclaim and ORB breakout setups on 5-minute charts.
Based on our trading history, provide brief reasoning for each trade candidate.

Strategy Memory:
{json.dumps(memory, indent=2)}

For each candidate, explain in 1-2 sentences why this setup looks promising,
referencing the setup_type (vwap_reclaim or orb), the signals, and any relevant patterns from our past performance."""

    prompt = f"""Here are today's intraday trade candidates:

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
    Scores all 25 watchlist stocks for VWAP reclaim setups on 5-min bars.
    """
    now_et = datetime.now(tz=ET)
    log.info("=" * 60)
    log.info(f"STRATEGY AGENT — {now_et.strftime('%H:%M ET')}")
    log.info("=" * 60)

    watchlist_stocks = load_watchlist()
    brief = load_research_brief()
    memory = load_strategy_memory()

    log.info(f"Watchlist: {[s['symbol'] for s in watchlist_stocks]}")
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
        log.info(f"Top candidates: {[(c['symbol'], c['setup_type']) for c in candidates[:5]]}")
    else:
        log.info("No qualified setups at this time (VWAP Reclaim or ORB Breakout)")

    log.info("STRATEGY AGENT COMPLETE")
    return candidates


if __name__ == "__main__":
    run()
