# XAUTUSD Dashboard — Version Record

## Current Release

| Field             | Value                                      |
|-------------------|--------------------------------------------|
| **Version**       | v1.0 — Signal-First Baseline               |
| **Git Tag**       | `xautusd-v1.0-baseline`                    |
| **Commit Hash**   | `c502f82c1070a0a77be91bf70ab280635299ba19` |
| **Branch**        | `master`                                   |
| **Tagged**        | 2026-10-13 (IST)                           |
| **Tests**         | 42 / 42 passing                            |

---

## Installation

### Prerequisites
- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) package manager

### Install dependencies
```powershell
# From the project root (C:\Users\tripa\smc-dashboard)
uv sync
uv sync --group dev   # includes pytest
```

### Environment Variables (names only — never commit values)
| Variable              | Default                                    | Purpose                          |
|-----------------------|--------------------------------------------|----------------------------------|
| `DELTA_REST_URL`      | `https://api.india.delta.exchange`         | Delta Exchange India REST base   |
| `DELTA_WS_URL`        | `wss://public-socket.india.delta.exchange` | Delta WebSocket (live feed)      |
| `DELTA_LEGACY_WS_URL` | `wss://socket.india.delta.exchange`        | Delta legacy WebSocket fallback  |
| `DELTA_PRICE_SOURCE`  | `index`                                    | `index` or `mark`                |
| `DELTA_SYMBOL`        | `.DEXAUTUSD`                               | Instrument symbol                |
| `HOST`                | `127.0.0.1`                               | Server bind host                 |
| `PORT`                | `8000`                                     | Server bind port                 |

> **CAUTION:** No API keys are required for public data (candlestick history, index price). If you ever add private endpoints, store keys in a `.env` file that is already listed in `.gitignore`. Never commit secret values.

### Start the server
```powershell
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open browser: **http://127.0.0.1:8000**

### Run tests
```powershell
uv run pytest backend/tests/ -v
```

---

## Project Structure

```
smc-dashboard/
├── backend/
│   ├── app.py                  # FastAPI application, REST + WebSocket endpoints
│   ├── config.py               # All configuration (URLs, symbols, timeframes, TZ)
│   ├── __init__.py
│   ├── adapters/
│   │   ├── base.py             # Abstract adapter interface
│   │   ├── delta_exchange.py   # Delta Exchange India adapter (REST + WS)
│   │   └── __init__.py
│   ├── smc/
│   │   ├── engine.py           # Main SMC analysis orchestrator
│   │   ├── models.py           # Pydantic data models (Candle, TerminalState, etc.)
│   │   ├── activation.py       # Key-level activation, watchlist, AlertStore
│   │   ├── displacement.py     # Displacement / impulse detection
│   │   ├── fvg.py              # Fair Value Gap detection
│   │   ├── liquidity.py        # Equal highs/lows, PDH/PDL, liquidity sweeps
│   │   ├── premium_discount.py # Premium/Discount zone, OTE (0.62–0.79 fib)
│   │   ├── psychological.py    # 20/80 psychological levels
│   │   ├── ranking.py          # Level ranking / prioritization
│   │   ├── structure.py        # Swing structure, BOS, CHoCH, HH/HL/LH/LL
│   │   ├── trendlines.py       # Dynamic trendline detection
│   │   └── __init__.py
│   └── tests/
│       ├── test_activation.py        # AlertStore, watchlist state tests
│       ├── test_audit_signals.py     # Signal audit: no look-ahead, no repainting
│       ├── test_delta_adapter.py     # Candle normalization, deduplication, 24h floor
│       ├── test_enhanced_smc.py      # Structure, displacement, OB, OTE, ranking
│       ├── test_integration.py       # Live Delta Exchange product/candle verification
│       ├── test_setup_lifecycle.py   # Target reached, stop breached, duplicate alerts
│       ├── test_smc_engine.py        # FVG, BOS 40%, liquidity sweep, psychological
│       ├── test_terminal_state.py    # Market bias mixed/directional, risk state
│       └── verify_delta_integration.py  # Manual integration smoke test
├── frontend/
│   ├── index.html              # Single-page app shell
│   ├── app.js                  # All frontend logic (chart, WS, UI state)
│   ├── styles.css              # Dark terminal theme styles
│   └── lightweight-charts.js  # TradingView Lightweight Charts (bundled, v4.x)
├── ALGORITHMS.md               # Detailed SMC algorithm documentation
├── CHANGELOG.md                # Release changelog
├── VERSION.md                  # This file
├── RELEASE_NOTES.md            # Baseline release notes + rollback instructions
├── pyproject.toml              # Python project + dependency declaration (uv)
├── uv.lock                     # Pinned dependency lockfile
├── requirements.txt            # pip-compatible requirements mirror
├── run.ps1                     # PowerShell convenience start script
└── .gitignore                  # Ignores: __pycache__, .venv, .pytest_cache
```

---

## Framework & Libraries

| Layer     | Technology                              | Version Constraint  |
|-----------|-----------------------------------------|---------------------|
| Backend   | Python                                  | ≥ 3.11 (tested 3.12)|
| Backend   | FastAPI                                 | ≥ 0.115.0           |
| Backend   | Uvicorn (ASGI server)                   | ≥ 0.30.0            |
| Backend   | websockets                              | ≥ 13.0              |
| Backend   | httpx (async HTTP)                      | ≥ 0.27.0            |
| Backend   | Pydantic v2                             | ≥ 2.8.0             |
| Backend   | python-dateutil                         | ≥ 2.9.0             |
| Frontend  | Vanilla JavaScript (ES2020+)            | No build step       |
| Frontend  | TradingView Lightweight Charts          | v4.x (bundled)      |
| Frontend  | HTML5 / CSS3                            | Single SPA          |

---

## API Endpoints (v1.0)

| Method | Path                        | Purpose                                              |
|--------|-----------------------------|------------------------------------------------------|
| GET    | `/`                         | Serve frontend SPA                                   |
| GET    | `/api/status`               | Health check, price source, connection status        |
| GET    | `/api/candles`              | Historical candles (`?tf=1H&limit=200`)              |
| GET    | `/api/smc`                  | Full SMC analysis for a timeframe                    |
| GET    | `/api/watchlist`            | Key-level watchlist entries and states               |
| GET    | `/api/alerts`               | Current alert log                                    |
| POST   | `/api/alerts/acknowledge`   | Mark alerts acknowledged                             |
| GET    | `/api/market-state`         | Terminal state (bias, setup state, risk state)       |
| GET    | `/api/config/price-source`  | Current price source (`index` / `mark`)              |
| POST   | `/api/refresh`              | Force resync historical candles                      |
| WS     | `/ws`                       | Live streaming: candle updates + SMC sync            |

---

## Supported Timeframes

`1D`, `4H`, `1H`, `30M`, `15M`, `5M`, `1M`

Default chart timeframe on load: **1H**

Minimum data window guaranteed: **≥ 24 hours** of candle history per timeframe on every fetch.
