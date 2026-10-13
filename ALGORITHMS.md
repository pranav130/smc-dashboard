# SMC Gold Intelligence Dashboard — Algorithm Reference & Specification

## 1. Overview & Data Provenance

* **Verified Instrument:** `XAUTUSD` (Tether Gold Perpetual Futures)
* **Product ID:** `131253` on Delta Exchange India (`api.india.delta.exchange`)
* **Underlying Commodity:** Physical Gold (1 XAUT = 1 fine troy ounce of gold held in Swiss vaults)
* **Contract Specification:** 0.001 XAUT per contract, quoted & settled in USD, tick size $0.01
* **Disclosed Basis:** Delta perpetual mark trades ~0.06%–0.18% above TradingView spot gold (`XAUUSD`) due to perpetual funding basis. Disclosed in UI.
* **Database Support:** Local filesystem/in-memory cache default; PostgreSQL at `E:\PostGres` available for historical multi-year backtesting and persistent trade logs.

---

## 2. Integrated SMC Algorithms

### 2.1 Swing Highs & Swing Lows (Fractal Window)
* **Formula:** A bar whose high (low) is strictly greater (lower) than the $N$ bars on each side ($N=3$ default).
* **Zero Lookahead Guarantee:** A swing at `pivot_idx` is **only knowable** at `confirm_idx = pivot_idx + N`. All downstream consumers use `confirm_time` rather than `pivot_time`.
* **Classification:**
  * **HH (Higher High):** Current confirmed swing high > previous confirmed swing high.
  * **LH (Lower High):** Current confirmed swing high < previous confirmed swing high.
  * **HL (Higher Low):** Current confirmed swing low > previous confirmed swing low.
  * **LL (Lower Low):** Current confirmed swing low < previous confirmed swing low.

### 2.2 Market Structure (BOS & CHoCH)
* **Trend State Machine:**
  * Bullish: Last swing high is HH AND last swing low is HL.
  * Bearish: Last swing high is LH AND last swing low is LL.
  * Undetermined: Mixed structure.
* **Break of Structure (BOS):**
  * Continuation break: Bullish trend breaks above last swing high, or Bearish trend breaks below last swing low.
  * **User's Retracement Rule:** BOS is **valid ONLY if prior retracement $\ge 40\%$** of the impulse leg before the break.
* **Change of Character (CHoCH / MSS):**
  * Reversal break: Bullish trend closes below last swing low, or Bearish trend closes above last swing high. Flips prevailing structural trend.

### 2.3 Fair Value Gaps (FVG) & Critical Sections
* **Bullish FVG:** $\text{Low}(C_2) > \text{High}(C_0)$ with bullish displacement on $C_1$.
* **Bearish FVG:** $\text{High}(C_2) < \text{Low}(C_0)$ with bearish displacement on $C_1$.
* **Equilibrium (50% Midpoint POI):** $\text{Midpoint} = \frac{\text{Top} + \text{Bottom}}{2}$.
* **Mitigation States:**
  1. `unmitigated`: Untouched.
  2. `partial_50`: Price retraces into the gap and tests the 50% midpoint.
  3. `fully_mitigated`: Price traverses completely through the gap boundaries.
* **Inversion FVG:** When price closes fully beyond the gap, the zone flips role (e.g., Bullish FVG becomes resistance).
* **Critical Section / POI:** Spatial overlap of Daily and 4H FVGs.

### 2.4 Order Blocks (Strict ICT Definition)
* **Definition:** The last opposite-colour candle immediately preceding the displacement leg that produced a confirmed BOS or CHoCH.
* **Knowability:** Known only at the bar where the structure break is confirmed.
* **Breaker Block:** If price closes fully through the order block zone, its role flips (e.g., Bullish OB demand becomes Bearish Breaker resistance).

### 2.5 Displacement Detection
* A candle whose body $|Close - Open| \ge 1.5 \times ATR(14)$. Evaluated progressively without future lookahead.

### 2.6 Premium / Discount & Optimal Trade Entry (OTE)
* **Dealing Range:** Last confirmed swing low to last confirmed swing high.
* **Equilibrium:** 50% midpoint of the dealing range.
* **Premium:** Upper 50% of the dealing range (favorable for sell-side analysis).
* **Discount:** Lower 50% of the dealing range (favorable for buy-side analysis).
* **OTE Zone:** $62\% \text{ to } 79\%$ Fibonacci retracement band of the most recent impulse leg.

### 2.7 Liquidity Levels & Sweeps
* **PDH / PDL:** Previous Day High / Low from confirmed daily candles.
* **PWH / PWL:** Previous Week High / Low from previous 7 daily candles.
* **EQH / EQL:** Equal Highs / Lows clustered within $\text{Tolerance} = 0.3 \times ATR(14)$.
* **Liquidity Sweep (LS):** High/Low wicks beyond the level, but candle closes back within the boundary.

### 2.8 Multi-Touch Trendlines (1H & 30M)
* Requires minimum 2 confirmed swing anchors.
* Third touch or more reinforces line validity.
* Breakout confirmed only by candle close through the line (not just wick pierce).

### 2.9 Psychological Round Numbers
* Static institutional levels ending in 20 and 80 (e.g. $4,120, $4,180, $4,220).

### 2.10 Key Level Ranking System
* Multi-factor scoring prioritizing:
  1. Higher Timeframe authority (1D > 4H > 1H > 30M)
  2. Freshness & mitigation state
  3. Confluence (overlap with round numbers, order blocks, FVG midpoints)
  4. Proximity to current spot/mark price
* Includes transparent human-readable justification for each score.

---

## 3. Disclaimers & Discretionary Usage
* This software is purely an analytical decision-support tool.
* It displays verified mathematical levels and descriptive market states.
* It does not execute automated trades, recommend orders, or guarantee market outcomes.
