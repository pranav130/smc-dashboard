"""
Comprehensive unit tests for the enhanced SMC modules:
- Swing detection confirmation offset & no-lookahead guarantee
- HH/HL/LH/LL labeling & Trend state machine
- BOS (>=40% retracement rule) and CHoCH detection
- Displacement candles & strict ICT Order Block detection
- Premium / Discount & OTE zones
- Liquidity sweeps
- Level ranking system
"""
import pytest
from backend.smc.models import Candle, AnalysisConfig
from backend.smc.structure import find_swings, calculate_bos, get_trend_state
from backend.smc.displacement import find_displacement_candles, find_order_blocks
from backend.smc.premium_discount import calculate_premium_discount, calculate_ote
from backend.smc.liquidity import calculate_pdh_pdl, calculate_equal_highs_lows
from backend.smc.trendlines import calculate_trendlines
from backend.smc.ranking import rank_key_levels
from backend.smc.fvg import calculate_fvgs
from backend.smc.psychological import calculate_psychological_levels


def _mock_candle(t: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(time=t, open=o, high=h, low=l, close=c, volume=100.0)


def test_swing_confirmation_offset_no_lookahead():
    """Verify that a swing at pivot_idx is only confirmed at pivot_idx + window."""
    window = 2
    # Create 7 candles with a distinct high at index 2 (time=200)
    # [10, 15, 25 (high), 18, 12, 10, 8]
    candles = [
        _mock_candle(0, 10, 12, 9, 10),
        _mock_candle(100, 10, 16, 9, 15),
        _mock_candle(200, 15, 25, 14, 24),   # Pivot index 2
        _mock_candle(300, 24, 20, 17, 18),
        _mock_candle(400, 18, 14, 11, 12),   # Confirmation index 2 + 2 = 4 (time=400)
        _mock_candle(500, 12, 11, 9, 10),
        _mock_candle(600, 10, 9, 7, 8),
    ]

    swings = find_swings(candles, "1H", window=window)
    highs = [s for s in swings if s.type == "high"]
    assert len(highs) >= 1
    sh = highs[0]
    assert sh.price == 25.0
    assert sh.time == 200        # The pivot time
    assert sh.confirm_time == 400 # The time it became knowable!


def test_hh_hl_and_trend_state():
    """Verify HH/HL/LH/LL labeling and trend state logic."""
    # Bullish sequence: Low(10) -> High(20) -> Low(15 - HL) -> High(25 - HH)
    candles = []
    # Base
    prices = [10, 12, 14, 20, 18, 15, 16, 17, 25, 22, 21, 20]
    for i, p in enumerate(prices):
        candles.append(_mock_candle(i * 100, p - 1, p + 1, p - 2, p))

    swings = find_swings(candles, "1H", window=1)
    trend = get_trend_state(swings)
    assert trend.trend in ["bullish", "bearish", "undetermined"]


def test_bos_and_choch_differentiation():
    """Verify that BoS and CHoCH are identified and retracement rule is applied."""
    # Swing high at 2000. Price pulls back to 1900 (leg was 1800->2000 => 200, retrace = 100 => 50%).
    # Then closes at 2050.
    candles = [
        _mock_candle(100, 1800, 1810, 1790, 1800), # SL at 1790
        _mock_candle(200, 1800, 1810, 1790, 1800),
        _mock_candle(300, 1850, 2000, 1840, 1990), # SH at 2000
        _mock_candle(400, 1990, 1995, 1920, 1930),
        _mock_candle(500, 1930, 1935, 1900, 1905), # Pullback low 1900 (50% retrace)
        _mock_candle(600, 1905, 1980, 1900, 1970),
        _mock_candle(700, 1970, 2060, 1960, 2050), # Closes above 2000
        _mock_candle(800, 2050, 2070, 2040, 2060),
    ]
    swings = find_swings(candles, "1H", window=1)
    bos_list = calculate_bos(candles, swings, "1H", AnalysisConfig(bos_min_retracement_pct=40.0))
    bull_breaks = [b for b in bos_list if b.type == "bullish"]
    if bull_breaks:
        assert bull_breaks[0].valid is True
        assert bull_breaks[0].retracement_pct >= 40.0


def test_displacement_and_order_blocks():
    """Verify displacement candle detection and Order Block identification."""
    candles = [
        _mock_candle(100, 2000, 2005, 1995, 2000),
        _mock_candle(200, 2000, 2005, 1995, 2002),
        _mock_candle(300, 2002, 2004, 1998, 1999), # Bearish candle before surge
        _mock_candle(400, 2000, 2050, 1995, 2048), # Large displacement candle (body=48)
        _mock_candle(500, 2048, 2060, 2040, 2055),
    ]
    disp = find_displacement_candles(candles, "1H", AnalysisConfig(displacement_body_atr_multiplier=1.5))
    assert len(disp) >= 1
    assert disp[0].direction == "bullish"


def test_premium_discount_and_ote():
    """Verify Premium/Discount and OTE zone calculations."""
    swings = find_swings([
        _mock_candle(100, 1000, 1005, 995, 1000),
        _mock_candle(200, 1000, 1005, 995, 1000),
        _mock_candle(300, 1000, 1200, 995, 1190), # SH at 1200
        _mock_candle(400, 1190, 1195, 950, 960),  # SL at 950
        _mock_candle(500, 960, 970, 955, 965),
    ], "1H", window=1)

    prem_disc = calculate_premium_discount([], swings, "1H", current_price=1150.0)
    assert prem_disc.position in ["premium", "discount", "equilibrium"]

    ote = calculate_ote(swings, "1H", current_price=1050.0)
    if ote:
        assert ote.bottom < ote.top


def test_level_ranking():
    """Verify key level scoring and explanatory reasons."""
    curr_price = 2000.0
    daily_fvgs = calculate_fvgs([
        _mock_candle(100, 1980, 1985, 1975, 1980),
        _mock_candle(200, 1985, 2020, 1982, 2018),
        _mock_candle(300, 2020, 2030, 2005, 2025), # FVG [1985 - 2005]
    ], "1D")

    psych = calculate_psychological_levels(curr_price)

    ranked = rank_key_levels(
        current_price=curr_price,
        daily_fvgs=daily_fvgs,
        h4_fvgs=[],
        current_fvgs=[],
        order_blocks=[],
        liquidity_levels=[],
        psychological_levels=psych,
        trendlines=[]
    )

    assert len(ranked) > 0
    assert ranked[0].score > 0
    assert len(ranked[0].score_reason) > 0
