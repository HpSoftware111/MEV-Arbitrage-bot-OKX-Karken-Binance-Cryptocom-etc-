"""
FastAPI MEV Bot - Real-time XRP Price Monitoring
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Optional
import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta

from database import create_tables, get_db, PriceData, ArbitrageOpportunity, TradeExecution, Position, PortfolioSnapshot, BotStatus, RiskEvent, StopLossOrder, PositionSize, SafetyRule
from price_monitor import PriceMonitor
from exchanges import ExchangeManager
from trading_executor import TradingExecutor
from portfolio_manager import PortfolioManager
from analytics_engine import AnalyticsEngine
from risk_manager import RiskManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable detailed logging for price_monitor to see arbitrage status
logging.getLogger('price_monitor').setLevel(logging.INFO)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    # Startup
    global price_monitor, monitor_task, trading_executor, portfolio_manager, analytics_engine, risk_manager
    
    # Create database tables
    create_tables()
    logger.info("Database tables created")
    
    # Initialize price monitor with WebSocket manager
    price_monitor = PriceMonitor(websocket_manager=manager)
    
    # Start monitoring in background
    monitor_task = asyncio.create_task(price_monitor.start_monitoring())
    logger.info("Price monitoring started")
    
    # Initialize trading executor
    exchange_manager = ExchangeManager()
    trading_executor = TradingExecutor(exchange_manager, websocket_manager=manager)
    logger.info("Trading executor initialized")
    
    # Initialize portfolio manager
    portfolio_manager = PortfolioManager(exchange_manager, websocket_manager=manager)
    logger.info("Portfolio manager initialized")
    
    # Initialize analytics engine
    analytics_engine = AnalyticsEngine(websocket_manager=manager)
    logger.info("Analytics engine initialized")
    
    # Initialize risk manager
    risk_manager = RiskManager(websocket_manager=manager)
    logger.info("Risk manager initialized")
    
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

# Global instances
price_monitor = None
monitor_task = None
trading_executor = None
portfolio_manager = None
analytics_engine = None
risk_manager = None

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
                await manager.send_personal_message('{"type": "pong", "timestamp": "' + datetime.now(timezone.utc).isoformat() + '"}', websocket)
            elif data == "get_balances":
                # Send current balances
                if price_monitor:
                    balances = price_monitor.get_current_balances()
                    await manager.send_personal_message(json.dumps({
                        "type": "balances",
                        "data": balances,
                        "timestamp": datetime.utcnow().isoformat()
                    }), websocket)
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
    for exchange in ['kraken', 'binanceus', 'okx', 'cryptocom']:  # All exchanges enabled
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

@app.get("/balances")
async def get_current_balances():
    """Get current balances from all exchanges"""
    if not price_monitor:
        raise HTTPException(status_code=503, detail="Price monitor not initialized")
    
    balances = price_monitor.get_current_balances()
    return balances

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
        
        # Get trading stats
        total_trades = db.query(TradeExecution).count()
        successful_trades = db.query(TradeExecution).filter(
            TradeExecution.status == "completed"
        ).count()
        
        from sqlalchemy import func
        total_profit = db.query(TradeExecution).filter(
            TradeExecution.status == "completed"
        ).with_entities(
            func.sum(TradeExecution.net_profit)
        ).scalar() or 0
        
        return {
            "total_price_records": total_prices,
            "total_arbitrage_opportunities": total_opportunities,
            "profitable_opportunities": profitable_opportunities,
            "latest_update": latest_update.timestamp if latest_update else None,
            "monitoring_status": price_monitor.is_running if price_monitor else False,
            "total_trades": total_trades,
            "successful_trades": successful_trades,
            "total_profit": round(total_profit, 4),
            "trading_status": trading_executor.get_trading_status() if trading_executor else None
        }
        
    except Exception as e:
        logger.error(f"Error fetching statistics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching statistics")

# Trading API Endpoints
@app.post("/trading/execute")
async def execute_trade(opportunity_id: int, background_tasks: BackgroundTasks):
    """Execute an arbitrage trade"""
    if not trading_executor:
        raise HTTPException(status_code=503, detail="Trading executor not initialized")
    
    try:
        db = next(get_db())
        try:
            # Get opportunity from database
            opportunity_record = db.query(ArbitrageOpportunity).filter(
                ArbitrageOpportunity.id == opportunity_id
            ).first()
            
            if not opportunity_record:
                raise HTTPException(status_code=404, detail="Opportunity not found")
            
            # Convert to dict
            opportunity = {
                'symbol': opportunity_record.symbol,
                'buy_exchange': opportunity_record.buy_exchange,
                'sell_exchange': opportunity_record.sell_exchange,
                'buy_price': opportunity_record.buy_price,
                'sell_price': opportunity_record.sell_price,
                'profit_percentage': opportunity_record.profit_percentage,
                'risk_score': opportunity_record.risk_score,
                'max_trade_size': opportunity_record.max_trade_size,
                'available_volume': opportunity_record.available_volume
            }
            
            # Execute trade in background
            background_tasks.add_task(trading_executor.execute_arbitrage_trade, opportunity)
            
            return {"message": "Trade execution started", "opportunity_id": opportunity_id}
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error executing trade: {str(e)}")
        raise HTTPException(status_code=500, detail="Error executing trade")

@app.get("/trading/status")
async def get_trading_status():
    """Get trading status"""
    if not trading_executor:
        raise HTTPException(status_code=503, detail="Trading executor not initialized")
    
    return trading_executor.get_trading_status()

@app.post("/trading/enable")
async def enable_trading():
    """Enable trading"""
    if not trading_executor:
        raise HTTPException(status_code=503, detail="Trading executor not initialized")
    
    trading_executor.enable_trading()
    return {"message": "Trading enabled"}

@app.post("/trading/disable")
async def disable_trading():
    """Disable trading"""
    if not trading_executor:
        raise HTTPException(status_code=503, detail="Trading executor not initialized")
    
    trading_executor.disable_trading()
    return {"message": "Trading disabled"}

@app.get("/trading/history")
async def get_trading_history(
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get trading history"""
    try:
        trades = db.query(TradeExecution).order_by(
            TradeExecution.timestamp.desc()
        ).limit(limit).all()
        
        return [{
            "trade_id": trade.trade_id,
            "symbol": trade.symbol,
            "buy_exchange": trade.buy_exchange,
            "sell_exchange": trade.sell_exchange,
            "trade_amount": trade.trade_amount,
            "buy_price": trade.buy_price,
            "sell_price": trade.sell_price,
            "total_fees": trade.total_fees,
            "net_profit": trade.net_profit,
            "execution_time": trade.execution_time,
            "status": trade.status,
            "timestamp": trade.timestamp,
            "error_message": trade.error_message
        } for trade in trades]
        
    except Exception as e:
        logger.error(f"Error fetching trading history: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching trading history")

# Portfolio Management API Endpoints
@app.get("/portfolio/metrics")
async def get_portfolio_metrics():
    """Get comprehensive portfolio metrics"""
    if not portfolio_manager:
        raise HTTPException(status_code=503, detail="Portfolio manager not initialized")
    
    try:
        metrics = await portfolio_manager.get_portfolio_metrics()
        return {
            "total_value_usdt": metrics.total_value_usdt,
            "total_pnl": metrics.total_pnl,
            "total_pnl_percentage": metrics.total_pnl_percentage,
            "daily_pnl": metrics.daily_pnl,
            "daily_pnl_percentage": metrics.daily_pnl_percentage,
            "win_rate": metrics.win_rate,
            "sharpe_ratio": metrics.sharpe_ratio,
            "max_drawdown": metrics.max_drawdown,
            "positions_count": metrics.positions_count,
            "last_updated": metrics.last_updated
        }
    except Exception as e:
        logger.error(f"Error fetching portfolio metrics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching portfolio metrics")

@app.get("/portfolio/positions")
async def get_portfolio_positions():
    """Get current portfolio positions"""
    if not portfolio_manager:
        raise HTTPException(status_code=503, detail="Portfolio manager not initialized")
    
    try:
        positions = await portfolio_manager.get_position_summary()
        return positions
    except Exception as e:
        logger.error(f"Error fetching portfolio positions: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching portfolio positions")

@app.post("/portfolio/snapshot")
async def create_portfolio_snapshot():
    """Create a new portfolio snapshot"""
    if not portfolio_manager:
        raise HTTPException(status_code=503, detail="Portfolio manager not initialized")
    
    try:
        await portfolio_manager.update_portfolio_snapshot()
        return {"message": "Portfolio snapshot created"}
    except Exception as e:
        logger.error(f"Error creating portfolio snapshot: {str(e)}")
        raise HTTPException(status_code=500, detail="Error creating portfolio snapshot")

@app.post("/portfolio/rebalance")
async def rebalance_portfolio():
    """Rebalance portfolio"""
    if not portfolio_manager:
        raise HTTPException(status_code=503, detail="Portfolio manager not initialized")
    
    try:
        await portfolio_manager.rebalance_portfolio()
        return {"message": "Portfolio rebalancing completed"}
    except Exception as e:
        logger.error(f"Error rebalancing portfolio: {str(e)}")
        raise HTTPException(status_code=500, detail="Error rebalancing portfolio")

@app.post("/portfolio/positions/{position_id}/close")
async def close_position(position_id: int, close_price: float, close_amount: Optional[float] = None):
    """Close a position"""
    if not portfolio_manager:
        raise HTTPException(status_code=503, detail="Portfolio manager not initialized")
    
    try:
        await portfolio_manager.close_position(position_id, close_price, close_amount)
        return {"message": f"Position {position_id} closed"}
    except Exception as e:
        logger.error(f"Error closing position: {str(e)}")
        raise HTTPException(status_code=500, detail="Error closing position")

@app.get("/portfolio/history")
async def get_portfolio_history(
    days: int = 30,
    db: Session = Depends(get_db)
):
    """Get portfolio value history"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        snapshots = db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.timestamp >= cutoff_date
        ).order_by(PortfolioSnapshot.timestamp).all()
        
        return [{
            "timestamp": snapshot.timestamp,
            "total_value_usdt": snapshot.total_value_usdt,
            "portfolio_data": json.loads(snapshot.portfolio_data) if snapshot.portfolio_data else {}
        } for snapshot in snapshots]
        
    except Exception as e:
        logger.error(f"Error fetching portfolio history: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching portfolio history")

# Advanced Analytics API Endpoints
@app.get("/analytics/performance")
async def get_performance_analytics(days: int = 30):
    """Get comprehensive performance analytics"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not initialized")
    
    try:
        metrics = await analytics_engine.get_performance_metrics(days)
        return {
            "total_return": metrics.total_return,
            "annualized_return": metrics.annualized_return,
            "volatility": metrics.volatility,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "calmar_ratio": metrics.calmar_ratio,
            "max_drawdown": metrics.max_drawdown,
            "max_drawdown_duration": metrics.max_drawdown_duration,
            "win_rate": metrics.win_rate,
            "profit_factor": metrics.profit_factor,
            "average_win": metrics.average_win,
            "average_loss": metrics.average_loss,
            "largest_win": metrics.largest_win,
            "largest_loss": metrics.largest_loss,
            "consecutive_wins": metrics.consecutive_wins,
            "consecutive_losses": metrics.consecutive_losses
        }
    except Exception as e:
        logger.error(f"Error fetching performance analytics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching performance analytics")

@app.get("/analytics/market")
async def get_market_analytics(days: int = 7):
    """Get market analysis and arbitrage patterns"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not initialized")
    
    try:
        analysis = await analytics_engine.get_market_analysis(days)
        return {
            "price_correlation": analysis.price_correlation,
            "volatility_analysis": analysis.volatility_analysis,
            "spread_analysis": analysis.spread_analysis,
            "volume_analysis": analysis.volume_analysis,
            "arbitrage_frequency": analysis.arbitrage_frequency,
            "best_performing_pairs": analysis.best_performing_pairs
        }
    except Exception as e:
        logger.error(f"Error fetching market analytics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching market analytics")

@app.get("/analytics/insights")
async def get_trading_insights(days: int = 30):
    """Get trading insights and recommendations"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not initialized")
    
    try:
        insights = await analytics_engine.get_trading_insights(days)
        return {
            "optimal_trade_size": insights.optimal_trade_size,
            "best_trading_hours": insights.best_trading_hours,
            "most_profitable_exchanges": insights.most_profitable_exchanges,
            "risk_adjusted_returns": insights.risk_adjusted_returns,
            "market_timing_accuracy": insights.market_timing_accuracy,
            "seasonal_patterns": insights.seasonal_patterns
        }
    except Exception as e:
        logger.error(f"Error fetching trading insights: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching trading insights")

@app.get("/analytics/portfolio")
async def get_portfolio_analytics(days: int = 30):
    """Get comprehensive portfolio analytics"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not initialized")
    
    try:
        analytics_data = await analytics_engine.get_portfolio_analytics(days)
        return analytics_data
    except Exception as e:
        logger.error(f"Error fetching portfolio analytics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching portfolio analytics")

@app.get("/analytics/risk")
async def get_risk_metrics(days: int = 30):
    """Get comprehensive risk metrics"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not initialized")
    
    try:
        risk_data = await analytics_engine.get_risk_metrics(days)
        return risk_data
    except Exception as e:
        logger.error(f"Error fetching risk metrics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching risk metrics")

@app.get("/analytics/dashboard")
async def get_analytics_dashboard(days: int = 30):
    """Get comprehensive analytics dashboard data"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not initialized")
    
    try:
        # Get all analytics data
        performance = await analytics_engine.get_performance_metrics(days)
        market = await analytics_engine.get_market_analysis(days)
        insights = await analytics_engine.get_trading_insights(days)
        portfolio = await analytics_engine.get_portfolio_analytics(days)
        risk = await analytics_engine.get_risk_metrics(days)
        
        return {
            "performance": {
                "total_return": performance.total_return,
                "annualized_return": performance.annualized_return,
                "volatility": performance.volatility,
                "sharpe_ratio": performance.sharpe_ratio,
                "max_drawdown": performance.max_drawdown,
                "win_rate": performance.win_rate,
                "profit_factor": performance.profit_factor
            },
            "market": {
                "price_correlation": market.price_correlation,
                "volatility_analysis": market.volatility_analysis,
                "best_performing_pairs": market.best_performing_pairs
            },
            "insights": {
                "optimal_trade_size": insights.optimal_trade_size,
                "best_trading_hours": insights.best_trading_hours,
                "most_profitable_exchanges": insights.most_profitable_exchanges,
                "market_timing_accuracy": insights.market_timing_accuracy
            },
            "portfolio": portfolio,
            "risk": risk,
            "analysis_period_days": days,
            "generated_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error generating analytics dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Error generating analytics dashboard")

# Risk Management API Endpoints
@app.get("/risk/metrics")
async def get_risk_metrics():
    """Get comprehensive risk metrics"""
    if not risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not initialized")
    
    try:
        metrics = await risk_manager.get_risk_metrics()
        return {
            "current_exposure": metrics.current_exposure,
            "max_exposure": metrics.max_exposure,
            "daily_pnl": metrics.daily_pnl,
            "daily_loss_limit": metrics.daily_loss_limit,
            "max_drawdown": metrics.max_drawdown,
            "max_drawdown_limit": metrics.max_drawdown_limit,
            "volatility": metrics.volatility,
            "volatility_limit": metrics.volatility_limit,
            "correlation_risk": metrics.correlation_risk,
            "correlation_limit": metrics.correlation_limit,
            "risk_score": metrics.risk_score,
            "safety_status": metrics.safety_status
        }
    except Exception as e:
        logger.error(f"Error fetching risk metrics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching risk metrics")

@app.post("/risk/assess")
async def assess_trade_risk(opportunity: dict):
    """Assess risk for a potential trade"""
    if not risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not initialized")
    
    try:
        allowed, message, risk_score = await risk_manager.assess_trade_risk(opportunity)
        return {
            "allowed": allowed,
            "message": message,
            "risk_score": risk_score
        }
    except Exception as e:
        logger.error(f"Error assessing trade risk: {str(e)}")
        raise HTTPException(status_code=500, detail="Error assessing trade risk")

@app.post("/risk/position-size")
async def calculate_position_size(opportunity: dict, account_balance: float):
    """Calculate optimal position size"""
    if not risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not initialized")
    
    try:
        sizing = await risk_manager.calculate_position_size(opportunity, account_balance)
        return {
            "optimal_size": sizing.optimal_size,
            "max_size": sizing.max_size,
            "min_size": sizing.min_size,
            "kelly_percentage": sizing.kelly_percentage,
            "risk_adjusted_size": sizing.risk_adjusted_size,
            "volatility_adjusted_size": sizing.volatility_adjusted_size
        }
    except Exception as e:
        logger.error(f"Error calculating position size: {str(e)}")
        raise HTTPException(status_code=500, detail="Error calculating position size")

@app.post("/risk/stop-loss/{position_id}")
async def create_stop_loss(position_id: int, config: dict):
    """Create stop-loss order for position"""
    if not risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not initialized")
    
    try:
        from risk_manager import StopLossConfig
        stop_config = StopLossConfig(
            enabled=config.get('enabled', True),
            stop_loss_percentage=config.get('stop_loss_percentage', 5.0),
            trailing_stop=config.get('trailing_stop', False),
            trailing_percentage=config.get('trailing_percentage', 2.0),
            time_based_stop=config.get('time_based_stop', False),
            max_hold_time=config.get('max_hold_time', 60)
        )
        
        success = await risk_manager.create_stop_loss(position_id, stop_config)
        return {"success": success, "message": "Stop-loss created" if success else "Failed to create stop-loss"}
    except Exception as e:
        logger.error(f"Error creating stop-loss: {str(e)}")
        raise HTTPException(status_code=500, detail="Error creating stop-loss")

@app.get("/risk/safety-check")
async def check_safety_rules():
    """Check all safety rules"""
    if not risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not initialized")
    
    try:
        safe, violations = await risk_manager.check_safety_rules()
        return {
            "safe": safe,
            "violations": violations,
            "violation_count": len(violations)
        }
    except Exception as e:
        logger.error(f"Error checking safety rules: {str(e)}")
        raise HTTPException(status_code=500, detail="Error checking safety rules")

@app.post("/risk/emergency-stop")
async def emergency_stop(reason: str):
    """Emergency stop all trading activities"""
    if not risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not initialized")
    
    try:
        success = await risk_manager.emergency_stop(reason)
        return {"success": success, "message": "Emergency stop activated" if success else "Failed to activate emergency stop"}
    except Exception as e:
        logger.error(f"Error in emergency stop: {str(e)}")
        raise HTTPException(status_code=500, detail="Error in emergency stop")

@app.get("/risk/events")
async def get_risk_events(
    limit: int = 50,
    severity: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get risk events history"""
    try:
        query = db.query(RiskEvent)
        
        if severity:
            query = query.filter(RiskEvent.severity == severity)
        
        events = query.order_by(desc(RiskEvent.timestamp)).limit(limit).all()
        
        return [{
            "id": event.id,
            "event_type": event.event_type,
            "details": json.loads(event.details) if event.details else [],
            "severity": event.severity,
            "timestamp": event.timestamp
        } for event in events]
        
    except Exception as e:
        logger.error(f"Error fetching risk events: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching risk events")

@app.get("/risk/safety-rules")
async def get_safety_rules(db: Session = Depends(get_db)):
    """Get safety rules configuration"""
    try:
        rules = db.query(SafetyRule).all()
        
        return [{
            "id": rule.id,
            "rule_type": rule.rule_type,
            "value": rule.value,
            "enabled": rule.enabled,
            "description": rule.description,
            "created_at": rule.created_at,
            "updated_at": rule.updated_at
        } for rule in rules]
        
    except Exception as e:
        logger.error(f"Error fetching safety rules: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching safety rules")

@app.post("/risk/safety-rules")
async def update_safety_rule(rule_data: dict, db: Session = Depends(get_db)):
    """Update safety rule"""
    try:
        rule = db.query(SafetyRule).filter(
            SafetyRule.rule_type == rule_data['rule_type']
        ).first()
        
        if rule:
            rule.value = rule_data['value']
            rule.enabled = rule_data.get('enabled', True)
            rule.description = rule_data.get('description', rule.description)
            rule.updated_at = datetime.utcnow()
        else:
            rule = SafetyRule(
                rule_type=rule_data['rule_type'],
                value=rule_data['value'],
                enabled=rule_data.get('enabled', True),
                description=rule_data.get('description', '')
            )
            db.add(rule)
        
        db.commit()
        
        return {"message": "Safety rule updated"}
        
    except Exception as e:
        logger.error(f"Error updating safety rule: {str(e)}")
        raise HTTPException(status_code=500, detail="Error updating safety rule")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
