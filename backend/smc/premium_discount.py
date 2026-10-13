"""
Premium / Discount zones and Optimal Trade Entry (OTE).

Definitions (canonical for this codebase):

* Dealing Range: defined by the last confirmed swing low to the last confirmed swing high.
* Equilibrium: 50% midpoint of the dealing range.
* Premium Zone: Upper 50% (above equilibrium) — favorable for selling/shorting.
* Discount Zone: Lower 50% (below equilibrium) — favorable for buying/longing.
* Optimal Trade Entry (OTE): 62%–79% Fibonacci retracement band of the most recent
  impulse leg between opposite confirmed swings.

Attribution: Algorithm inspired by smc-backtester/detectors/ict.py
(used as algorithmic reference only, pure-Python Candle implementation).
"""
from typing import List, Optional
from backend.smc.models import (
    Candle, SwingPoint, PremiumDiscountZone, OTEZone, AnalysisConfig
)


def calculate_premium_discount(
    candles: List[Candle],
    swings: List[SwingPoint],
    timeframe: str,
    current_price: float
) -> PremiumDiscountZone:
    """
    Calculate Premium / Discount state based on the most recent confirmed swing high and low.
    """
    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    if not highs or not lows:
        return PremiumDiscountZone(
            timeframe=timeframe,
            range_high=current_price,
            range_low=current_price,
            equilibrium=current_price,
            current_price=current_price,
            position="undetermined",
            position_pct=50.0,
            description="Insufficient swing points to establish dealing range."
        )

    last_high = highs[-1].price
    last_low = lows[-1].price

    # Ensure range boundaries are valid
    range_high = max(last_high, last_low)
    range_low = min(last_high, last_low)
    range_span = range_high - range_low

    if range_span <= 0:
        eq = range_high
        pos_pct = 50.0
        pos = "equilibrium"
    else:
        eq = round((range_high + range_low) / 2.0, 2)
        pos_pct = round(((current_price - range_low) / range_span) * 100.0, 1)
        if current_price > eq:
            pos = "premium"
        elif current_price < eq:
            pos = "discount"
        else:
            pos = "equilibrium"

    desc = (
        f"Dealing range [{range_low:.2f} - {range_high:.2f}] with Equilibrium at {eq:.2f}. "
        f"Price is currently at {current_price:.2f} ({pos_pct}% of range), located in {pos.upper()} zone."
    )

    return PremiumDiscountZone(
        timeframe=timeframe,
        range_high=range_high,
        range_low=range_low,
        equilibrium=eq,
        current_price=current_price,
        position=pos,
        position_pct=pos_pct,
        description=desc
    )


def calculate_ote(
    swings: List[SwingPoint],
    timeframe: str,
    current_price: float,
    config: Optional[AnalysisConfig] = None
) -> Optional[OTEZone]:
    """
    Calculate Optimal Trade Entry (OTE) zone (62% - 79% retracement of the latest impulse leg).
    """
    if config is None:
        config = AnalysisConfig()

    if len(swings) < 2:
        return None

    s1 = swings[-2]
    s2 = swings[-1]

    # Need opposite swing points to define impulse leg
    if s1.type == s2.type:
        return None

    # Bullish impulse leg (Low -> High) -> Retracement is down towards Discount
    if s1.type == "low" and s2.type == "high":
        leg_start = s1.price
        leg_end = s2.price
        leg_height = leg_end - leg_start
        if leg_height <= 0:
            return None

        # 62% retrace from high = high - (0.62 * leg)
        # 79% retrace from high = high - (0.79 * leg)
        top = round(leg_end - (config.ote_low_pct * leg_height), 2)
        bottom = round(leg_end - (config.ote_high_pct * leg_height), 2)
        mid = round((top + bottom) / 2.0, 2)
        in_zone = (bottom <= current_price <= top)

        return OTEZone(
            timeframe=timeframe,
            direction="bullish",
            top=top,
            bottom=bottom,
            midpoint=mid,
            impulse_start=leg_start,
            impulse_end=leg_end,
            in_zone=in_zone
        )

    # Bearish impulse leg (High -> Low) -> Retracement is up towards Premium
    elif s1.type == "high" and s2.type == "low":
        leg_start = s1.price
        leg_end = s2.price
        leg_drop = leg_start - leg_end
        if leg_drop <= 0:
            return None

        # 62% retrace from low = low + (0.62 * leg)
        # 79% retrace from low = low + (0.79 * leg)
        bottom = round(leg_end + (config.ote_low_pct * leg_drop), 2)
        top = round(leg_end + (config.ote_high_pct * leg_drop), 2)
        mid = round((top + bottom) / 2.0, 2)
        in_zone = (bottom <= current_price <= top)

        return OTEZone(
            timeframe=timeframe,
            direction="bearish",
            top=top,
            bottom=bottom,
            midpoint=mid,
            impulse_start=leg_start,
            impulse_end=leg_end,
            in_zone=in_zone
        )

    return None
