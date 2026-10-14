"""
Isolated Paper Trading Engine & Ledger for XAUTUSD.
Safety Guarantee: Absolutely NO Delta Exchange private credentials or order-placement calls exist in this module.
"""
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from backend.risk.manager import RiskManager

DB_PATH = os.getenv("PAPER_DB_PATH", str(Path(__file__).resolve().parent.parent / "paper_trading.sqlite3"))
LOCK = threading.RLock()
global_risk_manager = RiskManager()

DEFAULT_CONFIG: Dict[str, Any] = {
    "starting_equity": 10000.0,
    "risk_fraction": 0.0025,         # 0.25% risk per trade
    "daily_loss_fraction": 0.01,     # 1% daily loss limit
    "max_positions": 1,              # 1 concurrent position
    "max_data_age_seconds": 60,      # 60s stale data threshold
    "max_notional": 2500.0,          # $2,500 maximum notional cap
    "fee_rate": 0.0005,              # 0.05% taker fee
    "slippage_bps": 5.0,             # 5 basis points simulated slippage
}

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS paper_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS paper_events (
        id TEXT PRIMARY KEY,
        ts REAL NOT NULL,
        kind TEXT NOT NULL,
        setup_id TEXT,
        position_id TEXT,
        detail TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS paper_positions (
        id TEXT PRIMARY KEY,
        setup_id TEXT NOT NULL,
        direction TEXT NOT NULL,
        status TEXT NOT NULL,
        entry_price REAL NOT NULL,
        current_price REAL NOT NULL,
        quantity REAL NOT NULL,
        notional REAL NOT NULL,
        stop_loss REAL NOT NULL,
        take_profit REAL NOT NULL,
        entry_fee REAL NOT NULL,
        exit_price REAL,
        exit_fee REAL,
        gross_pnl REAL,
        net_pnl REAL,
        exit_reason TEXT,
        created_at REAL NOT NULL,
        closed_at REAL,
        signal_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS paper_orders (
        id TEXT PRIMARY KEY,
        position_id TEXT,
        setup_id TEXT NOT NULL,
        side TEXT NOT NULL,
        order_type TEXT NOT NULL,
        requested_price REAL NOT NULL,
        fill_price REAL NOT NULL,
        quantity REAL NOT NULL,
        status TEXT NOT NULL,
        rejection_reason TEXT,
        fee REAL NOT NULL DEFAULT 0.0,
        created_at REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_paper_positions_setup ON paper_positions(setup_id);
    CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status);
    CREATE INDEX IF NOT EXISTS idx_paper_orders_setup ON paper_orders(setup_id);
    CREATE INDEX IF NOT EXISTS idx_paper_events_ts ON paper_events(ts);
    """)

    # Dynamic column migrations for Section 7 & 8 metrics
    existing_cols = {r[1] for r in c.execute("PRAGMA table_info(paper_positions)").fetchall()}
    for col, col_type in [
        ("mfe", "REAL DEFAULT 0.0"),
        ("mae", "REAL DEFAULT 0.0"),
        ("highest_price", "REAL DEFAULT 0.0"),
        ("lowest_price", "REAL DEFAULT 0.0"),
        ("initial_stop", "REAL DEFAULT 0.0"),
        ("breakeven_triggered", "INTEGER DEFAULT 0"),
        ("trailing_stop_active", "INTEGER DEFAULT 0"),
    ]:
        if col not in existing_cols:
            try:
                c.execute(f"ALTER TABLE paper_positions ADD COLUMN {col} {col_type}")
            except Exception:
                pass

    # Seed configuration and metadata defaults
    for k, v in DEFAULT_CONFIG.items():
        c.execute("INSERT OR IGNORE INTO paper_meta(key, value) VALUES(?, ?)", (k, json.dumps(v)))

    now_day = time.strftime("%Y-%m-%d", time.gmtime())
    starting_eq = DEFAULT_CONFIG["starting_equity"]
    defaults_meta = {
        "engine_state": "STOPPED",    # STOPPED, RUNNING, PAUSED
        "emergency_stop": False,
        "equity": starting_eq,
        "peak_equity": starting_eq,
        "day_start_equity": starting_eq,
        "day_key": now_day,
        "last_price": 0.0,
        "last_price_ts": 0,
        "is_stale": False,
    }
    for k, v in defaults_meta.items():
        c.execute("INSERT OR IGNORE INTO paper_meta(key, value) VALUES(?, ?)", (k, json.dumps(v)))
    c.commit()
    return c

@contextmanager
def _database():
    c = _conn()
    try:
        yield c
    finally:
        c.close()

def _meta(c: sqlite3.Connection, key: str) -> Any:
    r = c.execute("SELECT value FROM paper_meta WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else None

def _set_meta(c: sqlite3.Connection, key: str, value: Any) -> None:
    c.execute(
        "INSERT INTO paper_meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )

def _log_event(
    c: sqlite3.Connection,
    kind: str,
    setup_id: Optional[str] = None,
    position_id: Optional[str] = None,
    detail: Any = None,
) -> None:
    c.execute(
        "INSERT INTO paper_events VALUES(?, ?, ?, ?, ?, ?)",
        (
            uuid.uuid4().hex,
            time.time(),
            kind,
            setup_id,
            position_id,
            json.dumps(detail or {}, default=str),
        ),
    )

def get_config() -> Dict[str, Any]:
    with LOCK, _database() as c:
        return {k: _meta(c, k) for k in DEFAULT_CONFIG}

def update_config(new_cfg: Dict[str, Any]) -> Dict[str, Any]:
    with LOCK, _database() as c:
        for k, v in new_cfg.items():
            if k not in DEFAULT_CONFIG:
                continue
            val = float(v)
            if k == "max_positions":
                val = max(1, int(val))
            elif k in ("risk_fraction", "daily_loss_fraction", "fee_rate", "slippage_bps", "starting_equity", "max_notional", "max_data_age_seconds"):
                if val <= 0:
                    raise ValueError(f"{k} must be positive")
            _set_meta(c, k, val)
        c.commit()
        _log_event(c, "CONFIG_UPDATED", detail=new_cfg)
        return get_config()

def _check_day_rollover(c: sqlite3.Connection) -> None:
    now_day = time.strftime("%Y-%m-%d", time.gmtime())
    current_day_key = _meta(c, "day_key")
    if current_day_key != now_day:
        current_eq = _meta(c, "equity")
        _set_meta(c, "day_key", now_day)
        _set_meta(c, "day_start_equity", current_eq)
        _log_event(c, "DAY_ROLLOVER", detail={"prev_day": current_day_key, "new_day": now_day, "start_equity": current_eq})

def _compute_metrics(c: sqlite3.Connection, last_price: float) -> Dict[str, Any]:
    cfg = {k: _meta(c, k) for k in DEFAULT_CONFIG}
    realized_eq = float(_meta(c, "equity") or cfg["starting_equity"])
    peak_eq = float(_meta(c, "peak_equity") or realized_eq)
    day_start_eq = float(_meta(c, "day_start_equity") or realized_eq)

    open_pos_rows = c.execute("SELECT * FROM paper_positions WHERE status='OPEN'").fetchall()
    open_positions = []
    total_unrealized_pnl = 0.0
    total_open_notional = 0.0

    fee_rate = cfg["fee_rate"]

    for row in open_pos_rows:
        pos = dict(row)
        direction = pos["direction"]
        qty = pos["quantity"]
        entry = pos["entry_price"]
        entry_fee = pos["entry_fee"]
        mark_price = last_price if (last_price and last_price > 0) else entry
        pos_notional = mark_price * qty
        total_open_notional += pos_notional

        # Mark-to-market unrealized P&L
        est_exit_fee = pos_notional * fee_rate
        if direction == "LONG":
            gross = (mark_price - entry) * qty
        else:
            gross = (entry - mark_price) * qty
        u_pnl = gross - entry_fee - est_exit_fee

        pos["current_price"] = round(mark_price, 4)
        pos["notional"] = round(pos_notional, 2)
        pos["unrealized_pnl"] = round(u_pnl, 4)
        pos["unrealized_pnl_pct"] = round((u_pnl / (entry * qty) * 100), 2) if (entry * qty) > 0 else 0.0
        open_positions.append(pos)
        total_unrealized_pnl += u_pnl

    current_equity = realized_eq + total_unrealized_pnl
    if current_equity > peak_eq:
        peak_eq = current_equity
        _set_meta(c, "peak_equity", peak_eq)

    available_balance = max(0.0, realized_eq - total_open_notional)
    daily_pnl = current_equity - day_start_eq
    daily_pnl_pct = (daily_pnl / day_start_eq * 100) if day_start_eq > 0 else 0.0

    closed_pos_rows = c.execute("SELECT * FROM paper_positions WHERE status='CLOSED'").fetchall()
    total_completed_trades = len(closed_pos_rows)
    total_realized_pnl = sum(float(r["net_pnl"] or 0) for r in closed_pos_rows)

    winning_trades = [r for r in closed_pos_rows if float(r["net_pnl"] or 0) > 0]
    win_rate = round((len(winning_trades) / total_completed_trades * 100), 1) if total_completed_trades > 0 else 0.0

    gross_profits = sum(float(r["gross_pnl"] or 0) for r in closed_pos_rows if float(r["gross_pnl"] or 0) > 0)
    gross_losses = abs(sum(float(r["gross_pnl"] or 0) for r in closed_pos_rows if float(r["gross_pnl"] or 0) < 0))
    if gross_losses > 0:
        profit_factor = round(gross_profits / gross_losses, 2)
    elif gross_profits > 0:
        profit_factor = "∞"
    else:
        profit_factor = "—"

    max_dd_amount = max(0.0, peak_eq - current_equity)
    max_dd_pct = round((max_dd_amount / peak_eq * 100), 2) if peak_eq > 0 else 0.0

    return {
        "starting_equity": cfg["starting_equity"],
        "realized_equity": round(realized_eq, 4),
        "current_equity": round(current_equity, 4),
        "available_balance": round(available_balance, 4),
        "unrealized_pnl": round(total_unrealized_pnl, 4),
        "realized_pnl": round(total_realized_pnl, 4),
        "daily_pnl": round(daily_pnl, 4),
        "daily_pnl_pct": round(daily_pnl_pct, 2),
        "open_positions_count": len(open_positions),
        "completed_trades_count": total_completed_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_amount": round(max_dd_amount, 2),
        "max_drawdown_pct": max_dd_pct,
        "open_positions": open_positions,
    }

def status() -> Dict[str, Any]:
    with LOCK, _database() as c:
        _check_day_rollover(c)
        last_price = float(_meta(c, "last_price") or 0.0)
        last_price_ts = int(_meta(c, "last_price_ts") or 0)
        is_stale = bool(_meta(c, "is_stale"))
        engine_state = str(_meta(c, "engine_state") or "STOPPED")
        emergency_stop = bool(_meta(c, "emergency_stop"))

        metrics = _compute_metrics(c, last_price)
        cfg = {k: _meta(c, k) for k in DEFAULT_CONFIG}

        orders = [dict(r) for r in c.execute("SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT 150").fetchall()]
        trades = [dict(r) for r in c.execute("SELECT * FROM paper_positions WHERE status='CLOSED' ORDER BY closed_at DESC LIMIT 150").fetchall()]
        events = [dict(r) for r in c.execute("SELECT * FROM paper_events ORDER BY ts DESC LIMIT 150").fetchall()]

        for e in events:
            try:
                e["detail"] = json.loads(e["detail"])
            except Exception:
                pass

        now = time.time()
        market_data_fresh = (last_price > 0) and not is_stale and (now - last_price_ts <= cfg["max_data_age_seconds"])

        return {
            "mode": "PAPER ONLY",
            "engine_state": engine_state,
            "enabled": engine_state == "RUNNING",
            "is_paused": engine_state == "PAUSED",
            "emergency_stop": emergency_stop,
            "market_data": {
                "last_price": last_price,
                "last_price_ts": last_price_ts,
                "is_stale": is_stale or not market_data_fresh,
                "status": "LIVE" if market_data_fresh else ("STALE" if last_price > 0 else "DISCONNECTED"),
            },
            "config": cfg,
            "metrics": metrics,
            "equity": metrics["current_equity"],
            "realized_pnl": metrics["realized_pnl"],
            "unrealized_pnl": metrics["unrealized_pnl"],
            "open_positions": metrics["open_positions"],
            "orders": orders,
            "trades": trades,
            "events": events,
            "counts": {
                "open": metrics["open_positions_count"],
                "completed": metrics["completed_trades_count"],
                "orders": len(orders),
                "events": len(events),
            },
            "risk_manager": global_risk_manager.get_status(now),
        }

def control(action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with LOCK, _database() as c:
        _check_day_rollover(c)
        action = action.lower()

        if action == "start":
            if _meta(c, "emergency_stop"):
                return {"success": False, "message": "Emergency stop is active; reset it explicitly first."}
            _set_meta(c, "engine_state", "RUNNING")
            _log_event(c, "ENGINE_STARTED", detail={"mode": "paper"})

        elif action == "pause":
            curr = _meta(c, "engine_state")
            if curr != "RUNNING":
                return {"success": False, "message": f"Cannot pause engine from state: {curr}"}
            _set_meta(c, "engine_state", "PAUSED")
            _log_event(c, "ENGINE_PAUSED", detail={"note": "Existing positions will still monitor SL/TP; new entries blocked"})

        elif action == "resume":
            if _meta(c, "emergency_stop"):
                return {"success": False, "message": "Emergency stop is active; reset it explicitly first."}
            _set_meta(c, "engine_state", "RUNNING")
            _log_event(c, "ENGINE_RESUMED", detail={"mode": "paper"})

        elif action == "stop":
            _set_meta(c, "engine_state", "STOPPED")
            _log_event(c, "ENGINE_STOPPED", detail={"reason": "manual stop"})

        elif action == "emergency-stop":
            _set_meta(c, "engine_state", "STOPPED")
            _set_meta(c, "emergency_stop", True)
            _log_event(c, "EMERGENCY_STOP", detail={"reason": "manual emergency stop"})

        elif action == "reset-stop":
            _set_meta(c, "emergency_stop", False)
            _set_meta(c, "engine_state", "STOPPED")
            _log_event(c, "STOP_RESET", detail={"note": "Emergency stop cleared. Engine remains STOPPED until manually started."})

        elif action == "close-all":
            last_price = float(_meta(c, "last_price") or 0.0)
            if last_price <= 0:
                return {"success": False, "message": "No valid latest market price; cannot execute simulated close."}
            open_rows = c.execute("SELECT * FROM paper_positions WHERE status='OPEN'").fetchall()
            closed_count = 0
            cfg = {k: _meta(c, k) for k in DEFAULT_CONFIG}
            for row in open_rows:
                _execute_close(c, dict(row), last_price, "MANUAL_CLOSE_ALL", cfg)
                closed_count += 1
            _log_event(c, "POSITIONS_CLOSED_ALL", detail={"count": closed_count, "price": last_price})

        elif action == "reset":
            # Safety confirmation requirement
            confirm = payload.get("confirm", False) if payload else False
            if not confirm:
                return {"success": False, "message": "Account reset requires explicit confirmation (confirm=True)."}

            cfg = {k: _meta(c, k) for k in DEFAULT_CONFIG}
            st_eq = cfg["starting_equity"]
            now_day = time.strftime("%Y-%m-%d", time.gmtime())

            c.execute("DELETE FROM paper_positions")
            c.execute("DELETE FROM paper_orders")
            c.execute("DELETE FROM paper_events")

            _set_meta(c, "engine_state", "STOPPED")
            _set_meta(c, "emergency_stop", False)
            _set_meta(c, "equity", st_eq)
            _set_meta(c, "peak_equity", st_eq)
            _set_meta(c, "day_start_equity", st_eq)
            _set_meta(c, "day_key", now_day)

            _log_event(c, "ACCOUNT_RESET", detail={"restored_equity": st_eq})
            c.commit()
            return {"success": True, "message": "Paper account reset successfully.", "status": status()}

        else:
            return {"success": False, "message": f"Unknown action: {action}"}

        c.commit()
        return {"success": True, "message": action, "status": status()}

def close_position(position_id: str) -> Dict[str, Any]:
    with LOCK, _database() as c:
        last_price = float(_meta(c, "last_price") or 0.0)
        if last_price <= 0:
            return {"success": False, "message": "No valid latest market price; cannot close position."}
        row = c.execute("SELECT * FROM paper_positions WHERE id=? AND status='OPEN'", (position_id,)).fetchone()
        if not row:
            return {"success": False, "message": "Open position not found or already closed."}
        cfg = {k: _meta(c, k) for k in DEFAULT_CONFIG}
        _execute_close(c, dict(row), last_price, "MANUAL_CLOSE", cfg)
        c.commit()
        return {"success": True, "message": "Position closed successfully.", "status": status()}

def _execute_close(
    c: sqlite3.Connection,
    pos: Dict[str, Any],
    price: float,
    reason: str,
    cfg: Dict[str, Any],
) -> None:
    direction = pos["direction"]
    qty = pos["quantity"]
    entry = pos["entry_price"]
    entry_fee = pos["entry_fee"]

    # Conservative slippage calculation on simulated exit
    slip = price * (cfg["slippage_bps"] / 10000.0)
    fill_price = (price - slip) if direction == "LONG" else (price + slip)
    exit_fee = fill_price * qty * cfg["fee_rate"]

    if direction == "LONG":
        gross_pnl = (fill_price - entry) * qty
    else:
        gross_pnl = (entry - fill_price) * qty

    net_pnl = gross_pnl - entry_fee - exit_fee
    now = time.time()

    # Update position record
    c.execute(
        """
        UPDATE paper_positions
        SET status='CLOSED', exit_price=?, exit_fee=?, gross_pnl=?, net_pnl=?, exit_reason=?, closed_at=?
        WHERE id=? AND status='OPEN'
        """,
        (fill_price, exit_fee, gross_pnl, net_pnl, reason, now, pos["id"]),
    )

    # Record closing order
    close_side = "SELL" if direction == "LONG" else "BUY"
    c.execute(
        """
        INSERT INTO paper_orders(id, position_id, setup_id, side, order_type, requested_price, fill_price, quantity, status, fee, created_at)
        VALUES(?, ?, ?, ?, 'MARKET', ?, ?, ?, 'FILLED', ?, ?)
        """,
        (uuid.uuid4().hex, pos["id"], pos["setup_id"], close_side, price, fill_price, qty, exit_fee, now),
    )

    # Update equity
    current_eq = float(_meta(c, "equity") or cfg["starting_equity"])
    new_eq = round(current_eq + net_pnl, 4)
    _set_meta(c, "equity", new_eq)

    _log_event(
        c,
        "POSITION_CLOSED",
        setup_id=pos["setup_id"],
        position_id=pos["id"],
        detail={
            "fill_price": fill_price,
            "exit_fee": exit_fee,
            "gross_pnl": round(gross_pnl, 4),
            "net_pnl": round(net_pnl, 4),
            "reason": reason,
            "new_equity": new_eq,
        },
    )
    global_risk_manager.update_equity(new_eq, now)
    global_risk_manager.discipline.record_trade_result(net_pnl, now)

def evaluate(setup: Optional[Dict[str, Any]], price: float, price_ts: int, is_stale: bool) -> Dict[str, Any]:
    now = time.time()
    with LOCK, _database() as c:
        _check_day_rollover(c)
        _set_meta(c, "last_price", float(price or 0.0))
        _set_meta(c, "last_price_ts", int(price_ts or 0))
        _set_meta(c, "is_stale", bool(is_stale))

        engine_state = _meta(c, "engine_state")
        emergency_stop = _meta(c, "emergency_stop")

        if emergency_stop:
            c.commit()
            return {"accepted": False, "reason": "EMERGENCY_STOP_ACTIVE"}

        if engine_state == "PAUSED":
            c.commit()
            return {"accepted": False, "reason": "ENGINE_PAUSED"}

        if engine_state != "RUNNING":
            c.commit()
            return {"accepted": False, "reason": "ENGINE_STOPPED"}

        cfg = {k: _meta(c, k) for k in DEFAULT_CONFIG}

        # Market data staleness verification
        if not price or price <= 0 or is_stale or (now - int(price_ts or 0) > cfg["max_data_age_seconds"]):
            _log_event(c, "SIGNAL_REJECTED", detail={"reason": "STALE_OR_INVALID_MARKET_DATA", "price": price, "age": now - int(price_ts or 0)})
            c.commit()
            return {"accepted": False, "reason": "STALE_OR_INVALID_MARKET_DATA"}

        # Signal state verification: only confirmed ACTIVE setups are eligible
        if not setup or setup.get("state") != "ACTIVE":
            st = setup.get("state") if setup else "NONE"
            c.commit()
            return {"accepted": False, "reason": f"NOT_ACTIVE (state={st})"}

        sid = str(setup.get("id") or "").strip()
        if not sid:
            _log_event(c, "SIGNAL_REJECTED", detail={"reason": "MISSING_SETUP_ID"})
            c.commit()
            return {"accepted": False, "reason": "MISSING_SETUP_ID"}

        # Duplicate check across open and historical positions
        existing = c.execute("SELECT 1 FROM paper_positions WHERE setup_id=?", (sid,)).fetchone()
        if existing:
            c.commit()
            return {"accepted": False, "reason": "DUPLICATE_SETUP"}

        # Direction verification
        direction_raw = str(setup.get("direction", "")).upper()
        if direction_raw in ("BULLISH", "LONG"):
            direction = "LONG"
        elif direction_raw in ("BEARISH", "SHORT"):
            direction = "SHORT"
        else:
            _log_event(c, "SIGNAL_REJECTED", setup_id=sid, detail={"reason": "INVALID_DIRECTION", "raw": direction_raw})
            c.commit()
            return {"accepted": False, "reason": "INVALID_DIRECTION"}

        # Price levels extraction & validation
        try:
            entry = float(setup.get("price") or 0.0)
            stop = float(setup.get("invalidation_price") or 0.0)
            target = float(setup.get("target_price") or 0.0)
            top = float(setup.get("top") or 0.0)
            bottom = float(setup.get("bottom") or 0.0)
        except (ValueError, TypeError):
            _log_event(c, "SIGNAL_REJECTED", setup_id=sid, detail={"reason": "MALFORMED_PRICE_LEVELS"})
            c.commit()
            return {"accepted": False, "reason": "MISSING_OR_INVALID_LEVELS"}

        if entry <= 0 or stop <= 0 or target <= 0 or top <= 0 or bottom <= 0 or top < bottom:
            _log_event(c, "SIGNAL_REJECTED", setup_id=sid, detail={"reason": "MISSING_OR_INVALID_LEVELS", "levels": {"entry": entry, "stop": stop, "target": target, "top": top, "bottom": bottom}})
            c.commit()
            return {"accepted": False, "reason": "MISSING_OR_INVALID_LEVELS"}

        # Strict level order check
        if direction == "LONG" and not (stop < entry < target):
            _log_event(c, "SIGNAL_REJECTED", setup_id=sid, detail={"reason": "INVALID_LEVEL_ORDER", "long_req": "stop < entry < target", "levels": [stop, entry, target]})
            c.commit()
            return {"accepted": False, "reason": "INVALID_LEVEL_ORDER"}
        elif direction == "SHORT" and not (target < entry < stop):
            _log_event(c, "SIGNAL_REJECTED", setup_id=sid, detail={"reason": "INVALID_LEVEL_ORDER", "short_req": "target < entry < stop", "levels": [target, entry, stop]})
            c.commit()
            return {"accepted": False, "reason": "INVALID_LEVEL_ORDER"}

        # Daily loss limit check
        equity = float(_meta(c, "equity") or cfg["starting_equity"])
        day_start_equity = float(_meta(c, "day_start_equity") or equity)
        max_daily_loss = day_start_equity * cfg["daily_loss_fraction"]
        if equity <= (day_start_equity - max_daily_loss):
            _set_meta(c, "engine_state", "STOPPED")
            _log_event(c, "RISK_STOP", setup_id=sid, detail={"reason": "DAILY_LOSS_LIMIT", "equity": equity, "day_start": day_start_equity, "loss_limit": max_daily_loss})
            c.commit()
            return {"accepted": False, "reason": "DAILY_LOSS_LIMIT"}

        # Target already reached check
        if (direction == "LONG" and price >= target) or (direction == "SHORT" and price <= target):
            _log_event(c, "SIGNAL_REJECTED", setup_id=sid, detail={"reason": "TARGET_ALREADY_REACHED", "price": price, "target": target})
            c.commit()
            return {"accepted": False, "reason": "TARGET_ALREADY_REACHED"}

        # Entry zone adherence check
        if not (bottom <= price <= top):
            _log_event(c, "SIGNAL_REJECTED", setup_id=sid, detail={"reason": "PRICE_OUTSIDE_ENTRY_ZONE", "price": price, "bottom": bottom, "top": top})
            c.commit()
            return {"accepted": False, "reason": "PRICE_OUTSIDE_ENTRY_ZONE"}

        # Concurrency limit check
        open_count = c.execute("SELECT COUNT(*) n FROM paper_positions WHERE status='OPEN'").fetchone()["n"]
        if open_count >= cfg["max_positions"]:
            _log_event(c, "SIGNAL_REJECTED", setup_id=sid, detail={"reason": "MAX_POSITIONS", "open": open_count, "limit": cfg["max_positions"]})
            c.commit()
            return {"accepted": False, "reason": "MAX_POSITIONS"}

        # Position sizing calculation
        risk_budget = equity * cfg["risk_fraction"]
        risk_per_unit = abs(entry - stop)
        if risk_per_unit <= 0:
            c.commit()
            return {"accepted": False, "reason": "ZERO_RISK_PER_UNIT"}

        qty = risk_budget / risk_per_unit
        max_qty = cfg["max_notional"] / price
        qty = min(qty, max_qty)

        if qty <= 0:
            c.commit()
            return {"accepted": False, "reason": "ZERO_SIZE"}

        # Simulated execution fill with slippage
        slip = price * (cfg["slippage_bps"] / 10000.0)
        fill_price = (price + slip) if direction == "LONG" else (price - slip)
        entry_fee = fill_price * qty * cfg["fee_rate"]

        pos_id = uuid.uuid4().hex
        order_id = uuid.uuid4().hex
        order_side = "BUY" if direction == "LONG" else "SELL"

        try:
            c.execute(
                """
                INSERT INTO paper_positions(
                    id, setup_id, direction, status, entry_price, current_price, quantity,
                    notional, stop_loss, take_profit, entry_fee, created_at, signal_json,
                    initial_stop, highest_price, lowest_price, mfe, mae, breakeven_triggered, trailing_stop_active
                )
                VALUES(?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, 0, 0)
                """,
                (
                    pos_id,
                    sid,
                    direction,
                    fill_price,
                    price,
                    qty,
                    fill_price * qty,
                    stop,
                    target,
                    entry_fee,
                    now,
                    json.dumps(setup, default=str),
                    stop,
                    fill_price,
                    fill_price,
                ),
            )
            c.execute(
                """
                INSERT INTO paper_orders(
                    id, position_id, setup_id, side, order_type, requested_price,
                    fill_price, quantity, status, fee, created_at
                )
                VALUES(?, ?, ?, ?, 'MARKET', ?, ?, ?, 'FILLED', ?, ?)
                """,
                (order_id, pos_id, sid, order_side, price, fill_price, qty, entry_fee, now),
            )
        except sqlite3.IntegrityError:
            c.commit()
            return {"accepted": False, "reason": "DUPLICATE_SETUP"}

        _log_event(
            c,
            "POSITION_OPENED",
            setup_id=sid,
            position_id=pos_id,
            detail={
                "order_id": order_id,
                "direction": direction,
                "entry_price": fill_price,
                "stop_loss": stop,
                "take_profit": target,
                "quantity": qty,
                "notional": fill_price * qty,
                "entry_fee": entry_fee,
            },
        )
        c.commit()
        return {
            "accepted": True,
            "position_id": pos_id,
            "order_id": order_id,
            "quantity": qty,
            "entry_price": fill_price,
        }

def update_stop_loss(position_id: str, new_stop: float) -> Dict[str, Any]:
    """
    Update position protective stop loss with strict Section 8 monotonic validation.
    Rule: Stops can ONLY move in the direction of profit (never widened).
    """
    with LOCK, _database() as c:
        row = c.execute("SELECT * FROM paper_positions WHERE id=? AND status='OPEN'", (position_id,)).fetchone()
        if not row:
            return {"success": False, "reason": "POSITION_NOT_FOUND", "message": "Open position not found"}

        pos = dict(row)
        direction = pos["direction"]
        current_stop = float(pos["stop_loss"])
        current_price = float(pos["current_price"])
        new_stop = round(float(new_stop), 2)

        # Monotonicity check
        if direction == "LONG":
            if new_stop <= current_stop:
                _log_event(c, "RISK_VIOLATION", position_id=position_id, detail={
                    "rule": "MONOTONIC_STOP_WIDEN_PROHIBITED",
                    "direction": "LONG",
                    "current_stop": current_stop,
                    "attempted_stop": new_stop
                })
                c.commit()
                return {
                    "success": False,
                    "reason": "REJECTED_NON_MONOTONIC_STOP",
                    "message": f"Cannot widen stop loss for LONG from ${current_stop:.2f} to ${new_stop:.2f}."
                }
            if new_stop >= current_price:
                return {
                    "success": False,
                    "reason": "STOP_EXCEEDS_MARKET_PRICE",
                    "message": f"New stop (${new_stop:.2f}) must be below current market price (${current_price:.2f})."
                }
        else:  # SHORT
            if new_stop >= current_stop:
                _log_event(c, "RISK_VIOLATION", position_id=position_id, detail={
                    "rule": "MONOTONIC_STOP_WIDEN_PROHIBITED",
                    "direction": "SHORT",
                    "current_stop": current_stop,
                    "attempted_stop": new_stop
                })
                c.commit()
                return {
                    "success": False,
                    "reason": "REJECTED_NON_MONOTONIC_STOP",
                    "message": f"Cannot widen stop loss for SHORT from ${current_stop:.2f} to ${new_stop:.2f}."
                }
            if new_stop <= current_price:
                return {
                    "success": False,
                    "reason": "STOP_EXCEEDS_MARKET_PRICE",
                    "message": f"New stop (${new_stop:.2f}) must be above current market price (${current_price:.2f})."
                }

        # Apply update
        c.execute("UPDATE paper_positions SET stop_loss=? WHERE id=?", (new_stop, position_id))
        _log_event(c, "STOP_LOSS_UPDATED", position_id=position_id, detail={
            "old_stop": current_stop,
            "new_stop": new_stop,
            "direction": direction
        })
        c.commit()
        return {
            "success": True,
            "message": f"Stop loss updated to ${new_stop:.2f}",
            "position_id": position_id,
            "new_stop": new_stop
        }

def mark_to_market(price: float, high: Optional[float] = None, low: Optional[float] = None) -> None:
    """
    Update open positions with realistic execution simulation:
    - MFE and MAE tracking
    - Break-even milestone activation (at 1R profit)
    - Conservative candle tie-breaker: if both stop and target touched in same bar, STOP LOSS executes.
    """
    if not price or price <= 0:
        return
    bar_high = float(high) if high is not None else float(price)
    bar_low = float(low) if low is not None else float(price)

    with LOCK, _database() as c:
        _check_day_rollover(c)
        cfg = {k: _meta(c, k) for k in DEFAULT_CONFIG}
        open_pos_rows = c.execute("SELECT * FROM paper_positions WHERE status='OPEN'").fetchall()

        for row in open_pos_rows:
            pos = dict(row)
            pos_id = pos["id"]
            direction = pos["direction"]
            entry_price = float(pos["entry_price"])
            stop = float(pos["stop_loss"])
            target = float(pos["take_profit"])
            initial_stop = float(pos.get("initial_stop") or stop)
            prev_highest = float(pos.get("highest_price") or entry_price)
            prev_lowest = float(pos.get("lowest_price") or entry_price)
            be_triggered = int(pos.get("breakeven_triggered") or 0)

            # Update highest and lowest extremes
            highest = max(prev_highest, bar_high)
            lowest = min(prev_lowest, bar_low)

            # MFE and MAE calculation
            if direction == "LONG":
                mfe = max(0.0, highest - entry_price)
                mae = max(0.0, entry_price - lowest)
            else:
                mfe = max(0.0, entry_price - lowest)
                mae = max(0.0, highest - entry_price)

            # 1R Break-even milestone check
            r_distance = abs(entry_price - initial_stop)
            if be_triggered == 0 and r_distance > 0:
                if direction == "LONG" and bar_high >= (entry_price + r_distance):
                    # Move stop to break-even + small buffer
                    new_be_stop = round(entry_price + 0.1, 2)
                    if new_be_stop > stop:
                        stop = new_be_stop
                        be_triggered = 1
                        _log_event(c, "BREAKEVEN_TRIGGERED", position_id=pos_id, detail={
                            "entry": entry_price, "new_stop": stop, "1R_target": entry_price + r_distance
                        })
                elif direction == "SHORT" and bar_low <= (entry_price - r_distance):
                    new_be_stop = round(entry_price - 0.1, 2)
                    if new_be_stop < stop:
                        stop = new_be_stop
                        be_triggered = 1
                        _log_event(c, "BREAKEVEN_TRIGGERED", position_id=pos_id, detail={
                            "entry": entry_price, "new_stop": stop, "1R_target": entry_price - r_distance
                        })

            # Update live position state in DB
            c.execute(
                """
                UPDATE paper_positions
                SET current_price=?, highest_price=?, lowest_price=?, mfe=?, mae=?,
                    stop_loss=?, breakeven_triggered=?
                WHERE id=?
                """,
                (price, highest, lowest, mfe, mae, stop, be_triggered, pos_id)
            )

            # Execution simulation: Conservative candle tie-breaker
            # If both stop and target touched in the same bar, assume stop was hit first!
            if direction == "LONG":
                stop_touched = (bar_low <= stop)
                target_touched = (bar_high >= target)
                if stop_touched and target_touched:
                    # Conservative tie-breaker: STOP LOSS executed
                    _execute_close(c, pos, stop, "STOP_LOSS", cfg)
                elif stop_touched:
                    _execute_close(c, pos, stop, "STOP_LOSS", cfg)
                elif target_touched:
                    _execute_close(c, pos, target, "TAKE_PROFIT", cfg)
            else:  # SHORT
                stop_touched = (bar_high >= stop)
                target_touched = (bar_low <= target)
                if stop_touched and target_touched:
                    # Conservative tie-breaker: STOP LOSS executed
                    _execute_close(c, pos, stop, "STOP_LOSS", cfg)
                elif stop_touched:
                    _execute_close(c, pos, stop, "STOP_LOSS", cfg)
                elif target_touched:
                    _execute_close(c, pos, target, "TAKE_PROFIT", cfg)

        c.commit()

def get_positions(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    with LOCK, _database() as c:
        last_price = float(_meta(c, "last_price") or 0.0)
        metrics = _compute_metrics(c, last_price)
        if status_filter == "OPEN":
            return metrics["open_positions"]
        elif status_filter == "CLOSED":
            return [dict(r) for r in c.execute("SELECT * FROM paper_positions WHERE status='CLOSED' ORDER BY closed_at DESC").fetchall()]
        else:
            all_rows = [dict(r) for r in c.execute("SELECT * FROM paper_positions ORDER BY created_at DESC").fetchall()]
            return all_rows

def get_orders() -> List[Dict[str, Any]]:
    with LOCK, _database() as c:
        return [dict(r) for r in c.execute("SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT 300").fetchall()]

def get_trades() -> List[Dict[str, Any]]:
    with LOCK, _database() as c:
        return [dict(r) for r in c.execute("SELECT * FROM paper_positions WHERE status='CLOSED' ORDER BY closed_at DESC LIMIT 300").fetchall()]

def get_events() -> List[Dict[str, Any]]:
    with LOCK, _database() as c:
        events = [dict(r) for r in c.execute("SELECT * FROM paper_events ORDER BY ts DESC LIMIT 300").fetchall()]
        for e in events:
            try:
                e["detail"] = json.loads(e["detail"])
            except Exception:
                pass
        return events
