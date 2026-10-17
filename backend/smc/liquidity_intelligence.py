"""
Hidden Liquidity and Liquidity Heatmap Intelligence Module for XAUTUSD.

This module provides rule-based detection, clustering, scoring, multi-timeframe confluence,
and sweep detection for hidden Buy-Side Liquidity (BSL), Sell-Side Liquidity (SSL),
Internal Range Liquidity (IRL), and External Range Liquidity (ERL).

Data Integrity Note:
All calculations are strictly derived from observed historical OHLCV candles, swing structure,
and volatility (ATR). No synthetic order book, fake institutional flow, or broker stop data is fabricated.
Zones are mathematically estimated hypotheses scored from 0 to 100.
"""

from typing import List, Dict, Optional, Literal, Tuple, Any
from pydantic import BaseModel, Field
import math
from backend.smc.models import Candle, SwingPoint, AnalysisConfig
from backend.smc.structure import _atr, find_swings


# ---------------------------------------------------------------------------
# Data Models for Liquidity Intelligence
# ---------------------------------------------------------------------------

LiquidityZoneType = Literal["BSL", "SSL", "IRL", "ERL", "IMBALANCE_VOID"]
ZoneStatus = Literal["ACTIVE", "APPROACHED", "SWEPT", "MITIGATED", "INVALIDATED"]


class LiquiditySubFactor(BaseModel):
    name: str
    points: float
    max_points: float
    description: str


class LiquidityScoreBreakdown(BaseModel):
    total_score: int                           # 0 to 100
    confidence: Literal["LOW", "MODERATE", "HIGH", "EXTREME"]
    factors: List[LiquiditySubFactor] = Field(default_factory=list)


class SweepRecord(BaseModel):
    breached: bool = False
    breach_time: Optional[int] = None
    breach_ist: Optional[str] = None
    breach_price: Optional[float] = None
    max_excursion: float = 0.0                # USD beyond boundary
    re_entered: bool = False
    confirmed_sweep: bool = False             # Closed back inside (rejection)
    subsequent_reaction_bars: int = 0
    is_sustained_breakout: bool = False


class LiquidityZone(BaseModel):
    id: str
    type: LiquidityZoneType                   # BSL, SSL, IRL, ERL, IMBALANCE_VOID
    label: str
    price: float                              # Core anchor / center price
    top: float                                # Upper boundary
    bottom: float                             # Lower boundary
    timeframe: str                            # Detection TF ("1D", "4H", "1H", "15M", "5M", etc.)
    supporting_timeframes: List[str] = Field(default_factory=list)
    confluence_count: int = 1                 # How many TFs / sources support this zone
    
    # Distance to current market price
    distance: float = 0.0                     # Signed: positive = above current price
    distance_pct: float = 0.0
    
    # Scoring
    score: int = 0                            # 0 to 100
    confidence: str = "MODERATE"
    score_breakdown: Optional[LiquidityScoreBreakdown] = None
    
    # Status
    status: ZoneStatus = "ACTIVE"
    touch_count: int = 1
    untested: bool = True
    
    # Timestamps
    first_detected_time: int
    first_detected_ist: str = ""
    last_updated_time: int
    last_updated_ist: str = ""
    
    # Sweep details
    sweep: SweepRecord = Field(default_factory=SweepRecord)
    
    # Transparency
    observed_evidence: List[str] = Field(default_factory=list)
    invalidation_criteria: str = ""
    is_data_enhanced: bool = False            # True if volume profile / order book was integrated


class LiquidityRadarSummary(BaseModel):
    nearest_bsl: List[LiquidityZone] = Field(default_factory=list)      # Up to 3
    nearest_ssl: List[LiquidityZone] = Field(default_factory=list)      # Up to 3
    strongest_active_zone: Optional[LiquidityZone] = None
    nearest_target_above: Optional[LiquidityZone] = None
    nearest_target_below: Optional[LiquidityZone] = None
    recent_sweeps: List[LiquidityZone] = Field(default_factory=list)


class LiquidityIntelligenceResult(BaseModel):
    timeframe: str
    current_price: float
    zones: List[LiquidityZone] = Field(default_factory=list)
    radar: LiquidityRadarSummary
    market_context_observations: List[str] = Field(default_factory=list)
    data_disclaimer: str = (
        "Model-derived liquidity estimate based on price-action clustering, swing structure, and ATR. "
        "No proprietary broker stop-loss feeds or synthetic order-book depth data are fabricated."
    )


# ---------------------------------------------------------------------------
# Core Detection Functions
# ---------------------------------------------------------------------------

def detect_raw_liquidity_levels(
    candles: List[Candle],
    timeframe: str,
    config: Optional[AnalysisConfig] = None
) -> List[Dict[str, Any]]:
    """
    Extract raw potential liquidity levels from swings, equal highs/lows,
    high/low sessions, and consolidation extremes.
    """
    if len(candles) < 10:
        return []

    if config is None:
        config = AnalysisConfig()

    atr_val = _atr(candles, 14)
    # Dynamic tolerance based on ATR: 0.25 * ATR
    tol = max(0.25, 0.25 * atr_val)

    swings = find_swings(candles, timeframe, config.swing_window)
    raw_levels: List[Dict[str, Any]] = []

    # 1. Swings Highs (Potential BSL)
    for s in swings:
        if s.type == "high":
            raw_levels.append({
                "type": "BSL",
                "price": s.price,
                "time": s.time,
                "ist_time": s.ist_time,
                "source": f"{timeframe} Swing High",
                "weight": 1.0,
                "timeframe": timeframe
            })
        elif s.type == "low":
            raw_levels.append({
                "type": "SSL",
                "price": s.price,
                "time": s.time,
                "ist_time": s.ist_time,
                "source": f"{timeframe} Swing Low",
                "weight": 1.0,
                "timeframe": timeframe
            })

    # 2. Daily Extremes / Session Bounds if available
    # Check highest and lowest of recent 24h chunk
    recent_24h_bars = min(len(candles), 48 if timeframe in ["30M", "15M", "5M"] else 24)
    if recent_24h_bars > 0:
        chunk = candles[-recent_24h_bars:]
        h_bar = max(chunk, key=lambda c: c.high)
        l_bar = min(chunk, key=lambda c: c.low)
        raw_levels.append({
            "type": "BSL",
            "price": h_bar.high,
            "time": h_bar.time,
            "ist_time": h_bar.ist_time,
            "source": f"24h Session High ({timeframe})",
            "weight": 1.2,
            "timeframe": timeframe
        })
        raw_levels.append({
            "type": "SSL",
            "price": l_bar.low,
            "time": l_bar.time,
            "ist_time": l_bar.ist_time,
            "source": f"24h Session Low ({timeframe})",
            "weight": 1.2,
            "timeframe": timeframe
        })

    return raw_levels


def cluster_liquidity_zones(
    raw_levels: List[Dict[str, Any]],
    current_price: float,
    current_candles: List[Candle],
    timeframe: str,
    atr_val: float
) -> List[LiquidityZone]:
    """
    Cluster nearby raw levels into structured zones within dynamic ATR bands.
    Eliminates dozens of redundant horizontal lines.
    """
    if not raw_levels:
        return []

    # Dynamic clustering bandwidth: 0.5 * ATR (minimum 0.40 USD for gold)
    cluster_bandwidth = max(0.40, 0.50 * atr_val)

    # Separate BSL and SSL
    bsl_items = sorted([lvl for lvl in raw_levels if lvl["type"] == "BSL"], key=lambda x: x["price"])
    ssl_items = sorted([lvl for lvl in raw_levels if lvl["type"] == "SSL"], key=lambda x: x["price"])

    clusters: List[LiquidityZone] = []
    zone_counter = 1

    for group_type, items in [("BSL", bsl_items), ("SSL", ssl_items)]:
        if not items:
            continue

        current_cluster: List[Dict[str, Any]] = [items[0]]

        for item in items[1:]:
            # If within bandwidth of cluster center or range
            if abs(item["price"] - current_cluster[-1]["price"]) <= cluster_bandwidth:
                current_cluster.append(item)
            else:
                # Flush cluster
                zone = _create_zone_from_cluster(current_cluster, group_type, current_price, current_candles, timeframe, atr_val, zone_counter)
                if zone:
                    clusters.append(zone)
                    zone_counter += 1
                current_cluster = [item]

        if current_cluster:
            zone = _create_zone_from_cluster(current_cluster, group_type, current_price, current_candles, timeframe, atr_val, zone_counter)
            if zone:
                clusters.append(zone)
                zone_counter += 1

    return clusters


def _create_zone_from_cluster(
    cluster_items: List[Dict[str, Any]],
    zone_type: str,
    current_price: float,
    candles: List[Candle],
    timeframe: str,
    atr_val: float,
    zone_idx: int
) -> Optional[LiquidityZone]:
    """Calculate zone boundaries, touch counts, touches, score, and sweep status."""
    if not cluster_items:
        return None

    prices = [item["price"] for item in cluster_items]
    min_p = min(prices)
    max_p = max(prices)
    avg_p = sum(prices) / len(prices)

    # Zone width padding: at least 0.20 * ATR buffer
    buffer = max(0.15, 0.15 * atr_val)
    top = round(max_p + buffer, 2)
    bottom = round(min_p - buffer, 2)
    center = round(avg_p, 2)

    # First detected and last updated times
    times = [item["time"] for item in cluster_items]
    first_time = min(times)
    last_time = max(times)
    first_ist = next((i.get("ist_time") for i in cluster_items if i.get("time") == first_time and i.get("ist_time")), "") or ""
    last_ist = next((i.get("ist_time") for i in cluster_items if i.get("time") == last_time and i.get("ist_time")), "") or ""

    # Supporting sources and timeframes
    sources = list(set(item["source"] for item in cluster_items))
    tfs = list(set(item.get("timeframe", timeframe) for item in cluster_items))

    # Evaluate touches & sweep behavior against subsequent candles
    touch_count = len(cluster_items)
    is_swept = False
    sweep_record = SweepRecord()
    is_mitigated = False
    is_approached = False

    # Check if price approached or breached the zone
    dist = round(center - current_price, 2)
    dist_pct = round((dist / current_price) * 100, 3) if current_price > 0 else 0.0

    # Scan candles after first_time to evaluate sweep vs breakout
    candles_after = [c for c in candles if c.time >= first_time]
    for c in candles_after:
        if zone_type == "BSL":
            # Pierced above top
            if c.high > top:
                sweep_record.breached = True
                sweep_record.breach_time = c.time
                sweep_record.breach_ist = c.ist_time
                sweep_record.breach_price = round(c.high, 2)
                excursion = round(c.high - top, 2)
                if excursion > sweep_record.max_excursion:
                    sweep_record.max_excursion = excursion

                # Did candle close back inside/below top? (Rejection = Sweep)
                if c.close <= top:
                    sweep_record.re_entered = True
                    sweep_record.confirmed_sweep = True
                    is_swept = True
                else:
                    # Closed above = sustained breakout / invalidation of liquidity pool
                    sweep_record.is_sustained_breakout = True
        elif zone_type == "SSL":
            # Pierced below bottom
            if c.low < bottom:
                sweep_record.breached = True
                sweep_record.breach_time = c.time
                sweep_record.breach_ist = c.ist_time
                sweep_record.breach_price = round(c.low, 2)
                excursion = round(bottom - c.low, 2)
                if excursion > sweep_record.max_excursion:
                    sweep_record.max_excursion = excursion

                # Did candle close back inside/above bottom? (Rejection = Sweep)
                if c.close >= bottom:
                    sweep_record.re_entered = True
                    sweep_record.confirmed_sweep = True
                    is_swept = True
                else:
                    # Closed below = sustained breakout
                    sweep_record.is_sustained_breakout = True

    # Determine status
    if sweep_record.is_sustained_breakout:
        status: ZoneStatus = "INVALIDATED"
    elif sweep_record.confirmed_sweep:
        status = "SWEPT"
    elif bottom <= current_price <= top:
        status = "APPROACHED"
    elif abs(dist) <= (1.2 * atr_val):
        status = "APPROACHED"
    else:
        status = "ACTIVE"

    # Score calculation (0 - 100)
    score_breakdown = _calculate_liquidity_score(
        zone_type=zone_type,
        cluster_count=len(cluster_items),
        confluence_tfs=tfs,
        status=status,
        dist=dist,
        atr_val=atr_val,
        is_swept=is_swept,
        is_breakout=sweep_record.is_sustained_breakout
    )

    # Classify whether Internal (IRL) or External (ERL)
    # If the zone is outside the recent high/low range, it is ERL; otherwise IRL
    recent_high = max((c.high for c in candles[-30:]), default=top)
    recent_low = min((c.low for c in candles[-30:]), default=bottom)
    
    final_type: LiquidityZoneType = zone_type  # type: ignore
    if center >= recent_high or center <= recent_low:
        sub_desc = f"External {zone_type}"
    else:
        sub_desc = f"Internal {zone_type}"

    label = f"{timeframe} {sub_desc} ({center})"

    invalidation_rule = (
        f"A closed candle body above {top} invalidates BSL resting liquidity"
        if zone_type == "BSL"
        else f"A closed candle body below {bottom} invalidates SSL resting liquidity"
    )

    return LiquidityZone(
        id=f"liq_{zone_type.lower()}_{timeframe.lower()}_{int(center * 100)}_{zone_idx}",
        type=final_type,
        label=label,
        price=center,
        top=top,
        bottom=bottom,
        timeframe=timeframe,
        supporting_timeframes=tfs,
        confluence_count=len(tfs),
        distance=dist,
        distance_pct=dist_pct,
        score=score_breakdown.total_score,
        confidence=score_breakdown.confidence,
        score_breakdown=score_breakdown,
        status=status,
        touch_count=touch_count,
        untested=(status == "ACTIVE"),
        first_detected_time=first_time,
        first_detected_ist=first_ist,
        last_updated_time=last_time,
        last_updated_ist=last_ist,
        sweep=sweep_record,
        observed_evidence=sources,
        invalidation_criteria=invalidation_rule,
        is_data_enhanced=False
    )


def _calculate_liquidity_score(
    zone_type: str,
    cluster_count: int,
    confluence_tfs: List[str],
    status: ZoneStatus,
    dist: float,
    atr_val: float,
    is_swept: bool,
    is_breakout: bool
) -> LiquidityScoreBreakdown:
    """
    Score zone from 0 to 100 using measurable factors:
    1. Cluster density (up to 30 pts)
    2. Multi-timeframe confluence (up to 25 pts)
    3. Proximity / Recency (up to 20 pts)
    4. Freshness / Untested state (up to 25 pts)
    """
    factors: List[LiquiditySubFactor] = []

    # Factor 1: Cluster density & touch count (Max 30)
    density_pts = min(30.0, 15.0 + (cluster_count * 5.0))
    factors.append(LiquiditySubFactor(
        name="Cluster Density",
        points=round(density_pts, 1),
        max_points=30.0,
        description=f"{cluster_count} clustered structural swing points within ATR boundary."
    ))

    # Factor 2: Multi-timeframe confluence (Max 25)
    tf_weights = {"1D": 15.0, "4H": 12.0, "1H": 8.0, "30M": 5.0, "15M": 4.0, "5M": 3.0, "1M": 2.0}
    confluence_pts = min(25.0, sum(tf_weights.get(tf, 4.0) for tf in confluence_tfs))
    factors.append(LiquiditySubFactor(
        name="Timeframe Confluence",
        points=round(confluence_pts, 1),
        max_points=25.0,
        description=f"Supported by {len(confluence_tfs)} timeframe(s): {', '.join(confluence_tfs)}."
    ))

    # Factor 3: Proximity / Relevance (Max 20)
    # Zones within 2 to 6 ATRs get full proximity score; extremely distant zones get penalized
    atr_dist = abs(dist) / max(0.5, atr_val)
    if atr_dist <= 2.0:
        prox_pts = 20.0
    elif atr_dist <= 5.0:
        prox_pts = 15.0
    elif atr_dist <= 10.0:
        prox_pts = 10.0
    else:
        prox_pts = 5.0
    factors.append(LiquiditySubFactor(
        name="Price Proximity",
        points=round(prox_pts, 1),
        max_points=20.0,
        description=f"Distance {abs(dist):.2f} USD ({atr_dist:.1f} ATR units from price)."
    ))

    # Factor 4: Freshness / State (Max 25)
    if is_breakout:
        fresh_pts = 0.0
        fresh_desc = "Invalidated: price cleanly broke through and closed beyond pool."
    elif is_swept:
        fresh_pts = 8.0
        fresh_desc = "Swept: liquidity already taken; lower probability of immediate restop."
    elif status == "APPROACHED":
        fresh_pts = 22.0
        fresh_desc = "Approached: actively testing entry boundary."
    else:
        fresh_pts = 25.0
        fresh_desc = "Untested & pristine: maximum resting stop liquidity assumed."

    factors.append(LiquiditySubFactor(
        name="Freshness State",
        points=round(fresh_pts, 1),
        max_points=25.0,
        description=fresh_desc
    ))

    total = int(round(sum(f.points for f in factors)))
    total = max(0, min(100, total))

    if total >= 80:
        confidence = "EXTREME"
    elif total >= 65:
        confidence = "HIGH"
    elif total >= 45:
        confidence = "MODERATE"
    else:
        confidence = "LOW"

    return LiquidityScoreBreakdown(
        total_score=total,
        confidence=confidence,
        factors=factors
    )


# ---------------------------------------------------------------------------
# Multi-Timeframe Liquidity Aggregator
# ---------------------------------------------------------------------------

def analyze_liquidity_intelligence(
    candles_by_tf: Dict[str, List[Candle]],
    current_timeframe: str = "1H",
    config: Optional[AnalysisConfig] = None
) -> LiquidityIntelligenceResult:
    """
    Main entry point for Hidden Liquidity Intelligence.
    Extracts, merges, and scores liquidity across all available timeframes.
    """
    if config is None:
        config = AnalysisConfig()

    curr_tf = current_timeframe.upper()
    primary_candles = candles_by_tf.get(curr_tf, [])
    current_price = primary_candles[-1].close if primary_candles else 0.0
    atr_val = _atr(primary_candles, 14) if primary_candles else 1.0

    raw_all_levels: List[Dict[str, Any]] = []

    # Gather raw levels across all available TFs
    for tf_key, t_candles in candles_by_tf.items():
        if t_candles and len(t_candles) >= 10:
            extracted = detect_raw_liquidity_levels(t_candles, tf_key, config)
            raw_all_levels.extend(extracted)

    # Cluster into coherent zones
    zones = cluster_liquidity_zones(raw_all_levels, current_price, primary_candles, curr_tf, atr_val)

    # Sort zones by price descending
    zones = sorted(zones, key=lambda z: z.price, reverse=True)

    # Build Liquidity Radar
    bsl_zones = [z for z in zones if z.type in ["BSL", "ERL"] and z.distance > 0 and z.status != "INVALIDATED"]
    ssl_zones = [z for z in zones if z.type in ["SSL", "ERL"] and z.distance < 0 and z.status != "INVALIDATED"]

    # Sort BSL by distance ascending (nearest above)
    nearest_bsl = sorted(bsl_zones, key=lambda z: abs(z.distance))[:3]
    # Sort SSL by distance ascending (nearest below)
    nearest_ssl = sorted(ssl_zones, key=lambda z: abs(z.distance))[:3]

    active_zones = [z for z in zones if z.status == "ACTIVE"]
    strongest_zone = max(active_zones, key=lambda z: z.score, default=None) if active_zones else None

    nearest_above = nearest_bsl[0] if nearest_bsl else None
    nearest_below = nearest_ssl[0] if nearest_ssl else None

    recent_sweeps = [z for z in zones if z.status == "SWEPT" or z.sweep.confirmed_sweep][:4]

    radar = LiquidityRadarSummary(
        nearest_bsl=nearest_bsl,
        nearest_ssl=nearest_ssl,
        strongest_active_zone=strongest_zone,
        nearest_target_above=nearest_above,
        nearest_target_below=nearest_below,
        recent_sweeps=recent_sweeps
    )

    # Contextual Observations
    observations: List[str] = []
    if nearest_above:
        observations.append(
            f"Nearest Buy-Side Pool: {nearest_above.label} at ${nearest_above.price:.2f} "
            f"(+{nearest_above.distance:.2f} USD, Score: {nearest_above.score}/100)"
        )
    if nearest_below:
        observations.append(
            f"Nearest Sell-Side Pool: {nearest_below.label} at ${nearest_below.price:.2f} "
            f"({nearest_below.distance:.2f} USD, Score: {nearest_below.score}/100)"
        )

    if strongest_zone:
        observations.append(
            f"Dominant Liquidity Magnet: {strongest_zone.label} with {strongest_zone.confluence_count} TF confluence "
            f"(Score: {strongest_zone.score}/100, Status: {strongest_zone.status})"
        )

    for sw in recent_sweeps:
        observations.append(
            f"Confirmed Sweep: {sw.label} was swept with max excursion of ${sw.sweep.max_excursion:.2f} "
            f"before rejecting back inside."
        )

    return LiquidityIntelligenceResult(
        timeframe=curr_tf,
        current_price=current_price,
        zones=zones,
        radar=radar,
        market_context_observations=observations
    )
