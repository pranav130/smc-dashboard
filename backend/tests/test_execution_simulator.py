import pytest
import time
from backend import paper_trading as pt


def init_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "paper_test_exec.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", test_db)
    with pt._database() as c:
        pass
    return test_db


def sample_setup(sid="exec-test", direction="bullish", entry=4100.0, stop=4090.0, target=4130.0, top=4102.0, bottom=4098.0):
    return {
        "id": sid,
        "name": "Model A Test",
        "direction": direction,
        "timeframe": "1H",
        "state": "ACTIVE",
        "price": entry,
        "top": top,
        "bottom": bottom,
        "invalidation_price": stop,
        "target_price": target,
        "score": 90,
    }


def test_monotonic_stop_loss_enforcement(tmp_path, monkeypatch):
    """Verify protective stops can only be tightened towards profit, never widened."""
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    # Open LONG at 4100 with stop at 4090
    s_long = sample_setup(sid="mono-long", entry=4100.0, stop=4090.0, target=4150.0)
    res = pt.evaluate(s_long, 4100.0, now, False)
    assert res["accepted"] is True
    pos_id = res["position_id"]

    # 1. Attempt to widen stop to 4085 -> REJECTED
    res_widen = pt.update_stop_loss(pos_id, 4085.0)
    assert res_widen["success"] is False
    assert res_widen["reason"] == "REJECTED_NON_MONOTONIC_STOP"

    # Verify event logged
    events = pt.get_events()
    assert any(e["kind"] == "RISK_VIOLATION" for e in events)

    # 2. Tighten stop to 4095 -> ACCEPTED
    res_tighten = pt.update_stop_loss(pos_id, 4095.0)
    assert res_tighten["success"] is True
    assert res_tighten["new_stop"] == 4095.0


def test_conservative_candle_tie_breaker(tmp_path, monkeypatch):
    """Verify when both stop and target touched in same bar, STOP LOSS executes."""
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    s_long = sample_setup(sid="tie-breaker-pos", entry=4100.0, stop=4090.0, target=4150.0)
    pt.evaluate(s_long, 4100.0, now, False)
    assert pt.status()["counts"]["open"] == 1

    # Candle with extreme volatility: Low = 4085 (hits stop), High = 4160 (hits target)
    pt.mark_to_market(price=4120.0, high=4160.0, low=4085.0)

    st = pt.status()
    assert st["counts"]["open"] == 0
    assert st["counts"]["completed"] == 1
    # Conservative tie-breaker must record STOP_LOSS, not take profit!
    assert st["trades"][0]["exit_reason"] == "STOP_LOSS"
    assert st["trades"][0]["net_pnl"] < 0


def test_breakeven_milestone_trigger(tmp_path, monkeypatch):
    """Verify stop loss moves to break-even once 1R milestone is reached."""
    init_test_db(tmp_path, monkeypatch)
    pt.control("start")
    now = int(time.time())

    # Long: Entry 4100, Stop 4090 -> 1R distance is $10 -> milestone is 4110.0
    s_long = sample_setup(sid="be-pos", entry=4100.0, stop=4090.0, target=4150.0)
    res = pt.evaluate(s_long, 4100.0, now, False)
    pos_id = res["position_id"]

    # Price moves to 4120 with low remaining at 4105 (above new BE stop 4102.15)
    pt.mark_to_market(price=4120.0, high=4120.0, low=4105.0)

    positions = pt.get_positions(status_filter="OPEN")
    assert len(positions) == 1
    pos = positions[0]
    # Stop should now be advanced to at least entry (4100.10)
    assert pos["stop_loss"] >= 4100.0
    assert pos["breakeven_triggered"] == 1
    assert pos["mfe"] >= 12.0
