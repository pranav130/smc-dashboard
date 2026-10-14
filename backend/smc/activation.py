"""
Key-Level Activation & Trade-Readiness Watchlist Engine.

Translates market conditions into a rule-based attention filter:
- INACTIVE: Price is not near a relevant level.
- APPROACHING: Price is nearing a significant Daily/4H FVG, support/resistance level or liquidity area.
- AT KEY LEVEL: Price has entered or reached the defined level zone.
- REACTION DEVELOPING: A relevant reaction, liquidity sweep or displacement event has been detected.
- SETUP TO INSPECT: A potentially relevant 1H/30M trendline breakout or breakdown has occurred near the important level.
- CHECKLIST REVIEW: The detected evidence warrants checking the user's trading checklist.
- INVALIDATED / PASSED: The level has been closed through or invalidated under explicit rules.

All states are descriptive market observations — NO automated buy/sell instructions.
"""
from typing import List, Dict, Any, Optional, Tuple
import time
from backend.smc.models import (
    Candle, FairValueGap, OrderBlock, LiquidityLevel, Trendline,
    BreakOfStructure, DisplacementCandle, ActivationState, CanonicalState,
    ChecklistItem, WatchlistEntry, WatchlistAlert, AnalysisConfig
)
from backend.smc.structure import _atr


class AlertStore:
    """
    Centralized in-memory alert manager with deduplication, configurable cooldown,
    and acknowledgment tracking.
    
    Alert Policy:
    - Routine approaching or testing of zones (APPROACHING, AT KEY LEVEL, REACTION DEVELOPING)
      remain quietly tracked in the Watchlist cards without disruptive notifications.
    - Active transitions (SETUP TO INSPECT, CHECKLIST REVIEW / ACTIVE, EXTREME, CRITICAL_RISK)
      trigger persistent alerts.
    - Escalation of severity breaks cooldown immediately.
    """
STATE_SEVERITY: Dict[str, int] = {
    "WAITING": 0,
    "INACTIVE": 0,
    "APPROACHING": 1,
    "AT LEVEL": 2,
    "AT KEY LEVEL": 2,
    "REACTION DEVELOPING": 3,
    "SETUP TO INSPECT": 4,
    "CHECKLIST REVIEW": 5,
    "EXTREME": 6,
    "PASSED / INVALIDATED": -1,
    "INVALIDATED / PASSED": -1,
    "SWEPT / MITIGATED": -1,
}


class AlertStore:
    """
    Central Alert Engine for Key-Level and Setup State Transitions.
    Deduplicates events by level_id and state, enforcing configurable cooldown.
    """
    def __init__(self, cooldown_seconds: int = 300):
        self._alerts: Dict[str, WatchlistAlert] = {}
        self._last_state_hash: Dict[str, str] = {}
        self._last_alert_time: Dict[str, float] = {}
        self._last_severity: Dict[str, int] = {}
        self.cooldown_seconds = cooldown_seconds

    def get_alerts(self, include_acknowledged: bool = False) -> List[WatchlistAlert]:
        alerts = list(self._alerts.values())
        if not include_acknowledged:
            alerts = [a for a in alerts if not a.acknowledged]
        alerts.sort(key=lambda a: a.timestamp, reverse=True)
        return alerts

    def acknowledge_alert(self, alert_id: str) -> bool:
        if alert_id in self._alerts:
            self._alerts[alert_id].acknowledged = True
            return True
        return False

    def dismiss_all(self):
        for a in self._alerts.values():
            a.acknowledged = True

    def register_transition(
        self,
        level_id: str,
        level_name: str,
        timeframe: str,
        state: ActivationState,
        evidence: List[str],
        timestamp: int,
        ist_time: str,
        is_stale: bool,
        is_extreme: bool = False,
        only_actionable: bool = False
    ) -> Optional[WatchlistAlert]:
        # Stale feed handling: stale data must not produce new active alerts
        if is_stale and only_actionable:
            return None

        # Alert policy: optionally filter to actionable transitions only
        if only_actionable:
            notify_states = ["SETUP TO INSPECT", "CHECKLIST REVIEW"]
            if state not in notify_states and not is_extreme:
                return None

        alert_severity_state = "EXTREME" if is_extreme else state
        state_hash = f"{level_id}_{alert_severity_state}"
        t_now = float(timestamp) if timestamp > 0 else time.time()

        last_hash = self._last_state_hash.get(level_id)
        last_time = self._last_alert_time.get(level_id, 0.0)
        last_sev = self._last_severity.get(level_id, 0)
        curr_sev = STATE_SEVERITY.get(alert_severity_state, 0)

        # Cooldown & deduplication:
        if (t_now - last_time) < self.cooldown_seconds:
            # Exact duplicate within cooldown window -> suppress
            if last_hash == state_hash:
                return None
            # If not an escalation to a strictly higher severity (e.g. oscillating between watch states) -> suppress
            if curr_sev <= last_sev and not (last_sev < 0 and curr_sev > 0):
                return None

        # Record new alert
        self._last_state_hash[level_id] = state_hash
        self._last_alert_time[level_id] = t_now
        self._last_severity[level_id] = curr_sev
        alert_id = f"alt_{level_id}_{alert_severity_state.lower().replace(' ', '_')}_{int(t_now)}"

        prefix = "[EXTREME CONFLUENCE]" if is_extreme else (
            "[ACTIVE SETUP]" if state == "CHECKLIST REVIEW" else (
                "[SETUP TO INSPECT]" if state == "SETUP TO INSPECT" else f"[{state}]"
            )
        )
        alert_msg = f"{prefix} {level_name} ({timeframe}) — {evidence[0] if evidence else 'State activated'}"

        alert = WatchlistAlert(
            id=alert_id,
            level_id=level_id,
            level_name=level_name,
            timeframe=timeframe,
            state=state,
            message=alert_msg,
            evidence=evidence,
            timestamp=int(t_now),
            ist_time=ist_time,
            acknowledged=False,
            is_stale_suppressed=is_stale
        )
        self._alerts[alert_id] = alert
        return alert


# Global alert store instance
global_alert_store = AlertStore()


def _is_price_in_zone(price: float, top: float, bottom: float, buffer: float = 0.0) -> bool:
    return (bottom - buffer) <= price <= (top + buffer)


def _distance_to_zone(price: float, top: float, bottom: float) -> Tuple[float, float]:
    """
    Returns (abs_distance, signed_distance) to zone boundaries.
    Signed distance is positive if zone is above price (+ overhead),
    negative if zone is below price (- underneath), 0.0 if inside.
    """
    if price < bottom:
        # Zone is above current market price
        d = bottom - price
        return d, d
    elif price > top:
        # Zone is below current market price
        d = top - price
        return abs(d), d
    else:
        return 0.0, 0.0


def evaluate_level_activation(
    level_id: str,
    name: str,
    level_type: str,
    timeframe: str,
    direction: Optional[str],
    price: float,
    top: float,
    bottom: float,
    freshness: str,
    current_price: float,
    current_candles: List[Candle],
    swings: Any,
    bos_signals: List[BreakOfStructure],
    displacement_candles: List[DisplacementCandle],
    supporting_fvgs: List[FairValueGap],
    liquidity_levels: List[LiquidityLevel],
    trendlines: List[Trendline],
    opposing_warnings: List[str],
    atr_val: float,
    config: AnalysisConfig,
    is_stale: bool = False
) -> WatchlistEntry:
    """
    Evaluate the activation state and checklist progress for a single key level.
    """
    zone_width = max(0.01, round(top - bottom, 2)) if (top and bottom) else 0.01
    midpoint = round((top + bottom) / 2.0, 2) if (top and bottom) else price

    # Distance to zone or level: positive = above price, negative = below price
    if top is not None and bottom is not None:
        raw_dist, signed_dist = _distance_to_zone(current_price, top, bottom)
        dist_to_mid = midpoint - current_price
    else:
        signed_dist = price - current_price
        dist_to_mid = signed_dist

    dist_abs = abs(signed_dist)
    dist_pct = round((dist_to_mid / current_price) * 100.0, 2) if current_price else 0.0

    # Configurable thresholds using ATR and zone width
    approach_threshold = max(zone_width, config.activation_approach_atr_multiplier * atr_val)
    at_level_buffer = config.activation_at_level_atr_multiplier * atr_val

    # 1. Checklist items initialization
    checklist: List[ChecklistItem] = [
        ChecklistItem(
            id="htf_zone_reached",
            name="1. Key Level In-Zone / Tested",
            description="Price reaches or enters the defined key level boundaries",
            satisfied=False,
            evidence="Pending",
            timeframe=timeframe
        ),
        ChecklistItem(
            id="liquidity_reaction",
            name="2. Liquidity Sweep or Rejection",
            description="Price sweeps resting liquidity or prints a rejection wick/displacement off the level",
            satisfied=False,
            evidence="Pending"
        ),
        ChecklistItem(
            id="trendline_break",
            name="3. 1H / 30M Trendline Breakout",
            description="A validated trendline breakout or breakdown confirmed by candle close",
            satisfied=False,
            evidence="Pending"
        ),
        ChecklistItem(
            id="displacement_fvg",
            name="4. Displacement & Supporting LTF FVG",
            description="High-momentum displacement candle and supporting FVG confirm participation",
            satisfied=False,
            evidence="Pending"
        ),
        ChecklistItem(
            id="clean_path",
            name="5. Clear Structural Path",
            description="No opposing higher-timeframe FVG directly blocking the trade within warning threshold",
            satisfied=True,
            evidence="Clean path verified"
        ),
    ]

    evidence: List[str] = []
    state: ActivationState = CanonicalState("WAITING")
    state_reason: str = ""
    last_event_time: Optional[int] = None
    last_event_ist: Optional[str] = None
    relevant_event_str: Optional[str] = None

    # Check opposing zones
    opposing_warning_str = None
    if opposing_warnings:
        # Check if there is an opposing warning relevant to this level
        for w in opposing_warnings:
            if direction == "bullish" and "Bearish" in w and "overhead" in w:
                opposing_warning_str = w
                checklist[4].satisfied = False
                checklist[4].evidence = w
                break
            elif direction == "bearish" and "Bullish" in w and "support" in w:
                opposing_warning_str = w
                checklist[4].satisfied = False
                checklist[4].evidence = w
                break

    # Check if level is invalidated
    is_invalidated = False
    if freshness.lower() == "fully_mitigated" and dist_abs > (approach_threshold * 1.5):
        is_invalidated = True
        state = CanonicalState("PASSED / INVALIDATED")
        state_reason = f"Level was fully mitigated and price has traded beyond approach threshold (${dist_abs:.2f} away)."
        evidence.append(f"Fully mitigated at past timestamp; current distance ${dist_abs:.2f}")
        relevant_event_str = "Level fully mitigated and passed"

    if not is_invalidated:
        # Step A: Check In-Zone vs Approaching vs Waiting
        in_zone = False
        if top is not None and bottom is not None:
            in_zone = _is_price_in_zone(current_price, top, bottom, buffer=at_level_buffer)
        else:
            in_zone = dist_abs <= at_level_buffer

        is_approaching = dist_abs <= approach_threshold

        if in_zone:
            checklist[0].satisfied = True
            checklist[0].evidence = f"Price at ${current_price:.2f} is within zone [${bottom:.2f} - ${top:.2f}] (buffer: ${at_level_buffer:.2f})"
            state = CanonicalState("AT LEVEL")
            state_reason = f"Price has reached the defined key level zone (${bottom:.2f} - ${top:.2f})."
            evidence.append(checklist[0].evidence)
            relevant_event_str = f"Price reached level zone (${bottom:.2f} - ${top:.2f})"
            if current_candles:
                last_event_time = current_candles[-1].time
                last_event_ist = current_candles[-1].ist_time
        elif is_approaching:
            state = CanonicalState("APPROACHING")
            state_reason = f"Price (${current_price:.2f}) is within ${approach_threshold:.2f} (ATR-derived) of level zone."
            evidence.append(f"Approaching distance: ${dist_abs:.2f} (Threshold: ${approach_threshold:.2f})")
            relevant_event_str = f"Approaching level (${dist_abs:.2f} away)"
            if current_candles:
                last_event_time = current_candles[-1].time
                last_event_ist = current_candles[-1].ist_time
        else:
            state = CanonicalState("WAITING")
            state_reason = f"Price (${current_price:.2f}) is ${dist_abs:.2f} away, beyond approaching threshold (${approach_threshold:.2f})."

        # Step B: If in zone or approaching, evaluate Step 2 (Liquidity Sweep or Rejection Structure)
        if in_zone or is_approaching:
            recent_candles = current_candles[-config.activation_sweep_recency_bars:] if current_candles else []
            sweep_found = False
            for liq in liquidity_levels:
                if liq.swept:
                    # Check if swept near this level price
                    if abs(liq.price - midpoint) <= approach_threshold:
                        sweep_found = True
                        checklist[1].satisfied = True
                        checklist[1].evidence = f"{liq.label} swept at ${liq.price:.2f} (Time: {liq.sweep_ist or 'recent'})"
                        evidence.append(checklist[1].evidence)
                        relevant_event_str = f"Confirmed sweep of {liq.label} at ${liq.price:.2f}"
                        if liq.sweep_time:
                            last_event_time = liq.sweep_time
                            last_event_ist = liq.sweep_ist
                        break

            # If no formal sweep, check for rejection candle at the zone
            if not sweep_found and in_zone and recent_candles:
                for rc in recent_candles[-3:]:
                    # Require closed candle: provisional forming candle cannot confirm rejection
                    if rc.is_forming:
                        continue
                    body = abs(rc.close - rc.open)
                    upper_wick = rc.high - max(rc.close, rc.open)
                    lower_wick = min(rc.close, rc.open) - rc.low
                    # Bullish rejection off support
                    if direction == "bullish" and lower_wick >= 1.5 * max(body, 0.2) and lower_wick >= 0.5 * atr_val:
                        sweep_found = True
                        checklist[1].satisfied = True
                        checklist[1].evidence = f"Long rejection lower wick (${lower_wick:.2f}) printed at ${rc.low:.2f}"
                        evidence.append(checklist[1].evidence)
                        relevant_event_str = f"Bullish rejection wick (${lower_wick:.2f}) off support"
                        last_event_time = rc.time
                        last_event_ist = rc.ist_time
                        break
                    # Bearish rejection off resistance
                    elif direction == "bearish" and upper_wick >= 1.5 * max(body, 0.2) and upper_wick >= 0.5 * atr_val:
                        sweep_found = True
                        checklist[1].satisfied = True
                        checklist[1].evidence = f"Long rejection upper wick (${upper_wick:.2f}) printed at ${rc.high:.2f}"
                        evidence.append(checklist[1].evidence)
                        relevant_event_str = f"Bearish rejection wick (${upper_wick:.2f}) off resistance"
                        last_event_time = rc.time
                        last_event_ist = rc.ist_time
                        break

            if sweep_found and in_zone:
                state = CanonicalState("REACTION DEVELOPING")
                state_reason = f"Price at key level zone with confirmed liquidity reaction / rejection."

            # Step C: Check Trendline Breakout (Step 3: SETUP TO INSPECT)
            trendline_break_found = False
            if sweep_found or in_zone:
                recent_tl_window = config.activation_break_recency_bars
                for tl in trendlines:
                    if tl.broken and tl.breakout_time:
                        # Check recency
                        if current_candles and (current_candles[-1].time - tl.breakout_time) <= (recent_tl_window * 3600):
                            # Directional alignment:
                            # Bullish setup (buying at support) requires breakout of descending RESISTANCE trendline
                            # Bearish setup (selling at resistance) requires breakdown of ascending SUPPORT trendline
                            if direction == "bullish" and tl.direction != "resistance":
                                continue
                            if direction == "bearish" and tl.direction != "support":
                                continue

                            trendline_break_found = True
                            checklist[2].satisfied = True
                            checklist[2].evidence = (
                                f"{tl.timeframe} {tl.direction.upper()} trendline broken at {tl.breakout_ist or 'recent'} "
                                f"({'confirmed by close' if tl.break_confirmed_by_close else 'wick break'})"
                            )
                            evidence.append(checklist[2].evidence)
                            sup_text = f" ({tl.structural_support_note})" if tl.structural_support_note else ""
                            relevant_event_str = f"{tl.timeframe} trendline breakout{sup_text}"
                            last_event_time = tl.breakout_time
                            last_event_ist = tl.breakout_ist
                            break

            if trendline_break_found:
                state = CanonicalState("SETUP TO INSPECT")
                state_reason = f"Key level reaction followed by validated {checklist[2].timeframe or '1H/30M'} trendline breakout."

            # Step D: Check Displacement & Supporting LTF FVG (Step 4 & 5: CHECKLIST REVIEW)
            disp_or_fvg_found = False
            if trendline_break_found:
                # Check recent displacement candle
                if displacement_candles:
                    latest_disp = displacement_candles[-1]
                    if current_candles and (current_candles[-1].time - latest_disp.time) <= (6 * 3600):
                        disp_or_fvg_found = True
                        checklist[3].satisfied = True
                        checklist[3].evidence = f"{latest_disp.direction.capitalize()} displacement candle (ratio {latest_disp.body_atr_ratio}x ATR) at {latest_disp.ist_time}"
                        evidence.append(checklist[3].evidence)
                        relevant_event_str = f"{latest_disp.direction.capitalize()} displacement candle ({latest_disp.body_atr_ratio}x ATR)"
                        last_event_time = latest_disp.time
                        last_event_ist = latest_disp.ist_time

                # Check recent supporting LTF FVG
                if not disp_or_fvg_found and supporting_fvgs:
                    for sf in supporting_fvgs[-3:]:
                        if not sf.mitigated and sf.direction == direction:
                            disp_or_fvg_found = True
                            checklist[3].satisfied = True
                            checklist[3].evidence = f"Supporting {sf.timeframe} {sf.direction} FVG [${sf.bottom:.2f} - ${sf.top:.2f}] formed"
                            evidence.append(checklist[3].evidence)
                            relevant_event_str = f"Supporting {sf.timeframe} {sf.direction} FVG formed"
                            break

            # If all 5 criteria are met, promote to CHECKLIST REVIEW (unless feed is stale)!
            if (
                checklist[0].satisfied and
                checklist[1].satisfied and
                checklist[2].satisfied and
                checklist[3].satisfied and
                checklist[4].satisfied
            ):
                if is_stale:
                    state = CanonicalState("SETUP TO INSPECT")
                    state_reason = "Full setup sequence detected, but market data feed is STALE (>60s). Retained in WATCH pending live data."
                else:
                    state = CanonicalState("CHECKLIST REVIEW")
                    state_reason = "Full SMC setup sequence detected. Evidence warrants manual checklist verification."

    # Priority determination:
    # High: 1D/4H with freshness and structural importance
    # Medium: Intermediate levels / LTF
    # Low: Secondary or mitigated levels
    priority = "Medium"
    priority_reason = "Intermediate market level under monitoring"
    score = 50

    if is_invalidated:
        priority = "Low"
        priority_reason = "Passed or fully mitigated level."
        score = 25
    elif timeframe in ["1D", "4H"]:
        if freshness in ["unmitigated", "unswept", "Active"]:
            priority = "High"
            priority_reason = f"High-priority {timeframe} HTF Level: Key structural boundary."
            score = 80
        else:
            priority = "Medium"
            priority_reason = f"Medium-priority {timeframe} Level: Partially tested HTF area."
            score = 65
    elif "Week" in name or "Day" in name:
        priority = "High"
        priority_reason = "High-priority Macro Liquidity: Untested resting orders."
        score = 85

    # Register alert transition in alert store
    t_event = current_candles[-1].time if current_candles else int(time.time())
    alert = global_alert_store.register_transition(
        level_id=level_id,
        level_name=name,
        timeframe=timeframe,
        state=state,
        evidence=evidence,
        timestamp=t_event,
        ist_time=(current_candles[-1].ist_time or "") if current_candles else "",
        is_stale=is_stale,
        only_actionable=True
    )

    return WatchlistEntry(
        level_id=level_id,
        name=name,
        type=level_type,
        timeframe=timeframe,
        direction=direction,
        price=midpoint,
        top=top,
        bottom=bottom,
        zone_width=zone_width,
        distance=round(signed_dist, 2),
        distance_pct=dist_pct,
        freshness=freshness,
        state=state,
        state_reason=state_reason,
        priority=priority,
        priority_reason=priority_reason,
        relevant_event=relevant_event_str,
        opposing_zone_nearby=opposing_warning_str,
        evidence=evidence,
        checklist=checklist,
        opposing_zone_warning=opposing_warning_str,
        last_event_time=last_event_time,
        last_event_ist=last_event_ist,
        score=score
    )


def generate_watchlist(
    current_price: float,
    current_candles: List[Candle],
    daily_fvgs: List[FairValueGap],
    h4_fvgs: List[FairValueGap],
    order_blocks: List[OrderBlock],
    liquidity_levels: List[LiquidityLevel],
    trendlines: List[Trendline],
    displacement_candles: List[DisplacementCandle],
    current_fvgs: List[FairValueGap],
    opposing_warnings: List[str],
    config: Optional[AnalysisConfig] = None,
    is_stale: bool = False
) -> Tuple[List[WatchlistEntry], List[WatchlistAlert]]:
    """
    Build the complete Trade-Readiness Watchlist across all significant market levels.
    """
    if config is None:
        config = AnalysisConfig()

    atr_val = _atr(current_candles, 14) if current_candles else 1.0
    entries: List[WatchlistEntry] = []

    # 1. Higher Timeframe FVGs (Daily & 4H)
    for f in (daily_fvgs + h4_fvgs):
        if f.mitigated:
            continue
        entry = evaluate_level_activation(
            level_id=f.id,
            name=f"{f.timeframe} {f.direction.capitalize()} FVG",
            level_type=f"{f.timeframe} FVG",
            timeframe=f.timeframe,
            direction=f.direction,
            price=f.midpoint,
            top=f.top,
            bottom=f.bottom,
            freshness=f.mitigation_level,
            current_price=current_price,
            current_candles=current_candles,
            swings=None,
            bos_signals=[],
            displacement_candles=displacement_candles,
            supporting_fvgs=current_fvgs,
            liquidity_levels=liquidity_levels,
            trendlines=trendlines,
            opposing_warnings=opposing_warnings,
            atr_val=atr_val,
            config=config,
            is_stale=is_stale
        )
        entries.append(entry)

    # 2. Key Order Blocks
    for ob in order_blocks:
        if ob.mitigated or ob.is_breaker:
            continue
        entry = evaluate_level_activation(
            level_id=ob.id,
            name=f"{ob.timeframe} {ob.direction.capitalize()} Order Block",
            level_type=f"{ob.timeframe} OB",
            timeframe=ob.timeframe,
            direction=ob.direction,
            price=ob.midpoint,
            top=ob.top,
            bottom=ob.bottom,
            freshness="unmitigated",
            current_price=current_price,
            current_candles=current_candles,
            swings=None,
            bos_signals=[],
            displacement_candles=displacement_candles,
            supporting_fvgs=current_fvgs,
            liquidity_levels=liquidity_levels,
            trendlines=trendlines,
            opposing_warnings=opposing_warnings,
            atr_val=atr_val,
            config=config,
            is_stale=is_stale
        )
        entries.append(entry)

    # 3. Major Liquidity Levels (PDH, PDL, PWH, PWL)
    for liq in liquidity_levels:
        if "Day" in liq.label or "Week" in liq.label:
            entry = evaluate_level_activation(
                level_id=f"liq_{liq.type}_{liq.time}",
                name=liq.label,
                level_type="Liquidity Pool",
                timeframe="1D" if "Day" in liq.label else "1W",
                direction="bearish" if "High" in liq.label else "bullish",
                price=liq.price,
                top=liq.price + 0.25,
                bottom=liq.price - 0.25,
                freshness="swept" if liq.swept else "unswept",
                current_price=current_price,
                current_candles=current_candles,
                swings=None,
                bos_signals=[],
                displacement_candles=displacement_candles,
                supporting_fvgs=current_fvgs,
                liquidity_levels=liquidity_levels,
                trendlines=trendlines,
                opposing_warnings=opposing_warnings,
                atr_val=atr_val,
                config=config,
                is_stale=is_stale
            )
            entries.append(entry)

    # Flag nearest level above and below
    above_entries = [e for e in entries if e.distance > 0]
    below_entries = [e for e in entries if e.distance < 0]

    above_entries.sort(key=lambda e: abs(e.distance))
    below_entries.sort(key=lambda e: abs(e.distance))

    if above_entries:
        above_entries[0].is_nearest_above = True
    if below_entries:
        below_entries[0].is_nearest_below = True

    # Sort prioritized:
    # 1. State priority: CHECKLIST REVIEW > SETUP TO INSPECT > REACTION DEVELOPING > AT KEY LEVEL > APPROACHING > INACTIVE > INVALIDATED
    state_weights = {
        "CHECKLIST REVIEW": 100,
        "SETUP TO INSPECT": 80,
        "REACTION DEVELOPING": 60,
        "AT LEVEL": 40,
        "AT KEY LEVEL": 40,
        "APPROACHING": 20,
        "WAITING": 0,
        "INACTIVE": 0,
        "PASSED / INVALIDATED": -10,
        "INVALIDATED / PASSED": -10,
    }
    priority_order = {"High": 3, "Medium": 2, "Low": 1}
    entries.sort(key=lambda e: (
        -state_weights.get(e.state, 0),
        -priority_order.get(e.priority, 1),
        abs(e.distance)
    ))

    # Get active unacknowledged alerts
    alerts = global_alert_store.get_alerts(include_acknowledged=False)

    return entries, alerts
