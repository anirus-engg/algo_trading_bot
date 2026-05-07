"""
Watchlist Agent: Scans universe, scores stocks by volume/volatility/liquidity, outputs top 25.
Runs pre-market every morning and again at 4:30pm EOD.
"""
import json
import pandas as pd
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import config
from strategy.signals import compute_atr, compute_volume_ratio
from agents.universe_agent import load_universe
from logger import get_logger

log = get_logger("watchlist")


def fetch_bars(symbols: list, days: int = config.BARS_LOOKBACK_DAYS) -> dict:
    """Fetch daily bars for all symbols in one batched API call."""
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
    result = bars.df if hasattr(bars, 'df') else bars
    log.debug(f"Bar fetch complete. Response type: {type(result).__name__}")
    return result


def score_stock(symbol: str, df: pd.DataFrame) -> dict:
    """Score a single stock for swing trading potential."""
    if len(df) < 21:
        log.debug(f"{symbol}: skipped — only {len(df)} bars (need 21)")
        return {"symbol": symbol, "score": 0, "reason": "insufficient_data"}

    df = df.copy()
    df = compute_atr(df)
    df = compute_volume_ratio(df)

    row = df.iloc[-1]

    vol_ratio = row.get("vol_ratio", 1.0)
    vol_score = min(vol_ratio * 2, 5)

    atr_pct = (row["atr"] / row["close"]) * 100
    if 2 <= atr_pct <= 5:
        vol_score_atr = 5
    elif atr_pct < 2:
        vol_score_atr = atr_pct
    else:
        vol_score_atr = max(0, 5 - (atr_pct - 5) * 0.5)

    dollar_volume = row["close"] * row["volume"]
    liquidity_score = min(dollar_volume / 10_000_000, 5)

    total_score = vol_score + vol_score_atr + liquidity_score

    log.debug(
        f"{symbol}: score={total_score:.2f} "
        f"(vol_ratio={vol_ratio:.2f}x, atr={atr_pct:.1f}%, "
        f"dollar_vol=${dollar_volume/1e6:.0f}M, close=${row['close']:.2f})"
    )

    return {
        "symbol": symbol,
        "score": round(total_score, 2),
        "vol_ratio": round(vol_ratio, 2),
        "atr_pct": round(atr_pct, 2),
        "dollar_volume": int(dollar_volume),
        "close": round(row["close"], 2),
    }


def run():
    """Main watchlist agent logic."""
    log.info("=" * 60)
    log.info("WATCHLIST AGENT STARTING")
    log.info("=" * 60)

    universe = load_universe()
    log.info(f"Universe loaded: {len(universe)} stocks")

    bars_dict = fetch_bars(universe)

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

            score_result = score_stock(symbol, df)
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
        json.dump(output, f, indent=2)

    log.info(f"Watchlist saved to {config.WATCHLIST_PATH}")
    log.info("WATCHLIST AGENT COMPLETE")
    return watchlist


if __name__ == "__main__":
    run()
