"""
Execution Agent: Places bracket orders and manages open positions.
Runs after strategy agent, then every 30 min intraday.
Never closes same-day positions.
"""
import json
from datetime import datetime, date, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import pandas as pd
import config
from strategy.signals import add_all_indicators, should_exit
from logger import get_logger

log = get_logger("execution")


def load_candidates() -> list:
    try:
        with open(config.CANDIDATES_PATH, "r") as f:
            data = json.load(f)
        return data.get("candidates", [])
    except FileNotFoundError:
        return []


def load_trade_log() -> dict:
    try:
        with open(config.TRADE_LOG_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"open_positions": {}, "closed_trades": []}


def save_trade_log(log_data: dict):
    with open(config.TRADE_LOG_PATH, "w") as f:
        json.dump(log_data, f, indent=2)


def get_open_positions(client: TradingClient) -> dict:
    positions = client.get_all_positions()
    return {p.symbol: p for p in positions}


def get_account(client: TradingClient):
    return client.get_account()


def fetch_bars_batch(symbols: list) -> dict:
    """Fetch 6 months of daily bars for multiple symbols in one API call."""
    if not symbols:
        return {}
    client_data = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    end = datetime.now()
    start = end - timedelta(days=config.BARS_LOOKBACK_DAYS)
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end
    )
    bars = client_data.get_stock_bars(request)
    multi_df = bars.df if hasattr(bars, 'df') else bars

    result = {}
    if isinstance(multi_df, pd.DataFrame) and not multi_df.empty:
        for symbol in symbols:
            try:
                df = multi_df.xs(symbol, level=0).copy() if multi_df.index.nlevels > 1 else multi_df.copy()
                if not df.empty:
                    result[symbol] = df
            except KeyError:
                pass
    log.debug(f"Batch bar fetch: got data for {len(result)}/{len(symbols)} symbols")
    return result


def place_bracket_order(client: TradingClient, candidate: dict) -> dict:
    """Place a bracket order (entry + stop + target)."""
    symbol = candidate["symbol"]
    shares = candidate["shares"]
    stop_loss = candidate["stop_loss"]
    take_profit = candidate["take_profit"]

    log.info(
        f"{symbol}: Placing bracket order — "
        f"{shares} shares @ ${candidate['entry']} | "
        f"stop=${stop_loss} | target=${take_profit} | "
        f"notional=${candidate['notional']}"
    )

    try:
        from alpaca.trading.requests import MarketOrderRequest
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=stop_loss),
            take_profit=TakeProfitRequest(limit_price=take_profit)
        )

        order = client.submit_order(order_data)
        log.info(f"{symbol}: Order submitted successfully — order_id={order.id}")

        return {
            "success": True,
            "order_id": str(order.id),
            "symbol": symbol,
            "shares": shares,
            "entry": candidate["entry"],
            "entry_price": candidate["entry"],
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "entry_date": str(date.today()),
            "reasoning": candidate.get("reasoning", ""),
            "signals": candidate.get("signals", {}),
            "signals_at_entry": candidate.get("signals", {}),
            "score": candidate.get("score", 0),
        }
    except Exception as e:
        log.error(f"{symbol}: Order failed — {e}")
        return {"success": False, "symbol": symbol, "error": str(e)}


def check_exit_signals(client: TradingClient, trade_log: dict):
    """Check if any open positions should be exited. Never closes same-day positions."""
    today = str(date.today())
    alpaca_positions = get_open_positions(client)

    log.info(f"Checking exit signals for {len(trade_log['open_positions'])} open positions...")

    symbols_to_check = [
        sym for sym, pos in trade_log["open_positions"].items()
        if pos.get("entry_date") != today and sym in alpaca_positions
    ]

    same_day = [
        sym for sym, pos in trade_log["open_positions"].items()
        if pos.get("entry_date") == today
    ]

    if same_day:
        log.info(f"Skipping same-day positions (no early exit): {same_day}")

    bars_by_symbol = fetch_bars_batch(symbols_to_check) if symbols_to_check else {}

    for symbol, position_data in list(trade_log["open_positions"].items()):
        entry_date = position_data.get("entry_date")

        if entry_date == today:
            continue

        if symbol not in alpaca_positions:
            log.info(f"{symbol}: Position no longer on Alpaca — bracket order filled (stop or target hit)")
            closed_trade = position_data.copy()
            closed_trade["exit_date"] = today
            closed_trade["exit_reason"] = "bracket_order_filled"
            trade_log["closed_trades"].append(closed_trade)
            del trade_log["open_positions"][symbol]
            continue

        try:
            df = bars_by_symbol.get(symbol)
            if df is None or df.empty:
                log.debug(f"{symbol}: no bar data for exit check")
                continue

            df = add_all_indicators(df)
            exit_signal = should_exit(df, position_data)

            if exit_signal["exit"]:
                log.info(f"{symbol}: EXIT signal triggered — reason={exit_signal['reason']}")
                alpaca_pos = alpaca_positions[symbol]
                sell_order = MarketOrderRequest(
                    symbol=symbol,
                    qty=abs(float(alpaca_pos.qty)),
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                client.submit_order(sell_order)

                closed_trade = position_data.copy()
                closed_trade["exit_date"] = today
                closed_trade["exit_reason"] = exit_signal["reason"]
                trade_log["closed_trades"].append(closed_trade)
                del trade_log["open_positions"][symbol]
                log.info(f"{symbol}: Sell order submitted")
            else:
                log.debug(f"{symbol}: holding — {exit_signal['reason']}")

        except Exception as e:
            log.warning(f"{symbol}: exit check error — {e}")
            continue


def run():
    """Main execution agent logic."""
    log.info("=" * 60)
    log.info("EXECUTION AGENT STARTING")
    log.info("=" * 60)

    client = TradingClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY, paper=True)

    candidates = load_candidates()
    trade_log = load_trade_log()

    account = get_account(client)
    buying_power = float(account.buying_power)
    portfolio_value = float(account.portfolio_value)
    log.info(f"Account — portfolio=${portfolio_value:,.2f}, buying_power=${buying_power:,.2f}")

    alpaca_positions = get_open_positions(client)
    log.info(f"Open positions on Alpaca: {list(alpaca_positions.keys()) or 'none'}")
    log.info(f"Tracked positions in log: {list(trade_log['open_positions'].keys()) or 'none'}")

    # Check exits first
    if trade_log["open_positions"]:
        check_exit_signals(client, trade_log)
    else:
        log.info("No open positions to check for exits")

    # Place new orders
    num_open = len(get_open_positions(client))
    slots_available = config.MAX_OPEN_POSITIONS - num_open
    log.info(f"Position slots: {num_open}/{config.MAX_OPEN_POSITIONS} used, {slots_available} available")

    if slots_available <= 0:
        log.info("Max positions reached — no new orders")
    elif not candidates:
        log.info("No qualified candidates — no new orders")
    else:
        log.info(f"Evaluating {len(candidates)} candidates for entry...")
        orders_placed = 0

        for candidate in candidates:
            if orders_placed >= slots_available:
                log.info(f"Position limit reached — stopping after {orders_placed} orders")
                break

            symbol = candidate["symbol"]

            if symbol in alpaca_positions or symbol in trade_log["open_positions"]:
                log.info(f"{symbol}: already have position — skipping")
                continue

            if candidate["notional"] > buying_power:
                log.warning(
                    f"{symbol}: insufficient buying power "
                    f"(need ${candidate['notional']:,.2f}, have ${buying_power:,.2f}) — skipping"
                )
                continue

            result = place_bracket_order(client, candidate)

            if result["success"]:
                trade_log["open_positions"][symbol] = result
                buying_power -= candidate["notional"]
                orders_placed += 1
                log.info(f"{symbol}: Position opened — {orders_placed}/{slots_available} slots used")
            else:
                log.error(f"{symbol}: Failed to place order — {result.get('error')}")

        log.info(f"New orders placed: {orders_placed}")

    save_trade_log(trade_log)
    log.info(f"Trade log saved — {len(trade_log['open_positions'])} open, {len(trade_log['closed_trades'])} closed")
    log.info("EXECUTION AGENT COMPLETE")
    return trade_log


if __name__ == "__main__":
    run()
