import os
from datetime import timezone, timedelta
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Delta Exchange India Configurations
DELTA_REST_URL = os.getenv("DELTA_REST_URL", "https://api.india.delta.exchange")
DELTA_WS_URL = os.getenv("DELTA_WS_URL", "wss://public-socket.india.delta.exchange")
DELTA_LEGACY_WS_URL = os.getenv("DELTA_LEGACY_WS_URL", "wss://socket.india.delta.exchange")

# Price Source Configuration:
# "index" = Delta Exchange Spot Index (.DEXAUTUSD) - Benchmark spot gold price (Exact spot gold tracking)
# "mark"  = Delta Exchange Perpetual Futures (XAUTUSD) - Perpetual futures mark price
PRICE_SOURCE = os.getenv("DELTA_PRICE_SOURCE", "index").lower()
INDEX_SYMBOL = ".DEXAUTUSD"
MARK_SYMBOL = "XAUTUSD"

DEFAULT_SYMBOL = os.getenv("DELTA_SYMBOL", INDEX_SYMBOL if PRICE_SOURCE == "index" else MARK_SYMBOL)
DEFAULT_PRODUCT_ID = 435 if DEFAULT_SYMBOL == INDEX_SYMBOL else 131253

# Supported Timeframes
TIMEFRAME_MAP = {
    "1D": "1d",
    "4H": "4h",
    "1H": "1h",
    "30M": "30m",
    "15M": "15m",
    "5M": "5m",
    "1M": "1m",
}

REVERSE_TIMEFRAME_MAP = {v: k for k, v in TIMEFRAME_MAP.items()}

TIMEFRAME_SECONDS = {
    "1d": 86400,
    "4h": 14400,
    "1h": 3600,
    "30m": 1800,
    "15m": 900,
    "5M": 300,
    "5m": 300,
    "1m": 60,
}

# IST Timezone (UTC + 05:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

# Server host & port
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

# Allowed CORS Origins
raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
if raw_origins.strip() == "*":
    ALLOWED_ORIGINS: List[str] = ["*"]
else:
    ALLOWED_ORIGINS = [orig.strip() for orig in raw_origins.split(",") if orig.strip()]

# Admin secret for sensitive operations (balance reset)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

# Persistent Database URL
raw_db_url = os.getenv("DATABASE_URL", "sqlite:///./data/paper_trading.db")
# Render / Heroku / Railway often set postgres://, which SQLAlchemy requires as postgresql://
if raw_db_url.startswith("postgres://"):
    DATABASE_URL = raw_db_url.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = raw_db_url

# STRICT SAFETY LOCK: Simulation / Paper trading only
EXECUTION_MODE = "PAPER"
INITIAL_PAPER_BALANCE = float(os.getenv("INITIAL_PAPER_BALANCE", "10000.0"))
DEFAULT_RISK_PER_TRADE_PCT = float(os.getenv("DEFAULT_RISK_PER_TRADE_PCT", "1.0"))
AUTO_PAPER_TRADING_ENABLED = os.getenv("AUTO_PAPER_TRADING_ENABLED", "true").lower() in ("true", "1", "yes")

def validate_environment():
    """Validate critical environment configurations and report diagnostics."""
    if EXECUTION_MODE != "PAPER":
        raise RuntimeError("SAFETY VIOLATION: Execution mode must strictly be PAPER.")
    return {
        "environment": ENVIRONMENT,
        "symbol": DEFAULT_SYMBOL,
        "database_type": "postgresql" if "postgresql" in DATABASE_URL else "sqlite",
        "paper_trading_mode": True,
        "auto_trading": AUTO_PAPER_TRADING_ENABLED
    }
