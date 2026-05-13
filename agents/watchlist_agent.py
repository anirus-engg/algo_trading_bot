"""
Watchlist Agent: Two-stage daily stock selection for day trading.

Stage 1 — Daily watchlist (runs 8:00 AM):
  Scores universe (100 stocks) by ATR% and volume ratio on daily bars.
  Outputs top 25 → watchlist.json

Stage 2 — Pre-market / open filter (runs 9:15 AM gap check + 9:35 AM volume confirm):
  Narrows the 25 to stocks that are actually "in play" today:
    - Gap > 1% from prior close (using quote API — works on Basic plan)
    - First 5-min bar volume > 1.5x 20-day average for that time slot
  Outputs filtered list → intraday_watchlist.json
"""
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date, time as dtime
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import config
from strategy.signals import compute_atr_daily, compute_volume_ratio_daily
from agents.universe_agent import load_universe
from logger import get_logger

log = get_logger("watchlist")

ET = ZoneInfo("America/New_York")


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy scalar types."""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


# ---------------------------------------------------------------------------
# Stage 1: Daily watchlist
# ---------------------------------------------------------------------------

def fetch_daily_bars(symbols: list, days: int = config.BARS_LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch daily bars for all symbols in one batched API call."""
    log.info(f"Fetching {days}-day daily bars for {len(symbols)} symbols...")
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
    result = bars.df if hasattr(bars, "df") else bars
    log.debug(f"Daily bar fetch complete. Type: {type(result).__name__}")
    return result


def score_stock_daily(symbol: str, df: pd.DataFrame) -> dict:
    """Score a stock for day trading potential using daily bars."""
    if len(df) < 21:
        log.debug(f"{symbol}: skipped — only {len(df)} bars (need 21)")
        return {"symbol": symbol, "score": 0, "reason": "insufficient_data"}

    df = df.copy()
    df = compute_atr_daily(df)
    df = compute_volume_ratio_daily(df)

    row = df.iloc[-1]

    vol_ratio = row.get("vol_ratio", 1.0)
    if pd.isna(vol_ratio):
        vol_ratio = 1.0
    vol_score = min(vol_ratio * 2, 5)

    atr_pct = (row["atr"] / row["close"]) * 100
    # Sweet spot for day trading: 2–6% ATR
    if 2.0 <= atr_pct <= 6.0:
        atr_score = 5
    elif atr_pct < 2.0:
        atr_score = atr_pct  # linear below 2%
    else:
        atr_score = max(0, 5 - (atr_pct - 6.0) * 0.5)  # penalise extreme volatility

    dollar_volume = row["close"] * row["volume"]
    liquidity_score = min(dollar_volume / 10_000_000, 5)

    total_score = vol_score + atr_score + liquidity_score

    log.debug(
        f"{symbol}: score={total_score:.2f} "
        f"(vol_ratio={vol_ratio:.2f}x, atr={atr_pct:.1f}%, "
        f"dollar_vol=${dollar_volume/1e6:.0f}M, close=${row['close']:.2f})"
    )

    return {
        "symbol": symbol,
        "score": float(round(total_score, 2)),
        "vol_ratio": float(round(vol_ratio, 2)),
        "atr_pct": float(round(atr_pct, 2)),
        "dollar_volume": int(dollar_volume),
        "close": float(round(row["close"], 2)),
        "prior_close": float(round(row["close"], 2)),  # used by gap filter
    }


def run_daily_watchlist() -> list:
    """
    Stage 1: Score universe and output top 25 to watchlist.json.
    Called at 8:00 AM daily.
    """
    log.info("=" * 60)
    log.info("WATCHLIST AGENT — STAGE 1: DAILY SCAN")
    log.info("=" * 60)

    universe = load_universe()
    log.info(f"Universe loaded: {len(universe)} stocks")

    bars_dict = fetch_daily_bars(universe)

    log.info(f"Scoring {len(universe)} stocks...")
    scores = []
    skipped = 0

    for symbol in universe:
        try:
            if isinstance(bars_dict, pd.DataFrame):
                if symbol in bars_dict.index.get_level_values(0):
                    df = bars_dict.xs(symbol, level=0)
                else:
                    log.debug(f"{symbol}: no bar data returned")
                    skipped += 1
                    continue
            else:
                df = bars_dict.get(symbol)
                if df is None:
                    skipped += 1
                    continue

            score_result = score_stock_daily(symbol, df)
            if score_result["score"] > 0:
                scores.append(score_result)
            else:
                skipped += 1

        except Exception as e:
            log.warning(f"{symbol}: scoring error — {e}")
            skipped += 1
            continue

    log.info(f"Scoring complete: {len(scores)} scored, {skipped} skipped")

    scores.sort(key=lambda x: x["score"], reverse=True)
    watchlist = scores[:config.WATCHLIST_SIZE]

    log.info(f"Top {len(watchlist)} stocks selected:")
    for i, s in enumerate(watchlist, 1):
        log.info(
            f"  {i:2}. {s['symbol']:<6} score={s['score']:5.2f}  "
            f"vol={s['vol_ratio']}x  atr={s['atr_pct']}%  close=${s['close']}"
        )

    output = {
        "generated_at": datetime.now().isoformat(),
        "watchlist": watchlist,
        "total_scanned": len(universe),
    }

    with open(config.WATCHLIST_PATH, "w") as f:
        json.dump(output, f, indent=2, cls=_NumpyEncoder)

    log.info(f"Watchlist saved to {config.WATCHLIST_PATH}")
    log.info("WATCHLIST AGENT — STAGE 1 COMPLETE")
    return watchlist


# ---------------------------------------------------------------------------
# Stage 2: Pre-market gap filter (9:15 AM — quote-based, no pre-market bars)
# ---------------------------------------------------------------------------

def fetch_latest_quotes(symbols: list) -> dict:
    """
    Fetch latest quote for each symbol using the quote API.
    Works on Alpaca Basic (free) plan.
    Returns {symbol: latest_price}
    """
    if not symbols:
        log.debug("fetch_latest_quotes called with empty symbol list — skipping")
        return {}

    client = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    try:
        request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = client.get_stock_latest_quote(request)
        result = {}
        for symbol, quote in quotes.items():
            # Use mid-price of bid/ask, fall back to ask price
            bid = float(quote.bid_price) if quote.bid_price else 0
            ask = float(quote.ask_price) if quote.ask_price else 0
            if bid > 0 and ask > 0:
                result[symbol] = (bid + ask) / 2
            elif ask > 0:
                result[symbol] = ask
            elif bid > 0:
                result[symbol] = bid
        log.debug(f"Quotes fetched for {len(result)}/{len(symbols)} symbols")
        return result
    except Exception as e:
        log.warning(f"Quote fetch failed: {e}")
        return {}


def run_gap_filter() -> list:
    """
    Stage 2a: Gap filter at 9:15 AM.
    Compares latest quote to prior close from watchlist.json.
    Keeps stocks with gap > MIN_GAP_PCT.
    Writes preliminary intraday_watchlist.json (will be refined at 9:35 AM).
    """
    log.info("=" * 60)
    log.info("WATCHLIST AGENT — STAGE 2a: GAP FILTER (9:15 AM)")
    log.info("=" * 60)

    try:
        with open(config.WATCHLIST_PATH) as f:
            data = json.load(f)
        watchlist = data["watchlist"]
    except FileNotFoundError:
        log.error("watchlist.json not found — run daily watchlist first")
        return []

    symbols = [s["symbol"] for s in watchlist]
    prior_closes = {s["symbol"]: s["prior_close"] for s in watchlist}

    if not symbols:
        log.warning("Watchlist is empty — skipping gap filter. Run daily watchlist scan first.")
        _save_intraday_watchlist([], stage="gap_filter_skipped_empty_watchlist")
        return []

    log.info(f"Checking gaps for {len(symbols)} symbols...")
    quotes = fetch_latest_quotes(symbols)

    gappers = []
    for stock in watchlist:
        symbol = stock["symbol"]
        prior_close = prior_closes.get(symbol, 0)
        current_price = quotes.get(symbol, 0)

        if prior_close <= 0 or current_price <= 0:
            log.debug(f"{symbol}: missing price data — skipping")
            continue

        gap_pct = ((current_price - prior_close) / prior_close) * 100

        log.debug(f"{symbol}: prior=${prior_close:.2f} current=${current_price:.2f} gap={gap_pct:+.2f}%")

        if abs(gap_pct) >= config.MIN_GAP_PCT:
            gappers.append({
                **stock,
                "current_price": round(current_price, 2),
                "gap_pct": round(gap_pct, 2),
                "gap_filter_passed": True,
                "volume_filter_passed": False,  # will be set at 9:35 AM
            })
            log.info(f"{symbol}: GAP PASSED — {gap_pct:+.2f}% (prior=${prior_close:.2f})")
        else:
            log.debug(f"{symbol}: gap {gap_pct:+.2f}% below threshold {config.MIN_GAP_PCT}%")

    log.info(f"Gap filter: {len(gappers)}/{len(symbols)} passed (gap >= {config.MIN_GAP_PCT}%)")

    # Write preliminary intraday watchlist — volume confirm will update it
    _save_intraday_watchlist(gappers, stage="gap_filter_only")

    log.info("WATCHLIST AGENT — STAGE 2a COMPLETE")
    return gappers


# ---------------------------------------------------------------------------
# Stage 2b: Volume confirmation (9:35 AM — first 5-min bar)
# ---------------------------------------------------------------------------

def fetch_first_5min_bars(symbols: list) -> dict:
    """
    Fetch the first completed 5-min bar of the session (9:30–9:35 AM).
    Also fetches 10 days of 5-min bars to compute the 20-bar volume average
    for the 9:30 AM slot.
    """
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

        log.debug(f"5-min bar fetch: got data for {len(result)}/{len(symbols)} symbols")
        return result

    except Exception as e:
        log.warning(f"5-min bar fetch failed: {e}")
        return {}


def compute_opening_volume_ratio(df: pd.DataFrame) -> float:
    """
    Compare today's first 5-min bar volume to the 20-day average volume
    of the 9:30 AM bar. Returns the ratio.
    """
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return 1.0

    df_et = df.copy()
    if df_et.index.tzinfo is None:
        df_et.index = df_et.index.tz_localize("UTC").tz_convert(ET)
    else:
        df_et.index = df_et.index.tz_convert(ET)

    # Filter to 9:30 AM bars only
    opening_bars = df_et[
        (df_et.index.hour == 9) & (df_et.index.minute == 30)
    ]

    if len(opening_bars) < 2:
        return 1.0

    # Historical average of 9:30 AM bar volume (exclude today)
    hist_avg = opening_bars["volume"].iloc[:-1].mean()
    today_vol = opening_bars["volume"].iloc[-1]

    if hist_avg <= 0:
        return 1.0

    return round(today_vol / hist_avg, 2)


def run_volume_confirm() -> list:
    """
    Stage 2b: Volume confirmation at 9:35 AM.
    Reads preliminary intraday_watchlist.json, checks first 5-min bar volume.
    Updates intraday_watchlist.json with final confirmed candidates.
    """
    log.info("=" * 60)
    log.info("WATCHLIST AGENT — STAGE 2b: VOLUME CONFIRM (9:35 AM)")
    log.info("=" * 60)

    try:
        with open(config.INTRADAY_WATCHLIST_PATH) as f:
            data = json.load(f)
        candidates = data.get("stocks", [])
    except FileNotFoundError:
        log.warning("intraday_watchlist.json not found — running gap filter first")
        candidates = run_gap_filter()

    if not candidates:
        log.info("No gap-filter candidates to check volume for")
        _save_intraday_watchlist([], stage="volume_confirmed")
        return []

    symbols = [s["symbol"] for s in candidates]
    log.info(f"Checking opening volume for {len(symbols)} gap candidates...")

    bars_by_symbol = fetch_first_5min_bars(symbols)

    confirmed = []
    for stock in candidates:
        symbol = stock["symbol"]
        df = bars_by_symbol.get(symbol)

        if df is None or df.empty:
            log.debug(f"{symbol}: no 5-min bar data — keeping from gap filter")
            # Keep it anyway — gap alone is enough signal
            confirmed.append({**stock, "volume_filter_passed": True, "open_vol_ratio": None})
            continue

        open_vol_ratio = compute_opening_volume_ratio(df)
        log.debug(f"{symbol}: opening vol ratio = {open_vol_ratio:.2f}x")

        if open_vol_ratio >= config.MIN_RELATIVE_VOLUME:
            log.info(
                f"{symbol}: VOLUME CONFIRMED — {open_vol_ratio:.2f}x "
                f"(gap={stock.get('gap_pct', 0):+.2f}%)"
            )
            confirmed.append({
                **stock,
                "volume_filter_passed": True,
                "open_vol_ratio": open_vol_ratio,
            })
        else:
            log.info(
                f"{symbol}: volume weak ({open_vol_ratio:.2f}x < {config.MIN_RELATIVE_VOLUME}x) "
                f"— keeping (gap={stock.get('gap_pct', 0):+.2f}%)"
            )
            # Keep stocks that passed gap filter even if volume is weak —
            # the strategy agent will score them and they may still qualify
            confirmed.append({
                **stock,
                "volume_filter_passed": open_vol_ratio >= config.MIN_RELATIVE_VOLUME,
                "open_vol_ratio": open_vol_ratio,
            })

    # Sort: volume-confirmed first, then by gap size
    confirmed.sort(key=lambda x: (
        -int(x.get("volume_filter_passed", False)),
        -abs(x.get("gap_pct", 0))
    ))

    log.info(
        f"Volume confirm complete: "
        f"{sum(1 for s in confirmed if s.get('volume_filter_passed'))} strong, "
        f"{len(confirmed)} total in intraday watchlist"
    )

    _save_intraday_watchlist(confirmed, stage="volume_confirmed")
    log.info("WATCHLIST AGENT — STAGE 2b COMPLETE")
    return confirmed


def _save_intraday_watchlist(stocks: list, stage: str = ""):
    output = {
        "generated_at": datetime.now().isoformat(),
        "stage": stage,
        "count": len(stocks),
        "stocks": stocks,
    }
    with open(config.INTRADAY_WATCHLIST_PATH, "w") as f:
        json.dump(output, f, indent=2, cls=_NumpyEncoder)
    log.info(f"Intraday watchlist saved: {len(stocks)} stocks → {config.INTRADAY_WATCHLIST_PATH}")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run():
    """
    Default run() — called by main.py morning sequence.
    Runs Stage 1 (daily watchlist scoring).
    Stage 2 (gap + volume filter) is scheduled separately.
    """
    return run_daily_watchlist()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "gap":
        run_gap_filter()
    elif len(sys.argv) > 1 and sys.argv[1] == "volume":
        run_volume_confirm()
    else:
        run_daily_watchlist()
