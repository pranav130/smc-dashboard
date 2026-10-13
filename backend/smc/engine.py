from typing import Dict, List, Any
from backend.smc.models import Candle
from backend.smc.fvg import calculate_fvgs, find_overlapping_fvgs
from backend.smc.structure import find_swings, calculate_bos, calculate_support_resistance
from backend.smc.liquidity import calculate_pdh_pdl, calculate_pwh_pwl, calculate_equal_highs_lows
from backend.smc.trendlines import calculate_trendlines
from backend.smc.psychological import calculate_psychological_levels

class SMCEngine:
    """
    Unified SMC Key-Level Intelligence Engine.
    Executes all calculations sequentially without lookahead bias.
    """

    def analyze_multi_timeframe(
        self,
        candles_by_tf: Dict[str, List[Candle]],
        selected_timeframe: str = "1H"
    ) -> Dict[str, Any]:
        """
        Perform complete multi-timeframe SMC analysis for the dashboard.
        """
        tf = selected_timeframe.upper()
        current_candles = candles_by_tf.get(tf, [])
        daily_candles = candles_by_tf.get("1D", [])
        h4_candles = candles_by_tf.get("4H", [])
        h1_candles = candles_by_tf.get("1H", [])
        m30_candles = candles_by_tf.get("30M", [])

        # Current market price
        current_price = 0.0
        if current_candles:
            current_price = current_candles[-1].close

        # 1. Fair Value Gaps
        daily_fvgs = calculate_fvgs(daily_candles, "1D")
        h4_fvgs = calculate_fvgs(h4_candles, "4H")
        curr_fvgs = calculate_fvgs(current_candles, tf) if tf not in ["1D", "4H"] else (daily_fvgs if tf == "1D" else h4_fvgs)

        # Overlapping HTF FVGs (Daily & 4H Critical Sections)
        overlapping_htf_fvgs = find_overlapping_fvgs(daily_fvgs, h4_fvgs)

        # 2. Market Structure & Swings
        swings = find_swings(current_candles, tf, window=3)
        bos_signals = calculate_bos(current_candles, swings, tf)
        sr_zones = calculate_support_resistance(swings)

        # 3. Liquidity Levels & Sweeps
        pdh_pdl = calculate_pdh_pdl(daily_candles, current_candles)
        pwh_pwl = calculate_pwh_pwl(daily_candles, current_candles)
        eq_highs_lows = calculate_equal_highs_lows(swings)

        all_liquidity = pdh_pdl + pwh_pwl + eq_highs_lows

        # 4. Trendlines (1H & 30M)
        trendlines = []
        if tf in ["1H", "30M"]:
            trendlines = calculate_trendlines(current_candles, swings, tf)
        elif h1_candles:
            h1_swings = find_swings(h1_candles, "1H", window=3)
            trendlines = calculate_trendlines(h1_candles, h1_swings, "1H")

        # 5. Psychological 20s and 80s Levels
        psych_levels = calculate_psychological_levels(current_price)

        # 6. Distance from current price to each important level
        key_levels_summary = []

        # Add unmitigated HTF FVGs
        for f in (daily_fvgs + h4_fvgs):
            if not f.mitigated:
                dist = round(f.midpoint - current_price, 2)
                dist_pct = round((dist / current_price) * 100.0, 2) if current_price else 0.0
                key_levels_summary.append({
                    "name": f"{f.timeframe} {f.direction.capitalize()} FVG Midpoint",
                    "type": "HTF FVG 50%",
                    "price": f.midpoint,
                    "top": f.top,
                    "bottom": f.bottom,
                    "distance": dist,
                    "distance_pct": dist_pct,
                    "mitigation": f.mitigation_level,
                    "timeframe": f.timeframe
                })

        # Add Liquidity Levels
        for liq in all_liquidity:
            dist = round(liq.price - current_price, 2)
            dist_pct = round((dist / current_price) * 100.0, 2) if current_price else 0.0
            key_levels_summary.append({
                "name": liq.label,
                "type": "Liquidity",
                "price": liq.price,
                "distance": dist,
                "distance_pct": dist_pct,
                "swept": liq.swept,
                "timeframe": "1D" if "Day" in liq.label else "1W" if "Week" in liq.label else tf
            })

        # Add Psychological Levels
        for pl in psych_levels[:4]:
            key_levels_summary.append({
                "name": f"Round {pl.level_type} Level ({pl.price})",
                "type": "Psychological",
                "price": pl.price,
                "distance": pl.distance,
                "distance_pct": pl.distance_pct,
                "timeframe": "Static"
            })

        # Sort summary by absolute distance from current price
        key_levels_summary.sort(key=lambda x: abs(x["distance"]))

        # 7. Check for Opposing Higher-Timeframe Zones
        # Rule from SMC guide: "Avoid trades when an opposing HTF FVG is present"
        opposing_warnings = []
        if current_price > 0:
            for f in (daily_fvgs + h4_fvgs):
                if not f.mitigated:
                    # If bearish FVG is directly above (< 1.5% distance)
                    if f.direction == "bearish" and 0 < (f.bottom - current_price) < (current_price * 0.015):
                        opposing_warnings.append(
                            f"Warning: Opposing Bearish {f.timeframe} FVG overhead at {f.bottom} - {f.top} (Midpoint: {f.midpoint})"
                        )
                    # If bullish FVG is directly below (< 1.5% distance)
                    elif f.direction == "bullish" and 0 < (current_price - f.top) < (current_price * 0.015):
                        opposing_warnings.append(
                            f"Warning: Opposing Bullish {f.timeframe} FVG support below at {f.bottom} - {f.top} (Midpoint: {f.midpoint})"
                        )

        return {
            "timeframe": tf,
            "current_price": current_price,
            "daily_fvgs": [f.model_dump() for f in daily_fvgs],
            "h4_fvgs": [f.model_dump() for f in h4_fvgs],
            "timeframe_fvgs": [f.model_dump() for f in curr_fvgs],
            "overlapping_htf_fvgs": overlapping_htf_fvgs,
            "swings": [s.model_dump() for s in swings],
            "bos_signals": [b.model_dump() for b in bos_signals],
            "support_resistance": sr_zones,
            "liquidity_levels": [l.model_dump() for l in all_liquidity],
            "trendlines": [t.model_dump() for t in trendlines],
            "psychological_levels": [p.model_dump() for p in psych_levels],
            "key_levels_summary": key_levels_summary,
            "opposing_warnings": opposing_warnings
        }
