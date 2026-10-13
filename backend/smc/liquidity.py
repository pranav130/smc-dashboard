"""
Liquidity levels, Equal Highs/Lows (EQH/EQL), and Liquidity Sweeps.

Definitions:
- PDH / PDL: Previous Day High / Low from confirmed daily candles.
- PWH / PWL: Previous Week High / Low from previous 7 daily candles.
- EQH / EQL: Equal Highs / Lows (tolerance based on ATR multiplier).
- Liquidity Sweep (LS): A candle pierces beyond the liquidity level with its wick
  but closes back inside the level boundary.
"""
from typing import List, Optional
from backend.smc.models import Candle, LiquidityLevel, SwingPoint, AnalysisConfig
from backend.smc.structure import _atr


def calculate_pdh_pdl(daily_candles: List[Candle], current_candles: List[Candle]) -> List[LiquidityLevel]:
    """
    Calculate Previous Day High (PDH) and Low (PDL) using confirmed Daily candles.
    Also detects if intraday price has swept PDH or PDL.
    """
    levels: List[LiquidityLevel] = []
    if len(daily_candles) < 2:
        return levels

    # Last confirmed full daily candle is daily_candles[-2] if [-1] is forming, else [-1]
    prev_day = daily_candles[-2] if daily_candles[-1].is_forming or len(daily_candles) > 1 else daily_candles[0]

    pdh = LiquidityLevel(
        type="PDH",
        label="Previous Day High",
        price=round(prev_day.high, 2),
        time=prev_day.time,
        ist_time=prev_day.ist_time,
        swept=False
    )

    pdl = LiquidityLevel(
        type="PDL",
        label="Previous Day Low",
        price=round(prev_day.low, 2),
        time=prev_day.time,
        ist_time=prev_day.ist_time,
        swept=False
    )

    # Intraday sweep detection
    for c in current_candles:
        if c.time > prev_day.time:
            # Bullish sweep of PDH: wicked above, closed below
            if c.high > pdh.price and c.close <= pdh.price:
                pdh.swept = True
                pdh.sweep_time = c.time
                pdh.sweep_ist = c.ist_time
            # Bearish sweep of PDL: wicked below, closed above
            if c.low < pdl.price and c.close >= pdl.price:
                pdl.swept = True
                pdl.sweep_time = c.time
                pdl.sweep_ist = c.ist_time

    levels.extend([pdh, pdl])
    return levels


def calculate_pwh_pwl(daily_candles: List[Candle], current_candles: List[Candle]) -> List[LiquidityLevel]:
    """
    Calculate Previous Week High (PWH) and Low (PWL) from previous 7 daily candles.
    """
    levels: List[LiquidityLevel] = []
    if len(daily_candles) < 8:
        return levels

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


def calculate_equal_highs_lows(
    candles: List[Candle],
    swings: List[SwingPoint],
    config: Optional[AnalysisConfig] = None
) -> List[LiquidityLevel]:
    """
    Detect Equal Highs (EQH) and Equal Lows (EQL) forming liquidity pools.
    Tolerance is dynamic: config.eql_tolerance_atr_multiplier * ATR(14)
    """
    if config is None:
        config = AnalysisConfig()

    atr_val = _atr(candles, 14) if candles else 1.0
    tol = max(0.2, config.eql_tolerance_atr_multiplier * atr_val)

    eq_levels: List[LiquidityLevel] = []
    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    # Check Equal Highs (Buy-Side Liquidity)
    for i in range(len(highs) - 1):
        for j in range(i + 1, min(i + 4, len(highs))):
            if abs(highs[i].price - highs[j].price) <= tol:
                avg_p = round((highs[i].price + highs[j].price) / 2.0, 2)
                eq_levels.append(LiquidityLevel(
                    type="EQH",
                    label=f"Equal Highs (BSL: {avg_p})",
                    price=avg_p,
                    time=highs[j].time,
                    ist_time=highs[j].ist_time,
                    swept=False
                ))

    # Check Equal Lows (Sell-Side Liquidity)
    for i in range(len(lows) - 1):
        for j in range(i + 1, min(i + 4, len(lows))):
            if abs(lows[i].price - lows[j].price) <= tol:
                avg_p = round((lows[i].price + lows[j].price) / 2.0, 2)
                eq_levels.append(LiquidityLevel(
                    type="EQL",
                    label=f"Equal Lows (SSL: {avg_p})",
                    price=avg_p,
                    time=lows[j].time,
                    ist_time=lows[j].ist_time,
                    swept=False
                ))

    # Check if EQH / EQL have been swept by subsequent candles
    time_map = {c.time: idx for idx, c in enumerate(candles)}
    for eq in eq_levels:
        idx = time_map.get(eq.time)
        if idx is not None:
            for c in candles[idx + 1:]:
                if eq.type == "EQH" and c.high > eq.price and c.close <= eq.price:
                    eq.swept = True
                    eq.sweep_time = c.time
                    eq.sweep_ist = c.ist_time
                    break
                elif eq.type == "EQL" and c.low < eq.price and c.close >= eq.price:
                    eq.swept = True
                    eq.sweep_time = c.time
                    eq.sweep_ist = c.ist_time
                    break

    return eq_levels
