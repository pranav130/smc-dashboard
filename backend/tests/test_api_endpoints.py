import pytest
import time
from fastapi.testclient import TestClient
from backend.app import app
from backend import paper_trading as pt
from backend.risk.rejection_inspector import global_rejection_inspector

client = TestClient(app)


def test_api_paper_rejections():
    """Verify /api/paper/rejections returns structured telemetry."""
    # Seed a rejection
    global_rejection_inspector.record_rejection(
        model="MODEL_A",
        stage_failed="NO_QUALIFYING_SWEEP",
        reasons=["No recent sweep"],
        evaluated_price=4100.0,
        setup_id="test-rej-1"
    )

    resp = client.get("/api/paper/rejections")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["rejections"]) >= 1
    assert data["rejections"][0]["model"] == "MODEL_A"

    resp_summary = client.get("/api/paper/rejections/summary")
    assert resp_summary.status_code == 200
    sum_data = resp_summary.json()
    assert sum_data["success"] is True
    assert "by_stage" in sum_data["summary"]


def test_api_trade_replay(tmp_path, monkeypatch):
    """Verify /api/paper/trade_replay/{pos_id} reconstructs forensic timeline."""
    test_db = str(tmp_path / "api_test_db.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", test_db)
    pt.control("start")
    now = int(time.time())

    setup = {
        "id": "replay-setup-1",
        "name": "Model A Replay",
        "direction": "bullish",
        "timeframe": "1H",
        "state": "ACTIVE",
        "price": 4100.0,
        "top": 4102.0,
        "bottom": 4098.0,
        "invalidation_price": 4090.0,
        "target_price": 4150.0,
        "score": 90,
    }
    res = pt.evaluate(setup, 4100.0, now, False)
    assert res["accepted"] is True
    pos_id = res["position_id"]

    # Close position
    pt.close_position(pos_id)

    # Replay endpoint
    resp = client.get(f"/api/paper/trade_replay/{pos_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["position"]["id"] == pos_id
    assert len(data["timeline"]) >= 2
    assert "metrics" in data


def test_api_update_stop(tmp_path, monkeypatch):
    """Verify /api/paper/positions/{pos_id}/update_stop validates monotonicity."""
    test_db = str(tmp_path / "api_test_stop.sqlite3")
    monkeypatch.setattr(pt, "DB_PATH", test_db)
    pt.control("start")
    now = int(time.time())

    setup = {
        "id": "stop-setup-1",
        "name": "Stop Update Test",
        "direction": "bullish",
        "timeframe": "1H",
        "state": "ACTIVE",
        "price": 4100.0,
        "top": 4102.0,
        "bottom": 4098.0,
        "invalidation_price": 4090.0,
        "target_price": 4150.0,
        "score": 90,
    }
    res = pt.evaluate(setup, 4100.0, now, False)
    pos_id = res["position_id"]

    # Attempt to widen stop to 4080 -> False
    resp_widen = client.post(f"/api/paper/positions/{pos_id}/update_stop", json={"new_stop": 4080.0})
    assert resp_widen.status_code == 200
    assert resp_widen.json()["success"] is False
    assert resp_widen.json()["reason"] == "REJECTED_NON_MONOTONIC_STOP"

    # Move stop up to 4095 -> True
    resp_up = client.post(f"/api/paper/positions/{pos_id}/update_stop", json={"new_stop": 4095.0})
    assert resp_up.status_code == 200
    assert resp_up.json()["success"] is True


def test_api_frontend_and_workstation_routes():
    """Verify frontend static/HTML routes serve the index, paper dashboard, and workstation V2."""
    resp_index = client.get("/")
    assert resp_index.status_code == 200
    assert "btnOpenV2" in resp_index.text
    assert "V2 Workstation" in resp_index.text

    resp_paper = client.get("/paper")
    assert resp_paper.status_code == 200

    resp_v2 = client.get("/v2")
    assert resp_v2.status_code == 200
    assert "SMC Workstation" in resp_v2.text

    resp_ws = client.get("/workstation")
    assert resp_ws.status_code == 200
    assert "SMC Workstation" in resp_ws.text

    resp_static_v2 = client.get("/static/smc-workstation-v2.html")
    assert resp_static_v2.status_code == 200
    assert "SMC Workstation" in resp_static_v2.text

