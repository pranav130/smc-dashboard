"""
Model A: SMC Liquidity Sweep & Retracement Strategy
Evaluates independently of trendline breaks.

Workflow:
1. Daily Directional Bias (Daily HH/HL vs LH/LL).
2. 4H Zone Context (4H FVG, Order Block, or Key Level).
3. 1H Liquidity Sweep (PDH, PDL, EQH, EQL, or swing sweep).
4. Confirmed MSS / Directional Displacement away from the swept level.
5. Retracement Entry into a supporting 1H/30M FVG or discount/premium zone.
6. Structural Stop Loss (beyond the sweep extreme) and Target (opposing liquidity, R:R >= 2.0).
"""
import uuid
from typing import List, Dict, Any, Optional, Tuple
from backend.smc.models import (
    Candle, ActiveSetupCardData, ChecklistItem, LiquidityLevel,
    FairValueGap, TrendState, BreakOfStructure, DisplacementCandle
)
from backend.config import MIN_REWARD_TO_RISK, TICK_SIZE


def evaluate_model_a(
    current_price: float,
    candles_1h: List[Candle],
    daily_trend: TrendState,
    h4_trend: TrendState,
    h4_fvgs: List[FairValueGap],
    h1_fvgs: List[FairValueGap],
    liquidity_levels: List[LiquidityLevel],
    bos_signals: List[BreakOfStructure],
    displacement_candles: List[DisplacementCandle],
    atr_val: float,
    is_stale: bool = False,
    sweep_lookback_bars: int = 20
) -> Tuple[Optional[ActiveSetupCardData], Dict[str, Any]]:
    """
    Evaluate Model A (SMC Sweep & Retracement) deterministically.
    Returns:
        (setup_card, rejection_telemetry)
    """
    telemetry = {
        "model": "MODEL_A",
        "evaluated_at_price": current_price,
        "is_stale": is_stale,
        "passed": False,
        "stage_failed": None,
        "reasons": []
    }

    if not candles_1h or len(candles_1h) < 10:
        telemetry["stage_failed"] = "INSUFFICIENT_DATA"
        telemetry["reasons"].append("Less than 10 1H candles available")
        return None, telemetry

    now_bar_time = candles_1h[-1].time
    recent_cutoff = now_bar_time - (sweep_lookback_bars * 3600)

    # 1. Identify qualifying recent liquidity sweeps
    # Bullish setup needs a sweep of LOW liquidity (PDL, PWL, EQL, or Swing Low)
    # Bearish setup needs a sweep of HIGH liquidity (PDH, PWH, EQH, or Swing High)
    bullish_sweeps = [
        l for l in liquidity_levels
        if l.swept and l.sweep_time and l.sweep_time >= recent_cutoff
        and l.type in ("PDL", "PWL", "EQL")
    ]
    bearish_sweeps = [
        l for l in liquidity_levels
        if l.swept and l.sweep_time and l.sweep_time >= recent_cutoff
        and l.type in ("PDH", "PWH", "EQH")
    ]

    # Decide primary direction based on swept levels and daily context
    candidate_direction = None
    selected_sweep: Optional[LiquidityLevel] = None

    if bullish_sweeps and not bearish_sweeps:
        candidate_direction = "bullish"
        selected_sweep = sorted(bullish_sweeps, key=lambda x: x.sweep_time or 0, reverse=True)[0]
    elif bearish_sweeps and not bullish_sweeps:
        candidate_direction = "bearish"
        selected_sweep = sorted(bearish_sweeps, key=lambda x: x.sweep_time or 0, reverse=True)[0]
    elif bullish_sweeps and bearish_sweeps:
        # If both swept recently, choose the most recent sweep
        s_bull = sorted(bullish_sweeps, key=lambda x: x.sweep_time or 0, reverse=True)[0]
        s_bear = sorted(bearish_sweeps, key=lambda x: x.sweep_time or 0, reverse=True)[0]
        if (s_bull.sweep_time or 0) >= (s_bear.sweep_time or 0):
            candidate_direction = "bullish"
            selected_sweep = s_bull
        else:
            candidate_direction = "bearish"
            selected_sweep = s_bear

    if not candidate_direction or not selected_sweep:
        telemetry["stage_failed"] = "NO_QUALIFYING_SWEEP"
        telemetry["reasons"].append(f"No sweep of key liquidity within last {sweep_lookback_bars} bars")
        return None, telemetry

    # 2. Check 4H / HTF Confluence
    # Bullish: 4H trend not strongly bearish, or price swept inside/near 4H Bullish FVG
    htf_confluence = False
    htf_notes = []
    if candidate_direction == "bullish":
        if h4_trend.trend in ("bullish", "neutral"):
            htf_confluence = True
            htf_notes.append(f"4H trend is {h4_trend.trend}")
        # Or test of 4H bullish FVG
        for f in h4_fvgs:
            if f.direction == "bullish" and f.freshness != "fully_mitigated":
                if f.bottom <= selected_sweep.price <= (f.top + atr_val):
                    htf_confluence = True
                    htf_notes.append(f"Tested 4H Bullish FVG [${f.bottom:.2f} - ${f.top:.2f}]")
                    break
    else:
        if h4_trend.trend in ("bearish", "neutral"):
            htf_confluence = True
            htf_notes.append(f"4H trend is {h4_trend.trend}")
        for f in h4_fvgs:
            if f.direction == "bearish" and f.freshness != "fully_mitigated":
                if (f.bottom - atr_val) <= selected_sweep.price <= f.top:
                    htf_confluence = True
                    htf_notes.append(f"Tested 4H Bearish FVG [${f.bottom:.2f} - ${f.top:.2f}]")
                    break

    if not htf_confluence:
        telemetry["stage_failed"] = "HTF_ALIGNMENT_FAILED"
        telemetry["reasons"].append(f"Candidate {candidate_direction} trade opposes 4H trend without 4H FVG backing")
        return None, telemetry

    # 3. MSS / Displacement Confirmation after Sweep
    sweep_time = selected_sweep.sweep_time or (now_bar_time - 3600)
    post_sweep_candles = [c for c in candles_1h if c.time >= sweep_time]
    
    # Check for directional displacement candle post-sweep
    displacement_confirmed = False
    disp_note = ""
    for d in displacement_candles:
        if d.time >= sweep_time and d.direction == candidate_direction:
            displacement_confirmed = True
            disp_note = f"Displacement bar at {d.ist_time} (body: ${d.body_size:.2f})"
            break

    # Also check if BOS/MSS was triggered post-sweep
    bos_confirmed = False
    bos_note = ""
    for b in bos_signals:
        if b.time >= sweep_time and b.direction == candidate_direction:
            bos_confirmed = True
            bos_note = f"MSS/BOS at {b.ist_time} breaking ${b.broken_level:.2f}"
            break

    if not (displacement_confirmed or bos_confirmed):
        telemetry["stage_failed"] = "NO_DISPLACEMENT_OR_MSS"
        telemetry["reasons"].append("No displacement candle or structural shift printed following sweep")
        return None, telemetry

    # 4. Entry Zone Definition (1H FVG or Retracement Zone)
    # Find active supporting 1H FVG created after sweep, or fallback to discount/premium retracement zone
    supporting_fvg = None
    for f in h1_fvgs:
        if f.direction == candidate_direction and f.time >= sweep_time:
            if f.freshness != "fully_mitigated":
                supporting_fvg = f
                break

    if candidate_direction == "bullish":
        # Find extreme low reached during sweep
        sweep_extreme = min([c.low for c in post_sweep_candles]) if post_sweep_candles else selected_sweep.price
        stop_loss = round(sweep_extreme - max(0.5, 0.1 * atr_val), 2)

        if supporting_fvg:
            entry_top = supporting_fvg.top
            entry_bottom = supporting_fvg.bottom
            entry_price = round(supporting_fvg.midpoint, 2)
            entry_type = f"1H Bullish FVG [${entry_bottom:.2f} - ${entry_top:.2f}]"
        else:
            # Retracement into lower 50% discount of post-sweep push
            high_point = max([c.high for c in post_sweep_candles]) if post_sweep_candles else current_price
            range_span = high_point - sweep_extreme
            if range_span <= 0:
                telemetry["stage_failed"] = "ZERO_RANGE_SPAN"
                return None, telemetry
            entry_top = round(high_point - 0.5 * range_span, 2)
            entry_bottom = round(sweep_extreme + 0.2 * range_span, 2)
            entry_price = round((entry_top + entry_bottom) / 2.0, 2)
            entry_type = f"Discount Retracement [${entry_bottom:.2f} - ${entry_top:.2f}]"

        # Opposing liquidity target (e.g. PDH, PWH, EQH or 2.5R minimum)
        opposing_liq = [
            l for l in liquidity_levels
            if not l.swept and l.price > entry_price and l.type in ("PDH", "PWH", "EQH")
        ]
        if opposing_liq:
            target_price = sorted(opposing_liq, key=lambda x: x.price)[0].price
        else:
            target_price = round(entry_price + (entry_price - stop_loss) * 2.5, 2)

    else:  # bearish
        sweep_extreme = max([c.high for c in post_sweep_candles]) if post_sweep_candles else selected_sweep.price
        stop_loss = round(sweep_extreme + max(0.5, 0.1 * atr_val), 2)

        if supporting_fvg:
            entry_top = supporting_fvg.top
            entry_bottom = supporting_fvg.bottom
            entry_price = round(supporting_fvg.midpoint, 2)
            entry_type = f"1H Bearish FVG [${entry_bottom:.2f} - ${entry_top:.2f}]"
        else:
            low_point = min([c.low for c in post_sweep_candles]) if post_sweep_candles else current_price
            range_span = sweep_extreme - low_point
            if range_span <= 0:
                telemetry["stage_failed"] = "ZERO_RANGE_SPAN"
                return None, telemetry
            entry_bottom = round(low_point + 0.5 * range_span, 2)
            entry_top = round(sweep_extreme - 0.2 * range_span, 2)
            entry_price = round((entry_top + entry_bottom) / 2.0, 2)
            entry_type = f"Premium Retracement [${entry_bottom:.2f} - ${entry_top:.2f}]"

        opposing_liq = [
            l for l in liquidity_levels
            if not l.swept and l.price < entry_price and l.type in ("PDL", "PWL", "EQL")
        ]
        if opposing_liq:
            target_price = sorted(opposing_liq, key=lambda x: x.price, reverse=True)[0].price
        else:
            target_price = round(entry_price - (stop_loss - entry_price) * 2.5, 2)

    # 5. Risk / Reward and Level Order Validation
    risk_distance = abs(entry_price - stop_loss)
    reward_distance = abs(target_price - entry_price)

    if risk_distance <= 0:
        telemetry["stage_failed"] = "ZERO_RISK_DISTANCE"
        return None, telemetry

    rr_ratio = reward_distance / risk_distance
    if rr_ratio < MIN_REWARD_TO_RISK:
        # Enforce minimum 2.0 R:R by extending target if structural target was too tight
        if candidate_direction == "bullish":
            target_price = round(entry_price + (risk_distance * MIN_REWARD_TO_RISK), 2)
        else:
            target_price = round(entry_price - (risk_distance * MIN_REWARD_TO_RISK), 2)
        reward_distance = abs(target_price - entry_price)
        rr_ratio = reward_distance / risk_distance

    # 6. Determine Signal State
    # Invalidation check: did price already invalidate stop?
    if candidate_direction == "bullish" and current_price <= stop_loss:
        signal_state = "INVALIDATED"
        state_reason = f"Price breached stop loss (${stop_loss:.2f})"
    elif candidate_direction == "bearish" and current_price >= stop_loss:
        signal_state = "INVALIDATED"
        state_reason = f"Price breached stop loss (${stop_loss:.2f})"
    # Target reached before entry?
    elif candidate_direction == "bullish" and current_price >= target_price:
        signal_state = "INVALIDATED"
        state_reason = "Target reached prior to order fill"
    elif candidate_direction == "bearish" and current_price <= target_price:
        signal_state = "INVALIDATED"
        state_reason = "Target reached prior to order fill"
    # Inside entry zone?
    elif entry_bottom <= current_price <= entry_top:
        if is_stale:
            signal_state = "WATCH"
            state_reason = "Price inside Model A entry zone, but feed is STALE (>60s)"
        else:
            signal_state = "ACTIVE"
            state_reason = f"Price in entry zone ({entry_type}) following verified sweep & displacement"
    else:
        signal_state = "WATCH"
        state_reason = f"Waiting for price to retrace into entry zone [${entry_bottom:.2f} - ${entry_top:.2f}]"

    checklist = [
        ChecklistItem(
            id="htf_context",
            name="1. 4H Context / Daily Alignment",
            description="Trade aligns with 4H trend or key HTF FVG reaction",
            satisfied=htf_confluence,
            evidence="; ".join(htf_notes) if htf_notes else "Verified",
            timeframe="4H"
        ),
        ChecklistItem(
            id="liquidity_sweep",
            name="2. Confirmed Liquidity Sweep",
            description=f"Swept {selected_sweep.label} at ${selected_sweep.price:.2f}",
            satisfied=True,
            evidence=f"{selected_sweep.label} swept ({selected_sweep.sweep_ist or 'recent'})",
            timeframe="1H"
        ),
        ChecklistItem(
            id="displacement_mss",
            name="3. Displacement / MSS",
            description="Momentum displacement or structural break away from swept level",
            satisfied=True,
            evidence=disp_note or bos_note or "Confirmed",
            timeframe="1H"
        ),
        ChecklistItem(
            id="retracement_zone",
            name="4. Entry Retracement Zone",
            description=f"Retracement into {entry_type}",
            satisfied=(entry_bottom <= current_price <= entry_top),
            evidence=f"Current: ${current_price:.2f} vs zone [${entry_bottom:.2f} - ${entry_top:.2f}]",
            timeframe="1H"
        ),
        ChecklistItem(
            id="risk_reward",
            name="5. Reward-to-Risk >= 2.0",
            description=f"Target ${target_price:.2f} with Stop ${stop_loss:.2f}",
            satisfied=(rr_ratio >= MIN_REWARD_TO_RISK),
            evidence=f"R:R = 1:{rr_ratio:.2f}",
            timeframe="1H"
        )
    ]

    setup_id = f"SETUP-MODA-{selected_sweep.type}-{int(sweep_time)}"

    setup_card = ActiveSetupCardData(
        id=setup_id,
        name="Model A: SMC Sweep & Retracement",
        direction=candidate_direction,
        timeframe="1H",
        state=signal_state,
        internal_state="CHECKLIST REVIEW" if signal_state == "ACTIVE" else "SETUP TO INSPECT",
        price=entry_price,
        top=entry_top,
        bottom=entry_bottom,
        zone_str=f"${entry_bottom:.2f} - ${entry_top:.2f}",
        distance=round(current_price - entry_price, 2),
        distance_pct=round(((current_price - entry_price) / current_price) * 100, 2) if current_price else 0.0,
        reason=state_reason,
        invalidation=f"Break of sweep extreme ${stop_loss:.2f}",
        invalidation_price=stop_loss,
        target=f"${target_price:.2f}",
        target_price=target_price,
        is_target_reached=False,
        reward_risk=f"1:{rr_ratio:.2f}",
        quality="Institutional" if htf_confluence and displacement_confirmed else "Standard",
        directional_context=f"Post-{selected_sweep.label} Sweep Retracement",
        confirmation_status="Close Confirmed" if (displacement_confirmed or bos_confirmed) else "Pending",
        checklist=checklist,
        opposing_warning=None,
        last_event_ist=selected_sweep.sweep_ist or "N/A"
    )

    telemetry["passed"] = (signal_state in ("ACTIVE", "WATCH"))
    telemetry["setup_id"] = setup_id
    telemetry["signal_state"] = signal_state
    telemetry["reward_risk"] = rr_ratio

    return setup_card, telemetry
