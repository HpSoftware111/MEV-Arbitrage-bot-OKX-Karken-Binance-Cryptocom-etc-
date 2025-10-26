"""
Portfolio Management System for MEV Bot
Handles balance tracking, position management, and portfolio analytics
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json

from exchanges import ExchangeManager
from database import BalanceData, TradeExecution, Position, PortfolioSnapshot, get_db
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

logger = logging.getLogger(__name__)

class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"

@dataclass
class PositionInfo:
    symbol: str
    exchange: str
    side: str  # 'long' or 'short'
    amount: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    status: PositionStatus
    opened_at: datetime
    closed_at: Optional[datetime] = None

@dataclass
class PortfolioMetrics:
    total_value_usdt: float
    total_pnl: float
    total_pnl_percentage: float
    daily_pnl: float
    daily_pnl_percentage: float
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    positions_count: int
    last_updated: datetime

class PortfolioManager:
    """Manages portfolio tracking, position management, and analytics"""
    
    def __init__(self, exchange_manager: ExchangeManager, websocket_manager=None):
        self.exchange_manager = exchange_manager
        self.websocket_manager = websocket_manager
        self.positions: Dict[str, PositionInfo] = {}
        self.portfolio_value_history: List[Tuple[datetime, float]] = []
        
        # Configuration
        import os
        self.base_currency = os.getenv('BASE_CURRENCY', 'USDT')
        self.position_size_limit = float(os.getenv('POSITION_SIZE_LIMIT', 0.1))  # 10% of portfolio
        self.max_positions = int(os.getenv('MAX_POSITIONS', 10))
        self.rebalance_threshold = float(os.getenv('REBALANCE_THRESHOLD', 0.05))  # 5%
        
    async def update_portfolio_snapshot(self):
        """Create a snapshot of current portfolio state"""
        try:
            # Get current balances from all exchanges
            balances = await self.exchange_manager.get_all_balances()
            
            # Calculate total portfolio value
            total_value = 0
            portfolio_data = {}
            
            for exchange, balance_data in balances.items():
                if balance_data.get('status') == 'authenticated':
                    exchange_value = 0
                    exchange_balances = {}
                    
                    for currency, balance_info in balance_data.get('balances', {}).items():
                        if balance_info['total'] > 0:
                            # Convert to USDT value
                            usdt_value = await self._convert_to_usdt(currency, balance_info['total'])
                            exchange_value += usdt_value
                            exchange_balances[currency] = {
                                'amount': balance_info['total'],
                                'usdt_value': usdt_value
                            }
                    
                    portfolio_data[exchange] = {
                        'total_value': exchange_value,
                        'balances': exchange_balances
                    }
                    total_value += exchange_value
            
            # Store snapshot in database
            await self._store_portfolio_snapshot(total_value, portfolio_data)
            
            # Update portfolio history
            self.portfolio_value_history.append((datetime.utcnow(), total_value))
            
            # Keep only last 1000 entries
            if len(self.portfolio_value_history) > 1000:
                self.portfolio_value_history = self.portfolio_value_history[-1000:]
            
            # Broadcast portfolio update
            if self.websocket_manager:
                await self._broadcast_portfolio_update(total_value, portfolio_data)
            
            logger.info(f"Portfolio snapshot updated. Total value: ${total_value:.2f}")
            
        except Exception as e:
            logger.error(f"Error updating portfolio snapshot: {str(e)}")
    
    async def track_position(self, trade_execution: TradeExecution):
        """Track a new position from trade execution"""
        try:
            # Determine position side based on trade
            if trade_execution.buy_exchange == trade_execution.sell_exchange:
                # Internal arbitrage - no position created
                return
            
            # Create position record
            position = Position(
                symbol=trade_execution.symbol,
                exchange=trade_execution.buy_exchange,
                side='long',  # We bought on this exchange
                amount=trade_execution.trade_amount,
                entry_price=trade_execution.buy_price,
                current_price=trade_execution.buy_price,
                unrealized_pnl=0,
                realized_pnl=0,
                status='open',
                opened_at=trade_execution.timestamp,
                trade_id=trade_execution.trade_id
            )
            
            db = next(get_db())
            try:
                db.add(position)
                db.commit()
                
                # Update in-memory positions
                position_key = f"{trade_execution.symbol}_{trade_execution.buy_exchange}"
                self.positions[position_key] = PositionInfo(
                    symbol=trade_execution.symbol,
                    exchange=trade_execution.buy_exchange,
                    side='long',
                    amount=trade_execution.trade_amount,
                    entry_price=trade_execution.buy_price,
                    current_price=trade_execution.buy_price,
                    unrealized_pnl=0,
                    realized_pnl=0,
                    status=PositionStatus.OPEN,
                    opened_at=trade_execution.timestamp
                )
                
                logger.info(f"Position tracked: {position_key}")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error tracking position: {str(e)}")
    
    async def update_position_prices(self):
        """Update current prices for all open positions"""
        try:
            db = next(get_db())
            try:
                open_positions = db.query(Position).filter(Position.status == 'open').all()
                
                for position in open_positions:
                    # Get current price for the symbol
                    current_price = await self._get_current_price(position.symbol, position.exchange)
                    
                    if current_price:
                        # Calculate unrealized PnL
                        if position.side == 'long':
                            unrealized_pnl = (current_price - position.entry_price) * position.amount
                        else:
                            unrealized_pnl = (position.entry_price - current_price) * position.amount
                        
                        # Update position
                        position.current_price = current_price
                        position.unrealized_pnl = unrealized_pnl
                        
                        # Update in-memory position
                        position_key = f"{position.symbol}_{position.exchange}"
                        if position_key in self.positions:
                            self.positions[position_key].current_price = current_price
                            self.positions[position_key].unrealized_pnl = unrealized_pnl
                
                db.commit()
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error updating position prices: {str(e)}")
    
    async def close_position(self, position_id: int, close_price: float, close_amount: Optional[float] = None):
        """Close a position partially or completely"""
        try:
            db = next(get_db())
            try:
                position = db.query(Position).filter(Position.id == position_id).first()
                
                if not position:
                    raise ValueError(f"Position {position_id} not found")
                
                # Calculate close amount
                if close_amount is None:
                    close_amount = position.amount
                else:
                    close_amount = min(close_amount, position.amount)
                
                # Calculate realized PnL
                if position.side == 'long':
                    realized_pnl = (close_price - position.entry_price) * close_amount
                else:
                    realized_pnl = (position.entry_price - close_price) * close_amount
                
                # Update position
                position.amount -= close_amount
                position.realized_pnl += realized_pnl
                
                if position.amount <= 0:
                    position.status = 'closed'
                    position.closed_at = datetime.utcnow()
                
                db.commit()
                
                # Update in-memory position
                position_key = f"{position.symbol}_{position.exchange}"
                if position_key in self.positions:
                    self.positions[position_key].amount -= close_amount
                    self.positions[position_key].realized_pnl += realized_pnl
                    
                    if self.positions[position_key].amount <= 0:
                        self.positions[position_key].status = PositionStatus.CLOSED
                        self.positions[position_key].closed_at = datetime.utcnow()
                
                logger.info(f"Position {position_id} closed. Realized PnL: ${realized_pnl:.2f}")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error closing position: {str(e)}")
    
    async def get_portfolio_metrics(self) -> PortfolioMetrics:
        """Calculate comprehensive portfolio metrics"""
        try:
            db = next(get_db())
            try:
                # Get latest portfolio snapshot
                latest_snapshot = db.query(PortfolioSnapshot).order_by(
                    desc(PortfolioSnapshot.timestamp)
                ).first()
                
                total_value = latest_snapshot.total_value_usdt if latest_snapshot else 0
                
                # Get daily PnL
                today = datetime.utcnow().date()
                yesterday_snapshot = db.query(PortfolioSnapshot).filter(
                    PortfolioSnapshot.timestamp >= today - timedelta(days=1)
                ).order_by(PortfolioSnapshot.timestamp).first()
                
                daily_pnl = 0
                daily_pnl_percentage = 0
                if yesterday_snapshot:
                    daily_pnl = total_value - yesterday_snapshot.total_value_usdt
                    daily_pnl_percentage = (daily_pnl / yesterday_snapshot.total_value_usdt) * 100
                
                # Get total PnL from trades
                total_trade_pnl = db.query(TradeExecution).filter(
                    TradeExecution.status == "completed"
                ).with_entities(
                    func.sum(TradeExecution.net_profit)
                ).scalar() or 0
                
                total_pnl_percentage = 0
                if total_value > 0:
                    total_pnl_percentage = (total_trade_pnl / total_value) * 100
                
                # Calculate win rate
                total_trades = db.query(TradeExecution).filter(
                    TradeExecution.status == "completed"
                ).count()
                
                winning_trades = db.query(TradeExecution).filter(
                    TradeExecution.status == "completed",
                    TradeExecution.net_profit > 0
                ).count()
                
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                
                # Calculate Sharpe ratio (simplified)
                sharpe_ratio = await self._calculate_sharpe_ratio()
                
                # Calculate max drawdown
                max_drawdown = await self._calculate_max_drawdown()
                
                # Count open positions
                positions_count = db.query(Position).filter(Position.status == 'open').count()
                
                return PortfolioMetrics(
                    total_value_usdt=total_value,
                    total_pnl=total_trade_pnl,
                    total_pnl_percentage=total_pnl_percentage,
                    daily_pnl=daily_pnl,
                    daily_pnl_percentage=daily_pnl_percentage,
                    win_rate=win_rate,
                    sharpe_ratio=sharpe_ratio,
                    max_drawdown=max_drawdown,
                    positions_count=positions_count,
                    last_updated=datetime.utcnow()
                )
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error calculating portfolio metrics: {str(e)}")
            return PortfolioMetrics(
                total_value_usdt=0,
                total_pnl=0,
                total_pnl_percentage=0,
                daily_pnl=0,
                daily_pnl_percentage=0,
                win_rate=0,
                sharpe_ratio=0,
                max_drawdown=0,
                positions_count=0,
                last_updated=datetime.utcnow()
            )
    
    async def get_position_summary(self) -> List[Dict]:
        """Get summary of all positions"""
        try:
            db = next(get_db())
            try:
                positions = db.query(Position).filter(Position.status == 'open').all()
                
                position_summary = []
                for position in positions:
                    # Get current price
                    current_price = await self._get_current_price(position.symbol, position.exchange)
                    
                    position_summary.append({
                        'id': position.id,
                        'symbol': position.symbol,
                        'exchange': position.exchange,
                        'side': position.side,
                        'amount': position.amount,
                        'entry_price': position.entry_price,
                        'current_price': current_price or position.current_price,
                        'unrealized_pnl': position.unrealized_pnl,
                        'realized_pnl': position.realized_pnl,
                        'opened_at': position.opened_at,
                        'trade_id': position.trade_id
                    })
                
                return position_summary
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting position summary: {str(e)}")
            return []
    
    async def rebalance_portfolio(self):
        """Rebalance portfolio based on target allocations"""
        try:
            # Get current portfolio metrics
            metrics = await self.get_portfolio_metrics()
            
            if metrics.total_value_usdt == 0:
                return
            
            # Check if rebalancing is needed
            # This is a simplified rebalancing logic
            # In practice, you'd have target allocations per exchange/asset
            
            logger.info("Portfolio rebalancing check completed")
            
        except Exception as e:
            logger.error(f"Error rebalancing portfolio: {str(e)}")
    
    async def _convert_to_usdt(self, currency: str, amount: float) -> float:
        """Convert any currency to USDT value"""
        try:
            if currency == 'USDT':
                return amount
            
            # Use exchange manager to get conversion rate
            # This is a simplified implementation
            # In practice, you'd get real-time rates from exchanges
            
            conversion_rates = {
                'BTC': 50000,  # Example rate
                'ETH': 3000,   # Example rate
                'XRP': 2.5,    # Example rate
                'BNB': 300,    # Example rate
            }
            
            rate = conversion_rates.get(currency, 1)
            return amount * rate
            
        except Exception as e:
            logger.error(f"Error converting {currency} to USDT: {str(e)}")
            return 0
    
    async def _get_current_price(self, symbol: str, exchange: str) -> Optional[float]:
        """Get current price for a symbol on an exchange"""
        try:
            exchange_instance = self.exchange_manager.exchanges.get(exchange)
            if exchange_instance:
                ticker = exchange_instance.fetch_ticker(symbol)
                return ticker['last']
        except Exception as e:
            logger.error(f"Error getting current price for {symbol} on {exchange}: {str(e)}")
        return None
    
    async def _store_portfolio_snapshot(self, total_value: float, portfolio_data: Dict):
        """Store portfolio snapshot in database"""
        try:
            db = next(get_db())
            try:
                snapshot = PortfolioSnapshot(
                    total_value_usdt=total_value,
                    portfolio_data=json.dumps(portfolio_data),
                    timestamp=datetime.utcnow()
                )
                db.add(snapshot)
                db.commit()
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error storing portfolio snapshot: {str(e)}")
    
    async def _broadcast_portfolio_update(self, total_value: float, portfolio_data: Dict):
        """Broadcast portfolio update via WebSocket"""
        try:
            message = {
                'type': 'portfolio_update',
                'data': {
                    'total_value': total_value,
                    'portfolio_data': portfolio_data,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }
            await self.websocket_manager.broadcast(json.dumps(message))
            
        except Exception as e:
            logger.error(f"Error broadcasting portfolio update: {str(e)}")
    
    async def _calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio for portfolio performance"""
        try:
            if len(self.portfolio_value_history) < 2:
                return 0
            
            # Calculate returns
            returns = []
            for i in range(1, len(self.portfolio_value_history)):
                prev_value = self.portfolio_value_history[i-1][1]
                curr_value = self.portfolio_value_history[i][1]
                if prev_value > 0:
                    returns.append((curr_value - prev_value) / prev_value)
            
            if not returns:
                return 0
            
            # Calculate mean and standard deviation
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_dev = variance ** 0.5
            
            # Sharpe ratio (assuming risk-free rate = 0)
            sharpe_ratio = mean_return / std_dev if std_dev > 0 else 0
            
            return sharpe_ratio
            
        except Exception as e:
            logger.error(f"Error calculating Sharpe ratio: {str(e)}")
            return 0
    
    async def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown"""
        try:
            if len(self.portfolio_value_history) < 2:
                return 0
            
            peak = self.portfolio_value_history[0][1]
            max_dd = 0
            
            for _, value in self.portfolio_value_history:
                if value > peak:
                    peak = value
                else:
                    drawdown = (peak - value) / peak
                    max_dd = max(max_dd, drawdown)
            
            return max_dd * 100  # Return as percentage
            
        except Exception as e:
            logger.error(f"Error calculating max drawdown: {str(e)}")
            return 0
