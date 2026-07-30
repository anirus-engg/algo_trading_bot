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
- Pre-market gap filter (9:15 AM): stocks must gap ≥ 1% from prior close
- Pre-market volume confirm (9:35 AM): opening bar volume must be ≥ 1.5x 20-day average
- Dual strategy scoring every 5 min on all 25 watchlist stocks:
  - **VWAP Reclaim**: price dips below VWAP then reclaims it with a bullish candle — detected within a 2-bar (10-min) lookback window; price must still be above VWAP at entry
  - **ORB Breakout**: price breaks above the 9:30–9:45 AM opening range high with a bullish candle (valid until 1:00 PM ET only)
- **Daily EMA trend gate**: daily EMA9 > EMA20 is a hard gate — stocks in a daily downtrend are rejected outright before any intraday scoring
- The 5-min EMA9/EMA20 relationship is a +2 bonus signal, not a hard gate
- Best qualifying setup per stock wins (higher score takes priority)
- Bracket order execution: setup-specific stops, 1.5:1 R:R target
- Exit signals checked every 5 min: VWAP break, EMA bearish cross, RSI exhaustion (> 75 and declining)
- Force close at 3:50 PM ET — no overnight holds
- Exit prices fetched from Alpaca order history; P&L and outcome computed and stored per trade
- Self-learning memory: Claude (Haiku) analyzes closed trades at 4:30 PM and updates strategy notes
- Daily summary email at 4:15 PM with per-trade P&L, exit prices, strategy type, and insights
- Paper trading only (experimental, not real money)

## Strategy Parameters

| Parameter | VWAP Reclaim | ORB Breakout |
|---|---|---|
| Candle timeframe | 5-minute | 5-minute |
| Entry trigger | Reclaim detected within last 2 bars (10 min); price still above VWAP | Close above opening range high with bullish candle |
| Daily EMA gate | Daily EMA9 > EMA20 — **hard gate, rejects daily downtrends** | Daily EMA9 > EMA20 — **hard gate, rejects daily downtrends** |
| 5-min EMA filter | EMA9 > EMA20 (+2 bonus, not required) | EMA9 > EMA20 (+2 bonus, not required) |
| RSI filter | 40–68 (+1 bonus, not required) | 40–72 (+1 bonus, not required) |
| Volume filter | ≥ 1.5x avg (+2), ≥ 1.0x avg (+1), < 1.0x (+0) | ≥ 1.5x avg (+2), ≥ 1.0x avg (+1), < 1.0x (+0) |
| Stop loss | 0.5x ATR (5-min) below entry | Below ORB low − 0.1x ATR |
| Take profit | 1.5:1 R:R | 1.5:1 R:R |
| Valid window | 9:45 AM – 3:50 PM ET | 9:45 AM – 1:00 PM ET |
| Min score to qualify | 4 | 4 |
| Max score | 9 | 9 |

## Scoring Breakdown

### VWAP Reclaim (max 9 points)
| Signal | Points | Type |
|---|---|---|
| VWAP reclaim detected within 2-bar lookback, price still above VWAP | +3 | Hard gate |
| Daily EMA9 > EMA20 | — | Hard gate (checked before scoring) |
| 5-min EMA9 > EMA20 | +2 | Bonus |
| RSI 40–68 | +1 | Bonus |
| Volume ≥ 1.5x avg | +2 | Bonus |
| Volume ≥ 1.0x avg | +1 | Bonus |
| Positive news sentiment | +1 | Bonus |

### ORB Breakout (max 9 points)
| Signal | Points | Type |
|---|---|---|
| Close above opening range high (bullish candle) | +3 | Hard gate |
| Daily EMA9 > EMA20 | — | Hard gate (checked before scoring) |
| 5-min EMA9 > EMA20 | +2 | Bonus |
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
| Stop ATR multiplier (VWAP) | 0.5x ATR below entry |
| Stop placement (ORB) | Below ORB low − 0.1x ATR |

## Universe & Watchlist Filters

| Parameter | Value |
|---|---|
| Universe | S&P 500 |
| Min price | $20 |
| Min ATR% (daily) | 1.5% |
| Universe size | Top 100 by avg daily dollar volume |
| Watchlist size | Top 25 by ATR%/volume |
| Min pre-market gap | ≥ 1% from prior close (9:15 AM filter) |
| Min opening volume | ≥ 1.5x 20-day avg for 9:30 AM bar (9:35 AM filter) |

## Daily Schedule (ET)

| Time | Agent | Action |
|---|---|---|
| 6:30 AM (Mon) | Universe Agent | Weekly S&P 500 refresh → universe.json |
| 8:00 AM | Watchlist Agent | Daily top 25 scan → watchlist.json |
| 8:30 AM | Research Agent | News scrape + Claude sentiment → research_brief.json |
| 9:15 AM | Watchlist Agent | Gap filter — stocks gapping ≥ 1% → intraday_watchlist.json |
| 9:35 AM | Watchlist Agent | Volume confirm — opening bar ≥ 1.5x avg → intraday_watchlist.json |
| 9:45 AM – 3:50 PM | Strategy + Execution | Every 5 min: score setups, place/manage orders, check exits |
| 3:50 PM | Execution Agent | Force close all positions, fetch exit prices, compute P&L |
| 4:15 PM | Email Agent | Daily summary email with P&L, exit prices, strategy type per trade |
| 4:30 PM | Memory Agent | Claude analyzes trades → strategy_memory.json |
| 4:30 PM | Watchlist Agent | EOD watchlist refresh for next day |

## Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| Daily EMA gate instead of 5-min EMA gate | 5-min EMA9/20 is too noisy — single bad candle flips it and blocks valid setups all day. Daily EMA is stable and reflects the real trend. |
| 2-bar VWAP reclaim lookback | Agent runs every 5 min; worst-case a reclaim fires at bar start and agent fires at next bar end — ~10 min lag. Lookback catches this without chasing stale setups. |
| Price must still be above VWAP at entry | Auto-invalidates reclaims where the stock dipped back below VWAP before agent fired. |
| ORB valid until 1:00 PM only | ORB setups go stale in the afternoon; breakouts after 1 PM lack the opening momentum context. |
| Exit P&L fetched from Alpaca order history | Bracket fills happen silently (stop or target); the bot queries filled sell orders to get actual exit price rather than estimating. |
| Volume as bonus, not hard gate | Early data showed wins on weak volume; sample too small to make it a hard gate. Monitored for future adjustment. |

## Tech Stack

| Component | Detail |
|---|---|
| Broker | Alpaca (paper trading) |
| Data feed | IEX (free tier, ~60% market volume) — daily bars use default feed |
| LLM | Claude Haiku (via Anthropic API) — sentiment, candidate reasoning, memory analysis |
| Language | Python 3.12 |
| Scheduling | `schedule` library via main.py (30s poll loop) |
| State | JSON files in data/ — no database |
