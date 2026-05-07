#!/usr/bin/env python3
"""
Quick test to verify Alpaca connection and fetch sample data.
"""
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
import config

def test_trading_connection():
    """Test trading API connection."""
    print("Testing Alpaca Trading API connection...")
    try:
        client = TradingClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY, paper=True)
        account = client.get_account()
        print(f"✓ Connected to paper trading account")
        print(f"  Account ID: {account.id}")
        print(f"  Buying Power: ${float(account.buying_power):,.2f}")
        print(f"  Portfolio Value: ${float(account.portfolio_value):,.2f}")
        return True
    except Exception as e:
        print(f"✗ Trading API connection failed: {e}")
        return False

def test_data_connection():
    """Test market data API connection."""
    print("\nTesting Alpaca Market Data API connection...")
    try:
        client = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
        
        # Fetch sample bars for AAPL
        end = datetime.now()
        start = end - timedelta(days=5)
        
        request = StockBarsRequest(
            symbol_or_symbols=["AAPL"],
            timeframe=TimeFrame.Day,
            start=start,
            end=end
        )
        
        bars = client.get_stock_bars(request)
        df = bars.df if hasattr(bars, 'df') else bars
        
        print(f"✓ Market data API working")
        print(f"  Fetched {len(df)} bars for AAPL")
        if not df.empty:
            latest = df.iloc[-1]
            print(f"  Latest close: ${latest['close']:.2f}")
        return True
    except Exception as e:
        print(f"✗ Market data API connection failed: {e}")
        return False

def test_anthropic():
    """Test Anthropic API connection (optional)."""
    print("\nTesting Anthropic API connection...")
    if not config.ANTHROPIC_API_KEY:
        print("⚠ ANTHROPIC_API_KEY not set (optional)")
        return True
    
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=50,
            messages=[{"role": "user", "content": "Say 'API test successful' and nothing else."}]
        )
        
        print(f"✓ Anthropic API working")
        print(f"  Response: {response.content[0].text}")
        return True
    except Exception as e:
        print(f"✗ Anthropic API connection failed: {e}")
        return False

if __name__ == "__main__":
    print("="*60)
    print("Stock Trading Agent - Connection Test")
    print("="*60)
    print()
    
    results = []
    results.append(test_trading_connection())
    results.append(test_data_connection())
    results.append(test_anthropic())
    
    print()
    print("="*60)
    if all(results[:2]):  # Trading and data are required
        print("✓ All required connections successful!")
        print("\nYou can now run: python main.py")
    else:
        print("✗ Some connections failed. Check your API keys in .env")
    print("="*60)
