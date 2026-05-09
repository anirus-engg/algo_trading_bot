# Project Structure

```
algo_trading_bot/
├── .env                      # API keys (gitignored)
├── .gitignore
├── requirements.txt
├── README.md
├── config.py                 # Central configuration
├── main.py                   # Orchestrator (chains agents on schedule)
├── start.sh / stop.sh        # Service control scripts
│
├── agents/                   # All agent modules
│   ├── universe_agent.py     # Weekly S&P 500 refresh → top 100 by dollar volume
│   ├── watchlist_agent.py    # Daily top 25 + pre-market gap/volume filter
│   ├── research_agent.py     # Scrapes news, summarizes with Claude
│   ├── strategy_agent.py     # Scores VWAP reclaim setups on 5-min bars
│   ├── execution_agent.py    # Places orders, manages positions, force close 3:50 PM
│   └── memory_agent.py       # Analyzes trades, updates strategy memory
│
├── strategy/                 # Pure signal logic (no I/O)
│   ├── signals.py            # EMA9/20, RSI, ATR, VWAP, VWAP reclaim scoring
│   └── __init__.py
│
├── data/                     # JSON state files (gitignored)
│   ├── universe.json         # Top 100 S&P 500 stocks (weekly refresh)
│   ├── watchlist.json        # Top 25 stocks from daily scan
│   ├── intraday_watchlist.json  # 5–12 "in play" stocks after gap+volume filter
│   ├── research_brief.json   # News sentiment from research agent
│   ├── candidates.json       # Ranked VWAP reclaim candidates
│   ├── trade_log.json        # Open positions + closed trades
│   └── strategy_memory.json  # Self-learning memory (all trades + notes)
│
└── .kiro/
    └── steering/             # AI assistant guidance
        ├── product.md
        ├── tech.md
        └── structure.md
```

## Conventions

### Agent Design
- Each agent is a standalone module with a `run()` function
- Agents read from JSON files (previous agent's output)
- Agents write to JSON files (next agent's input)
- No shared state except via JSON files
- Pure functions in `strategy/signals.py` (testable, no side effects)

### Data Flow
```
Universe Agent (weekly) → universe.json (top 100 S&P 500)
                ↓
Watchlist Agent (8:00 AM) → watchlist.json (top 25 by ATR%/volume)
                ↓
Gap Filter (9:15 AM) → intraday_watchlist.json (gap > 1% from prior close)
                ↓
Volume Confirm (9:35 AM) → intraday_watchlist.json (first 5-min bar volume > 1.5x avg)
                ↓
Strategy Agent (every 5 min) → candidates.json (VWAP reclaim setups scored)
                ↓
Execution Agent (every 5 min) → trade_log.json (bracket orders, exits, force close 3:50 PM)
                ↓
Memory Agent (4:30 PM EOD) → strategy_memory.json (feeds back into Strategy Agent)
```

### Configuration
- All constants in `config.py`
- Secrets in `.env` (never committed)
- Schedule times configurable per agent

### Logging
- Print statements with timestamps for visibility
- macOS Launch Agent logs to `~/Library/Logs/stockagent/`

### Self-Learning
- `strategy_memory.json` is the living knowledge base
- Cached in Claude prompts (token efficiency)
- Updated after every closed trade
- Informs future strategy decisions
