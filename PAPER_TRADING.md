# XAUTUSD Paper Trading Dashboard (v1.1)

A dedicated, isolated paper-trading simulation and ledger dashboard for XAUTUSD, driven by confirmed Smart Money Concepts (SMC) signals from Delta Exchange India market data.

---

## 1. Safety Boundary & Paper-Only Guarantee

> [!IMPORTANT]
> **NO REAL EXCHANGE ORDERS ARE PLACED OR PLACABLE.**
> - The paper engine code in `backend/paper_trading.py` contains **zero** Delta Exchange private API credentials, API key loading, authentication headers, or order-routing functions.
> - The engine runs strictly against a local SQLite database (`paper_trading.sqlite3`).
> - The original read-only SMC dashboard at `/` remains intact. The paper trading dashboard at `/paper` is fully isolated.

---

## 2. Prerequisites & Quickstart

### Prerequisites
- Python ≥ 3.11 (tested on CPython 3.12.15)
- [`uv`](https://github.com/astral-sh/uv) package manager

### Installation

```powershell
# From the project root
uv sync --group dev
```

### Running the Application

```powershell
# Start local FastAPI backend on port 8000
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

### Accessing the Dashboards

1. **Original SMC Dashboard:** Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.
2. **Accessing Paper Trading:** Click the minimal **Paper Trading →** link located on the header of the main dashboard, or navigate directly to [http://127.0.0.1:8000/paper](http://127.0.0.1:8000/paper).

---

## 3. Simulator Controls & Workflow

The paper engine begins in a safe, **`STOPPED`** state after fresh installation or reset.

### Engine States

| State | Behavior |
|---|---|
| **`STOPPED`** | Inactive. No new entries simulated. |
| **`RUNNING`** | Active. Monitored for confirmed `ACTIVE` SMC setups. Evaluates entry zone, sizes positions, simulates fills, and monitors open positions for SL/TP. |
| **`PAUSED`** | Paused. Blocks **all** new entries. **Existing simulated positions continue to be monitored for Stop-Loss and Take-Profit execution.** |
| **`KILL SWITCH`** | Emergency Stop active. Immediately locks all entry evaluation. Persists across restarts in SQLite. Requires explicit user action (*Clear Stop Lock*) to reset. |

### Available Controls

- **Start Paper Engine (`POST /api/paper/control/start`):** Activates simulation loop. Blocked if Emergency Stop is engaged.
- **Pause (`POST /api/paper/control/pause`):** Temporarily halts new trade entries while continuing mark-to-market monitoring of open positions.
- **Resume (`POST /api/paper/control/resume`):** Restores active entry evaluation from paused state.
- **Stop (`POST /api/paper/control/stop`):** Gracefully stops the engine.
- **Emergency Stop (`POST /api/paper/control/emergency-stop`):** Immediately engages persistent kill switch lock.
- **Clear Stop Lock (`POST /api/paper/control/reset-stop`):** Clears the emergency stop lock. Engine safely defaults to `STOPPED` until manually started.
- **Close All Positions (`POST /api/paper/control/close-all`):** Immediately closes all active paper positions at current market mark price (with slippage and fees).
- **Close Position (`POST /api/paper/positions/{id}/close`):** Closes a specific open paper position from the positions table.
- **Reset Account (`POST /api/paper/control/reset`):** Requires explicit confirmation dialog (`confirm: true`). Wipes all paper orders, positions, trades, and event history, restoring starting equity to $10,000.00.

---

## 4. Execution Rules & Fill Assumptions

### Signal Qualification
Only setups confirmed with state **strictly `ACTIVE`** by the upstream SMC engine are eligible for entry.
- `WATCH`, `PENDING`, `FORMING`, `INVALIDATED`, or unconfirmed signals are rejected.
- Setups with current price outside the entry zone `[bottom, top]` are deferred.
- Setups where target is already reached or levels are inverted (`stop < entry < target` for Long) are rejected.
- Setup IDs are deduplicated: a setup that has already opened a trade cannot open duplicate positions.

### Sizing and Risk Model
Position sizing is dynamically calculated using the account risk budget and invalidation distance:
$$\text{Risk Budget} = \text{Current Equity} \times \text{Risk Fraction} \quad (\text{Default: } \$10,000 \times 0.25\% = \$25)$$
$$\text{Quantity} = \min\left( \frac{\text{Risk Budget}}{|\text{Entry Price} - \text{Stop Loss}|}, \; \frac{\text{Max Notional}}{\text{Market Price}} \right)$$

### Slippage & Fee Models
- **Simulated Entry Slippage:** 5 basis points ($0.05\%$). Added for LONG fills, subtracted for SHORT fills.
- **Simulated Exit Slippage:** 5 basis points ($0.05\%$). Subtracted for LONG exits, added for SHORT exits.
- **Simulated Fees:** 5 basis points ($0.05\%$) taker fee applied to notional value on both entry and exit:
  $$\text{Fee} = \text{Fill Price} \times \text{Quantity} \times 0.0005$$
- **Net P&L:**
  $$\text{Net P&L} = \text{Gross P&L} - \text{Entry Fee} - \text{Exit Fee}$$

---

## 5. Risk Management Defaults

The configuration defaults can be viewed and adjusted via the UI **Risk Settings** modal or `POST /api/paper/config`:

| Parameter | Default | Description |
|---|---|---|
| `starting_equity` | `$10,000.00` | Base simulated virtual equity |
| `risk_fraction` | `0.0025` ($0.25\%$) | Max capital risked per trade based on SL distance |
| `daily_loss_fraction` | `0.01` ($1.0\%$) | Cumulative daily loss threshold that halts the engine |
| `max_positions` | `1` | Max concurrent open paper positions |
| `max_notional` | `$2,500.00` | Maximum notional value cap per single position |
| `max_data_age_seconds` | `60` | Stale market data threshold in seconds |
| `fee_rate` | `0.0005` ($0.05\%$) | Simulated taker fee per fill |
| `slippage_bps` | `5.0` ($0.05\%$) | Simulated slippage in basis points |

---

## 6. Database Location & Backup Instructions

- **Database Path:** Local SQLite file at `backend/paper_trading.sqlite3` (override via `PAPER_DB_PATH` environment variable).
- **WAL Mode:** Write-Ahead Logging (`PRAGMA journal_mode=WAL`) is enabled for safe concurrent reads and transactions.

### Creating a Backup
To back up simulated paper history without stopping the application:

```powershell
# Copy the database and its WAL file
Copy-Item "backend/paper_trading.sqlite3*" "backend/backup_paper_$(Get-Date -Format 'yyyyMMdd_HHmmss').sqlite3"
```

---

## 7. Market Data Limitations & Contract Safety

- **Price Feed:** Delta Exchange India Spot Index (`.DEXAUTUSD`).
- **Notice on Contract Basis:** Spot index prices reflect the underlying gold index. Tradable perpetual futures (`XAUTUSD` or `XAUT-PERP`) may exhibit basis spreads, funding rate premiums/discounts, and distinct minimum lot sizes or contract step values on live Delta Exchange. The paper dashboard clearly labels simulation as approximate.
- **Stale Data Protection:** If the market data timestamp exceeds 60 seconds or the websocket disconnects, the engine halts new entries and logs a stale feed audit event.

---

## 8. Verification & Test Suite

Run the complete automated offline test suite (54 tests):

```powershell
uv run pytest backend/tests/ --ignore=backend/tests/test_integration.py -v
```

All 54 tests pass, covering:
- Only `ACTIVE` setups trigger entries
- Deduplication and idempotency
- Invalidation and level-ordering rejection
- Risk budget & notional caps
- Daily loss limit tripping
- Stop-loss & take-profit execution
- Accurate fee and slippage math
- SQLite restart persistence
- Pause & emergency stop isolation
- Single-execution position close
- Explicit reset confirmation
- Stale data blocking
- Original dashboard backward compatibility
