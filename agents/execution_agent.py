"""
Execution Agent: Places bracket orders and manages open intraday positions.

Key rules:
  - Only enters during trading window: 9:45 AM – 3:50 PM ET
  - Force-closes ALL positions at 3:50 PM ET (no overnight holds)
  - Stop: 0.5x ATR (5-min) below entry
  - Target: 1.5:1 R:R
  - Checks exit signals (VWAP break, EMA cross, RSI exhaustion) every 5 min
  - Runs every 5 minutes via main.py scheduler
"""
import json
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import pandas as pd
import config
from strategy.signals import add_all_indicators, should_exit_intraday
from logger import get_logger

log = get_logger("execution")

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_candidates() -> list:
    try:
        with open(config.CANDIDATES_PATH) as f:
            data = json.load(f)
        return data.get("candidates", [])
    except FileNotFoundError:
        return []


def load_trade_log() -> dict:
    try:
        with open(config.TRADE_LOG_PATH) as f:
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


def fetch_intraday_bars_batch(symbols: list) -> dict:
    """Fetch 5-min bars for multiple symbols — used for exit signal checks."""
    if not symbols:
        return {}
    client_data = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    end = datetime.now(tz=ET)
    start = end - timedelta(days=config.INTRADAY_BARS_LOOKBACK_DAYS)

    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame(config.INTRADAY_TIMEFRAME_MINUTES, TimeFrameUnit.Minute),
            start=start,
            end=end,
            feed=config.INTRADAY_DATA_FEED,
        )
        bars = client_data.get_stock_bars(request)
        multi_df = bars.df if hasattr(bars, "df") else bars

        result = {}
        if isinstance(multi_df, pd.DataFrame) and not multi_df.empty:
            for symbol in symbols:
                try:
                    df = (multi_df.xs(symbol, level=0).copy()
                          if multi_df.index.nlevels > 1 else multi_df.copy())
                    if not df.empty:
                        result[symbol] = df
                except KeyError:
                    pass

        log.debug(f"5-min bar fetch: got data for {len(result)}/{len(symbols)} symbols")
        return result

    except Exception as e:
        log.warning(f"5-min bar fetch failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Trading window helpers
# ---------------------------------------------------------------------------

def is_within_trading_window() -> bool:
    """
    Returns True if current ET time is within the active trading window:
    9:45 AM – 3:50 PM ET.
    """
    now = datetime.now(tz=ET).time()
    start = datetime.now(tz=ET).replace(
        hour=config.TRADING_START_HOUR,
        minute=config.TRADING_START_MINUTE,
        second=0, microsecond=0
    ).time()
    end = datetime.now(tz=ET).replace(
        hour=config.FORCE_CLOSE_HOUR,
        minute=config.FORCE_CLOSE_MINUTE,
        second=0, microsecond=0
    ).time()
    return start <= now <= end


def is_force_close_time() -> bool:
    """Returns True if it's time to force-close all positions (>= 3:50 PM ET)."""
    now = datetime.now(tz=ET).time()
    close_time = datetime.now(tz=ET).replace(
        hour=config.FORCE_CLOSE_HOUR,
        minute=config.FORCE_CLOSE_MINUTE,
        second=0, microsecond=0
    ).time()
    return now >= close_time


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def place_bracket_order(client: TradingClient, candidate: dict) -> dict:
    """Place a bracket order (entry + stop + target) for an intraday position."""
    symbol = candidate["symbol"]
    shares = candidate["shares"]
    stop_loss = candidate["stop_loss"]
    take_profit = candidate["take_profit"]

    log.info(
        f"{symbol}: Placing bracket order — "
        f"{shares} shares @ ${candidate['entry']} | "
        f"stop=${stop_loss} | target=${take_profit} | "
        f"notional=${candidate['notional']} | "
        f"R:R=1.5:1 | stop_atr=0.5x"
    )

    try:
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
        log.info(f"{symbol}: Order submitted — order_id={order.id}")

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
            "entry_time": datetime.now(tz=ET).strftime("%H:%M"),
            "reasoning": candidate.get("reasoning", ""),
            "signals": candidate.get("signals", {}),
            "signals_at_entry": candidate.get("signals", {}),
            "score": candidate.get("score", 0),
            "vwap_at_entry": candidate.get("vwap"),
            "gap_pct": candidate.get("gap_pct"),
            "open_vol_ratio": candidate.get("open_vol_ratio"),
        }
    except Exception as e:
        log.error(f"{symbol}: Order failed — {e}")
        return {"success": False, "symbol": symbol, "error": str(e)}


# ---------------------------------------------------------------------------
# Force close
# ---------------------------------------------------------------------------

def force_close_all_positions(client: TradingClient, trade_log: dict):
    """
    Force-close all open positions at 3:50 PM ET.
    Cancels any open bracket orders first, then submits market sell orders.
    """
    log.info("FORCE CLOSE — 3:50 PM ET — flattening all positions")

    alpaca_positions = get_open_positions(client)
    today = str(date.today())

    if not alpaca_positions:
        log.info("No open positions to close")
        # Clean up any stale tracked positions
        for symbol in list(trade_log["open_positions"].keys()):
            closed = trade_log["open_positions"].pop(symbol)
            closed["exit_date"] = today
            closed["exit_time"] = datetime.now(tz=ET).strftime("%H:%M")
            closed["exit_reason"] = "force_close_eod_no_position"
            trade_log["closed_trades"].append(closed)
        return

    # Cancel all open orders first to avoid bracket order conflicts
    try:
        client.cancel_orders()
        log.info("All open orders cancelled before force close")
    except Exception as e:
        log.warning(f"Could not cancel open orders: {e}")

    for symbol, alpaca_pos in alpaca_positions.items():
        qty = abs(float(alpaca_pos.qty))
        if qty <= 0:
            continue

        try:
            sell_order = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            client.submit_order(sell_order)
            log.info(f"{symbol}: Force-close sell order submitted ({qty} shares)")

            # Update trade log
            if symbol in trade_log["open_positions"]:
                closed = trade_log["open_positions"].pop(symbol)
            else:
                closed = {"symbol": symbol, "shares": qty, "entry_date": today}

            closed["exit_date"] = today
            closed["exit_time"] = datetime.now(tz=ET).strftime("%H:%M")
            closed["exit_reason"] = "force_close_eod"
            trade_log["closed_trades"].append(closed)

        except Exception as e:
            log.error(f"{symbol}: Force-close failed — {e}")

    log.info("Force close complete")


# ---------------------------------------------------------------------------
# Exit signal checks
# ---------------------------------------------------------------------------

def check_exit_signals(client: TradingClient, trade_log: dict):
    """
    Check open positions for intraday exit signals every 5 minutes.
    Exits on: VWAP break, bearish EMA cross, RSI exhaustion.
    """
    today = str(date.today())
    alpaca_positions = get_open_positions(client)

    if not trade_log["open_positions"]:
        log.debug("No open positions to check for exits")
        return

    log.info(f"Checking exit signals for {len(trade_log['open_positions'])} open positions...")

    symbols_to_check = [
        sym for sym in trade_log["open_positions"]
        if sym in alpaca_positions
    ]

    # Detect positions closed by bracket orders (stop or target hit)
    for symbol in list(trade_log["open_positions"].keys()):
        if symbol not in alpaca_positions:
            log.info(f"{symbol}: No longer on Alpaca — bracket order filled (stop or target hit)")
            closed = trade_log["open_positions"].pop(symbol)
            closed["exit_date"] = today
            closed["exit_time"] = datetime.now(tz=ET).strftime("%H:%M")
            closed["exit_reason"] = "bracket_order_filled"
            trade_log["closed_trades"].append(closed)

    if not symbols_to_check:
        return

    bars_by_symbol = fetch_intraday_bars_batch(symbols_to_check)

    for symbol in symbols_to_check:
        if symbol not in trade_log["open_positions"]:
            continue  # already closed above

        position_data = trade_log["open_positions"][symbol]

        try:
            df = bars_by_symbol.get(symbol)
            if df is None or df.empty:
                log.debug(f"{symbol}: no 5-min bar data for exit check")
                continue

            df = add_all_indicators(df)
            exit_signal = should_exit_intraday(df, position_data)

            if exit_signal["exit"]:
                log.info(f"{symbol}: EXIT signal — reason={exit_signal['reason']}")
                alpaca_pos = alpaca_positions[symbol]
                sell_order = MarketOrderRequest(
                    symbol=symbol,
                    qty=abs(float(alpaca_pos.qty)),
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                client.submit_order(sell_order)

                closed = trade_log["open_positions"].pop(symbol)
                closed["exit_date"] = today
                closed["exit_time"] = datetime.now(tz=ET).strftime("%H:%M")
                closed["exit_reason"] = exit_signal["reason"]
                trade_log["closed_trades"].append(closed)
                log.info(f"{symbol}: Sell order submitted")
            else:
                log.debug(f"{symbol}: holding — {exit_signal['reason']}")

        except Exception as e:
            log.warning(f"{symbol}: exit check error — {e}")
            continue


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    """
    Main execution agent logic.
    Called every 5 minutes during trading hours by main.py.
    """
    now_et = datetime.now(tz=ET)
    log.info("=" * 60)
    log.info(f"EXECUTION AGENT — {now_et.strftime('%H:%M ET')}")
    log.info("=" * 60)

    client = TradingClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY, paper=True)
    trade_log = load_trade_log()

    account = get_account(client)
    buying_power = float(account.buying_power)
    portfolio_value = float(account.portfolio_value)
    log.info(f"Account — portfolio=${portfolio_value:,.2f}, buying_power=${buying_power:,.2f}")

    alpaca_positions = get_open_positions(client)
    log.info(f"Open positions on Alpaca: {list(alpaca_positions.keys()) or 'none'}")

    # --- Force close at 3:50 PM ---
    if is_force_close_time():
        log.info("3:50 PM ET — initiating force close of all positions")
        force_close_all_positions(client, trade_log)
        save_trade_log(trade_log)
        log.info("EXECUTION AGENT COMPLETE (force close)")
        return trade_log

    # --- Check exit signals on open positions ---
    if trade_log["open_positions"]:
        check_exit_signals(client, trade_log)
    else:
        log.info("No open positions to check for exits")

    # --- Enter new positions (only within trading window) ---
    if not is_within_trading_window():
        log.info(
            f"Outside trading window "
            f"({config.TRADING_START_HOUR}:{config.TRADING_START_MINUTE:02d}–"
            f"{config.FORCE_CLOSE_HOUR}:{config.FORCE_CLOSE_MINUTE:02d} ET) "
            f"— no new entries"
        )
        save_trade_log(trade_log)
        return trade_log

    candidates = load_candidates()
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
    log.info(
        f"Trade log saved — "
        f"{len(trade_log['open_positions'])} open, "
        f"{len(trade_log['closed_trades'])} closed"
    )
    log.info("EXECUTION AGENT COMPLETE")
    return trade_log


if __name__ == "__main__":
    run()
