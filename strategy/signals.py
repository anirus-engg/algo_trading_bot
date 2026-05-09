"""
Pure signal detection functions for intraday (5-min) day trading.
No side effects, no I/O. All functions take a pandas DataFrame of OHLCV bars.

Strategy: VWAP Reclaim
  - Price dips below VWAP then closes back above it
  - EMA9 > EMA20 (intraday uptrend intact)
  - RSI < 70 (not overbought / exhausted)
  - Reclaim candle volume > 20-bar average (conviction)
"""
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Intraday indicators (5-min bars)
# ---------------------------------------------------------------------------

def compute_emas(df: pd.DataFrame, fast: int = 9, slow: int = 20) -> pd.DataFrame:
    """EMA9 and EMA20 for intraday trend direction."""
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    return df


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average True Range — used for stop sizing."""
    df = df.copy()
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=period - 1, adjust=False).mean()
    return df


def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Session VWAP — resets each trading day.
    Requires a DatetimeIndex. Falls back to cumulative VWAP if date info unavailable.
    """
    df = df.copy()

    if isinstance(df.index, pd.DatetimeIndex):
        df["date"] = df.index.date
        df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
        df["tp_vol"] = df["typical_price"] * df["volume"]

        # Cumulative sums reset per day
        df["cum_tp_vol"] = df.groupby("date")["tp_vol"].cumsum()
        df["cum_vol"] = df.groupby("date")["volume"].cumsum()
        df["vwap"] = df["cum_tp_vol"] / df["cum_vol"]

        df.drop(columns=["date", "typical_price", "tp_vol", "cum_tp_vol", "cum_vol"],
                inplace=True)
    else:
        # Fallback: cumulative VWAP across all bars
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()

    return df


def compute_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Volume ratio vs rolling average — measures relative activity."""
    df = df.copy()
    df["vol_avg"] = df["volume"].rolling(period).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg"].replace(0, np.nan)
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all intraday indicators to a 5-min bar DataFrame."""
    df = compute_emas(df)
    df = compute_rsi(df)
    df = compute_atr(df)
    df = compute_vwap(df)
    df = compute_volume_ratio(df)
    return df


# ---------------------------------------------------------------------------
# VWAP Reclaim pattern detection
# ---------------------------------------------------------------------------

def detect_vwap_reclaim(df: pd.DataFrame) -> dict:
    """
    Detect a VWAP reclaim setup on the most recent candle.

    Conditions:
      1. Previous candle closed BELOW VWAP (the dip)
      2. Current candle closes ABOVE VWAP (the reclaim)
      3. Current candle is bullish (close > open)

    Returns dict with detected flag and details.
    """
    if len(df) < 3:
        return {"detected": False, "reason": "insufficient_bars"}

    curr = df.iloc[-1]
    prev = df.iloc[-2]

    prev_below_vwap = prev["close"] < prev["vwap"]
    curr_above_vwap = curr["close"] > curr["vwap"]
    curr_bullish = curr["close"] > curr["open"]

    if prev_below_vwap and curr_above_vwap and curr_bullish:
        vwap_reclaim_size = curr["close"] - curr["vwap"]
        return {
            "detected": True,
            "vwap": round(curr["vwap"], 2),
            "close": round(curr["close"], 2),
            "reclaim_size": round(vwap_reclaim_size, 2),
            "prev_close": round(prev["close"], 2),
        }

    reason = []
    if not prev_below_vwap:
        reason.append("prev_not_below_vwap")
    if not curr_above_vwap:
        reason.append("curr_not_above_vwap")
    if not curr_bullish:
        reason.append("curr_not_bullish")

    return {"detected": False, "reason": "+".join(reason)}


# ---------------------------------------------------------------------------
# Composite intraday signal scoring
# ---------------------------------------------------------------------------

def score_intraday_setup(df: pd.DataFrame, news_sentiment: str = "neutral") -> dict:
    """
    Score a VWAP reclaim day trading setup on 5-min bars.
    Returns a dict with score, qualified flag, and all signal values.

    Minimum score of 4 required to qualify.

    Scoring:
      VWAP reclaim (prev below, curr above, bullish candle)  +3  [required]
      EMA9 > EMA20 (intraday uptrend)                        +2
      RSI 40–68 (not overbought, has room to run)            +1
      Volume on reclaim candle > 20-bar avg                  +2
      Positive news sentiment                                +1
      -------------------------------------------------------
      Max score: 9
      Minimum to qualify: 4
    """
    min_bars = 25  # need enough bars for EMA20 + volume avg
    if len(df) < min_bars:
        return {"score": 0, "qualified": False, "reason": "insufficient_bars"}

    # Ensure indicators are computed
    if "vwap" not in df.columns:
        df = add_all_indicators(df)

    row = df.iloc[-1]

    # --- Hard requirement: VWAP reclaim must be present ---
    reclaim = detect_vwap_reclaim(df)
    if not reclaim["detected"]:
        return {
            "score": 0,
            "qualified": False,
            "reason": f"no_vwap_reclaim:{reclaim.get('reason', '')}",
        }

    score = 3  # base score for the reclaim itself
    signals = {
        "vwap_reclaim": {
            "vwap": reclaim["vwap"],
            "close": reclaim["close"],
            "reclaim_size": reclaim["reclaim_size"],
            "points": 3,
        }
    }

    # EMA9 > EMA20 — intraday trend is up
    ema_uptrend = row["ema_fast"] > row["ema_slow"]
    if ema_uptrend:
        score += 2
        signals["ema_trend"] = {
            "ema9": round(row["ema_fast"], 2),
            "ema20": round(row["ema_slow"], 2),
            "signal": "uptrend",
            "points": 2,
        }
    else:
        signals["ema_trend"] = {
            "ema9": round(row["ema_fast"], 2),
            "ema20": round(row["ema_slow"], 2),
            "signal": "downtrend",
            "points": 0,
        }

    # RSI in healthy range — not overbought
    rsi = row["rsi"]
    rsi_ok = 40 <= rsi <= 68
    if rsi_ok:
        score += 1
        signals["rsi"] = {"value": round(rsi, 1), "signal": "healthy_range", "points": 1}
    else:
        signals["rsi"] = {
            "value": round(rsi, 1),
            "signal": "overbought" if rsi > 68 else "oversold",
            "points": 0,
        }

    # Volume confirmation on reclaim candle
    vol_ratio = row.get("vol_ratio", 1.0)
    if pd.isna(vol_ratio):
        vol_ratio = 1.0
    if vol_ratio >= 1.5:
        score += 2
        signals["volume"] = {
            "ratio": round(vol_ratio, 2),
            "signal": "strong_confirmation",
            "points": 2,
        }
    elif vol_ratio >= 1.0:
        score += 1
        signals["volume"] = {
            "ratio": round(vol_ratio, 2),
            "signal": "above_avg",
            "points": 1,
        }
    else:
        signals["volume"] = {
            "ratio": round(vol_ratio, 2),
            "signal": "weak",
            "points": 0,
        }

    # News sentiment bonus
    if news_sentiment == "positive":
        score += 1
        signals["news"] = {"sentiment": "positive", "points": 1}
    else:
        signals["news"] = {"sentiment": news_sentiment, "points": 0}

    return {
        "score": score,
        "qualified": score >= 4,
        "signals": signals,
        "close": round(row["close"], 2),
        "vwap": round(row["vwap"], 2),
        "ema_fast": round(row["ema_fast"], 2),
        "ema_slow": round(row["ema_slow"], 2),
        "atr": round(row["atr"], 4),
        "rsi": round(rsi, 1),
        "vol_ratio": round(vol_ratio, 2),
    }


# ---------------------------------------------------------------------------
# Entry / exit price calculation
# ---------------------------------------------------------------------------

def calculate_entry_levels(score_result: dict, max_position_size: float = 5000.0) -> dict:
    """
    Calculate intraday entry, stop, target, and position size.

    Stop: 0.5x ATR below the entry candle low (tight intraday stop)
    Target: 1.5:1 R:R
    """
    close = score_result["close"]
    atr = score_result["atr"]

    # Stop below entry candle low — use 0.5x ATR as buffer
    stop_loss = round(close - (0.5 * atr), 2)
    risk_per_share = round(close - stop_loss, 2)

    if risk_per_share <= 0:
        return {}

    # 1.5:1 reward:risk
    take_profit = round(close + (1.5 * risk_per_share), 2)

    # Position sizing: max notional / entry price, capped at max_position_size
    shares = int(max_position_size / close)
    shares = max(shares, 1)
    notional = round(shares * close, 2)

    return {
        "entry": close,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_per_share": risk_per_share,
        "shares": shares,
        "notional": notional,
    }


# ---------------------------------------------------------------------------
# Intraday exit signal detection
# ---------------------------------------------------------------------------

def should_exit_intraday(df: pd.DataFrame, position: dict) -> dict:
    """
    Check if an open intraday position should be exited early (before force close).

    Exit conditions:
      1. Price closes below VWAP — setup invalidated
      2. EMA9 crosses below EMA20 — intraday trend reversed
      3. RSI > 75 and declining — momentum exhaustion

    Force close at 3:50 PM is handled separately by the execution agent.
    Returns {"exit": bool, "reason": str}
    """
    if len(df) < 3:
        return {"exit": False, "reason": "insufficient_data"}

    if "vwap" not in df.columns:
        df = add_all_indicators(df)

    row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # Close below VWAP — setup invalidated
    if row["close"] < row["vwap"]:
        return {"exit": True, "reason": "close_below_vwap"}

    # EMA9 crossed below EMA20 — intraday trend reversed
    ema_was_up = prev_row["ema_fast"] > prev_row["ema_slow"]
    ema_now_down = row["ema_fast"] < row["ema_slow"]
    if ema_was_up and ema_now_down:
        return {"exit": True, "reason": "ema_cross_bearish"}

    # RSI overbought and declining — momentum exhaustion
    rsi = row.get("rsi", 50)
    prev_rsi = prev_row.get("rsi", 50)
    if rsi > 75 and rsi < prev_rsi:
        return {"exit": True, "reason": "rsi_exhaustion"}

    return {"exit": False, "reason": "hold"}


# ---------------------------------------------------------------------------
# Daily bar helpers (used by universe/watchlist agents)
# ---------------------------------------------------------------------------

def compute_atr_daily(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ATR on daily bars — used for universe filtering and watchlist scoring."""
    return compute_atr(df, period)


def compute_volume_ratio_daily(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Volume ratio on daily bars — used for watchlist scoring."""
    return compute_volume_ratio(df, period)
