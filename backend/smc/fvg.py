"""
Fair Value Gap (FVG) detection, mitigation tracking, and inversion logic.

Strictly progressive and lookahead-bias free.
Supports:
- 3-candle FVG pattern
- ATR-based minimum size filtering
- Consecutive FVG joining
- Inversion / breaker FVG tracking (when price closes beyond the gap)
- HTF overlap discovery (Critical Section / POI)
"""
from typing import List, Optional
from backend.smc.models import Candle, FairValueGap, AnalysisConfig
from backend.smc.structure import _atr


def calculate_fvgs(
    candles: List[Candle],
    timeframe: str,
    config: Optional[AnalysisConfig] = None
) -> List[FairValueGap]:
    """
    Calculate Fair Value Gaps with mitigation, inversion, and size filtering.
    """
    if config is None:
        config = AnalysisConfig()

    if len(candles) < 3:
        return []

    # Calculate average body size and ATR
    body_sizes = [abs(c.close - c.open) for c in candles]
    avg_body = sum(body_sizes) / len(body_sizes) if body_sizes else 1.0
    atr_val = _atr(candles, 14)
    min_size = config.fvg_min_size_atr_multiplier * atr_val

    raw_fvgs: List[FairValueGap] = []

    # 3-candle pattern: candle[i-2], candle[i-1], candle[i]
    for i in range(2, len(candles)):
        c0 = candles[i - 2]
        c1 = candles[i - 1]  # The displacement / impulse candle
        c2 = candles[i]

        # Prevent premature / repainting FVGs: candle 3 must be closed
        if c2.is_forming:
            continue

        body1 = abs(c1.close - c1.open)
        is_displacement = body1 >= (config.displacement_body_atr_multiplier * avg_body)

        # Bullish FVG: Low of c2 > High of c0
        if c2.low > c0.high and c1.close > c1.open:
            top = c2.low
            bottom = c0.high
            size = top - bottom
            if size >= min_size:
                midpoint = round((top + bottom) / 2.0, 2)
                fvg_id = f"fvg_bull_{timeframe}_{c1.time}"
                raw_fvgs.append(FairValueGap(
                    id=fvg_id,
                    timeframe=timeframe,
                    direction="bullish",
                    top=round(top, 2),
                    bottom=round(bottom, 2),
                    midpoint=midpoint,
                    start_time=c1.time,
                    start_ist=c1.ist_time,
                    mitigated=False,
                    mitigation_level="unmitigated",
                    is_displacement=is_displacement,
                    size=round(size, 2)
                ))

        # Bearish FVG: High of c2 < Low of c0
        elif c2.high < c0.low and c1.close < c1.open:
            top = c0.low
            bottom = c2.high
            size = top - bottom
            if size >= min_size:
                midpoint = round((top + bottom) / 2.0, 2)
                fvg_id = f"fvg_bear_{timeframe}_{c1.time}"
                raw_fvgs.append(FairValueGap(
                    id=fvg_id,
                    timeframe=timeframe,
                    direction="bearish",
                    top=round(top, 2),
                    bottom=round(bottom, 2),
                    midpoint=midpoint,
                    start_time=c1.time,
                    start_ist=c1.ist_time,
                    mitigated=False,
                    mitigation_level="unmitigated",
                    is_displacement=is_displacement,
                    size=round(size, 2)
                ))

    # Optional: join consecutive touching FVGs
    if config.fvg_join_consecutive and len(raw_fvgs) > 1:
        merged_fvgs: List[FairValueGap] = []
        skip_indices = set()
        for idx in range(len(raw_fvgs)):
            if idx in skip_indices:
                continue
            curr = raw_fvgs[idx]
            if idx + 1 < len(raw_fvgs):
                nxt = raw_fvgs[idx + 1]
                if curr.direction == nxt.direction and abs(curr.top - nxt.bottom) <= 0.2:
                    new_top = max(curr.top, nxt.top)
                    new_bottom = min(curr.bottom, nxt.bottom)
                    curr = FairValueGap(
                        id=f"{curr.id}_merged",
                        timeframe=timeframe,
                        direction=curr.direction,
                        top=new_top,
                        bottom=new_bottom,
                        midpoint=round((new_top + new_bottom) / 2.0, 2),
                        start_time=curr.start_time,
                        start_ist=curr.start_ist,
                        mitigated=False,
                        mitigation_level="unmitigated",
                        is_displacement=curr.is_displacement or nxt.is_displacement,
                        size=round(new_top - new_bottom, 2)
                    )
                    skip_indices.add(idx + 1)
            merged_fvgs.append(curr)
        raw_fvgs = merged_fvgs

    # Evaluate mitigation & inversion forward in time
    time_map = {c.time: k for k, c in enumerate(candles)}

    for fvg in raw_fvgs:
        start_idx = time_map.get(fvg.start_time)
        if start_idx is None or start_idx + 2 >= len(candles):
            continue

        # Forward tracking starts from candle c2 completion (start_idx + 2)
        for k in range(start_idx + 2, len(candles)):
            c = candles[k]
            if fvg.direction == "bullish":
                # Mitigation: downward pullback into gap
                if c.low <= fvg.top:
                    if c.low <= fvg.midpoint:
                        fvg.mitigation_level = "partial_50"
                    if c.low <= fvg.bottom:
                        fvg.mitigated = True
                        fvg.mitigated_at = c.time
                        fvg.mitigated_ist = c.ist_time
                        fvg.mitigation_level = "fully_mitigated"

                # Inversion: candle close fully below gap bottom (requires closed candle)
                if not c.is_forming and c.close < fvg.bottom:
                    fvg.inverted = True
                    fvg.inverted_at = c.time
                    break
                if fvg.mitigated:
                    break

            else:  # Bearish FVG
                # Mitigation: upward pullback into gap
                if c.high >= fvg.bottom:
                    if c.high >= fvg.midpoint:
                        fvg.mitigation_level = "partial_50"
                    if c.high >= fvg.top:
                        fvg.mitigated = True
                        fvg.mitigated_at = c.time
                        fvg.mitigated_ist = c.ist_time
                        fvg.mitigation_level = "fully_mitigated"

                # Inversion: candle close fully above gap top (requires closed candle)
                if not c.is_forming and c.close > fvg.top:
                    fvg.inverted = True
                    fvg.inverted_at = c.time
                    break
                if fvg.mitigated:
                    break

    return raw_fvgs


def find_overlapping_fvgs(htf_fvgs: List[FairValueGap], ltf_fvgs: List[FairValueGap]) -> List[dict]:
    """
    Find overlapping Fair Value Gaps across timeframes (Critical Section / POI).
    """
    overlaps = []
    for h in htf_fvgs:
        if h.mitigated or h.inverted:
            continue
        for l in ltf_fvgs:
            if l.mitigated or l.inverted:
                continue
            if h.direction == l.direction:
                overlap_top = min(h.top, l.top)
                overlap_bottom = max(h.bottom, l.bottom)
                if overlap_top > overlap_bottom:
                    overlaps.append({
                        "htf_id": h.id,
                        "ltf_id": l.id,
                        "htf_timeframe": h.timeframe,
                        "ltf_timeframe": l.timeframe,
                        "direction": h.direction,
                        "overlap_top": round(overlap_top, 2),
                        "overlap_bottom": round(overlap_bottom, 2),
                        "overlap_midpoint": round((overlap_top + overlap_bottom) / 2.0, 2)
                    })
    return overlaps
