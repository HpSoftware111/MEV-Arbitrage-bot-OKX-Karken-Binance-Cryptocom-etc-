"""
Database configuration and models for MEV Bot
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mev_bot.db")

# Create engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Exchange(Base):
    """Exchange configuration table"""
    __tablename__ = "exchanges"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, index=True)
    api_key = Column(String(255), nullable=True)
    api_secret = Column(String(255), nullable=True)
    passphrase = Column(String(255), nullable=True)  # For OKX
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class PriceData(Base):
    """Real-time price data table"""
    __tablename__ = "price_data"
    
    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(50), index=True)
    symbol = Column(String(20), index=True)
    bid_price = Column(Float)
    ask_price = Column(Float)
    last_price = Column(Float)
    volume = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

class BalanceData(Base):
    """Balance data table"""
    __tablename__ = "balance_data"
    
    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(50), index=True)
    currency = Column(String(10), index=True)
    free_balance = Column(Float)
    used_balance = Column(Float)
    total_balance = Column(Float)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

class ArbitrageOpportunity(Base):
    """Arbitrage opportunities table"""
    __tablename__ = "arbitrage_opportunities"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True)
    buy_exchange = Column(String(50))
    sell_exchange = Column(String(50))
    buy_price = Column(Float)
    sell_price = Column(Float)
    gross_profit = Column(Float, nullable=True)
    buy_fee = Column(Float, nullable=True)
    sell_fee = Column(Float, nullable=True)
    total_fees = Column(Float, nullable=True)
    buy_slippage = Column(Float, nullable=True)
    sell_slippage = Column(Float, nullable=True)
    total_slippage = Column(Float, nullable=True)
    transfer_cost = Column(Float, nullable=True, default=0)
    transfer_time_minutes = Column(Integer, nullable=True, default=0)
    profit_amount = Column(Float)
    profit_percentage = Column(Float)
    available_volume = Column(Float, nullable=True)
    min_trade_size = Column(Float, nullable=True)
    max_trade_size = Column(Float, nullable=True)
    small_trade_profit = Column(Float, nullable=True)
    large_trade_profit = Column(Float, nullable=True)
    risk_score = Column(Float, nullable=True)
    price_spread_percentage = Column(Float, nullable=True)
    volume = Column(Float)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    is_executed = Column(Boolean, default=False)
    direction = Column(String(50), nullable=True)

class TradeExecution(Base):
    """Trade execution records table"""
    __tablename__ = "trade_executions"
    
    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(String(100), unique=True, index=True)
    symbol = Column(String(20), index=True)
    buy_exchange = Column(String(50))
    sell_exchange = Column(String(50))
    buy_order_id = Column(String(100), nullable=True)
    sell_order_id = Column(String(100), nullable=True)
    trade_amount = Column(Float)
    buy_price = Column(Float)
    sell_price = Column(Float)
    total_fees = Column(Float)
    net_profit = Column(Float)
    execution_time = Column(Float)  # seconds
    status = Column(String(20), default="pending")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    error_message = Column(Text, nullable=True)

class Position(Base):
    """Position tracking table"""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True)
    exchange = Column(String(50), index=True)
    side = Column(String(10))  # 'long' or 'short'
    amount = Column(Float)
    entry_price = Column(Float)
    current_price = Column(Float)
    unrealized_pnl = Column(Float, default=0)
    realized_pnl = Column(Float, default=0)
    status = Column(String(20), default="open")  # 'open', 'closed', 'partial'
    opened_at = Column(DateTime, default=datetime.utcnow, index=True)
    closed_at = Column(DateTime, nullable=True)
    trade_id = Column(String(100), nullable=True)

class PortfolioSnapshot(Base):
    """Portfolio snapshot table"""
    __tablename__ = "portfolio_snapshots"
    
    id = Column(Integer, primary_key=True, index=True)
    total_value_usdt = Column(Float)
    portfolio_data = Column(Text)  # JSON data
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

class BotStatus(Base):
    """Bot status and configuration table"""
    __tablename__ = "bot_status"
    
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(20), default="stopped")  # running, stopped, error
    last_update = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)
    config = Column(Text, nullable=True)  # JSON config

class RiskEvent(Base):
    """Risk events and alerts table"""
    __tablename__ = "risk_events"
    
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50), index=True)
    details = Column(Text)
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

class StopLossOrder(Base):
    """Stop-loss orders table"""
    __tablename__ = "stop_loss_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(Integer, ForeignKey("positions.id"))
    stop_price = Column(Float)
    trailing_stop = Column(Boolean, default=False)
    trailing_percentage = Column(Float, nullable=True)
    time_based = Column(Boolean, default=False)
    max_hold_time = Column(Integer, nullable=True)  # minutes
    status = Column(String(20), default="active")  # active, executed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)
    execution_reason = Column(Text, nullable=True)

class PositionSize(Base):
    """Position sizing records table"""
    __tablename__ = "position_sizes"
    
    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(String(100), ForeignKey("trade_executions.trade_id"))
    optimal_size = Column(Float)
    max_size = Column(Float)
    min_size = Column(Float)
    kelly_percentage = Column(Float)
    risk_adjusted_size = Column(Float)
    volatility_adjusted_size = Column(Float)
    final_size = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

class SafetyRule(Base):
    """Safety rules configuration table"""
    __tablename__ = "safety_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    rule_type = Column(String(50), unique=True, index=True)
    value = Column(Float)
    enabled = Column(Boolean, default=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

# Create tables
def create_tables():
    """Create all database tables"""
    Base.metadata.create_all(bind=engine)

# Database dependency
def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
