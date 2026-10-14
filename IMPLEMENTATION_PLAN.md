# MASTER IMPLEMENTATION PLAN
**Project:** Professional SMC Algorithmic Trading Engine  
**Execution Order:** Stage 1 to Stage 11

---

## Stage Breakdown & Milestones

### STAGE 1 — Audit & Baseline Architecture ✅
- [x] Full codebase audit and root-cause analysis of empty signal pipeline.
- [x] Create `AUDIT_REPORT.md`.
- [x] Create `ARCHITECTURE.md`.
- [x] Run baseline test suite (61 tests passed).
- [x] Document instrument economics: XAUTUSD perpetual futures (ID 131253) vs `.DEXAUTUSD` spot index (ID 435).

### STAGE 2 — Market Data Pipeline & Normalization
- [ ] Implement strict UTC candle normalizer with gap, duplicate, and stale detection.
- [ ] Standardize instrument mapping to `XAUTUSD` (0.001 XAUT contract multiplier).
- [ ] Implement bounded exponential-backoff reconnects and connection state machine (`CONNECTED`, `STALE`, `DISCONNECTED`, `INVALID_DATA`, `RECOVERING`).
- [ ] Add unit and integration tests for data health and fail-closed behavior.

### STAGE 3 — Deterministic SMC Strategy Engine
- [ ] **Decouple Strategies**:
  - Implement **Model A (SMC Sweep & Retracement)**: Daily bias, 4H context, confirmed swing sweep, MSS/BOS displacement, retracement entry, structural SL/TP.
  - Implement **Model B (Structural Trendline Break)**: Confirmed pivot construction, minimum touch geometry, breakout/retest validation, independent SL/TP.
- [ ] Implement mathematical 3-candle FVG engine (proximal/distal tracking, mitigation ratio, invalidation).
- [ ] Implement confirmed swing pivot engine with strict zero-repainting guarantees.
- [ ] Write unit tests verifying both models independently.

### STAGE 4 — Central Risk Manager & Discipline Engine
- [ ] Implement Central Risk Engine enforcing:
  - 0.25% single-trade equity risk budget.
  - Exact contract quantity sizing based on `$0.01` tick size, `0.001 XAUT` multiplier, and fees.
  - 1.0% daily loss limit (persisted at 00:00 UTC).
  - 2.5% weekly loss limit (persisted at Monday 00:00 UTC).
  - 5.0% peak-to-trough drawdown circuit breaker.
  - Max 1 active position initially.
  - Minimum 2.0 reward-to-risk requirement.
- [ ] Implement Psychological Discipline Engine:
  - 3-consecutive-loss cooldown lock (4 hours).
  - Anti-revenge trading controls.
  - Hardened state persistence surviving server restarts.

### STAGE 5 — Realistic Execution Simulator
- [ ] Implement realistic execution engine with:
  - Spread and taker commission modeling (0.05%).
  - Adverse slippage (5 bps).
  - Conservative intra-candle tie-breaker (assumes Stop Loss hit first if both SL and TP touched).
  - Partial fill / liquidity bounds simulation.
  - Monotonic stop-loss verification (rejection of stop widening).

### STAGE 6 — Stops, Trailing & Partial Exits
- [ ] Implement true break-even trailing after transaction costs.
- [ ] Implement and test 3 trailing methods: (1) Swing structure, (2) ATR trailing, (3) Hybrid.
- [ ] Implement optional pyramiding module (disabled by default, max 2 additions, strict combined worst-case portfolio risk).

### STAGE 7 — Backtesting Engine & Strategy Laboratory
- [ ] Build historical walk-forward backtesting framework.
- [ ] Implement chronological chronological dataset splits: In-Sample (60%), Validation (20%), Out-of-Sample (20%).
- [ ] Implement Monte Carlo bootstrap simulation (1,000 resamples) for drawdown distribution.
- [ ] Calculate expectancy metrics: Net Expectancy, Profit Factor, Max Drawdown, Sharpe, Sortino.
- [ ] Build Strategy Laboratory comparison runner for Model A vs Model B.

### STAGE 8 — Signal Rejection Inspector & Diagnostics
- [ ] Build Signal Rejection Inspector recording structured failure reasons for every rejected candidate setup.
- [ ] Expose rejection telemetry via REST API and live UI drawer.

### STAGE 9 — Trade Replay & Forensic Audit Journal
- [ ] Implement deterministic point-in-time trade replay engine.
- [ ] Build forensic audit journal recording exact candle state, risk checks, and execution logs.
- [ ] Add CSV export endpoints for trade history and audit events.

### STAGE 10 — UI Integration & Acceptance Verification
- [ ] Update frontend dashboard with:
  - Live data feed health indicator and heartbeat.
  - Model A & Model B active setup cards.
  - Real-time Signal Rejection Inspector drawer.
  - Risk meter (Daily loss, Weekly loss, Drawdown).
  - Replay and laboratory tabs.
- [ ] Run full automated test suite (target: >90 comprehensive tests).
- [ ] Verify Render deployment live sync.

### STAGE 11 — Strategy Validation & Final Evidence Report
- [ ] Execute out-of-sample backtest runs with realistic transaction costs.
- [ ] Evaluate Strategy Promotion Gates (`PASS`, `CONDITIONAL PASS`, `FAIL`, `INSUFFICIENT EVIDENCE`).
- [ ] Publish complete final deliverables: `STRATEGY_SPECIFICATION.md`, `RISK_MANAGEMENT.md`, `EXECUTION_MODEL.md`, `BACKTESTING_METHODOLOGY.md`, `EXPERIMENT_REGISTRY.md`, `TEST_REPORT.md`, `OPERATIONS_RUNBOOK.md`.
