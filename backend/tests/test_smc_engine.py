import pytest
from backend.smc.models import Candle
from backend.smc.fvg import calculate_fvgs
from backend.smc.structure import find_swings, calculate_bos
from backend.smc.liquidity import calculate_pdh_pdl
from backend.smc.psychological import calculate_psychological_levels

def make_candle(t: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(time=t, open=o, high=h, low=l, close=c, volume=100.0, is_forming=False, ist_time=f"T{t}")

def test_bullish_fvg_and_midpoint():
    # 3 candles where candle 2 low > candle 0 high
    c0 = make_candle(100, 4100, 4110, 4095, 4105)
    c1 = make_candle(200, 4105, 4150, 4105, 4145)  # Large displacement
    c2 = make_candle(300, 4145, 4160, 4130, 4155)  # Low is 4130 > 4110 (c0 high)

    fvgs = calculate_fvgs([c0, c1, c2], "1H")
    assert len(fvgs) == 1
    fvg = fvgs[0]
    assert fvg.direction == "bullish"
    assert fvg.top == 4130.0
    assert fvg.bottom == 4110.0
    assert fvg.midpoint == 4120.0  # 50% Equilibrium POI
    assert fvg.mitigated is False
    assert fvg.mitigation_level == "unmitigated"

def test_fvg_mitigation_partial_and_full():
    c0 = make_candle(100, 4100, 4110, 4095, 4105)
    c1 = make_candle(200, 4105, 4150, 4105, 4145)
    c2 = make_candle(300, 4145, 4160, 4130, 4155)  # FVG between 4110 and 4130, midpoint 4120
    
    # Candle 3 retraces to 4115 (past 50% midpoint 4120, but above bottom 4110)
    c3 = make_candle(400, 4155, 4155, 4115, 4125)
    fvgs_partial = calculate_fvgs([c0, c1, c2, c3], "1H")
    assert fvgs_partial[0].mitigation_level == "partial_50"
    assert fvgs_partial[0].mitigated is False

    # Candle 4 completely breaks below bottom 4110 -> full mitigation
    c4 = make_candle(500, 4125, 4130, 4100, 4105)
    fvgs_full = calculate_fvgs([c0, c1, c2, c3, c4], "1H")
    assert fvgs_full[0].mitigated is True
    assert fvgs_full[0].mitigation_level == "fully_mitigated"

def test_bos_40_percent_rule():
    # Construct swings:
    # Swing low at 4000, swing high at 4200 (leg = 200)
    # Pullback to 4100 (retracement = 100/200 = 50% >= 40%) -> VALID BoS when breaking 4200
    candles = [
        make_candle(10, 4000, 4010, 3990, 4005),
        make_candle(20, 4005, 4050, 4000, 4045),
        make_candle(30, 4045, 4100, 4040, 4095),
        make_candle(40, 4095, 4205, 4090, 4200),  # Swing High around 4205
        make_candle(50, 4200, 4202, 4150, 4160),
        make_candle(60, 4160, 4170, 4100, 4110),  # Retracement to 4100 (50% pullback)
        make_candle(70, 4110, 4180, 4105, 4175),
        make_candle(80, 4175, 4220, 4170, 4215),  # Closes at 4215 > 4205 -> BoS!
    ]
    swings = find_swings(candles, "30M", window=1)
    bos_list = calculate_bos(candles, swings, "30M")
    assert any(b.valid and b.retracement_pct >= 40.0 for b in bos_list)

def test_liquidity_sweep_detection():
    # Previous day candle
    daily = [
        make_candle(1000, 4150, 4200, 4100, 4180),  # Prev day: High=4200, Low=4100
        make_candle(2000, 4180, 4210, 4170, 4190)   # Current forming day
    ]
    # Intraday candle that pierces PDH (high=4205) but closes back below (close=4195) -> SWEEP!
    intraday = [
        make_candle(1500, 4185, 4205, 4180, 4195)
    ]
    levels = calculate_pdh_pdl(daily, intraday)
    pdh = next(l for l in levels if l.type == "PDH")
    assert pdh.price == 4200.0
    assert pdh.swept is True

def test_psychological_levels():
    levels = calculate_psychological_levels(4192.50)
    prices = [l.price for l in levels]
    # Check that 4180.0 and 4220.0 are found
    assert 4180.0 in prices
    assert 4220.0 in prices

def test_zero_lookahead_bias():
    # Confirm that adding future candles does NOT alter past confirmed FVG properties
    c0 = make_candle(100, 4100, 4110, 4095, 4105)
    c1 = make_candle(200, 4105, 4150, 4105, 4145)
    c2 = make_candle(300, 4145, 4160, 4130, 4155)

    initial_fvgs = calculate_fvgs([c0, c1, c2], "1H")
    assert len(initial_fvgs) == 1
    fvg_initial = initial_fvgs[0]

    # Append 5 future candles that do not mitigate
    c3 = make_candle(400, 4155, 4170, 4150, 4165)
    c4 = make_candle(500, 4165, 4180, 4160, 4175)
    extended_fvgs = calculate_fvgs([c0, c1, c2, c3, c4], "1H")

    fvg_extended = extended_fvgs[0]
    assert fvg_extended.top == fvg_initial.top
    assert fvg_extended.bottom == fvg_initial.bottom
    assert fvg_extended.midpoint == fvg_initial.midpoint
    assert fvg_extended.start_time == fvg_initial.start_time
