"""
Level ranking and scoring engine for Gold Liquidity Intelligence (XAUTUSD).

Deterministic, transparent priority system:
- High, Medium, Low priority with plain-English rationales.
- Higher Timeframe authority (1D > 4H > 1H > 30M) strictly outranks low-value clutter.
- A nearby minor level will NEVER outrank a meaningful HTF level solely because of proximity.
- Identifies opposing HTF zones that could obstruct price movement.
"""
from typing import List, Dict, Any, Optional
from backend.smc.models import (
    LevelRanking, FairValueGap, OrderBlock, LiquidityLevel, PsychologicalLevel,
    Trendline, AnalysisConfig
)


def rank_key_levels(
    current_price: float,
    daily_fvgs: List[FairValueGap],
    h4_fvgs: List[FairValueGap],
    current_fvgs: List[FairValueGap],
    order_blocks: List[OrderBlock],
    liquidity_levels: List[LiquidityLevel],
    psychological_levels: List[PsychologicalLevel],
    trendlines: List[Trendline],
    config: Optional[AnalysisConfig] = None,
    opposing_warnings: Optional[List[str]] = None,
    interaction_states: Optional[Dict[str, str]] = None
) -> List[LevelRanking]:
    """
    Score and prioritize key levels deterministically:
    High, Medium, Low priority tiers with human-readable rationales.
    High priority levels are always surfaced before Medium and Low,
    regardless of price proximity.
    """
    if config is None:
        config = AnalysisConfig()
    if opposing_warnings is None:
        opposing_warnings = []
    if interaction_states is None:
        interaction_states = {}

    ranked: List[LevelRanking] = []

    # Pre-build lookup of opposing HTF zones
    htf_opposing_overhead = [
        f for f in (daily_fvgs + h4_fvgs)
        if not f.mitigated and not f.inverted and f.direction == "bearish" and f.bottom > current_price
    ]
    htf_opposing_underneath = [
        f for f in (daily_fvgs + h4_fvgs)
        if not f.mitigated and not f.inverted and f.direction == "bullish" and f.top < current_price
    ]

    # 1. Higher Timeframe FVGs (Daily & 4H)
    for f in (daily_fvgs + h4_fvgs):
        if f.mitigated:
            continue
        dist = round(f.midpoint - current_price, 2)
        dist_pct = round((dist / current_price) * 100.0, 2) if current_price else 0.0

        score = 50
        reasons = []

        if f.timeframe == "1D":
            score += 35
            reasons.append("Daily HTF market authority")
        elif f.timeframe == "4H":
            score += 25
            reasons.append("4H primary key-level boundary")

        if f.mitigation_level == "unmitigated":
            score += 20
            reasons.append("Fresh, unmitigated imbalance")
        elif f.mitigation_level == "partial_50":
            score += 10
            reasons.append("Partial mitigation (midpoint tested)")

        if f.is_displacement:
            score += 15
            reasons.append("High-momentum displacement origin")

        # Confluence with 20/80 round numbers
        for p in psychological_levels:
            if abs(f.midpoint - p.price) <= 1.5:
                score += 10
                reasons.append(f"Confluence with round {p.level_type} level (${p.price:.2f})")
                break

        # Check opposing zone
        opp_note = None
        if dist > 0 and htf_opposing_overhead:
            near_opp = min(htf_opposing_overhead, key=lambda z: z.bottom)
            if near_opp.bottom < f.bottom:
                opp_note = f"Opposing Bearish {near_opp.timeframe} FVG overhead at ${near_opp.bottom:.2f}"
        elif dist < 0 and htf_opposing_underneath:
            near_opp = max(htf_opposing_underneath, key=lambda z: z.top)
            if near_opp.top > f.top:
                opp_note = f"Opposing Bullish {near_opp.timeframe} FVG support below at ${near_opp.top:.2f}"

        # Deterministic Priority
        if score >= 75:
            priority = "High"
            p_reason = f"Major {f.timeframe} HTF Level: {reasons[0]} with fresh imbalance."
        elif score >= 50:
            priority = "Medium"
            p_reason = f"Intermediate {f.timeframe} Level: {reasons[0]}."
        else:
            priority = "Low"
            p_reason = "Secondary level under surveillance."

        ranked.append(LevelRanking(
            name=f"{f.timeframe} {f.direction.capitalize()} FVG Midpoint",
            type=f"{f.timeframe} FVG 50%",
            price=f.midpoint,
            timeframe=f.timeframe,
            direction=f.direction,
            distance=dist,
            distance_pct=dist_pct,
            top=f.top,
            bottom=f.bottom,
            mitigation=f.mitigation_level,
            score=score,
            score_reason="; ".join(reasons),
            priority=priority,
            priority_reason=p_reason,
            opposing_zone_nearby=opp_note,
            interaction_state=interaction_states.get(f.id, "WAITING"),
            source_id=f.id
        ))

    # 2. Strict ICT Order Blocks
    for ob in order_blocks:
        if ob.mitigated or ob.is_breaker:
            continue
        dist = round(ob.midpoint - current_price, 2)
        dist_pct = round((dist / current_price) * 100.0, 2) if current_price else 0.0

        score = 45
        reasons = [f"Origin of confirmed structural break (${ob.broken_level:.2f})"]
        if ob.timeframe in ["1D", "4H"]:
            score += 30
            reasons.append("HTF Order Block")
        else:
            score += 15
            reasons.append(f"{ob.timeframe} Intermediate Order Block")

        if score >= 75:
            priority = "High"
            p_reason = f"High structural importance: {reasons[1]}."
        elif score >= 50:
            priority = "Medium"
            p_reason = f"Intermediate Order Block: {reasons[0]}."
        else:
            priority = "Low"
            p_reason = "Minor order block."

        ranked.append(LevelRanking(
            name=f"{ob.timeframe} {ob.direction.capitalize()} Order Block",
            type=f"{ob.timeframe} OB",
            price=ob.midpoint,
            timeframe=ob.timeframe,
            direction=ob.direction,
            distance=dist,
            distance_pct=dist_pct,
            top=ob.top,
            bottom=ob.bottom,
            mitigation="unmitigated",
            score=score,
            score_reason="; ".join(reasons),
            priority=priority,
            priority_reason=p_reason,
            opposing_zone_nearby=None,
            interaction_state=interaction_states.get(ob.id, "WAITING"),
            source_id=ob.id
        ))

    # 3. Macro Liquidity Levels (PDH, PDL, PWH, PWL, and EQH/EQL Clusters)
    # Group nearby liquidity levels within 1.0 USD to prevent clutter
    clustered_liquidity: List[LiquidityLevel] = []
    sorted_liq = sorted(liquidity_levels, key=lambda l: l.price)
    i = 0
    while i < len(sorted_liq):
        current = sorted_liq[i]
        cluster = [current]
        j = i + 1
        while j < len(sorted_liq) and abs(sorted_liq[j].price - current.price) <= 1.0:
            cluster.append(sorted_liq[j])
            j += 1
        if len(cluster) > 1:
            labels = [c.label for c in cluster]
            types = [c.type for c in cluster]
            is_swept = any(c.swept for c in cluster)
            avg_price = round(sum(c.price for c in cluster) / len(cluster), 2)
            clustered_liquidity.append(LiquidityLevel(
                type=types[0],
                label=f"{'/'.join(labels)} Cluster",
                price=avg_price,
                time=current.time,
                ist_time=current.ist_time,
                swept=is_swept
            ))
            i = j
        else:
            clustered_liquidity.append(current)
            i += 1

    for liq in clustered_liquidity:
        dist = round(liq.price - current_price, 2)
        dist_pct = round((dist / current_price) * 100.0, 2) if current_price else 0.0

        score = 45
        reasons = [liq.label]
        if "Week" in liq.label:
            score += 35
            tf = "1W"
            reasons.append("Weekly macro liquidity pool")
        elif "Day" in liq.label:
            score += 30
            tf = "1D"
            reasons.append("Daily key liquidity pool")
        elif "Cluster" in liq.label:
            score += 25
            tf = "1H"
            reasons.append("Confluent liquidity cluster")
        else:
            score += 15
            tf = "Intraday"

        if not liq.swept:
            score += 15
            reasons.append("Untested resting buy/sell-side liquidity")
        else:
            score -= 10
            reasons.append("Liquidity already swept")

        if score >= 75:
            priority = "High"
            p_reason = f"High Liquidity Target: {reasons[1]} ({'Untested' if not liq.swept else 'Swept'})."
        elif score >= 50:
            priority = "Medium"
            p_reason = f"Significant Liquidity Pool: {reasons[0]}."
        else:
            priority = "Low"
            p_reason = "Intraday liquidity level."

        ranked.append(LevelRanking(
            name=liq.label,
            type="Liquidity Pool",
            price=liq.price,
            timeframe=tf,
            direction=None,
            distance=dist,
            distance_pct=dist_pct,
            swept=liq.swept,
            score=score,
            score_reason="; ".join(reasons),
            priority=priority,
            priority_reason=p_reason,
            opposing_zone_nearby=None,
            interaction_state=interaction_states.get(f"liq_{liq.type}_{liq.time}", "WAITING"),
            source_id=f"liq_{liq.type}_{liq.time}"
        ))

    # 4. Psychological Round Numbers (20s and 80s)
    # Only keep the nearest 4, and label as Low priority unless confluent with HTF structure
    for pl in psychological_levels[:4]:
        score = 30
        reasons = [f"Institutional round psychological level ({pl.level_type})"]
        priority = "Low"
        p_reason = "Round psychological price reference; requires structural confluence."

        ranked.append(LevelRanking(
            name=f"Round {pl.level_type} Institutional (${pl.price:.2f})",
            type="Psychological",
            price=pl.price,
            timeframe="Static",
            direction=None,
            distance=pl.distance,
            distance_pct=pl.distance_pct,
            score=score,
            score_reason="; ".join(reasons),
            priority=priority,
            priority_reason=p_reason,
            opposing_zone_nearby=None,
            interaction_state="WAITING",
            source_id=f"psych_{pl.price}"
        ))

    # Priority Weighting Scheme:
    # High Priority = 3, Medium = 2, Low = 1
    # Sort order:
    # 1. Priority Tier (High > Medium > Low)
    # 2. Within the same priority tier: Absolute proximity (closest to market price first)
    # 3. Score as tie-breaker
    priority_map = {"High": 3, "Medium": 2, "Low": 1}
    ranked.sort(key=lambda x: (
        -priority_map.get(x.priority, 1),
        abs(x.distance),
        -x.score
    ))

    return ranked[:config.max_levels_display]
