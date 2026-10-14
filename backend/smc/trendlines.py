"""
Trendline construction, multi-touch validation, and breakout detection.

Rules (specifically geared for 1H and 30M):
- At least 2 confirmed swing points (anchors) required.
- Third touch or more reinforces line validity.
- Breakout validation requires candle CLOSE through the trendline (not just wick).
- Slope / angular limits applied to avoid vertical or unrealistic trendlines.
"""
from typing import List, Optional
import math
from backend.smc.models import (
    Candle, SwingPoint, Trendline, TrendlineTouch, AnalysisConfig
)


def calculate_trendlines(
    candles: List[Candle],
    swings: List[SwingPoint],
    timeframe: str,
    config: Optional[AnalysisConfig] = None
) -> List[Trendline]:
    """
    Construct valid trendlines from confirmed swings and track breakout status.
    """
    if config is None:
        config = AnalysisConfig()

    trendlines: List[Trendline] = []
    if len(swings) < 2 or len(candles) < 5:
        return trendlines

    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    time_map = {c.time: idx for idx, c in enumerate(candles)}
    current_time = candles[-1].time

    # 1. Resistance Trendline (Connecting descending swing highs)
    if len(highs) >= 2:
        for i in range(len(highs) - 1):
            h1 = highs[i]
            h2 = highs[i + 1]

            # Descending slope for resistance line
            if h2.price < h1.price and h2.time > h1.time:
                time_diff = h2.time - h1.time
                slope = (h2.price - h1.price) / time_diff

                # Find additional touches along the ray
                touches = [
                    TrendlineTouch(time=h1.time, price=h1.price, ist_time=h1.ist_time),
                    TrendlineTouch(time=h2.time, price=h2.price, ist_time=h2.ist_time),
                ]

                # Check intermediate or subsequent highs that touch the line (tolerance ±0.50)
                for h_other in highs[i + 2:]:
                    expected_p = h1.price + slope * (h_other.time - h1.time)
                    if abs(h_other.price - expected_p) <= 0.75:
                        touches.append(TrendlineTouch(time=h_other.time, price=h_other.price, ist_time=h_other.ist_time))

                # Track breakout: candle closes above trendline
                broken = False
                breakout_time = None
                breakout_ist = None

                h2_idx = time_map.get(h2.time, len(candles) - 1)
                for c in candles[h2_idx + 1:]:
                    line_price = h1.price + slope * (c.time - h1.time)
                    if config.trendline_break_requires_close:
                        if not c.is_forming and c.close > line_price:
                            broken = True
                            breakout_time = c.time
                            breakout_ist = c.ist_time
                            break
                    else:
                        if c.high > line_price:
                            broken = True
                            breakout_time = c.time
                            breakout_ist = c.ist_time
                            break

                # Evaluate structural support: higher low before bullish breakout
                has_hl = False
                note = None
                if broken and breakout_time:
                    # Check swing lows that formed between h1 and breakout_time
                    inter_lows = [l for l in lows if h1.time <= l.time <= breakout_time]
                    if len(inter_lows) >= 2 and inter_lows[-1].price > inter_lows[-2].price:
                        has_hl = True
                        note = f"Higher low at ${inter_lows[-1].price:.2f} supported bullish breakout"
                    elif any(l.label == "HL" for l in inter_lows):
                        has_hl = True
                        note = "Higher low confirmed prior to breakout"

                proj_price = round(h1.price + slope * (current_time - h1.time), 2)
                if not broken and candles and candles[-1].close > proj_price:
                    broken = True
                    breakout_time = candles[-1].time
                    breakout_ist = candles[-1].ist_time

                tl_id = f"tl_res_{timeframe}_{h1.time}_{h2.time}"
                trendlines.append(Trendline(
                    id=tl_id,
                    timeframe=timeframe,
                    direction="resistance",
                    anchor1_time=h1.time,
                    anchor1_price=h1.price,
                    anchor2_time=h2.time,
                    anchor2_price=h2.price,
                    touch_count=len(touches),
                    touches=touches,
                    broken=broken,
                    breakout_time=breakout_time,
                    breakout_ist=breakout_ist,
                    slope=slope,
                    current_projected_price=proj_price,
                    break_confirmed_by_close=broken and config.trendline_break_requires_close,
                    has_higher_low_pre_break=has_hl,
                    structural_support_note=note
                ))

    # 2. Support Trendline (Connecting ascending swing lows)
    if len(lows) >= 2:
        for i in range(len(lows) - 1):
            l1 = lows[i]
            l2 = lows[i + 1]

            # Ascending slope for support line
            if l2.price > l1.price and l2.time > l1.time:
                time_diff = l2.time - l1.time
                slope = (l2.price - l1.price) / time_diff

                touches = [
                    TrendlineTouch(time=l1.time, price=l1.price, ist_time=l1.ist_time),
                    TrendlineTouch(time=l2.time, price=l2.price, ist_time=l2.ist_time),
                ]

                for l_other in lows[i + 2:]:
                    expected_p = l1.price + slope * (l_other.time - l1.time)
                    if abs(l_other.price - expected_p) <= 0.75:
                        touches.append(TrendlineTouch(time=l_other.time, price=l_other.price, ist_time=l_other.ist_time))

                broken = False
                breakout_time = None
                breakout_ist = None

                l2_idx = time_map.get(l2.time, len(candles) - 1)
                for c in candles[l2_idx + 1:]:
                    line_price = l1.price + slope * (c.time - l1.time)
                    if config.trendline_break_requires_close:
                        if not c.is_forming and c.close < line_price:
                            broken = True
                            breakout_time = c.time
                            breakout_ist = c.ist_time
                            break
                    else:
                        if c.low < line_price:
                            broken = True
                            breakout_time = c.time
                            breakout_ist = c.ist_time
                            break

                # Evaluate structural support: lower high before bearish breakdown
                has_lh = False
                note = None
                if broken and breakout_time:
                    inter_highs = [h for h in highs if l1.time <= h.time <= breakout_time]
                    if len(inter_highs) >= 2 and inter_highs[-1].price < inter_highs[-2].price:
                        has_lh = True
                        note = f"Lower high at ${inter_highs[-1].price:.2f} supported bearish breakdown"
                    elif any(h.label == "LH" for h in inter_highs):
                        has_lh = True
                        note = "Lower high confirmed prior to breakdown"

                proj_price = round(l1.price + slope * (current_time - l1.time), 2)
                if not broken and candles and candles[-1].close < proj_price:
                    broken = True
                    breakout_time = candles[-1].time
                    breakout_ist = candles[-1].ist_time

                tl_id = f"tl_sup_{timeframe}_{l1.time}_{l2.time}"
                trendlines.append(Trendline(
                    id=tl_id,
                    timeframe=timeframe,
                    direction="support",
                    anchor1_time=l1.time,
                    anchor1_price=l1.price,
                    anchor2_time=l2.time,
                    anchor2_price=l2.price,
                    touch_count=len(touches),
                    touches=touches,
                    broken=broken,
                    breakout_time=breakout_time,
                    breakout_ist=breakout_ist,
                    slope=slope,
                    current_projected_price=proj_price,
                    break_confirmed_by_close=broken and config.trendline_break_requires_close,
                    has_lower_high_pre_break=has_lh,
                    structural_support_note=note
                ))

    # Deduplicate and prioritize high-quality trendlines:
    # 1. Prefer >= 3 touches over 2 touches.
    # 2. If multiple trendlines in the same direction project within $4.00 USD of each other,
    #    keep only the single strongest line with the highest touch count.
    trendlines.sort(key=lambda t: (t.touch_count, 1 if t.broken else 0, t.anchor2_time), reverse=True)
    deduped: List[Trendline] = []
    for tl in trendlines:
        if tl.current_projected_price is None:
            continue
        collides = any(
            d.direction == tl.direction and abs(d.current_projected_price - tl.current_projected_price) < 4.0
            for d in deduped
        )
        if not collides:
            deduped.append(tl)

    return deduped[:4]
