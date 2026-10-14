"""
Unified SMC Key-Level Intelligence Engine.

Orchestrates all calculations sequentially:
1. Multi-timeframe Fair Value Gaps (1D, 4H, 1H, 30M) + Inversions + Overlaps
2. Swings (with confirmation offset and HH/HL/LH/LL labeling)
3. Trend state determination
4. BOS & CHoCH (enforcing >= 40% retracement rule for BOS)
5. Displacement candles & Order Blocks (strict ICT definition)
6. Premium / Discount & OTE zones
7. Liquidity levels (PDH/PDL, PWH/PWL, EQH/EQL, Liquidity Sweeps)
8. Multi-touch trendlines (1H, 30M)
9. Psychological 20s and 80s round numbers
10. Key level ranking with multi-factor scoring & human-readable rationale
11. Opposing higher-timeframe zone warnings
12. Comprehensive descriptive market state summary
"""
from typing import Dict, List, Any, Optional
from backend.smc.models import (
    Candle, MarketState, AnalysisConfig, TerminalState, ActiveSetupCardData
)
from backend.smc.fvg import calculate_fvgs, find_overlapping_fvgs
from backend.smc.structure import (
    find_swings, calculate_bos, calculate_support_resistance, get_trend_state, _atr
)
from backend.smc.displacement import (
    find_displacement_candles, find_order_blocks
)
from backend.smc.premium_discount import (
    calculate_premium_discount, calculate_ote
)
from backend.smc.liquidity import (
    calculate_pdh_pdl, calculate_pwh_pwl, calculate_equal_highs_lows
)
from backend.smc.trendlines import calculate_trendlines
from backend.smc.psychological import calculate_psychological_levels
from backend.smc.ranking import rank_key_levels
from backend.smc.activation import generate_watchlist, global_alert_store
from backend.smc.liquidity_intelligence import analyze_liquidity_intelligence
from backend.smc.strategies import evaluate_model_a, evaluate_model_b


class SMCEngine:
    """
    Unified SMC Key-Level Intelligence Engine.
    Executes all calculations sequentially without lookahead bias.
    """

    def analyze_multi_timeframe(
        self,
        candles_by_tf: Dict[str, List[Candle]],
        selected_timeframe: str = "1H",
        config: Optional[AnalysisConfig] = None,
        is_stale: bool = False
    ) -> Dict[str, Any]:
        """
        Perform complete multi-timeframe SMC analysis for the dashboard.
        """
        if config is None:
            config = AnalysisConfig()

        tf = selected_timeframe.upper()
        current_candles = candles_by_tf.get(tf, [])
        daily_candles = candles_by_tf.get("1D", [])
        h4_candles = candles_by_tf.get("4H", [])
        h1_candles = candles_by_tf.get("1H", [])
        m30_candles = candles_by_tf.get("30M", [])
        m15_candles = candles_by_tf.get("15M", [])

        # Current market price & volatility
        current_price = current_candles[-1].close if current_candles else 0.0
        atr_val = _atr(current_candles, 14) if current_candles else 5.0

        # 1. Fair Value Gaps (1D, 4H, 1H, and Current TF)
        daily_fvgs = calculate_fvgs(daily_candles, "1D", config)
        h4_fvgs = calculate_fvgs(h4_candles, "4H", config)
        h1_candles = candles_by_tf.get("1H", [])
        h1_fvgs = calculate_fvgs(h1_candles, "1H", config) if h1_candles else []

        if tf == "1D":
            curr_fvgs = daily_fvgs
        elif tf == "4H":
            curr_fvgs = h4_fvgs
        elif tf == "1H":
            curr_fvgs = h1_fvgs
        else:
            curr_fvgs = calculate_fvgs(current_candles, tf, config)

        # Overlapping HTF FVGs (Daily & 4H Critical Sections)
        overlapping_htf_fvgs = find_overlapping_fvgs(daily_fvgs, h4_fvgs)

        # 2. Market Structure & Swings
        swings = find_swings(current_candles, tf, window=config.swing_window)
        daily_swings = find_swings(daily_candles, "1D", window=config.swing_window)
        h4_swings = find_swings(h4_candles, "4H", window=config.swing_window)

        # Trend states
        daily_trend_state = get_trend_state(daily_swings)
        h4_trend_state = get_trend_state(h4_swings)
        h1_swings = find_swings(h1_candles, "1H", window=config.swing_window) if h1_candles else []
        h1_trend_state = get_trend_state(h1_swings)
        m15_swings = find_swings(m15_candles, "15M", window=config.swing_window) if m15_candles else []
        m15_trend_state = get_trend_state(m15_swings)
        current_trend_state = get_trend_state(swings)

        # BOS & CHoCH
        bos_signals = calculate_bos(current_candles, swings, tf, config)
        sr_zones = calculate_support_resistance(swings)

        # 3. Displacement & Order Blocks
        displacement_candles = find_displacement_candles(current_candles, tf, config)
        order_blocks = find_order_blocks(current_candles, bos_signals, displacement_candles, tf, config)

        # Also get HTF Order Blocks for authority
        h4_bos = calculate_bos(h4_candles, h4_swings, "4H", config)
        h4_disp = find_displacement_candles(h4_candles, "4H", config)
        h4_obs = find_order_blocks(h4_candles, h4_bos, h4_disp, "4H", config)

        all_order_blocks = order_blocks + [ob for ob in h4_obs if ob.timeframe != tf]

        # 4. Premium / Discount & OTE
        prem_disc = calculate_premium_discount(current_candles, swings, tf, current_price)
        daily_prem_disc = calculate_premium_discount(daily_candles, daily_swings, "1D", current_price)
        ote_zone = calculate_ote(swings, tf, current_price, config)

        # 5. Liquidity Levels & Sweeps
        pdh_pdl = calculate_pdh_pdl(daily_candles, current_candles)
        pwh_pwl = calculate_pwh_pwl(daily_candles, current_candles)
        eq_highs_lows = calculate_equal_highs_lows(current_candles, swings, config)
        all_liquidity = pdh_pdl + pwh_pwl + eq_highs_lows

        # 6. Trendlines (Focus on Intraday Execution: 1H, 30M, 15M, 5M, 1M)
        trendlines = []
        if tf in ["1H", "30M", "15M", "5M", "1M"]:
            trendlines = calculate_trendlines(current_candles, swings, tf, config)
        elif h1_candles:
            h1_swings = find_swings(h1_candles, "1H", window=config.swing_window)
            trendlines = calculate_trendlines(h1_candles, h1_swings, "1H", config)

        # 7. Psychological 20s and 80s Levels
        psych_levels = calculate_psychological_levels(current_price)

        # 8. Level Ranking with Scored Criteria & Explanations
        ranked_levels = rank_key_levels(
            current_price=current_price,
            daily_fvgs=daily_fvgs,
            h4_fvgs=h4_fvgs,
            current_fvgs=curr_fvgs,
            order_blocks=all_order_blocks,
            liquidity_levels=all_liquidity,
            psychological_levels=psych_levels,
            trendlines=trendlines,
            config=config
        )

        # 9. Opposing Higher-Timeframe Zone Detection
        # Rule: "Avoid trades when an opposing HTF FVG is present"
        opposing_warnings = []
        opposing_fvg_above = None
        opposing_fvg_below = None

        if current_price > 0:
            for f in (daily_fvgs + h4_fvgs):
                if not f.mitigated and not f.inverted:
                    dist_up = f.bottom - current_price
                    dist_down = current_price - f.top

                    # Overhead Bearish FVG within warning threshold
                    if f.direction == "bearish" and 0 < dist_up < (current_price * config.opposing_zone_pct):
                        msg = f"Opposing Bearish {f.timeframe} FVG overhead at ${f.bottom:.2f} - ${f.top:.2f} (Midpoint: ${f.midpoint:.2f})"
                        opposing_warnings.append(msg)
                        if opposing_fvg_above is None:
                            opposing_fvg_above = f"${f.midpoint:.2f} ({f.timeframe})"

                    # Support Bullish FVG underneath within warning threshold
                    elif f.direction == "bullish" and 0 < dist_down < (current_price * config.opposing_zone_pct):
                        msg = f"Opposing Bullish {f.timeframe} FVG support below at ${f.bottom:.2f} - ${f.top:.2f} (Midpoint: ${f.midpoint:.2f})"
                        opposing_warnings.append(msg)
                        if opposing_fvg_below is None:
                            opposing_fvg_below = f"${f.midpoint:.2f} ({f.timeframe})"

        # 10. Synthesize Descriptive Market State
        above_levels = [l for l in ranked_levels if l.distance > 0]
        below_levels = [l for l in ranked_levels if l.distance < 0]

        nearest_above = above_levels[0] if above_levels else None
        nearest_below = below_levels[0] if below_levels else None

        ote_desc = None
        if ote_zone:
            ote_desc = f"{ote_zone.direction.capitalize()} OTE Zone [${ote_zone.bottom:.2f} - ${ote_zone.top:.2f}] (Mid: ${ote_zone.midpoint:.2f})"

        summary_text = (
            f"Gold (XAUTUSD) is currently trading at ${current_price:.2f}. "
            f"Daily Trend: {daily_trend_state.trend.capitalize()} | 4H Trend: {h4_trend_state.trend.capitalize()} | {tf} Trend: {current_trend_state.trend.capitalize()}. "
            f"Position: {daily_prem_disc.position.upper()} ({daily_prem_disc.position_pct}% of Daily Range). "
        )
        if nearest_above:
            summary_text += f"Immediate resistance above: {nearest_above.name} at ${nearest_above.price:.2f} (+${nearest_above.distance:.2f}). "
        if nearest_below:
            summary_text += f"Immediate support below: {nearest_below.name} at ${nearest_below.price:.2f} (${nearest_below.distance:.2f}). "

        market_state = MarketState(
            current_price=current_price,
            timeframe=tf,
            daily_trend=daily_trend_state.trend,
            h4_trend=h4_trend_state.trend,
            current_tf_trend=current_trend_state.trend,
            daily_position=daily_prem_disc.position,
            daily_position_pct=daily_prem_disc.position_pct,
            nearest_level_above=nearest_above.name if nearest_above else None,
            nearest_level_above_price=nearest_above.price if nearest_above else None,
            nearest_level_below=nearest_below.name if nearest_below else None,
            nearest_level_below_price=nearest_below.price if nearest_below else None,
            opposing_htf_fvg_above=opposing_fvg_above,
            opposing_htf_fvg_below=opposing_fvg_below,
            in_ote_zone=ote_zone.in_zone if ote_zone else False,
            ote_description=ote_desc,
            summary=summary_text,
            warnings=opposing_warnings
        )

        # 11. Generate Key-Level Activation & Trade-Readiness Watchlist
        watchlist_entries, active_alerts = generate_watchlist(
            current_price=current_price,
            current_candles=current_candles,
            daily_fvgs=daily_fvgs,
            h4_fvgs=h4_fvgs,
            order_blocks=all_order_blocks,
            liquidity_levels=all_liquidity,
            trendlines=trendlines,
            displacement_candles=displacement_candles,
            current_fvgs=curr_fvgs,
            opposing_warnings=opposing_warnings,
            config=config,
            is_stale=is_stale
        )

        # Count active levels by state
        state_counts = {}
        for entry in watchlist_entries:
            state_counts[entry.state] = state_counts.get(entry.state, 0) + 1

        # 12. Synthesize Signal-First Terminal State Machine
        bias_details = {
            "1D": daily_trend_state.trend.upper(),
            "4H": h4_trend_state.trend.upper(),
            "1H": h1_trend_state.trend.upper(),
            "15M": m15_trend_state.trend.upper()
        }
        has_bullish = any(t == "BULLISH" for t in bias_details.values())
        has_bearish = any(t == "BEARISH" for t in bias_details.values())
        if has_bullish and has_bearish:
            market_bias = "MIXED"
        elif has_bullish and not has_bearish:
            market_bias = "BULLISH"
        elif has_bearish and not has_bullish:
            market_bias = "BEARISH"
        else:
            market_bias = "NEUTRAL"

        # Risk / Data State
        risk_reasons = []
        if is_stale:
            risk_state = "CRITICAL"
            risk_reasons.append("Data feed stale (>60s) or disconnected")
        elif opposing_warnings:
            risk_state = "CAUTION"
            risk_reasons.extend(opposing_warnings)
        else:
            risk_state = "NORMAL"

        # Evaluate setup states and detect extreme/active/watch setups
        terminal_setup_state = "IDLE"
        extreme_reasons = []
        candidate_setups = []

        # Check overlapping HTF FVG bounds for extreme detection
        htf_crit_ranges = []
        for o_fvg in overlapping_htf_fvgs:
            htf_crit_ranges.append((o_fvg.get("overlap_bottom", 0.0), o_fvg.get("overlap_top", 0.0)))

        for entry in watchlist_entries:
            # Check for extreme confluence (only fully confirmed ACTIVE setups can escalate to EXTREME)
            is_extreme = False
            reasons = []
            if entry.state == "CHECKLIST REVIEW":
                # Check HTF overlap
                if entry.top and entry.bottom:
                    for crit_b, crit_t in htf_crit_ranges:
                        if max(entry.bottom, crit_b) <= min(entry.top, crit_t):
                            is_extreme = True
                            reasons.append("Overlapping HTF FVG critical confluence")
                            break
                # Check PDH/PDL sweep + HTF trend confluence
                has_sweep = any("sweep" in ev.lower() for ev in entry.evidence)
                if has_sweep and ((entry.direction == "bullish" and daily_trend_state.trend == "bullish") or
                                  (entry.direction == "bearish" and daily_trend_state.trend == "bearish")):
                    is_extreme = True
                    reasons.append("Liquidity sweep with HTF trend alignment")
                if entry.score >= 85 and entry.state == "CHECKLIST REVIEW":
                    is_extreme = True
                    reasons.append("High confluence score (>=85) with full checklist")

            if is_extreme:
                t_state = "EXTREME"
                extreme_reasons.extend(reasons)
            elif entry.state == "CHECKLIST REVIEW":
                t_state = "ACTIVE"
            elif entry.state in ["SETUP TO INSPECT", "REACTION DEVELOPING", "AT LEVEL", "AT KEY LEVEL", "APPROACHING"]:
                t_state = "WATCH"
            elif entry.state in ["PASSED / INVALIDATED", "INVALIDATED / PASSED", "SWEPT / MITIGATED"]:
                t_state = "INVALIDATED"
            else:
                t_state = "IDLE"

            # Entry Zone Boundaries
            entry_top = entry.top if entry.top is not None else entry.price
            entry_bottom = entry.bottom if entry.bottom is not None else entry.price
            entry_mid = entry.price

            # Invalidation Level (Stop Loss)
            inval_price = None
            if entry.direction == "bullish":
                inval_price = entry_bottom if entry_bottom < entry_mid else round(entry_mid * 0.998, 2)
                inval_str = f"Close below {inval_price:.2f}"
            elif entry.direction == "bearish":
                inval_price = entry_top if entry_top > entry_mid else round(entry_mid * 1.002, 2)
                inval_str = f"Close above {inval_price:.2f}"
            else:
                inval_str = "Break of opposing structure"

            # Target Identification & Semantic Directional Validation
            target_price = None
            target_str = "N/A"
            target_type = None
            is_target_reached = False
            is_stop_breached = False

            if entry.direction == "bullish":
                # Valid targets for LONG must be strictly above entry zone top AND must be legitimate resistance or buy-side liquidity
                bull_targets = []
                for l in ranked_levels:
                    if l.price > (entry_top + 0.1):
                        l_name_lower = l.name.lower()
                        l_type_lower = l.type.lower()
                        # Reject Sell-Side Liquidity (Equal Lows / SSL / PDL / PWL) as a Long target!
                        if "equal low" in l_name_lower or "ssl" in l_name_lower or "pdl" in l_name_lower or "pwl" in l_name_lower:
                            continue
                        bull_targets.append(l)

                bull_targets.sort(key=lambda l: l.price)
                if bull_targets:
                    cand = bull_targets[0]
                    target_price = cand.price
                    target_type = cand.type
                    target_str = f"{cand.name} ({cand.price:.2f})"
                    if current_price >= target_price:
                        is_target_reached = True
                        target_str = f"{cand.name} ({cand.price:.2f}) [REACHED]"

                # Invalidation breach check
                if inval_price is not None and current_price <= inval_price:
                    is_stop_breached = True

            elif entry.direction == "bearish":
                # Valid targets for SHORT must be strictly below entry zone bottom AND must be legitimate support or sell-side liquidity
                bear_targets = []
                for l in ranked_levels:
                    if l.price < (entry_bottom - 0.1):
                        l_name_lower = l.name.lower()
                        l_type_lower = l.type.lower()
                        # Reject Buy-Side Liquidity (Equal Highs / BSL / PDH / PWH) as a Short target!
                        if "equal high" in l_name_lower or "bsl" in l_name_lower or "pdh" in l_name_lower or "pwh" in l_name_lower:
                            continue
                        bear_targets.append(l)

                bear_targets.sort(key=lambda l: l.price, reverse=True)
                if bear_targets:
                    cand = bear_targets[0]
                    target_price = cand.price
                    target_type = cand.type
                    target_str = f"{cand.name} ({cand.price:.2f})"
                    if current_price <= target_price:
                        is_target_reached = True
                        target_str = f"{cand.name} ({cand.price:.2f}) [REACHED]"

                # Invalidation breach check
                if inval_price is not None and current_price >= inval_price:
                    is_stop_breached = True

            # Directional Trend Alignment & Countertrend Verification
            daily_trend_str = daily_trend_state.trend.lower()
            trade_class: Literal["PRO-TREND", "COUNTERTREND (HIGH RISK)", "NEUTRAL"] = "NEUTRAL"
            dir_context = "NEUTRAL BIAS"

            if entry.direction == "bullish":
                if daily_trend_str == "bullish":
                    trade_class = "PRO-TREND"
                    dir_context = "PRO-TREND LONG (1D ALIGNED)"
                elif daily_trend_str == "bearish":
                    trade_class = "COUNTERTREND (HIGH RISK)"
                    dir_context = "COUNTERTREND LONG (HIGH RISK) · 1D BIAS IS BEARISH"
                else:
                    trade_class = "NEUTRAL"
                    dir_context = "BULLISH SETUP (1D NEUTRAL)"
            elif entry.direction == "bearish":
                if daily_trend_str == "bearish":
                    trade_class = "PRO-TREND"
                    dir_context = "PRO-TREND SHORT (1D ALIGNED)"
                elif daily_trend_str == "bullish":
                    trade_class = "COUNTERTREND (HIGH RISK)"
                    dir_context = "COUNTERTREND SHORT (HIGH RISK) · 1D BIAS IS BULLISH"
                else:
                    trade_class = "NEUTRAL"
                    dir_context = "BEARISH SETUP (1D NEUTRAL)"

            # Strict Reward / Risk Validation
            rr_str = "N/A"
            rr_val = None
            if not is_target_reached and not is_stop_breached:
                if entry.direction == "bullish" and target_price and inval_price:
                    risk = entry_mid - inval_price
                    reward = target_price - entry_mid
                    if risk > 0.05 and reward > 0.05 and inval_price < entry_bottom and target_price > entry_top and current_price < target_price:
                        rr_val = reward / risk
                        rr_str = f"1:{rr_val:.1f}"
                elif entry.direction == "bearish" and target_price and inval_price:
                    risk = inval_price - entry_mid
                    reward = entry_mid - target_price
                    if risk > 0.05 and reward > 0.05 and inval_price > entry_top and target_price < entry_bottom and current_price > target_price:
                        rr_val = reward / risk
                        rr_str = f"1:{rr_val:.1f}"

            # Canonical Setup State Transitions with Strict Lifecycle Rules
            canon_state: Literal["WATCH", "WAITING FOR CONFIRMATION", "READY", "ENTERED", "INVALIDATED", "EXPIRED", "IDLE"] = "IDLE"
            t_state: TerminalSignalState = "IDLE"

            if is_target_reached:
                canon_state = "EXPIRED"
                t_state = "EXPIRED"
                state_reason = f"Target already reached (${target_price:.2f}). Setup expired."
            elif is_stop_breached:
                canon_state = "INVALIDATED"
                t_state = "INVALIDATED"
                state_reason = f"Invalidation level breached (${inval_price:.2f}). Setup stopped out."
            elif entry.state in ["PASSED / INVALIDATED", "SWEPT / MITIGATED", "INVALIDATED / PASSED"]:
                canon_state = "INVALIDATED"
                t_state = "INVALIDATED"
                state_reason = entry.state_reason
            elif entry.state == "CHECKLIST REVIEW":
                # Check prerequisites: Valid stop, valid target, R:R >= 1.5, clean path
                if rr_val is not None and rr_val >= 1.5 and target_price and inval_price and not entry.opposing_zone_warning:
                    canon_state = "READY"
                    t_state = "EXTREME" if is_extreme else "ACTIVE"
                    state_reason = "All 5 checklist criteria satisfied with verified SL, TP, and R:R >= 1:1.5."
                else:
                    canon_state = "WAITING FOR CONFIRMATION"
                    t_state = "WATCH"
                    if rr_val is not None and rr_val < 1.5:
                        state_reason = f"Checklist met but rejected: Sub-threshold R:R ({rr_str} < 1:1.5)."
                    elif entry.opposing_zone_warning:
                        state_reason = f"Checklist met but blocked by opposing HTF zone: {entry.opposing_zone_warning}."
                    else:
                        state_reason = "Pending final target/invalidation confirmation."
            elif entry.state in ["SETUP TO INSPECT", "REACTION DEVELOPING"]:
                canon_state = "WAITING FOR CONFIRMATION"
                t_state = "WATCH"
                state_reason = entry.state_reason
            elif entry.state in ["AT LEVEL", "AT KEY LEVEL", "APPROACHING", "WAITING"]:
                canon_state = "WATCH"
                t_state = "WATCH"
                state_reason = entry.state_reason
            else:
                canon_state = "IDLE"
                t_state = "IDLE"
                state_reason = entry.state_reason

            quality_label = "High Confluence" if is_extreme or entry.score >= 80 else ("Confirmed" if canon_state == "READY" else "Standard")
            zone_str = f"{entry.bottom:.2f} - {entry.top:.2f}" if (entry.bottom is not None and entry.top is not None) else f"{entry.price:.2f}"

            if canon_state == "READY":
                conf_status = "Ready for Manual Inspection"
            elif canon_state == "WAITING FOR CONFIRMATION":
                conf_status = "Waiting for Confirmation"
            elif canon_state == "WATCH":
                conf_status = "Surveillance (Approaching/At Zone)"
            elif canon_state in ["INVALIDATED", "EXPIRED"]:
                conf_status = "Setup Inactive / Expired"
            else:
                conf_status = "Idle Surveillance"

            # 12-Point Setup Inspector Checklist (Phase 5)
            inspector_checklist = [
                {
                    "id": "daily_bias",
                    "title": "Daily Directional Bias",
                    "status": "PASS" if trade_class == "PRO-TREND" else ("FAIL" if trade_class == "COUNTERTREND (HIGH RISK)" else "NOT AVAILABLE"),
                    "detail": f"1D Bias is {daily_trend_str.upper()}. Setup is {trade_class}."
                },
                {
                    "id": "htf_location",
                    "title": "HTF Key Level POI",
                    "status": "PASS" if entry.timeframe in ["1D", "4H", "1W"] else "FAIL",
                    "detail": f"Originated from {entry.timeframe} {entry.type}."
                },
                {
                    "id": "liquidity_sweep",
                    "title": "Liquidity Sweep / Rejection",
                    "status": "PASS" if entry.checklist[1].satisfied else "FAIL",
                    "detail": entry.checklist[1].evidence
                },
                {
                    "id": "structural_confirmation",
                    "title": "Trendline Break / MSS",
                    "status": "PASS" if entry.checklist[2].satisfied else "FAIL",
                    "detail": entry.checklist[2].evidence
                },
                {
                    "id": "displacement",
                    "title": "Institutional Displacement",
                    "status": "PASS" if (len(entry.checklist) > 3 and entry.checklist[3].satisfied) else "FAIL",
                    "detail": entry.checklist[3].evidence if len(entry.checklist) > 3 else "Pending"
                },
                {
                    "id": "supporting_fvg",
                    "title": "Supporting LTF FVG",
                    "status": "PASS" if any("FVG" in ev for ev in entry.evidence) else "FAIL",
                    "detail": "Supporting FVG detected" if any("FVG" in ev for ev in entry.evidence) else "No supporting FVG formed"
                },
                {
                    "id": "closed_candle_confirm",
                    "title": "Closed-Candle Confirmation",
                    "status": "PASS" if any("close" in ev.lower() for ev in entry.evidence) else "FAIL",
                    "detail": "Confirmed on closed candle" if any("close" in ev.lower() for ev in entry.evidence) else "Pending closed-bar validation"
                },
                {
                    "id": "stop_placement",
                    "title": "Valid Stop-Loss Placement",
                    "status": "PASS" if (inval_price is not None and ((entry.direction == 'bullish' and inval_price < entry_bottom) or (entry.direction == 'bearish' and inval_price > entry_top))) else "FAIL",
                    "detail": inval_str
                },
                {
                    "id": "valid_target",
                    "title": "Structurally Valid Target",
                    "status": "PASS" if (target_price is not None and not is_target_reached) else "FAIL",
                    "detail": target_str
                },
                {
                    "id": "minimum_rr",
                    "title": "Minimum Reward / Risk (>= 1:1.5)",
                    "status": "PASS" if (rr_val is not None and rr_val >= 1.5) else "FAIL",
                    "detail": f"Calculated R:R {rr_str}" if rr_val is not None else "R:R unavailable or < 1:1.5"
                },
                {
                    "id": "friction_assumptions",
                    "title": "Friction & Basis Disclosed",
                    "status": "PASS",
                    "detail": "0.01 tick size, 0.001 XAUT contract, basis spread monitored"
                },
                {
                    "id": "contract_validity",
                    "title": "Contract Specifications",
                    "status": "PASS",
                    "detail": "XAUTUSD Perpetual Futures (Product ID 131253)"
                }
            ]

            setup_card = ActiveSetupCardData(
                id=entry.level_id,
                name=entry.name,
                direction=entry.direction if entry.direction in ["bullish", "bearish"] else "neutral",
                timeframe=entry.timeframe,
                state=t_state,
                internal_state=entry.state,
                price=entry.price,
                top=entry.top,
                bottom=entry.bottom,
                zone_str=zone_str,
                distance=entry.distance,
                distance_pct=entry.distance_pct,
                reason=state_reason,
                invalidation=inval_str,
                invalidation_price=inval_price,
                target=target_str,
                target_price=target_price,
                target_type=target_type,
                is_target_reached=is_target_reached,
                reward_risk=rr_str,
                reward_risk_numeric=round(rr_val, 2) if rr_val is not None else None,
                quality=quality_label,
                directional_context=dir_context,
                trade_classification=trade_class,
                canonical_setup_state=canon_state,
                daily_bias=daily_trend_str.upper(),
                confirmation_status=conf_status,
                checklist=entry.checklist,
                inspector_checklist=inspector_checklist,
                opposing_warning=entry.opposing_zone_warning,
                last_event_ist=entry.last_event_ist or "N/A"
            )
            candidate_setups.append((t_state, entry.score, abs(entry.distance), setup_card))

        # Independent Strategy Models: Model A (Sweep & Retrace) & Model B (Trendline Break)
        model_a_setup, model_a_telemetry = evaluate_model_a(
            current_price=current_price,
            candles_1h=h1_candles if h1_candles else current_candles,
            daily_trend=daily_trend_state,
            h4_trend=h4_trend_state,
            h4_fvgs=h4_fvgs,
            h1_fvgs=h1_fvgs,
            liquidity_levels=all_liquidity,
            bos_signals=bos_signals,
            displacement_candles=displacement_candles,
            atr_val=atr_val,
            is_stale=is_stale
        )
        if model_a_setup:
            candidate_setups.append((model_a_setup.state, 95, abs(model_a_setup.distance), model_a_setup))

        model_b_setup, model_b_telemetry = evaluate_model_b(
            current_price=current_price,
            candles_1h=h1_candles if h1_candles else current_candles,
            trendlines=trendlines,
            swings=h1_swings if h1_candles else swings,
            h1_fvgs=h1_fvgs,
            atr_val=atr_val,
            is_stale=is_stale
        )
        if model_b_setup:
            candidate_setups.append((model_b_setup.state, 90, abs(model_b_setup.distance), model_b_setup))

        # Overall setup state determination:
        # A setup ONLY displays in the top banner if it is READY or actively developing reaction in zone (WAITING FOR CONFIRMATION).
        # Routine WATCH levels (levels price is just approaching) remain in the Watchlist table and do NOT clutter the top banner.
        TF_WEIGHTS = {"1D": 400, "4H": 300, "1H": 200, "30M": 100, "15M": 50, "5M": 20, "1M": 10}
        state_order = {"EXTREME": 5000, "ACTIVE": 4000, "READY": 3000, "WAITING FOR CONFIRMATION": 2500, "WATCH": 2000, "INVALIDATED": 100, "IDLE": 0}
        if any(c[0] == "EXTREME" for c in candidate_setups):
            terminal_setup_state = "EXTREME"
        elif any(c[0] == "ACTIVE" for c in candidate_setups):
            terminal_setup_state = "ACTIVE"
        elif any(c[0] in ["READY", "WAITING FOR CONFIRMATION"] for c in candidate_setups):
            terminal_setup_state = "WATCH"
        elif any(c[0] == "WATCH" for c in candidate_setups):
            terminal_setup_state = "WATCH"
        elif any(c[0] == "INVALIDATED" for c in candidate_setups):
            terminal_setup_state = "INVALIDATED"
        else:
            terminal_setup_state = "IDLE"

        active_setup = None
        if candidate_setups:
            qualifying = [c for c in candidate_setups if c[0] in ["EXTREME", "ACTIVE", "READY", "WAITING FOR CONFIRMATION", "WATCH"]]
            if not qualifying:
                qualifying = candidate_setups
            qualifying.sort(
                key=lambda x: (
                    state_order.get(x[0], 0) + TF_WEIGHTS.get(x[3].timeframe, 0),
                    x[1],
                    -x[2]
                ),
                reverse=True
            )
            active_setup = qualifying[0][3]

        terminal_state = TerminalState(
            market_bias=market_bias,
            bias_details=bias_details,
            setup_state=terminal_setup_state,
            risk_state=risk_state,
            active_setup=active_setup,
            extreme_reasons=list(set(extreme_reasons)),
            risk_reasons=risk_reasons
        )

        # 12. Hidden Liquidity & Heatmap Intelligence
        liquidity_intelligence = analyze_liquidity_intelligence(
            candles_by_tf=candles_by_tf,
            current_timeframe=tf,
            config=config
        )

        # 13. Synthesize Recent Structural Events Feed
        raw_events = []
        for l in all_liquidity:
            if getattr(l, "swept", False):
                raw_events.append({
                    "timestamp": getattr(l, "sweep_time", 0) or 0,
                    "ist_time": getattr(l, "sweep_ist", None) or "Recent",
                    "type": "LIQUIDITY_SWEEP",
                    "title": f"Liquidity Sweep · {l.label}",
                    "detail": f"Price swept resting liquidity at ${l.price:.2f} ({getattr(l, 'swept_by_timeframe', None) or 'Current TF'}). Closed back inside.",
                    "timeframe": getattr(l, "swept_by_timeframe", None) or tf,
                    "badge": "SWEEP",
                    "badge_color": "var(--gold)"
                })

        for tl in trendlines:
            if tl.broken:
                note = f" ({tl.structural_support_note})" if tl.structural_support_note else ""
                raw_events.append({
                    "timestamp": tl.breakout_time or 0,
                    "ist_time": tl.breakout_ist or "Recent",
                    "type": "TRENDLINE_BREAK",
                    "title": f"{tl.timeframe} {tl.direction.upper()} Trendline Break",
                    "detail": f"Confirmed breakout with {tl.touch_count} touches, projection ${tl.current_projected_price:.2f}{note}.",
                    "timeframe": tl.timeframe,
                    "badge": "TL BREAK",
                    "badge_color": "var(--purple-extreme)"
                })

        for d in displacement_candles[-6:]:
            raw_events.append({
                "timestamp": d.time,
                "ist_time": d.ist_time or "Recent",
                "type": "DISPLACEMENT",
                "title": f"{d.timeframe} {d.direction.capitalize()} Displacement",
                "detail": f"Institutional expansion candle (body: ${d.body_size:.2f}, {d.body_atr_ratio:.1f}x ATR).",
                "timeframe": d.timeframe,
                "badge": "DISPLACEMENT",
                "badge_color": "var(--teal-bull)" if d.direction == "bullish" else "var(--red-bear)"
            })

        for b in bos_signals[-6:]:
            raw_events.append({
                "timestamp": b.time,
                "ist_time": getattr(b, "ist_time", None) or "Recent",
                "type": "STRUCTURE_BREAK",
                "title": f"{b.kind} ({b.type.upper()})",
                "detail": f"Confirmed structure break at ${b.broken_level:.2f} (Retracement: {b.retracement_pct:.1f}%).",
                "timeframe": getattr(b, "timeframe", tf),
                "badge": b.kind,
                "badge_color": "var(--blue)"
            })

        for a in active_alerts:
            raw_events.append({
                "timestamp": a.timestamp,
                "ist_time": a.ist_time or "Recent",
                "type": "STATE_ALERT",
                "title": f"{a.level_name} ({a.timeframe})",
                "detail": a.message,
                "timeframe": a.timeframe,
                "badge": str(a.state),
                "badge_color": "var(--gold)"
            })

        raw_events.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        seen_events = set()
        recent_events = []
        for ev in raw_events:
            key = (ev["type"], ev["title"], ev.get("timestamp", 0))
            if key not in seen_events:
                seen_events.add(key)
                recent_events.append(ev)

        return {
            "timeframe": tf,
            "current_price": current_price,
            "terminal_state": terminal_state.model_dump(),
            "market_state": market_state.model_dump(),
            "trend_state": current_trend_state.model_dump(),
            "daily_trend_state": daily_trend_state.model_dump(),
            "h4_trend_state": h4_trend_state.model_dump(),
            "h1_trend_state": h1_trend_state.model_dump(),
            "m15_trend_state": m15_trend_state.model_dump(),
            "daily_fvgs": [f.model_dump() for f in daily_fvgs],
            "h4_fvgs": [f.model_dump() for f in h4_fvgs],
            "h1_fvgs": [f.model_dump() for f in h1_fvgs],
            "timeframe_fvgs": [f.model_dump() for f in curr_fvgs],
            "overlapping_htf_fvgs": overlapping_htf_fvgs,
            "swings": [s.model_dump() for s in swings],
            "bos_signals": [b.model_dump() for b in bos_signals],
            "displacement_candles": [d.model_dump() for d in displacement_candles],
            "order_blocks": [ob.model_dump() for ob in all_order_blocks],
            "premium_discount": prem_disc.model_dump(),
            "daily_premium_discount": daily_prem_disc.model_dump(),
            "ote_zone": ote_zone.model_dump() if ote_zone else None,
            "support_resistance": sr_zones,
            "liquidity_levels": [l.model_dump() for l in all_liquidity],
            "trendlines": [t.model_dump() for t in trendlines],
            "psychological_levels": [p.model_dump() for p in psych_levels],
            "key_levels_summary": [r.model_dump() for r in ranked_levels],
            "watchlist": [w.model_dump() for w in watchlist_entries],
            "active_alerts": [a.model_dump() for a in active_alerts],
            "recent_events": recent_events[:15],
            "state_counts": state_counts,
            "opposing_warnings": opposing_warnings,
            "liquidity_intelligence": liquidity_intelligence.model_dump(),
            "model_a_setup": model_a_setup.model_dump() if model_a_setup else None,
            "model_a_telemetry": model_a_telemetry,
            "model_b_setup": model_b_setup.model_dump() if model_b_setup else None,
            "model_b_telemetry": model_b_telemetry
        }
