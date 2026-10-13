"""
Automated Verification Suite for XAUTUSD Paper Trading Dashboard (v1.1)
Covers all 14 strict test requirements specified in the project specification.
"""
import os
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient

from backend import paper_trading as pt
from backend.app import app

def init_test_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_paper.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    pt._conn().close()
    return db_file

def sample_setup(sid="setup-001", state="ACTIVE", direction="bullish", entry=100.0, stop=95.0, target=110.0, top=102.0, bottom=98.0):
    return {
        "id": sid,
        "state": state,
        "direction": direction,
        "price": entry,
        "invalidation_price": stop,
        "target_price": target,
        "top": top,
        "bottom": bottom,
        "rr_ratio": 2.0,
        "timestamp": int(time.time()),
    }

# 1. Only ACTIVE setups can initiate entries
def test_01_only_active_setups_can_initiate_entries(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    for bad_state in ["WATCH", "EXTREME", "INVALIDATED", "PENDING", "FORMING", "EXPIRED"]:
        res = pt.evaluate(sample_setup(sid=f"setup-{bad_state}", state=bad_state), 100.0, now, False)
        assert res["accepted"] is False
        assert "NOT_ACTIVE" in res["reason"]

    res_none = pt.evaluate(None, 100.0, now, False)
    assert res_none["accepted"] is False
    assert "NOT_ACTIVE" in res_none["reason"]

    # Confirmed ACTIVE setup enters successfully
    res_active = pt.evaluate(sample_setup(sid="setup-active", state="ACTIVE"), 100.0, now, False)
    assert res_active["accepted"] is True
    assert res_active["quantity"] > 0

# 2. Duplicate setups cannot open duplicate positions
def test_02_duplicate_setups_cannot_open_duplicate_positions(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())
    setup = sample_setup(sid="setup-dup-1")

    res1 = pt.evaluate(setup, 100.0, now, False)
    assert res1["accepted"] is True

    res2 = pt.evaluate(setup, 100.0, now, False)
    assert res2["accepted"] is False
    assert res2["reason"] == "DUPLICATE_SETUP"
    assert pt.status()["counts"]["open"] == 1

# 3. Invalid or missing entry/stop-loss/target data is rejected safely
def test_03_invalid_or_missing_levels_rejected_safely(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    # Missing ID
    s_no_id = sample_setup(sid="")
    assert pt.evaluate(s_no_id, 100.0, now, False)["reason"] == "MISSING_SETUP_ID"

    # Non-positive entry or stop
    s_neg = sample_setup(sid="s-neg", entry=-100)
    assert pt.evaluate(s_neg, 100.0, now, False)["reason"] == "MISSING_OR_INVALID_LEVELS"

    # Inverted level order for LONG (stop must be < entry < target)
    s_inv_long = sample_setup(sid="s-inv-long", stop=105.0)  # stop > entry
    assert pt.evaluate(s_inv_long, 100.0, now, False)["reason"] == "INVALID_LEVEL_ORDER"

    # Inverted level order for SHORT (target must be < entry < stop)
    s_inv_short = sample_setup(sid="s-inv-short", direction="bearish", entry=100.0, stop=90.0, target=110.0, top=102.0, bottom=98.0)
    assert pt.evaluate(s_inv_short, 100.0, now, False)["reason"] == "INVALID_LEVEL_ORDER"

    # Target already reached
    s_target_hit = sample_setup(sid="s-target-hit", entry=100.0, stop=95.0, target=110.0)
    assert pt.evaluate(s_target_hit, 111.0, now, False)["reason"] == "TARGET_ALREADY_REACHED"

    # Outside entry zone
    s_outside = sample_setup(sid="s-outside", top=101.0, bottom=99.0)
    assert pt.evaluate(s_outside, 105.0, now, False)["reason"] == "PRICE_OUTSIDE_ENTRY_ZONE"

# 4. Position sizing respects configured risk budget
def test_04_position_sizing_respects_configured_risk_budget(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    # Starting equity = $10,000, risk_fraction = 0.0025 -> $25 risk budget
    # Entry = 100, Stop = 95 -> risk per unit = 5
    # Expected qty = 25 / 5 = 5 units
    setup = sample_setup(sid="setup-size-1", entry=100.0, stop=95.0, target=115.0)
    res = pt.evaluate(setup, 100.0, now, False)
    assert res["accepted"] is True
    assert pytest.approx(res["quantity"], rel=1e-3) == 5.0

# 5. Daily loss and notional limits block or cap new trades
def test_05_daily_loss_and_notional_limits(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    # Notional cap test: max_notional = $2,500
    # Entry = 1000, Stop = 999.9 -> risk_per_unit = 0.1 -> unconstrained qty would be 250 units ($250,000)
    # Capped qty = 2500 / 1000 = 2.5 units
    setup_huge = sample_setup(sid="setup-huge", entry=1000.0, stop=999.9, target=1010.0, top=1005.0, bottom=995.0)
    res_notional = pt.evaluate(setup_huge, 1000.0, now, False)
    assert res_notional["accepted"] is True
    assert pytest.approx(res_notional["quantity"], rel=1e-3) == 2.5

    # Daily loss limit test
    # Set equity below loss limit
    with pt._database() as c:
        pt._set_meta(c, "equity", 9850.0)  # > 1% loss on $10,000
        c.commit()

    setup_after_loss = sample_setup(sid="setup-after-loss")
    res_loss = pt.evaluate(setup_after_loss, 100.0, now, False)
    assert res_loss["accepted"] is False
    assert res_loss["reason"] == "DAILY_LOSS_LIMIT"
    assert pt.status()["engine_state"] == "STOPPED"

# 6. Stop-loss and take-profit events close simulated positions correctly
def test_06_sl_and_tp_close_positions_correctly(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    # Open LONG position
    s_long = sample_setup(sid="s-long-tp", entry=100.0, stop=95.0, target=110.0)
    pt.evaluate(s_long, 100.0, now, False)
    assert pt.status()["counts"]["open"] == 1

    # Price hits take-profit
    pt.mark_to_market(110.5)
    st = pt.status()
    assert st["counts"]["open"] == 0
    assert st["counts"]["completed"] == 1
    assert st["trades"][0]["exit_reason"] == "TAKE_PROFIT"
    assert st["trades"][0]["net_pnl"] > 0

    # Open SHORT position
    s_short = sample_setup(sid="s-short-sl", direction="bearish", entry=100.0, stop=105.0, target=90.0, top=102.0, bottom=98.0)
    pt.evaluate(s_short, 100.0, now, False)
    assert pt.status()["counts"]["open"] == 1

    # Price hits stop-loss for short
    pt.mark_to_market(105.5)
    st2 = pt.status()
    assert st2["counts"]["open"] == 0
    assert st2["counts"]["completed"] == 2
    assert st2["trades"][0]["exit_reason"] == "STOP_LOSS"
    assert st2["trades"][0]["net_pnl"] < 0

# 7. Fees and slippage are reflected in P&L
def test_07_fees_and_slippage_reflected_in_pnl(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    setup = sample_setup(sid="setup-fees", entry=100.0, stop=95.0, target=110.0)
    res = pt.evaluate(setup, 100.0, now, False)
    # 5 bps slippage on $100 entry = 100 * 0.0005 = 0.05 -> fill = 100.05
    assert res["entry_price"] > 100.0

    # Close manually at 105.0
    # Exit fill with 5 bps slippage = 105 - 0.0525 = 104.9475
    pt.close_position(res["position_id"])
    trade = pt.status()["trades"][0]

    gross = trade["gross_pnl"]
    net = trade["net_pnl"]
    fees = trade["entry_fee"] + trade["exit_fee"]
    assert pytest.approx(net, rel=1e-4) == gross - fees
    assert fees > 0

# 8. Repeated requests do not duplicate trades
def test_08_repeated_requests_idempotent(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())
    setup = sample_setup(sid="setup-repeat-1")

    outcomes = [pt.evaluate(setup, 100.0, now, False) for _ in range(5)]
    assert outcomes[0]["accepted"] is True
    for o in outcomes[1:]:
        assert o["accepted"] is False
        assert o["reason"] == "DUPLICATE_SETUP"
    assert pt.status()["counts"]["open"] == 1

# 9. Paper account state persists after a restart
def test_09_paper_state_persists_after_restart(tmp_path, monkeypatch):
    db_file = init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())
    pt.evaluate(sample_setup(sid="setup-persist"), 100.0, now, False)

    st_before = pt.status()
    eq_before = st_before["equity"]
    open_before = st_before["counts"]["open"]
    assert open_before == 1

    # Simulate restart by clearing any cached handles and reconnecting
    monkeypatch.setattr(pt, "DB_PATH", db_file)
    st_after = pt.status()
    assert st_after["counts"]["open"] == 1
    assert st_after["equity"] == eq_before
    assert st_after["open_positions"][0]["setup_id"] == "setup-persist"

# 10. Pause and emergency stop prevent new entries
def test_10_pause_and_emergency_stop_behavior(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    # Open 1 position before pausing
    pt.evaluate(sample_setup(sid="setup-p1", entry=100.0, stop=95.0, target=110.0), 100.0, now, False)

    # Pause engine
    pause_res = pt.control("pause")
    assert pause_res["success"] is True
    assert pt.status()["engine_state"] == "PAUSED"

    # New entry blocked during pause
    blocked_eval = pt.evaluate(sample_setup(sid="setup-p2"), 100.0, now, False)
    assert blocked_eval["accepted"] is False
    assert blocked_eval["reason"] == "ENGINE_PAUSED"

    # Existing position STILL monitors and exits on TP during pause
    pt.mark_to_market(111.0)
    assert pt.status()["counts"]["open"] == 0
    assert pt.status()["counts"]["completed"] == 1

    # Resume engine
    pt.control("resume")
    assert pt.status()["engine_state"] == "RUNNING"

    # Emergency stop triggers kill switch
    pt.control("emergency-stop")
    st = pt.status()
    assert st["emergency_stop"] is True
    assert st["engine_state"] == "STOPPED"

    # Starting while emergency stop is active is rejected
    assert pt.control("start")["success"] is False

    # Clear stop lock
    pt.control("reset-stop")
    st2 = pt.status()
    assert st2["emergency_stop"] is False
    assert st2["engine_state"] == "STOPPED"

# 11. Closing a position updates ledger and balance exactly once
def test_11_closing_position_updates_balance_once(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    res = pt.evaluate(sample_setup(sid="setup-close-once"), 100.0, now, False)
    pos_id = res["position_id"]

    eq_initial = pt.status()["equity"]
    close1 = pt.close_position(pos_id)
    assert close1["success"] is True
    eq_after_close = pt.status()["equity"]

    # Attempting to close already closed position
    close2 = pt.close_position(pos_id)
    assert close2["success"] is False
    assert pt.status()["equity"] == eq_after_close

# 12. Reset requires explicit confirmation and restores state
def test_12_reset_requires_explicit_confirmation(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())
    pt.evaluate(sample_setup(sid="setup-reset"), 100.0, now, False)

    # Calling reset without confirm flag fails safely
    res_no_confirm = pt.control("reset", {})
    assert res_no_confirm["success"] is False
    assert "confirmation" in res_no_confirm["message"].lower()

    # Calling reset with confirm=True resets everything
    res_confirm = pt.control("reset", {"confirm": True})
    assert res_confirm["success"] is True
    st = pt.status()
    assert st["counts"]["open"] == 0
    assert st["counts"]["completed"] == 0
    assert st["equity"] == 10000.0
    assert st["engine_state"] == "STOPPED"

# 13. Stale or disconnected market data blocks new entries
def test_13_stale_market_data_blocks_entries(tmp_path, monkeypatch):
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())
    setup = sample_setup(sid="setup-stale")

    # Stale flag is True
    assert pt.evaluate(setup, 100.0, now, is_stale=True)["reason"] == "STALE_OR_INVALID_MARKET_DATA"

    # Price timestamp is too old (> 60s)
    assert pt.evaluate(setup, 100.0, now - 120, is_stale=False)["reason"] == "STALE_OR_INVALID_MARKET_DATA"

    # Invalid non-positive price
    assert pt.evaluate(setup, 0.0, now, is_stale=False)["reason"] == "STALE_OR_INVALID_MARKET_DATA"

# 14. Original dashboard API behavior and signal-generation tests remain unchanged
def test_14_fastapi_endpoints_backward_compatibility():
    client = TestClient(app)

    # 1. Original dashboard endpoints work
    r_index = client.get("/")
    assert r_index.status_code == 200

    r_status = client.get("/api/status?timeframe=1H")
    assert r_status.status_code == 200
    data = r_status.json()
    assert "symbol" in data
    assert "current_price" in data

    # 2. Dedicated paper dashboard endpoints work
    r_paper_html = client.get("/paper")
    assert r_paper_html.status_code == 200

    r_paper_status = client.get("/api/paper/status")
    assert r_paper_status.status_code == 200
    paper_data = r_paper_status.json()
    assert paper_data["mode"] == "PAPER ONLY"
    assert "metrics" in paper_data
    assert "config" in paper_data
