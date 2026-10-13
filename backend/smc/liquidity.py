from typing import List, Optional
from datetime import datetime
from backend.config import IST_TZ
from backend.smc.models import Candle, LiquidityLevel, SwingPoint

def calculate_pdh_pdl(daily_candles: List[Candle], current_candles: List[Candle]) -> List[LiquidityLevel]:
    """
    Calculate Previous Day High (PDH) and Previous Day Low (PDL) using confirmed Daily candles.
    Also detects if today's price has swept PDH or PDL.
    """
    levels: List[LiquidityLevel] = []
    if len(daily_candles) < 2:
        return levels

    # The last confirmed full daily candle is daily_candles[-2] (or [-1] if [-1] is closed)
    prev_day = daily_candles[-2] if daily_candles[-1].is_forming or len(daily_candles) > 1 else daily_candles[0]

    # PDH
    pdh = LiquidityLevel(
        type="PDH",
        label="Previous Day High",
        price=round(prev_day.high, 2),
        time=prev_day.time,
        ist_time=prev_day.ist_time,
        swept=False
    )

    # PDL
    pdl = LiquidityLevel(
        type="PDL",
        label="Previous Day Low",
        price=round(prev_day.low, 2),
        time=prev_day.time,
        ist_time=prev_day.ist_time,
        swept=False
    )

    # Check for sweeps during current session candles (candles after prev_day.time)
    for c in current_candles:
        if c.time > prev_day.time:
            # High swept: pierced above PDH, but closed below PDH
            if c.high > pdh.price and c.close <= pdh.price:
                pdh.swept = True
                pdh.sweep_time = c.time
                pdh.sweep_ist = c.ist_time
            # Low swept: pierced below PDL, but closed above PDL
            if c.low < pdl.price and c.close >= pdl.price:
                pdl.swept = True
                pdl.sweep_time = c.time
                pdl.sweep_ist = c.ist_time

    levels.extend([pdh, pdl])
    return levels


def calculate_pwh_pwl(daily_candles: List[Candle], current_candles: List[Candle]) -> List[LiquidityLevel]:
    """
    Calculate Previous Week High (PWH) and Previous Week Low (PWL) from previous 7 daily candles.
    """
    levels: List[LiquidityLevel] = []
    if len(daily_candles) < 8:
        return levels

    # Previous full week: 7 daily candles prior to current week
    prev_week_candles = daily_candles[-8:-1]
    if not prev_week_candles:
        return levels

    pwh_val = max(c.high for c in prev_week_candles)
    pwl_val = min(c.low for c in prev_week_candles)
    start_c = prev_week_candles[0]

    pwh = LiquidityLevel(
        type="PWH",
        label="Previous Week High",
        price=round(pwh_val, 2),
        time=start_c.time,
        ist_time=start_c.ist_time,
        swept=False
    )

    pwl = LiquidityLevel(
        type="PWL",
        label="Previous Week Low",
        price=round(pwl_val, 2),
        time=start_c.time,
        ist_time=start_c.ist_time,
        swept=False
    )

    for c in current_candles:
        if c.time > prev_week_candles[-1].time:
            if c.high > pwh.price and c.close <= pwh.price:
                pwh.swept = True
                pwh.sweep_time = c.time
                pwh.sweep_ist = c.ist_time
            if c.low < pwl.price and c.close >= pwl.price:
                pwl.swept = True
                pwl.sweep_time = c.time
                pwl.sweep_ist = c.ist_time

    levels.extend([pwh, pwl])
    return levels


def calculate_equal_highs_lows(swings: List[SwingPoint], tolerance: float = 0.5) -> List[LiquidityLevel]:
    """
    Detect Equal Highs (EQH) and Equal Lows (EQL) forming buy-side / sell-side liquidity pools.
    Tolerance is in USD (e.g. $0.50 on Gold).
    """
    eq_levels: List[LiquidityLevel] = []
    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    # Check Equal Highs
    for i in range(len(highs) - 1):
        for j in range(i + 1, min(i + 4, len(highs))):
            if abs(highs[i].price - highs[j].price) <= tolerance:
                avg_p = round((highs[i].price + highs[j].price) / 2.0, 2)
                eq_levels.append(LiquidityLevel(
                    type="EQH",
                    label=f"Equal Highs (BSL: {avg_p})",
                    price=avg_p,
                    time=highs[j].time,
                    ist_time=highs[j].ist_time,
                    swept=False
                ))

    # Check Equal Lows
    for i in range(len(lows) - 1):
        for j in range(i + 1, min(i + 4, len(lows))):
            if abs(lows[i].price - lows[j].price) <= tolerance:
                avg_p = round((lows[i].price + lows[j].price) / 2.0, 2)
                eq_levels.append(LiquidityLevel(
                    type="EQL",
                    label=f"Equal Lows (SSL: {avg_p})",
                    price=avg_p,
                    time=lows[j].time,
                    ist_time=lows[j].ist_time,
                    swept=False
                ))

    return eq_levels
