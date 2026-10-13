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
    Candle, MarketState, AnalysisConfig
)
from backend.smc.fvg import calculate_fvgs, find_overlapping_fvgs
from backend.smc.structure import (
    find_swings, calculate_bos, calculate_support_resistance, get_trend_state
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


class SMCEngine:
    """
    Unified SMC Key-Level Intelligence Engine.
    Executes all calculations sequentially without lookahead bias.
    """

    def analyze_multi_timeframe(
        self,
        candles_by_tf: Dict[str, List[Candle]],
        selected_timeframe: str = "1H",
        config: Optional[AnalysisConfig] = None
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

        # Current market price
        current_price = current_candles[-1].close if current_candles else 0.0

        # 1. Fair Value Gaps (1D, 4H, and Current TF)
        daily_fvgs = calculate_fvgs(daily_candles, "1D", config)
        h4_fvgs = calculate_fvgs(h4_candles, "4H", config)
        if tf == "1D":
            curr_fvgs = daily_fvgs
        elif tf == "4H":
            curr_fvgs = h4_fvgs
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

        # 6. Trendlines (Focus on 1H & 30M)
        trendlines = []
        if tf in ["1H", "30M"]:
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

        return {
            "timeframe": tf,
            "current_price": current_price,
            "market_state": market_state.model_dump(),
            "trend_state": current_trend_state.model_dump(),
            "daily_trend_state": daily_trend_state.model_dump(),
            "h4_trend_state": h4_trend_state.model_dump(),
            "daily_fvgs": [f.model_dump() for f in daily_fvgs],
            "h4_fvgs": [f.model_dump() for f in h4_fvgs],
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
            "opposing_warnings": opposing_warnings
        }
