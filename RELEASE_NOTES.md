# XAUTUSD Dashboard v1.0 — Release Notes

**Release:** v1.0 — Signal-First Baseline  
**Tag:** `xautusd-v1.0-baseline`  
**Commit:** `c502f82c1070a0a77be91bf70ab280635299ba19`  
**Branch:** `master`  
**Date:** 2026-10-13  
**Tests:** ✅ 42 / 42 passing

---

## What This Release Contains

A complete, working XAUTUSD trading dashboard connected to **Delta Exchange India** live data.
The dashboard is a read-only monitoring and decision-support tool. It does not place orders.

### Core Capabilities (Verified)

| Feature | Status |
|---------|--------|
| Live XAUTUSD Spot Index price (`.DEXAUTUSD`) | ✅ Verified (live) |
| Historical candles via Delta Exchange REST API | ✅ Verified (live) |
| All timeframes: 1D, 4H, 1H, 30M, 15M, 5M, 1M | ✅ Verified (live) |
| ≥ 24h candle data guaranteed on every load | ✅ Verified (automated test) |
| WebSocket live candle stream | ✅ Verified (live) |
| IST timestamp sync | ✅ Verified (live) |
| FVG detection (bullish + bearish) | ✅ Verified (automated test) |
| BOS / CHoCH market structure | ✅ Verified (automated test) |
| Equal highs/lows (BSL/SSL) | ✅ Verified (automated test) |
| PDH / PDL liquidity levels | ✅ Verified (code-inspected) |
| OTE zone (61.8–78.6% fib) | ✅ Verified (automated test) |
| Psychological 20/80 levels | ✅ Verified (automated test) |
| Liquidity sweep detection | ✅ Verified (automated test) |
| Trendline detection | ✅ Code-inspected, not unit-tested |
| Order Block detection | ✅ Code-inspected (via displacement.py) |
| HTF FVG overlay (1D + 4H) on all timeframes | ✅ Verified (live) |
| 1H FVGs visible only on 1H timeframe | ✅ Verified (code + live) |
| FVG colors: peacock green (bullish), orange (bearish) | ✅ Verified (live) |
| Setup states: WATCH, ACTIVE, EXTREME, INVALIDATED | ✅ Verified (automated test) |
| Target-reached lifecycle (INVALIDATED with reason) | ✅ Verified (automated test) |
| Stop-breached lifecycle | ✅ Verified (automated test) |
| 4H/Daily priority weighting over 1H/15M | ✅ Verified (automated test) |
| Market bias: bullish/bearish/mixed/neutral | ✅ Verified (automated test) |
| Risk/Data state: normal/caution/critical | ✅ Verified (automated test) |
| Focus Setup Mode (TP + SL lines on chart) | ✅ Code-inspected + live |
| Collision-aware price label placement | ✅ Code-inspected |
| Alert deduplication | ✅ Verified (automated test) |
| Separate alert counters (Active/Watch/Risk) | ✅ Code-inspected |
| Signal Summary bar (Bias / Setup / Risk) | ✅ Code-inspected + live |
| Setup card state banners (WATCH/ACTIVE/EXTREME/INVALIDATED) | ✅ Code-inspected + live |
| Timeframe button switching | ✅ Verified (live) |
| Fullscreen chart toggle | ✅ Code-inspected + live |

### Known Limitations / Untested Areas

| Area | Status |
|------|--------|
| Trendline accuracy | Code exists; no unit test |
| Order Block visual rendering | Code exists; no isolated unit test |
| Overlay individual toggle persistence across TF switches | Untested |
| Mobile / small viewport layout | Designed for 1366×768; mobile untested |
| Multiple concurrent browser clients via WebSocket | Basic implementation; load untested |
| Backend auto-reconnect to Delta WebSocket on long disconnect | Code exists; stress untested |
| Index price vs Mark price mid-session switch | Config works; hot-switch not tested |
| 30M timeframe data quality | Not specifically tested |
| R:R calculation when stop = 0 (divide-by-zero guard) | Marked "N/A"; edge case not tested |
| No remote Git remote configured | Local repo only; no GitHub/GitLab push |

---

## Known Bugs

None confirmed at time of v1.0 tag. All 42 tests pass cleanly.

---

## Features That Must Not Regress

1. Live price updates from Delta Exchange India Index (`.DEXAUTUSD`)
2. Timeframe button switching updates the chart correctly
3. 1H FVGs do NOT appear on 5M or 15M charts
4. HTF FVGs (4H + 1D) appear on all timeframes
5. Setup state never promoted to ACTIVE without closed-candle confirmation
6. `is_target_reached = True` → setup shown as INVALIDATED, not ACTIVE
7. AlertStore deduplication prevents repeated notifications for the same event
8. All 42 automated tests continue to pass

---

## Rollback Instructions

### Option A — Safe checkout into a new branch (RECOMMENDED)

```powershell
# Step 1: Preserve any newer work you have
git -C C:\Users\tripa\smc-dashboard stash push -m "work-before-rollback"

# Step 2: Create a new branch from the baseline tag (does NOT touch master)
git -C C:\Users\tripa\smc-dashboard checkout -b rollback/v1.0 xautusd-v1.0-baseline

# Step 3: Start the server from this branch
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

### Option B — Restore into a separate directory (SAFEST, no risk to master)

```powershell
# Step 1: Create a git worktree from the baseline tag
git -C C:\Users\tripa\smc-dashboard worktree add ..\smc-dashboard-v1.0 xautusd-v1.0-baseline

# Step 2: Install dependencies in the worktree
Set-Location ..\smc-dashboard-v1.0
uv sync

# Step 3: Start server from there (use a different port if master is running)
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8001

# Step 4: When done, remove the worktree
git -C C:\Users\tripa\smc-dashboard worktree remove ..\smc-dashboard-v1.0
```

### Option C — Return master to baseline (only if later changes are broken and you want to undo them)

```powershell
# Step 1: Check what changed since v1.0
git -C C:\Users\tripa\smc-dashboard log xautusd-v1.0-baseline..HEAD --oneline

# Step 2: Create a backup branch of the newer work FIRST
git -C C:\Users\tripa\smc-dashboard branch backup/pre-rollback HEAD

# Step 3: Reset master to the baseline (--soft keeps your changes staged, safer)
git -C C:\Users\tripa\smc-dashboard reset --soft xautusd-v1.0-baseline

# OR hard reset (discards uncommitted changes - use only if backup branch exists)
# git -C C:\Users\tripa\smc-dashboard reset --hard xautusd-v1.0-baseline
```

### View the saved version
```powershell
# See tag details
git -C C:\Users\tripa\smc-dashboard show xautusd-v1.0-baseline

# See commit the tag points to
git -C C:\Users\tripa\smc-dashboard rev-parse xautusd-v1.0-baseline
# Expected: c502f82c1070a0a77be91bf70ab280635299ba19
```

### After any rollback — reinstall dependencies
```powershell
uv sync          # restore exact pinned versions from uv.lock
uv sync --group dev  # include test dependencies
```

> ⚠️ **Source rollback does NOT affect:**  
> - Delta Exchange exchange-side data, your account, or any orders  
> - External API state  
> - Any `.env` files or local secrets (these are git-ignored and remain as-is)

---

## Future Versioning Rules

| Version | Meaning | When to Tag |
|---------|---------|-------------|
| **v1.0** | This baseline | ✅ Tagged |
| **v1.1** | Next approved improvement | After tests pass + visual review |
| **v1.2** | Subsequent improvement | After tests pass + visual review |
| **v2.0** | Major redesign or architecture change | After full regression suite passes |

### Before every new feature
1. `git status` — ensure working tree is clean
2. `uv run pytest backend/tests/ -v` — all tests must pass
3. Implement the feature in a branch or directly on master
4. Run tests again — fix any regressions before merging
5. Tag the release: `git tag -a xautusd-vX.Y -m "Description"`

### If a feature fails
- Do not delete master
- Create `backup/` branch of broken state
- Roll back the specific feature commit: `git revert <commit-hash>`
- Or restore known-good baseline with `git worktree` (Option B above)
