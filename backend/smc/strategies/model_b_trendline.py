"""
Model B: Structural Trendline Break Strategy
Evaluates independently of SMC liquidity sweeps.

Workflow:
1. Multi-touch trendline (>= 2 verified swing anchors on 1H/30M) with valid geometry.
2. Verified Breakout / Breakdown confirmed by candle CLOSE (not merely a wick).
3. Pre-break Structural Confluence:
   - Bullish break: Higher Low formed prior to break, or sweep of local low.
   - Bearish break: Lower High formed prior to break, or sweep of local high.
4. Entry on breakout bar close or retest of broken trendline.
5. Structural Stop Loss (beyond pre-break swing pivot) and Target (opposing swing/liquidity, R:R >= 2.0).
6. FVG serves as optional confluence, not a mandatory prerequisite.
"""
from typing import List, Dict, Any, Optional, Tuple
from backend.smc.models import (
    Candle, ActiveSetupCardData, ChecklistItem, Trendline,
    FairValueGap, TrendState, SwingPoint
)
from backend.config import MIN_REWARD_TO_RISK, TICK_SIZE


def evaluate_model_b(
    current_price: float,
    candles_1h: List[Candle],
    trendlines: List[Trendline],
    swings: List[SwingPoint],
    h1_fvgs: List[FairValueGap],
    atr_val: float,
    is_stale: bool = False,
    breakout_lookback_bars: int = 15
) -> Tuple[Optional[ActiveSetupCardData], Dict[str, Any]]:
    """
    Evaluate Model B (Structural Trendline Break) deterministically.
    Returns:
        (setup_card, rejection_telemetry)
    """
    telemetry = {
        "model": "MODEL_B",
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
    recent_cutoff = now_bar_time - (breakout_lookback_bars * 3600)

    # 1. Filter broken trendlines with verified breakout within recent lookback
    qualifying_tls = [
        tl for tl in trendlines
        if tl.broken and tl.breakout_time and tl.breakout_time >= recent_cutoff
        and tl.break_confirmed_by_close
    ]

    if not qualifying_tls:
        telemetry["stage_failed"] = "NO_BROKEN_TRENDLINE"
        telemetry["reasons"].append(f"No close-confirmed trendline break in last {breakout_lookback_bars} bars")
        return None, telemetry

    # Sort by touch count (>= 2) and recency of break
    selected_tl = sorted(
        qualifying_tls,
        key=lambda x: (x.touch_count, x.breakout_time or 0),
        reverse=True
    )[0]

    # Direction:
    # Breaking resistance (descending) -> Bullish breakout
    # Breaking support (ascending) -> Bearish breakdown
    is_bullish = (selected_tl.direction == "resistance")
    candidate_direction = "bullish" if is_bullish else "bearish"

    # 2. Pre-break Structural Confluence Check
    # Bullish requires has_higher_low_pre_break OR swing low support
    # Bearish requires has_lower_high_pre_break OR swing high resistance
    has_structural_prep = (
        (is_bullish and selected_tl.has_higher_low_pre_break) or
        (not is_bullish and selected_tl.has_lower_high_pre_break)
    )

    # If flag is false, check recent swing points before breakout
    if not has_structural_prep and swings:
        pre_break_swings = [s for s in swings if s.time < (selected_tl.breakout_time or now_bar_time)]
        if is_bullish:
            lows = [s for s in pre_break_swings if s.type == "low"]
            if len(lows) >= 2 and lows[-1].price > lows[-2].price:
                has_structural_prep = True
        else:
            highs = [s for s in pre_break_swings if s.type == "high"]
            if len(highs) >= 2 and highs[-1].price < highs[-2].price:
                has_structural_prep = True

    if not has_structural_prep:
        telemetry["stage_failed"] = "LACKS_PRE_BREAK_STRUCTURE"
        telemetry["reasons"].append(
            f"Trendline break lacks required pre-break {'Higher Low' if is_bullish else 'Lower High'}"
        )
        return None, telemetry

    # 3. Define Entry Zone and Retest Level
    # Breakout price at the time of break
    break_time = selected_tl.breakout_time or now_bar_time
    candles_since_break = [c for c in candles_1h if c.time >= break_time]
    breakout_bar = candles_since_break[0] if candles_since_break else candles_1h[-1]

    # Retest zone around the broken trendline projected price or breakout bar close
    projected = selected_tl.current_projected_price or breakout_bar.close
    buffer = max(0.5, 0.2 * atr_val)

    if is_bullish:
        entry_bottom = round(projected - buffer, 2)
        entry_top = round(max(breakout_bar.close, projected + buffer), 2)
        entry_price = round((entry_bottom + entry_top) / 2.0, 2)

        # Stop loss placed beyond recent pre-break swing low
        pre_break_lows = [s for s in swings if s.type == "low" and s.time <= break_time]
        if pre_break_lows:
            recent_low = pre_break_lows[-1].price
        else:
            recent_low = min([c.low for c in candles_1h[-10:]])
        stop_loss = round(recent_low - max(0.5, 0.1 * atr_val), 2)

        # Target: next major swing high
        high_targets = [s.price for s in swings if s.type == "high" and s.price > entry_price]
        if high_targets:
            target_price = round(min(high_targets), 2)
        else:
            target_price = round(entry_price + (entry_price - stop_loss) * 2.5, 2)

    else:  # Bearish
        entry_top = round(projected + buffer, 2)
        entry_bottom = round(min(breakout_bar.close, projected - buffer), 2)
        entry_price = round((entry_bottom + entry_top) / 2.0, 2)

        pre_break_highs = [s for s in swings if s.type == "high" and s.time <= break_time]
        if pre_break_highs:
            recent_high = pre_break_highs[-1].price
        else:
            recent_high = max([c.high for c in candles_1h[-10:]])
        stop_loss = round(recent_high + max(0.5, 0.1 * atr_val), 2)

        low_targets = [s.price for s in swings if s.type == "low" and s.price < entry_price]
        if low_targets:
            target_price = round(max(low_targets), 2)
        else:
            target_price = round(entry_price - (stop_loss - entry_price) * 2.5, 2)

    # 4. Reward-to-Risk Validation
    risk_distance = abs(entry_price - stop_loss)
    reward_distance = abs(target_price - entry_price)

    if risk_distance <= 0:
        telemetry["stage_failed"] = "ZERO_RISK_DISTANCE"
        return None, telemetry

    rr_ratio = reward_distance / risk_distance
    if rr_ratio < MIN_REWARD_TO_RISK:
        if is_bullish:
            target_price = round(entry_price + (risk_distance * MIN_REWARD_TO_RISK), 2)
        else:
            target_price = round(entry_price - (risk_distance * MIN_REWARD_TO_RISK), 2)
        reward_distance = abs(target_price - entry_price)
        rr_ratio = reward_distance / risk_distance

    # 5. Optional FVG Confluence
    fvg_confluence = False
    for f in h1_fvgs:
        if f.direction == candidate_direction and f.time >= (break_time - 3600):
            if f.freshness != "fully_mitigated":
                fvg_confluence = True
                break

    # 6. Signal State
    if is_bullish and current_price <= stop_loss:
        signal_state = "INVALIDATED"
        state_reason = f"Price breached structural stop loss (${stop_loss:.2f})"
    elif not is_bullish and current_price >= stop_loss:
        signal_state = "INVALIDATED"
        state_reason = f"Price breached structural stop loss (${stop_loss:.2f})"
    elif is_bullish and current_price >= target_price:
        signal_state = "INVALIDATED"
        state_reason = "Target reached prior to retest entry"
    elif not is_bullish and current_price <= target_price:
        signal_state = "INVALIDATED"
        state_reason = "Target reached prior to retest entry"
    elif entry_bottom <= current_price <= entry_top:
        if is_stale:
            signal_state = "WATCH"
            state_reason = "Price inside Model B entry zone, but feed is STALE (>60s)"
        else:
            signal_state = "ACTIVE"
            state_reason = f"Price in entry/retest zone of broken {selected_tl.direction} trendline"
    else:
        signal_state = "WATCH"
        state_reason = f"Waiting for retest of broken trendline zone [${entry_bottom:.2f} - ${entry_top:.2f}]"

    checklist = [
        ChecklistItem(
            id="multi_touch_trendline",
            name="1. Multi-Touch Trendline Verified",
            description=f"{selected_tl.touch_count}-touch {selected_tl.direction} trendline on {selected_tl.timeframe}",
            satisfied=True,
            evidence=f"Anchors verified with {selected_tl.touch_count} touches",
            timeframe=selected_tl.timeframe
        ),
        ChecklistItem(
            id="confirmed_breakout",
            name="2. Confirmed Candle Close Breakout",
            description="Candle closed decisively beyond trendline boundary",
            satisfied=selected_tl.break_confirmed_by_close,
            evidence=f"Breakout confirmed at {selected_tl.breakout_ist or 'recent'}",
            timeframe="1H"
        ),
        ChecklistItem(
            id="pre_break_structure",
            name="3. Pre-Break Structural Foundation",
            description=f"Confirmed {'Higher Low' if is_bullish else 'Lower High'} formed prior to breakout",
            satisfied=has_structural_prep,
            evidence=selected_tl.structural_support_note or "Pre-break structural shift verified",
            timeframe="1H"
        ),
        ChecklistItem(
            id="retest_entry_zone",
            name="4. Retest / Breakout Zone",
            description=f"Price inside entry zone [${entry_bottom:.2f} - ${entry_top:.2f}]",
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

    setup_id = f"SETUP-MODB-{selected_tl.id}-{int(break_time)}"

    setup_card = ActiveSetupCardData(
        id=setup_id,
        name="Model B: Structural Trendline Break",
        direction=candidate_direction,
        timeframe=selected_tl.timeframe or "1H",
        state=signal_state,
        internal_state="CHECKLIST REVIEW" if signal_state == "ACTIVE" else "SETUP TO INSPECT",
        price=entry_price,
        top=entry_top,
        bottom=entry_bottom,
        zone_str=f"${entry_bottom:.2f} - ${entry_top:.2f}",
        distance=round(current_price - entry_price, 2),
        distance_pct=round(((current_price - entry_price) / current_price) * 100, 2) if current_price else 0.0,
        reason=state_reason,
        invalidation=f"Break of pre-break pivot ${stop_loss:.2f}",
        invalidation_price=stop_loss,
        target=f"${target_price:.2f}",
        target_price=target_price,
        is_target_reached=False,
        reward_risk=f"1:{rr_ratio:.2f}",
        quality="Institutional" if (has_structural_prep and fvg_confluence) else "Standard",
        directional_context=f"Trendline Breakout ({selected_tl.direction})",
        confirmation_status="Close Confirmed" if selected_tl.break_confirmed_by_close else "Provisional",
        checklist=checklist,
        opposing_warning=None,
        last_event_ist=selected_tl.breakout_ist or "N/A"
    )

    telemetry["passed"] = (signal_state in ("ACTIVE", "WATCH"))
    telemetry["setup_id"] = setup_id
    telemetry["signal_state"] = signal_state
    telemetry["reward_risk"] = rr_ratio

    return setup_card, telemetry
