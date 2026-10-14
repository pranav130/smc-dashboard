import pytest
from backend.risk.rejection_inspector import RejectionInspector
from backend.backtesting.engine import BacktestEngine
from backend.smc.models import Candle


def make_candle(ts, o, h, l, c, v=10.0):
    return Candle(
        time=ts, open=float(o), high=float(h), low=float(l), close=float(c),
        volume=float(v), is_forming=False, ist_time="2026-10-14 12:00:00 IST",
        utc_time="2026-10-14 06:30:00 UTC"
    )


def test_rejection_inspector_recording_and_filtering():
    """Verify RejectionInspector records telemetry and filters accurately."""
    inspector = RejectionInspector(max_records=100)

    # Record 3 rejections
    r1 = inspector.record_rejection(
        model="MODEL_A",
        stage_failed="NO_QUALIFYING_SWEEP",
        reasons=["No sweep in last 20 bars"],
        evaluated_price=4100.0,
        setup_id="s1",
        direction="bullish"
    )
    r2 = inspector.record_rejection(
        model="MODEL_B",
        stage_failed="NO_BROKEN_TRENDLINE",
        reasons=["Trendline not broken by close"],
        evaluated_price=4105.0,
        setup_id="s2",
        direction="bearish"
    )
    r3 = inspector.record_rejection(
        model="MODEL_A",
        stage_failed="NET_RR_BELOW_THRESHOLD",
        reasons=["Net R:R 1.4 < 2.0"],
        evaluated_price=4110.0,
        setup_id="s3",
        direction="bullish"
    )

    all_rejections = inspector.get_rejections(limit=10)
    assert len(all_rejections) == 3
    # Latest first
    assert all_rejections[0]["id"] == r3["id"]

    # Filter by model
    model_a_only = inspector.get_rejections(model_filter="MODEL_A")
    assert len(model_a_only) == 2

    # Filter by stage
    sweep_only = inspector.get_rejections(stage_filter="NO_QUALIFYING_SWEEP")
    assert len(sweep_only) == 1
    assert sweep_only[0]["setup_id"] == "s1"

    # Summary
    summary = inspector.get_rejection_summary()
    assert summary["total_rejections"] == 3
    assert summary["by_model"]["MODEL_A"] == 2
    assert summary["by_model"]["MODEL_B"] == 1
    assert summary["by_stage"]["NO_QUALIFYING_SWEEP"] == 1


def test_backtest_engine_walk_forward_splits():
    """Verify BacktestEngine executes chronological 60/20/20 walk-forward splits."""
    engine = BacktestEngine(starting_equity=10000.0)

    # 100 hourly candles
    candles = [make_candle(1000 + i * 3600, 4000 + (i % 20), 4010 + (i % 20), 3990 + (i % 20), 4005 + (i % 20)) for i in range(100)]

    wf_results = engine.run_walk_forward_validation(candles_1h=candles, strategy_mode="COMBINED")
    assert "splits" in wf_results
    splits = wf_results["splits"]
    assert "in_sample_train" in splits
    assert "validation" in splits
    assert "out_of_sample_test" in splits

    train_res = splits["in_sample_train"]
    assert train_res["split"] == "TRAIN_60_PCT"
    assert "monte_carlo" in train_res


def test_monte_carlo_resampling():
    """Verify Monte Carlo simulation resamples trades and returns 95% confidence intervals."""
    engine = BacktestEngine(starting_equity=10000.0)

    # Dummy trade returns: mix of wins and losses with positive expectancy
    trades = [
        {"net_pnl": 50.0},
        {"net_pnl": -25.0},
        {"net_pnl": 65.0},
        {"net_pnl": -25.0},
        {"net_pnl": 45.0},
        {"net_pnl": -25.0},
    ]

    mc = engine._monte_carlo_resample(trades, num_simulations=1000)
    assert mc["simulations"] == 1000
    assert "median_max_dd_pct" in mc
    assert "ci_95_max_dd_pct" in mc
    assert mc["ci_95_max_dd_pct"] >= mc["median_max_dd_pct"]
    assert "probability_of_ruin_pct" in mc
    # With small non-martingale risk, probability of 20% ruin should be low/zero
    assert mc["probability_of_ruin_pct"] <= 5.0
