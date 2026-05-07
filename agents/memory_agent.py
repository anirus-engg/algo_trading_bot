"""
Memory Agent: Analyzes closed trades and updates strategy memory.
Runs after market close. Self-learning feedback loop.
"""
import json
from datetime import datetime
from anthropic import Anthropic
import config
from logger import get_logger

log = get_logger("memory")


def load_trade_log() -> dict:
    try:
        with open(config.TRADE_LOG_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"open_positions": {}, "closed_trades": []}


def load_strategy_memory() -> dict:
    try:
        with open(config.STRATEGY_MEMORY_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"trades": [], "strategy_notes": "No trades yet.", "signal_performance": {}}


def save_strategy_memory(memory: dict):
    with open(config.STRATEGY_MEMORY_PATH, "w") as f:
        json.dump(memory, f, indent=2)


def compute_signal_performance(trades: list) -> dict:
    """Compute win rate for each signal combination."""
    performance = {}

    for trade in trades:
        if "outcome" not in trade:
            continue
        signals = trade.get("signals_at_entry", {})
        signal_keys = [
            name for name, data in signals.items()
            if isinstance(data, dict) and data.get("points", 0) >= 1
        ]
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

    log.info(f"Sending {len(new_trades)} new trades to Claude for analysis...")
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = f"""You are analyzing our swing trading performance to improve our strategy.

Current strategy memory:
{json.dumps(memory, indent=2)}

New closed trades since last update:
{json.dumps(new_trades, indent=2)}

Tasks:
1. Analyze what's working and what's not
2. Identify patterns in winning vs losing trades
3. Update the "strategy_notes" field with actionable insights
4. Suggest any rule adjustments

Return the updated memory object as valid JSON with an updated "strategy_notes" field.
Keep it concise (max 500 words)."""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            system=[{
                "type": "text",
                "text": "You are a quantitative trading analyst. Return only valid JSON.",
                "cache_control": {"type": "ephemeral"}
            }]
        )

        content = response.content[0].text
        updated_memory = json.loads(content)
        log.info(f"Strategy notes updated by Claude")
        log.debug(f"New strategy notes: {updated_memory.get('strategy_notes', '')[:300]}")
        return updated_memory

    except Exception as e:
        log.warning(f"Claude memory update failed: {e}")
        return memory


def run():
    """Main memory agent logic."""
    log.info("=" * 60)
    log.info("MEMORY AGENT STARTING")
    log.info("=" * 60)

    trade_log = load_trade_log()
    memory = load_strategy_memory()

    total_closed = len(trade_log["closed_trades"])
    existing_count = len(memory["trades"])
    new_trades = trade_log["closed_trades"][existing_count:]

    log.info(f"Total closed trades: {total_closed}")
    log.info(f"Already in memory: {existing_count}")
    log.info(f"New trades to process: {len(new_trades)}")

    if not new_trades:
        log.info("No new closed trades — memory unchanged")
        return memory

    # Log each new trade
    for trade in new_trades:
        symbol = trade.get("symbol", "?")
        pnl = trade.get("pnl", 0)
        outcome = trade.get("outcome", "unknown")
        reason = trade.get("exit_reason", "unknown")
        log.info(f"  New trade: {symbol} | outcome={outcome} | P&L=${pnl:.2f} | exit={reason}")

    memory["trades"].extend(new_trades)
    memory["signal_performance"] = compute_signal_performance(memory["trades"])

    # Log signal performance
    log.info("Signal performance (all time):")
    for combo, stats in memory["signal_performance"].items():
        total = stats["wins"] + stats["losses"]
        win_rate = (stats["wins"] / total * 100) if total > 0 else 0
        log.info(f"  {combo}: {stats['wins']}W/{stats['losses']}L ({win_rate:.0f}% win rate)")

    # Overall stats
    all_trades = memory["trades"]
    wins = sum(1 for t in all_trades if t.get("outcome") == "win")
    total = len(all_trades)
    total_pnl = sum(t.get("pnl", 0) for t in all_trades)
    win_rate = (wins / total * 100) if total > 0 else 0
    log.info(f"Overall: {total} trades | {win_rate:.0f}% win rate | total P&L=${total_pnl:,.2f}")

    memory = update_memory_with_claude(memory, new_trades)

    save_strategy_memory(memory)
    log.info(f"Strategy memory saved to {config.STRATEGY_MEMORY_PATH}")
    log.info("MEMORY AGENT COMPLETE")
    return memory


if __name__ == "__main__":
    run()
