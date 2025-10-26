"""
Database configuration and models for MEV Bot
"""

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

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
    profit_amount = Column(Float)
    profit_percentage = Column(Float)
    volume = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    is_executed = Column(Boolean, default=False)
    direction = Column(String(50), nullable=True)

class BotStatus(Base):
    """Bot status and configuration table"""
    __tablename__ = "bot_status"
    
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(20), default="stopped")  # running, stopped, error
    last_update = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)
    config = Column(Text, nullable=True)  # JSON config

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
