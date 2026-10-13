import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from backend.config import (
    DEFAULT_SYMBOL,
    IST_TZ,
    INITIAL_PAPER_BALANCE,
    DEFAULT_RISK_PER_TRADE_PCT,
    AUTO_PAPER_TRADING_ENABLED,
    EXECUTION_MODE
)
from backend.paper.models import AccountModel, PositionModel, TradeModel
from backend.paper.database import get_db, log_event

logger = logging.getLogger("PaperEngine")

# Simulated exchange fee & slippage parameters (realistic execution model)
TAKER_FEE_PCT = 0.0005  # 0.05%
SLIPPAGE_PER_OZ = 0.05  # $0.05 per ounce simulated spread/slippage

class PaperTradingEngine:
    """
    24/7 Persistent Paper Trading & Risk Management Engine.
    Evaluates real-time price against active positions, enforces strict stop-loss/take-profit,
    and safeguards simulated account state against process restarts.
    """

    def __init__(self):
        self.is_monitoring = True
        self.last_price = 0.0
        self.last_evaluation_time = 0
        self.auto_trading_enabled = AUTO_PAPER_TRADING_ENABLED
        logger.info(f"Initialized PaperTradingEngine (Mode: {EXECUTION_MODE}, Auto: {self.auto_trading_enabled})")

    def format_ist(self, ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=IST_TZ).strftime("%Y-%m-%d %H:%M:%S IST")

    def get_account_summary(self) -> Dict[str, Any]:
        """Return real-time account summary with equity, margin, and win rate."""
        with get_db() as db:
            account = db.query(AccountModel).filter(AccountModel.id == 1).first()
            if not account:
                account = AccountModel(id=1, balance=INITIAL_PAPER_BALANCE, initial_balance=INITIAL_PAPER_BALANCE)
                db.add(account)
                db.commit()

            open_positions = db.query(PositionModel).filter(PositionModel.status == "OPEN").all()
            total_unrealized_pnl = sum(p.unrealized_pnl for p in open_positions)
            equity = account.balance + total_unrealized_pnl

            trades = db.query(TradeModel).all()
            win_count = sum(1 for t in trades if t.net_pnl > 0)
            loss_count = sum(1 for t in trades if t.net_pnl <= 0)
            total_realized_pnl = sum(t.net_pnl for t in trades)

            total_wins_val = sum(t.net_pnl for t in trades if t.net_pnl > 0)
            total_loss_val = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
            profit_factor = round(total_wins_val / total_loss_val, 2) if total_loss_val > 0 else (99.0 if total_wins_val > 0 else 0.0)

            return {
                "balance": round(account.balance, 2),
                "equity": round(equity, 2),
                "initial_balance": round(account.initial_balance, 2),
                "currency": account.currency,
                "open_positions_count": len(open_positions),
                "total_trades": len(trades),
                "winning_trades": win_count,
                "losing_trades": loss_count,
                "win_rate_pct": round((win_count / len(trades) * 100) if trades else 0.0, 1),
                "total_realized_pnl": round(total_realized_pnl, 2),
                "total_unrealized_pnl": round(total_unrealized_pnl, 2),
                "profit_factor": profit_factor,
                "auto_trading_enabled": self.auto_trading_enabled,
                "execution_mode": EXECUTION_MODE,
                "monitoring_active": self.is_monitoring,
                "last_evaluated_price": round(self.last_price, 2)
            }

    def get_open_positions(self) -> List[Dict[str, Any]]:
        with get_db() as db:
            positions = db.query(PositionModel).filter(PositionModel.status == "OPEN").all()
            return [p.to_dict() for p in positions]

    def get_trade_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with get_db() as db:
            trades = db.query(TradeModel).order_by(TradeModel.exit_time.desc()).limit(limit).all()
            return [t.to_dict() for t in trades]

    def on_tick(self, current_price: float, timestamp: Optional[int] = None):
        """
        Evaluate all active paper positions against incoming market price tick.
        Executed 24/7 on every market candle/tick update.
        """
        if current_price <= 0:
            return

        self.last_price = current_price
        now_ts = timestamp or int(time.time())
        self.last_evaluation_time = now_ts

        with get_db() as db:
            open_positions = db.query(PositionModel).filter(PositionModel.status == "OPEN").all()
            if not open_positions:
                return

            account = db.query(AccountModel).filter(AccountModel.id == 1).first()

            for pos in open_positions:
                pos.current_price = current_price

                # Calculate current P&L
                if pos.direction == "BUY":
                    raw_pnl = (current_price - pos.entry_price) * pos.quantity
                    pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
                else:  # SELL
                    raw_pnl = (pos.entry_price - current_price) * pos.quantity
                    pnl_pct = ((pos.entry_price - current_price) / pos.entry_price) * 100

                pos.unrealized_pnl = raw_pnl
                pos.unrealized_pnl_pct = pnl_pct

                # Check Stop-Loss & Take-Profit triggers
                should_close = False
                exit_reason = ""
                exit_price = current_price

                if pos.direction == "BUY":
                    if pos.stop_loss > 0 and current_price <= pos.stop_loss:
                        should_close = True
                        exit_reason = "STOP_LOSS"
                        exit_price = min(pos.stop_loss, current_price)
                    elif pos.take_profit > 0 and current_price >= pos.take_profit:
                        should_close = True
                        exit_reason = "TAKE_PROFIT"
                        exit_price = max(pos.take_profit, current_price)
                else:  # SELL
                    if pos.stop_loss > 0 and current_price >= pos.stop_loss:
                        should_close = True
                        exit_reason = "STOP_LOSS"
                        exit_price = max(pos.stop_loss, current_price)
                    elif pos.take_profit > 0 and current_price <= pos.take_profit:
                        should_close = True
                        exit_reason = "TAKE_PROFIT"
                        exit_price = min(pos.take_profit, current_price)

                if should_close:
                    self._close_position_internal(db, account, pos, exit_price, exit_reason, now_ts)

    def _close_position_internal(
        self,
        db,
        account: AccountModel,
        pos: PositionModel,
        exit_price: float,
        reason: str,
        exit_time: int
    ):
        """Execute transactional closing of paper position with fees and slippage."""
        # Calculate gross realized P&L
        if pos.direction == "BUY":
            gross_pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            gross_pnl = (pos.entry_price - exit_price) * pos.quantity

        gross_pnl_pct = (gross_pnl / (pos.entry_price * pos.quantity)) * 100 if pos.entry_price > 0 else 0.0

        # Calculate simulated fee (entry + exit) & slippage
        notional_entry = pos.entry_price * pos.quantity
        notional_exit = exit_price * pos.quantity
        fee = (notional_entry + notional_exit) * TAKER_FEE_PCT
        slippage = pos.quantity * SLIPPAGE_PER_OZ
        net_pnl = gross_pnl - fee - slippage

        # Update Account Balance
        account.balance += net_pnl
        account.total_trades += 1
        if net_pnl > 0:
            account.winning_trades += 1
        else:
            account.losing_trades += 1

        duration = max(0, exit_time - pos.entry_time)

        # Record Historical Trade
        trade = TradeModel(
            symbol=pos.symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            entry_time=pos.entry_time,
            entry_time_ist=pos.entry_time_ist,
            exit_time=exit_time,
            exit_time_ist=self.format_ist(exit_time),
            duration_seconds=duration,
            realized_pnl=gross_pnl,
            realized_pnl_pct=gross_pnl_pct,
            fee=fee,
            slippage=slippage,
            net_pnl=net_pnl,
            exit_reason=reason,
            signal_id=pos.signal_id,
            strategy=pos.strategy,
            status="CLOSED"
        )
        db.add(trade)
        db.delete(pos)

        log_msg = f"Closed Paper Position {pos.id} ({pos.direction} {pos.quantity}oz @ {exit_price}) via {reason}. Net P&L: ${net_pnl:+,.2f}"
        logger.info(log_msg)
        log_event("INFO", "POSITION", log_msg, f"Trade ID: {trade.id}, Exit: {exit_price}, Net: {net_pnl}")

    def open_paper_order(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        strategy: str,
        signal_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Open a simulated paper order with duplicate-trade protection.
        """
        direction = direction.upper()
        if direction not in ("BUY", "SELL"):
            raise ValueError("Direction must be BUY or SELL")

        now_ts = int(time.time())
        ist_str = self.format_ist(now_ts)

        with get_db() as db:
            # 1. Duplicate check: If signal_id already used in open or closed trades
            if signal_id:
                existing_pos = db.query(PositionModel).filter(PositionModel.signal_id == signal_id).first()
                if existing_pos:
                    logger.warning(f"Duplicate protection: Open position already exists for signal {signal_id}")
                    return {"success": False, "message": f"Position already open for signal {signal_id}"}

                existing_trd = db.query(TradeModel).filter(TradeModel.signal_id == signal_id).first()
                if existing_trd:
                    logger.warning(f"Duplicate protection: Historical trade already exists for signal {signal_id}")
                    return {"success": False, "message": f"Trade already executed for signal {signal_id}"}

            account = db.query(AccountModel).filter(AccountModel.id == 1).first()
            if not account:
                account = AccountModel(id=1, balance=INITIAL_PAPER_BALANCE, initial_balance=INITIAL_PAPER_BALANCE)
                db.add(account)
                db.commit()

            # Ensure reasonable quantity (minimum 0.01 oz, default based on risk)
            if quantity <= 0:
                quantity = self.calculate_position_size(account.balance, entry_price, stop_loss)

            pos = PositionModel(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                quantity=quantity,
                stop_loss=stop_loss,
                take_profit=take_profit,
                entry_time=now_ts,
                entry_time_ist=ist_str,
                signal_id=signal_id,
                strategy=strategy,
                current_price=entry_price,
                unrealized_pnl=0.0,
                unrealized_pnl_pct=0.0,
                status="OPEN"
            )
            db.add(pos)

            log_msg = f"Opened Paper Position ({direction} {quantity}oz @ {entry_price} USD | SL: {stop_loss} | TP: {take_profit}) Strategy: {strategy}"
            logger.info(log_msg)
            log_event("INFO", "POSITION", log_msg, f"Signal: {signal_id}")

            return {
                "success": True,
                "message": "Paper order opened successfully",
                "position": pos.to_dict()
            }

    def close_position_manually(self, position_id: str) -> Dict[str, Any]:
        """Manually close an open paper position at current market price."""
        now_ts = int(time.time())
        with get_db() as db:
            pos = db.query(PositionModel).filter(PositionModel.id == position_id).first()
            if not pos:
                return {"success": False, "message": f"Position {position_id} not found"}

            account = db.query(AccountModel).filter(AccountModel.id == 1).first()
            exit_price = self.last_price if self.last_price > 0 else pos.entry_price
            self._close_position_internal(db, account, pos, exit_price, "MANUAL_CLOSE", now_ts)
            return {"success": True, "message": f"Position {position_id} closed manually at {exit_price}"}

    def calculate_position_size(self, balance: float, entry_price: float, stop_loss: float) -> float:
        """Calculate position size based on account risk percentage (default: 1%)."""
        risk_amount = balance * (DEFAULT_RISK_PER_TRADE_PCT / 100.0)
        risk_per_unit = abs(entry_price - stop_loss) if (stop_loss > 0 and entry_price != stop_loss) else (entry_price * 0.005)
        if risk_per_unit <= 0:
            return 0.1
        qty = risk_amount / risk_per_unit
        # Clamp between 0.01 and 10.0 ounces
        return round(max(0.01, min(qty, 10.0)), 4)

    def evaluate_signals_for_paper_trading(self, analysis: Dict[str, Any], current_price: float):
        """
        Continuous market evaluation loop: Translates verified SMC transitions
        (e.g., CHECKLIST REVIEW or SETUP TO INSPECT) into paper trades when auto-trading is enabled.
        """
        if not self.auto_trading_enabled or current_price <= 0:
            return

        active_alerts = analysis.get("active_alerts", [])
        watchlist = analysis.get("watchlist", [])

        for entry in watchlist:
            state = entry.get("state")
            if state in ("CHECKLIST REVIEW", "SETUP TO INSPECT"):
                level_name = entry.get("level_name", "")
                level_type = entry.get("level_type", "").upper()
                timeframe = entry.get("timeframe", "1H")
                key_level = entry.get("key_level", current_price)

                # Determine direction:
                # If level is Bullish FVG or Support / Bullish OB -> BUY
                # If level is Bearish FVG or Resistance / Bearish OB -> SELL
                direction = "BUY" if ("BULLISH" in level_name.upper() or "SUPPORT" in level_type or "DISCOUNT" in level_type) else "SELL"

                # Define stop-loss and take-profit
                # For gold, 0.5% - 1.0% ATR or zone boundary
                if direction == "BUY":
                    sl = round(key_level * 0.995, 2)
                    tp = round(current_price + (current_price - sl) * 2.0, 2)  # 1:2 R:R
                else:
                    sl = round(key_level * 1.005, 2)
                    tp = round(current_price - (sl - current_price) * 2.0, 2)

                # Unique signal ID incorporating date, timeframe, level to prevent duplicates
                date_str = datetime.now(tz=IST_TZ).strftime("%Y%m%d_%H")
                signal_id = f"smc_{entry.get('level_id')}_{timeframe}_{direction}_{date_str}"
                strategy = f"SMC {timeframe} {level_name} ({state})"

                self.open_paper_order(
                    symbol=DEFAULT_SYMBOL,
                    direction=direction,
                    entry_price=current_price,
                    quantity=0.0,  # Auto-calculate from risk
                    stop_loss=sl,
                    take_profit=tp,
                    strategy=strategy,
                    signal_id=signal_id
                )

    def reset_account(self, new_balance: float = INITIAL_PAPER_BALANCE) -> Dict[str, Any]:
        """Reset paper trading account balance and clear active positions."""
        with get_db() as db:
            account = db.query(AccountModel).filter(AccountModel.id == 1).first()
            if account:
                account.balance = new_balance
                account.initial_balance = new_balance
                account.total_trades = 0
                account.winning_trades = 0
                account.losing_trades = 0

            # Delete open positions
            db.query(PositionModel).delete()
            log_event("WARNING", "ACCOUNT", f"Account reset to ${new_balance:,.2f} USD")
            return {"success": True, "message": f"Account reset to ${new_balance:,.2f}"}

    def set_auto_trading(self, enabled: bool) -> Dict[str, Any]:
        self.auto_trading_enabled = enabled
        log_event("INFO", "SYSTEM", f"Auto Paper Trading set to {enabled}")
        return {"success": True, "auto_trading_enabled": enabled}
