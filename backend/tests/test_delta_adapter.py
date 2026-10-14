import time
import pytest
from backend.adapters.delta_exchange import DeltaExchangeAdapter
from backend.smc.models import Candle

def test_normalize_candle_seconds():
    adapter = DeltaExchangeAdapter()
    raw = {
        "time": 1700000000,
        "open": 4190.0,
        "high": 4200.0,
        "low": 4185.0,
        "close": 4195.0,
        "volume": 120.5
    }
    candle = adapter._normalize_candle(raw)
    assert candle is not None
    assert candle.time == 1700000000
    assert candle.open == 4190.0
    assert candle.high == 4200.0
    assert candle.low == 4185.0
    assert candle.close == 4195.0
    assert candle.volume == 120.5
    assert "IST" in candle.ist_time

def test_normalize_candle_microseconds():
    adapter = DeltaExchangeAdapter()
    raw = {
        "cst": 1791875760000000,  # microseconds
        "o": "4192.5",
        "h": "4195.0",
        "l": "4191.0",
        "c": "4194.0",
        "v": "350.0"
    }
    candle = adapter._normalize_candle(raw, is_forming=True)
    assert candle is not None
    assert candle.time == 1791875760
    assert candle.open == 4192.5
    assert candle.close == 4194.0
    assert candle.is_forming is True

def test_candle_deduplication_and_sorting():
    adapter = DeltaExchangeAdapter()
    c1 = {"time": 1700003600, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1}
    c2 = {"time": 1700000000, "open": 9, "high": 11, "low": 8, "close": 10, "volume": 2}
    c3 = {"time": 1700003600, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1}  # duplicate
    
    cleaned = []
    seen = set()
    for item in [c1, c2, c3]:
        c = adapter._normalize_candle(item)
        if c and c.time not in seen:
            seen.add(c.time)
            cleaned.append(c)
    cleaned.sort(key=lambda x: x.time)

    assert len(cleaned) == 2
    assert cleaned[0].time == 1700000000
    assert cleaned[1].time == 1700003600

def test_min_24h_candles_guarantee():
    from backend.adapters.delta_exchange import MIN_24H_CANDLES, TIMEFRAME_LIMITS
    from backend.config import TIMEFRAME_SECONDS, TIMEFRAME_MAP

    for tf in ["1D", "4H", "1H", "30M", "15M", "5M", "1M"]:
        min_candles = MIN_24H_CANDLES[tf]
        limit = TIMEFRAME_LIMITS[tf]
        res = TIMEFRAME_MAP[tf]
        sec_per_candle = TIMEFRAME_SECONDS[res]
        
        # Verify min_candles spans at least 24 hours (86400 seconds)
        # Note: 1D spans 1 day (86400s) with 2 candles spanning 48h
        min_span_seconds = min_candles * sec_per_candle
        assert min_span_seconds >= 86400, f"{tf} min_candles {min_candles} only spans {min_span_seconds}s (< 86400s)"
        assert limit >= min_candles, f"{tf} limit {limit} must be >= min_candles {min_candles}"

@pytest.mark.asyncio
async def test_fetch_candles_enforces_24h_minimum(monkeypatch):
    from backend.adapters.delta_exchange import MIN_24H_CANDLES
    adapter = DeltaExchangeAdapter()

    # Mock _normalize_candle to return dummy candles
    now = 1700000000
    mock_raw = [{"time": now - i * 60, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10} for i in range(2000)]
    
    class MockResponse:
        status_code = 200
        def json(self):
            return {"success": True, "result": mock_raw}

    class MockClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, params=None):
            return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: MockClient())

    # Requesting limit=5 on 1M must be clamped to at least MIN_24H_CANDLES["1M"] (1450)
    candles = await adapter.fetch_historical_candles(".DEXAUTUSD", "1M", limit=5)
    assert len(candles) >= MIN_24H_CANDLES["1M"]


def test_utc_timestamp_formatting():
    adapter = DeltaExchangeAdapter()
    raw = {
        "time": 1700000000,
        "open": 4000.0,
        "high": 4010.0,
        "low": 3995.0,
        "close": 4005.0,
        "volume": 50.0
    }
    candle = adapter._normalize_candle(raw)
    assert candle is not None
    assert candle.utc_time is not None
    assert "UTC" in candle.utc_time
    assert candle.ist_time is not None
    assert "IST" in candle.ist_time


def test_feed_state_transitions():
    import time
    adapter = DeltaExchangeAdapter()
    
    # 1. Initially stopped -> DISCONNECTED
    assert adapter.get_feed_state() == "DISCONNECTED"
    
    # 2. Running and connected with recent update -> CONNECTED
    adapter.is_running = True
    adapter.connection_status = "Connected"
    adapter.last_successful_update = int(time.time())
    assert adapter.get_feed_state() == "CONNECTED"
    
    # 3. Update older than 120s -> STALE
    adapter.last_successful_update = int(time.time()) - 150
    assert adapter.get_feed_state() == "STALE"
    
    # 4. Polling fallback or reconnecting -> RECOVERING
    adapter.use_polling_fallback = True
    assert adapter.get_feed_state() == "RECOVERING"
    adapter.use_polling_fallback = False
    
    # 5. Invalid data detected -> INVALID DATA
    adapter.has_invalid_data = True
    assert adapter.get_feed_state() == "INVALID DATA"


def test_market_data_status_generation():
    adapter = DeltaExchangeAdapter()
    adapter.is_running = True
    adapter.connection_status = "Connected"
    adapter.last_successful_update = int(time.time())

    status = adapter.get_market_data_status("XAUTUSD", "1H")
    assert status.symbol == "XAUTUSD"
    assert status.feed_state == "CONNECTED"
    assert status.contract_multiplier == 0.001
    assert status.tick_size == 0.01
    assert status.heartbeat_ok is True

