from typing import List, Tuple, Optional
from backend.smc.models import Candle, SwingPoint, BreakOfStructure

def find_swings(candles: List[Candle], timeframe: str, window: int = 3) -> List[SwingPoint]:
    """
    Find major swing highs and swing lows using symmetrical window validation.
    """
    if len(candles) < (window * 2 + 1):
        return []

    swings: List[SwingPoint] = []
    n = len(candles)

    for i in range(window, n - window):
        c = candles[i]
        high_val = c.high
        low_val = c.low

        # Check Swing High
        is_swing_high = True
        for k in range(1, window + 1):
            if candles[i - k].high >= high_val or candles[i + k].high >= high_val:
                is_swing_high = False
                break
        if is_swing_high:
            swings.append(SwingPoint(
                time=c.time,
                ist_time=c.ist_time,
                price=round(high_val, 2),
                type="high",
                timeframe=timeframe
            ))

        # Check Swing Low
        is_swing_low = True
        for k in range(1, window + 1):
            if candles[i - k].low <= low_val or candles[i + k].low <= low_val:
                is_swing_low = False
                break
        if is_swing_low:
            swings.append(SwingPoint(
                time=c.time,
                ist_time=c.ist_time,
                price=round(low_val, 2),
                type="low",
                timeframe=timeframe
            ))

    # Sort chronologically
    swings.sort(key=lambda s: s.time)
    return swings


def calculate_bos(candles: List[Candle], swings: List[SwingPoint], timeframe: str) -> List[BreakOfStructure]:
    """
    Calculate Break of Structure (BoS) with strict verification:
    Rule from SMC trading rules:
    - Retracement must be at least 40.0% before the structure break is valid.
    """
    bos_list: List[BreakOfStructure] = []
    if len(swings) < 2 or len(candles) < 5:
        return bos_list

    # Match swings to candle indices
    candle_time_map = {c.time: i for i, c in enumerate(candles)}

    for s_idx in range(len(swings) - 1):
        prev_swing = swings[s_idx]
        prev_swing_idx = candle_time_map.get(prev_swing.time)
        if prev_swing_idx is None:
            continue

        # Look forward in candles until next same-type swing or end
        if prev_swing.type == "high":
            # For a Bullish BoS, price must break above this swing high
            # First, check if there was an established swing low before/around it to gauge the impulse leg
            # and verify a retracement of >= 40% before breaking the high
            pullback_low = float("inf")
            for c_i in range(prev_swing_idx + 1, len(candles)):
                c = candles[c_i]
                pullback_low = min(pullback_low, c.low)

                if c.close > prev_swing.price:
                    # Break occurred at candle c_i
                    # Calculate retracement percentage
                    # Impulse height estimate
                    impulse_start_low = prev_swing.price * 0.98
                    # Find closest prior swing low
                    prior_lows = [s.price for s in swings[:s_idx] if s.type == "low"]
                    if prior_lows:
                        impulse_start_low = prior_lows[-1]

                    total_leg = prev_swing.price - impulse_start_low
                    if total_leg > 0:
                        retrace_depth = prev_swing.price - pullback_low
                        retrace_pct = (retrace_depth / total_leg) * 100.0
                    else:
                        retrace_pct = 50.0  # Safe fallback if leg is minimal

                    is_valid = retrace_pct >= 40.0

                    bos_list.append(BreakOfStructure(
                        time=c.time,
                        ist_time=c.ist_time,
                        type="bullish",
                        broken_level=prev_swing.price,
                        retracement_pct=round(retrace_pct, 1),
                        valid=is_valid,
                        timeframe=timeframe
                    ))
                    break

        elif prev_swing.type == "low":
            # For Bearish BoS, price must break below this swing low
            pullback_high = float("-inf")
            for c_i in range(prev_swing_idx + 1, len(candles)):
                c = candles[c_i]
                pullback_high = max(pullback_high, c.high)

                if c.close < prev_swing.price:
                    # Break occurred
                    prior_highs = [s.price for s in swings[:s_idx] if s.type == "high"]
                    impulse_start_high = prior_highs[-1] if prior_highs else prev_swing.price * 1.02

                    total_leg = impulse_start_high - prev_swing.price
                    if total_leg > 0:
                        retrace_depth = pullback_high - prev_swing.price
                        retrace_pct = (retrace_depth / total_leg) * 100.0
                    else:
                        retrace_pct = 50.0

                    is_valid = retrace_pct >= 40.0

                    bos_list.append(BreakOfStructure(
                        time=c.time,
                        ist_time=c.ist_time,
                        type="bearish",
                        broken_level=prev_swing.price,
                        retracement_pct=round(retrace_pct, 1),
                        valid=is_valid,
                        timeframe=timeframe
                    ))
                    break

    return bos_list


def calculate_support_resistance(swings: List[SwingPoint], tolerance: float = 1.5) -> List[dict]:
    """Group swing points to identify major support and resistance zones."""
    sr_zones = []
    prices = [s.price for s in swings]
    if not prices:
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
            role = "resistance" if high_count > low_count else "support" if low_count > high_count else "pivot"
            sr_zones.append({
                "price": avg_price,
                "role": role,
                "touches": len(cl),
                "last_touch_time": max(item.time for item in cl)
            })

    sr_zones.sort(key=lambda x: x["touches"], reverse=True)
    return sr_zones[:8]
