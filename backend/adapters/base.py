from abc import ABC, abstractmethod
from typing import List, Dict, Any, Callable
from backend.smc.models import Candle

class BaseMarketDataAdapter(ABC):
    """Abstract base adapter for market data providers (Delta, Binance, etc.)"""

    @abstractmethod
    async def fetch_historical_candles(self, symbol: str, timeframe: str, limit: int = 500) -> List[Candle]:
        """Fetch historical confirmed OHLCV candles."""
        pass

    @abstractmethod
    async def start_streaming(self, symbol: str, timeframes: List[str], on_candle_update: Callable[[str, Candle], Any]):
        """Connect to live streaming service (e.g. WebSocket)."""
        pass

    @abstractmethod
    async def stop_streaming(self):
        """Disconnect and cleanup live streaming service."""
        pass

    @abstractmethod
    def get_connection_status(self) -> str:
        """Return the current connection status."""
        pass
