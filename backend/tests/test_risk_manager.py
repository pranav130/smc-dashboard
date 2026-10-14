import pytest
import time
from backend.risk.manager import RiskManager
from backend.risk.discipline import DisciplineManager


def test_contract_sizing_and_notional_cap():
    """Verify exact Delta Exchange contract sizing and $2,500 notional cap."""
    rm = RiskManager(starting_equity=10000.0)

    # Entry 4100.0, Stop 4090.0 (distance $10), Target 4150.0 (distance $50, Net R:R 2.3 after fees and slippage)
    res = rm.evaluate_order(
        direction="LONG",
        entry_price=4100.0,
        stop_loss=4090.0,
        take_profit=4150.0,
        open_positions_count=0,
        is_feed_safe=True
    )

    assert res["passed"] is True
    assert res["reason"] == "ORDER_RISK_APPROVED"
    # Notional per contract = 4100 * 0.001 = $4.10
    # $2500 cap / $4.10 = 609 contracts
    assert res["qty_contracts"] == 609
    assert res["notional"] <= 2500.0
    assert res["net_rr"] >= 2.0


def test_budget_below_min_contract_rejection():
    """Verify rejection when risk budget is less than 1 contract's loss (never round up)."""
    # Tiny equity $10.0 -> 0.25% budget = $0.025
    rm = RiskManager(starting_equity=10.0)
    # Stop distance $100 -> loss per contract = 100 * 0.001 = $0.10
    # Budget ($0.025) < Loss per contract ($0.10)
    res = rm.evaluate_order(
        direction="LONG",
        entry_price=4100.0,
        stop_loss=4000.0,
        take_profit=4400.0,
        open_positions_count=0,
        is_feed_safe=True
    )
    assert res["passed"] is False
    assert res["reason"] == "BUDGET_BELOW_MIN_CONTRACT"
    assert res["qty_contracts"] == 0


def test_net_rr_rejection():
    """Verify rejection when net R:R falls below 2.0 after simulated fees and slippage."""
    rm = RiskManager(starting_equity=10000.0)
    # Gross R:R is 2.05, but fees and slippage drag net R:R below 2.0
    res = rm.evaluate_order(
        direction="LONG",
        entry_price=4100.0,
        stop_loss=4090.0,
        take_profit=4120.2, # barely over 2.0 gross
        open_positions_count=0,
        is_feed_safe=True
    )
    assert res["passed"] is False
    assert res["reason"] == "NET_RR_BELOW_THRESHOLD"


def test_daily_loss_limit_circuit_breaker():
    """Verify 1.0% daily loss limit halts order evaluation."""
    rm = RiskManager(starting_equity=10000.0)
    # Day start equity is 10,000. 1% limit is $100 loss.
    # Simulate equity drop to $9,890 ($110 loss)
    rm.update_equity(9890.0)

    res = rm.evaluate_order(
        direction="LONG",
        entry_price=4100.0,
        stop_loss=4090.0,
        take_profit=4130.0,
        open_positions_count=0,
        is_feed_safe=True
    )
    assert res["passed"] is False
    assert res["reason"] == "DAILY_LOSS_LIMIT_REACHED"


def test_peak_to_trough_drawdown_circuit_breaker():
    """Verify 5.0% peak-to-trough drawdown trips circuit breaker."""
    rm = RiskManager(starting_equity=10000.0)
    # Run up to peak 11,000
    rm.update_equity(11000.0)
    assert rm.peak_equity == 11000.0

    # Drawdown of 5.5% from peak (11000 * 0.945 = 10,395)
    rm.update_equity(10395.0)
    assert rm.circuit_breaker_tripped is True

    res = rm.evaluate_order(
        direction="LONG",
        entry_price=4100.0,
        stop_loss=4090.0,
        take_profit=4130.0,
        open_positions_count=0,
        is_feed_safe=True
    )
    assert res["passed"] is False
    assert res["reason"] == "CIRCUIT_BREAKER_ACTIVE"

    # Reset circuit breaker
    rm.reset_circuit_breaker()
    assert rm.circuit_breaker_tripped is False


def test_discipline_cooldowns_and_quotas():
    """Verify anti-revenge 15m cooldown, 3-loss 4h cooldown, and 3-trade daily quota."""
    dm = DisciplineManager()
    now = 1000000.0

    # 1. Initially allowed
    allowed, reason, rem = dm.can_enter_trade(now)
    assert allowed is True

    # 2. Record 1 loss -> 15m cooldown
    dm.record_trade_result(-25.0, now)
    allowed, reason, rem = dm.can_enter_trade(now + 100)
    assert allowed is False
    assert "cooling off" in reason.lower()
    assert rem == 800

    # 3. Fast forward after 15m -> permitted again
    allowed, reason, rem = dm.can_enter_trade(now + 905)
    assert allowed is True

    # 4. Record 2 more consecutive losses (total 3 consecutive) -> 4-hour cooldown
    dm.record_trade_result(-25.0, now + 1000)
    dm.record_trade_result(-25.0, now + 2000)
    allowed, reason, rem = dm.can_enter_trade(now + 2100)
    assert allowed is False
    assert "consecutive loss limit" in reason.lower()
    assert rem > 10000  # 4 hours = 14400s

    # 5. Fast forward past 4 hours -> daily quota reached (3 trades completed)
    allowed, reason, rem = dm.can_enter_trade(now + 17000)
    assert allowed is False
    assert "daily trade limit reached" in reason.lower()
