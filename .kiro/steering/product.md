# Product

Self-learning **day trading** agent for Alpaca paper trading.

## Purpose

Automate intraday strategy execution with continuous learning from same-day trade results.
The agent scans stocks pre-market, identifies VWAP Reclaim and ORB Breakout setups on 5-minute
charts, executes trades via Alpaca, and force-closes all positions by 3:50 PM ET. Learns from
P&L after each session to improve over time.

## Key Features

- Weekly universe refresh: S&P 500 filtered by price ≥ $20, ATR% ≥ 1.5%, top 100 by dollar volume
- Daily watchlist: top 25 from universe by ATR%/volume (8:00 AM)
- Dual strategy scoring every 5 min on all 25 watchlist stocks:
  - **VWAP Reclaim**: price dips below VWAP then reclaims it with a bullish candle
  - **ORB Breakout**: price breaks above the 9:30–9:45 AM opening range high with a bullish candle (valid until 1:00 PM ET only)
- Both setups require **daily EMA9 > EMA20** — stocks in a daily downtrend are rejected outright before intraday scoring
- The 5-min EMA9/EMA20 is a +2 bonus signal, not a hard gate
- Best qualifying setup per stock wins (higher score takes priority)
- Bracket order execution: setup-specific stops, 1.5:1 R:R target
- Force close at 3:50 PM ET — no overnight holds
- Self-learning memory: Claude (Haiku) analyzes closed trades at 4:30 PM and updates strategy notes
- Daily summary email at 4:15 PM with P&L, exit prices, and strategy insights per trade
- Paper trading only (experimental, not real money)

## Strategy Parameters

| Parameter | VWAP Reclaim | ORB Breakout |
|---|---|---|
| Candle timeframe | 5-minute | 5-minute |
| Entry trigger | Prev candle below VWAP, current candle closes above VWAP (bullish) | Current candle closes above opening range high (bullish) |
| EMA filter | **Daily EMA9 > EMA20** (hard gate) + 5-min EMA9 > EMA20 (+2 bonus) | **Daily EMA9 > EMA20** (hard gate) + 5-min EMA9 > EMA20 (+2 bonus) |
| RSI filter | 40–68 (bonus, not required) | 40–72 (bonus, not required) |
| Volume filter | Above 20-bar avg (bonus, not required) | Above 20-bar avg (bonus, not required) |
| Stop loss | 0.5x ATR (5-min) below entry | Below ORB low − 0.1x ATR |
| Take profit | 1.5:1 R:R | 1.5:1 R:R |
| Valid window | 9:45 AM – 3:50 PM ET | 9:45 AM – 1:00 PM ET |
| Min score to qualify | 4 | 4 |
| Max score | 9 | 9 |

## Scoring Breakdown

### VWAP Reclaim (max 9 points)
| Signal | Points | Type |
|---|---|---|
| VWAP reclaim pattern detected | +3 | Hard gate |
| EMA9 > EMA20 (uptrend) | +2 | Hard gate |
| RSI 40–68 | +1 | Bonus |
| Volume ≥ 1.5x avg | +2 | Bonus |
| Volume ≥ 1.0x avg | +1 | Bonus |
| Positive news sentiment | +1 | Bonus |

### ORB Breakout (max 9 points)
| Signal | Points | Type |
|---|---|---|
| Close above opening range high (bullish candle) | +3 | Hard gate |
| EMA9 > EMA20 (uptrend) | +2 | Hard gate |
| RSI 40–72 | +1 | Bonus |
| Volume ≥ 1.5x avg | +2 | Bonus |
| Volume ≥ 1.0x avg | +1 | Bonus |
| Positive news sentiment | +1 | Bonus |

## Position & Risk Rules

| Parameter | Value |
|---|---|
| Max position size | $5,000 notional |
| Max open positions | 5 |
| Trading window | 9:45 AM – 3:50 PM ET |
| Force close | 3:50 PM ET (no overnight holds) |
| Reward:Risk ratio | 1.5:1 |

## Universe Filters

| Parameter | Value |
|---|---|
| Universe | S&P 500 |
| Min price | $20 |
| Min ATR% (daily) | 1.5% |
| Universe size | Top 100 by avg daily dollar volume |
| Watchlist size | Top 25 by ATR%/volume |

## Daily Schedule (ET)

| Time | Agent | Action |
|---|---|---|
| 6:30 AM (Mon) | Universe Agent | Weekly S&P 500 refresh → universe.json |
| 8:00 AM | Watchlist Agent | Daily top 25 scan → watchlist.json |
| 8:30 AM | Research Agent | News scrape + Claude sentiment → research_brief.json |
| 9:45 AM – 3:50 PM | Strategy + Execution | Every 5 min: score setups, place/manage orders |
| 3:50 PM | Execution Agent | Force close all positions |
| 4:15 PM | Email Agent | Daily summary email with P&L and insights |
| 4:30 PM | Memory Agent | Claude analyzes trades → strategy_memory.json |

## Tech Stack

| Component | Detail |
|---|---|
| Broker | Alpaca (paper trading) |
| Data feed | IEX (free tier, ~60% market volume) |
| LLM | Claude Haiku (via Anthropic API) — sentiment, reasoning, memory |
| Language | Python 3 |
| Scheduling | APScheduler via main.py |
