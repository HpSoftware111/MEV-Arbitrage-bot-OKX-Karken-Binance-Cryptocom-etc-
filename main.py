"""
FastAPI MEV Bot - Real-time XRP Price Monitoring
"""

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Optional
import asyncio
import logging
import json
from datetime import datetime, timedelta

from database import create_tables, get_db, PriceData, ArbitrageOpportunity, BotStatus
from price_monitor import PriceMonitor
from exchanges import ExchangeManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    # Startup
    global price_monitor, monitor_task
    
    # Create database tables
    create_tables()
    logger.info("Database tables created")
    
    # Initialize price monitor with WebSocket manager
    price_monitor = PriceMonitor(websocket_manager=manager)
    
    # Start monitoring in background
    monitor_task = asyncio.create_task(price_monitor.start_monitoring())
    logger.info("Price monitoring started")
    
    yield
    
    # Shutdown
    if price_monitor:
        await price_monitor.stop_monitoring()
    
    if monitor_task:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
    
    logger.info("Price monitoring stopped")

# Create FastAPI app
app = FastAPI(
    title="MEV Bot - XRP Price Monitor",
    description="Real-time XRP price monitoring across multiple exchanges",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global price monitor instance
price_monitor = None
monitor_task = None

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                # Remove disconnected connections
                self.active_connections.remove(connection)

manager = ConnectionManager()

# Pydantic models for API responses
from pydantic import BaseModel

class PriceResponse(BaseModel):
    exchange: str
    symbol: str
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    last_price: Optional[float] = None
    volume: Optional[float] = None
    timestamp: Optional[datetime] = None

class ArbitrageResponse(BaseModel):
    id: int
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    gross_profit: Optional[float] = None
    buy_fee: Optional[float] = None
    sell_fee: Optional[float] = None
    total_fees: Optional[float] = None
    buy_slippage: Optional[float] = None
    sell_slippage: Optional[float] = None
    total_slippage: Optional[float] = None
    profit_amount: float
    profit_percentage: float
    volume: float
    timestamp: datetime
    is_executed: bool
    direction: Optional[str] = None

class BotStatusResponse(BaseModel):
    status: str
    last_update: datetime
    error_message: Optional[str]

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main UI"""
    with open("templates/index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/")
async def api_root():
    """API root endpoint"""
    return {
        "message": "MEV Bot - XRP Price Monitor",
        "status": "running",
        "version": "1.0.0"
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle any incoming messages
            data = await websocket.receive_text()
            # Handle ping messages
            if data == "ping":
                await manager.send_personal_message('{"type": "pong", "timestamp": "' + datetime.utcnow().isoformat() + '"}', websocket)
            else:
                # Echo back any other received message as JSON
                await manager.send_personal_message(f'{{"type": "echo", "message": "{data}", "timestamp": "{datetime.utcnow().isoformat()}"}}', websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "monitoring": price_monitor.is_running if price_monitor else False
    }

@app.get("/prices", response_model=List[PriceResponse])
async def get_current_prices():
    """Get current XRP prices from all exchanges"""
    if not price_monitor:
        raise HTTPException(status_code=503, detail="Price monitor not initialized")
    
    prices = price_monitor.get_current_prices()
    return prices

@app.get("/prices/history")
async def get_price_history(
    exchange: Optional[str] = None,
    hours: int = 24,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get historical price data"""
    try:
        query = db.query(PriceData).filter(
            PriceData.symbol == "XRPUSDT",
            PriceData.timestamp >= datetime.utcnow() - timedelta(hours=hours)
        )
        
        if exchange:
            query = query.filter(PriceData.exchange == exchange)
        
        prices = query.order_by(PriceData.timestamp.desc()).limit(limit).all()
        
        return [{
            "exchange": price.exchange,
            "symbol": price.symbol,
            "bid_price": price.bid_price,
            "ask_price": price.ask_price,
            "last_price": price.last_price,
            "volume": price.volume,
            "timestamp": price.timestamp
        } for price in prices]
        
    except Exception as e:
        logger.error(f"Error fetching price history: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching price history")

@app.get("/arbitrage/opportunities", response_model=List[ArbitrageResponse])
async def get_arbitrage_opportunities(
    limit: int = 10,
    min_profit: float = 0.1
):
    """Get recent arbitrage opportunities"""
    if not price_monitor:
        raise HTTPException(status_code=503, detail="Price monitor not initialized")
    
    opportunities = price_monitor.get_recent_opportunities(limit)
    
    # Filter by minimum profit
    filtered_opportunities = [
        opp for opp in opportunities 
        if opp['profit_percentage'] >= min_profit
    ]
    
    return filtered_opportunities

@app.get("/arbitrage/opportunities/live")
async def get_live_arbitrage_opportunities():
    """Get live arbitrage opportunities (current prices)"""
    if not price_monitor:
        raise HTTPException(status_code=503, detail="Price monitor not initialized")
    
    current_prices = price_monitor.get_current_prices()
    
    if len(current_prices) < 2:
        return {"message": "Need at least 2 exchanges for arbitrage detection"}
    
    opportunities = price_monitor.calculate_arbitrage_opportunities(current_prices)
    
    # Filter profitable opportunities
    profitable_opportunities = [
        opp for opp in opportunities 
        if opp['profit_percentage'] >= 0.1
    ]
    
    return {
        "current_prices": current_prices,
        "opportunities": profitable_opportunities,
        "timestamp": datetime.utcnow()
    }

@app.get("/exchanges/status")
async def get_exchange_status():
    """Get status of all exchanges"""
    if not price_monitor:
        raise HTTPException(status_code=503, detail="Price monitor not initialized")
    
    current_prices = price_monitor.get_current_prices()
    
    exchange_status = {}
    for exchange in ['kraken', 'okx', 'binance', 'cryptocom']:  # All exchanges enabled
        exchange_data = next(
            (p for p in current_prices if p['exchange'] == exchange), 
            None
        )
        
        exchange_status[exchange] = {
            "status": "online" if exchange_data and exchange_data['last_price'] else "offline",
            "last_price": exchange_data['last_price'] if exchange_data else None,
            "last_update": exchange_data['timestamp'].isoformat() if exchange_data and exchange_data['timestamp'] else None
        }
    
    return exchange_status

@app.post("/monitor/start")
async def start_monitoring():
    """Start price monitoring"""
    global price_monitor, monitor_task
    
    if price_monitor and price_monitor.is_running:
        return {"message": "Monitoring already running"}
    
    if not price_monitor:
        price_monitor = PriceMonitor()
    
    monitor_task = asyncio.create_task(price_monitor.start_monitoring())
    
    return {"message": "Price monitoring started"}

@app.post("/monitor/stop")
async def stop_monitoring():
    """Stop price monitoring"""
    global price_monitor, monitor_task
    
    if not price_monitor or not price_monitor.is_running:
        return {"message": "Monitoring not running"}
    
    await price_monitor.stop_monitoring()
    
    if monitor_task:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
    
    return {"message": "Price monitoring stopped"}

@app.get("/stats")
async def get_statistics(db: Session = Depends(get_db)):
    """Get bot statistics"""
    try:
        # Count total price records
        total_prices = db.query(PriceData).count()
        
        # Count arbitrage opportunities
        total_opportunities = db.query(ArbitrageOpportunity).count()
        
        # Count opportunities with profit > 0.1%
        profitable_opportunities = db.query(ArbitrageOpportunity).filter(
            ArbitrageOpportunity.profit_percentage >= 0.1
        ).count()
        
        # Get latest price update
        latest_update = db.query(PriceData).order_by(
            PriceData.timestamp.desc()
        ).first()
        
        return {
            "total_price_records": total_prices,
            "total_arbitrage_opportunities": total_opportunities,
            "profitable_opportunities": profitable_opportunities,
            "latest_update": latest_update.timestamp if latest_update else None,
            "monitoring_status": price_monitor.is_running if price_monitor else False
        }
        
    except Exception as e:
        logger.error(f"Error fetching statistics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching statistics")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
