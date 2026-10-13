"""
Market structure: swing detection, HH/HL/LH/LL labeling, BOS and CHoCH detection.

Key design principles (from smc-backtester/detectors/structure.py algorithm,
ported to our pure-Python Candle model — NO pandas/numpy dependency):

* Swing high at pivot_idx is only KNOWN at confirm_idx = pivot_idx + window.
  Every consumer must use confirm_time (= candles[confirm_idx].time) when
  deciding WHAT WAS KNOWN AT THAT MOMENT. This prevents lookahead bias.
* HH/HL/LH/LL labels compare each confirmed swing against the previous
  confirmed swing of the same type.
* Trend: bullish = last swing high is HH AND last swing low is HL;
          bearish = last swing high is LH AND last swing low is LL;
          otherwise undetermined (carries previous trend label).
* BOS:   trend-continuation break. Bullish trend: close > last swing high.
          Bearish trend: close < last swing low.
* CHoCH: trend-reversal break (Change of Character / Market Structure Shift).
          Bullish trend: close < last swing low (bearish CHoCH).
          Bearish trend: close > last swing high (bullish CHoCH).
* Retracement filter (user's rule): BoS only valid when retracement >= 40%.

Attribution: Algorithm inspired by smc-backtester/detectors/structure.py
(no LICENSE file — used as algorithmic reference only, not copied verbatim).
"""
from typing import List, Optional, Tuple
from backend.smc.models import (
    Candle, SwingPoint, BreakOfStructure, TrendState, AnalysisConfig
)


# ---------------------------------------------------------------------------
# ATR helper (pure Python, 14-period)
# ---------------------------------------------------------------------------

def _atr(candles: List[Candle], period: int = 14) -> float:
    """Simple ATR calculation — no numpy dependency."""
    if len(candles) < 2:
        return 1.0
    trs = []
    for i in range(1, len(candles)):
        prev_close = candles[i - 1].close
        c = candles[i]
        tr = max(
            c.high - c.low,
            abs(c.high - prev_close),
            abs(c.low - prev_close)
        )
        trs.append(tr)
    relevant = trs[-period:] if len(trs) >= period else trs
    return sum(relevant) / len(relevant) if relevant else 1.0


# ---------------------------------------------------------------------------
# Swing detection with confirmation offset
# ---------------------------------------------------------------------------

def find_swings(
    candles: List[Candle],
    timeframe: str,
    window: int = 3
) -> List[SwingPoint]:
    """
    Find confirmed swing highs/lows using symmetrical N-bar window.
    
    confirm_idx = pivot_idx + window  (first bar at which the swing is knowable).
    SwingPoint.confirm_time = candles[confirm_idx].time
    SwingPoint.time = candles[pivot_idx].time  (the actual swing price bar)
    
    Returned list is sorted by confirm_time (ascending) — the chronological
    order in which each swing became KNOWN.
    
    HH/HL/LH/LL labels are assigned on the fly as each swing is confirmed.
    """
    n = len(candles)
    if n < (window * 2 + 1):
        return []

    last_confirmed_high: Optional[float] = None
    last_confirmed_low: Optional[float] = None
    swings: List[SwingPoint] = []

    # We can only detect swings at pivot indices window … n-window-1
    # (need window bars on each side)
    for pivot_idx in range(window, n - window):
        c_pivot = candles[pivot_idx]
        high_val = c_pivot.high
        low_val = c_pivot.low
        confirm_idx = pivot_idx + window  # first bar at which this is knowable
        c_confirm = candles[confirm_idx]
        # Prevent premature swings: confirmation candle must be closed
        if c_confirm.is_forming:
            continue

        # --- Swing High ---
        is_sh = all(
            candles[pivot_idx - k].high < high_val and candles[pivot_idx + k].high < high_val
            for k in range(1, window + 1)
        )
        if is_sh:
            label = ""
            if last_confirmed_high is not None:
                label = "HH" if high_val > last_confirmed_high else "LH"
            last_confirmed_high = high_val
            swings.append(SwingPoint(
                time=c_pivot.time,
                confirm_time=c_confirm.time,
                ist_time=c_pivot.ist_time,
                price=round(high_val, 2),
                type="high",
                timeframe=timeframe,
                label=label
            ))

        # --- Swing Low ---
        is_sl = all(
            candles[pivot_idx - k].low > low_val and candles[pivot_idx + k].low > low_val
            for k in range(1, window + 1)
        )
        if is_sl:
            label = ""
            if last_confirmed_low is not None:
                label = "HL" if low_val > last_confirmed_low else "LL"
            last_confirmed_low = low_val
            swings.append(SwingPoint(
                time=c_pivot.time,
                confirm_time=c_confirm.time,
                ist_time=c_pivot.ist_time,
                price=round(low_val, 2),
                type="low",
                timeframe=timeframe,
                label=label
            ))

    # Sort by confirm_time so callers process them in the order they became known
    swings.sort(key=lambda s: (s.confirm_time, s.time))
    return swings


# ---------------------------------------------------------------------------
# Trend state machine
# ---------------------------------------------------------------------------

def get_trend_state(swings: List[SwingPoint]) -> TrendState:
    """
    Derive structural trend from the last labeled swing high and low.
    Bullish: last SH is HH AND last SL is HL.
    Bearish: last SH is LH AND last SL is LL.
    Otherwise undetermined.
    """
    highs = [s for s in swings if s.type == "high" and s.label in ("HH", "LH")]
    lows  = [s for s in swings if s.type == "low"  and s.label in ("HL", "LL")]

    last_h = highs[-1] if highs else None
    last_l = lows[-1]  if lows  else None

    if last_h and last_l:
        if last_h.label == "HH" and last_l.label == "HL":
            trend = "bullish"
            desc = (
                f"Bullish structure: HH at ${last_h.price:.2f}, HL at ${last_l.price:.2f}. "
                "Price is making higher highs and higher lows."
            )
        elif last_h.label == "LH" and last_l.label == "LL":
            trend = "bearish"
            desc = (
                f"Bearish structure: LH at ${last_h.price:.2f}, LL at ${last_l.price:.2f}. "
                "Price is making lower highs and lower lows."
            )
        else:
            trend = "undetermined"
            desc = (
                f"Mixed structure: Last swing high is {last_h.label} (${last_h.price:.2f}), "
                f"last swing low is {last_l.label} (${last_l.price:.2f}). Trend undetermined."
            )
    else:
        trend = "undetermined"
        desc = "Insufficient confirmed swings to determine trend."

    return TrendState(
        trend=trend,
        last_swing_high=last_h.price if last_h else None,
        last_swing_low=last_l.price if last_l else None,
        last_swing_high_time=last_h.time if last_h else None,
        last_swing_low_time=last_l.time if last_l else None,
        description=desc
    )


# ---------------------------------------------------------------------------
# BOS + CHoCH detection
# ---------------------------------------------------------------------------

def calculate_bos(
    candles: List[Candle],
    swings: List[SwingPoint],
    timeframe: str,
    config: Optional[AnalysisConfig] = None
) -> List[BreakOfStructure]:
    """
    Detect Break of Structure (BoS) and Change of Character (CHoCH).
    
    - BoS: trend-continuation break (close beyond last swing IN trend direction).
    - CHoCH: trend-reversal break (close beyond last swing AGAINST trend direction).
    - User rule: BoS only VALID when prior retracement >= 40%.
      CHoCH is always valid (it signals a potential reversal regardless).
    
    Lookahead safety: we only look at candles AFTER confirm_time of each swing.
    """
    if config is None:
        config = AnalysisConfig()

    bos_list: List[BreakOfStructure] = []
    if len(swings) < 2 or len(candles) < 5:
        return bos_list

    # Build time → candle index map
    time_to_idx = {c.time: i for i, c in enumerate(candles)}

    # Running trend state, updated as we process swings chronologically
    current_trend = "undetermined"
    last_swing_high: Optional[SwingPoint] = None
    last_swing_low: Optional[SwingPoint] = None

    # Already-detected BoS/CHoCH times (to avoid duplicating at the same candle)
    already_detected = set()

    # Work through confirmed swings in order to update trend
    # For each swing, after it becomes confirmed, scan forward for structure breaks
    processed_swing_idx = 0

    for c_idx, c in enumerate(candles):
        # BoS / CHoCH requires candle close confirmation; forming candles cannot confirm breaks
        if c.is_forming:
            continue

        # First, absorb any swings that are now confirmed (confirm_time <= c.time)
        while processed_swing_idx < len(swings) and swings[processed_swing_idx].confirm_time <= c.time:
            sw = swings[processed_swing_idx]
            if sw.type == "high":
                last_swing_high = sw
            else:
                last_swing_low = sw
            processed_swing_idx += 1

        # Now check for structure breaks on THIS candle (c_idx)
        if last_swing_high is None or last_swing_low is None:
            continue
        if c.time in already_detected:
            continue

        # Update trend based on latest confirmed swings
        h_label = last_swing_high.label
        l_label = last_swing_low.label
        if h_label == "HH" and l_label == "HL":
            current_trend = "bullish"
        elif h_label == "LH" and l_label == "LL":
            current_trend = "bearish"
        # else keep current_trend as is

        # --- Bullish BoS or Bearish CHoCH ---
        # Bullish BoS: price closes above last swing HIGH (trend continuation if bullish)
        if c.close > last_swing_high.price and c.time > last_swing_high.confirm_time:
            kind = "BOS" if current_trend == "bullish" else "CHoCH"

            # Retracement check: how much did price pull back from last SH before breaking?
            # Look for the lowest close between last_swing_high.time and now
            sh_idx = time_to_idx.get(last_swing_high.time, 0)
            sl_price = last_swing_low.price if last_swing_low else last_swing_high.price * 0.98

            pullback_low = min(
                (candles[k].low for k in range(sh_idx + 1, c_idx) if k < len(candles)),
                default=last_swing_high.price
            )

            total_leg = last_swing_high.price - sl_price
            retrace_pct = 50.0  # fallback
            if total_leg > 0:
                retrace_depth = last_swing_high.price - pullback_low
                retrace_pct = min(100.0, (retrace_depth / total_leg) * 100.0)

            is_valid = retrace_pct >= config.bos_min_retracement_pct

            bos_list.append(BreakOfStructure(
                time=c.time,
                ist_time=c.ist_time,
                type="bullish",
                kind=kind,
                broken_level=round(last_swing_high.price, 2),
                retracement_pct=round(retrace_pct, 1),
                valid=is_valid,
                timeframe=timeframe
            ))
            already_detected.add(c.time)

            # If CHoCH, flip trend
            if kind == "CHoCH":
                current_trend = "bullish"

        # --- Bearish BoS or Bullish CHoCH ---
        # Bearish BoS: price closes below last swing LOW (trend continuation if bearish)
        elif c.close < last_swing_low.price and c.time > last_swing_low.confirm_time:
            kind = "BOS" if current_trend == "bearish" else "CHoCH"

            sl_idx = time_to_idx.get(last_swing_low.time, 0)
            sh_price = last_swing_high.price if last_swing_high else last_swing_low.price * 1.02

            pullback_high = max(
                (candles[k].high for k in range(sl_idx + 1, c_idx) if k < len(candles)),
                default=last_swing_low.price
            )

            total_leg = sh_price - last_swing_low.price
            retrace_pct = 50.0
            if total_leg > 0:
                retrace_depth = pullback_high - last_swing_low.price
                retrace_pct = min(100.0, (retrace_depth / total_leg) * 100.0)

            is_valid = retrace_pct >= config.bos_min_retracement_pct

            bos_list.append(BreakOfStructure(
                time=c.time,
                ist_time=c.ist_time,
                type="bearish",
                kind=kind,
                broken_level=round(last_swing_low.price, 2),
                retracement_pct=round(retrace_pct, 1),
                valid=is_valid,
                timeframe=timeframe
            ))
            already_detected.add(c.time)

            if kind == "CHoCH":
                current_trend = "bearish"

    return bos_list


# ---------------------------------------------------------------------------
# Support / Resistance cluster zones
# ---------------------------------------------------------------------------

def calculate_support_resistance(
    swings: List[SwingPoint],
    tolerance: float = 1.5
) -> List[dict]:
    """Group swing points to identify major support and resistance zones."""
    sr_zones = []
    if not swings:
        return sr_zones

    # Cluster swing prices within tolerance
    clusters: List[List[SwingPoint]] = []
    for s in swings:
        added = False
        for cl in clusters:
            avg_p = sum(item.price for item in cl) / len(cl)
            if abs(s.price - avg_p) <= tolerance:
                cl.append(s)
                added = True
                break
        if not added:
            clusters.append([s])

    # Convert clusters of 2+ touches into S/R levels
    for cl in clusters:
        if len(cl) >= 2:
            avg_price = round(sum(item.price for item in cl) / len(cl), 2)
            high_count = sum(1 for item in cl if item.type == "high")
            low_count = sum(1 for item in cl if item.type == "low")
            if high_count > low_count:
                role = "resistance"
            elif low_count > high_count:
                role = "support"
            else:
                role = "pivot"
            sr_zones.append({
                "price": avg_price,
                "role": role,
                "touches": len(cl),
                "last_touch_time": max(item.time for item in cl)
            })

    sr_zones.sort(key=lambda x: x["touches"], reverse=True)
    return sr_zones[:8]
