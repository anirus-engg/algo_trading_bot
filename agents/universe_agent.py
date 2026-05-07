"""
Universe Agent: Fetches S&P 500 constituents and filters to top 200 by average daily volume.
Runs weekly (every Monday) to keep the universe current.
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

UNIVERSE_PATH = "data/universe.json"
UNIVERSE_SIZE = 200
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
                # Handle special tickers Alpaca doesn't support
                if "." in ticker:
                    continue  # skip BRK.B, BF.B etc — Alpaca uses different format
                tickers.append(ticker)
        print(f"  Fetched {len(tickers)} S&P 500 tickers from Wikipedia")
        return tickers
    except Exception as e:
        print(f"  Warning: Failed to fetch S&P 500 list ({e}), using cached universe")
        return []


def rank_by_volume(tickers: list, top_n: int = UNIVERSE_SIZE) -> list:
    """
    Fetch 30-day bars for all tickers in batches and rank by average daily dollar volume.
    Returns top N symbols.
    """
    client = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    end = datetime.now()
    start = end - timedelta(days=35)  # ~25 trading days

    # Alpaca has a limit on symbols per request — batch in groups of 100
    BATCH_SIZE = 100
    all_scores = []

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
            df_all = bars.df if hasattr(bars, 'df') else bars

            if not isinstance(df_all, pd.DataFrame) or df_all.empty:
                continue

            for symbol in batch:
                try:
                    df = df_all.xs(symbol, level=0) if df_all.index.nlevels > 1 else df_all
                    if df.empty or len(df) < 5:
                        continue
                    avg_dollar_volume = (df["close"] * df["volume"]).mean()
                    all_scores.append({
                        "symbol": symbol,
                        "avg_dollar_volume": float(avg_dollar_volume),
                        "avg_close": float(df["close"].mean()),
                    })
                except KeyError:
                    pass

        except Exception as e:
            print(f"  Warning: Batch {i//BATCH_SIZE + 1} failed: {e}")
            continue

    # Sort by average dollar volume descending
    all_scores.sort(key=lambda x: x["avg_dollar_volume"], reverse=True)

    top = all_scores[:top_n]
    print(f"  Ranked {len(all_scores)} stocks, selected top {len(top)} by avg daily dollar volume")
    return [s["symbol"] for s in top]


def load_universe() -> list:
    """Load cached universe, falling back to config.SCAN_UNIVERSE if not available."""
    try:
        with open(UNIVERSE_PATH) as f:
            data = json.load(f)
        # Check if it's stale (older than 8 days)
        generated = datetime.fromisoformat(data["generated_at"])
        age_days = (datetime.now() - generated).days
        if age_days > 8:
            print(f"  Universe is {age_days} days old, will refresh")
        return data["symbols"]
    except FileNotFoundError:
        return config.SCAN_UNIVERSE


def run():
    """Main universe agent logic."""
    print(f"[{datetime.now()}] Universe Agent: Fetching S&P 500 constituents...")

    tickers = fetch_sp500_tickers()

    if not tickers:
        print(f"  Falling back to existing universe")
        return load_universe()

    print(f"[{datetime.now()}] Universe Agent: Ranking by average daily dollar volume...")
    top_symbols = rank_by_volume(tickers, top_n=UNIVERSE_SIZE)

    output = {
        "generated_at": datetime.now().isoformat(),
        "source": "S&P 500 Wikipedia + Alpaca volume ranking",
        "total_sp500": len(tickers),
        "selected": len(top_symbols),
        "symbols": top_symbols,
    }

    with open(UNIVERSE_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[{datetime.now()}] Universe Agent: Saved top {len(top_symbols)} symbols")
    print(f"  Top 10: {top_symbols[:10]}")

    return top_symbols


if __name__ == "__main__":
    run()
