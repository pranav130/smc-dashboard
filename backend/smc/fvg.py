from typing import List, Optional
from backend.smc.models import Candle, FairValueGap

def calculate_fvgs(candles: List[Candle], timeframe: str) -> List[FairValueGap]:
    """
    Calculate Fair Value Gaps (FVG) across candle series with 50% midpoint and mitigation tracking.
    Strictly progressive (no lookahead bias).
    """
    if len(candles) < 3:
        return []

    # Calculate average body size for displacement detection
    body_sizes = [abs(c.close - c.open) for c in candles]
    avg_body = sum(body_sizes) / len(body_sizes) if body_sizes else 1.0

    fvgs: List[FairValueGap] = []

    # 3-candle pattern: candle[i-2], candle[i-1], candle[i]
    for i in range(2, len(candles)):
        c0 = candles[i - 2]
        c1 = candles[i - 1]  # The displacement candle
        c2 = candles[i]

        body1 = abs(c1.close - c1.open)
        is_displacement = body1 >= (1.5 * avg_body)

        # Bullish FVG: Low of c2 > High of c0
        if c2.low > c0.high and c1.close > c1.open:
            top = c2.low
            bottom = c0.high
            midpoint = round((top + bottom) / 2.0, 2)
            fvg_id = f"fvg_bull_{timeframe}_{c1.time}"

            fvg = FairValueGap(
                id=fvg_id,
                timeframe=timeframe,
                direction="bullish",
                top=round(top, 2),
                bottom=round(bottom, 2),
                midpoint=midpoint,
                start_time=c1.time,
                start_ist=c1.ist_time,
                mitigated=False,
                mitigation_level="unmitigated"
            )
            fvgs.append(fvg)

        # Bearish FVG: High of c2 < Low of c0
        elif c2.high < c0.low and c1.close < c1.open:
            top = c0.low
            bottom = c2.high
            midpoint = round((top + bottom) / 2.0, 2)
            fvg_id = f"fvg_bear_{timeframe}_{c1.time}"

            fvg = FairValueGap(
                id=fvg_id,
                timeframe=timeframe,
                direction="bearish",
                top=round(top, 2),
                bottom=round(bottom, 2),
                midpoint=midpoint,
                start_time=c1.time,
                start_ist=c1.ist_time,
                mitigated=False,
                mitigation_level="unmitigated"
            )
            fvgs.append(fvg)

    # Now evaluate mitigation status forward in time from FVG creation
    for fvg in fvgs:
        # Find index of candle right after FVG completion
        fvg_idx = next((k for k, c in enumerate(candles) if c.time == fvg.start_time), -1)
        if fvg_idx == -1 or fvg_idx + 2 >= len(candles):
            continue

        for k in range(fvg_idx + 2, len(candles)):
            c = candles[k]
            if fvg.direction == "bullish":
                # Bullish FVG: price pulls down into the gap
                if c.low <= fvg.top:
                    # Touched gap
                    if c.low <= fvg.midpoint:
                        fvg.mitigation_level = "partial_50"
                    if c.low <= fvg.bottom:
                        fvg.mitigated = True
                        fvg.mitigated_at = c.time
                        fvg.mitigated_ist = c.ist_time
                        fvg.mitigation_level = "fully_mitigated"
                        break  # Once fully mitigated, status is sealed
            else:
                # Bearish FVG: price pulls up into the gap
                if c.high >= fvg.bottom:
                    # Touched gap
                    if c.high >= fvg.midpoint:
                        fvg.mitigation_level = "partial_50"
                    if c.high >= fvg.top:
                        fvg.mitigated = True
                        fvg.mitigated_at = c.time
                        fvg.mitigated_ist = c.ist_time
                        fvg.mitigation_level = "fully_mitigated"
                        break

    return fvgs


def find_overlapping_fvgs(htf_fvgs: List[FairValueGap], ltf_fvgs: List[FairValueGap]) -> List[dict]:
    """Find overlapping Fair Value Gaps across timeframes (Critical Section / POI)."""
    overlaps = []
    for h in htf_fvgs:
        if h.mitigated:
            continue
        for l in ltf_fvgs:
            if l.mitigated:
                continue
            if h.direction == l.direction:
                # Check price range overlap
                overlap_top = min(h.top, l.top)
                overlap_bottom = max(h.bottom, l.bottom)
                if overlap_top > overlap_bottom:
                    overlaps.append({
                        "htf_id": h.id,
                        "ltf_id": l.id,
                        "htf_timeframe": h.timeframe,
                        "ltf_timeframe": l.timeframe,
                        "direction": h.direction,
                        "overlap_top": overlap_top,
                        "overlap_bottom": overlap_bottom,
                        "overlap_midpoint": round((overlap_top + overlap_bottom) / 2.0, 2)
                    })
    return overlaps
