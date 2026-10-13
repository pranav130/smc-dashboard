import os
from datetime import timezone, timedelta

# Delta Exchange India Configurations
DELTA_REST_URL = os.getenv("DELTA_REST_URL", "https://api.india.delta.exchange")
DELTA_WS_URL = os.getenv("DELTA_WS_URL", "wss://public-socket.india.delta.exchange")
DELTA_LEGACY_WS_URL = os.getenv("DELTA_LEGACY_WS_URL", "wss://socket.india.delta.exchange")

DEFAULT_SYMBOL = os.getenv("DELTA_SYMBOL", "XAUTUSD")
DEFAULT_PRODUCT_ID = 131253

# Supported Timeframes
TIMEFRAME_MAP = {
    "1D": "1d",
    "4H": "4h",
    "1H": "1h",
    "30M": "30m"
}

REVERSE_TIMEFRAME_MAP = {v: k for k, v in TIMEFRAME_MAP.items()}

TIMEFRAME_SECONDS = {
    "1d": 86400,
    "4h": 14400,
    "1h": 3600,
    "30m": 1800
}

# IST Timezone (UTC + 05:30)
IST_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

# Server host & port
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
