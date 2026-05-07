"""
Research Agent: Scrapes news for watchlist stocks + macro context.
Sources:
  - Yahoo Finance RSS feeds (free, no API key)
  - Finviz news scraper (free, no API key)
  - Seeking Alpha RSS (free)
Uses Claude to batch-summarize into actionable sentiment brief.
"""
import json
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


# ---------------------------------------------------------------------------
# News scrapers (free, no API key required)
# ---------------------------------------------------------------------------

def scrape_yahoo_finance_rss(symbol: str) -> list:
    """Fetch headlines from Yahoo Finance RSS feed for a symbol."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:5]  # top 5 headlines
        return [item.find("title").text.strip() for item in items if item.find("title")]
    except Exception:
        return []


def scrape_finviz_news(symbol: str) -> list:
    """Fetch headlines from Finviz news table for a symbol."""
    url = f"https://finviz.com/quote.ashx?t={symbol}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        news_table = soup.find(id="news-table")
        if not news_table:
            return []
        rows = news_table.find_all("tr")[:8]
        headlines = []
        for row in rows:
            a = row.find("a")
            if a:
                headlines.append(a.text.strip())
        return headlines
    except Exception:
        return []


def scrape_google_finance_news(symbol: str) -> list:
    """Fetch headlines from Google Finance RSS feed for a symbol."""
    url = f"https://news.google.com/rss/search?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:5]
        return [item.find("title").text.strip() for item in items if item.find("title")]
    except Exception:
        return []


def scrape_google_finance_market_news() -> list:
    """Fetch broad market news from Google Finance RSS."""
    url = "https://news.google.com/rss/search?q=stock+market+today&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:8]
        return [item.find("title").text.strip() for item in items if item.find("title")]
    except Exception:
        return []


def scrape_macro_news() -> list:
    """Fetch macro market headlines from Yahoo Finance market news RSS."""
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:8]
        return [item.find("title").text.strip() for item in items if item.find("title")]
    except Exception:
        return []



    """Fetch macro market headlines from Yahoo Finance market news RSS."""
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:8]
        return [item.find("title").text.strip() for item in items if item.find("title")]
    except Exception:
        return []


def scrape_news(symbols: list) -> dict:
    """
    Scrape news headlines for all symbols.
    Uses Yahoo Finance RSS + Finviz as sources.
    Batches requests with small delay to avoid rate limiting.
    """
    news_data = {}

    print(f"  Scraping news for {len(symbols)} symbols...")

    for i, symbol in enumerate(symbols):
        headlines = []

        # Yahoo Finance RSS (primary)
        yahoo_headlines = scrape_yahoo_finance_rss(symbol)
        headlines.extend(yahoo_headlines)

        # Google Finance RSS (secondary)
        google_headlines = scrape_google_finance_news(symbol)
        # Deduplicate against Yahoo headlines
        for h in google_headlines:
            if h not in headlines:
                headlines.append(h)

        # Finviz (tertiary, only if both above returned nothing)
        if not headlines:
            finviz_headlines = scrape_finviz_news(symbol)
            headlines.extend(finviz_headlines)

        news_data[symbol] = {
            "headlines": headlines[:8],  # cap at 8 per stock
            "source": "yahoo+google" if yahoo_headlines or google_headlines else ("finviz" if headlines else "none"),
        }

        # Small delay every 5 requests to be polite
        if i > 0 and i % 5 == 0:
            time.sleep(1)

    # Macro context: merge Yahoo + Google market news
    macro_headlines = scrape_macro_news()
    google_macro = scrape_google_finance_market_news()
    for h in google_macro:
        if h not in macro_headlines:
            macro_headlines.append(h)

    news_data["_macro"] = {
        "headlines": macro_headlines[:12],
        "source": "yahoo_rss+google_finance",
    }

    total_with_news = sum(1 for s, d in news_data.items()
                         if s != "_macro" and d["headlines"])
    print(f"  Got headlines for {total_with_news}/{len(symbols)} symbols")

    return news_data


# ---------------------------------------------------------------------------
# Claude summarization (batched, cached)
# ---------------------------------------------------------------------------

def summarize_with_claude(news_data: dict, watchlist: list) -> dict:
    """Use Claude to batch-summarize all news into actionable sentiment brief."""
    if not config.ANTHROPIC_API_KEY:
        print("  Warning: ANTHROPIC_API_KEY not set — using keyword-based fallback")
        return keyword_sentiment_fallback(news_data, watchlist)

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Compress news data — only send headlines, not metadata
    compressed = {}
    for symbol in watchlist:
        headlines = news_data.get(symbol, {}).get("headlines", [])
        if headlines:
            compressed[symbol] = headlines
        else:
            compressed[symbol] = ["No recent news found"]

    macro_headlines = news_data.get("_macro", {}).get("headlines", [])

    prompt = f"""Analyze these stock news headlines for swing trading sentiment.

Macro headlines:
{json.dumps(macro_headlines, indent=2)}

Stock headlines:
{json.dumps(compressed, indent=2)}

For each stock, return a JSON array of objects with:
- "symbol": ticker
- "sentiment": "positive", "negative", or "neutral"
- "summary": 1 sentence max — key catalyst or reason

Return ONLY a valid JSON array, no other text. Example:
[{{"symbol": "AAPL", "sentiment": "positive", "summary": "Strong iPhone demand reported."}}]"""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            system=[
                {
                    "type": "text",
                    "text": "You are a financial news analyst. Return only valid JSON arrays.",
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        )

        content = response.content[0].text.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        items = json.loads(content)

        # Convert array to dict keyed by symbol
        result = {}
        for item in items:
            sym = item.get("symbol")
            if sym:
                result[sym] = {
                    "sentiment": item.get("sentiment", "neutral"),
                    "summary": item.get("summary", ""),
                }

        # Fill in any missing symbols
        for symbol in watchlist:
            if symbol not in result:
                result[symbol] = {"sentiment": "neutral", "summary": "No news available."}

        return result

    except Exception as e:
        print(f"  Warning: Claude summarization failed ({e}), using fallback")
        return keyword_sentiment_fallback(news_data, watchlist)


def keyword_sentiment_fallback(news_data: dict, watchlist: list) -> dict:
    """
    Simple keyword-based sentiment when Claude is unavailable.
    Not as accurate but better than all-neutral.
    """
    positive_words = {"beat", "surge", "rally", "upgrade", "buy", "strong",
                      "record", "growth", "profit", "gain", "rise", "bullish",
                      "outperform", "raised", "exceed", "boost"}
    negative_words = {"miss", "drop", "fall", "downgrade", "sell", "weak",
                      "loss", "decline", "cut", "bearish", "underperform",
                      "layoff", "recall", "investigation", "lawsuit", "warning"}

    result = {}
    for symbol in watchlist:
        headlines = news_data.get(symbol, {}).get("headlines", [])
        text = " ".join(headlines).lower()

        pos = sum(1 for w in positive_words if w in text)
        neg = sum(1 for w in negative_words if w in text)

        if pos > neg:
            sentiment = "positive"
        elif neg > pos:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        result[symbol] = {
            "sentiment": sentiment,
            "summary": headlines[0] if headlines else "No news available.",
        }

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    """Main research agent logic."""
    print(f"[{datetime.now()}] Research Agent: Loading watchlist...")

    with open(config.WATCHLIST_PATH, "r") as f:
        data = json.load(f)
    watchlist = [item["symbol"] for item in data["watchlist"]]

    print(f"[{datetime.now()}] Research Agent: Scraping news from Yahoo Finance, Google Finance + Finviz...")
    news_data = scrape_news(watchlist)

    print(f"[{datetime.now()}] Research Agent: Summarizing with Claude...")
    brief = summarize_with_claude(news_data, watchlist)

    # Save brief
    output = {
        "generated_at": datetime.now().isoformat(),
        "watchlist": watchlist,
        "brief": brief,
        "raw_headlines": {s: news_data[s]["headlines"]
                         for s in watchlist if news_data.get(s, {}).get("headlines")},
        "macro_headlines": news_data.get("_macro", {}).get("headlines", []),
    }

    with open(config.RESEARCH_BRIEF_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary
    sentiments = [v["sentiment"] if isinstance(v, dict) else v
                  for v in brief.values()]
    pos = sentiments.count("positive")
    neg = sentiments.count("negative")
    neu = sentiments.count("neutral")
    print(f"[{datetime.now()}] Research Agent: Complete — "
          f"{pos} positive, {neg} negative, {neu} neutral")

    return brief


if __name__ == "__main__":
    run()
