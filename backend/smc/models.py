from typing import Optional, List, Literal
from pydantic import BaseModel, Field

class Candle(BaseModel):
    time: int                  # Unix epoch timestamp in seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    is_forming: bool = False   # True if this is the currently forming live candle
    ist_time: Optional[str] = None

class FairValueGap(BaseModel):
    id: str
    timeframe: str             # "1D", "4H", "1H", "30M"
    direction: Literal["bullish", "bearish"]
    top: float                 # Upper boundary
    bottom: float              # Lower boundary
    midpoint: float            # 50% Equilibrium / Critical Section POI
    start_time: int
    start_ist: Optional[str] = None
    mitigated: bool = False
    mitigated_at: Optional[int] = None
    mitigated_ist: Optional[str] = None
    mitigation_level: Literal["unmitigated", "partial_50", "fully_mitigated"] = "unmitigated"

class SwingPoint(BaseModel):
    time: int
    ist_time: Optional[str] = None
    price: float
    type: Literal["high", "low"]
    timeframe: str

class BreakOfStructure(BaseModel):
    time: int
    ist_time: Optional[str] = None
    type: Literal["bullish", "bearish"]
    broken_level: float
    retracement_pct: float     # Must be >= 40.0% to satisfy user's rule
    valid: bool
    timeframe: str

class LiquidityLevel(BaseModel):
    type: Literal["PDH", "PDL", "PWH", "PWL", "EQH", "EQL"]
    label: str
    price: float
    time: int
    ist_time: Optional[str] = None
    swept: bool = False
    sweep_time: Optional[int] = None
    sweep_ist: Optional[str] = None

class PsychologicalLevel(BaseModel):
    price: float
    level_type: Literal["20", "80"]
    distance: float
    distance_pct: float

class Trendline(BaseModel):
    timeframe: str
    direction: Literal["support", "resistance"]
    start_time: int
    start_price: float
    end_time: int
    end_price: float
    broken: bool = False
    breakout_time: Optional[int] = None

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
