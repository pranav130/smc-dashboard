"""
SMC Dashboard — Pydantic data models.
All models are pure-Python / Pydantic; no pandas/numpy dependency here.
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core market data
# ---------------------------------------------------------------------------

class Candle(BaseModel):
    time: int                  # Unix epoch timestamp in seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    is_forming: bool = False   # True if this is the currently forming live candle
    ist_time: Optional[str] = None


class MarketDataStatus(BaseModel):
    instrument_name: str = "Tether Gold Token Perpetual Future"
    symbol: str = "XAUTUSD"
    product_id: int = 131253
    contract_type: str = "perpetual_futures"
    quote_currency: str = "USD"
    settling_currency: str = "USD"
    contract_value: str = "0.001 XAUT"
    tick_size: float = 0.01
    data_provider: str = "Delta Exchange India"
    selected_timeframe: str = "1H"
    last_candle_timestamp: int = 0
    last_candle_ist: str = ""
    last_update_timestamp: int = 0
    last_update_ist: str = ""
    connection_status: Literal["Connected", "Reconnecting", "Delayed", "Disconnected", "Polling Fallback"] = "Disconnected"
    candle_state: Literal["Confirmed", "Forming"] = "Confirmed"
    current_price: float = 0.0
    is_stale: bool = False
    warnings: List[str] = Field(default_factory=list)
    # Disclosure: Delta perpetual vs spot basis
    basis_disclosure: str = (
        "XAUTUSD is a perpetual futures contract on Delta Exchange India. "
        "Mark price typically trades 0.06%–0.18% above TradingView XAUUSD spot "
        "due to normal perpetual funding premium. This is expected and disclosed."
    )


# ---------------------------------------------------------------------------
# Fair Value Gaps
# ---------------------------------------------------------------------------

class FairValueGap(BaseModel):
    id: str
    timeframe: str                        # "1D", "4H", "1H", "30M"
    direction: Literal["bullish", "bearish"]
    top: float                            # Upper boundary
    bottom: float                         # Lower boundary
    midpoint: float                       # 50% Equilibrium / Critical Section POI
    start_time: int
    start_ist: Optional[str] = None
    mitigated: bool = False
    mitigated_at: Optional[int] = None
    mitigated_ist: Optional[str] = None
    mitigation_level: Literal["unmitigated", "partial_50", "fully_mitigated"] = "unmitigated"
    is_displacement: bool = False         # True if the middle candle was a displacement candle
    inverted: bool = False                # True if price closed fully through, flipping role
    inverted_at: Optional[int] = None
    size: float = 0.0                     # Gap size in price units


# ---------------------------------------------------------------------------
# Market Structure
# ---------------------------------------------------------------------------

class SwingPoint(BaseModel):
    time: int
    confirm_time: int                     # Time at which this swing was KNOWABLE (pivot_time + n bars)
    ist_time: Optional[str] = None
    price: float
    type: Literal["high", "low"]
    timeframe: str
    label: Literal["HH", "HL", "LH", "LL", ""] = ""   # HH/HL/LH/LL label


class BreakOfStructure(BaseModel):
    time: int
    ist_time: Optional[str] = None
    type: Literal["bullish", "bearish"]
    kind: Literal["BOS", "CHoCH"] = "BOS"   # BOS = trend-continuation, CHoCH = trend-flip
    broken_level: float
    retracement_pct: float                   # Must be >= 40.0% to satisfy user's rule
    valid: bool
    timeframe: str


class TrendState(BaseModel):
    """Current structural trend as of the last confirmed swing."""
    trend: Literal["bullish", "bearish", "undetermined"] = "undetermined"
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None
    last_swing_high_time: Optional[int] = None
    last_swing_low_time: Optional[int] = None
    description: str = ""                    # Plain-language description for UI


# ---------------------------------------------------------------------------
# Order Blocks & Displacement
# ---------------------------------------------------------------------------

class DisplacementCandle(BaseModel):
    """A candle whose body >= body_atr_multiplier * ATR(14)."""
    time: int
    ist_time: Optional[str] = None
    direction: Literal["bullish", "bearish"]
    body_size: float
    atr: float
    body_atr_ratio: float
    timeframe: str


class OrderBlock(BaseModel):
    """
    Strict ICT Order Block: the last opposite-colour candle immediately
    preceding the displacement move that caused a BoS or CHoCH.
    Known only at the bar when the BoS/CHoCH is confirmed.
    """
    id: str
    timeframe: str
    direction: Literal["bullish", "bearish"]   # bullish OB = support zone; bearish OB = resistance zone
    top: float
    bottom: float
    midpoint: float
    created_time: int                           # When the OB became knowable (BoS/CHoCH confirmation bar)
    origin_time: int                            # The actual OB candle's timestamp
    origin_ist: Optional[str] = None
    created_ist: Optional[str] = None
    broken_level: float                         # The swing level that was broken to confirm this OB
    mitigated: bool = False
    mitigated_at: Optional[int] = None
    mitigated_ist: Optional[str] = None
    is_breaker: bool = False                    # True if price closed fully through (breaker block)
    breaker_at: Optional[int] = None


# ---------------------------------------------------------------------------
# Premium / Discount / OTE
# ---------------------------------------------------------------------------

class PremiumDiscountZone(BaseModel):
    """
    Premium = upper 50% of the dealing range (last swing low → last swing high).
    Discount = lower 50%.
    """
    timeframe: str
    range_high: float                           # Last confirmed swing high
    range_low: float                            # Last confirmed swing low
    equilibrium: float                          # 50% midpoint
    current_price: float
    position: Literal["premium", "discount", "equilibrium", "undetermined"] = "undetermined"
    position_pct: float = 0.0                  # 0% = range_low, 100% = range_high
    description: str = ""


class OTEZone(BaseModel):
    """
    Optimal Trade Entry: 62%–79% retracement of the most recent impulse leg.
    Impulse leg = distance between the last two confirmed swings of opposite type.
    """
    timeframe: str
    direction: Literal["bullish", "bearish"]   # bullish OTE = discount retracement buy zone
    top: float                                  # 62% retracement level
    bottom: float                               # 79% retracement level
    midpoint: float
    impulse_start: float
    impulse_end: float
    in_zone: bool = False                       # True if current price is inside the OTE zone


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------

class LiquidityLevel(BaseModel):
    type: Literal["PDH", "PDL", "PWH", "PWL", "EQH", "EQL"]
    label: str
    price: float
    time: int
    ist_time: Optional[str] = None
    swept: bool = False
    sweep_time: Optional[int] = None
    sweep_ist: Optional[str] = None


# ---------------------------------------------------------------------------
# Psychological Levels
# ---------------------------------------------------------------------------

class PsychologicalLevel(BaseModel):
    price: float
    level_type: Literal["20", "80"]
    distance: float
    distance_pct: float


# ---------------------------------------------------------------------------
# Trendlines
# ---------------------------------------------------------------------------

class TrendlineTouch(BaseModel):
    time: int
    price: float
    ist_time: Optional[str] = None


class Trendline(BaseModel):
    id: str
    timeframe: str
    direction: Literal["support", "resistance"]   # support = ascending, resistance = descending
    anchor1_time: int
    anchor1_price: float
    anchor2_time: int
    anchor2_price: float
    touch_count: int = 2
    touches: List[TrendlineTouch] = Field(default_factory=list)
    broken: bool = False
    breakout_time: Optional[int] = None
    breakout_ist: Optional[str] = None
    slope: float = 0.0                            # price per second
    # Price at the current bar (projected from slope)
    current_projected_price: Optional[float] = None
    # Was the break confirmed by a close (not just a wick)?
    break_confirmed_by_close: bool = False


# ---------------------------------------------------------------------------
# Level Ranking
# ---------------------------------------------------------------------------

class LevelRanking(BaseModel):
    """
    Scored summary entry for a key level. Used in Key Levels table.
    Score is a heuristic ranking aid — NOT a probability of trade success.
    """
    name: str
    type: str                                     # "HTF FVG", "OrderBlock", "Liquidity", "Psychological", etc.
    price: float
    timeframe: str
    direction: Optional[str] = None               # "bullish"/"bearish" for FVGs/OBs, None for liquidity
    distance: float                               # Signed: positive = above current price
    distance_pct: float
    top: Optional[float] = None                  # Zone top (for FVGs, OBs)
    bottom: Optional[float] = None               # Zone bottom
    mitigation: Optional[str] = None             # unmitigated / partial_50 / fully_mitigated
    swept: Optional[bool] = None
    score: int = 0                               # Ranking score (higher = more significant)
    score_reason: str = ""                       # Plain-language reason for score
    source_id: Optional[str] = None             # Original zone ID


# ---------------------------------------------------------------------------
# Market State
# ---------------------------------------------------------------------------

class MarketState(BaseModel):
    """
    Plain-language market state summary. Descriptive only — NO trading signals.
    """
    current_price: float = 0.0
    timeframe: str = "1H"

    # Trend
    daily_trend: Literal["bullish", "bearish", "undetermined"] = "undetermined"
    h4_trend: Literal["bullish", "bearish", "undetermined"] = "undetermined"
    current_tf_trend: Literal["bullish", "bearish", "undetermined"] = "undetermined"

    # Premium / Discount relative to daily range
    daily_position: Literal["premium", "discount", "equilibrium", "undetermined"] = "undetermined"
    daily_position_pct: float = 0.0

    # Nearest levels
    nearest_level_above: Optional[str] = None
    nearest_level_above_price: Optional[float] = None
    nearest_level_below: Optional[str] = None
    nearest_level_below_price: Optional[float] = None

    # Opposing zone warnings
    opposing_htf_fvg_above: Optional[str] = None
    opposing_htf_fvg_below: Optional[str] = None

    # OTE state
    in_ote_zone: bool = False
    ote_description: Optional[str] = None

    # Free-text summary
    summary: str = ""
    warnings: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Analysis config (passed through API query params / engine)
# ---------------------------------------------------------------------------

class AnalysisConfig(BaseModel):
    """All key thresholds are configurable here — none are hardcoded in modules."""
    # Swing detection
    swing_window: int = 3           # N bars each side for swing detection
    # Confirmation offset handled internally: confirm_time = pivot_time + window candles

    # FVG
    fvg_min_size_atr_multiplier: float = 0.1   # Minimum FVG size as fraction of ATR(14)
    fvg_join_consecutive: bool = False           # Merge touching same-direction FVGs

    # Displacement
    displacement_body_atr_multiplier: float = 1.5

    # BOS
    bos_min_retracement_pct: float = 40.0

    # Equal Highs/Lows tolerance (as multiplier of ATR)
    eql_tolerance_atr_multiplier: float = 0.3

    # Order Blocks
    ob_max_gap_bars: int = 10       # Max bars between OB candle and displacement candle

    # Trendlines
    trendline_min_touches: int = 2
    trendline_max_angle_deg: float = 70.0       # Reject near-vertical trendlines
    trendline_break_requires_close: bool = True  # Close must confirm break (not just wick)

    # Premium/Discount
    ote_low_pct: float = 0.62
    ote_high_pct: float = 0.79

    # Opposing zone warning distance
    opposing_zone_pct: float = 0.015   # 1.5%

    # Key levels
    max_levels_display: int = 20

    # Key-Level Activation & Watchlist thresholds (incorporating ATR and zone width)
    activation_approach_atr_multiplier: float = 1.5   # Threshold for APPROACHING state
    activation_at_level_atr_multiplier: float = 0.5   # Buffer around zone boundary for AT KEY LEVEL
    activation_sweep_recency_bars: int = 10           # Recency window for liquidity sweep reaction
    activation_break_recency_bars: int = 15           # Recency window for trendline breakout setup


# ---------------------------------------------------------------------------
# Key-Level Activation & Trade-Readiness Watchlist
# ---------------------------------------------------------------------------

ActivationState = Literal[
    "INACTIVE",
    "APPROACHING",
    "AT KEY LEVEL",
    "REACTION DEVELOPING",
    "SETUP TO INSPECT",
    "CHECKLIST REVIEW",
    "INVALIDATED / PASSED"
]


class ChecklistItem(BaseModel):
    id: str
    name: str
    description: str
    satisfied: bool = False
    evidence: str = "Pending"
    timeframe: Optional[str] = None


class WatchlistEntry(BaseModel):
    level_id: str
    name: str
    type: str                             # "HTF FVG", "OrderBlock", "Liquidity", "Support/Resistance"
    timeframe: str                        # "1D", "4H", "1H", etc.
    direction: Optional[str] = None       # "bullish", "bearish", None
    price: float                          # Midpoint or single level price
    top: Optional[float] = None
    bottom: Optional[float] = None
    zone_width: float = 0.0
    distance: float                       # Signed distance to current price
    distance_pct: float
    freshness: str = "Active"             # "unmitigated", "partial_50", "swept", "active"
    state: ActivationState = "INACTIVE"
    state_reason: str = ""
    evidence: List[str] = Field(default_factory=list)
    checklist: List[ChecklistItem] = Field(default_factory=list)
    opposing_zone_warning: Optional[str] = None
    last_event_time: Optional[int] = None
    last_event_ist: Optional[str] = None
    is_nearest_above: bool = False
    is_nearest_below: bool = False
    score: int = 0


class WatchlistAlert(BaseModel):
    id: str
    level_id: str
    level_name: str
    timeframe: str
    state: ActivationState
    message: str
    evidence: List[str] = Field(default_factory=list)
    timestamp: int
    ist_time: Optional[str] = ""
    acknowledged: bool = False
    is_stale_suppressed: bool = False
