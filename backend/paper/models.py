import uuid
import time
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, Index
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class AccountModel(Base):
    __tablename__ = "paper_accounts"

    id = Column(Integer, primary_key=True, default=1)
    balance = Column(Float, nullable=False, default=10000.0)
    initial_balance = Column(Float, nullable=False, default=10000.0)
    currency = Column(String(10), nullable=False, default="USD")
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "balance": round(self.balance, 2),
            "initial_balance": round(self.initial_balance, 2),
            "currency": self.currency,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_pct": round((self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0, 1)
        }


class PositionModel(Base):
    __tablename__ = "paper_positions"

    id = Column(String(64), primary_key=True, default=lambda: f"pos_{uuid.uuid4().hex[:12]}")
    symbol = Column(String(32), nullable=False, index=True)
    direction = Column(String(8), nullable=False)  # BUY or SELL
    entry_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)        # in ounces / contracts
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    entry_time = Column(Integer, nullable=False)
    entry_time_ist = Column(String(32), nullable=False)
    signal_id = Column(String(128), nullable=True, unique=True, index=True)  # Deduplication lock
    strategy = Column(String(128), nullable=False)
    current_price = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0)
    unrealized_pnl_pct = Column(Float, default=0.0)
    status = Column(String(16), default="OPEN", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": round(self.entry_price, 2),
            "quantity": round(self.quantity, 4),
            "stop_loss": round(self.stop_loss, 2),
            "take_profit": round(self.take_profit, 2),
            "entry_time": self.entry_time,
            "entry_time_ist": self.entry_time_ist,
            "signal_id": self.signal_id,
            "strategy": self.strategy,
            "current_price": round(self.current_price, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "status": self.status
        }


class TradeModel(Base):
    __tablename__ = "paper_trades"

    id = Column(String(64), primary_key=True, default=lambda: f"trd_{uuid.uuid4().hex[:12]}")
    symbol = Column(String(32), nullable=False, index=True)
    direction = Column(String(8), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    entry_time = Column(Integer, nullable=False)
    entry_time_ist = Column(String(32), nullable=False)
    exit_time = Column(Integer, nullable=False)
    exit_time_ist = Column(String(32), nullable=False)
    duration_seconds = Column(Integer, default=0)
    realized_pnl = Column(Float, nullable=False)
    realized_pnl_pct = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    slippage = Column(Float, default=0.0)
    net_pnl = Column(Float, nullable=False)
    exit_reason = Column(String(32), nullable=False)  # TAKE_PROFIT, STOP_LOSS, MANUAL_CLOSE, INVALIDATION
    signal_id = Column(String(128), nullable=True, index=True)
    strategy = Column(String(128), nullable=False)
    status = Column(String(16), default="CLOSED")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": round(self.entry_price, 2),
            "exit_price": round(self.exit_price, 2),
            "quantity": round(self.quantity, 4),
            "stop_loss": round(self.stop_loss, 2),
            "take_profit": round(self.take_profit, 2),
            "entry_time": self.entry_time,
            "entry_time_ist": self.entry_time_ist,
            "exit_time": self.exit_time,
            "exit_time_ist": self.exit_time_ist,
            "duration_seconds": self.duration_seconds,
            "realized_pnl": round(self.realized_pnl, 2),
            "realized_pnl_pct": round(self.realized_pnl_pct, 2),
            "fee": round(self.fee, 2),
            "slippage": round(self.slippage, 2),
            "net_pnl": round(self.net_pnl, 2),
            "exit_reason": self.exit_reason,
            "signal_id": self.signal_id,
            "strategy": self.strategy,
            "status": self.status
        }


class PaperLogModel(Base):
    __tablename__ = "paper_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Integer, nullable=False, index=True)
    timestamp_ist = Column(String(32), nullable=False)
    level = Column(String(16), default="INFO")
    category = Column(String(32), default="SYSTEM")
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "timestamp_ist": self.timestamp_ist,
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "details": self.details
        }
