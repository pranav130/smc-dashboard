"""
Psychological Discipline & Emotional Cooldown Engine.
Enforces behavioral safeguards required by Section 9:
1. Anti-revenge cooling off (15 min after any loss).
2. 3-consecutive-loss circuit breaker (4-hour cooldown).
3. Daily trade quota limit (max 3 trades per 24h UTC session).
4. Full audit observability for cooldown timers.
"""
import time
from typing import Dict, Any, Tuple, Optional


class DisciplineManager:
    """Authoritative tracker of trader discipline rules and cooldowns."""

    def __init__(
        self,
        single_loss_cooldown_seconds: int = 900,       # 15 minutes
        consecutive_loss_threshold: int = 3,
        consecutive_loss_cooldown_seconds: int = 14400, # 4 hours
        max_daily_trades: int = 3
    ):
        self.single_loss_cooldown_seconds = single_loss_cooldown_seconds
        self.consecutive_loss_threshold = consecutive_loss_threshold
        self.consecutive_loss_cooldown_seconds = consecutive_loss_cooldown_seconds
        self.max_daily_trades = max_daily_trades

        self.consecutive_losses: int = 0
        self.trades_today_count: int = 0
        self.current_utc_day: str = time.strftime("%Y-%m-%d", time.gmtime())
        self.cooldown_until: float = 0.0
        self.cooldown_reason: Optional[str] = None

    def _check_rollover(self, now: float):
        day_str = time.strftime("%Y-%m-%d", time.gmtime(now))
        if day_str != self.current_utc_day:
            self.current_utc_day = day_str
            self.trades_today_count = 0

    def can_enter_trade(self, now: Optional[float] = None) -> Tuple[bool, str, int]:
        """
        Check whether psychological discipline rules permit a new trade entry.
        Returns:
            (is_permitted, rejection_reason, remaining_cooldown_seconds)
        """
        if now is None:
            now = time.time()
        self._check_rollover(now)

        # Check active cooldown timer
        if now < self.cooldown_until:
            rem = int(self.cooldown_until - now)
            reason = self.cooldown_reason or f"Active cooldown ({rem}s remaining)"
            return False, reason, rem

        # Check daily trade quota
        if self.trades_today_count >= self.max_daily_trades:
            return False, f"Daily trade limit reached ({self.trades_today_count}/{self.max_daily_trades} trades)", 0

        return True, "DISCIPLINE_PERMITTED", 0

    def record_trade_result(self, net_pnl: float, now: Optional[float] = None):
        """Record trade completion and update discipline state."""
        if now is None:
            now = time.time()
        self._check_rollover(now)

        self.trades_today_count += 1

        if net_pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.consecutive_loss_threshold:
                self.cooldown_until = now + self.consecutive_loss_cooldown_seconds
                self.cooldown_reason = (
                    f"Consecutive loss limit reached ({self.consecutive_losses} losses). "
                    f"Cooling off for {self.consecutive_loss_cooldown_seconds // 3600} hours."
                )
            else:
                self.cooldown_until = now + self.single_loss_cooldown_seconds
                self.cooldown_reason = (
                    f"Post-loss cooling off ({self.single_loss_cooldown_seconds // 60}m) to prevent revenge trading."
                )
        else:
            # Winning or break-even trade resets consecutive loss counter
            self.consecutive_losses = 0

    def get_status(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Return observable status dictionary for API and UI."""
        if now is None:
            now = time.time()
        self._check_rollover(now)

        remaining = max(0, int(self.cooldown_until - now)) if now < self.cooldown_until else 0
        in_cooldown = remaining > 0

        return {
            "in_cooldown": in_cooldown,
            "cooldown_remaining_seconds": remaining,
            "cooldown_reason": self.cooldown_reason if in_cooldown else None,
            "consecutive_losses": self.consecutive_losses,
            "consecutive_loss_threshold": self.consecutive_loss_threshold,
            "trades_today": self.trades_today_count,
            "max_daily_trades": self.max_daily_trades,
            "daily_quota_exhausted": self.trades_today_count >= self.max_daily_trades,
            "utc_day": self.current_utc_day
        }
