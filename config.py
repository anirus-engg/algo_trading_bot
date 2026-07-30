import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca
APCA_API_KEY_ID = os.getenv("APCA_API_KEY_ID")
APCA_API_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
APCA_API_BASE_URL = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# claude-3-5-haiku-20241022 — fast, cheap, good for sentiment + memory
# claude-3-5-sonnet-20241022 — higher quality, use if memory/reasoning quality degrades
ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"

# Email settings
EMAIL_TO = os.getenv("EMAIL_TO", "aniruddhags@gmail.com")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# ---------------------------------------------------------------------------
# Trading rules — Day Trading
# ---------------------------------------------------------------------------
MAX_POSITION_SIZE = 5000.0          # max notional per position ($)
MIN_SIGNAL_SCORE = 4                # minimum score to qualify as a candidate
REWARD_RISK_RATIO = 1.5             # 1.5:1 R:R target
MAX_OPEN_POSITIONS = 5

# VWAP reclaim lookback: how many bars back to search for a reclaim candle.
# 2 bars = 10 min, covering the worst-case scheduling gap between reclaim and agent fire.
# Price must still be above VWAP at current bar — stale reclaims are auto-invalidated.
VWAP_RECLAIM_LOOKBACK_BARS = 2

# Stop loss: 0.5x ATR (5-min) below entry candle low
STOP_ATR_MULTIPLIER = 0.5

# Force-close all positions at this time (ET) — no overnight holds
FORCE_CLOSE_HOUR = 15               # 3 PM ET
FORCE_CLOSE_MINUTE = 50            # 3:50 PM ET

# Trading window (ET) — no entries before 9:45 AM
TRADING_START_HOUR = 9
TRADING_START_MINUTE = 45

# Opening range: first 15 min (9:30–9:45) — observe only, no entries
OPENING_RANGE_MINUTES = 15

# ---------------------------------------------------------------------------
# Universe filters
# ---------------------------------------------------------------------------
MIN_STOCK_PRICE = 20.0              # minimum price filter ($)
MIN_ATR_PCT = 1.5                   # minimum ATR% (daily) for day trading
UNIVERSE_SIZE = 100                 # top N by avg daily dollar volume

# ---------------------------------------------------------------------------
# Intraday bar settings
# ---------------------------------------------------------------------------
INTRADAY_TIMEFRAME_MINUTES = 5      # 5-min candles
INTRADAY_BARS_LOOKBACK_DAYS = 10    # days of 5-min history for indicators
DAILY_BARS_LOOKBACK_DAYS = 45       # days of daily bars for ATR/universe scoring (approx 30 trading days)
DAILY_EMA_FAST = 9                  # daily EMA fast period — used as hard trend gate
DAILY_EMA_SLOW = 20                 # daily EMA slow period — used as hard trend gate

# Alpaca data feed for intraday bars
# "iex" — free, works on Basic plan (~60% of market volume, fine for paper trading)
# "sip" — full market data, requires Algo Trader Plus ($99/mo) or Unlimited plan
# To upgrade: change this to "sip" after upgrading your Alpaca subscription
INTRADAY_DATA_FEED = "iex"

# Legacy alias used by universe/watchlist agents
BARS_LOOKBACK_DAYS = DAILY_BARS_LOOKBACK_DAYS

# ---------------------------------------------------------------------------
# Watchlist / pre-market filters
# ---------------------------------------------------------------------------
WATCHLIST_SIZE = 25
MIN_GAP_PCT = 1.0               # minimum gap % from prior close to pass gap filter (9:15 AM)
MIN_RELATIVE_VOLUME = 1.5       # minimum opening bar volume ratio to pass volume confirm (9:35 AM)

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
DATA_DIR = "data"
WATCHLIST_PATH = f"{DATA_DIR}/watchlist.json"
INTRADAY_WATCHLIST_PATH = f"{DATA_DIR}/intraday_watchlist.json"
RESEARCH_BRIEF_PATH = f"{DATA_DIR}/research_brief.json"
CANDIDATES_PATH = f"{DATA_DIR}/candidates.json"
TRADE_LOG_PATH = f"{DATA_DIR}/trade_log.json"
STRATEGY_MEMORY_PATH = f"{DATA_DIR}/strategy_memory.json"

# ---------------------------------------------------------------------------
# Schedule times (ET)
# ---------------------------------------------------------------------------
# Weekly universe refresh — Monday pre-market
UNIVERSE_HOUR = 6
UNIVERSE_MINUTE = 30

# Daily watchlist scan — pre-market
WATCHLIST_HOUR = 8
WATCHLIST_MINUTE = 0

# Research / news — after watchlist
RESEARCH_HOUR = 8
RESEARCH_MINUTE = 30

# Intraday execution polling — every 5 min from 9:45 AM to 3:50 PM
EXECUTION_INTERVAL_MINUTES = 5

# EOD
EMAIL_HOUR = 16
EMAIL_MINUTE = 15
MEMORY_HOUR = 16
MEMORY_MINUTE = 30
WATCHLIST_EOD_HOUR = 16
WATCHLIST_EOD_MINUTE = 30
