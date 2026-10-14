import pytest
from backend.smc.models import (
    Candle, LiquidityLevel, FairValueGap, TrendState, Trendline,
    SwingPoint, DisplacementCandle, BreakOfStructure
)
from backend.smc.strategies.model_a_sweep import evaluate_model_a
from backend.smc.strategies.model_b_trendline import evaluate_model_b


def make_candle(ts, o, h, l, c, v=10.0, is_forming=False):
    return Candle(
        time=ts, open=float(o), high=float(h), low=float(l), close=float(c),
        volume=float(v), is_forming=is_forming, ist_time="2026-10-14 12:00:00 IST",
        utc_time="2026-10-14 06:30:00 UTC"
    )


def test_model_a_bullish_sweep_and_retracement():
    """Verify Model A generates an ACTIVE or WATCH signal upon bullish liquidity sweep & displacement."""
    # 20 hours of hourly candles
    candles = [make_candle(1000 + i * 3600, 4100, 4110, 4095, 4105) for i in range(20)]
    now_ts = candles[-1].time

    # Liquidity level: PDL at 4090 was swept 2 hours ago
    sweep_ts = now_ts - 7200
    pdl = LiquidityLevel(
        type="PDL", label="Previous Day Low", price=4090.0, time=sweep_ts - 36000,
        swept=True, sweep_time=sweep_ts, sweep_ist="2026-10-14 10:00:00 IST"
    )

    # 4H trend is bullish
    h4_trend = TrendState(trend="bullish")
    daily_trend = TrendState(trend="bullish")

    # Displacement candle printed after sweep
    disp = DisplacementCandle(
        time=sweep_ts + 3600, direction="bullish", body_size=15.0,
        atr=10.0, body_atr_ratio=1.5, timeframe="1H",
        ist_time="2026-10-14 11:00:00 IST"
    )

    # Supporting 1H FVG created after sweep: [4095 - 4102], mid 4098.5
    fvg = FairValueGap(
        id="fvg_1h_1", timeframe="1H", direction="bullish", top=4102.0, bottom=4095.0,
        midpoint=4098.5, start_time=sweep_ts + 3600, size=7.0
    )

    # 1. Price is at 4099 (inside FVG) -> ACTIVE
    setup, telemetry = evaluate_model_a(
        current_price=4099.0,
        candles_1h=candles,
        daily_trend=daily_trend,
        h4_trend=h4_trend,
        h4_fvgs=[],
        h1_fvgs=[fvg],
        liquidity_levels=[pdl],
        bos_signals=[],
        displacement_candles=[disp],
        atr_val=10.0,
        is_stale=False
    )

    assert setup is not None
    assert setup.name == "Model A: SMC Sweep & Retracement"
    assert setup.direction == "bullish"
    assert setup.state == "ACTIVE"
    assert setup.top == 4102.0
    assert setup.bottom == 4095.0
    assert setup.invalidation_price < 4095.0
    assert setup.target_price > 4102.0
    assert "1:" in setup.reward_risk
    assert telemetry["passed"] is True

    # 2. Price is at 4105 (above entry zone 4095-4102, but below target 4109.75) -> WATCH
    setup_watch, telem_watch = evaluate_model_a(
        current_price=4105.0,
        candles_1h=candles,
        daily_trend=daily_trend,
        h4_trend=h4_trend,
        h4_fvgs=[],
        h1_fvgs=[fvg],
        liquidity_levels=[pdl],
        bos_signals=[],
        displacement_candles=[disp],
        atr_val=10.0,
        is_stale=False
    )
    assert setup_watch is not None
    assert setup_watch.state == "WATCH"


def test_model_a_rejection_no_sweep():
    """Verify Model A rejects setup if no liquidity was swept recently."""
    candles = [make_candle(1000 + i * 3600, 4100, 4110, 4095, 4105) for i in range(20)]
    pdl = LiquidityLevel(
        type="PDL", label="Previous Day Low", price=4090.0, time=1000, swept=False
    )
    setup, telemetry = evaluate_model_a(
        current_price=4100.0,
        candles_1h=candles,
        daily_trend=TrendState(trend="bullish"),
        h4_trend=TrendState(trend="bullish"),
        h4_fvgs=[],
        h1_fvgs=[],
        liquidity_levels=[pdl],
        bos_signals=[],
        displacement_candles=[],
        atr_val=10.0,
        is_stale=False
    )
    assert setup is None
    assert telemetry["passed"] is False
    assert telemetry["stage_failed"] == "NO_QUALIFYING_SWEEP"


def test_model_b_structural_trendline_break():
    """Verify Model B generates an independent breakout setup."""
    candles = [make_candle(1000 + i * 3600, 4100, 4110, 4095, 4105) for i in range(20)]
    now_ts = candles[-1].time

    # Descending trendline (resistance) broken with close confirmation 2 hours ago
    break_ts = now_ts - 7200
    tl = Trendline(
        id="tl_res_1",
        timeframe="1H",
        direction="resistance",
        anchor1_time=now_ts - 36000,
        anchor1_price=4150.0,
        anchor2_time=now_ts - 18000,
        anchor2_price=4130.0,
        touch_count=3,
        broken=True,
        breakout_time=break_ts,
        breakout_ist="2026-10-14 10:00:00 IST",
        break_confirmed_by_close=True,
        has_higher_low_pre_break=True,
        current_projected_price=4108.0
    )

    swings = [
        SwingPoint(time=now_ts - 14400, confirm_time=now_ts - 10800, price=4092.0, type="low", timeframe="1H", label="HL"),
        SwingPoint(time=now_ts - 21600, confirm_time=now_ts - 18000, price=4130.0, type="high", timeframe="1H", label="LH"),
    ]

    # Evaluate at 4109 (in retest zone around projected 4108)
    setup, telemetry = evaluate_model_b(
        current_price=4109.0,
        candles_1h=candles,
        trendlines=[tl],
        swings=swings,
        h1_fvgs=[],
        atr_val=10.0,
        is_stale=False
    )

    assert setup is not None
    assert setup.name == "Model B: Structural Trendline Break"
    assert setup.direction == "bullish"
    assert setup.state == "ACTIVE"
    assert setup.invalidation_price < 4108.0
    assert setup.target_price > 4109.0
    assert "1:" in setup.reward_risk
    assert telemetry["passed"] is True


def test_model_b_rejection_without_close_confirmation():
    """Verify Model B rejects trendline breaks that are not confirmed by candle close."""
    candles = [make_candle(1000 + i * 3600, 4100, 4110, 4095, 4105) for i in range(20)]
    now_ts = candles[-1].time

    tl = Trendline(
        id="tl_res_wick",
        timeframe="1H",
        direction="resistance",
        anchor1_time=now_ts - 36000,
        anchor1_price=4150.0,
        anchor2_time=now_ts - 18000,
        anchor2_price=4130.0,
        touch_count=2,
        broken=True,
        breakout_time=now_ts - 3600,
        break_confirmed_by_close=False,  # only wicked
        has_higher_low_pre_break=True,
        current_projected_price=4108.0
    )

    setup, telemetry = evaluate_model_b(
        current_price=4109.0,
        candles_1h=candles,
        trendlines=[tl],
        swings=[],
        h1_fvgs=[],
        atr_val=10.0,
        is_stale=False
    )
    assert setup is None
    assert telemetry["passed"] is False
    assert telemetry["stage_failed"] == "NO_BROKEN_TRENDLINE"
