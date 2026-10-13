"""
Comprehensive unit tests for Key-Level Activation & Trade-Readiness Watchlist:
- 7 Activation states (INACTIVE, APPROACHING, AT KEY LEVEL, REACTION DEVELOPING, SETUP TO INSPECT, CHECKLIST REVIEW, INVALIDATED / PASSED)
- Checklist item verification
- Alert deduplication and suppression under stale conditions
"""
import pytest
import time
from backend.smc.models import (
    Candle, FairValueGap, OrderBlock, LiquidityLevel, Trendline,
    DisplacementCandle, AnalysisConfig
)
from backend.smc.activation import (
    evaluate_level_activation, generate_watchlist, AlertStore
)


def _mock_c(t: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(time=t, open=o, high=h, low=l, close=c, volume=100.0)


def test_activation_states_inactive_and_approaching():
    config = AnalysisConfig(activation_approach_atr_multiplier=1.5)
    atr_val = 10.0  # approach threshold is 15.0 or zone width
    candles = [_mock_c(100, 2000, 2010, 1990, 2000)]

    # Level at 2050 - 2060 (midpoint 2055, bottom 2050)
    # Price at 2000 -> dist to bottom is 50 > 15 -> INACTIVE
    entry_inactive = evaluate_level_activation(
        level_id="test_fvg_1",
        name="4H Bullish FVG",
        level_type="4H FVG",
        timeframe="4H",
        direction="bullish",
        price=2055.0,
        top=2060.0,
        bottom=2050.0,
        freshness="unmitigated",
        current_price=2000.0,
        current_candles=candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[],
        supporting_fvgs=[],
        liquidity_levels=[],
        trendlines=[],
        opposing_warnings=[],
        atr_val=atr_val,
        config=config
    )
    assert entry_inactive.state == "INACTIVE"

    # Price moves to 2040 -> dist to bottom is 10 <= 15 -> APPROACHING
    entry_approaching = evaluate_level_activation(
        level_id="test_fvg_1",
        name="4H Bullish FVG",
        level_type="4H FVG",
        timeframe="4H",
        direction="bullish",
        price=2055.0,
        top=2060.0,
        bottom=2050.0,
        freshness="unmitigated",
        current_price=2040.0,
        current_candles=candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[],
        supporting_fvgs=[],
        liquidity_levels=[],
        trendlines=[],
        opposing_warnings=[],
        atr_val=atr_val,
        config=config
    )
    assert entry_approaching.state == "APPROACHING"


def test_activation_at_key_level():
    config = AnalysisConfig()
    atr_val = 5.0
    candles = [_mock_c(100, 2052, 2055, 2050, 2052)]

    # Price inside zone [2050 - 2060]
    entry_at_level = evaluate_level_activation(
        level_id="test_fvg_2",
        name="Daily Bullish FVG",
        level_type="1D FVG",
        timeframe="1D",
        direction="bullish",
        price=2055.0,
        top=2060.0,
        bottom=2050.0,
        freshness="unmitigated",
        current_price=2053.0,
        current_candles=candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[],
        supporting_fvgs=[],
        liquidity_levels=[],
        trendlines=[],
        opposing_warnings=[],
        atr_val=atr_val,
        config=config
    )
    assert entry_at_level.state == "AT KEY LEVEL"
    assert entry_at_level.checklist[0].satisfied is True


def test_reaction_developing_and_setup_to_inspect():
    config = AnalysisConfig()
    atr_val = 5.0
    candles = [_mock_c(100, 2052, 2055, 2050, 2053)]

    # 1. Add swept liquidity near the level
    swept_liq = LiquidityLevel(
        type="PDL",
        label="Previous Day Low",
        price=2051.0,
        time=90,
        swept=True,
        sweep_time=100
    )

    entry_reaction = evaluate_level_activation(
        level_id="test_fvg_3",
        name="4H Bullish FVG",
        level_type="4H FVG",
        timeframe="4H",
        direction="bullish",
        price=2055.0,
        top=2060.0,
        bottom=2050.0,
        freshness="unmitigated",
        current_price=2053.0,
        current_candles=candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[],
        supporting_fvgs=[],
        liquidity_levels=[swept_liq],
        trendlines=[],
        opposing_warnings=[],
        atr_val=atr_val,
        config=config
    )
    assert entry_reaction.state == "REACTION DEVELOPING"
    assert entry_reaction.checklist[1].satisfied is True

    # 2. Add broken trendline -> Promotes to SETUP TO INSPECT
    broken_tl = Trendline(
        id="tl_1",
        timeframe="1H",
        direction="resistance",
        anchor1_time=10,
        anchor1_price=2070,
        anchor2_time=50,
        anchor2_price=2060,
        touch_count=2,
        broken=True,
        breakout_time=95,
        break_confirmed_by_close=True
    )

    entry_setup = evaluate_level_activation(
        level_id="test_fvg_3",
        name="4H Bullish FVG",
        level_type="4H FVG",
        timeframe="4H",
        direction="bullish",
        price=2055.0,
        top=2060.0,
        bottom=2050.0,
        freshness="unmitigated",
        current_price=2053.0,
        current_candles=candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[],
        supporting_fvgs=[],
        liquidity_levels=[swept_liq],
        trendlines=[broken_tl],
        opposing_warnings=[],
        atr_val=atr_val,
        config=config
    )
    assert entry_setup.state == "SETUP TO INSPECT"
    assert entry_setup.checklist[2].satisfied is True


def test_checklist_review_state():
    config = AnalysisConfig()
    atr_val = 5.0
    now_ts = 1000
    candles = [_mock_c(now_ts, 2052, 2055, 2050, 2054)]

    swept_liq = LiquidityLevel(
        type="PDL",
        label="Previous Day Low",
        price=2051.0,
        time=now_ts - 50,
        swept=True,
        sweep_time=now_ts - 10
    )
    broken_tl = Trendline(
        id="tl_2",
        timeframe="30M",
        direction="resistance",
        anchor1_time=now_ts - 500,
        anchor1_price=2080,
        anchor2_time=now_ts - 200,
        anchor2_price=2065,
        touch_count=2,
        broken=True,
        breakout_time=now_ts - 5,
        break_confirmed_by_close=True
    )
    disp = DisplacementCandle(
        time=now_ts - 5,
        direction="bullish",
        body_size=12.0,
        atr=5.0,
        body_atr_ratio=2.4,
        timeframe="30M"
    )

    entry_checklist = evaluate_level_activation(
        level_id="test_fvg_full",
        name="Daily Bullish FVG",
        level_type="1D FVG",
        timeframe="1D",
        direction="bullish",
        price=2055.0,
        top=2060.0,
        bottom=2050.0,
        freshness="unmitigated",
        current_price=2053.0,
        current_candles=candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[disp],
        supporting_fvgs=[],
        liquidity_levels=[swept_liq],
        trendlines=[broken_tl],
        opposing_warnings=[],
        atr_val=atr_val,
        config=config
    )
    assert entry_checklist.state == "CHECKLIST REVIEW"
    # All 5 checklist items satisfied
    for item in entry_checklist.checklist:
        assert item.satisfied is True


def test_opposing_htf_prevents_checklist_review():
    config = AnalysisConfig()
    atr_val = 5.0
    now_ts = 1000
    candles = [_mock_c(now_ts, 2052, 2055, 2050, 2054)]

    swept_liq = LiquidityLevel(
        type="PDL",
        label="Previous Day Low",
        price=2051.0,
        time=now_ts - 50,
        swept=True,
        sweep_time=now_ts - 10
    )
    broken_tl = Trendline(
        id="tl_2",
        timeframe="30M",
        direction="resistance",
        anchor1_time=now_ts - 500,
        anchor1_price=2080,
        anchor2_time=now_ts - 200,
        anchor2_price=2065,
        touch_count=2,
        broken=True,
        breakout_time=now_ts - 5,
        break_confirmed_by_close=True
    )
    disp = DisplacementCandle(
        time=now_ts - 5,
        direction="bullish",
        body_size=12.0,
        atr=5.0,
        body_atr_ratio=2.4,
        timeframe="30M"
    )

    # Opposing Bearish 1D FVG overhead
    opposing_msg = "Opposing Bearish 1D FVG overhead at $2062 - $2080"

    entry = evaluate_level_activation(
        level_id="test_fvg_opposed",
        name="Daily Bullish FVG",
        level_type="1D FVG",
        timeframe="1D",
        direction="bullish",
        price=2055.0,
        top=2060.0,
        bottom=2050.0,
        freshness="unmitigated",
        current_price=2053.0,
        current_candles=candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[disp],
        supporting_fvgs=[],
        liquidity_levels=[swept_liq],
        trendlines=[broken_tl],
        opposing_warnings=[opposing_msg],
        atr_val=atr_val,
        config=config
    )
    # Opposing HTF prevents promotion to CHECKLIST REVIEW; remains at SETUP TO INSPECT
    assert entry.state == "SETUP TO INSPECT"
    assert entry.checklist[4].satisfied is False
    assert opposing_msg in entry.checklist[4].evidence


def test_alert_store_deduplication_and_stale_suppression():
    store = AlertStore()

    # Alert 1
    a1 = store.register_transition(
        level_id="lvl_1",
        level_name="4H FVG",
        timeframe="4H",
        state="APPROACHING",
        evidence=["Approaching"],
        timestamp=100,
        ist_time="12:00",
        is_stale=False
    )
    assert a1 is not None

    # Immediate duplicate transition should NOT fire
    a2 = store.register_transition(
        level_id="lvl_1",
        level_name="4H FVG",
        timeframe="4H",
        state="APPROACHING",
        evidence=["Approaching again"],
        timestamp=105,
        ist_time="12:05",
        is_stale=False
    )
    assert a2 is None

    # State transition to AT KEY LEVEL fires
    a3 = store.register_transition(
        level_id="lvl_1",
        level_name="4H FVG",
        timeframe="4H",
        state="AT KEY LEVEL",
        evidence=["Entered zone"],
        timestamp=110,
        ist_time="12:10",
        is_stale=True  # Stale data
    )
    assert a3 is not None
    assert a3.is_stale_suppressed is True

    # Acknowledgment
    assert store.acknowledge_alert(a1.id) is True
    active = store.get_alerts(include_acknowledged=False)
    assert len(active) == 1
    assert active[0].id == a3.id
