import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
import httpx
import websockets

from backend.config import (
    DELTA_REST_URL,
    DELTA_WS_URL,
    DELTA_LEGACY_WS_URL,
    TIMEFRAME_MAP,
    REVERSE_TIMEFRAME_MAP,
    TIMEFRAME_SECONDS,
    IST_TZ,
)
from backend.adapters.base import BaseMarketDataAdapter
from backend.smc.models import Candle

logger = logging.getLogger("DeltaAdapter")
logging.basicConfig(level=logging.INFO)

class DeltaExchangeAdapter(BaseMarketDataAdapter):
    """
    Dedicated Market Data Adapter for Delta Exchange India.
    Connects to official REST API and WebSocket candle stream for XAUTUSD.
    """

    def __init__(self, base_rest_url: str = DELTA_REST_URL, ws_url: str = DELTA_WS_URL):
        self.base_rest_url = base_rest_url.rstrip("/")
        self.ws_url = ws_url
        self.legacy_ws_url = DELTA_LEGACY_WS_URL
        self.connection_status = "Disconnected"
        self.last_successful_update = 0
        self.is_running = False
        self._ws_task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None
        self.use_polling_fallback = False

        # In-memory candle storage: timeframe -> list of confirmed Candle
        self.candles: Dict[str, List[Candle]] = {
            "1D": [],
            "4H": [],
            "1H": [],
            "30M": [],
            "15M": [],
            "5M": [],
            "1M": [],
        }
        # Currently forming candle per timeframe
        self.forming_candles: Dict[str, Optional[Candle]] = {
            "1D": None,
            "4H": None,
            "1H": None,
            "30M": None,
            "15M": None,
            "5M": None,
            "1M": None,
        }

        self.on_update_callbacks: List[Callable[[str, Candle], Any]] = []

    def format_ist(self, ts: int) -> str:
        """Convert unix timestamp in seconds to formatted IST string."""
        return datetime.fromtimestamp(ts, tz=IST_TZ).strftime("%Y-%m-%d %H:%M:%S IST")

    def _normalize_candle(self, raw: dict, is_forming: bool = False) -> Optional[Candle]:
        """Validate and normalize raw candle dictionary to Candle model."""
        try:
            # Handle time field which can be seconds or microseconds
            raw_time = raw.get("time") or raw.get("cst") or raw.get("ts")
            if raw_time is None:
                return None
            
            ts = int(raw_time)
            if ts > 1e14:  # microseconds
                ts = ts // 1_000_000
            elif ts > 1e11:  # milliseconds
                ts = ts // 1_000

            o = float(raw.get("open") or raw.get("o", 0.0))
            h = float(raw.get("high") or raw.get("h", 0.0))
            l = float(raw.get("low") or raw.get("l", 0.0))
            c = float(raw.get("close") or raw.get("c", 0.0))
            v = float(raw.get("volume") or raw.get("v", 0.0))

            # Validation
            if h < l or h < o or h < c or l > o or l > c:
                # Sanity adjustment if tick anomalies occur
                h = max(h, o, c)
                l = min(l, o, c)

            return Candle(
                time=ts,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                is_forming=is_forming,
                ist_time=self.format_ist(ts)
            )
        except Exception as e:
            logger.warning(f"Failed to normalize candle: {raw}, error: {e}")
            return None

    async def fetch_historical_candles(
        self,
        symbol: str = "XAUTUSD",
        timeframe: str = "1H",
        limit: int = 500
    ) -> List[Candle]:
        """
        Fetch genuine historical candles from Delta Exchange India /v2/history/candles.
        Handles pagination, deduplication, and ascending sorting.
        """
        res = TIMEFRAME_MAP.get(timeframe.upper(), timeframe.lower())
        tf_seconds = TIMEFRAME_SECONDS.get(res, 3600)
        
        now = int(time.time())
        # Calculate start timestamp for requested number of candles with a safety margin
        total_span = limit * tf_seconds
        start_time = now - total_span

        url = f"{self.base_rest_url}/v2/history/candles"
        all_raw = []

        # Paginate in chunks if limit > 2000
        chunk_seconds = 2000 * tf_seconds
        curr_start = start_time

        async with httpx.AsyncClient(timeout=15.0) as client:
            while curr_start < now:
                curr_end = min(curr_start + chunk_seconds, now)
                params = {
                    "symbol": symbol,
                    "resolution": res,
                    "start": curr_start,
                    "end": curr_end
                }
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("success") and "result" in data:
                            chunk = data["result"]
                            all_raw.extend(chunk)
                        else:
                            logger.error(f"Delta API returned error for {symbol} {timeframe}: {data}")
                    else:
                        logger.error(f"Delta API HTTP {resp.status_code}: {resp.text}")
                except Exception as e:
                    logger.error(f"Exception fetching historical candles: {e}")
                    break

                curr_start = curr_end + 1

        # Process, deduplicate, validate, sort
        seen_times = set()
        cleaned: List[Candle] = []

        for item in all_raw:
            candle = self._normalize_candle(item, is_forming=False)
            if candle and candle.time not in seen_times:
                seen_times.add(candle.time)
                cleaned.append(candle)

        # Sort chronologically ascending
        cleaned.sort(key=lambda x: x.time)

        # Limit to the requested count
        if len(cleaned) > limit:
            cleaned = cleaned[-limit:]

        self.candles[timeframe.upper()] = cleaned
        self.last_successful_update = int(time.time())
        return cleaned

    async def initialize_all_timeframes(self, symbol: str = "XAUTUSD", limit: int = 500):
        """Fetch historical candles for all supported timeframes."""
        tasks = [
            self.fetch_historical_candles(symbol, tf, limit)
            for tf in ["1D", "4H", "1H", "30M", "15M", "5M", "1M"]
        ]
        await asyncio.gather(*tasks)
        logger.info(f"Initialized all timeframes for {symbol}: "
                    f"1D: {len(self.candles['1D'])}, "
                    f"4H: {len(self.candles['4H'])}, "
                    f"1H: {len(self.candles['1H'])}, "
                    f"30M: {len(self.candles['30M'])}, "
                    f"15M: {len(self.candles['15M'])}, "
                    f"5M: {len(self.candles['5M'])}, "
                    f"1M: {len(self.candles['1M'])}")

    def update_forming_candle(self, timeframe: str, raw_candle: dict):
        """
        Update the currently forming candle from streaming tick or candle feed.
        Finalizes confirmed candle when a new candle boundary is crossed.
        """
        tf = timeframe.upper()
        res = TIMEFRAME_MAP.get(tf, tf.lower())
        tf_secs = TIMEFRAME_SECONDS.get(res, 3600)

        candle = self._normalize_candle(raw_candle, is_forming=True)
        if not candle:
            return

        # Check if the forming candle is for a new candle period compared to existing history
        existing = self.candles.get(tf, [])
        last_confirmed = existing[-1] if existing else None

        if last_confirmed and candle.time > last_confirmed.time:
            # We are forming a candle ahead of the last confirmed
            # If we had a previous forming candle whose start time was before this candle,
            # that previous forming candle is now completed/confirmed!
            prev_forming = self.forming_candles.get(tf)
            if prev_forming and prev_forming.time < candle.time:
                prev_forming.is_forming = False
                existing.append(prev_forming)
                logger.info(f"Finalized confirmed candle for {tf} at {prev_forming.ist_time}")

        self.forming_candles[tf] = candle
        self.last_successful_update = int(time.time())

        # Notify callbacks
        for cb in self.on_update_callbacks:
            try:
                cb(tf, candle)
            except Exception as e:
                logger.error(f"Error in update callback: {e}")

    async def start_streaming(
        self,
        symbol: str = "XAUTUSD",
        timeframes: Optional[List[str]] = None,
        on_candle_update: Optional[Callable[[str, Candle], Any]] = None
    ):
        """Start the WebSocket market-data stream with auto-reconnection and polling fallback."""
        if timeframes is None:
            timeframes = ["1D", "4H", "1H", "30M", "15M", "5M", "1M"]

        if on_candle_update:
            self.on_update_callbacks.append(on_candle_update)

        self.is_running = True
        self._ws_task = asyncio.create_task(self._ws_loop(symbol, timeframes))

    async def _ws_loop(self, symbol: str, timeframes: List[str]):
        """WebSocket listener loop with automatic reconnection and fallback."""
        reconnect_delay = 2.0
        max_reconnect_delay = 30.0
        failure_count = 0

        ws_channels = []
        for tf in timeframes:
            res = TIMEFRAME_MAP.get(tf.upper(), tf.lower())
            ws_channels.append({"name": f"candlestick_{res}", "symbols": [symbol]})
        ws_channels.append({"name": "v2/ticker", "symbols": [symbol]})

        subscribe_payload = {
            "type": "subscribe",
            "payload": {
                "channels": ws_channels
            }
        }

        # Select primary or legacy URL
        target_urls = [self.ws_url, self.legacy_ws_url]
        url_idx = 0

        while self.is_running:
            active_url = target_urls[url_idx % len(target_urls)]
            try:
                self.connection_status = "Reconnecting" if failure_count > 0 else "Connecting"
                logger.info(f"Connecting to Delta WebSocket: {active_url}")

                async with websockets.connect(
                    active_url,
                    ping_interval=20,
                    ping_timeout=15,
                    close_timeout=5
                ) as ws:
                    self.connection_status = "Connected"
                    failure_count = 0
                    reconnect_delay = 2.0
                    self.use_polling_fallback = False
                    logger.info("Delta WebSocket connected successfully.")

                    # Send subscriptions
                    await ws.send(json.dumps(subscribe_payload))
                    logger.info(f"Subscribed to channels for {symbol}")

                    # After reconnection, re-sync the latest candles to prevent gaps
                    await self.initialize_all_timeframes(symbol, limit=50)

                    while self.is_running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        msg_type = data.get("type", "")

                        if msg_type.startswith("candlestick_"):
                            res = data.get("res") or msg_type.replace("candlestick_", "")
                            tf = REVERSE_TIMEFRAME_MAP.get(res, res.upper())
                            self.update_forming_candle(tf, data)
                        elif msg_type == "v2/ticker" or "mark_price" in data or "close" in data:
                            # Ticker update can be used to update the close of forming candles
                            close_val = data.get("close") or data.get("mark_price")
                            if close_val:
                                for tf in ["30M", "1H", "4H", "1D"]:
                                    forming = self.forming_candles.get(tf)
                                    if forming:
                                        forming.close = float(close_val)
                                        forming.high = max(forming.high, forming.close)
                                        forming.low = min(forming.low, forming.close)
                                self.last_successful_update = int(time.time())

            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                failure_count += 1
                logger.warning(f"WebSocket disconnected ({e}). Retrying in {reconnect_delay}s...")
                self.connection_status = "Reconnecting"
                url_idx += 1  # Try other endpoint on next try

                # If 3 consecutive failures occur, engage polling fallback
                if failure_count >= 3 and not self.use_polling_fallback:
                    self.use_polling_fallback = True
                    self.connection_status = "Polling Fallback"
                    logger.info("Engaging REST polling fallback...")
                    if not self._poll_task or self._poll_task.done():
                        self._poll_task = asyncio.create_task(self._poll_fallback_loop(symbol, timeframes))

                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)

    async def _poll_fallback_loop(self, symbol: str, timeframes: List[str]):
        """REST polling fallback loop if WebSocket is disrupted."""
        logger.info("Starting REST polling fallback loop (interval: 15s)...")
        while self.is_running and self.use_polling_fallback:
            try:
                for tf in timeframes:
                    await self.fetch_historical_candles(symbol, tf, limit=10)
                self.last_successful_update = int(time.time())
                self.connection_status = "Polling Fallback"
            except Exception as e:
                logger.error(f"Error in polling fallback: {e}")
            await asyncio.sleep(15)

    async def stop_streaming(self):
        """Stop streaming and cleanup tasks."""
        self.is_running = False
        self.connection_status = "Disconnected"
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        logger.info("Delta adapter streaming stopped.")

    def get_connection_status(self) -> str:
        """Return the current connection status."""
        # Check staleness: if no update in > 45 seconds while running
        if self.connection_status == "Connected" and (time.time() - self.last_successful_update > 45):
            return "Delayed"
        return self.connection_status

    def get_candles(self, timeframe: str) -> List[Candle]:
        """Return full candle series including current forming candle."""
        tf = timeframe.upper()
        confirmed = list(self.candles.get(tf, []))
        forming = self.forming_candles.get(tf)
        if forming:
            # If forming candle has newer timestamp than last confirmed, append it
            if not confirmed or forming.time > confirmed[-1].time:
                confirmed.append(forming)
            elif confirmed and forming.time == confirmed[-1].time:
                # Replace last candle with updated forming values
                confirmed[-1] = forming
        return confirmed
