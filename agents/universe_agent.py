"""
Universe Agent: Fetches S&P 500 constituents and filters to top 100 by average daily dollar volume.
Filters applied:
  - Price >= $20 (avoids low-priced, wide-spread stocks)
  - ATR% >= 1.5% (needs intraday movement for day trading)
  - Top 100 by avg daily dollar volume (liquidity)
Runs weekly (every Monday pre-market).
Results cached to data/universe.json.
"""
import json
import pandas as pd
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import config
from logger import get_logger

log = get_logger("universe")

UNIVERSE_PATH = "data/universe.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def fetch_sp500_tickers() -> list:
    """Scrape S&P 500 constituents from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "constituents"})
        tickers = []
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if cols:
                ticker = cols[0].text.strip()
                # Skip tickers with dots — Alpaca uses different format (BRK.B etc.)
                if "." in ticker:
                    continue
                tickers.append(ticker)
        log.info(f"Fetched {len(tickers)} S&P 500 tickers from Wikipedia")
        return tickers
    except Exception as e:
        log.warning(f"Failed to fetch S&P 500 list ({e}), using cached universe")
        return []


def rank_and_filter(tickers: list, top_n: int = config.UNIVERSE_SIZE) -> list:
    """
    Fetch 30-day daily bars for all tickers, apply filters, rank by dollar volume.

    Filters:
      - avg_close >= MIN_STOCK_PRICE ($20)
      - atr_pct >= MIN_ATR_PCT (1.5%) — ensures enough intraday movement

    Returns top N symbols by avg daily dollar volume.
    """
    client = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    end = datetime.now()
    start = end - timedelta(days=35)  # ~25 trading days

    BATCH_SIZE = 100
    all_scores = []
    filtered_price = 0
    filtered_atr = 0

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start,
                end=end
            )
            bars = client.get_stock_bars(request)
            df_all = bars.df if hasattr(bars, "df") else bars

            if not isinstance(df_all, pd.DataFrame) or df_all.empty:
                continue

            for symbol in batch:
                try:
                    df = df_all.xs(symbol, level=0) if df_all.index.nlevels > 1 else df_all
                    if df.empty or len(df) < 5:
                        continue

                    avg_close = float(df["close"].mean())
                    avg_dollar_volume = float((df["close"] * df["volume"]).mean())

                    # Price filter
                    if avg_close < config.MIN_STOCK_PRICE:
                        filtered_price += 1
                        log.debug(f"{symbol}: filtered — avg price ${avg_close:.2f} < ${config.MIN_STOCK_PRICE}")
                        continue

                    # ATR% filter — use True Range approximation
                    high_low = df["high"] - df["low"]
                    high_close = (df["high"] - df["close"].shift()).abs()
                    low_close = (df["low"] - df["close"].shift()).abs()
                    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
                    atr = tr.mean()
                    atr_pct = (atr / avg_close) * 100

                    if atr_pct < config.MIN_ATR_PCT:
                        filtered_atr += 1
                        log.debug(f"{symbol}: filtered — ATR% {atr_pct:.2f}% < {config.MIN_ATR_PCT}%")
                        continue

                    all_scores.append({
                        "symbol": symbol,
                        "avg_dollar_volume": avg_dollar_volume,
                        "avg_close": round(avg_close, 2),
                        "atr_pct": round(atr_pct, 2),
                    })

                except KeyError:
                    pass

        except Exception as e:
            log.warning(f"Batch {i // BATCH_SIZE + 1} failed: {e}")
            continue

    log.info(
        f"Filtering complete: {len(all_scores)} passed | "
        f"{filtered_price} removed (price < ${config.MIN_STOCK_PRICE}) | "
        f"{filtered_atr} removed (ATR% < {config.MIN_ATR_PCT}%)"
    )

    # Sort by avg daily dollar volume descending
    all_scores.sort(key=lambda x: x["avg_dollar_volume"], reverse=True)
    top = all_scores[:top_n]

    log.info(f"Selected top {len(top)} by avg daily dollar volume")
    if top:
        log.info(f"Top 10: {[s['symbol'] for s in top[:10]]}")
        log.info(
            f"Dollar volume range: "
            f"${top[0]['avg_dollar_volume']/1e9:.1f}B – "
            f"${top[-1]['avg_dollar_volume']/1e6:.0f}M"
        )

    return top


def load_universe() -> list:
    """Load cached universe, falling back to config.SCAN_UNIVERSE if not available."""
    try:
        with open(UNIVERSE_PATH) as f:
            data = json.load(f)
        generated = datetime.fromisoformat(data["generated_at"])
        age_days = (datetime.now() - generated).days
        if age_days > 8:
            log.info(f"Universe is {age_days} days old — will refresh on next Monday run")
        return data["symbols"]
    except FileNotFoundError:
        log.warning("universe.json not found — falling back to config.SCAN_UNIVERSE")
        # Minimal fallback: liquid large-caps that pass our filters
        return [
            "NVDA", "TSLA", "MSFT", "AAPL", "AMZN", "META", "GOOGL", "AMD",
            "AVGO", "PLTR", "NFLX", "QCOM", "LLY", "UNH", "XOM", "JPM",
            "LRCX", "CRM", "AMAT", "V", "MA", "GS", "BAC", "CRWD", "PANW",
            "COIN", "UBER", "HOOD", "DDOG", "SNOW",
        ]


def run():
    """Main universe agent logic."""
    log.info("=" * 60)
    log.info("UNIVERSE AGENT STARTING")
    log.info("=" * 60)
    log.info(
        f"Filters: price >= ${config.MIN_STOCK_PRICE} | "
        f"ATR% >= {config.MIN_ATR_PCT}% | "
        f"top {config.UNIVERSE_SIZE} by dollar volume"
    )

    tickers = fetch_sp500_tickers()

    if not tickers:
        log.warning("No tickers fetched — keeping existing universe")
        return load_universe()

    scored = rank_and_filter(tickers, top_n=config.UNIVERSE_SIZE)

    if not scored:
        log.warning("No stocks passed filters — keeping existing universe")
        return load_universe()

    symbols = [s["symbol"] for s in scored]

    output = {
        "generated_at": datetime.now().isoformat(),
        "source": "S&P 500 Wikipedia + Alpaca volume ranking",
        "filters": {
            "min_price": config.MIN_STOCK_PRICE,
            "min_atr_pct": config.MIN_ATR_PCT,
            "top_n": config.UNIVERSE_SIZE,
        },
        "total_sp500": len(tickers),
        "passed_filters": len(scored),
        "selected": len(symbols),
        "symbols": symbols,
    }

    with open(UNIVERSE_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info(f"Universe saved: {len(symbols)} symbols → {UNIVERSE_PATH}")
    log.info("UNIVERSE AGENT COMPLETE")
    return symbols


if __name__ == "__main__":
    run()
