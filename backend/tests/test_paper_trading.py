import pytest
from backend.config import EXECUTION_MODE, INITIAL_PAPER_BALANCE
from backend.paper.database import init_db, get_db
from backend.paper.models import AccountModel, PositionModel, TradeModel
from backend.paper.engine import PaperTradingEngine

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    # Clean tables before each test
    with get_db() as db:
        db.query(PositionModel).delete()
        db.query(TradeModel).delete()
        account = db.query(AccountModel).filter(AccountModel.id == 1).first()
        if account:
            account.balance = 10000.0
            account.initial_balance = 10000.0
            account.total_trades = 0
            account.winning_trades = 0
            account.losing_trades = 0
        else:
            db.add(AccountModel(id=1, balance=10000.0, initial_balance=10000.0))

def test_simulation_safety_lock():
    """Verify that execution mode is strictly PAPER and no live keys are required."""
    assert EXECUTION_MODE == "PAPER"

def test_database_initialization_and_account():
    """Verify that account initializes with configured balance."""
    with get_db() as db:
        account = db.query(AccountModel).filter(AccountModel.id == 1).first()
        assert account is not None
        assert account.balance == 10000.0
        assert account.currency == "USD"

def test_open_paper_order():
    """Verify opening a paper order successfully records position."""
    engine = PaperTradingEngine()
    res = engine.open_paper_order(
        symbol="XAUTUSD",
        direction="BUY",
        entry_price=2700.0,
        quantity=1.0,
        stop_loss=2680.0,
        take_profit=2740.0,
        strategy="SMC 1H FVG Test",
        signal_id="sig_test_001"
    )
    assert res["success"] is True
    assert res["position"]["direction"] == "BUY"
    assert res["position"]["entry_price"] == 2700.0

    # Verify stored in DB
    with get_db() as db:
        pos = db.query(PositionModel).filter(PositionModel.signal_id == "sig_test_001").first()
        assert pos is not None
        assert pos.quantity == 1.0
        assert pos.status == "OPEN"

def test_duplicate_trade_protection():
    """Verify that duplicate signals cannot open duplicate trades."""
    engine = PaperTradingEngine()
    # 1. First order
    res1 = engine.open_paper_order(
        symbol="XAUTUSD",
        direction="BUY",
        entry_price=2700.0,
        quantity=1.0,
        stop_loss=2680.0,
        take_profit=2740.0,
        strategy="SMC 1H FVG Test",
        signal_id="sig_duplicate_check"
    )
    assert res1["success"] is True

    # 2. Second order with identical signal_id must be rejected
    res2 = engine.open_paper_order(
        symbol="XAUTUSD",
        direction="BUY",
        entry_price=2705.0,
        quantity=1.0,
        stop_loss=2680.0,
        take_profit=2740.0,
        strategy="SMC 1H FVG Test",
        signal_id="sig_duplicate_check"
    )
    assert res2["success"] is False
    assert "already" in res2["message"].lower()

def test_position_take_profit_execution():
    """Verify that reaching Take Profit closes position, logs trade, and credits balance."""
    engine = PaperTradingEngine()
    engine.open_paper_order(
        symbol="XAUTUSD",
        direction="BUY",
        entry_price=2700.0,
        quantity=1.0,
        stop_loss=2680.0,
        take_profit=2740.0,
        strategy="SMC 1H FVG Test",
        signal_id="sig_tp_test"
    )

    # Tick at 2720 (in progress)
    engine.on_tick(2720.0)
    with get_db() as db:
        pos = db.query(PositionModel).filter(PositionModel.signal_id == "sig_tp_test").first()
        assert pos is not None
        assert pos.unrealized_pnl == 20.0

    # Tick at 2745 (hits TP)
    engine.on_tick(2745.0)
    with get_db() as db:
        # Position must be closed and removed from open positions
        pos = db.query(PositionModel).filter(PositionModel.signal_id == "sig_tp_test").first()
        assert pos is None

        # Trade must be recorded in historical trades
        trade = db.query(TradeModel).filter(TradeModel.signal_id == "sig_tp_test").first()
        assert trade is not None
        assert trade.exit_reason == "TAKE_PROFIT"
        assert trade.net_pnl > 0.0

        # Balance must increase
        account = db.query(AccountModel).filter(AccountModel.id == 1).first()
        assert account.balance > 10000.0
        assert account.winning_trades == 1

def test_position_stop_loss_execution():
    """Verify that reaching Stop Loss closes position, logs trade, and debits balance."""
    engine = PaperTradingEngine()
    engine.open_paper_order(
        symbol="XAUTUSD",
        direction="BUY",
        entry_price=2700.0,
        quantity=1.0,
        stop_loss=2680.0,
        take_profit=2740.0,
        strategy="SMC 1H FVG Test",
        signal_id="sig_sl_test"
    )

    # Tick at 2675 (hits SL)
    engine.on_tick(2675.0)
    with get_db() as db:
        pos = db.query(PositionModel).filter(PositionModel.signal_id == "sig_sl_test").first()
        assert pos is None

        trade = db.query(TradeModel).filter(TradeModel.signal_id == "sig_sl_test").first()
        assert trade is not None
        assert trade.exit_reason == "STOP_LOSS"
        assert trade.net_pnl < 0.0

        account = db.query(AccountModel).filter(AccountModel.id == 1).first()
        assert account.balance < 10000.0
        assert account.losing_trades == 1

def test_account_summary_metrics():
    """Verify summary metrics calculation."""
    engine = PaperTradingEngine()
    summary = engine.get_account_summary()
    assert summary["balance"] == 10000.0
    assert summary["equity"] == 10000.0
    assert summary["open_positions_count"] == 0
    assert summary["total_trades"] == 0
    assert summary["execution_mode"] == "PAPER"

@pytest.mark.asyncio
async def test_health_check_endpoint():
    """Verify that health check reports healthy state."""
    from backend.app import app
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["database"] == "connected"
        assert data["mode"] == "PAPER_TRADING"

@pytest.mark.asyncio
async def test_paper_api_endpoints():
    """Verify paper API endpoints return valid JSON responses."""
    from backend.app import app
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Summary
        resp = await client.get("/api/paper/summary")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 2. Open Positions
        resp = await client.get("/api/paper/positions")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 3. Trades
        resp = await client.get("/api/paper/trades")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 4. Logs
        resp = await client.get("/api/paper/logs")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

