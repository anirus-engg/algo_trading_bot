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

    trades_summary = [
        {
            "symbol": t.get("symbol"),
            "setup_type": t.get("setup_type", "vwap_reclaim"),
            "outcome": t.get("outcome"),
            "pnl": t.get("pnl"),
            "exit_reason": t.get("exit_reason"),
            "entry_price": t.get("entry_price", t.get("entry")),
            "exit_price": t.get("exit_price"),
            "score": t.get("score"),
            "signals_at_entry": t.get("signals_at_entry", {}),
        }
        for t in new_trades
    ]

    wins = sum(1 for t in new_trades if t.get("outcome") == "win")
    losses = sum(1 for t in new_trades if t.get("outcome") == "loss")
    total_pnl = sum(t.get("pnl", 0) for t in new_trades)

    prompt = f"""You are a quantitative trading analyst reviewing intraday day trading results.

Previous strategy notes:
{memory.get('strategy_notes', 'No prior notes.')}

New closed trades ({len(new_trades)} trades, {wins}W/{losses}L, P&L=${total_pnl:+.2f}):
{json.dumps(trades_summary, indent=2)}

Write 3-5 concise bullet-point insights covering:
- What setups/signals are working vs failing
- Patterns in wins vs losses (score, volume, exit reason)
- Any actionable rule adjustments

Return ONLY the bullet points as plain text (no JSON, no headers)."""

    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
            system=[{
                "type": "text",
                "text": "You are a quantitative trading analyst. Be concise and actionable.",
                "cache_control": {"type": "ephemeral"}
            }]
        )

        notes = response.content[0].text.strip()
        if notes:
            memory["strategy_notes"] = notes
            log.info(f"Strategy notes updated by Claude")
            log.debug(f"New strategy notes: {notes[:300]}")
        else:
            log.warning("Claude returned empty notes — keeping existing")

        return memory

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
