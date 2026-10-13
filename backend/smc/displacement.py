"""
Displacement detection and Order Block identification.

Definitions (canonical for this codebase):

* Displacement: a candle whose body >= body_atr_multiplier × ATR(14). Default 1.5×.
  Body = |close − open|. Known at the close of that candle.

* Order Block (strict ICT definition): the LAST opposite-colour candle immediately
  preceding the displacement candle that caused a BoS or CHoCH. Known only at the
  bar when the BoS/CHoCH is confirmed. Zone = that candle's full high–low range.

* Breaker Block: an OB through which price subsequently closes fully. Zone role
  flips (bullish OB → bearish resistance). First retest from the new side = signal.

Attribution: Algorithm conceptually from smc-backtester/detectors/ict.py
(no LICENSE file — used as algorithmic reference only, adapted to our Candle model).
"""
from typing import List, Optional
from backend.smc.models import (
    Candle, SwingPoint, BreakOfStructure, DisplacementCandle, OrderBlock,
    AnalysisConfig
)
from backend.smc.structure import _atr


# ---------------------------------------------------------------------------
# Displacement detection
# ---------------------------------------------------------------------------

def find_displacement_candles(
    candles: List[Candle],
    timeframe: str,
    config: Optional[AnalysisConfig] = None
) -> List[DisplacementCandle]:
    """
    Return all candles whose body >= displacement_body_atr_multiplier × ATR(14).
    The ATR is calculated up to and including each candle (no lookahead).
    """
    if config is None:
        config = AnalysisConfig()
    if len(candles) < 2:
        return []

    result: List[DisplacementCandle] = []
    period = 14
    mult = config.displacement_body_atr_multiplier

    for i in range(1, len(candles)):
        c = candles[i]
        # Prevent premature signals: displacement is confirmed only at candle close
        if c.is_forming:
            continue
        body = abs(c.close - c.open)

        # ATR uses only candles up to and including i (no lookahead)
        atr_val = _atr(candles[:i + 1], period)
        if atr_val <= 0:
            continue

        ratio = body / atr_val
        if ratio >= mult:
            direction = "bullish" if c.close > c.open else "bearish"
            result.append(DisplacementCandle(
                time=c.time,
                ist_time=c.ist_time,
                direction=direction,
                body_size=round(body, 2),
                atr=round(atr_val, 2),
                body_atr_ratio=round(ratio, 2),
                timeframe=timeframe
            ))

    return result


# ---------------------------------------------------------------------------
# Order Block detection
# ---------------------------------------------------------------------------

def find_order_blocks(
    candles: List[Candle],
    bos_signals: List[BreakOfStructure],
    displacement_candles: List[DisplacementCandle],
    timeframe: str,
    config: Optional[AnalysisConfig] = None
) -> List[OrderBlock]:
    """
    For each confirmed BoS or CHoCH, find the corresponding Order Block.
    
    Algorithm (lookahead-free — OB is known only at the BoS/CHoCH confirmation bar):
    1. Find the BoS/CHoCH confirmation candle.
    2. Walk backwards to find the most recent displacement candle in the leg
       that preceded the break (same direction as the break, within max_gap_bars).
    3. From that displacement candle, walk further backwards to find the last
       opposite-colour candle — that is the Order Block.
    4. Zone = OB candle's full high–low range.
    
    Mitigation and breaker logic are tracked forward from OB creation.
    """
    if config is None:
        config = AnalysisConfig()

    result: List[OrderBlock] = []
    if not bos_signals or not candles:
        return result

    # Index candles by time for fast lookup
    time_to_idx = {c.time: i for i, c in enumerate(candles)}
    disp_times = {d.time: d for d in displacement_candles}

    ob_ids_created: set = set()

    for bos in bos_signals:
        bos_idx = time_to_idx.get(bos.time)
        if bos_idx is None:
            continue

        # Bullish BoS/CHoCH: the OB is a bearish (supply-absorbing) candle just
        # before the bullish displacement that drove price up through the swing.
        # It acts as a demand/support zone.
        #
        # Bearish BoS/CHoCH: the OB is a bullish candle just before the bearish
        # displacement — acts as a supply/resistance zone.
        is_bullish_break = bos.type == "bullish"

        # Step 1: walk backwards from BoS bar to find last displacement candle
        # that matches the direction of the break (within max_gap_bars)
        displacement_idx = None
        for k in range(bos_idx - 1, max(0, bos_idx - config.ob_max_gap_bars) - 1, -1):
            c = candles[k]
            if c.time in disp_times:
                d = disp_times[c.time]
                # For bullish break, displacement candle should be bullish
                if is_bullish_break and d.direction == "bullish":
                    displacement_idx = k
                    break
                elif not is_bullish_break and d.direction == "bearish":
                    displacement_idx = k
                    break

        if displacement_idx is None:
            # No displacement candle found — fall back to using the candle 2 bars before BoS
            # as an approximate origin (lookahead-free: we know this at the BoS bar)
            displacement_idx = max(0, bos_idx - 2)

        # Step 2: walk backwards from displacement_idx to find last opposite-colour candle
        ob_candle: Optional[Candle] = None
        for k in range(displacement_idx - 1, -1, -1):
            c = candles[k]
            c_is_bullish = c.close > c.open
            if is_bullish_break and not c_is_bullish:  # last bearish candle → bullish OB
                ob_candle = c
                break
            elif not is_bullish_break and c_is_bullish:  # last bullish candle → bearish OB
                ob_candle = c
                break

        if ob_candle is None:
            continue

        ob_direction = "bullish" if is_bullish_break else "bearish"
        ob_id = f"ob_{ob_direction}_{timeframe}_{ob_candle.time}"
        if ob_id in ob_ids_created:
            continue
        ob_ids_created.add(ob_id)

        # The OB zone = the OB candle's full high–low range
        ob_top = round(ob_candle.high, 2)
        ob_bottom = round(ob_candle.low, 2)
        ob_mid = round((ob_top + ob_bottom) / 2.0, 2)

        ob = OrderBlock(
            id=ob_id,
            timeframe=timeframe,
            direction=ob_direction,
            top=ob_top,
            bottom=ob_bottom,
            midpoint=ob_mid,
            created_time=bos.time,       # Known at the BoS confirmation bar
            origin_time=ob_candle.time,
            origin_ist=ob_candle.ist_time,
            created_ist=bos.ist_time,
            broken_level=bos.broken_level,
            mitigated=False,
            is_breaker=False
        )

        # Step 3: Track mitigation and breaker conversion forward
        ob_known_idx = bos_idx  # OB is knowable from this index
        for k in range(ob_known_idx + 1, len(candles)):
            future = candles[k]
            if ob.direction == "bullish":
                # Bullish OB = demand zone; mitigated when price touches from above
                if future.low <= ob.top and not ob.mitigated:
                    ob.mitigated = True
                    ob.mitigated_at = future.time
                    ob.mitigated_ist = future.ist_time
                # Breaker: price closes fully below the zone
                if not ob.is_breaker and future.close < ob.bottom:
                    ob.is_breaker = True
                    ob.breaker_at = future.time
                    break  # Zone role flipped — no longer tracking as OB
            else:
                # Bearish OB = supply zone; mitigated when price touches from below
                if future.high >= ob.bottom and not ob.mitigated:
                    ob.mitigated = True
                    ob.mitigated_at = future.time
                    ob.mitigated_ist = future.ist_time
                # Breaker: price closes fully above the zone
                if not ob.is_breaker and future.close > ob.top:
                    ob.is_breaker = True
                    ob.breaker_at = future.time
                    break

        result.append(ob)

    # Sort by creation time
    result.sort(key=lambda o: o.created_time)
    return result
