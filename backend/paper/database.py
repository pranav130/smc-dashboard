import os
import logging
from contextlib import contextmanager
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from backend.config import DATABASE_URL, INITIAL_PAPER_BALANCE, IST_TZ
from backend.paper.models import Base, AccountModel, PaperLogModel

logger = logging.getLogger("PaperDB")

# Configure database directory if SQLite
if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    # PostgreSQL configuration
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create all tables and guarantee initial paper trading account exists."""
    Base.metadata.create_all(bind=engine)
    with get_db() as db:
        account = db.query(AccountModel).filter(AccountModel.id == 1).first()
        if not account:
            account = AccountModel(
                id=1,
                balance=INITIAL_PAPER_BALANCE,
                initial_balance=INITIAL_PAPER_BALANCE,
                currency="USD"
            )
            db.add(account)
            db.commit()
            logger.info(f"Initialized persistent paper trading account with ${INITIAL_PAPER_BALANCE:,.2f} USD")

@contextmanager
def get_db():
    """Provide a transactional database session scope."""
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database transaction error: {e}")
        raise
    finally:
        db.close()

def log_event(level: str, category: str, message: str, details: str = ""):
    """Record a persistent system / trade log entry."""
    try:
        now_ts = int(datetime.now().timestamp())
        ist_str = datetime.now(tz=IST_TZ).strftime("%Y-%m-%d %H:%M:%S IST")
        with get_db() as db:
            log_entry = PaperLogModel(
                timestamp=now_ts,
                timestamp_ist=ist_str,
                level=level,
                category=category,
                message=message,
                details=details
            )
            db.add(log_entry)
            db.commit()
    except Exception as e:
        logger.warning(f"Could not persist log event: {e}")
