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
# "mark"  = Delta Exchange Perpetual Futures (XAUTUSD) - Tradable instrument with order book & fills
# "index" = Delta Exchange Spot Index (.DEXAUTUSD) - Benchmark spot gold price reference
PRICE_SOURCE = os.getenv("DELTA_PRICE_SOURCE", "mark").lower()
INDEX_SYMBOL = ".DEXAUTUSD"
MARK_SYMBOL = "XAUTUSD"

DEFAULT_SYMBOL = os.getenv("DELTA_SYMBOL", MARK_SYMBOL if PRICE_SOURCE == "mark" else INDEX_SYMBOL)
DEFAULT_PRODUCT_ID = 131253 if DEFAULT_SYMBOL == MARK_SYMBOL else 435

# Tradable Instrument Specifications (Delta Exchange India Perpetual Futures)
CONTRACT_MULTIPLIER = 0.001   # 1 contract = 0.001 XAUT (0.001 troy ounce)
TICK_SIZE = 0.01             # Minimum price increment ($0.01 USD)
QUOTE_CURRENCY = "USD"
SETTLING_CURRENCY = "USD"
MIN_ORDER_QTY = 1            # Minimum contracts (1 contract = 0.001 XAUT)
MAX_NOTIONAL_CAP = float(os.getenv("MAX_NOTIONAL_CAP", "2500.0"))  # $2,500 maximum notional cap

# Transaction Cost Assumptions (Conservative Microstructure Model)
TAKER_FEE_RATE = 0.0005      # 0.05% taker commission per side
MAKER_FEE_RATE = 0.0002      # 0.02% maker fee
SLIPPAGE_BPS = 5.0           # 5 basis points adverse slippage proxy (0.05%)
MAX_DATA_AGE_SECONDS = 60    # Stale data cutoff (fail-closed if >60s)

# Supported Timeframes
TIMEFRAME_MAP = {
    "1D": "1d",
    "4H": "4h",
    "2H": "2h",
    "1H": "1h",
    "30M": "30m",
    "15M": "15m",
    "10M": "10m",
    "5M": "5m",
    "1M": "1m",
}

REVERSE_TIMEFRAME_MAP = {v: k for k, v in TIMEFRAME_MAP.items()}

TIMEFRAME_SECONDS = {
    "1d": 86400,
    "4h": 14400,
    "2h": 7200,
    "1h": 3600,
    "30m": 1800,
    "15m": 900,
    "10m": 600,
    "10M": 600,
    "5M": 300,
    "5m": 300,
    "1m": 60,
}

# Standard Timezones
UTC_TZ = timezone.utc
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

# Persistent Database URL (PostgreSQL in production, SQLite WAL locally)
raw_db_url = os.getenv("DATABASE_URL", "sqlite:///./data/paper_trading.db")
if raw_db_url.startswith("postgres://"):
    DATABASE_URL = raw_db_url.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = raw_db_url

# STRICT SAFETY LOCK: Simulation / Paper trading only
EXECUTION_MODE = "PAPER"
INITIAL_PAPER_BALANCE = float(os.getenv("INITIAL_PAPER_BALANCE", "10000.0"))
DEFAULT_RISK_PER_TRADE_PCT = float(os.getenv("DEFAULT_RISK_PER_TRADE_PCT", "1.0"))
AUTO_PAPER_TRADING_ENABLED = os.getenv("AUTO_PAPER_TRADING_ENABLED", "true").lower() in ("true", "1", "yes")

# Section 6: Non-Negotiable Risk Limits & Guardrails
INITIAL_RISK_PER_TRADE_PCT = 0.25   # 0.25% of current equity per trade
DAILY_LOSS_LIMIT_PCT = 1.0          # 1.0% of start-of-day equity
WEEKLY_LOSS_LIMIT_PCT = 2.5         # 2.5% of start-of-week equity
MAX_DRAWDOWN_LIMIT_PCT = 5.0        # 5.0% peak-to-trough circuit breaker
MAX_CONCURRENT_POSITIONS = 1        # Exactly 1 active position initially
MIN_REWARD_TO_RISK = 2.0            # Minimum 2:1 net reward-to-risk
CONSECUTIVE_LOSS_PAUSE_COUNT = 3    # Pause after 3 consecutive losses
CONSECUTIVE_LOSS_COOLDOWN_SECS = 14400 # 4 hours mandatory cooling off

# STRATEGY FREEZE METADATA (Pre-Declared Forward Testing Protocol)
STRATEGY_VERSION = "2.1.0-FROZEN-20261014"
FORWARD_TEST_START_UTC = "2026-10-14T14:15:00Z"
FORWARD_TEST_DURATION_DAYS = 30
FORWARD_TEST_MIN_TRADES = 50

def validate_environment():
    """Validate critical environment configurations and report diagnostics."""
    if EXECUTION_MODE != "PAPER":
        raise RuntimeError("SAFETY VIOLATION: Execution mode must strictly be PAPER.")
    return {
        "environment": ENVIRONMENT,
        "symbol": DEFAULT_SYMBOL,
        "product_id": DEFAULT_PRODUCT_ID,
        "contract_multiplier": CONTRACT_MULTIPLIER,
        "database_type": "postgresql" if "postgresql" in DATABASE_URL else "sqlite",
        "paper_trading_mode": True,
        "auto_trading": AUTO_PAPER_TRADING_ENABLED,
        "risk_limits": {
            "risk_per_trade_pct": INITIAL_RISK_PER_TRADE_PCT,
            "daily_loss_limit_pct": DAILY_LOSS_LIMIT_PCT,
            "weekly_loss_limit_pct": WEEKLY_LOSS_LIMIT_PCT,
            "max_drawdown_limit_pct": MAX_DRAWDOWN_LIMIT_PCT,
            "min_rr": MIN_REWARD_TO_RISK,
        }
    }
