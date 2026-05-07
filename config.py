import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca
APCA_API_KEY_ID = os.getenv("APCA_API_KEY_ID")
APCA_API_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
APCA_API_BASE_URL = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Email settings
EMAIL_TO = os.getenv("EMAIL_TO", "aniruddhags@gmail.com")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# Trading rules
MAX_POSITION_SIZE = 5000.0
MIN_SIGNAL_SCORE = 5
REWARD_RISK_RATIO = 2.0
TRAILING_STOP_ACTIVATION_R = 1.0  # activate trailing stop at 1x risk
MAX_OPEN_POSITIONS = 5

# Universe to scan
SCAN_UNIVERSE = [
    # Large-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "INTC", "CRM",
    "ORCL", "ADBE", "QCOM", "TXN", "AVGO", "MU", "AMAT", "LRCX", "KLAC", "MRVL",
    # Finance
    "JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW", "AXP", "V", "MA", "PYPL",
    # Healthcare
    "UNH", "JNJ", "PFE", "ABBV", "MRK", "LLY", "TMO", "DHR", "ABT", "AMGN",
    # Consumer
    "AMZN", "HD", "MCD", "NKE", "SBUX", "TGT", "WMT", "COST", "LOW", "TJX",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "PXD", "MPC", "VLO", "PSX", "OXY",
    # ETFs (broad market + sector)
    "SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "GLD",
    # High-momentum mid-caps
    "PANW", "CRWD", "SNOW", "DDOG", "NET", "ZS", "FTNT", "OKTA", "MDB", "GTLB",
    "UBER", "LYFT", "ABNB", "DASH", "COIN", "HOOD", "SOFI", "AFRM", "UPST", "SQ",
    # Industrials / macro
    "CAT", "DE", "BA", "LMT", "RTX", "GE", "HON", "MMM", "UPS", "FDX",
    # Semis / AI plays
    "ARM", "SMCI", "PLTR", "AI", "IONQ", "RGTI", "QUBT", "BBAI", "SOUN", "RKLB",
    # Additional liquid names
    "DIS", "NFLX", "SPOT", "PINS", "SNAP", "TWLO", "ZM", "DOCU", "BOX", "DROPBOX",
    "F", "GM", "RIVN", "LCID", "NIO", "LI", "XPEV", "BIDU", "JD", "BABA", 
    # Small Cap
    "JOBY", "QBTS"
]

# Deduplicate
SCAN_UNIVERSE = list(dict.fromkeys(SCAN_UNIVERSE))

# Data fetch window
BARS_LOOKBACK_DAYS = 180  # 6 months of daily bars (~126 trading days)

# Watchlist size
WATCHLIST_SIZE = 25

# Data paths
DATA_DIR = "data"
WATCHLIST_PATH = f"{DATA_DIR}/watchlist.json"
RESEARCH_BRIEF_PATH = f"{DATA_DIR}/research_brief.json"
CANDIDATES_PATH = f"{DATA_DIR}/candidates.json"
TRADE_LOG_PATH = f"{DATA_DIR}/trade_log.json"
STRATEGY_MEMORY_PATH = f"{DATA_DIR}/strategy_memory.json"

# Schedule times (ET)
WATCHLIST_HOUR = 7
WATCHLIST_MINUTE = 0
RESEARCH_HOUR = 7
RESEARCH_MINUTE = 30
STRATEGY_HOUR = 8
STRATEGY_MINUTE = 0
EXECUTION_HOUR = 8
EXECUTION_MINUTE = 30
EXECUTION_INTERVAL_MINUTES = 30  # intraday re-run interval
EMAIL_HOUR = 16
EMAIL_MINUTE = 15  # send daily summary email
MEMORY_HOUR = 16
MEMORY_MINUTE = 30  # after market close
WATCHLIST_EOD_HOUR = 16
WATCHLIST_EOD_MINUTE = 30  # refresh watchlist at end of day
