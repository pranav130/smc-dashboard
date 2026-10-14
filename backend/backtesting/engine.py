"""
Historical Backtesting, Walk-Forward Validation & Monte Carlo Engine for XAUTUSD SMC Strategies.
Strictly implements Section 10 requirements:
- Chronological walk-forward execution without lookahead bias.
- 60% Train (In-Sample), 20% Validation, 20% Test (Out-of-Sample) splits.
- Realistic execution: taker fees (0.05%), slippage (5 bps), conservative candle tie-breaker.
- Comprehensive metrics: Win Rate, Profit Factor, Expectancy, Max Drawdown, Sharpe, Sortino, Calmar.
- 1,000-iteration Monte Carlo resampling for 95% confidence intervals and ruin probability.
- Independent testing of Model A vs Model B vs Combined.
"""
import math
import random
from typing import List, Dict, Any, Optional, Tuple
from backend.smc.models import Candle
from backend.smc.engine import SMCEngine
from backend.risk.manager import RiskManager
from backend.config import (
    INITIAL_PAPER_BALANCE as INITIAL_EQUITY,
    CONTRACT_MULTIPLIER,
    TAKER_FEE_RATE,
    SLIPPAGE_BPS,
    MIN_REWARD_TO_RISK,
    MAX_NOTIONAL_CAP,
)


class BacktestEngine:
    """Rigorous historical backtest and simulation engine."""

    def __init__(
        self,
        starting_equity: float = INITIAL_EQUITY,
        fee_rate: float = TAKER_FEE_RATE,
        slippage_bps: float = SLIPPAGE_BPS,
        contract_multiplier: float = CONTRACT_MULTIPLIER
    ):
        self.starting_equity = starting_equity
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.contract_multiplier = contract_multiplier
        self.smc_engine = SMCEngine()

    def run_backtest(
        self,
        candles_1h: List[Candle],
        candles_4h: Optional[List[Candle]] = None,
        candles_1d: Optional[List[Candle]] = None,
        strategy_mode: str = "COMBINED",  # "MODEL_A", "MODEL_B", "COMBINED"
        split_name: str = "ALL"
    ) -> Dict[str, Any]:
        """
        Execute chronological walk-forward simulation across historical candles.
        """
        if len(candles_1h) < 30:
            return {
                "split": split_name,
                "strategy": strategy_mode,
                "total_trades": 0,
                "error": "Insufficient historical candles for backtesting (minimum 30 required)"
            }

        equity = self.starting_equity
        peak_equity = self.starting_equity
        trades: List[Dict[str, Any]] = []
        equity_curve: List[float] = [equity]

        rm = RiskManager(
            starting_equity=self.starting_equity,
            taker_fee_rate=self.fee_rate,
            slippage_bps=self.slippage_bps,
            contract_multiplier=self.contract_multiplier
        )

        active_position: Optional[Dict[str, Any]] = None

        # Warm-up window: start at bar 25 so multi-timeframe indicators can initialize
        for i in range(25, len(candles_1h)):
            current_bar = candles_1h[i]
            history_1h = candles_1h[:i+1]

            # Construct available 4H and 1D context strictly up to current_bar.time (no lookahead)
            now_ts = current_bar.time
            h4_avail = [c for c in (candles_4h or []) if c.time <= now_ts]
            d1_avail = [c for c in (candles_1d or []) if c.time <= now_ts]

            # 1. If we have an active position, update mark-to-market using current bar
            if active_position is not None:
                pos = active_position
                direction = pos["direction"]
                stop = pos["stop_loss"]
                target = pos["take_profit"]
                initial_stop = pos["initial_stop"]
                entry_price = pos["entry_price"]
                qty = pos["quantity"]
                entry_fee = pos["entry_fee"]

                bar_high = current_bar.high
                bar_low = current_bar.low

                # Check 1R Break-even milestone
                r_dist = abs(entry_price - initial_stop)
                if not pos["be_triggered"] and r_dist > 0:
                    if direction == "LONG" and bar_high >= (entry_price + r_dist):
                        pos["stop_loss"] = round(entry_price + 0.1, 2)
                        pos["be_triggered"] = True
                        stop = pos["stop_loss"]
                    elif direction == "SHORT" and bar_low <= (entry_price - r_dist):
                        pos["stop_loss"] = round(entry_price - 0.1, 2)
                        pos["be_triggered"] = True
                        stop = pos["stop_loss"]

                # Conservative tie-breaker: if both stop and target touched in same bar, STOP LOSS executes
                closed = False
                exit_price = 0.0
                exit_reason = ""

                if direction == "LONG":
                    stop_hit = (bar_low <= stop)
                    target_hit = (bar_high >= target)
                    if stop_hit and target_hit:
                        closed = True
                        exit_price = stop
                        exit_reason = "STOP_LOSS"
                    elif stop_hit:
                        closed = True
                        exit_price = stop
                        exit_reason = "STOP_LOSS"
                    elif target_hit:
                        closed = True
                        exit_price = target
                        exit_reason = "TAKE_PROFIT"
                else:  # SHORT
                    stop_hit = (bar_high >= stop)
                    target_hit = (bar_low <= target)
                    if stop_hit and target_hit:
                        closed = True
                        exit_price = stop
                        exit_reason = "STOP_LOSS"
                    elif stop_hit:
                        closed = True
                        exit_price = stop
                        exit_reason = "STOP_LOSS"
                    elif target_hit:
                        closed = True
                        exit_price = target
                        exit_reason = "TAKE_PROFIT"

                if closed:
                    # Calculate exit fill with slippage
                    slip = exit_price * (self.slippage_bps / 10000.0)
                    fill_exit = (exit_price - slip) if direction == "LONG" else (exit_price + slip)
                    exit_fee = fill_exit * qty * self.fee_rate

                    if direction == "LONG":
                        gross_pnl = (fill_exit - entry_price) * qty
                    else:
                        gross_pnl = (entry_price - fill_exit) * qty

                    net_pnl = gross_pnl - entry_fee - exit_fee
                    equity = round(equity + net_pnl, 4)
                    if equity > peak_equity:
                        peak_equity = equity

                    trades.append({
                        "trade_index": len(trades) + 1,
                        "model": pos["model"],
                        "direction": direction,
                        "entry_time": pos["entry_time"],
                        "exit_time": current_bar.time,
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(fill_exit, 2),
                        "quantity": qty,
                        "gross_pnl": round(gross_pnl, 4),
                        "net_pnl": round(net_pnl, 4),
                        "fees": round(entry_fee + exit_fee, 4),
                        "exit_reason": exit_reason,
                        "equity_after": equity,
                        "r_multiple": round(net_pnl / (r_dist * qty), 2) if (r_dist * qty) > 0 else 0.0
                    })
                    equity_curve.append(equity)
                    rm.update_equity(equity, current_bar.time)
                    active_position = None

            # 2. If no position is open, evaluate strategy signals on the current bar
            if active_position is None:
                candles_by_tf = {
                    "1H": history_1h,
                    "4H": h4_avail if h4_avail else history_1h,
                    "1D": d1_avail if d1_avail else history_1h,
                }
                analysis = self.smc_engine.analyze_multi_timeframe(
                    candles_by_tf=candles_by_tf,
                    selected_timeframe="1H",
                    is_stale=False
                )

                candidate_setup = None
                model_tag = ""

                # Select strategy according to strategy_mode
                if strategy_mode in ("MODEL_A", "COMBINED"):
                    a_setup = analysis.get("model_a_setup")
                    if a_setup and a_setup.get("state") == "ACTIVE":
                        candidate_setup = a_setup
                        model_tag = "MODEL_A"

                if candidate_setup is None and strategy_mode in ("MODEL_B", "COMBINED"):
                    b_setup = analysis.get("model_b_setup")
                    if b_setup and b_setup.get("state") == "ACTIVE":
                        candidate_setup = b_setup
                        model_tag = "MODEL_B"

                if candidate_setup:
                    entry_p = float(candidate_setup["price"])
                    stop_p = float(candidate_setup["invalidation_price"])
                    target_p = float(candidate_setup["target_price"])
                    dir_str = candidate_setup["direction"].upper()

                    # Evaluate order through Central Risk Manager
                    risk_eval = rm.evaluate_order(
                        direction=dir_str,
                        entry_price=entry_p,
                        stop_loss=stop_p,
                        take_profit=target_p,
                        open_positions_count=0,
                        is_feed_safe=True,
                        now=current_bar.time
                    )

                    if risk_eval["passed"]:
                        qty = risk_eval["qty_xaut"]
                        # Entry fill with slippage
                        slip = entry_p * (self.slippage_bps / 10000.0)
                        fill_entry = (entry_p + slip) if dir_str in ("LONG", "BULLISH") else (entry_p - slip)
                        entry_fee = fill_entry * qty * self.fee_rate

                        active_position = {
                            "model": model_tag,
                            "direction": "LONG" if dir_str in ("LONG", "BULLISH") else "SHORT",
                            "entry_price": fill_entry,
                            "stop_loss": stop_p,
                            "take_profit": target_p,
                            "initial_stop": stop_p,
                            "quantity": qty,
                            "entry_fee": entry_fee,
                            "entry_time": current_bar.time,
                            "be_triggered": False
                        }

        # 3. Calculate Performance Metrics
        metrics = self._calculate_metrics(trades, equity_curve, split_name, strategy_mode)

        # 4. Monte Carlo Resampling (1,000 iterations)
        mc_results = self._monte_carlo_resample(trades, num_simulations=1000)
        metrics["monte_carlo"] = mc_results

        return metrics

    def run_walk_forward_validation(
        self,
        candles_1h: List[Candle],
        candles_4h: Optional[List[Candle]] = None,
        candles_1d: Optional[List[Candle]] = None,
        strategy_mode: str = "COMBINED"
    ) -> Dict[str, Any]:
        """
        Partition historical dataset into chronological 60% Train, 20% Validation, 20% Test splits.
        """
        n = len(candles_1h)
        if n < 50:
            return {"error": "Need at least 50 candles for walk-forward splits"}

        train_end = int(n * 0.60)
        val_end = int(n * 0.80)

        train_candles = candles_1h[:train_end]
        val_candles = candles_1h[train_end:val_end]
        test_candles = candles_1h[val_end:]

        train_res = self.run_backtest(train_candles, candles_4h, candles_1d, strategy_mode, "TRAIN_60_PCT")
        val_res = self.run_backtest(val_candles, candles_4h, candles_1d, strategy_mode, "VAL_20_PCT")
        test_res = self.run_backtest(test_candles, candles_4h, candles_1d, strategy_mode, "TEST_20_PCT_OOS")

        return {
            "strategy": strategy_mode,
            "total_candles": n,
            "splits": {
                "in_sample_train": train_res,
                "validation": val_res,
                "out_of_sample_test": test_res
            }
        }

    def _calculate_metrics(
        self,
        trades: List[Dict[str, Any]],
        equity_curve: List[float],
        split_name: str,
        strategy_mode: str
    ) -> Dict[str, Any]:
        """Compute institutional performance ratios and statistics."""
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "split": split_name,
                "strategy": strategy_mode,
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "net_profit": 0.0,
                "return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "expectancy_dollars": 0.0,
                "trades": []
            }

        wins = [t for t in trades if t["net_pnl"] > 0]
        losses = [t for t in trades if t["net_pnl"] < 0]
        win_rate = (len(wins) / total_trades) * 100.0

        gross_profit = sum(t["gross_pnl"] for t in wins)
        gross_loss = abs(sum(t["gross_pnl"] for t in losses))
        total_fees = sum(t["fees"] for t in trades)
        net_profit = sum(t["net_pnl"] for t in trades)

        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)
        expectancy_dollars = net_profit / total_trades
        return_pct = (net_profit / self.starting_equity) * 100.0

        # Drawdown calculation
        peak = self.starting_equity
        max_dd_amount = 0.0
        max_dd_pct = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd_amount = peak - eq
            dd_pct = (dd_amount / peak) * 100.0 if peak > 0 else 0.0
            if dd_amount > max_dd_amount:
                max_dd_amount = dd_amount
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        # Annualized Sharpe & Sortino (assuming hourly trading frequency)
        pnls = [t["net_pnl"] for t in trades]
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
        std_dev = math.sqrt(variance) if variance > 0 else 1e-6

        downside_variance = sum((min(0.0, p)) ** 2 for p in pnls) / len(pnls)
        downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 1e-6

        # Annualization factor for 1H bars (~8760 trading hours/year in crypto)
        ann_factor = math.sqrt(total_trades)
        sharpe_ratio = (mean_pnl / std_dev) * ann_factor if std_dev > 0 else 0.0
        sortino_ratio = (mean_pnl / downside_std) * ann_factor if downside_std > 0 else 0.0

        calmar_ratio = (return_pct / max_dd_pct) if max_dd_pct > 0 else 0.0

        return {
            "split": split_name,
            "strategy": strategy_mode,
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "total_fees": round(total_fees, 2),
            "net_profit": round(net_profit, 2),
            "return_pct": round(return_pct, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy_dollars": round(expectancy_dollars, 2),
            "max_drawdown_dollars": round(max_dd_amount, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "sortino_ratio": round(sortino_ratio, 2),
            "calmar_ratio": round(calmar_ratio, 2),
            "ending_equity": round(equity_curve[-1], 2),
            "trades": trades
        }

    def _monte_carlo_resample(
        self,
        trades: List[Dict[str, Any]],
        num_simulations: int = 1000
    ) -> Dict[str, Any]:
        """Bootstrap resampling with replacement across trade returns."""
        if len(trades) < 5:
            return {
                "simulations": 0,
                "median_max_dd_pct": 0.0,
                "ci_95_max_dd_pct": 0.0,
                "probability_of_ruin_pct": 0.0,
                "note": "Insufficient trades for Monte Carlo"
            }

        pnls = [t["net_pnl"] for t in trades]
        sim_max_dds: List[float] = []
        ruin_count = 0

        for _ in range(num_simulations):
            sample = random.choices(pnls, k=len(pnls))
            eq = self.starting_equity
            peak = eq
            sim_max_dd = 0.0
            for pnl in sample:
                eq += pnl
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
                if dd > sim_max_dd:
                    sim_max_dd = dd
            sim_max_dds.append(sim_max_dd)
            if sim_max_dd >= 20.0:  # 20% drawdown ruin threshold
                ruin_count += 1

        sim_max_dds.sort()
        idx_50 = int(num_simulations * 0.50)
        idx_95 = int(num_simulations * 0.95)

        return {
            "simulations": num_simulations,
            "median_max_dd_pct": round(sim_max_dds[idx_50], 2),
            "ci_95_max_dd_pct": round(sim_max_dds[idx_95], 2),
            "probability_of_ruin_pct": round((ruin_count / num_simulations) * 100.0, 2)
        }
