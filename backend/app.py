import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Set, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from backend.config import (
    DEFAULT_SYMBOL,
    DEFAULT_PRODUCT_ID,
    INDEX_SYMBOL,
    MARK_SYMBOL,
    PRICE_SOURCE,
    IST_TZ,
)
from backend.adapters.delta_exchange import DeltaExchangeAdapter, MIN_24H_CANDLES, TIMEFRAME_LIMITS
from backend.smc.models import MarketDataStatus, Candle, AnalysisConfig
from backend.smc.engine import SMCEngine

# Initialize adapter & engine
adapter = DeltaExchangeAdapter()
smc_engine = SMCEngine()

# Active WebSocket connections to browser clients
connected_clients: Set[WebSocket] = set()

def broadcast_live_update(timeframe: str, candle: Candle):
    """Callback triggered whenever a forming or confirmed candle updates."""
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: fetch historical candles across all timeframes ensuring at least 24 hours of data
    print(f"Starting SMC Dashboard backend for {DEFAULT_SYMBOL}...")
    await adapter.initialize_all_timeframes(DEFAULT_SYMBOL)
    # Start live WebSocket stream across all timeframes
    await adapter.start_streaming(
        symbol=DEFAULT_SYMBOL,
        timeframes=["1D", "4H", "1H", "30M", "15M", "5M", "1M"],
        on_candle_update=broadcast_live_update
    )
    yield
    # Shutdown
    print("Shutting down SMC Dashboard...")
    await adapter.stop_streaming()

app = FastAPI(title="SMC Key-Level Intelligence Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Endpoints
@app.get("/api/status")
async def get_status(timeframe: str = Query("1H")):
    return get_current_status(timeframe)

@app.get("/api/candles")
async def get_candles(timeframe: str = Query("1H")):
    tf = timeframe.upper()
    candles = adapter.get_candles(tf)
    min_count = MIN_24H_CANDLES.get(tf, 25)
    if len(candles) < min_count:
        candles = await adapter.fetch_historical_candles(
            DEFAULT_SYMBOL, tf, limit=TIMEFRAME_LIMITS.get(tf, 500)
        )
    return {
        "success": True,
        "symbol": DEFAULT_SYMBOL,
        "timeframe": tf,
        "count": len(candles),
        "candles": [c.model_dump() for c in candles]
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

# WebSocket Endpoint for Live Frontend Streaming
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        # Send initial status & sync
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

# Serve Frontend static assets
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def serve_index():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "SMC Dashboard Frontend building..."}
