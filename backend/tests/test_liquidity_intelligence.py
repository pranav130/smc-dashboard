"""
Automated unit tests for Hidden Liquidity and Liquidity Heatmap Intelligence Module.

Tests cover:
1. Raw level extraction (swings, equal highs/lows)
2. Dynamic clustering & ATR bandwidth grouping
3. Zone scoring (0 to 100) & subfactor breakdown
4. Multi-timeframe confluence weighting
5. Sweep detection: Piercing wick + candle close back inside (rejection)
6. Breakout detection: Clean close beyond boundary marked INVALIDATED
7. Disclaimers & Zero fake order-book data validation
"""

import pytest
from datetime import datetime
from backend.smc.models import Candle
from backend.smc.liquidity_intelligence import (
    detect_raw_liquidity_levels,
    cluster_liquidity_zones,
    analyze_liquidity_intelligence,
    LiquidityZone,
    SweepRecord
)


def make_candle(t: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> Candle:
    dt = datetime.fromtimestamp(t)
    return Candle(
        time=t,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
        ist_time=dt.strftime("%Y-%m-%d %H:%M:%S")
    )


def test_raw_level_extraction_swings():
    """Verify swing highs become BSL and swing lows become SSL."""
    # Build 15 candles with clear swing high at index 5 and swing low at index 10
    candles = []
    base_time = 1700000000
    for i in range(20):
        # Peak at 5 (price 2050), trough at 12 (price 1980)
        if i == 5:
            c = make_candle(base_time + i*3600, 2030, 2050.0, 2025, 2035)
        elif i == 12:
            c = make_candle(base_time + i*3600, 1990, 1995, 1980.0, 1985)
        else:
            c = make_candle(base_time + i*3600, 2000, 2010, 1990, 2005)
        candles.append(c)

    raw = detect_raw_liquidity_levels(candles, "1H")
    bsl = [r for r in raw if r["type"] == "BSL"]
    ssl = [r for r in raw if r["type"] == "SSL"]

    assert len(bsl) >= 1
    assert any(b["price"] == 2050.0 for b in bsl)
    assert len(ssl) >= 1
    assert any(s["price"] == 1980.0 for s in ssl)


def test_dynamic_clustering_eliminates_redundancy():
    """Verify nearby levels within ATR bandwidth are merged into one zone."""
    raw_levels = [
        {"type": "BSL", "price": 2040.10, "time": 100, "ist_time": "", "source": "Swing 1", "weight": 1.0, "timeframe": "1H"},
        {"type": "BSL", "price": 2040.35, "time": 200, "ist_time": "", "source": "Swing 2", "weight": 1.0, "timeframe": "1H"},
        {"type": "BSL", "price": 2040.40, "time": 300, "ist_time": "", "source": "Swing 3", "weight": 1.0, "timeframe": "4H"},
    ]
    # Synthetic current candles
    candles = [make_candle(400, 2010, 2015, 2005, 2012)]
    atr_val = 2.0  # Bandwidth = max(0.4, 0.5 * 2.0) = 1.0 USD

    zones = cluster_liquidity_zones(raw_levels, 2012.0, candles, "1H", atr_val)

    # All three levels around 2040 should cluster into a SINGLE zone
    assert len(zones) == 1
    zone = zones[0]
    assert zone.type == "BSL"
    assert zone.touch_count == 3
    assert 2039.0 <= zone.bottom <= zone.top <= 2042.0
    assert "1H" in zone.supporting_timeframes
    assert "4H" in zone.supporting_timeframes


def test_liquidity_scoring_and_breakdown():
    """Test score is strictly bounded 0-100 and factors are transparent."""
    raw_levels = [
        {"type": "BSL", "price": 2050.0, "time": 100, "ist_time": "", "source": "Daily Swing", "weight": 1.5, "timeframe": "1D"},
        {"type": "BSL", "price": 2050.2, "time": 200, "ist_time": "", "source": "4H Swing", "weight": 1.2, "timeframe": "4H"},
    ]
    candles = [make_candle(300, 2045, 2048, 2042, 2046)]
    zones = cluster_liquidity_zones(raw_levels, 2046.0, candles, "1H", 2.5)

    assert len(zones) == 1
    zone = zones[0]
    assert 0 <= zone.score <= 100
    assert zone.score_breakdown is not None
    assert len(zone.score_breakdown.factors) == 4
    # Pristine & close zone with HTF confluence should have strong score
    assert zone.score >= 60


def test_sweep_rejection_vs_sustained_breakout():
    """Verify rejection is marked SWEPT, while sustained close beyond is INVALIDATED."""
    # Case 1: Sweep rejection (High > top, Close <= top)
    raw_bsl = [{"type": "BSL", "price": 2050.0, "time": 100, "ist_time": "", "source": "Swing", "weight": 1.0, "timeframe": "1H"}]
    # Candle pierces 2052, but closes at 2049
    sweep_candles = [
        make_candle(100, 2040, 2050, 2035, 2045),
        make_candle(200, 2045, 2052.5, 2044, 2049.0)
    ]
    zones_swept = cluster_liquidity_zones(raw_bsl, 2049.0, sweep_candles, "1H", 1.5)
    assert len(zones_swept) == 1
    assert zones_swept[0].status == "SWEPT"
    assert zones_swept[0].sweep.confirmed_sweep is True
    assert zones_swept[0].sweep.max_excursion > 0

    # Case 2: Sustained breakout (High > top, Close > top)
    breakout_candles = [
        make_candle(100, 2040, 2050, 2035, 2045),
        make_candle(200, 2045, 2055.0, 2044, 2054.0)  # closed well above top
    ]
    zones_breakout = cluster_liquidity_zones(raw_bsl, 2054.0, breakout_candles, "1H", 1.5)
    assert len(zones_breakout) == 1
    assert zones_breakout[0].status == "INVALIDATED"
    assert zones_breakout[0].sweep.is_sustained_breakout is True


def test_data_integrity_no_fake_orderbook():
    """Ensure data disclaimer is explicit and no synthetic broker data is returned."""
    candles_by_tf = {
        "1H": [
            make_candle(100, 2000, 2010, 1990, 2005),
            make_candle(200, 2005, 2020, 2000, 2015),
            make_candle(300, 2015, 2018, 2005, 2010),
            make_candle(400, 2010, 2012, 1995, 2000),
            make_candle(500, 2000, 2025, 1998, 2020),
            make_candle(600, 2020, 2022, 2010, 2018),
            make_candle(700, 2018, 2019, 2005, 2008),
            make_candle(800, 2008, 2030, 2006, 2028),
            make_candle(900, 2028, 2029, 2020, 2025),
            make_candle(1000, 2025, 2026, 2015, 2020),
        ]
    }
    res = analyze_liquidity_intelligence(candles_by_tf, "1H")
    assert "No proprietary broker stop-loss feeds" in res.data_disclaimer
    assert res.radar is not None
    assert isinstance(res.radar.nearest_bsl, list)
    assert isinstance(res.radar.nearest_ssl, list)
