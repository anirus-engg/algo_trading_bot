# Quick Start Guide

## 1. Setup (one time)

```bash
# Run setup script (creates venv and installs dependencies)
./setup.sh

# Add your Anthropic API key to .env (optional but recommended)
# Edit .env and add: ANTHROPIC_API_KEY=your_key_here
```

## 2. Test Connection

```bash
# Activate virtual environment first
source venv/bin/activate

# Run test
python test_connection.py
```

This verifies:
- ✓ Alpaca paper trading account access
- ✓ Market data API working
- ✓ Anthropic API (optional)

## 3. Run Manually (Testing)

```bash
# Activate virtual environment
source venv/bin/activate

# Run main script
python main.py
```

This will:
1. Run the full morning sequence immediately
2. Then wait for scheduled times
3. Press Ctrl+C to stop

Watch it execute:
- Watchlist Agent scans 200+ stocks
- Research Agent scrapes news
- Strategy Agent scores setups
- Execution Agent places orders

## 4. Run as Background Service

```bash
# Start (runs on schedule, auto-restarts on crash, starts on login)
./start.sh

# View logs in real-time
journalctl --user -u stockagent.service -f

# Check status
systemctl --user status stockagent.service

# Stop
./stop.sh
```

## 5. Check Results

```bash
# View today's watchlist
cat data/watchlist.json

# View trade candidates
cat data/candidates.json

# View open positions and closed trades
cat data/trade_log.json

# View strategy memory (self-learning)
cat data/strategy_memory.json
```

## 6. Monitor in Alpaca Dashboard

Go to your Alpaca paper trading dashboard to see:
- Orders placed
- Open positions
- Trade history
- P&L

## Daily Schedule

- **7:00am ET**: Watchlist scan
- **7:30am ET**: Research + news
- **8:00am ET**: Strategy scoring
- **8:30am ET**: Place orders
- **Every 30 min (9am-4pm)**: Position management
- **4:15pm ET**: Email daily summary to aniruddhags@gmail.com
- **4:30pm ET**: Memory update (learns from closed trades)

## Troubleshooting

**No trades being placed?**
- Check that candidates have score >= 5 in `data/candidates.json`
- Verify buying power in Alpaca dashboard
- Check logs for errors

**Agent not starting?**
- Run `./stop.sh` then `./start.sh` again
- Check logs: `journalctl --user -u stockagent.service -n 50`
- Check systemd status: `systemctl --user status stockagent.service`

**Want to adjust strategy?**
- Edit `config.py` for position size, max positions, etc.
- Edit `strategy/signals.py` for signal logic
- Restart the agent after changes

## Next Steps

After a few days of trading:
1. Check your email at 4:15 PM ET for daily summaries
2. Review `data/strategy_memory.json` to see what the agent learned
3. Check closed trades and P&L in your Alpaca dashboard
4. The agent will automatically adjust its strategy based on results
5. Monitor the "strategy_notes" field to see Claude's insights

**To enable email reports**: See `EMAIL_SETUP.md` for Gmail setup instructions.

## Safety Notes

- This is **paper trading only** (no real money)
- Max position size: $5,000
- Max open positions: 5
- No same-day closes (swing trades only)
- All trades logged with full reasoning for review
