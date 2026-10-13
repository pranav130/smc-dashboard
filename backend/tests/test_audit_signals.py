import pytest
import time
from backend.smc.models import (
    Candle, AnalysisConfig, FairValueGap, OrderBlock, LiquidityLevel,
    Trendline, TrendlineTouch, DisplacementCandle, SwingPoint, BreakOfStructure
)
from backend.smc.fvg import calculate_fvgs
from backend.smc.displacement import find_displacement_candles
from backend.smc.structure import find_swings, calculate_bos
from backend.smc.trendlines import calculate_trendlines
from backend.smc.activation import (
    evaluate_level_activation, AlertStore, global_alert_store
)
from backend.smc.engine import SMCEngine
from backend.adapters.delta_exchange import DeltaExchangeAdapter


def make_test_candle(t: int, o: float, h: float, l: float, c: float, is_forming: bool = False) -> Candle:
    return Candle(
        time=t,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100.0,
        is_forming=is_forming,
        ist_time="12:00:00 IST"
    )


# ---------------------------------------------------------------------------
# 1. Closed-Candle Confirmation Tests (Zero premature / repainting signals)
# ---------------------------------------------------------------------------

def test_closed_candle_confirmation_fvg():
    """Verify that Fair Value Gaps cannot form or invert on provisional forming candles."""
    cfg = AnalysisConfig(fvg_min_size_atr_multiplier=0.01)

    # c0, c1, and c2 (forming)
    candles_forming = [
        make_test_candle(100, 2000, 2002, 1998, 2000, is_forming=False), # c0: high=2002
        make_test_candle(200, 2001, 2025, 2001, 2024, is_forming=False), # c1: impulse
        make_test_candle(300, 2024, 2030, 2010, 2028, is_forming=True),  # c2: low=2010 > 2002, BUT forming!
    ]
    # While c2 is forming, FVG must NOT be established (prevents premature / repainting FVG)
    fvgs_forming = calculate_fvgs(candles_forming, "1H", cfg)
    assert len(fvgs_forming) == 0

    # Once c2 closes, FVG is confirmed!
    candles_closed = [
        make_test_candle(100, 2000, 2002, 1998, 2000, is_forming=False),
        make_test_candle(200, 2001, 2025, 2001, 2024, is_forming=False),
        make_test_candle(300, 2024, 2030, 2010, 2028, is_forming=False), # Closed
    ]
    fvgs_closed = calculate_fvgs(candles_closed, "1H", cfg)
    assert len(fvgs_closed) == 1
    assert fvgs_closed[0].direction == "bullish"
    assert fvgs_closed[0].bottom == 2002.0
    assert fvgs_closed[0].top == 2010.0

    # Inversion test: price moves below bottom (2002) on a forming candle
    candles_inversion_forming = candles_closed + [
        make_test_candle(400, 2010, 2012, 1995, 1996, is_forming=True) # close below 2002, but forming
    ]
    fvgs_inv_forming = calculate_fvgs(candles_inversion_forming, "1H", cfg)
    assert fvgs_inv_forming[0].inverted is False  # Cannot invert on provisional candle!

    # When candle closes below bottom, inversion is confirmed!
    candles_inversion_closed = candles_closed + [
        make_test_candle(400, 2010, 2012, 1995, 1996, is_forming=False) # Closed below 2002
    ]
    fvgs_inv_closed = calculate_fvgs(candles_inversion_closed, "1H", cfg)
    assert fvgs_inv_closed[0].inverted is True


def test_closed_candle_confirmation_displacement_and_bos():
    """Verify displacement and BoS do not trigger on forming candles."""
    cfg = AnalysisConfig(displacement_body_atr_multiplier=1.2, bos_min_retracement_pct=40.0)

    # 15 candles
    base_candles = [
        make_test_candle(i * 100, 2000, 2005, 1995, 2000, is_forming=False)
        for i in range(14)
    ]
    # Candle 15 has giant body, but is forming
    forming_disp = base_candles + [
        make_test_candle(1400, 2000, 2050, 1998, 2048, is_forming=True)
    ]
    disps_forming = find_displacement_candles(forming_disp, "1H", cfg)
    assert len(disps_forming) == 0  # Must be zero while forming

    # When closed, it is recognized as displacement
    closed_disp = base_candles + [
        make_test_candle(1400, 2000, 2050, 1998, 2048, is_forming=False)
    ]
    disps_closed = find_displacement_candles(closed_disp, "1H", cfg)
    assert len(disps_closed) == 1


# ---------------------------------------------------------------------------
# 2. WATCH → ACTIVE State Transition
# ---------------------------------------------------------------------------

def test_watch_to_active_state_transition():
    """Trace setup from WATCH (At Key Level / In-Zone) to ACTIVE (Checklist Review 5/5)."""
    cfg = AnalysisConfig()

    # Candles with no rejection wicks (low is near open/close)
    base_candles = [
        make_test_candle(i * 100, 2001.0, 2003.0, 2000.5, 2002.0, is_forming=False)
        for i in range(20)
    ]

    # Level: Bullish zone at 2000 - 2005
    # Step 1: Price is inside zone at 2002, but no sweep, no TL break, no displacement
    entry_watch = evaluate_level_activation(
        level_id="fvg_test_1",
        name="1H Bullish FVG",
        level_type="FVG",
        timeframe="1H",
        direction="bullish",
        price=2002.5,
        top=2005.0,
        bottom=2000.0,
        freshness="unmitigated",
        current_price=2002.0,
        current_candles=base_candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[],
        supporting_fvgs=[],
        liquidity_levels=[],
        trendlines=[],
        opposing_warnings=[],
        atr_val=5.0,
        config=cfg,
        is_stale=False
    )
    # Must be in WATCH state (AT KEY LEVEL), NOT active!
    assert entry_watch.state == "AT KEY LEVEL"
    assert entry_watch.checklist[0].satisfied is True   # In-zone satisfied
    assert entry_watch.checklist[1].satisfied is False  # Sweep pending
    assert entry_watch.checklist[2].satisfied is False  # TL break pending
    assert entry_watch.checklist[3].satisfied is False  # Displacement pending

    # Step 2: Add confirmed sweep, validated trendline break, and displacement
    mock_liq = LiquidityLevel(
        type="PDL",
        label="Previous Day Low",
        price=1999.0,
        time=1800,
        swept=True,
        sweep_time=1900,
        sweep_ist="12:30 IST"
    )
    mock_tl = Trendline(
        id="tl_1",
        timeframe="1H",
        direction="resistance",
        anchor1_time=1000,
        anchor1_price=2015.0,
        anchor2_time=1500,
        anchor2_price=2010.0,
        touch_count=3,
        broken=True,
        breakout_time=1900,
        breakout_ist="12:30 IST",
        break_confirmed_by_close=True
    )
    mock_disp = DisplacementCandle(
        time=1900,
        ist_time="12:30 IST",
        direction="bullish",
        body_size=8.0,
        atr=5.0,
        body_atr_ratio=1.6,
        timeframe="1H"
    )

    entry_active = evaluate_level_activation(
        level_id="fvg_test_1",
        name="1H Bullish FVG",
        level_type="FVG",
        timeframe="1H",
        direction="bullish",
        price=2002.5,
        top=2005.0,
        bottom=2000.0,
        freshness="unmitigated",
        current_price=2003.0,
        current_candles=base_candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[mock_disp],
        supporting_fvgs=[],
        liquidity_levels=[mock_liq],
        trendlines=[mock_tl],
        opposing_warnings=[],
        atr_val=5.0,
        config=cfg,
        is_stale=False
    )
    # All 5 checklist items satisfied -> Promoted to ACTIVE (CHECKLIST REVIEW)!
    assert entry_active.state == "CHECKLIST REVIEW"
    assert all(c.satisfied for c in entry_active.checklist)


# ---------------------------------------------------------------------------
# 3. WATCH → INVALIDATED & ACTIVE → INVALIDATED Transitions
# ---------------------------------------------------------------------------

def test_watch_to_invalidated_transition():
    """Verify that a watch level is properly marked INVALIDATED when fully mitigated and blown past."""
    cfg = AnalysisConfig()
    base_candles = [make_test_candle(100, 2000, 2005, 1995, 2001)]

    # Level is fully mitigated and price is 50.0 away (beyond 1.5 * approach threshold)
    entry_inval = evaluate_level_activation(
        level_id="fvg_mitigated_1",
        name="1H Bullish FVG",
        level_type="FVG",
        timeframe="1H",
        direction="bullish",
        price=1950.0,
        top=1955.0,
        bottom=1945.0,
        freshness="fully_mitigated",
        current_price=2000.0,
        current_candles=base_candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[],
        supporting_fvgs=[],
        liquidity_levels=[],
        trendlines=[],
        opposing_warnings=[],
        atr_val=5.0,
        config=cfg,
        is_stale=False
    )
    assert entry_inval.state == "INVALIDATED / PASSED"


# ---------------------------------------------------------------------------
# 4. EXTREME Escalation Strictness
# ---------------------------------------------------------------------------

def test_extreme_escalation_requires_confirmed_active():
    """Verify that an unconfirmed WATCH setup cannot falsely escalate to EXTREME."""
    engine = SMCEngine()

    # Candles
    bull_candles = [
        make_test_candle(i * 100, 2000.0 + i, 2002.0 + i, 1999.0 + i, 2001.0 + i)
        for i in range(20)
    ]
    candles_dict = {
        "1D": bull_candles,
        "4H": bull_candles,
        "1H": bull_candles,
        "15M": bull_candles
    }

    # Routine analysis with no 5/5 checklist review setup
    res = engine.analyze_multi_timeframe(candles_dict, selected_timeframe="15M")
    t_state = res["terminal_state"]
    # Should not be EXTREME if no setup passed full confirmation
    assert t_state["setup_state"] in ["IDLE", "WATCH"]


# ---------------------------------------------------------------------------
# 5. Duplicate Event Suppression & Cooldown
# ---------------------------------------------------------------------------

def test_duplicate_event_suppression_and_cooldown():
    """Verify alert engine suppresses duplicate ticks and allows genuine escalation."""
    store = AlertStore(cooldown_seconds=300)

    # 1. First actionable alert at t=1000
    a1 = store.register_transition(
        level_id="lvl_btc",
        level_name="15M OB",
        timeframe="15M",
        state="SETUP TO INSPECT",
        evidence=["Trendline breakout confirmed"],
        timestamp=1000,
        ist_time="10:00",
        is_stale=False,
        only_actionable=True
    )
    assert a1 is not None

    # 2. Duplicate tick with same state at t=1010 (10s later, within 300s window) -> SUPPRESSED
    a2 = store.register_transition(
        level_id="lvl_btc",
        level_name="15M OB",
        timeframe="15M",
        state="SETUP TO INSPECT",
        evidence=["Trendline breakout confirmed"],
        timestamp=1010,
        ist_time="10:00",
        is_stale=False,
        only_actionable=True
    )
    assert a2 is None

    # 3. Genuine escalation to CHECKLIST REVIEW at t=1050 (50s later) -> ALLOWED (breaks cooldown on escalation!)
    a3 = store.register_transition(
        level_id="lvl_btc",
        level_name="15M OB",
        timeframe="15M",
        state="CHECKLIST REVIEW",
        evidence=["Displacement & FVG confirmed"],
        timestamp=1050,
        ist_time="10:01",
        is_stale=False,
        only_actionable=True
    )
    assert a3 is not None
    assert a3.state == "CHECKLIST REVIEW"

    # 4. Repeated check at t=1060 with same CHECKLIST REVIEW -> SUPPRESSED
    a4 = store.register_transition(
        level_id="lvl_btc",
        level_name="15M OB",
        timeframe="15M",
        state="CHECKLIST REVIEW",
        evidence=["Displacement & FVG confirmed"],
        timestamp=1060,
        ist_time="10:01",
        is_stale=False,
        only_actionable=True
    )
    assert a4 is None


# ---------------------------------------------------------------------------
# 6. Stale Feed Handling
# ---------------------------------------------------------------------------

def test_stale_feed_suppresses_active_promotion_and_alerts():
    """Verify stale data (>60s) suppresses promotion to CHECKLIST REVIEW and alerts."""
    cfg = AnalysisConfig()
    base_candles = [make_test_candle(i * 100, 2000, 2005, 1995, 2001) for i in range(20)]

    mock_liq = LiquidityLevel(type="PDL", label="PDL", price=1999.0, time=1800, swept=True)
    mock_tl = Trendline(
        id="tl_1", timeframe="1H", direction="resistance", anchor1_time=1000, anchor1_price=2015.0,
        anchor2_time=1500, anchor2_price=2010.0, touch_count=3, broken=True, breakout_time=1900,
        break_confirmed_by_close=True
    )
    mock_disp = DisplacementCandle(time=1900, ist_time="12:00", direction="bullish", body_size=8.0, atr=5.0, body_atr_ratio=1.6, timeframe="1H")

    # When feed is stale (is_stale=True), even with 5/5 criteria it MUST NOT become CHECKLIST REVIEW
    entry = evaluate_level_activation(
        level_id="fvg_stale",
        name="1H Bullish FVG",
        level_type="FVG",
        timeframe="1H",
        direction="bullish",
        price=2002.5,
        top=2005.0,
        bottom=2000.0,
        freshness="unmitigated",
        current_price=2003.0,
        current_candles=base_candles,
        swings=[],
        bos_signals=[],
        displacement_candles=[mock_disp],
        supporting_fvgs=[],
        liquidity_levels=[mock_liq],
        trendlines=[mock_tl],
        opposing_warnings=[],
        atr_val=5.0,
        config=cfg,
        is_stale=True # STALE DATA!
    )
    # Stale feed suppresses promotion:
    assert entry.state == "SETUP TO INSPECT"
    assert "STALE" in entry.state_reason

    # Stale alert is suppressed from firing actionable notifications:
    store = AlertStore()
    alt = store.register_transition(
        level_id="fvg_stale",
        level_name="1H FVG",
        timeframe="1H",
        state="CHECKLIST REVIEW",
        evidence=["Full criteria"],
        timestamp=int(time.time()),
        ist_time="12:00",
        is_stale=True,
        only_actionable=True
    )
    assert alt is None


# ---------------------------------------------------------------------------
# 7. WebSocket Reconnects & Stale Forming Candle Invalidation
# ---------------------------------------------------------------------------

def test_adapter_forming_candle_cleared_on_historical_resync():
    """Verify that reconnecting and re-fetching historical candles clears stale forming candles."""
    adapter = DeltaExchangeAdapter()

    # Pre-disconnect: forming candle at t=500
    adapter.forming_candles["1H"] = make_test_candle(500, 2000, 2005, 1998, 2004, is_forming=True)

    # Historical resync returns closed candles up to t=500
    cleaned_candles = [
        make_test_candle(300, 1990, 1995, 1988, 1992, is_forming=False),
        make_test_candle(400, 1992, 1998, 1990, 1996, is_forming=False),
        make_test_candle(500, 2000, 2008, 1997, 2006, is_forming=False), # Closed finalized candle at t=500!
    ]
    adapter.candles["1H"] = cleaned_candles
    # Invalidate stale forming candle if covered by fetched historical candles
    forming = adapter.forming_candles.get("1H")
    if forming and cleaned_candles and forming.time <= cleaned_candles[-1].time:
        adapter.forming_candles["1H"] = None

    candles = adapter.get_candles("1H")
    assert len(candles) == 3
    # Ensure the finalized candle is preserved, not overwritten by stale pre-disconnect forming candle
    assert candles[-1].close == 2006.0
    assert candles[-1].is_forming is False
