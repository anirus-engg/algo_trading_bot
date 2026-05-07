# Product

Self-learning swing trading agent for Alpaca paper trading.

## Purpose

Automate swing trading strategy execution with continuous learning from trade results. The agent scans stocks, identifies EMA pullback setups with momentum confirmation, executes trades via Alpaca, and learns from P&L to improve over time.

## Key Features

- Automated daily stock screening (200+ universe → top 25 watchlist)
- Multi-factor signal scoring (EMA, RSI, MACD, momentum, patterns)
- News sentiment integration via Claude
- Bracket order execution with trailing stops
- Self-learning memory system that evolves strategy based on real results
- Paper trading only (experimental, not real money)
