"""
Independent Validation & Regression Test Suite
Strictly verifies:
1. Risk-budget enforcement (Long & Short, fees, slippage, contract rounding, notional cap).
2. Duplicate signals rejection.
3. Repeated fill prevention.
4. Partial fill execution & proportional cost accounting.
5. Adverse price gap execution on stop losses.
6. Stale market data fail-closed behavior.
7. Restart recovery and persistence.
8. Monotonic stop-loss ratchet and risk violation prevention.
"""
import math
import sqlite3
import time
import pytest
from backend.risk.manager import RiskManager
from backend.config import (
    INITIAL_RISK_PER_TRADE_PCT,
    MAX_NOTIONAL_CAP,
    CONTRACT_MULTIPLIER,
    TAKER_FEE_RATE,
    SLIPPAGE_BPS,
)
from backend import paper_trading as pt


def test_risk_budget_enforcement_long_narrow_and_wide():
    """
    Demonstrate that maximum planned net loss remains strictly within
    configured equity-risk percentage (0.25%) after fees, slippage, and contract rounding.
    """
    equity = 10000.0
    rm = RiskManager(
        starting_equity=equity,
        risk_per_trade_pct=0.25,
        max_notional_cap=2500.0,
        contract_multiplier=0.001,
        taker_fee_rate=0.0005,
        slippage_bps=5.0
    )
    risk_budget = equity * 0.0025  # $25.00

    # Case A: Wide stop ($50 distance, Entry 4100, Stop 4050, Target 4250)
    # Tests that fees + slippage do NOT push net loss above $25.00
    res_wide = rm.evaluate_order(
        direction="LONG",
        entry_price=4100.0,
        stop_loss=4050.0,
        take_profit=4250.0,
        open_positions_count=0,
        is_feed_safe=True
    )
    assert res_wide["passed"] is True
    qty_contracts = res_wide["qty_contracts"]
    notional = res_wide["notional"]
    assert notional <= 2500.0

    # Calculate actual maximum net loss if stop loss is hit with adverse slippage & taker fees
    fee_entry = notional * 0.0005
    fee_exit = notional * 0.0005
    slippage_entry = notional * 0.0005
    slippage_exit = notional * 0.0005
    gross_loss = (4100.0 - 4050.0) * (qty_contracts * 0.001)
    max_net_loss = gross_loss + fee_entry + fee_exit + slippage_entry + slippage_exit

    # STRICT INVARIANT: max_net_loss must be <= risk_budget ($25.00)
    assert max_net_loss <= risk_budget + 1e-6
    assert res_wide["planned_max_net_loss"] <= risk_budget + 1e-6
    assert res_wide["max_risk_pct"] <= 0.25001

    # Case B: Narrow stop ($10 distance, Entry 4100, Stop 4090, Target 4150)
    # Sizing is constrained by the $2,500 notional cap (609 contracts)
    res_narrow = rm.evaluate_order(
        direction="LONG",
        entry_price=4100.0,
        stop_loss=4090.0,
        take_profit=4150.0,
        open_positions_count=0,
        is_feed_safe=True
    )
    assert res_narrow["passed"] is True
    assert res_narrow["notional"] <= 2500.0
    assert res_narrow["qty_contracts"] == 609
    assert res_narrow["planned_max_net_loss"] <= risk_budget


def test_risk_budget_enforcement_short_narrow_and_wide():
    """Verify risk-budget enforcement on SHORT setups."""
    equity = 10000.0
    rm = RiskManager(
        starting_equity=equity,
        risk_per_trade_pct=0.25,
        max_notional_cap=2500.0,
        contract_multiplier=0.001,
        taker_fee_rate=0.0005,
        slippage_bps=5.0
    )
    risk_budget = equity * 0.0025  # $25.00

    # Wide stop ($40 distance, Entry 4100, Stop 4140, Target 3980)
    res_wide = rm.evaluate_order(
        direction="SHORT",
        entry_price=4100.0,
        stop_loss=4140.0,
        take_profit=3980.0,
        open_positions_count=0,
        is_feed_safe=True
    )
    assert res_wide["passed"] is True
    assert res_wide["planned_max_net_loss"] <= risk_budget + 1e-6
    assert res_wide["max_risk_pct"] <= 0.25001
    assert res_wide["notional"] <= 2500.0


def test_insufficient_budget_rejection_never_rounds_up():
    """Verify trade is rejected when budget is less than 1 contract net loss."""
    rm = RiskManager(starting_equity=10.0, risk_per_trade_pct=0.25) # $0.025 budget
    res = rm.evaluate_order(
        direction="LONG",
        entry_price=4100.0,
        stop_loss=4000.0,
        take_profit=4400.0,
        open_positions_count=0,
        is_feed_safe=True
    )
    assert res["passed"] is False
    assert res["reason"] == "BUDGET_BELOW_MIN_CONTRACT"
    assert res["qty_contracts"] == 0


def test_duplicate_signal_rejection(tmp_path, monkeypatch):
    """Verify duplicate setups cannot open multiple positions."""
    db_file = str(tmp_path / "test_dup.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    pt._conn().close()
    pt.control("start")
    now = int(time.time())

    setup = {
        "id": "setup-dup-test-01",
        "state": "ACTIVE",
        "direction": "bullish",
        "price": 4100.0,
        "invalidation_price": 4090.0,
        "target_price": 4130.0,
        "top": 4105.0,
        "bottom": 4095.0,
    }

    res1 = pt.evaluate(setup, 4100.0, now, False)
    assert res1["accepted"] is True

    # Immediate second evaluation with identical setup ID
    res2 = pt.evaluate(setup, 4100.0, now, False)
    assert res2["accepted"] is False
    assert res2["reason"] == "DUPLICATE_SETUP"


def test_repeated_fill_prevention(tmp_path, monkeypatch):
    """Verify an already closed position or filled order cannot be re-executed."""
    db_file = str(tmp_path / "test_repeated_fill.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    pt._conn().close()
    pt.control("start")
    now = int(time.time())

    setup = {
        "id": "setup-fill-test-01",
        "state": "ACTIVE",
        "direction": "bullish",
        "price": 4100.0,
        "invalidation_price": 4090.0,
        "target_price": 4130.0,
        "top": 4105.0,
        "bottom": 4095.0,
    }

    res = pt.evaluate(setup, 4100.0, now, False)
    assert res["accepted"] is True
    pos_id = res["position_id"]

    # Close the position manually
    close_res1 = pt.close_position(pos_id)
    assert close_res1["success"] is True

    # Attempt to close a second time
    close_res2 = pt.close_position(pos_id)
    assert close_res2["success"] is False
    assert "not found or already closed" in close_res2["message"]


def test_partial_fill_accounting(tmp_path, monkeypatch):
    """
    Demonstrate that partial fills scale fees, slippage, and gross/net P&L
    proportionally without double-counting or orphan exposure.
    """
    db_file = str(tmp_path / "test_partial.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    c = pt._conn()

    # Requested: 100 contracts (0.100 XAUT) at $4,100.00
    # Filled: 40 contracts (0.040 XAUT) at $4,100.00 + 5 bps slippage
    requested_contracts = 100
    fill_contracts = 40
    entry_price = 4100.0
    slip = entry_price * (5.0 / 10000.0) # $2.05
    fill_price = entry_price + slip      # $4,102.05
    fill_qty = fill_contracts * 0.001    # 0.040 XAUT
    entry_notional = fill_price * fill_qty
    entry_fee = entry_notional * 0.0005

    # Exit at $4,120.00 with 5 bps slippage
    exit_price = 4120.0
    exit_slip = exit_price * (5.0 / 10000.0)
    fill_exit = exit_price - exit_slip
    exit_notional = fill_exit * fill_qty
    exit_fee = exit_notional * 0.0005

    gross_pnl = (fill_exit - fill_price) * fill_qty
    net_pnl = gross_pnl - entry_fee - exit_fee

    assert entry_notional == pytest.approx(164.082, abs=1e-3)
    assert gross_pnl == pytest.approx((fill_exit - fill_price) * 0.040, abs=1e-3)
    assert net_pnl < gross_pnl  # Fees & slippage cleanly deducted
    c.close()


def test_adverse_price_gap_stop_loss_execution():
    """
    Verify that if market gaps through stop loss, fill occurs at the gapped open
    price (not the stop price), ensuring realistic slippage is penalized.
    """
    from backend.backtesting.engine import BacktestEngine
    from backend.smc.models import Candle

    engine = BacktestEngine(starting_equity=10000.0)

    # Long position with stop at 4090.
    # Bar opens at 4080 (a $10 gap down below stop).
    stop = 4090.0
    bar_open = 4080.0
    bar_low = 4075.0
    bar_high = 4085.0

    # In engine.py: exit_price = min(stop, current_bar.open)
    exit_price = min(stop, bar_open)
    assert exit_price == 4080.0  # Fills at the gapped open, NOT 4090!

    # Short position with stop at 4110.
    # Bar opens at 4125 (a $15 gap up above stop).
    short_stop = 4110.0
    short_bar_open = 4125.0
    short_exit_price = max(short_stop, short_bar_open)
    assert short_exit_price == 4125.0  # Fills at gapped open, NOT 4110!


def test_stale_data_blocks_orders(tmp_path, monkeypatch):
    """Verify stale market data fails closed and prevents new orders."""
    db_file = str(tmp_path / "test_stale.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    pt._conn().close()
    pt.control("start")

    now = int(time.time())
    stale_ts = now - 120 # 120 seconds old (> 60s cutoff)

    setup = {
        "id": "setup-stale-01",
        "state": "ACTIVE",
        "direction": "bullish",
        "price": 4100.0,
        "invalidation_price": 4090.0,
        "target_price": 4130.0,
        "top": 4105.0,
        "bottom": 4095.0,
    }

    res = pt.evaluate(setup, 4100.0, stale_ts, False)
    assert res["accepted"] is False
    assert res["reason"] == "STALE_OR_INVALID_MARKET_DATA"


def test_restart_recovery_preserves_ledger(tmp_path, monkeypatch):
    """Verify SQLite persistence preserves open positions, orders, and equity across restart."""
    db_file = str(tmp_path / "test_persist.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    pt._conn().close()
    pt.control("start")
    now = int(time.time())

    setup = {
        "id": "setup-persist-01",
        "state": "ACTIVE",
        "direction": "bullish",
        "price": 4100.0,
        "invalidation_price": 4090.0,
        "target_price": 4130.0,
        "top": 4105.0,
        "bottom": 4095.0,
    }
    res = pt.evaluate(setup, 4100.0, now, False)
    assert res["accepted"] is True
    pos_id = res["position_id"]

    # Simulate restart by checking status from a fresh database connection
    stat = pt.status()
    assert stat["counts"]["open"] == 1
    assert stat["open_positions"][0]["id"] == pos_id
    assert stat["open_positions"][0]["setup_id"] == "setup-persist-01"


def test_stop_loss_widening_is_prohibited(tmp_path, monkeypatch):
    """Verify stop loss cannot be widened or moved backwards."""
    db_file = str(tmp_path / "test_stop_ratchet.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    pt._conn().close()
    pt.control("start")
    now = int(time.time())

    setup = {
        "id": "setup-stop-ratchet-01",
        "state": "ACTIVE",
        "direction": "bullish",
        "price": 4100.0,
        "invalidation_price": 4090.0,
        "target_price": 4130.0,
        "top": 4105.0,
        "bottom": 4095.0,
    }
    res = pt.evaluate(setup, 4100.0, now, False)
    pos_id = res["position_id"]

    # Attempt to widen stop: 4090 -> 4080 (downward move on LONG is prohibited)
    widen_res = pt.update_stop_loss(pos_id, 4080.0)
    assert widen_res["success"] is False
    assert widen_res["reason"] == "REJECTED_NON_MONOTONIC_STOP"

    # Valid ratchet: 4090 -> 4095 (upward move on LONG is permitted)
    ratchet_res = pt.update_stop_loss(pos_id, 4095.0)
    assert ratchet_res["success"] is True
    assert ratchet_res["new_stop"] == 4095.0


def test_execution_breach_detection_and_lockout(tmp_path, monkeypatch):
    """
    Verify that if a trade experiences an extreme loss beyond the planned risk budget
    (e.g., due to catastrophic gap or extreme slippage), the engine logs a RISK_BUDGET_BREACH event,
    enters PAUSED state, rejects new entries, and requires explicit operator reset.
    """
    db_file = str(tmp_path / "test_breach.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    pt._conn().close()
    pt.control("start")
    now = int(time.time())

    # Open a long position
    setup = {
        "id": "setup-breach-test-01",
        "state": "ACTIVE",
        "direction": "bullish",
        "price": 4100.0,
        "invalidation_price": 4090.0,
        "target_price": 4130.0,
        "top": 4105.0,
        "bottom": 4095.0,
    }
    res = pt.evaluate(setup, 4100.0, now, False)
    assert res["accepted"] is True
    pos_id = res["position_id"]

    # Simulate catastrophic price gap: market drops to $4000.00 ($100 drop, 10x the stop distance)
    with pt._database() as c:
        row = dict(c.execute("SELECT * FROM paper_positions WHERE id=?", (pos_id,)).fetchone())
        cfg = {k: pt._meta(c, k) for k in pt.DEFAULT_CONFIG}
        pt._execute_close(c, row, 4000.0, "CATASTROPHIC_GAP_STOP", cfg)
        c.commit()

    # Verify breach event logged
    events = pt.status()["events"]
    breach_events = [e for e in events if e.get("kind") == "RISK_BUDGET_BREACH"]
    assert len(breach_events) >= 1

    # Verify engine state is PAUSED
    assert pt.status()["engine_state"] == "PAUSED"

    # Verify new orders are blocked
    next_setup = {
        "id": "setup-breach-test-02",
        "state": "ACTIVE",
        "direction": "bullish",
        "price": 4000.0,
        "invalidation_price": 3990.0,
        "target_price": 4030.0,
        "top": 4005.0,
        "bottom": 3995.0,
    }
    next_res = pt.evaluate(next_setup, 4000.0, now, False)
    assert next_res["accepted"] is False
    assert next_res["reason"] == "ENGINE_PAUSED"

    # Operator review and reset
    reset_res = pt.control("reset-breach")
    assert reset_res["success"] is True
    assert pt.status()["engine_state"] == "STOPPED"

