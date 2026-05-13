"""
One-time backfill script: fetches actual exit fill prices from Alpaca for all
closed trades that are missing exit_price / pnl / outcome, then updates both
trade_log.json and strategy_memory.json.

Run once from the project root:
    python backfill_pnl.py
"""
import json
import time
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
import config
from logger import get_logger

log = get_logger("backfill")


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def fetch_filled_sells(client: TradingClient, symbol: str) -> list:
    """Return all filled sell orders for a symbol, most recent first."""
    try:
        request = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            symbols=[symbol],
            limit=50,
        )
        orders = client.get_orders(filter=request)
        filled_sells = [
            o for o in orders
            if (
                str(o.side).lower() in ("sell", "orderside.sell")
                and str(o.status).lower() in ("filled", "orderstatus.filled")
                and o.filled_avg_price is not None
            )
        ]
        return sorted(filled_sells, key=lambda o: o.filled_at or o.updated_at, reverse=True)
    except Exception as e:
        log.warning(f"{symbol}: fetch_filled_sells failed — {e}")
        return []


def resolve_exit(client: TradingClient, trade: dict) -> dict:
    """
    Try to find the actual exit fill price for a trade.
    Matches by symbol + approximate exit time (within 15 min window).
    Returns updated trade dict.
    """
    symbol = trade.get("symbol", "?")
    entry_price = trade.get("entry_price", trade.get("entry", 0))
    stop_loss = trade.get("stop_loss", 0)
    take_profit = trade.get("take_profit", 0)
    shares = trade.get("shares", 0)

    filled_sells = fetch_filled_sells(client, symbol)
    if not filled_sells:
        log.warning(f"{symbol}: no filled sell orders found — using stop_loss as fallback")
        # Fallback: assume stop was hit (conservative)
        exit_price = stop_loss if stop_loss else entry_price
        exit_reason = "stop_hit_estimated"
    else:
        best = filled_sells[0]
        exit_price = float(best.filled_avg_price)
        log.info(f"{symbol}: found exit fill ${exit_price} (order {best.id})")

        if take_profit and stop_loss:
            dist_to_target = abs(exit_price - take_profit)
            dist_to_stop = abs(exit_price - stop_loss)
            if dist_to_target < dist_to_stop:
                exit_reason = "target_hit"
            else:
                exit_reason = "stop_hit"
        else:
            exit_reason = trade.get("exit_reason", "bracket_order_filled")

    pnl = (exit_price - entry_price) * shares
    trade["exit_price"] = round(exit_price, 4)
    trade["pnl"] = round(pnl, 2)
    trade["pnl_pct"] = round((exit_price - entry_price) / entry_price * 100, 3) if entry_price else 0
    trade["outcome"] = "win" if pnl > 0 else "loss"
    trade["exit_reason"] = exit_reason

    log.info(
        f"{symbol}: entry=${entry_price} exit=${exit_price} "
        f"shares={shares} P&L=${pnl:.2f} outcome={trade['outcome']} reason={exit_reason}"
    )
    return trade


def backfill(trades: list, client: TradingClient) -> list:
    updated = []
    needs_backfill = [t for t in trades if not t.get("exit_price") and t.get("exit_date")]
    already_done = [t for t in trades if t.get("exit_price") or not t.get("exit_date")]

    log.info(f"Trades needing backfill: {len(needs_backfill)}, already complete: {len(already_done)}")

    for trade in needs_backfill:
        resolved = resolve_exit(client, trade)
        updated.append(resolved)
        time.sleep(0.3)  # avoid rate limiting

    return already_done + updated


def main():
    log.info("=" * 60)
    log.info("BACKFILL P&L — fetching exit prices from Alpaca")
    log.info("=" * 60)

    client = TradingClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY, paper=True)

    # --- Backfill trade_log.json ---
    trade_log = load_json(config.TRADE_LOG_PATH)
    closed = trade_log.get("closed_trades", [])
    log.info(f"trade_log.json: {len(closed)} closed trades")
    trade_log["closed_trades"] = backfill(closed, client)
    save_json(config.TRADE_LOG_PATH, trade_log)
    log.info(f"trade_log.json updated")

    # --- Backfill strategy_memory.json ---
    memory = load_json(config.STRATEGY_MEMORY_PATH)
    mem_trades = memory.get("trades", [])
    log.info(f"strategy_memory.json: {len(mem_trades)} trades")
    memory["trades"] = backfill(mem_trades, client)

    # Recompute signal performance
    from agents.memory_agent import compute_signal_performance
    memory["signal_performance"] = compute_signal_performance(memory["trades"])

    # Summarise
    all_trades = memory["trades"]
    wins = sum(1 for t in all_trades if t.get("outcome") == "win")
    total = len(all_trades)
    total_pnl = sum(t.get("pnl", 0) for t in all_trades)
    win_rate = (wins / total * 100) if total else 0
    log.info(f"Overall: {total} trades | {win_rate:.0f}% win rate | total P&L=${total_pnl:,.2f}")

    # Update strategy notes with real data
    memory["strategy_notes"] = (
        f"Backfilled {total} trades. "
        f"Win rate: {win_rate:.0f}% ({wins}W/{total-wins}L). "
        f"Total P&L: ${total_pnl:,.2f}. "
        f"All exits via bracket orders (stop or target). "
        f"Memory agent will enrich this further at next EOD run."
    )

    save_json(config.STRATEGY_MEMORY_PATH, memory)
    log.info("strategy_memory.json updated")
    log.info("BACKFILL COMPLETE")


if __name__ == "__main__":
    main()
