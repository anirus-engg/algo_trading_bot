"""
Watchlist Agent: Scans universe, scores stocks, outputs top 25.
Runs pre-market every morning.
"""
import json
import pandas as pd
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import config
from strategy.signals import compute_atr, compute_volume_ratio


def fetch_bars(symbols: list, days: int = 30) -> dict:
    """Fetch daily bars for all symbols."""
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
    return bars.df if hasattr(bars, 'df') else bars


def score_stock(symbol: str, df: pd.DataFrame) -> dict:
    """Score a single stock for swing trading potential."""
    if len(df) < 21:
        return {"symbol": symbol, "score": 0, "reason": "insufficient_data"}
    
    df = df.copy()
    df = compute_atr(df)
    df = compute_volume_ratio(df)
    
    row = df.iloc[-1]
    
    # Volume score (relative to 20-day avg)
    vol_ratio = row.get("vol_ratio", 1.0)
    vol_score = min(vol_ratio * 2, 5)  # cap at 5
    
    # Volatility score (ATR as % of price)
    atr_pct = (row["atr"] / row["close"]) * 100
    # Sweet spot: 2-5% ATR
    if 2 <= atr_pct <= 5:
        vol_score_atr = 5
    elif atr_pct < 2:
        vol_score_atr = atr_pct  # too low
    else:
        vol_score_atr = max(0, 5 - (atr_pct - 5) * 0.5)  # penalize high volatility
    
    # Liquidity (dollar volume)
    dollar_volume = row["close"] * row["volume"]
    liquidity_score = min(dollar_volume / 10_000_000, 5)  # $10M+ = max score
    
    total_score = vol_score + vol_score_atr + liquidity_score
    
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
    print(f"[{datetime.now()}] Watchlist Agent: Starting scan of {len(config.SCAN_UNIVERSE)} stocks...")
    
    # Fetch bars for all symbols
    bars_dict = fetch_bars(config.SCAN_UNIVERSE)
    
    # Score each stock
    scores = []
    for symbol in config.SCAN_UNIVERSE:
        try:
            if isinstance(bars_dict, pd.DataFrame):
                # Multi-index DataFrame
                if symbol in bars_dict.index.get_level_values(0):
                    df = bars_dict.xs(symbol, level=0)
                else:
                    continue
            else:
                df = bars_dict.get(symbol)
                if df is None:
                    continue
            
            score_result = score_stock(symbol, df)
            scores.append(score_result)
        except Exception as e:
            print(f"  Error scoring {symbol}: {e}")
            continue
    
    # Sort by score descending
    scores.sort(key=lambda x: x["score"], reverse=True)
    
    # Take top N
    watchlist = scores[:config.WATCHLIST_SIZE]
    
    # Save to JSON
    output = {
        "generated_at": datetime.now().isoformat(),
        "watchlist": watchlist,
        "total_scanned": len(config.SCAN_UNIVERSE),
    }
    
    with open(config.WATCHLIST_PATH, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"[{datetime.now()}] Watchlist Agent: Generated watchlist with {len(watchlist)} stocks")
    print(f"  Top 5: {[s['symbol'] for s in watchlist[:5]]}")
    
    return watchlist


if __name__ == "__main__":
    run()
