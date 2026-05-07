"""
Research Agent: Scrapes news for watchlist stocks + macro context.
Sources:
  - Yahoo Finance RSS feeds (free, no API key)
  - Google Finance RSS (free, no API key)
  - Finviz news scraper (free, no API key)
Uses Claude to batch-summarize into actionable sentiment brief.
"""
import json
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic
import config
from logger import get_logger

log = get_logger("research")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def scrape_yahoo_finance_rss(symbol: str) -> list:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:5]
        headlines = [item.find("title").text.strip() for item in items if item.find("title")]
        log.debug(f"{symbol}: Yahoo RSS returned {len(headlines)} headlines")
        return headlines
    except Exception as e:
        log.debug(f"{symbol}: Yahoo RSS failed — {e}")
        return []


def scrape_google_finance_news(symbol: str) -> list:
    url = f"https://news.google.com/rss/search?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:5]
        headlines = [item.find("title").text.strip() for item in items if item.find("title")]
        log.debug(f"{symbol}: Google Finance returned {len(headlines)} headlines")
        return headlines
    except Exception as e:
        log.debug(f"{symbol}: Google Finance failed — {e}")
        return []


def scrape_finviz_news(symbol: str) -> list:
    url = f"https://finviz.com/quote.ashx?t={symbol}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        news_table = soup.find(id="news-table")
        if not news_table:
            return []
        rows = news_table.find_all("tr")[:8]
        headlines = [row.find("a").text.strip() for row in rows if row.find("a")]
        log.debug(f"{symbol}: Finviz returned {len(headlines)} headlines")
        return headlines
    except Exception as e:
        log.debug(f"{symbol}: Finviz failed — {e}")
        return []


def scrape_macro_news() -> list:
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:8]
        return [item.find("title").text.strip() for item in items if item.find("title")]
    except Exception as e:
        log.debug(f"Yahoo macro RSS failed — {e}")
        return []


def scrape_google_finance_market_news() -> list:
    url = "https://news.google.com/rss/search?q=stock+market+today&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item")[:8]
        return [item.find("title").text.strip() for item in items if item.find("title")]
    except Exception as e:
        log.debug(f"Google macro news failed — {e}")
        return []


def scrape_news(symbols: list) -> dict:
    """Scrape news from Yahoo Finance RSS + Google Finance + Finviz."""
    log.info(f"Scraping news for {len(symbols)} symbols...")
    news_data = {}

    for i, symbol in enumerate(symbols):
        headlines = []

        yahoo = scrape_yahoo_finance_rss(symbol)
        headlines.extend(yahoo)

        google = scrape_google_finance_news(symbol)
        for h in google:
            if h not in headlines:
                headlines.append(h)

        if not headlines:
            finviz = scrape_finviz_news(symbol)
            headlines.extend(finviz)

        source = "yahoo+google" if (yahoo or google) else ("finviz" if headlines else "none")
        news_data[symbol] = {"headlines": headlines[:8], "source": source}

        if headlines:
            log.debug(f"{symbol} [{source}]: {headlines[0][:80]}")
        else:
            log.debug(f"{symbol}: no headlines found")

        if i > 0 and i % 5 == 0:
            time.sleep(1)

    # Macro context
    macro = scrape_macro_news()
    google_macro = scrape_google_finance_market_news()
    for h in google_macro:
        if h not in macro:
            macro.append(h)

    news_data["_macro"] = {"headlines": macro[:12], "source": "yahoo+google"}

    with_news = sum(1 for s, d in news_data.items() if s != "_macro" and d["headlines"])
    log.info(f"News scraping complete: {with_news}/{len(symbols)} symbols have headlines")
    if macro:
        log.info(f"Macro headlines: {macro[0][:80]}")

    return news_data


def summarize_with_claude(news_data: dict, watchlist: list) -> dict:
    """Batch-summarize all news into sentiment brief using Claude."""
    if not config.ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — using keyword-based fallback")
        return keyword_sentiment_fallback(news_data, watchlist)

    log.info("Sending news to Claude for sentiment analysis (batched)...")
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    compressed = {}
    for symbol in watchlist:
        headlines = news_data.get(symbol, {}).get("headlines", [])
        compressed[symbol] = headlines if headlines else ["No recent news found"]

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

Return ONLY a valid JSON array, no other text."""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            system=[{
                "type": "text",
                "text": "You are a financial news analyst. Return only valid JSON arrays.",
                "cache_control": {"type": "ephemeral"}
            }]
        )

        content = response.content[0].text.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        items = json.loads(content)
        result = {}
        for item in items:
            sym = item.get("symbol")
            if sym:
                result[sym] = {
                    "sentiment": item.get("sentiment", "neutral"),
                    "summary": item.get("summary", ""),
                }

        for symbol in watchlist:
            if symbol not in result:
                result[symbol] = {"sentiment": "neutral", "summary": "No news available."}

        pos = sum(1 for v in result.values() if v.get("sentiment") == "positive")
        neg = sum(1 for v in result.values() if v.get("sentiment") == "negative")
        neu = sum(1 for v in result.values() if v.get("sentiment") == "neutral")
        log.info(f"Claude sentiment: {pos} positive, {neg} negative, {neu} neutral")

        for sym, data in result.items():
            log.debug(f"  {sym}: [{data['sentiment']}] {data.get('summary', '')[:80]}")

        return result

    except Exception as e:
        log.warning(f"Claude summarization failed ({e}), using keyword fallback")
        return keyword_sentiment_fallback(news_data, watchlist)


def keyword_sentiment_fallback(news_data: dict, watchlist: list) -> dict:
    """Simple keyword-based sentiment fallback."""
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
        sentiment = "positive" if pos > neg else ("negative" if neg > pos else "neutral")
        result[symbol] = {
            "sentiment": sentiment,
            "summary": headlines[0] if headlines else "No news available.",
        }
        log.debug(f"  {symbol}: [{sentiment}] (keyword: +{pos}/-{neg})")

    pos_count = sum(1 for v in result.values() if v["sentiment"] == "positive")
    neg_count = sum(1 for v in result.values() if v["sentiment"] == "negative")
    neu_count = sum(1 for v in result.values() if v["sentiment"] == "neutral")
    log.info(f"Keyword sentiment: {pos_count} positive, {neg_count} negative, {neu_count} neutral")
    return result


def run():
    """Main research agent logic."""
    log.info("=" * 60)
    log.info("RESEARCH AGENT STARTING")
    log.info("=" * 60)

    with open(config.WATCHLIST_PATH, "r") as f:
        data = json.load(f)
    watchlist = [item["symbol"] for item in data["watchlist"]]
    log.info(f"Watchlist loaded: {watchlist}")

    news_data = scrape_news(watchlist)

    brief = summarize_with_claude(news_data, watchlist)

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

    log.info(f"Research brief saved to {config.RESEARCH_BRIEF_PATH}")
    log.info("RESEARCH AGENT COMPLETE")
    return brief


if __name__ == "__main__":
    run()
