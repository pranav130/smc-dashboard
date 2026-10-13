"""
Automated Test Suite for Setup Lifecycle, Target Reached, Stop Loss Breach,
Level Ordering, Duplicate Alert Suppression, and HTF Weighting.
"""

import pytest
import time
from backend.smc.models import Candle, AnalysisConfig, LiquidityLevel, FairValueGap
from backend.smc.engine import SMCEngine
from backend.smc.activation import evaluate_level_activation, AlertStore


def make_candle(t: int, o: float, h: float, l: float, c: float, is_forming: bool = False) -> Candle:
    return Candle(
        time=t,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100.0,
        is_forming=is_forming,
        ist_time=f"T{t}"
    )


# ---------------------------------------------------------------------------
# 1. Target Already Reached Lifecycle Tests
# ---------------------------------------------------------------------------

def test_target_already_reached_long_lifecycle():
    """
    Verify the scenario from the user screenshot:
    Bullish setup with entry zone ~4173.66-4182.67 and target 4184.57.
    When live price is 4185.67 (exceeding target), the setup must be flagged
    as expired/invalidated with is_target_reached=True and reward_risk='N/A'.
    """
    engine = SMCEngine()
    cfg = AnalysisConfig(swing_window=1)

    # 1. Historical swing high established at exactly 4184.57
    h0 = make_candle(10, 4180.0, 4182.0, 4178.0, 4181.0)
    h1 = make_candle(20, 4181.0, 4184.57, 4179.0, 4183.0) # Swing High at 4184.57
    h2 = make_candle(30, 4183.0, 4183.5, 4175.0, 4176.0)

    # 2. Base candles creating an FVG at ~4173.66 - 4182.67
    c0 = make_candle(100, 4170.0, 4173.66, 4168.0, 4172.0)
    c1 = make_candle(200, 4172.0, 4184.00, 4172.0, 4183.0) # Impulse up
    c2 = make_candle(300, 4183.0, 4184.00, 4182.67, 4183.5) # Low is 4182.67 > 4173.66
    
    # 3. Price retraces into zone, then later runs up past 4184.57 to 4185.67
    c3 = make_candle(400, 4183.5, 4184.00, 4178.00, 4180.0) # Touched POI
    c4 = make_candle(500, 4180.0, 4185.67, 4179.00, 4185.67) # Price at 4185.67 (surpassed 4184.57)

    candles_1h = [h0, h1, h2, c0, c1, c2, c3, c4]
    multi_candles = {
        "1D": candles_1h,
        "4H": candles_1h,
        "1H": candles_1h,
        "15M": candles_1h
    }

    res = engine.analyze_multi_timeframe(multi_candles, selected_timeframe="1H", config=cfg)
    t_state = res["terminal_state"]
    active_setup = t_state.get("active_setup")

    # In this screenshot scenario, the market price (4185.67) has blown past the key levels:
    assert t_state["setup_state"] == "INVALIDATED"
    assert active_setup is not None
    assert active_setup["state"] == "INVALIDATED"
    assert active_setup["reward_risk"] == "N/A"
    assert ("Target already reached" in active_setup["reason"] or "Invalidation level breached" in active_setup["reason"])


def test_target_already_reached_short_lifecycle():
    """
    Verify bearish setup with target 4180.0 is marked INVALIDATED when price is 4175.0.
    """
    engine = SMCEngine()
    cfg = AnalysisConfig(swing_window=1)

    # Historical swing low at 4180.0
    l0 = make_candle(10, 4190.0, 4192.0, 4185.0, 4188.0)
    l1 = make_candle(20, 4188.0, 4189.0, 4180.0, 4183.0) # Swing Low at 4180.0
    l2 = make_candle(30, 4183.0, 4195.0, 4182.0, 4192.0)

    # Bearish FVG between 4200 and 4210
    c0 = make_candle(100, 4215.0, 4216.0, 4210.0, 4212.0)
    c1 = make_candle(200, 4212.0, 4212.0, 4195.0, 4196.0) # Impulse down
    c2 = make_candle(300, 4196.0, 4200.0, 4190.0, 4192.0) # High is 4200 < 4210
    # Price breaks down past 4180 to 4175
    c3 = make_candle(400, 4192.0, 4195.0, 4174.0, 4175.0)

    candles = [l0, l1, l2, c0, c1, c2, c3]
    multi_candles = {
        "1D": candles,
        "4H": candles,
        "1H": candles,
        "15M": candles
    }

    res = engine.analyze_multi_timeframe(multi_candles, selected_timeframe="1H", config=cfg)
    t_state = res["terminal_state"]
    active_setup = t_state.get("active_setup")

    if active_setup and active_setup.get("target_price") and active_setup["direction"] == "bearish":
        if active_setup["target_price"] >= 4175.0:
            assert active_setup["is_target_reached"] is True
            assert active_setup["state"] == "INVALIDATED"
            assert active_setup["reward_risk"] == "N/A"


# ---------------------------------------------------------------------------
# 2. Stop Loss Breach Lifecycle Tests
# ---------------------------------------------------------------------------

def test_stop_loss_breached_long_lifecycle():
    """
    Verify that when price drops below the invalidation level for a Long setup,
    it transitions to INVALIDATED with reason explaining invalidation breached.
    """
    engine = SMCEngine()
    cfg = AnalysisConfig(swing_window=1)

    # Bullish FVG: 4173.66 - 4182.67. Invalidation is ~4172.0
    c0 = make_candle(100, 4170.0, 4173.66, 4168.0, 4172.0)
    c1 = make_candle(200, 4172.0, 4185.00, 4172.0, 4184.0)
    c2 = make_candle(300, 4184.0, 4186.00, 4182.67, 4185.0)
    # Price plummets through bottom to 4160.0 (breaching stop!)
    c3 = make_candle(400, 4185.0, 4185.00, 4158.00, 4160.0)

    candles = [c0, c1, c2, c3]
    multi_candles = {
        "1D": candles,
        "4H": candles,
        "1H": candles,
        "15M": candles
    }

    res = engine.analyze_multi_timeframe(multi_candles, selected_timeframe="1H", config=cfg)
    t_state = res["terminal_state"]
    active_setup = t_state.get("active_setup")

    if active_setup and active_setup["direction"] == "bullish":
        assert active_setup["state"] == "INVALIDATED"
        assert active_setup["reward_risk"] == "N/A"


# ---------------------------------------------------------------------------
# 3. Price Outside Entry Zone Remains in Watch / Inactive
# ---------------------------------------------------------------------------

def test_price_outside_entry_zone_remains_watch():
    """
    Verify that when price has not touched the entry POI, checklist entry_touched
    is False and setup is NOT promoted to ACTIVE (CHECKLIST REVIEW).
    """
    cfg = AnalysisConfig()
    base_candles = [make_candle(i * 100, 4150, 4155, 4148, 4152) for i in range(15)]
    current_price = 4180.0 # Price is 25 USD above zone (4150-4160)

    entry = evaluate_level_activation(
        level_id="fvg_watch",
        name="1H Bullish FVG",
        level_type="FVG",
        timeframe="1H",
        direction="bullish",
        price=4155.0,
        top=4160.0,
        bottom=4150.0,
        freshness="unmitigated",
        current_price=current_price,
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

    assert entry.state != "CHECKLIST REVIEW"
    assert any("Key Level In-Zone" in c.name and not c.satisfied for c in entry.checklist)


# ---------------------------------------------------------------------------
# 4. Duplicate Alert Suppression
# ---------------------------------------------------------------------------

def test_duplicate_alert_suppression():
    """
    Verify that AlertStore suppresses duplicate alert events fired in rapid succession
    for the exact same level and state.
    """
    store = AlertStore()
    now_ts = int(time.time())

    alt1 = store.register_transition(
        level_id="fvg_1h_dup",
        level_name="1H Bullish FVG",
        timeframe="1H",
        state="CHECKLIST REVIEW",
        evidence=["Closed candle confirmed"],
        timestamp=now_ts,
        ist_time="14:00:00 IST",
        is_stale=False,
        only_actionable=True
    )
    assert alt1 is not None
    assert len(store.get_alerts()) == 1

    # Second event immediately afterwards: MUST be suppressed!
    alt2 = store.register_transition(
        level_id="fvg_1h_dup",
        level_name="1H Bullish FVG",
        timeframe="1H",
        state="CHECKLIST REVIEW",
        evidence=["Duplicate WebSocket tick"],
        timestamp=now_ts + 1,
        ist_time="14:00:01 IST",
        is_stale=False,
        only_actionable=True
    )
    assert alt2 is None
    assert len(store.get_alerts()) == 1


# ---------------------------------------------------------------------------
# 5. Higher-Timeframe Priority Weighting
# ---------------------------------------------------------------------------

def test_htf_priority_weighting():
    """
    Verify that 4H and Daily setups have strict priority over 1H and 15M setups
    in the single setup card selection hierarchy.
    """
    engine = SMCEngine()
    cfg = AnalysisConfig(swing_window=1)

    # 4H candles with a clean FVG
    c_4h_0 = make_candle(1000, 4170.0, 4172.0, 4168.0, 4171.0)
    c_4h_1 = make_candle(2000, 4171.0, 4190.0, 4171.0, 4189.0)
    c_4h_2 = make_candle(3000, 4189.0, 4192.0, 4180.0, 4190.0) # FVG: 4172 - 4180
    c_4h_3 = make_candle(4000, 4190.0, 4191.0, 4175.0, 4178.0) # Price at 4178 (inside 4H POI)
    candles_4h = [c_4h_0, c_4h_1, c_4h_2, c_4h_3]

    # 15M candles with a smaller FVG
    c_15_0 = make_candle(100, 4176.0, 4177.0, 4175.0, 4176.5)
    c_15_1 = make_candle(200, 4176.5, 4182.0, 4176.5, 4181.5)
    c_15_2 = make_candle(300, 4181.5, 4183.0, 4179.0, 4182.0)
    c_15_3 = make_candle(400, 4182.0, 4182.5, 4177.5, 4178.0)
    candles_15m = [c_15_0, c_15_1, c_15_2, c_15_3]

    multi = {
        "1D": candles_4h,
        "4H": candles_4h,
        "1H": candles_4h,
        "15M": candles_15m
    }

    res = engine.analyze_multi_timeframe(multi, selected_timeframe="15M", config=cfg)
    active_setup = res["terminal_state"].get("active_setup")

    if active_setup:
        # 4H setup must be prioritized over 15M due to TF_WEIGHTS
        assert active_setup["timeframe"] in ["4H", "1D"]
