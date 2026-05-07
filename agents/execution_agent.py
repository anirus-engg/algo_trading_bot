"""
Execution Agent: Places bracket orders and manages open positions.
Runs after strategy agent, then every 30 min intraday.
Never closes same-day positions.
"""
import json
from datetime import datetime, date
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import pandas as pd
import config
from strategy.signals import add_all_indicators, should_exit


def load_candidates() -> list:
    """Load trade candidates."""
    try:
        with open(config.CANDIDATES_PATH, "r") as f:
            data = json.load(f)
        return data.get("candidates", [])
    except FileNotFoundError:
        return []


def load_trade_log() -> dict:
    """Load trade log."""
    try:
        with open(config.TRADE_LOG_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"open_positions": {}, "closed_trades": []}


def save_trade_log(log: dict):
    """Save trade log."""
    with open(config.TRADE_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def get_open_positions(client: TradingClient) -> dict:
    """Get current open positions from Alpaca."""
    positions = client.get_all_positions()
    return {p.symbol: p for p in positions}


def get_account(client: TradingClient):
    """Get account info."""
    return client.get_account()


def place_bracket_order(client: TradingClient, candidate: dict) -> dict:
    """Place a bracket order (entry + stop + target)."""
    symbol = candidate["symbol"]
    shares = candidate["shares"]
    stop_loss = candidate["stop_loss"]
    take_profit = candidate["take_profit"]
    
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
        
        return {
            "success": True,
            "order_id": str(order.id),
            "symbol": symbol,
            "shares": shares,
            "entry": candidate["entry"],
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "entry_date": str(date.today()),
            "reasoning": candidate.get("reasoning", ""),
            "signals": candidate.get("signals", {}),
        }
    except Exception as e:
        return {"success": False, "symbol": symbol, "error": str(e)}


def fetch_bars_batch(symbols: list) -> dict:
    """Fetch daily bars for multiple symbols in one API call."""
    if not symbols:
        return {}
    client_data = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        limit=60
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
    return result


def check_exit_signals(client: TradingClient, log: dict):
    """Check if any open positions should be exited (no same-day closes)."""
    today = str(date.today())
    alpaca_positions = get_open_positions(client)

    # Batch fetch bars for all open positions in one call
    symbols_to_check = [
        sym for sym, pos in log["open_positions"].items()
        if pos.get("entry_date") != today and sym in alpaca_positions
    ]

    bars_by_symbol = fetch_bars_batch(symbols_to_check) if symbols_to_check else {}

    for symbol, position_data in list(log["open_positions"].items()):
        entry_date = position_data.get("entry_date")

        # Never close same-day
        if entry_date == today:
            continue

        # Check if position still exists on Alpaca
        if symbol not in alpaca_positions:
            closed_trade = position_data.copy()
            closed_trade["exit_date"] = today
            closed_trade["exit_reason"] = "bracket_order_filled"
            log["closed_trades"].append(closed_trade)
            del log["open_positions"][symbol]
            print(f"  {symbol}: Position closed via bracket order")
            continue

        # Check exit signals using batched bar data
        try:
            df = bars_by_symbol.get(symbol)
            if df is None or df.empty:
                continue

            df = add_all_indicators(df)
            exit_signal = should_exit(df, position_data)

            if exit_signal["exit"]:
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
                log["closed_trades"].append(closed_trade)
                del log["open_positions"][symbol]

                print(f"  {symbol}: Exit signal triggered ({exit_signal['reason']})")

        except Exception as e:
            print(f"  Error checking exit for {symbol}: {e}")
            continue


def run():
    """Main execution agent logic."""
    print(f"[{datetime.now()}] Execution Agent: Starting...")
    
    client = TradingClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY, paper=True)
    
    # Load state
    candidates = load_candidates()
    log = load_trade_log()
    
    # Check account
    account = get_account(client)
    buying_power = float(account.buying_power)
    print(f"  Buying power: ${buying_power:,.2f}")
    
    # Check existing positions
    alpaca_positions = get_open_positions(client)
    num_open = len(alpaca_positions)
    print(f"  Open positions: {num_open}")
    
    # Check exit signals for open positions
    if log["open_positions"]:
        print(f"[{datetime.now()}] Execution Agent: Checking exit signals...")
        check_exit_signals(client, log)
    
    # Place new orders if we have room
    if num_open < config.MAX_OPEN_POSITIONS and candidates:
        print(f"[{datetime.now()}] Execution Agent: Placing new orders...")
        
        for candidate in candidates:
            if num_open >= config.MAX_OPEN_POSITIONS:
                break
            
            symbol = candidate["symbol"]
            
            # Skip if already have position
            if symbol in alpaca_positions or symbol in log["open_positions"]:
                continue
            
            # Check buying power
            if candidate["notional"] > buying_power:
                continue
            
            # Place order
            result = place_bracket_order(client, candidate)
            
            if result["success"]:
                log["open_positions"][symbol] = result
                buying_power -= candidate["notional"]
                num_open += 1
                print(f"  {symbol}: Order placed ({candidate['shares']} shares @ ${candidate['entry']})")
            else:
                print(f"  {symbol}: Order failed - {result.get('error')}")
    
    # Save log
    save_trade_log(log)
    
    print(f"[{datetime.now()}] Execution Agent: Complete")
    
    return log


if __name__ == "__main__":
    run()
