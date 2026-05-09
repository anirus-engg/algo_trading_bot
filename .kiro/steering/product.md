# Product

Self-learning **day trading** agent for Alpaca paper trading.

## Purpose

Automate intraday VWAP reclaim strategy execution with continuous learning from same-day trade results.
The agent scans stocks pre-market, identifies VWAP reclaim setups on 5-minute charts, executes trades
via Alpaca, and force-closes all positions by 3:50 PM ET. Learns from P&L to improve over time.

## Key Features

- Weekly universe refresh: S&P 500 filtered by price ≥ $20, ATR% ≥ 1.5%, top 100 by dollar volume
- Daily watchlist: top 25 from universe by ATR%/volume (8:00 AM)
- Pre-market gap filter: narrows to "in play" stocks via quote API (9:15 AM)
- Opening volume confirm: first 5-min bar vs 20-day average (9:35 AM)
- VWAP reclaim signal scoring: EMA9/20 trend + RSI + volume confirmation
- Bracket order execution: 0.5x ATR stop, 1.5:1 R:R target
- Force close at 3:50 PM ET — no overnight holds
- Self-learning memory system that evolves strategy based on same-day results
- Paper trading only (experimental, not real money)

## Strategy Parameters

| Parameter | Value |
|---|---|
| Candle timeframe | 5-minute |
| Setup | VWAP Reclaim |
| Entry filter | EMA9 > EMA20, RSI < 70, volume > avg |
| Stop loss | 0.5x ATR (5-min) below entry |
| Take profit | 1.5:1 R:R |
| Max position size | $5,000 |
| Max open positions | 5 |
| Trading window | 9:45 AM – 3:50 PM ET |
| Force close | 3:50 PM ET |
| Universe | S&P 500, price ≥ $20, ATR% ≥ 1.5%, top 100 |
