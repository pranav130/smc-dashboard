import asyncio
import os
import time
import logging
from contextlib import asynccontextmanager
from typing import Set, Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Header, HTTPException, Body, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.config import (
    DEFAULT_SYMBOL,
    DEFAULT_PRODUCT_ID,
    INDEX_SYMBOL,
    MARK_SYMBOL,
    PRICE_SOURCE,
    IST_TZ,
    ALLOWED_ORIGINS,
    ADMIN_API_KEY,
    validate_environment
)
from backend.adapters.delta_exchange import DeltaExchangeAdapter, MIN_24H_CANDLES, TIMEFRAME_LIMITS
from backend.smc.models import MarketDataStatus, Candle, AnalysisConfig
from backend.smc.engine import SMCEngine
from backend.paper.database import init_db, get_db
from backend.paper.engine import PaperTradingEngine
from backend.paper.models import PaperLogModel
from backend import paper_trading
from backend.risk.rejection_inspector import global_rejection_inspector
from backend.backtesting.engine import BacktestEngine

logger = logging.getLogger("App")
logging.basicConfig(level=logging.INFO)

# Validate environment safety
validate_environment()

# Initialize adapter, engine & persistent paper trading system
adapter = DeltaExchangeAdapter()
smc_engine = SMCEngine()
paper_engine = PaperTradingEngine()

# Active WebSocket connections to browser clients
connected_clients: Set[WebSocket] = set()

# Background monitoring task handle
background_monitor_task: Optional[asyncio.Task] = None

def broadcast_live_update(timeframe: str, candle: Candle):
    """Callback triggered whenever a forming or confirmed candle updates."""
    # 1. Immediately evaluate paper trading positions on price tick
    if candle.close > 0:
        paper_engine.on_tick(candle.close, candle.time)
        paper_trading.mark_to_market(candle.close)

    # 2. Broadcast to connected browser clients if any exist
    if not connected_clients:
        return

    payload = {
        "event": "candle_update",
        "type": "candle_update",
        "timeframe": timeframe,
        "candle": candle.model_dump(),
        "status": get_current_status(timeframe).model_dump()
    }
    
    asyncio.create_task(_send_to_all(payload))

async def _send_to_all(message: dict):
    disconnected = []
    for ws in list(connected_clients):
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.discard(ws)

def get_current_status(timeframe: str = "1H") -> MarketDataStatus:
    tf = timeframe.upper()
    candles = adapter.get_candles(tf)
    last_candle = candles[-1] if candles else None
    current_price = last_candle.close if last_candle else 0.0

    conn_status = adapter.get_connection_status()
    now_ts = int(time.time())
    is_stale = (now_ts - adapter.last_successful_update) > 60

    warnings = []
    if is_stale:
        warnings.append("Data stream is delayed or stale (>60s since last update).")
    if conn_status in ["Reconnecting", "Disconnected"]:
        warnings.append(f"Connection issue: Status is {conn_status}.")

    last_ts = last_candle.time if last_candle else 0
    last_ist = last_candle.ist_time if last_candle else ""
    candle_state = "Forming" if (last_candle and last_candle.is_forming) else "Confirmed"

    is_index = (DEFAULT_SYMBOL == INDEX_SYMBOL)
    inst_name = "Tether Gold Spot Index (.DEXAUTUSD)" if is_index else "Tether Gold Perpetual Future (XAUTUSD)"
    contract_type = "spot_index" if is_index else "perpetual_futures"
    contract_val = "Spot Gold Index (1 oz Benchmark)" if is_index else "0.001 XAUT"

    return MarketDataStatus(
        instrument_name=inst_name,
        symbol=DEFAULT_SYMBOL,
        product_id=DEFAULT_PRODUCT_ID,
        contract_type=contract_type,
        quote_currency="USD",
        settling_currency="USD",
        contract_value=contract_val,
        tick_size=0.01,
        data_provider="Delta Exchange India",
        selected_timeframe=tf,
        last_candle_timestamp=last_ts,
        last_candle_ist=last_ist or adapter.format_ist(last_ts),
        last_update_timestamp=adapter.last_successful_update,
        last_update_ist=adapter.format_ist(adapter.last_successful_update) if adapter.last_successful_update else "",
        connection_status=conn_status,
        candle_state=candle_state,
        current_price=current_price,
        is_stale=is_stale,
        warnings=warnings
    )

async def _background_market_monitor_loop():
    """
    24/7 continuous market evaluation loop running independently of browser clients.
    Polls/evaluates SMC setups and open paper positions periodically even with 0 active web sessions.
    """
    logger.info("24/7 Background Market Monitoring loop started.")
    while True:
        try:
            await asyncio.sleep(5)
            candles_1h = adapter.get_candles("1H")
            if not candles_1h:
                continue

            current_price = candles_1h[-1].close if candles_1h else 0.0
            if current_price <= 0:
                continue

            last_h1 = candles_1h[-1] if candles_1h else None
            high_val = last_h1.high if last_h1 else current_price
            low_val = last_h1.low if last_h1 else current_price

            # Update open paper positions with conservative tie-breaker
            paper_engine.on_tick(current_price)
            paper_trading.mark_to_market(current_price, high=high_val, low=low_val)

            # Evaluate multi-timeframe SMC signals for paper trading
            candles_by_tf = {
                tf: adapter.get_candles(tf)
                for tf in ["1D", "4H", "1H", "30M", "15M", "5M", "1M"]
            }
            status = get_current_status("1H")
            analysis = smc_engine.analyze_multi_timeframe(candles_by_tf, "1H", is_stale=status.is_stale)
            paper_engine.evaluate_signals_for_paper_trading(analysis, current_price)

            terminal = analysis.get("terminal_state") or {}
            setup = terminal.get("active_setup") or {}

            # Fallback to decoupled Model A or Model B setups if eligible
            if not setup or (hasattr(setup, "state") and setup.state != "ACTIVE") or (isinstance(setup, dict) and setup.get("state") != "ACTIVE"):
                mod_a = analysis.get("model_a_setup")
                mod_b = analysis.get("model_b_setup")
                if mod_a and getattr(mod_a, "state", None) == "ACTIVE":
                    setup = mod_a
                elif mod_b and getattr(mod_b, "state", None) == "ACTIVE":
                    setup = mod_b

            if hasattr(setup, "model_dump"):
                setup = setup.model_dump()

            if setup and setup.get("state") == "ACTIVE":
                decision = paper_trading.evaluate(
                    setup,
                    current_price,
                    status.last_update_timestamp,
                    status.is_stale,
                )
                if decision.get("accepted"):
                    logger.info(f"⚡ [24/7 Engine] Executed paper trade for setup {setup.get('id')}: position #{decision.get('position_id')}")
                elif not decision.get("accepted"):
                    global_rejection_inspector.record_rejection(
                        model=setup.get("name", "SMC Setup"),
                        stage_failed=decision.get("reason", "RISK_REJECTION"),
                        reasons=[decision.get("message") or decision.get("reason") or "Setup rejected by risk controller"],
                        evaluated_price=current_price,
                        setup_id=setup.get("id"),
                        direction=setup.get("direction"),
                        telemetry=decision.get("telemetry", {})
                    )

        except asyncio.CancelledError:
            logger.info("24/7 Background Market Monitoring loop stopped.")
            break
        except Exception as e:
            logger.error(f"Error in continuous background monitor: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize persistent database tables
    print("Initializing persistent database schema...")
    init_db()

    # 2. Fetch historical candles across all timeframes
    print(f"Starting SMC Dashboard backend for {DEFAULT_SYMBOL}...")
    await adapter.initialize_all_timeframes(DEFAULT_SYMBOL)

    # 3. Start live WebSocket stream across all timeframes
    await adapter.start_streaming(
        symbol=DEFAULT_SYMBOL,
        timeframes=["1D", "4H", "1H", "30M", "15M", "5M", "1M"],
        on_candle_update=broadcast_live_update
    )

    # 4. Launch 24/7 continuous market evaluation task
    global background_monitor_task
    background_monitor_task = asyncio.create_task(_background_market_monitor_loop())

    yield

    # Shutdown
    print("Shutting down SMC Dashboard...")
    if background_monitor_task and not background_monitor_task.done():
        background_monitor_task.cancel()
    await adapter.stop_streaming()

app = FastAPI(title="SMC Key-Level Intelligence Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ==============================================================================
# Health Check Endpoints (for Render, Railway, Load Balancer)
# ==============================================================================
@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health_check():
    db_ok = False
    try:
        with get_db() as db:
            db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    adapter_status = adapter.get_connection_status()
    is_healthy = db_ok and (adapter_status != "Disconnected")

    return {
        "status": "healthy" if is_healthy else "degraded",
        "timestamp": int(time.time()),
        "database": "connected" if db_ok else "unreachable",
        "market_feed": adapter_status,
        "symbol": DEFAULT_SYMBOL,
        "mode": "PAPER_TRADING",
        "service": "smc-dashboard"
    }

# ==============================================================================
# Main Dashboard API Endpoints (Preserved Exactly)
# ==============================================================================
@app.get("/api/status")
async def get_status(timeframe: str = Query("1H")):
    return get_current_status(timeframe)

@app.get("/api/candles")
async def get_candles(
    timeframe: Optional[str] = Query(None),
    tf: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    format: Optional[str] = Query(None)
):
    selected_tf = (tf or timeframe or "1H").upper()
    candles = adapter.get_candles(selected_tf)
    min_count = MIN_24H_CANDLES.get(selected_tf, 25)
    if len(candles) < min_count:
        candles = await adapter.fetch_historical_candles(
            DEFAULT_SYMBOL, selected_tf, limit=TIMEFRAME_LIMITS.get(selected_tf, 500)
        )

    # Format items compatible with both template [{t,o,h,l,c,closed}] and existing dashboard [{time,open,...}]
    items = [
        {
            "t": c.time,
            "time": c.time,
            "o": c.open,
            "open": c.open,
            "h": c.high,
            "high": c.high,
            "l": c.low,
            "low": c.low,
            "c": c.close,
            "close": c.close,
            "v": c.volume,
            "volume": c.volume,
            "closed": not c.is_forming,
            "is_forming": c.is_forming
        }
        for c in candles
    ]

    # If called via template signature (?tf=... or ?format=array), return array directly
    if tf is not None or format == "array":
        return items

    return {
        "success": True,
        "symbol": DEFAULT_SYMBOL,
        "timeframe": selected_tf,
        "count": len(candles),
        "candles": [c.model_dump() for c in candles]
    }

@app.get("/api/signal")
async def get_signal(
    timeframe: Optional[str] = Query(None),
    tf: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None)
):
    selected_tf = (tf or timeframe or "1H").upper()
    candles_by_tf = {
        k: adapter.get_candles(k)
        for k in ["1D", "4H", "2H", "1H", "30M", "15M", "10M", "5M", "1M"]
    }
    status = get_current_status(selected_tf)
    analysis = smc_engine.analyze_multi_timeframe(
        candles_by_tf, selected_tf, is_stale=status.is_stale
    )

    terminal = analysis.get("terminal_state", {})
    state = terminal.get("classification") or terminal.get("signal_state") or "WAIT_WATCH"
    setup = terminal.get("setup") or analysis.get("active_setup") or {}

    direction = None
    raw_dir = str(setup.get("direction") or "").lower()
    if "bull" in raw_dir or "long" in raw_dir:
        direction = "long"
    elif "bear" in raw_dir or "short" in raw_dir:
        direction = "short"

    entry = setup.get("entry_price") or setup.get("price") or setup.get("entry_zone_mid")
    stop = setup.get("invalidation_price") or setup.get("stop_loss")
    target1 = setup.get("target_price") or setup.get("target1")
    target2 = setup.get("target2") or (round(target1 + (target1 - entry), 2) if (target1 and entry) else None)
    targets = [t for t in [target1, target2] if t is not None]

    now_ts = int(time.time())
    expires_at = setup.get("expires_at") or (now_ts + 14400 if state in ["ACTIVE", "EXTREME"] else None)

    # Structure & retracement
    structure = analysis.get("market_structure_summary") or analysis.get("market_structure", "Neutral Market Structure")
    retracement = analysis.get("retracement_summary") or analysis.get("retracement", "In Equilibrium Zone")

    # Multi-timeframe bias map
    market_state = analysis.get("market_state", {})
    tf_data = market_state.get("timeframes", {})
    bias_map = {}
    for k in ["1d", "4h", "2h", "1h", "15m"]:
        b = tf_data.get(k.upper(), {}).get("bias") or "Neutral"
        bias_map[k] = str(b).capitalize()

    # Liquidity & key levels with explicit HTF (4H/1D) and Current-TF separation
    levels = []
    seen_levels = set()

    # 1. Higher-Timeframe FVGs (4H and 1D unmitigated gaps)
    for f in (analysis.get("h4_fvgs") or []) + (analysis.get("daily_fvgs") or []):
        if not f.get("mitigated"):
            mid = round(float(f.get("midpoint", 0)), 2)
            if mid > 0 and mid not in seen_levels:
                seen_levels.add(mid)
                f_tf = str(f.get("timeframe") or "4H").upper()
                dir_str = str(f.get("direction") or "Bullish").capitalize()
                levels.append({
                    "kind": "FVG",
                    "price": mid,
                    "label": f"{f_tf} {dir_str} FVG (${f.get('bottom', 0):.2f}-${f.get('top', 0):.2f})",
                    "tf": f_tf,
                    "is_htf_fvg": True,
                    "is_curr_fvg": False,
                    "is_htf_level": False,
                    "is_curr_level": False
                })

    # 2. Current Timeframe FVGs (unmitigated gaps from the active chart resolution)
    for f in (analysis.get("timeframe_fvgs") or []):
        if not f.get("mitigated"):
            mid = round(float(f.get("midpoint", 0)), 2)
            if mid > 0 and mid not in seen_levels:
                seen_levels.add(mid)
                f_tf = str(f.get("timeframe") or selected_tf).upper()
                dir_str = str(f.get("direction") or "Bullish").capitalize()
                is_htf = f_tf in ["1D", "4H", "1W"]
                levels.append({
                    "kind": "FVG",
                    "price": mid,
                    "label": f"{f_tf} {dir_str} FVG (${f.get('bottom', 0):.2f}-${f.get('top', 0):.2f})",
                    "tf": f_tf,
                    "is_htf_fvg": is_htf,
                    "is_curr_fvg": not is_htf,
                    "is_htf_level": False,
                    "is_curr_level": False
                })

    # 3. Key Levels & Liquidity Pools
    for l in (analysis.get("key_levels_summary") or []) + (analysis.get("liquidity_levels") or []):
        p = round(float(l.get("price", 0)), 2)
        if p <= 0 or p in seen_levels:
            continue
        seen_levels.add(p)
        kind = str(l.get("type") or l.get("kind") or "POI").upper()
        if "BSL" in kind: kind = "BSL"
        elif "SSL" in kind: kind = "SSL"
        elif "FVG" in kind: kind = "FVG"
        elif "EQH" in kind: kind = "EQH"
        elif "EQL" in kind: kind = "EQL"
        elif "SUP" in kind or "SUPPORT" in kind: kind = "SUP"
        elif "RES" in kind or "RESIST" in kind: kind = "RES"
        else: kind = "RES" if p > status.current_price else "SUP"

        label = str(l.get("name") or l.get("label") or kind)
        l_tf = str(l.get("timeframe") or l.get("tf") or ("1D" if any(x in label.lower() for x in ["previous day", "previous week", "pdh", "pdl", "pwh", "pwl"]) else selected_tf)).upper()

        is_fvg = (kind == "FVG")
        is_htf_fvg = is_fvg and (l_tf in ["1D", "4H", "1W"] or "4h" in label.lower() or "1d" in label.lower() or "daily" in label.lower())
        is_curr_fvg = is_fvg and not is_htf_fvg

        is_htf_level = not is_fvg and (l_tf in ["1D", "4H", "1W"] or any(x in label.lower() for x in ["previous day", "previous week", "pdh", "pdl", "pwh", "pwl", "daily", "weekly", "institutional", "round 20", "round 80"]))
        is_curr_level = not is_fvg and not is_htf_level

        levels.append({
            "kind": kind,
            "price": p,
            "label": label,
            "tf": l_tf,
            "is_htf_fvg": is_htf_fvg,
            "is_curr_fvg": is_curr_fvg,
            "is_htf_level": is_htf_level,
            "is_curr_level": is_curr_level
        })

    # Confirmation checklist
    checklist = []
    raw_checklist = setup.get("confluence_checklist") or analysis.get("confirmation_checklist", [])
    if isinstance(raw_checklist, list):
        for item in raw_checklist:
            if isinstance(item, dict):
                checklist.append({
                    "label": item.get("name") or item.get("label") or item.get("condition", "Condition"),
                    "met": bool(item.get("met", False) or item.get("status") == "PASS")
                })
    if not checklist:
        checklist = [
            {"label": "HTF directional bias alignment", "met": direction is not None and bias_map.get("1h", "").lower() == direction},
            {"label": "Valid SMC displacement / BOS", "met": state in ["ACTIVE", "EXTREME", "WATCH"]},
            {"label": "Key POI retracement (FVG / S&R)", "met": state in ["ACTIVE", "EXTREME"]},
            {"label": "Safety line & risk boundary intact", "met": not status.is_stale}
        ]

    return {
        "state": state,
        "direction": direction,
        "entry": float(entry) if entry else None,
        "stop": float(stop) if stop else None,
        "targets": targets,
        "expires_at": expires_at,
        "structure": structure,
        "retracement": retracement,
        "bias": bias_map,
        "levels": levels,
        "checklist": checklist
    }


@app.get("/api/smc")
async def get_smc_analysis(
    timeframe: str = Query("1H"),
    swing_window: int = Query(3),
    fvg_min_size_mult: float = Query(0.1),
    bos_min_retrace: float = Query(40.0)
):
    tf = timeframe.upper()
    candles_by_tf = {
        "1D": adapter.get_candles("1D"),
        "4H": adapter.get_candles("4H"),
        "1H": adapter.get_candles("1H"),
        "30M": adapter.get_candles("30M"),
        "15M": adapter.get_candles("15M"),
        "5M": adapter.get_candles("5M"),
        "1M": adapter.get_candles("1M"),
    }
    config = AnalysisConfig(
        swing_window=swing_window,
        fvg_min_size_atr_multiplier=fvg_min_size_mult,
        bos_min_retracement_pct=bos_min_retrace
    )
    status = get_current_status(tf)
    analysis = smc_engine.analyze_multi_timeframe(candles_by_tf, tf, config, is_stale=status.is_stale)
    return {
        "success": True,
        "status": status.model_dump(),
        "analysis": analysis
    }

@app.get("/api/watchlist")
async def get_watchlist(timeframe: str = Query("1H")):
    tf = timeframe.upper()
    candles_by_tf = {
        "1D": adapter.get_candles("1D"),
        "4H": adapter.get_candles("4H"),
        "1H": adapter.get_candles("1H"),
        "30M": adapter.get_candles("30M"),
        "15M": adapter.get_candles("15M"),
        "5M": adapter.get_candles("5M"),
        "1M": adapter.get_candles("1M"),
    }
    status = get_current_status(tf)
    analysis = smc_engine.analyze_multi_timeframe(candles_by_tf, tf, is_stale=status.is_stale)
    return {
        "success": True,
        "timeframe": tf,
        "watchlist": analysis.get("watchlist", []),
        "active_alerts": analysis.get("active_alerts", []),
        "state_counts": analysis.get("state_counts", {}),
        "status": status.model_dump()
    }

@app.get("/api/alerts")
async def get_alerts(include_acknowledged: bool = Query(False)):
    from backend.smc.activation import global_alert_store
    alerts = global_alert_store.get_alerts(include_acknowledged=include_acknowledged)
    return {
        "success": True,
        "alerts": [a.model_dump() for a in alerts]
    }

@app.post("/api/alerts/acknowledge")
async def acknowledge_alert(alert_id: str = Query(None), dismiss_all: bool = Query(False)):
    from backend.smc.activation import global_alert_store
    if dismiss_all:
        global_alert_store.dismiss_all()
        return {"success": True, "message": "All alerts dismissed"}
    elif alert_id:
        res = global_alert_store.acknowledge_alert(alert_id)
        return {"success": res, "message": f"Alert {alert_id} acknowledged" if res else "Alert not found"}
    return {"success": False, "message": "No alert_id or dismiss_all specified"}

@app.get("/api/market-state")
async def get_market_state(timeframe: str = Query("1H")):
    tf = timeframe.upper()
    candles_by_tf = {
        "1D": adapter.get_candles("1D"),
        "4H": adapter.get_candles("4H"),
        "1H": adapter.get_candles("1H"),
        "30M": adapter.get_candles("30M"),
        "15M": adapter.get_candles("15M"),
        "5M": adapter.get_candles("5M"),
        "1M": adapter.get_candles("1M"),
    }
    status = get_current_status(tf)
    analysis = smc_engine.analyze_multi_timeframe(candles_by_tf, tf, is_stale=status.is_stale)
    return {
        "success": True,
        "market_state": analysis.get("market_state"),
        "status": status.model_dump()
    }

@app.get("/api/liquidity-intelligence")
async def get_liquidity_intelligence(timeframe: str = Query("1H")):
    tf = timeframe.upper()
    candles_by_tf = {
        "1D": adapter.get_candles("1D"),
        "4H": adapter.get_candles("4H"),
        "1H": adapter.get_candles("1H"),
        "30M": adapter.get_candles("30M"),
        "15M": adapter.get_candles("15M"),
        "5M": adapter.get_candles("5M"),
        "1M": adapter.get_candles("1M"),
    }
    status = get_current_status(tf)
    analysis = smc_engine.analyze_multi_timeframe(candles_by_tf, tf, is_stale=status.is_stale)
    return {
        "success": True,
        "timeframe": tf,
        "liquidity_intelligence": analysis.get("liquidity_intelligence"),
        "status": status.model_dump()
    }

@app.get("/api/config/price-source")
async def get_price_source():
    is_index = (DEFAULT_SYMBOL == INDEX_SYMBOL)
    return {
        "success": True,
        "price_source": "index" if is_index else "mark",
        "symbol": DEFAULT_SYMBOL,
        "product_id": DEFAULT_PRODUCT_ID,
        "index_symbol": INDEX_SYMBOL,
        "mark_symbol": MARK_SYMBOL,
        "description": "Delta Exchange India Spot Gold Index (.DEXAUTUSD)" if is_index else "Delta Exchange India Perpetual Futures Mark Price (XAUTUSD)"
    }

@app.post("/api/refresh")
async def refresh_market_data():
    await adapter.initialize_all_timeframes(DEFAULT_SYMBOL)
    return {"success": True, "message": "Refreshed historical candles for all timeframes (>= 24h data)"}

# ==============================================================================
# Isolated Paper Trading API Endpoints
# ==============================================================================
@app.get("/api/paper/status")
@app.get("/api/paper/summary")
async def get_paper_status():
    return paper_trading.status()

@app.get("/api/paper/positions")
async def get_paper_positions(status: Optional[str] = Query(None)):
    return paper_trading.get_positions(status_filter=status)

@app.get("/api/paper/orders")
async def get_paper_orders():
    return paper_trading.get_orders()

@app.get("/api/paper/trades")
async def get_paper_trades(limit: int = Query(100)):
    return paper_trading.get_trades()

@app.get("/api/paper/events")
@app.get("/api/paper/logs")
async def get_paper_events(limit: int = Query(100)):
    return paper_trading.get_events()

@app.get("/api/paper/config")
async def get_paper_config():
    return paper_trading.get_config()

@app.post("/api/paper/config")
async def update_paper_config(payload: Dict[str, Any] = Body(...)):
    try:
        updated = paper_trading.update_config(payload)
        return {"success": True, "config": updated}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/paper/control/{action}")
async def paper_control(action: str, request: Request):
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        pass
    return paper_trading.control(action, payload)

@app.post("/api/paper/positions/{position_id}/close")
async def paper_close_position_by_id(position_id: str):
    return paper_trading.close_position(position_id)

@app.post("/api/paper/close")
async def paper_close_position(request: Request):
    target_id = None
    try:
        body = await request.json()
        target_id = body.get("position_id")
    except Exception:
        pass
    if not target_id:
        return {"success": False, "message": "Missing position_id"}
    return paper_trading.close_position(target_id)

@app.get("/api/paper/rejections")
async def get_paper_rejections(
    model: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    limit: int = Query(100)
):
    """Retrieve filtered list of rejected candidate trade setups."""
    return {
        "success": True,
        "rejections": global_rejection_inspector.get_rejections(limit=limit, model_filter=model, stage_filter=stage),
        "summary": global_rejection_inspector.get_rejection_summary()
    }

@app.get("/api/paper/rejections/summary")
async def get_paper_rejections_summary():
    """Retrieve aggregated rejection statistics by model and failed pipeline stage."""
    return {
        "success": True,
        "summary": global_rejection_inspector.get_rejection_summary()
    }

@app.post("/api/paper/backtest")
async def run_paper_backtest(payload: Dict[str, Any] = Body(default={})):
    """
    Execute historical walk-forward backtest (60% Train, 20% Val, 20% Test) and Monte Carlo simulation.
    """
    strategy = payload.get("strategy", "COMBINED").upper()
    candles_1h = adapter.get_candles("1H")
    candles_4h = adapter.get_candles("4H")
    candles_1d = adapter.get_candles("1D")

    if len(candles_1h) < 30:
        return {
            "success": False,
            "message": f"Insufficient historical candles ({len(candles_1h)}/30 loaded). Refresh market data first."
        }

    engine = BacktestEngine()
    results = engine.run_walk_forward_validation(
        candles_1h=candles_1h,
        candles_4h=candles_4h,
        candles_1d=candles_1d,
        strategy_mode=strategy
    )
    return {
        "success": True,
        "strategy": strategy,
        "results": results
    }

@app.get("/api/paper/trade_replay/{position_id}")
async def get_trade_replay(position_id: str):
    """
    Forensic point-in-time trade reconstruction:
    Reconstructs exact signal state, entry fill, excursions (MFE/MAE), stop adjustments, and exit fills.
    """
    positions = paper_trading.get_positions()
    target_pos = next((p for p in positions if p["id"] == position_id), None)
    if not target_pos:
        raise HTTPException(status_code=404, detail="Trade position not found")

    events = [e for e in paper_trading.get_events() if (e.get("position_id") == position_id or e.get("setup_id") == target_pos.get("setup_id"))]
    orders = [o for o in paper_trading.get_orders() if o.get("position_id") == position_id]

    return {
        "success": True,
        "position": target_pos,
        "timeline": sorted(events, key=lambda x: x.get("ts", 0)),
        "orders": orders,
        "metrics": {
            "mfe": target_pos.get("mfe", 0.0),
            "mae": target_pos.get("mae", 0.0),
            "breakeven_triggered": bool(target_pos.get("breakeven_triggered", 0)),
            "holding_period_seconds": (target_pos.get("closed_at") or time.time()) - target_pos.get("created_at", 0)
        }
    }

@app.post("/api/paper/positions/{position_id}/update_stop")
async def update_position_stop(position_id: str, payload: Dict[str, Any] = Body(...)):
    """Update position stop loss with strict monotonic validation."""
    new_stop = payload.get("new_stop")
    if new_stop is None:
        return {"success": False, "message": "Missing new_stop parameter"}
    return paper_trading.update_stop_loss(position_id, float(new_stop))

@app.post("/api/paper/tick")
async def paper_tick():
    tf = "1H"
    candles_by_tf = {
        name: adapter.get_candles(name)
        for name in ["1D", "4H", "1H", "30M", "15M", "5M", "1M"]
    }
    status = get_current_status(tf)
    analysis = smc_engine.analyze_multi_timeframe(candles_by_tf, tf, is_stale=status.is_stale)
    terminal = analysis.get("terminal_state") or {}
    setup = terminal.get("active_setup") or {}

    # Fallback to decoupled Model A or Model B setups if eligible
    if not setup or (hasattr(setup, "state") and setup.state != "ACTIVE") or (isinstance(setup, dict) and setup.get("state") != "ACTIVE"):
        mod_a = analysis.get("model_a_setup")
        mod_b = analysis.get("model_b_setup")
        if mod_a and getattr(mod_a, "state", None) == "ACTIVE":
            setup = mod_a
        elif mod_b and getattr(mod_b, "state", None) == "ACTIVE":
            setup = mod_b

    if hasattr(setup, "model_dump"):
        setup = setup.model_dump()

    # Pass bar high/low for conservative tie-breaker
    h1_candles = candles_by_tf.get("1H", [])
    last_h1 = h1_candles[-1] if h1_candles else None
    high_val = last_h1.high if last_h1 else status.current_price
    low_val = last_h1.low if last_h1 else status.current_price

    paper_trading.mark_to_market(status.current_price, high=high_val, low=low_val)
    decision = paper_trading.evaluate(
        setup,
        status.current_price,
        status.last_update_timestamp,
        status.is_stale,
    )

    # Telemetry logging to RejectionInspector if setup was evaluated but rejected
    if not decision.get("accepted") and setup and setup.get("name"):
        global_rejection_inspector.record_rejection(
            model=setup.get("name", "SMC Setup"),
            stage_failed=decision.get("reason", "RISK_REJECTION"),
            reasons=[decision.get("message") or decision.get("reason") or "Setup rejected by risk controller"],
            evaluated_price=status.current_price,
            setup_id=setup.get("id"),
            direction=setup.get("direction"),
            telemetry=decision.get("telemetry", {})
        )

    return {
        "success": True,
        "decision": decision,
        "status": paper_trading.status(),
        "active_setup": setup,
        "model_a_setup": analysis.get("model_a_setup"),
        "model_b_setup": analysis.get("model_b_setup"),
        "terminal_state": terminal,
        "market": {
            "price": status.current_price,
            "timestamp": status.last_update_timestamp,
            "is_stale": status.is_stale,
            "connection_status": status.connection_status,
            "feed_state": adapter.get_feed_state()
        },
    }

@app.post("/api/paper/simulate-demo-trade")
async def simulate_demo_trade():
    tf = "1H"
    status = get_current_status(tf)
    price = status.current_price if status.current_price > 0 else 4160.0
    ts = int(time.time())
    paper_trading.control("start")
    demo_setup = {
        "id": f"demo_setup_{ts}",
        "name": "Demo 1H Bullish Setup",
        "direction": "bullish",
        "timeframe": "1H",
        "state": "ACTIVE",
        "price": round(price, 2),
        "top": round(price + 2.0, 2),
        "bottom": round(price - 2.0, 2),
        "invalidation_price": round(price - 10.0, 2),
        "target_price": round(price + 50.0, 2),
        "rr_ratio": 5.0,
        "timestamp": ts,
    }
    decision = paper_trading.evaluate(demo_setup, price, ts, False)
    return {
        "success": True,
        "decision": decision,
        "status": paper_trading.status(),
        "demo_setup": demo_setup,
    }

# ==============================================================================
# WebSocket Endpoint for Live Frontend Streaming
# ==============================================================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        await websocket.send_json({
            "event": "connected",
            "message": "Connected to Delta Exchange Live Gold Stream",
            "status": get_current_status("1H").model_dump()
        })
        while True:
            data = await websocket.receive_text()
            if data:
                try:
                    import json
                    req = json.loads(data)
                    action = req.get("action")
                    if action == "subscribe_timeframe":
                        tf = req.get("timeframe", "1H").upper()
                        candles_by_tf = {
                            "1D": adapter.get_candles("1D"),
                            "4H": adapter.get_candles("4H"),
                            "1H": adapter.get_candles("1H"),
                            "30M": adapter.get_candles("30M"),
                            "15M": adapter.get_candles("15M"),
                            "5M": adapter.get_candles("5M"),
                            "1M": adapter.get_candles("1M"),
                        }
                        analysis = smc_engine.analyze_multi_timeframe(candles_by_tf, tf)
                        await websocket.send_json({
                            "event": "smc_sync",
                            "type": "smc_sync",
                            "timeframe": tf,
                            "candles": [c.model_dump() for c in adapter.get_candles(tf)],
                            "analysis": analysis,
                            "status": get_current_status(tf).model_dump()
                        })
                except Exception:
                    pass
    except WebSocketDisconnect:
        connected_clients.discard(websocket)
    except Exception:
        connected_clients.discard(websocket)

# ==============================================================================
# Static Asset & HTML Routes
# ==============================================================================
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.api_route("/", methods=["GET", "HEAD"])
async def serve_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "SMC Dashboard Frontend building..."}

@app.get("/paper")
async def serve_paper_dashboard():
    """Serve dedicated Paper Trading Dashboard."""
    paper_path = os.path.join(frontend_dir, "paper.html")
    if os.path.exists(paper_path):
        return FileResponse(paper_path)
    return {"message": "Paper Trading Dashboard building..."}

@app.get("/workstation")
@app.get("/v2")
async def serve_workstation_dashboard():
    """Serve dedicated SMC Workstation V2."""
    workstation_path = os.path.join(frontend_dir, "smc-workstation-v2.html")
    if not os.path.exists(workstation_path):
        workstation_path = os.path.join(frontend_dir, "SMC_Workstation_V2_offline.html")
    if os.path.exists(workstation_path):
        return FileResponse(workstation_path)
    return {"message": "SMC Workstation V2 building..."}

