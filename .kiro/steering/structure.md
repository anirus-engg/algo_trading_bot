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
├── com.stockagent.plist      # macOS Launch Agent config
│
├── agents/                   # All agent modules
│   ├── watchlist_agent.py    # Scans universe, scores stocks
│   ├── research_agent.py     # Scrapes news, summarizes with Claude
│   ├── strategy_agent.py     # Scores setups, ranks candidates
│   ├── execution_agent.py    # Places orders, manages positions
│   └── memory_agent.py       # Analyzes trades, updates strategy memory
│
├── strategy/                 # Pure signal logic (no I/O)
│   ├── signals.py            # EMA, RSI, MACD, patterns, scoring
│   └── __init__.py
│
├── data/                     # JSON state files (gitignored)
│   ├── watchlist.json        # Top 25 stocks from watchlist agent
│   ├── research_brief.json   # News sentiment from research agent
│   ├── candidates.json       # Ranked trade candidates from strategy agent
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
Watchlist Agent → watchlist.json
                ↓
Research Agent → research_brief.json
                ↓
Strategy Agent → candidates.json
                ↓
Execution Agent → trade_log.json
                ↓
Memory Agent → strategy_memory.json (feeds back into Strategy Agent)
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
