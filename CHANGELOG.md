# Changelog

All notable changes to the XAUTUSD SMC Dashboard are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [v1.0] — 2026-10-13 — Signal-First Baseline

**Tag:** `xautusd-v1.0-baseline`  
**Commit:** `c502f82c1070a0a77be91bf70ab280635299ba19`  
**Tests:** 42 / 42 passing

This is the first stable, fully documented release. All features listed below were verified
through code inspection and the automated test suite. Live behavior was confirmed during
active development sessions.

---

### Added

#### Infrastructure
- `uv`-based Python environment management (`pyproject.toml`, `uv.lock`)
- FastAPI + Uvicorn ASGI backend serving frontend via `StaticFiles`
- WebSocket endpoint (`/ws`) for real-time candle + SMC sync push to browser
- `.gitignore` excluding `.venv`, `__pycache__`, `.pytest_cache`
- `run.ps1` convenience start script

#### Data Integration
- **Delta Exchange India adapter** (`backend/adapters/delta_exchange.py`)
  - REST: historical OHLCV candles via `/v2/history/candles`
  - WebSocket: live candle streaming via Delta public socket
  - Candle normalization: handles seconds-epoch and microseconds-epoch timestamps
  - Deduplication and sorting of candle arrays
  - Minimum 24-hour data guarantee: fetches additional pages until ≥ 24h window is satisfied
  - Forming (provisional) candle cleared on historical resync to prevent look-ahead bias
- **Price source:** Delta Exchange Spot Index (`.DEXAUTUSD`, product ID 435)
  - Configurable: switch to Mark price (`XAUTUSD`, product ID 131253) via `DELTA_PRICE_SOURCE=mark`
- **IST timezone:** all timestamps localized to Asia/Kolkata (UTC+05:30) and synced to system clock

#### SMC Analytics Engine
- **FVG detection** (`fvg.py`): bullish and bearish Fair Value Gaps with midpoint calculation, partial/full mitigation tracking, closed-candle confirmation only (no look-ahead)
- **Market structure** (`structure.py`): swing highs/lows with N-bar confirmation offset, HH/HL/LH/LL classification, BOS (Break of Structure) and CHoCH (Change of Character) with 40% body rule
- **Displacement** (`displacement.py`): impulse/displacement candle detection for Order Block sourcing
- **Liquidity analysis** (`liquidity.py`): Equal Highs (BSL), Equal Lows (SSL), PDH (Previous Day High), PDL (Previous Day Low), liquidity sweep detection
- **Premium/Discount zones** (`premium_discount.py`): equilibrium (50%), OTE zone (61.8–78.6% Fibonacci retracement)
- **Psychological levels** (`psychological.py`): 20/80 round-number levels
- **Level ranking** (`ranking.py`): multi-factor scoring for zone prioritization
- **Trendlines** (`trendlines.py`): dynamic swing-point trendline detection
- **Key-Level Activation & Watchlist** (`activation.py`):
  - 7 rule-based watchlist states: `INACTIVE`, `APPROACHING`, `AT_KEY_LEVEL`, `REACTION_DEVELOPING`, `SETUP_TO_INSPECT`, `CHECKLIST_REVIEW`, `TRADE_READY`
  - `AlertStore`: event deduplication with cooldown, stale-feed suppression
- **Multi-timeframe SMC engine** (`engine.py`):
  - HTF FVG analysis: 1D + 4H computed separately and overlaid
  - `TF_WEIGHTS` priority: 1D = 1.5, 4H = 1.2, 1H = 1.0, 15M/5M/1M = 0.8
  - Setup states: `WATCH`, `ACTIVE`, `EXTREME`, `INVALIDATED`
  - `is_target_reached` and `is_stop_breached` lifecycle checks preventing stale setups
  - R:R marked `"N/A"` when target already reached or stop already breached
  - EXTREME escalation: requires confirmed ACTIVE state (not just WATCH)
  - Market bias: `bullish`, `bearish`, `mixed`, `neutral` based on HTF structure consensus
  - Risk/data state: `normal`, `caution`, `critical` based on data freshness and feed health

#### Frontend UI
- **Dark institutional terminal theme** (near-black/navy, teal bullish, red bearish, amber watch, grey inactive)
- **Compact header**: instrument name, live Index price, source timestamp, connection pill (LIVE / DELAYED / DISCONNECTED), collapse button for Details metadata
- **Signal summary bar**: Market Bias, Setup State, Risk/Data State with timeframe arrows (1D, 4H, 1H, 15M)
- **Active Setup Card** with state-specific banners:
  - WATCH: amber banner "Waiting for confirmation"
  - ACTIVE: teal banner "Setup confirmed"
  - EXTREME: purple banner "Extreme confluence"
  - INVALIDATED: red banner with specific reason
  - `directional-context-tag` (LONG/SHORT) framed as context, not entry instruction
  - `is_target_reached` displayed when setup is expired
- **Chart** (TradingView Lightweight Charts v4.x):
  - Candlestick chart with OHLCV, zoom, pan, crosshair, price scale, time scale
  - Default timeframe: 1H; timeframe buttons: 1D, 4H, 1H, 30M, 15M, 5M, 1M
  - Working timeframe button switching (currentTf state managed correctly)
  - ≥ 24h data for all timeframes on load
- **Chart Overlays** (individually toggleable via Overlays popover):
  - HTF FVGs (1D + 4H): Bullish = peacock green, Bearish = orange
  - 1H FVGs: lighter colors, shown only on 1H timeframe (not bleed into 5M/15M)
  - Current-TF FVGs shown on all timeframes
  - Order Blocks, PDH/PDL, Equal Highs/Lows, Trendlines, Swing Structure markers (BOS/CHoCH), OTE zone, Liquidity levels, 20/80 levels
  - **Focus Setup Mode** toggle: emphasizes active setup's POI zone, TP line, SL line; fades secondary overlays
- **Collision-aware price axis labels**: 1.20 USD threshold prevents overlapping labels on price scale
- **Crosshair legend**: distinguishes `[HISTORICAL]` candle OHLC from `[LATEST]` candle
- **Alert Drawer** (collapsible sidebar):
  - Separate badge counters: ACTIVE setups, WATCH setups, Risk/Data events
  - Three micro-badges on collapsed rail
  - Alert deduplication by `category_message` key; category-colored borders
- **Overlay controls in chart toolbar**: Focus Setup, Overlays menu, Fullscreen

---

### Fixed (during v1.0 development cycle)
- Timeframe button switching: `currentTf` was not updating correctly → fixed
- Look-ahead bias: forming candle cleared on historical resync
- 1H FVGs bleeding into 5M/15M → restricted to 1H timeframe only
- Target-already-reached logic: LONG invalidated when `current_price >= target_price`
- Focus Target appearing on wrong timeframes when Focus Mode is OFF → fixed
- Duplicate WebSocket events causing repeated signal triggers → suppressed via AlertStore cooldown
- Chart timestamps out of sync with system clock → fixed via IST localization

---

### Tests Added (42 total)

| File | Tests | Coverage |
|------|-------|----------|
| `test_activation.py` | 6 | Watchlist states, AlertStore dedup, stale suppression |
| `test_audit_signals.py` | 8 | Closed-candle confirmation, WATCH→ACTIVE, WATCH→INVALIDATED, EXTREME escalation, duplicate events, stale feed, forming candle resync |
| `test_delta_adapter.py` | 5 | Candle normalization (seconds + microseconds epoch), dedup+sort, 24h floor |
| `test_enhanced_smc.py` | 6 | Swing confirmation no-lookahead, HH/HL/trend, BOS/CHoCH, displacement+OB, OTE, level ranking |
| `test_integration.py` | 2 | Live Delta product verification, live candles all timeframes |
| `test_setup_lifecycle.py` | 6 | Target reached (long+short), stop breached, price outside entry zone, duplicate alert suppression, HTF priority weighting |
| `test_smc_engine.py` | 6 | Bullish FVG+midpoint, FVG mitigation, BOS 40% rule, liquidity sweep, psychological levels, zero look-ahead bias |
| `test_terminal_state.py` | 3 | Market bias mixed/directional, risk state stale/normal, alert actionable filtering |

---

## [Upcoming]

### [v1.1] — Planned
- _Not yet defined. To be added after v1.0 acceptance._

---

## Version Numbering

| Segment | Meaning |
|---------|---------|
| **v1.x** | v1.0 baseline and incremental improvements |
| **v1.1** | First approved improvement release |
| **v2.0** | Major redesign or architectural change |
