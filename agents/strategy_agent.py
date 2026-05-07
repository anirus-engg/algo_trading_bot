"""
Strategy Agent: Scores watchlist stocks for EMA pullback + RSI + momentum setups.
Reads strategy memory (cached) and outputs ranked candidates.
"""
import json
import pandas as pd
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from anthropic import Anthropic
import config
from strategy.signals import add_all_indicators, score_setup, calculate_entry_levels


def load_watchlist() -> list:
    """Load watchlist symbols."""
    with open(config.WATCHLIST_PATH, "r") as f:
        data = json.load(f)
    return [item["symbol"] for item in data["watchlist"]]


def load_research_brief() -> dict:
    """Load research brief."""
    with open(config.RESEARCH_BRIEF_PATH, "r") as f:
        data = json.load(f)
    return data["brief"]


def load_strategy_memory() -> dict:
    """Load strategy memory (for prompt caching)."""
    try:
        with open(config.STRATEGY_MEMORY_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"trades": [], "strategy_notes": "No trades yet.", "signal_performance": {}}


def fetch_bars_batch(symbols: list, days: int = 60) -> dict:
    """Fetch daily bars for all symbols in a single API call. Returns dict of symbol -> DataFrame."""
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
    multi_df = bars.df if hasattr(bars, 'df') else bars

    result = {}
    if isinstance(multi_df, pd.DataFrame) and not multi_df.empty:
        for symbol in symbols:
            try:
                if multi_df.index.nlevels > 1:
                    df = multi_df.xs(symbol, level=0).copy()
                else:
                    df = multi_df.copy()
                if not df.empty:
                    result[symbol] = df
            except KeyError:
                pass  # symbol had no data

    return result


def score_candidates(watchlist: list, brief: dict, memory: dict) -> list:
    """Score all watchlist stocks and return qualified candidates."""
    candidates = []

    # Single batched API call for all symbols
    print(f"  Fetching bars for {len(watchlist)} symbols in one batch call...")
    bars_by_symbol = fetch_bars_batch(watchlist)
    print(f"  Got data for {len(bars_by_symbol)}/{len(watchlist)} symbols")

    for symbol in watchlist:
        try:
            df = bars_by_symbol.get(symbol)
            if df is None or df.empty or len(df) < 52:
                continue

            df = add_all_indicators(df)

            sentiment = "neutral"
            if isinstance(brief, dict) and symbol in brief:
                val = brief[symbol]
                sentiment = val.get("sentiment", "neutral") if isinstance(val, dict) else val

            score_result = score_setup(df, news_sentiment=sentiment)

            if not score_result.get("qualified"):
                continue

            entry_levels = calculate_entry_levels(score_result, config.MAX_POSITION_SIZE)
            if not entry_levels:
                continue

            candidate = {
                "symbol": symbol,
                "score": score_result["score"],
                "signals": score_result["signals"],
                "entry": entry_levels["entry"],
                "stop_loss": entry_levels["stop_loss"],
                "take_profit": entry_levels["take_profit"],
                "shares": entry_levels["shares"],
                "notional": entry_levels["notional"],
                "risk_per_share": entry_levels["risk_per_share"],
                "trailing_stop_activation_price": entry_levels["trailing_stop_activation_price"],
                "sentiment": sentiment,
            }

            candidates.append(candidate)

        except Exception as e:
            print(f"  Error scoring {symbol}: {e}")
            continue

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def add_claude_reasoning(candidates: list, memory: dict) -> list:
    """Use Claude to add reasoning for each candidate (batched call)."""
    if not config.ANTHROPIC_API_KEY or not candidates:
        return candidates
    
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    
    # Build cached system prompt with strategy memory
    system_prompt = f"""You are a swing trading strategist. Based on our trading history, provide brief reasoning for each trade candidate.

Strategy Memory (cached):
{json.dumps(memory, indent=2)}

For each candidate, explain in 1-2 sentences why this setup looks promising based on the signals and our past performance with similar setups."""
    
    candidates_json = json.dumps(candidates, indent=2)
    
    prompt = f"""Here are today's trade candidates:

{candidates_json}

For each candidate, add a "reasoning" field with 1-2 sentences explaining why this setup is strong.
Return the full candidates array as valid JSON with the reasoning field added."""
    
    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        )
        
        content = response.content[0].text
        enriched = json.loads(content)
        return enriched
    except Exception as e:
        print(f"  Warning: Claude reasoning failed: {e}")
        # Add default reasoning
        for c in candidates:
            c["reasoning"] = f"Score {c['score']}: Strong technical setup with {c['sentiment']} sentiment."
        return candidates


def run():
    """Main strategy agent logic."""
    print(f"[{datetime.now()}] Strategy Agent: Loading inputs...")
    
    watchlist = load_watchlist()
    brief = load_research_brief()
    memory = load_strategy_memory()
    
    print(f"[{datetime.now()}] Strategy Agent: Scoring {len(watchlist)} stocks...")
    candidates = score_candidates(watchlist, brief, memory)
    
    print(f"[{datetime.now()}] Strategy Agent: Found {len(candidates)} qualified candidates")
    
    if candidates:
        print(f"[{datetime.now()}] Strategy Agent: Adding Claude reasoning...")
        candidates = add_claude_reasoning(candidates, memory)
    
    # Save candidates
    output = {
        "generated_at": datetime.now().isoformat(),
        "candidates": candidates,
    }
    
    with open(config.CANDIDATES_PATH, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"[{datetime.now()}] Strategy Agent: Saved {len(candidates)} candidates")
    if candidates:
        print(f"  Top 3: {[c['symbol'] for c in candidates[:3]]}")
    
    return candidates


if __name__ == "__main__":
    run()
