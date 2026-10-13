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
