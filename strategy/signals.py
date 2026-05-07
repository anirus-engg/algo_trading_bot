"""
Pure signal detection functions. No side effects, no I/O.
All functions take a pandas DataFrame of OHLCV daily bars.
"""
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Trend & momentum indicators
# ---------------------------------------------------------------------------

def compute_emas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
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


def compute_macd(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=period - 1, adjust=False).mean()
    return df


def compute_roc(df: pd.DataFrame, period: int = 10) -> pd.DataFrame:
    df = df.copy()
    df["roc"] = df["close"].pct_change(periods=period) * 100
    return df


def compute_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Approximate daily VWAP from OHLCV bars."""
    df = df.copy()
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
    return df


def compute_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["vol_avg"] = df["volume"].rolling(period).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg"]
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = compute_emas(df)
    df = compute_rsi(df)
    df = compute_macd(df)
    df = compute_atr(df)
    df = compute_roc(df)
    df = compute_vwap(df)
    df = compute_volume_ratio(df)
    return df


# ---------------------------------------------------------------------------
# Pattern detection (operates on last few candles)
# ---------------------------------------------------------------------------

def is_bullish_engulfing(df: pd.DataFrame) -> bool:
    """Last candle engulfs the previous bearish candle."""
    if len(df) < 2:
        return False
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    prev_bearish = prev["close"] < prev["open"]
    curr_bullish = curr["close"] > curr["open"]
    engulfs = curr["open"] <= prev["close"] and curr["close"] >= prev["open"]
    return bool(prev_bearish and curr_bullish and engulfs)


def is_inside_bar_breakout(df: pd.DataFrame) -> bool:
    """Current bar breaks above the high of an inside bar."""
    if len(df) < 3:
        return False
    two_back = df.iloc[-3]
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    inside = prev["high"] < two_back["high"] and prev["low"] > two_back["low"]
    breakout = curr["close"] > two_back["high"]
    return bool(inside and breakout)


def is_higher_highs_higher_lows(df: pd.DataFrame, lookback: int = 5) -> bool:
    """Recent swing structure shows HH/HL."""
    if len(df) < lookback:
        return False
    recent = df.tail(lookback)
    highs = recent["high"].values
    lows = recent["low"].values
    hh = all(highs[i] >= highs[i - 1] for i in range(1, len(highs)))
    hl = all(lows[i] >= lows[i - 1] for i in range(1, len(lows)))
    return bool(hh and hl)


def is_morning_star(df: pd.DataFrame) -> bool:
    """
    Morning Star (3-candle reversal):
    1. Large bearish candle
    2. Small-bodied candle (star) that gaps down — indecision
    3. Large bullish candle that closes into the body of candle 1
    """
    if len(df) < 3:
        return False
    c1 = df.iloc[-3]  # large bearish
    c2 = df.iloc[-2]  # small star
    c3 = df.iloc[-1]  # large bullish

    c1_bearish = c1["close"] < c1["open"]
    c1_body = abs(c1["open"] - c1["close"])

    c2_body = abs(c2["open"] - c2["close"])
    c2_small = c2_body < c1_body * 0.3  # star body is small relative to c1

    c3_bullish = c3["close"] > c3["open"]
    c3_body = abs(c3["open"] - c3["close"])
    c3_recovers = c3["close"] >= c1["open"] + (c1["close"] - c1["open"]) * 0.5  # closes into c1 body

    return bool(c1_bearish and c2_small and c3_bullish and c3_recovers and c3_body > c1_body * 0.5)


def is_three_white_soldiers(df: pd.DataFrame) -> bool:
    """
    Three White Soldiers (3-candle continuation/reversal):
    - Three consecutive bullish candles
    - Each opens within the prior candle's body
    - Each closes higher than the prior close
    - Each has a relatively small upper wick (not exhaustion)
    """
    if len(df) < 3:
        return False
    c1 = df.iloc[-3]
    c2 = df.iloc[-2]
    c3 = df.iloc[-1]

    # All three bullish
    if not (c1["close"] > c1["open"] and
            c2["close"] > c2["open"] and
            c3["close"] > c3["open"]):
        return False

    # Each opens within prior body
    c2_opens_in_c1 = c1["open"] <= c2["open"] <= c1["close"]
    c3_opens_in_c2 = c2["open"] <= c3["open"] <= c2["close"]

    # Each closes higher
    ascending = c2["close"] > c1["close"] and c3["close"] > c2["close"]

    # Upper wicks not too long (< 25% of body) — avoids exhaustion candles
    def wick_ok(c):
        body = c["close"] - c["open"]
        upper_wick = c["high"] - c["close"]
        return body > 0 and upper_wick < body * 0.25

    return bool(c2_opens_in_c1 and c3_opens_in_c2 and ascending and
                wick_ok(c1) and wick_ok(c2) and wick_ok(c3))


def detect_pattern(df: pd.DataFrame) -> str:
    """Returns the strongest pattern detected, or 'none'."""
    if is_morning_star(df):
        return "morning_star"
    if is_three_white_soldiers(df):
        return "three_white_soldiers"
    if is_bullish_engulfing(df):
        return "bullish_engulfing"
    if is_inside_bar_breakout(df):
        return "inside_bar_breakout"
    if is_higher_highs_higher_lows(df):
        return "higher_highs_higher_lows"
    return "none"


# ---------------------------------------------------------------------------
# Composite signal scoring
# ---------------------------------------------------------------------------

def score_setup(df: pd.DataFrame, news_sentiment: str = "neutral") -> dict:
    """
    Score a swing trade setup. Returns a dict with score and all signal values.
    Minimum score of 5 required to qualify as a trade candidate.

    Scoring:
      RSI 40-55 turning up          +2  (required zone for pullback entry)
      MACD histogram turning pos    +2
      ROC > 5%                      +1
      Price above VWAP              +1
      Bullish candle pattern        +2
      Volume above avg on signal    +1
      Positive news sentiment       +1
      HH/HL structure               +1
    """
    if len(df) < 52:  # need enough bars for 50 EMA
        return {"score": 0, "qualified": False, "reason": "insufficient_bars"}

    row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # --- Hard requirements (disqualify if not met) ---
    uptrend = row["ema20"] > row["ema50"]
    if not uptrend:
        return {"score": 0, "qualified": False, "reason": "no_uptrend"}

    # Price near 20 EMA (within 2%)
    ema_distance_pct = abs(row["close"] - row["ema20"]) / row["ema20"] * 100
    near_ema = ema_distance_pct <= 2.0
    if not near_ema:
        return {"score": 0, "qualified": False, "reason": "price_not_near_ema20",
                "ema_distance_pct": round(ema_distance_pct, 2)}

    score = 0
    signals = {}

    # RSI in pullback zone and turning up
    rsi = row["rsi"]
    prev_rsi = prev_row["rsi"]
    rsi_in_zone = 40 <= rsi <= 55
    rsi_turning_up = rsi > prev_rsi
    if rsi_in_zone and rsi_turning_up:
        score += 2
        signals["rsi"] = {"value": round(rsi, 1), "signal": "pullback_zone_turning_up", "points": 2}
    else:
        signals["rsi"] = {"value": round(rsi, 1), "signal": "neutral", "points": 0}

    # MACD histogram turning positive
    macd_hist = row["macd_hist"]
    prev_macd_hist = prev_row["macd_hist"]
    macd_turning = macd_hist > prev_macd_hist and macd_hist > -0.5
    if macd_turning:
        score += 2
        signals["macd"] = {"histogram": round(macd_hist, 4), "signal": "turning_positive", "points": 2}
    else:
        signals["macd"] = {"histogram": round(macd_hist, 4), "signal": "neutral", "points": 0}

    # ROC momentum
    roc = row.get("roc", 0)
    if roc and roc > 5:
        score += 1
        signals["roc"] = {"value": round(roc, 2), "signal": "strong_momentum", "points": 1}
    else:
        signals["roc"] = {"value": round(roc, 2) if roc else 0, "signal": "weak", "points": 0}

    # Price vs VWAP
    above_vwap = row["close"] > row["vwap"]
    if above_vwap:
        score += 1
        signals["vwap"] = {"signal": "above", "points": 1}
    else:
        signals["vwap"] = {"signal": "below", "points": 0}

    # Pattern
    pattern = detect_pattern(df)
    if pattern in ("bullish_engulfing", "inside_bar_breakout", "morning_star", "three_white_soldiers"):
        score += 2
        signals["pattern"] = {"detected": pattern, "points": 2}
    elif pattern == "higher_highs_higher_lows":
        score += 1
        signals["pattern"] = {"detected": pattern, "points": 1}
    else:
        signals["pattern"] = {"detected": "none", "points": 0}

    # Volume confirmation
    vol_ratio = row.get("vol_ratio", 1.0)
    if vol_ratio and vol_ratio > 1.2:
        score += 1
        signals["volume"] = {"ratio": round(vol_ratio, 2), "signal": "above_avg", "points": 1}
    else:
        signals["volume"] = {"ratio": round(vol_ratio, 2) if vol_ratio else 1.0, "signal": "below_avg", "points": 0}

    # News sentiment
    if news_sentiment == "positive":
        score += 1
        signals["news"] = {"sentiment": "positive", "points": 1}
    else:
        signals["news"] = {"sentiment": news_sentiment, "points": 0}

    # HH/HL structure
    if is_higher_highs_higher_lows(df):
        score += 1
        signals["structure"] = {"signal": "hh_hl", "points": 1}
    else:
        signals["structure"] = {"signal": "neutral", "points": 0}

    return {
        "score": score,
        "qualified": score >= 5,
        "signals": signals,
        "close": round(row["close"], 2),
        "ema20": round(row["ema20"], 2),
        "ema50": round(row["ema50"], 2),
        "atr": round(row["atr"], 2),
        "rsi": round(rsi, 1),
        "pattern": pattern,
        "ema_distance_pct": round(ema_distance_pct, 2),
    }


# ---------------------------------------------------------------------------
# Entry / exit price calculation
# ---------------------------------------------------------------------------

def calculate_entry_levels(score_result: dict, max_position_size: float = 5000.0) -> dict:
    """Calculate entry, stop, target, and position size."""
    close = score_result["close"]
    atr = score_result["atr"]
    ema20 = score_result["ema20"]

    # Stop below the pullback low (1x ATR below EMA20)
    stop_loss = round(ema20 - atr, 2)
    risk_per_share = round(close - stop_loss, 2)

    if risk_per_share <= 0:
        return {}

    # Take profit at 2x risk
    take_profit = round(close + (2 * risk_per_share), 2)

    # Trailing stop activates at 1x risk, trails by 1x ATR
    trailing_stop_activation = round(close + risk_per_share, 2)

    # Position sizing: risk 1% of max position or max_position_size shares
    shares = int(min(max_position_size / close, max_position_size / close))
    # Cap by max position size
    shares = min(shares, int(max_position_size / close))
    notional = round(shares * close, 2)

    return {
        "entry": close,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_per_share": risk_per_share,
        "trailing_stop_activation_price": trailing_stop_activation,
        "shares": shares,
        "notional": notional,
    }


# ---------------------------------------------------------------------------
# Exit signal detection (for open positions)
# ---------------------------------------------------------------------------

def should_exit(df: pd.DataFrame, position: dict) -> dict:
    """
    Check if an open position should be exited.
    Returns {"exit": bool, "reason": str}
    Never triggers same-day exit (caller enforces entry_date check).
    """
    if len(df) < 2:
        return {"exit": False, "reason": "insufficient_data"}

    row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # Bearish engulfing
    prev_bullish = prev_row["close"] > prev_row["open"]
    curr_bearish = row["close"] < row["open"]
    engulfs_down = (row["open"] >= prev_row["close"] and row["close"] <= prev_row["open"])
    if prev_bullish and curr_bearish and engulfs_down:
        return {"exit": True, "reason": "bearish_engulfing"}

    # Close below 20 EMA
    if row["close"] < row["ema20"]:
        return {"exit": True, "reason": "close_below_ema20"}

    # RSI overbought + MACD declining
    rsi = row.get("rsi", 50)
    macd_hist = row.get("macd_hist", 0)
    prev_macd_hist = prev_row.get("macd_hist", 0)
    if rsi > 72 and macd_hist < prev_macd_hist:
        return {"exit": True, "reason": "rsi_overbought_macd_declining"}

    return {"exit": False, "reason": "hold"}
