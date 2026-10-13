import pytest
import time
from backend.smc.models import Candle, AnalysisConfig
from backend.smc.engine import SMCEngine
from backend.smc.activation import AlertStore


def make_candle(t: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(
        time=t,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100.0,
        ist_time="12:00"
    )


def test_market_bias_mixed_and_directional():
    engine = SMCEngine()
    cfg = AnalysisConfig(swing_window=1)

    # Bullish: SL(10) -> SH(20) -> SL(14, HL) -> SH(26, HH)
    bull_candles = [
        make_candle(0, 12, 12, 12, 12),
        make_candle(100, 11, 12, 10, 11),  # SL 10
        make_candle(200, 12, 16, 12, 15),
        make_candle(300, 16, 20, 15, 19),  # SH 20
        make_candle(400, 18, 18, 16, 16),
        make_candle(500, 16, 17, 14, 15),  # SL 14 (HL)
        make_candle(600, 16, 22, 16, 21),
        make_candle(700, 21, 26, 20, 25),  # SH 26 (HH)
        make_candle(800, 24, 24, 22, 23),
        make_candle(900, 23, 23, 21, 22),
    ]

    # Bearish: SH(30) -> SL(20) -> SH(25, LH) -> SL(15, LL)
    bear_candles = [
        make_candle(0, 28, 28, 28, 28),
        make_candle(100, 28, 30, 27, 29),  # SH 30
        make_candle(200, 27, 28, 24, 25),
        make_candle(300, 24, 24, 20, 21),  # SL 20
        make_candle(400, 22, 23, 21, 22),
        make_candle(500, 22, 25, 21, 24),  # SH 25 (LH)
        make_candle(600, 23, 23, 18, 19),
        make_candle(700, 18, 19, 15, 16),  # SL 15 (LL)
        make_candle(800, 16, 17, 16, 17),
        make_candle(900, 16, 17, 15, 16),
    ]

    # Test Mixed bias: 1D is Bullish, 4H is Bearish
    candles_mixed = {
        "1D": bull_candles,
        "4H": bear_candles,
        "1H": bull_candles,
        "15M": bull_candles
    }
    res_mixed = engine.analyze_multi_timeframe(candles_mixed, selected_timeframe="15M", config=cfg)
    t_state_mixed = res_mixed["terminal_state"]
    assert t_state_mixed["market_bias"] == "MIXED"
    assert t_state_mixed["bias_details"]["1D"] == "BULLISH"
    assert t_state_mixed["bias_details"]["4H"] == "BEARISH"

    # Test Pure Bullish bias
    candles_bull = {
        "1D": bull_candles,
        "4H": bull_candles,
        "1H": bull_candles,
        "15M": bull_candles
    }
    res_bull = engine.analyze_multi_timeframe(candles_bull, selected_timeframe="15M", config=cfg)
    t_state_bull = res_bull["terminal_state"]
    assert t_state_bull["market_bias"] == "BULLISH"


def test_risk_state_stale_and_normal():
    engine = SMCEngine()
    candles = {
        "15M": [make_candle(100 + i * 60, 2000.0, 2005.0, 1995.0, 2002.0) for i in range(20)]
    }

    # Stale feed
    res_stale = engine.analyze_multi_timeframe(candles, selected_timeframe="15M", is_stale=True)
    assert res_stale["terminal_state"]["risk_state"] == "CRITICAL"
    assert any("stale" in r.lower() for r in res_stale["terminal_state"]["risk_reasons"])

    # Fresh feed
    res_fresh = engine.analyze_multi_timeframe(candles, selected_timeframe="15M", is_stale=False)
    assert res_fresh["terminal_state"]["risk_state"] in ["NORMAL", "CAUTION"]


def test_alert_store_actionable_filtering():
    store = AlertStore()

    # Routine approaching alert with only_actionable=True should NOT produce an alert
    alt_routine = store.register_transition(
        level_id="lvl_watch_1",
        level_name="4H Bullish FVG",
        timeframe="4H",
        state="APPROACHING",
        evidence=["Within 0.35%"],
        timestamp=int(time.time()),
        ist_time="14:30",
        is_stale=False,
        only_actionable=True
    )
    assert alt_routine is None

    # Active checklist review alert should produce an alert
    alt_active = store.register_transition(
        level_id="lvl_active_1",
        level_name="15M Order Block",
        timeframe="15M",
        state="CHECKLIST REVIEW",
        evidence=["Full 5/5 SMC confirmation passed"],
        timestamp=int(time.time()),
        ist_time="14:35",
        is_stale=False,
        only_actionable=True
    )
    assert alt_active is not None
    assert alt_active.state == "CHECKLIST REVIEW"
    assert "[ACTIVE SETUP]" in alt_active.message
