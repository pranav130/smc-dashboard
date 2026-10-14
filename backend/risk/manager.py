"""
Authoritative Central Risk Management Engine for XAUTUSD Paper Trading.
Strictly implements Section 6 & Section 9 requirements:
- Maximum 1 concurrent position on XAUTUSD.
- Fixed 0.25% equity risk per trade.
- Exact Delta Exchange India contract sizing (multiplier = 0.001 XAUT).
- $2,500 maximum notional cap.
- Strict rejection if budget < 1 contract (never round up).
- Net R:R >= 2.0 verification after simulated fees (0.05%) and slippage (5 bps).
- 1.0% daily loss limit (00:00 UTC rollover).
- 2.5% weekly loss limit (Monday 00:00 UTC rollover).
- 5.0% peak-to-trough max drawdown circuit breaker.
- Anti-martingale / non-increasing size guarantee.
"""
import math
import time
from typing import Dict, Any, Tuple, Optional
from backend.config import (
    INITIAL_PAPER_BALANCE as INITIAL_EQUITY,
    INITIAL_RISK_PER_TRADE_PCT,
    DAILY_LOSS_LIMIT_PCT,
    WEEKLY_LOSS_LIMIT_PCT,
    MAX_DRAWDOWN_LIMIT_PCT,
    MAX_NOTIONAL_CAP,
    CONTRACT_MULTIPLIER,
    TAKER_FEE_RATE,
    SLIPPAGE_BPS,
    MIN_REWARD_TO_RISK,
    TICK_SIZE,
)
from backend.risk.discipline import DisciplineManager


class RiskManager:
    """Authoritative risk controller governing trade validation, position sizing, and limits."""

    def __init__(
        self,
        starting_equity: float = INITIAL_EQUITY,
        risk_per_trade_pct: float = INITIAL_RISK_PER_TRADE_PCT, # 0.25%
        daily_loss_limit_pct: float = DAILY_LOSS_LIMIT_PCT,     # 1.0%
        weekly_loss_limit_pct: float = WEEKLY_LOSS_LIMIT_PCT,   # 2.5%
        max_drawdown_limit_pct: float = MAX_DRAWDOWN_LIMIT_PCT, # 5.0%
        max_notional_cap: float = MAX_NOTIONAL_CAP,             # $2,500
        contract_multiplier: float = CONTRACT_MULTIPLIER,       # 0.001
        taker_fee_rate: float = TAKER_FEE_RATE,                 # 0.0005
        slippage_bps: float = SLIPPAGE_BPS,                     # 5.0
        min_reward_to_risk: float = MIN_REWARD_TO_RISK,         # 2.0
        discipline_manager: Optional[DisciplineManager] = None
    ):
        self.starting_equity = starting_equity
        self.current_equity = starting_equity
        self.peak_equity = starting_equity
        self.risk_fraction = risk_per_trade_pct / 100.0
        self.daily_loss_fraction = daily_loss_limit_pct / 100.0
        self.weekly_loss_fraction = weekly_loss_limit_pct / 100.0
        self.max_drawdown_fraction = max_drawdown_limit_pct / 100.0
        self.max_notional_cap = max_notional_cap
        self.contract_multiplier = contract_multiplier
        self.taker_fee_rate = taker_fee_rate
        self.slippage_bps = slippage_bps
        self.min_reward_to_risk = min_reward_to_risk

        self.discipline = discipline_manager or DisciplineManager()

        # Session tracking
        self.current_utc_day = time.strftime("%Y-%m-%d", time.gmtime())
        self.current_utc_week = time.strftime("%Y-%W", time.gmtime())
        self.day_start_equity = starting_equity
        self.week_start_equity = starting_equity

        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason: Optional[str] = None

    def update_equity(self, new_equity: float, now: Optional[float] = None):
        """Update current equity and track peak drawdown."""
        if now is None:
            now = time.time()
        self._check_rollovers(now)

        self.current_equity = round(new_equity, 4)
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

        # Peak-to-trough drawdown check (5.0% circuit breaker)
        dd_fraction = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        if dd_fraction >= self.max_drawdown_fraction:
            self.circuit_breaker_tripped = True
            self.circuit_breaker_reason = (
                f"Peak-to-trough drawdown limit reached ({dd_fraction * 100:.2f}% >= {self.max_drawdown_fraction * 100:.1f}%). "
                f"Engine entered circuit breaker HALT. Manual reset required."
            )

    def _check_rollovers(self, now: float):
        day_str = time.strftime("%Y-%m-%d", time.gmtime(now))
        if day_str != self.current_utc_day:
            self.current_utc_day = day_str
            self.day_start_equity = self.current_equity

        week_str = time.strftime("%Y-%W", time.gmtime(now))
        if week_str != self.current_utc_week:
            self.current_utc_week = week_str
            self.week_start_equity = self.current_equity

    def reset_circuit_breaker(self):
        """Explicit operator reset of peak-to-trough circuit breaker."""
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = None
        self.peak_equity = self.current_equity

    def evaluate_order(
        self,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        open_positions_count: int,
        is_feed_safe: bool,
        now: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Authoritatively validate an incoming trade setup and calculate position size.
        Returns:
            Dict containing:
                passed: bool
                reason: str
                qty_contracts: int (or 0)
                qty_xaut: float
                notional: float
                risk_budget: float
                net_rr: float
                telemetry: dict
        """
        if now is None:
            now = time.time()
        self._check_rollovers(now)

        telemetry: Dict[str, Any] = {
            "checks": {},
            "limits": {
                "equity": self.current_equity,
                "peak_equity": self.peak_equity,
                "day_start_equity": self.day_start_equity,
                "week_start_equity": self.week_start_equity,
            }
        }

        # 1. Market Data Safety Check (Fail Closed)
        if not is_feed_safe:
            return self._reject("FEED_UNSAFE_OR_STALE", "Market data feed is not safe (stale, invalid, or disconnected)", telemetry)

        # 2. Circuit Breaker Check
        if self.circuit_breaker_tripped:
            return self._reject("CIRCUIT_BREAKER_ACTIVE", self.circuit_breaker_reason or "Circuit breaker active", telemetry)

        # 3. Daily Loss Limit Check (1.0% of day start equity)
        daily_loss = self.day_start_equity - self.current_equity
        daily_loss_limit = self.day_start_equity * self.daily_loss_fraction
        if daily_loss >= daily_loss_limit:
            return self._reject(
                "DAILY_LOSS_LIMIT_REACHED",
                f"Daily loss (${daily_loss:.2f}) reached limit of ${daily_loss_limit:.2f} (1.0% limit)",
                telemetry
            )

        # 4. Weekly Loss Limit Check (2.5% of week start equity)
        weekly_loss = self.week_start_equity - self.current_equity
        weekly_loss_limit = self.week_start_equity * self.weekly_loss_fraction
        if weekly_loss >= weekly_loss_limit:
            return self._reject(
                "WEEKLY_LOSS_LIMIT_REACHED",
                f"Weekly loss (${weekly_loss:.2f}) reached limit of ${weekly_loss_limit:.2f} (2.5% limit)",
                telemetry
            )

        # 5. Psychological Discipline & Cooldown Check
        allowed_disp, reason_disp, rem_cooldown = self.discipline.can_enter_trade(now)
        if not allowed_disp:
            return self._reject("DISCIPLINE_COOLDOWN_ACTIVE", reason_disp, telemetry)

        # 6. Concurrency Limit (Max 1 concurrent position)
        if open_positions_count >= 1:
            return self._reject("MAX_CONCURRENT_POSITIONS", "Maximum 1 concurrent position allowed on XAUTUSD", telemetry)

        # 7. Price Levels & Direction Ordering
        direction_norm = direction.upper()
        if direction_norm not in ("LONG", "BULLISH", "SHORT", "BEARISH"):
            return self._reject("INVALID_DIRECTION", f"Unknown trade direction: {direction}", telemetry)
        is_long = direction_norm in ("LONG", "BULLISH")

        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            return self._reject("INVALID_LEVEL_PRICES", "Prices must be positive non-zero", telemetry)

        if is_long:
            if not (stop_loss < entry_price < take_profit):
                return self._reject("INVALID_LEVEL_ORDER", f"Long levels violate stop ({stop_loss}) < entry ({entry_price}) < target ({take_profit})", telemetry)
        else:
            if not (take_profit < entry_price < stop_loss):
                return self._reject("INVALID_LEVEL_ORDER", f"Short levels violate target ({take_profit}) < entry ({entry_price}) < stop ({stop_loss})", telemetry)

        # 8. Sizing Calculation (0.25% equity risk, Delta contract multiplier 0.001)
        risk_budget = self.current_equity * self.risk_fraction
        loss_per_price_unit = abs(entry_price - stop_loss)
        loss_per_contract = loss_per_price_unit * self.contract_multiplier

        if loss_per_contract <= 0:
            return self._reject("ZERO_LOSS_PER_CONTRACT", "Stop loss equals entry price", telemetry)

        # Exact integer contract units: floor(risk_budget / loss_per_contract)
        qty_contracts = math.floor(risk_budget / loss_per_contract)

        # Reject if budget < 1 contract (never round up to avoid risk breach)
        if qty_contracts < 1:
            return self._reject(
                "BUDGET_BELOW_MIN_CONTRACT",
                f"Risk budget (${risk_budget:.2f}) is insufficient for 1 contract (${loss_per_contract:.2f} risk)",
                telemetry
            )

        # Cap by Max Notional ($2,500)
        notional_per_contract = entry_price * self.contract_multiplier
        max_contracts_by_notional = math.floor(self.max_notional_cap / notional_per_contract)
        if qty_contracts > max_contracts_by_notional:
            qty_contracts = max_contracts_by_notional

        if qty_contracts < 1:
            return self._reject(
                "NOTIONAL_CAP_EXCEEDED",
                f"Single contract notional (${notional_per_contract:.2f}) exceeds cap (${self.max_notional_cap:.2f})",
                telemetry
            )

        total_notional = qty_contracts * notional_per_contract
        qty_xaut = round(qty_contracts * self.contract_multiplier, 5)

        # 9. Realistic Transaction Cost & Net R:R Validation
        reward_per_price_unit = abs(take_profit - entry_price)
        gross_reward = reward_per_price_unit * self.contract_multiplier * qty_contracts
        gross_risk = loss_per_contract * qty_contracts

        # Estimated round-trip taker fees (0.05% each leg = 0.10% total)
        round_trip_fee = 2.0 * self.taker_fee_rate * total_notional
        # Estimated round-trip slippage (5 bps each leg = 10 bps total)
        round_trip_slippage = 2.0 * (self.slippage_bps / 10000.0) * total_notional

        net_reward = gross_reward - round_trip_fee - round_trip_slippage
        net_risk = gross_risk + round_trip_fee + round_trip_slippage

        if net_risk <= 0:
            return self._reject("ZERO_NET_RISK", "Net risk calculation returned zero", telemetry)

        net_rr = net_reward / net_risk
        if net_rr < self.min_reward_to_risk:
            return self._reject(
                "NET_RR_BELOW_THRESHOLD",
                f"Net R:R ({net_rr:.2f}) after fees (${round_trip_fee:.2f}) and slippage (${round_trip_slippage:.2f}) is below minimum {self.min_reward_to_risk:.1f}",
                telemetry
            )

        # All checks passed!
        telemetry["checks"]["all_passed"] = True
        return {
            "passed": True,
            "reason": "ORDER_RISK_APPROVED",
            "qty_contracts": int(qty_contracts),
            "qty_xaut": qty_xaut,
            "notional": round(total_notional, 2),
            "risk_budget": round(risk_budget, 4),
            "actual_dollar_risk": round(gross_risk, 4),
            "estimated_fees": round(round_trip_fee, 4),
            "estimated_slippage": round(round_trip_slippage, 4),
            "net_rr": round(net_rr, 2),
            "gross_rr": round(gross_reward / gross_risk, 2),
            "telemetry": telemetry
        }

    def _reject(self, code: str, message: str, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        telemetry["checks"]["failed_code"] = code
        telemetry["checks"]["failed_message"] = message
        return {
            "passed": False,
            "reason": code,
            "message": message,
            "qty_contracts": 0,
            "qty_xaut": 0.0,
            "notional": 0.0,
            "risk_budget": 0.0,
            "actual_dollar_risk": 0.0,
            "estimated_fees": 0.0,
            "estimated_slippage": 0.0,
            "net_rr": 0.0,
            "gross_rr": 0.0,
            "telemetry": telemetry
        }

    def get_status(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Return full observable risk status."""
        if now is None:
            now = time.time()
        self._check_rollovers(now)

        current_dd = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        daily_loss = self.day_start_equity - self.current_equity
        daily_loss_pct = (daily_loss / self.day_start_equity * 100.0) if self.day_start_equity > 0 else 0.0
        weekly_loss = self.week_start_equity - self.current_equity
        weekly_loss_pct = (weekly_loss / self.week_start_equity * 100.0) if self.week_start_equity > 0 else 0.0

        return {
            "current_equity": round(self.current_equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "day_start_equity": round(self.day_start_equity, 2),
            "week_start_equity": round(self.week_start_equity, 2),
            "max_drawdown_pct": round(current_dd * 100.0, 2),
            "max_drawdown_limit_pct": self.max_drawdown_fraction * 100.0,
            "daily_loss_pct": round(daily_loss_pct, 2),
            "daily_loss_limit_pct": self.daily_loss_fraction * 100.0,
            "weekly_loss_pct": round(weekly_loss_pct, 2),
            "weekly_loss_limit_pct": self.weekly_loss_fraction * 100.0,
            "circuit_breaker_tripped": self.circuit_breaker_tripped,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "max_notional_cap": self.max_notional_cap,
            "contract_multiplier": self.contract_multiplier,
            "discipline": self.discipline.get_status(now)
        }
