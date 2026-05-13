"""
Pure signal detection functions for intraday (5-min) day trading.
No side effects, no I/O. All functions take a pandas DataFrame of OHLCV bars.

Strategies:
  1. VWAP Reclaim
     - Price dips below VWAP then closes back above it
     - EMA9 > EMA20 (intraday uptrend intact)
     - RSI < 70 (not overbought)
     - Reclaim candle volume > 20-bar average (conviction)

  2. ORB Breakout (Opening Range Breakout)
     - Opening range = high/low of first 3 x 5-min bars (9:30–9:45 AM)
     - Entry: current candle closes above the opening range high
     - EMA9 > EMA20 (trend filter)
     - Volume on breakout candle > 1.5x average
     - Only valid 9:45 AM – 1:00 PM (goes stale in afternoon)
"""
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo
import config

ET = ZoneInfo("America/New_York")


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
        "setup_type": "vwap_reclaim",
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
# ORB — Opening Range Breakout
# ---------------------------------------------------------------------------

def compute_opening_range(df: pd.DataFrame, range_bars: int = 3) -> dict:
    """
    Compute the opening range from the first N 5-min bars of today's session.
    Default: 3 bars = 9:30–9:45 AM ET.

    Returns {"high": float, "low": float, "formed": bool}
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        return {"high": None, "low": None, "formed": False}

    df_et = df.copy()
    if df_et.index.tzinfo is None:
        df_et.index = df_et.index.tz_localize("UTC").tz_convert(ET)
    else:
        df_et.index = df_et.index.tz_convert(ET)

    today = df_et.index[-1].date()
    today_bars = df_et[df_et.index.date == today]

    if len(today_bars) < range_bars:
        return {"high": None, "low": None, "formed": False}

    opening_bars = today_bars.iloc[:range_bars]
    orb_high = float(opening_bars["high"].max())
    orb_low = float(opening_bars["low"].min())

    return {
        "high": round(orb_high, 2),
        "low": round(orb_low, 2),
        "formed": True,
        "range_bars": range_bars,
        "range_size": round(orb_high - orb_low, 2),
    }


def detect_orb_breakout(df: pd.DataFrame, range_bars: int = 3) -> dict:
    """
    Detect an Opening Range Breakout on the most recent candle.

    Conditions:
      1. Opening range is fully formed (at least range_bars bars today)
      2. Current candle closes ABOVE the opening range high
      3. Current candle is bullish (close > open)
      4. We are past the opening range window (bar index > range_bars)
      5. Only valid until 1:00 PM ET (ORB setups go stale in afternoon)

    Returns dict with detected flag and details.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        return {"detected": False, "reason": "no_datetime_index"}

    df_et = df.copy()
    if df_et.index.tzinfo is None:
        df_et.index = df_et.index.tz_localize("UTC").tz_convert(ET)
    else:
        df_et.index = df_et.index.tz_convert(ET)

    today = df_et.index[-1].date()
    today_bars = df_et[df_et.index.date == today]

    # Need at least range_bars + 1 bars (range + at least one breakout candle)
    if len(today_bars) <= range_bars:
        return {"detected": False, "reason": "opening_range_not_formed"}

    # ORB only valid until 1:00 PM ET
    current_time = df_et.index[-1].time()
    from datetime import time as dtime
    if current_time >= dtime(13, 0):
        return {"detected": False, "reason": "past_orb_window_1pm"}

    orb = compute_opening_range(df, range_bars)
    if not orb["formed"]:
        return {"detected": False, "reason": "opening_range_not_formed"}

    curr = df_et.iloc[-1]
    curr_bullish = curr["close"] > curr["open"]
    breaks_above_orb = curr["close"] > orb["high"]

    if breaks_above_orb and curr_bullish:
        breakout_size = curr["close"] - orb["high"]
        return {
            "detected": True,
            "orb_high": orb["high"],
            "orb_low": orb["low"],
            "orb_range": orb["range_size"],
            "close": round(float(curr["close"]), 2),
            "breakout_size": round(breakout_size, 2),
        }

    reason = []
    if not breaks_above_orb:
        reason.append(f"close_{curr['close']:.2f}_below_orb_high_{orb['high']:.2f}")
    if not curr_bullish:
        reason.append("curr_not_bullish")

    return {"detected": False, "reason": "+".join(reason)}


def score_orb_setup(df: pd.DataFrame, news_sentiment: str = "neutral") -> dict:
    """
    Score an Opening Range Breakout setup on 5-min bars.
    Returns a dict with score, qualified flag, setup_type, and all signal values.

    Minimum score of 4 required to qualify.

    Scoring:
      ORB breakout (close above opening range high, bullish)  +3  [required]
      EMA9 > EMA20 (intraday uptrend)                         +2
      RSI 40–72 (momentum building, not exhausted)            +1
      Volume on breakout candle >= 1.5x avg                   +2
      Volume on breakout candle >= 1.0x avg                   +1
      Positive news sentiment                                  +1
      -------------------------------------------------------
      Max score: 9
      Minimum to qualify: 4
    """
    min_bars = 25
    if len(df) < min_bars:
        return {"score": 0, "qualified": False, "reason": "insufficient_bars",
                "setup_type": "orb"}

    if "vwap" not in df.columns:
        df = add_all_indicators(df)

    row = df.iloc[-1]

    # --- Hard requirement: ORB breakout must be present ---
    breakout = detect_orb_breakout(df)
    if not breakout["detected"]:
        return {
            "score": 0,
            "qualified": False,
            "reason": f"no_orb_breakout:{breakout.get('reason', '')}",
            "setup_type": "orb",
        }

    score = 3  # base score for the breakout itself
    signals = {
        "orb_breakout": {
            "orb_high": breakout["orb_high"],
            "orb_low": breakout["orb_low"],
            "orb_range": breakout["orb_range"],
            "close": breakout["close"],
            "breakout_size": breakout["breakout_size"],
            "points": 3,
        }
    }

    # EMA9 > EMA20 — intraday trend is up
    ema_uptrend = row["ema_fast"] > row["ema_slow"]
    if ema_uptrend:
        score += 2
        signals["ema_trend"] = {
            "ema9": round(float(row["ema_fast"]), 2),
            "ema20": round(float(row["ema_slow"]), 2),
            "signal": "uptrend",
            "points": 2,
        }
    else:
        signals["ema_trend"] = {
            "ema9": round(float(row["ema_fast"]), 2),
            "ema20": round(float(row["ema_slow"]), 2),
            "signal": "downtrend",
            "points": 0,
        }

    # RSI — allow slightly higher range for ORB (momentum breakouts can have higher RSI)
    rsi = float(row["rsi"])
    rsi_ok = 40 <= rsi <= 72
    if rsi_ok:
        score += 1
        signals["rsi"] = {"value": round(rsi, 1), "signal": "healthy_range", "points": 1}
    else:
        signals["rsi"] = {
            "value": round(rsi, 1),
            "signal": "overbought" if rsi > 72 else "oversold",
            "points": 0,
        }

    # Volume confirmation on breakout candle
    vol_ratio = row.get("vol_ratio", 1.0)
    if pd.isna(vol_ratio):
        vol_ratio = 1.0
    vol_ratio = float(vol_ratio)
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
        "setup_type": "orb",
        "signals": signals,
        "close": round(float(row["close"]), 2),
        "vwap": round(float(row["vwap"]), 2),
        "ema_fast": round(float(row["ema_fast"]), 2),
        "ema_slow": round(float(row["ema_slow"]), 2),
        "atr": round(float(row["atr"]), 4),
        "rsi": round(rsi, 1),
        "vol_ratio": round(vol_ratio, 2),
        "orb_high": breakout["orb_high"],
        "orb_low": breakout["orb_low"],
    }


# ---------------------------------------------------------------------------
# Entry / exit price calculation
# ---------------------------------------------------------------------------

def calculate_entry_levels(score_result: dict, max_position_size: float = 5000.0) -> dict:
    """
    Calculate intraday entry, stop, target, and position size.

    VWAP Reclaim: stop = 0.5x ATR below entry
    ORB Breakout: stop = below ORB low (natural invalidation level),
                  fallback to 0.5x ATR if ORB low not available
    Target: 1.5:1 R:R for both setups
    """
    close = score_result["close"]
    atr = score_result["atr"]
    setup_type = score_result.get("setup_type", "vwap_reclaim")

    if setup_type == "orb":
        orb_low = score_result.get("orb_low")
        if orb_low and orb_low < close:
            # Stop just below the ORB low — natural invalidation
            stop_loss = round(orb_low - (0.1 * atr), 2)
        else:
            stop_loss = round(close - (0.5 * atr), 2)
    else:
        # VWAP reclaim: tight stop 0.5x ATR below entry
        stop_loss = round(close - (0.5 * atr), 2)

    risk_per_share = round(close - stop_loss, 2)

    if risk_per_share <= 0:
        return {}

    # 1.5:1 reward:risk
    take_profit = round(close + (config.REWARD_RISK_RATIO * risk_per_share), 2)

    # Position sizing: max notional / entry price
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

    VWAP Reclaim exits:
      1. Price closes below VWAP — setup invalidated
      2. EMA9 crosses below EMA20 — intraday trend reversed
      3. RSI > 75 and declining — momentum exhaustion

    ORB Breakout exits:
      1. Price closes back below ORB high — breakout failed
      2. EMA9 crosses below EMA20 — trend reversed
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
    setup_type = position.get("setup_type", "vwap_reclaim")

    if setup_type == "orb":
        # ORB: exit if price closes back below the ORB high (breakout failed)
        orb_high = position.get("orb_high")
        if orb_high and row["close"] < orb_high:
            return {"exit": True, "reason": "close_below_orb_high"}
    else:
        # VWAP Reclaim: exit if price closes below VWAP
        if row["close"] < row["vwap"]:
            return {"exit": True, "reason": "close_below_vwap"}

    # Common exits for both setups
    # EMA9 crossed below EMA20 — intraday trend reversed
    ema_was_up = prev_row["ema_fast"] > prev_row["ema_slow"]
    ema_now_down = row["ema_fast"] < row["ema_slow"]
    if ema_was_up and ema_now_down:
        return {"exit": True, "reason": "ema_cross_bearish"}

    # RSI overbought and declining — momentum exhaustion
    rsi = float(row.get("rsi", 50))
    prev_rsi = float(prev_row.get("rsi", 50))
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
