# Stock Trading Agent

Self-learning swing trading agent that integrates with Alpaca paper trading.

## Architecture

- **Watchlist Agent**: Scans 200+ stocks, scores by volume/volatility/news, outputs top 25
- **Research Agent**: Scrapes news, uses Claude to summarize sentiment
- **Strategy Agent**: EMA pullback + RSI + MACD + momentum scoring with pattern detection
- **Execution Agent**: Places bracket orders, manages exits (no same-day closes)
- **Memory Agent**: Analyzes closed trades, updates strategy notes (self-learning loop)

## Setup

1. Install dependencies:
```bash
./setup.sh
```

2. Set up environment variables in `.env`:
```
APCA_API_KEY_ID=your_key
APCA_API_SECRET_KEY=your_secret
APCA_API_BASE_URL=https://paper-api.alpaca.markets
ANTHROPIC_API_KEY=your_claude_key  # optional but recommended
```

3. Create log directory:
```bash
mkdir -p ~/.local/share/stockagent
```

## Usage

### Manual run (for testing):
```bash
source venv/bin/activate
python main.py
```

### Background service (auto-start on login):
```bash
./start.sh
```

View logs:
```bash
journalctl --user -u stockagent.service -f
```

Check status:
```bash
systemctl --user status stockagent.service
```

Stop the service:
```bash
./stop.sh
```

## Schedule

- **7:00am ET**: Watchlist scan
- **7:30am ET**: Research + news scraping
- **8:00am ET**: Strategy scoring
- **8:30am ET**: Execution (place orders)
- **Every 30 min (9am-4pm)**: Intraday position management
- **4:15pm ET**: Email daily summary
- **4:30pm ET**: Memory update (self-learning)

## Trading Rules

- Max position size: $5,000
- Max open positions: 5
- No same-day closes (swing trades only)
- 2:1 reward/risk ratio
- Trailing stop activates at 1x risk

## Strategy

EMA pullback with multi-factor scoring:
- 20 EMA > 50 EMA (uptrend required)
- Price pulls back to 20 EMA
- RSI 40-55 turning up
- MACD histogram turning positive
- ROC > 5% (momentum)
- Price above VWAP
- Bullish candle patterns
- Volume confirmation
- News sentiment

Minimum score of 5 to qualify.

## Self-Learning

All trades are logged with full signal context. After market close, the Memory Agent:
1. Computes win rates for each signal combination
2. Uses Claude to analyze what's working vs not
3. Updates strategy notes (cached in future strategy calls)
4. Sends daily email summary to aniruddhags@gmail.com
5. Agent evolves over time based on real P&L

See `EMAIL_SETUP.md` for configuring email reports.

## Files

- `config.py` - Configuration and constants
- `main.py` - Orchestrator
- `agents/` - All agent modules
- `strategy/signals.py` - Pure signal detection functions
- `data/` - JSON state files (watchlist, candidates, trade log, memory)

## .env file for reference: 
./.env
```

APCA_API_KEY_ID=
APCA_API_SECRET_KEY=
APCA_API_BASE_URL=
ANTHROPIC_API_KEY=

# Email settings (for daily summary reports)
EMAIL_TO
EMAIL_FROM=
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER-
SMTP_PASSWORD=

```
