from typing import List, Optional
from backend.smc.models import Candle, SwingPoint, Trendline

def calculate_trendlines(candles: List[Candle], swings: List[SwingPoint], timeframe: str) -> List[Trendline]:
    """
    Identify prominent 1H and 30M trendlines and detect confirmed breakouts/breakdowns.
    """
    trendlines: List[Trendline] = []
    if len(swings) < 3 or len(candles) < 10:
        return trendlines

    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    # Resistance Trendline (connecting 2 descending swing highs)
    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        if h2.time > h1.time and h2.price < h1.price:  # Downward slope
            slope = (h2.price - h1.price) / (h2.time - h1.time)
            tl = Trendline(
                timeframe=timeframe,
                direction="resistance",
                start_time=h1.time,
                start_price=h1.price,
                end_time=h2.time,
                end_price=h2.price,
                broken=False
            )
            # Check for breakout in subsequent candles
            for c in candles:
                if c.time > h2.time:
                    projected_price = h2.price + slope * (c.time - h2.time)
                    if c.close > projected_price:
                        tl.broken = True
                        tl.breakout_time = c.time
                        break
            trendlines.append(tl)

    # Support Trendline (connecting 2 ascending swing lows)
    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        if l2.time > l1.time and l2.price > l1.price:  # Upward slope
            slope = (l2.price - l1.price) / (l2.time - l1.time)
            tl = Trendline(
                timeframe=timeframe,
                direction="support",
                start_time=l1.time,
                start_price=l1.price,
                end_time=l2.time,
                end_price=l2.price,
                broken=False
            )
            for c in candles:
                if c.time > l2.time:
                    projected_price = l2.price + slope * (c.time - l2.time)
                    if c.close < projected_price:
                        tl.broken = True
                        tl.breakout_time = c.time
                        break
            trendlines.append(tl)

    return trendlines
