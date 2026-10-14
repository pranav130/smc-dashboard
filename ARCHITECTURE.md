# PROFESSIONAL SMC ALGORITHMIC TRADING SYSTEM ARCHITECTURE
**Target Instrument:** XAUTUSD (Tether Gold Perpetual Futures, Delta Exchange India)  
**Primary Execution:** 1H Signal Timeframe | Context: 1D & 4H Structure | Execution Mode: Strict Paper Trading

---

## 1. High-Level Architectural Principles

1. **Deterministic & Mathematically Rigorous**: No vague or subjective chart annotations. Every swing pivot, Fair Value Gap (FVG), Market Structure Shift (MSS/CHOCH), and liquidity sweep is computed via explicit algorithmic formulas with zero repainting.
2. **Fail-Closed Safety**: If market data is stale (>60s), malformed, or disconnected, or if risk budgets cannot be verified, the engine immediately transitions to `HALTED` or `DEGRADED`, blocking all new simulated entries while preserving protective stops on open positions.
3. **Decoupled Strategy Pipelines**: Model A (SMC Liquidity Sweep & Retracement) and Model B (Structural Trendline Breakout) operate as distinct, independently backtested, and audited strategy modules with separate performance attribution.
4. **Authoritative Backend State**: Frontend dashboards (Terminal and Paper Trading) are strictly presentation views communicating via authenticated REST and WebSockets; all order sizing, fills, stops, and P&L calculations occur authoritatively on the backend.
5. **Durable Point-in-Time Persistence**: Every trading decision, signal evaluation, and risk check is logged with full point-in-time configuration snapshots to support 100% reproducible forensic trade replay.

---

## 2. Component Architecture

```
smc-dashboard/
├── backend/
│   ├── adapters/
│   │   ├── base.py                   # Market data abstract interface
│   │   └── delta_exchange.py         # Delta Exchange India REST + WS adapter (UTC normalizer)
│   ├── config.py                     # Central validated environment & instrument specifications
│   ├── smc/
│   │   ├── models.py                 # Pydantic v2 domain models for candles, levels, setups
│   │   ├── structure.py              # Swing pivots, BOS, MSS, Dealing ranges, Premium/Discount
│   │   ├── fvg.py                    # 3-candle FVG identification, mitigation, and tracking
│   │   ├── liquidity.py              # Swing liquidity, equal highs/lows, PDH/PDL detection
│   │   ├── trendlines.py             # Geometric trendline construction and validated breaks
│   │   ├── displacement.py           # Volume/ATR displacement candle confirmation
│   │   ├── strategies/
│   │   │   ├── model_a_sweep.py      # Independent Model A: SMC Sweep & Retracement
│   │   │   └── model_b_trendline.py  # Independent Model B: Structural Trendline Break
│   │   ├── signal_machine.py         # Signal lifecycle state machine & Rejection Inspector
│   │   └── engine.py                 # Unified multi-timeframe analysis orchestrator
│   ├── risk/
│   │   ├── manager.py                # Central risk validator (0.25% risk, 1% daily, 2.5% weekly, 5% DD)
│   │   └── discipline.py             # Cooldown manager, loss streaks, revenge trading circuit breaker
│   ├── execution/
│   │   ├── simulator.py              # Realistic paper execution (spread, slippage, fees, tie-breaker)
│   │   └── ledger.py                 # Unified persistent SQLite/WAL accounting ledger
│   ├── backtesting/
│   │   ├── engine.py                 # Historical walk-forward backtest simulator
│   │   ├── metrics.py                # Expectancy, Sharpe, Sortino, Drawdown, Monte Carlo analytics
│   │   └── laboratory.py             # Strategy comparison, parameter sensitivity, out-of-sample gate
│   ├── replay/
│   │   └── forensics.py              # Bar-by-bar deterministic trade replay & journal
│   └── app.py                        # FastAPI production web server, routes, and lifespan manager
├── frontend/
│   ├── index.html                    # Institutional SMC Terminal Dashboard
│   ├── app.js                        # Terminal controller & TradingView Lightweight Charts
│   ├── paper.html                    # Dedicated 24/7 Paper Trading Command Center
│   ├── paper.js                      # Paper trading controller, live ledger, and rejection inspector
│   └── styles.css / paper.css        # High-contrast institutional dark & light themes
```

---

## 3. Instrument Economics: XAUTUSD Perpetual Futures

Delta Exchange India lists two distinct gold assets. The system explicitly standardizes on the tradable perpetual futures contract:

| Property | Value | Architectural Impact |
| :--- | :--- | :--- |
| **Trading Symbol** | `XAUTUSD` | Primary instrument for execution, orders, and paper ledger |
| **Product ID** | `131253` | Delta Exchange contract identifier |
| **Contract Type** | `perpetual_futures` | Inverse/linear perpetual derivative with funding rate |
| **Contract Multiplier** | `0.001 XAUT` | 1 contract = 0.001 troy oz (at $4,100 gold, 1 contract = $4.10 notional) |
| **Underlying Asset** | Tether Gold (`XAUT`) | Physically backed gold token |
| **Quote & Settlement** | `USD` | Account balance and P&L calculated in USD |
| **Tick Size** | `$0.01` | Minimum price increment for order validation and rounding |
| **Benchmark Index** | `.DEXAUTUSD` (ID: 435) | Spot gold benchmark referenced exclusively for basis calculations |
| **Simulated Taker Fee** | `0.05%` (5 bps) | Applied at entry and exit notional value |
| **Simulated Slippage** | `5 bps` ($0.05/contract) | Modeled adverse price slippage on market executions |

---

## 4. Signal State Machine

Signals advance through explicit, deterministic lifecycle states with full audit logging:

```
[ CANDIDATE ]  --> SMC Criteria Detected (Bias + Level + Reaction)
      |
      v
[ CONFIRMED ]  --> Structural Confirmation (Displacement or Validated Break)
      |
      v
[   ACTIVE  ]  --> Passed All Central Risk Limits & Retracement Zone Entry Triggered
      |
      v
[  CONSUMED ]  --> Executed into Paper Position
```

### Alternative Terminal States:
- **`INVALIDATED`**: Structural invalidation price violated before trigger.
- **`EXPIRED`**: Max allowed time in zone elapsed or price moved past target without filling.
- **`REJECTED`**: Denied by Central Risk Manager, Stale Feed check, or Psychological Discipline lock. Every rejection records explicit telemetry in the **Signal Rejection Inspector**.

---

## 5. Central Risk Management Specifications

1. **Single-Trade Risk Budget**:
   $$\text{Risk Budget} = \text{Current Equity} \times 0.0025 \quad (0.25\%)$$
2. **Position Sizing Formula**:
   $$\text{Loss Per Contract} = |\text{Planned Entry} - \text{Stop Loss}| \times \text{Multiplier} + \text{Estimated Costs}$$
   $$\text{Order Quantity (Contracts)} = \left\lfloor \frac{\text{Risk Budget}}{\text{Loss Per Contract}} \right\rfloor$$
   *Bounded by:* Max notional ($2,500) and available free margin.
3. **Loss Limits & Circuit Breakers**:
   - **Daily Loss Limit**: 1.0% of Start-of-Day Equity. Breaching halts new entries until next UTC day (00:00 UTC).
   - **Weekly Loss Limit**: 2.5% of Start-of-Week Equity. Breaching halts new entries until next Monday 00:00 UTC.
   - **Peak-to-Trough Drawdown**: 5.0% maximum allowed drawdown. Breaching engages a persistent Emergency Lock requiring manual review.
   - **Consecutive Loss Cooldown**: 3 consecutive losses triggers a mandatory 4-hour evaluation cooldown.

---

## 6. Execution Simulator & Tie-Breaker Logic

When simulating historical bar fills or processing live bar closures where High and Low both span key levels:
- **Conservative Tie-Breaker**: If a single candle's range touches both Stop Loss and Take Profit, the simulator **strictly assumes Stop Loss was hit first**, recording a loss. Favorable execution is never assumed.
- **Slippage Modeling**:
  $$\text{Fill Price}_{\text{Long}} = \text{Trigger Price} \times (1 + \text{Slippage Rate})$$
  $$\text{Fill Price}_{\text{Short}} = \text{Trigger Price} \times (1 - \text{Slippage Rate})$$
- **Protective Stop Monotonicity**: Stop Loss levels may only move in the risk-reducing direction (closer to market). Any order attempting to widen a stop is rejected by the risk engine.
