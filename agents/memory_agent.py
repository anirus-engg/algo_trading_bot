"""
Memory Agent: Analyzes closed trades and updates strategy memory.
Runs after market close. Self-learning feedback loop.
"""
import json
from datetime import datetime
from anthropic import Anthropic
import config


def load_trade_log() -> dict:
    """Load trade log."""
    try:
        with open(config.TRADE_LOG_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"open_positions": {}, "closed_trades": []}


def load_strategy_memory() -> dict:
    """Load strategy memory."""
    try:
        with open(config.STRATEGY_MEMORY_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"trades": [], "strategy_notes": "No trades yet.", "signal_performance": {}}


def save_strategy_memory(memory: dict):
    """Save strategy memory."""
    with open(config.STRATEGY_MEMORY_PATH, "w") as f:
        json.dump(memory, f, indent=2)


def compute_signal_performance(trades: list) -> dict:
    """Compute win rate for each signal combination."""
    performance = {}
    
    for trade in trades:
        if "outcome" not in trade:
            continue
        
        signals = trade.get("signals_at_entry", {})
        
        # Build signal key from high-scoring signals
        signal_keys = []
        for sig_name, sig_data in signals.items():
            if isinstance(sig_data, dict) and sig_data.get("points", 0) >= 1:
                signal_keys.append(sig_name)
        
        if not signal_keys:
            continue
        
        key = "+".join(sorted(signal_keys))
        
        if key not in performance:
            performance[key] = {"wins": 0, "losses": 0}
        
        if trade["outcome"] == "win":
            performance[key]["wins"] += 1
        else:
            performance[key]["losses"] += 1
    
    return performance


def update_memory_with_claude(memory: dict, new_trades: list) -> dict:
    """Use Claude to analyze new trades and update strategy notes."""
    if not config.ANTHROPIC_API_KEY or not new_trades:
        return memory
    
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    
    # Build prompt
    prompt = f"""You are analyzing our swing trading performance to improve our strategy.

Current strategy memory:
{json.dumps(memory, indent=2)}

New closed trades since last update:
{json.dumps(new_trades, indent=2)}

Tasks:
1. Analyze what's working and what's not
2. Identify patterns in winning vs losing trades
3. Update the "strategy_notes" field with actionable insights
4. Suggest any rule adjustments (e.g., avoid certain signal combos, increase weight on others)

Return the updated memory object as valid JSON with an updated "strategy_notes" field.
Keep it concise (max 500 words)."""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            system=[
                {
                    "type": "text",
                    "text": "You are a quantitative trading analyst. Return only valid JSON.",
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        )
        
        content = response.content[0].text
        updated_memory = json.loads(content)
        return updated_memory
    
    except Exception as e:
        print(f"  Warning: Claude memory update failed: {e}")
        return memory


def run():
    """Main memory agent logic."""
    print(f"[{datetime.now()}] Memory Agent: Loading trade log...")
    
    log = load_trade_log()
    memory = load_strategy_memory()
    
    # Find new closed trades (not yet in memory)
    existing_trade_count = len(memory["trades"])
    new_trades = log["closed_trades"][existing_trade_count:]
    
    if not new_trades:
        print(f"[{datetime.now()}] Memory Agent: No new closed trades")
        return memory
    
    print(f"[{datetime.now()}] Memory Agent: Processing {len(new_trades)} new trades...")
    
    # Append new trades to memory
    memory["trades"].extend(new_trades)
    
    # Recompute signal performance
    memory["signal_performance"] = compute_signal_performance(memory["trades"])
    
    # Update strategy notes with Claude
    print(f"[{datetime.now()}] Memory Agent: Updating strategy notes with Claude...")
    memory = update_memory_with_claude(memory, new_trades)
    
    # Save updated memory
    save_strategy_memory(memory)
    
    print(f"[{datetime.now()}] Memory Agent: Memory updated")
    print(f"  Total trades: {len(memory['trades'])}")
    print(f"  Signal combos tracked: {len(memory['signal_performance'])}")
    
    return memory


if __name__ == "__main__":
    run()
