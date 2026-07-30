# Tech Stack

## Language & Runtime
- Python 3.12

## Frameworks & Libraries
- `alpaca-py` — broker API (orders, positions, market data)
- `anthropic` — Claude Haiku for sentiment analysis, candidate reasoning, and memory updates
- `pandas` — bar data manipulation and indicator computation
- `numpy` — numerical operations in signal functions
- `schedule` — lightweight job scheduler (30s poll loop in main.py)
- `python-dotenv` — loads secrets from .env

## Data & State
- JSON files in `data/` — no database
- `universe.json`, `watchlist.json`, `intraday_watchlist.json`, `candidates.json`, `trade_log.json`, `strategy_memory.json`

## External Services
- **Alpaca** — paper trading broker + IEX market data feed
- **Anthropic** — Claude Haiku API

## Common Commands

```bash
# Activate venv
source venv/bin/activate

# Start the agent
./start.sh

# Stop the agent
./stop.sh

# Run a specific agent manually
python -m agents.watchlist_agent
python -m agents.strategy_agent
python -m agents.execution_agent

# Backfill P&L for existing trades (one-time)
python backfill_pnl.py

# Test Alpaca connection
python test_connection.py
```

## Environment Variables (.env)
```
APCA_API_KEY_ID=
APCA_API_SECRET_KEY=
APCA_API_BASE_URL=https://paper-api.alpaca.markets
ANTHROPIC_API_KEY=
EMAIL_TO=
EMAIL_FROM=
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
```
