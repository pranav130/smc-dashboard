"""
Level ranking and scoring engine.

Answers the prompt's 3 core questions:
1. Where are the important Gold price levels?
2. Why are those levels important?
3. What is price currently doing around those levels?

Explicit heuristic scoring based on SMC rules:
- Higher Timeframe weight (1D > 4H > 1H > 30M)
- Freshness & Mitigation (unmitigated > partial > mitigated)
- Confluence (overlapping FVG, 20/80 round number alignment, order block overlap)
- Proximity to current price
- Liquidity status (unswept > swept)
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
    config: Optional[AnalysisConfig] = None
) -> List[LevelRanking]:
    """
    Score and order key levels by significance and proximity.
    """
    if config is None:
        config = AnalysisConfig()

    ranked: List[LevelRanking] = []

    # 1. Higher Timeframe FVGs (1D & 4H)
    for f in (daily_fvgs + h4_fvgs):
        if f.mitigated:
            continue
        dist = round(f.midpoint - current_price, 2)
        dist_pct = round((dist / current_price) * 100.0, 2) if current_price else 0.0

        # Score calculation
        score = 50  # Base
        reasons = []
        if f.timeframe == "1D":
            score += 30
            reasons.append("Daily HTF authority")
        elif f.timeframe == "4H":
            score += 20
            reasons.append("4H structural boundary")

        if f.mitigation_level == "unmitigated":
            score += 20
            reasons.append("Completely unmitigated fresh gap")
        elif f.mitigation_level == "partial_50":
            score += 10
            reasons.append("Partial mitigation (midpoint tested)")

        if f.is_displacement:
            score += 15
            reasons.append("Formed with high-momentum displacement")

        # Confluence with 20/80 round levels
        for p in psychological_levels:
            if abs(f.midpoint - p.price) <= 1.5:
                score += 15
                reasons.append(f"Confluence with round {p.level_type} level (${p.price})")
                break

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
            source_id=f.id
        ))

    # 2. Order Blocks
    for ob in order_blocks:
        if ob.mitigated or ob.is_breaker:
            continue
        dist = round(ob.midpoint - current_price, 2)
        dist_pct = round((dist / current_price) * 100.0, 2) if current_price else 0.0

        score = 45
        reasons = [f"Origin of confirmed structural break (${ob.broken_level:.2f})"]
        if ob.timeframe in ["1D", "4H"]:
            score += 25
            reasons.append("HTF Order Block")
        else:
            score += 15
            reasons.append(f"{ob.timeframe} LTF Order Block")

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
            source_id=ob.id
        ))

    # 3. Liquidity Levels (PDH, PDL, PWH, PWL, EQH, EQL)
    for liq in liquidity_levels:
        dist = round(liq.price - current_price, 2)
        dist_pct = round((dist / current_price) * 100.0, 2) if current_price else 0.0

        score = 40
        reasons = [liq.label]
        if "Day" in liq.label:
            score += 25
            tf = "1D"
        elif "Week" in liq.label:
            score += 35
            tf = "1W"
        else:
            score += 20
            tf = "Intraday"

        if not liq.swept:
            score += 15
            reasons.append("Untapped resting liquidity pool")
        else:
            score -= 10
            reasons.append("Already swept by wick")

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
            source_id=f"liq_{liq.type}_{liq.time}"
        ))

    # 4. Psychological Levels
    for pl in psychological_levels[:4]:
        score = 35
        reasons = [f"Institutional round psychological barrier ({pl.level_type})"]
        ranked.append(LevelRanking(
            name=f"Round {pl.level_type} Psychological (${pl.price})",
            type="Psychological",
            price=pl.price,
            timeframe="Static",
            direction=None,
            distance=pl.distance,
            distance_pct=pl.distance_pct,
            score=score,
            score_reason="; ".join(reasons),
            source_id=f"psych_{pl.price}"
        ))

    # Sort primarily by absolute distance from current price, secondarily by score
    ranked.sort(key=lambda x: (abs(x.distance), -x.score))

    return ranked[:config.max_levels_display]
