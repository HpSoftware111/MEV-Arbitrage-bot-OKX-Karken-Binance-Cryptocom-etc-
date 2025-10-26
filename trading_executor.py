"""
Trading execution system for arbitrage opportunities
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import json

from exchanges import ExchangeManager
from database import ArbitrageOpportunity, TradeExecution, get_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class OrderStatus(Enum):
    PENDING = "pending"
    PLACED = "placed"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"

class TradeStatus(Enum):
    PENDING = "pending"
    BUY_PLACED = "buy_placed"
    BUY_FILLED = "buy_filled"
    SELL_PLACED = "sell_placed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class OrderResult:
    order_id: Optional[str]
    status: OrderStatus
    filled_amount: float
    filled_price: float
    remaining_amount: float
    fee: float
    timestamp: datetime
    error_message: Optional[str] = None

@dataclass
class TradeExecutionResult:
    trade_id: str
    status: TradeStatus
    buy_order: Optional[OrderResult]
    sell_order: Optional[OrderResult]
    total_profit: float
    total_fees: float
    execution_time: float
    error_message: Optional[str] = None

class TradingExecutor:
    """Handles execution of arbitrage trades"""
    
    def __init__(self, exchange_manager: ExchangeManager, websocket_manager=None):
        self.exchange_manager = exchange_manager
        self.websocket_manager = websocket_manager
        self.active_trades: Dict[str, TradeExecutionResult] = {}
        self.max_concurrent_trades = 3
        self.order_timeout = 30  # seconds
        self.is_trading_enabled = True
        
        # Safety limits
        self.max_trade_amount = 1000  # Maximum per trade
        self.daily_trade_limit = 10000  # Maximum per day
        self.min_profit_threshold = 0.05  # Minimum profit percentage
        
        # Load from environment
        import os
        self.max_trade_amount = float(os.getenv('MAX_TRADE_AMOUNT', 1000))
        self.daily_trade_limit = float(os.getenv('DAILY_TRADE_LIMIT', 10000))
        self.min_profit_threshold = float(os.getenv('MIN_PROFIT_THRESHOLD', 0.05))
        
    async def execute_arbitrage_trade(self, opportunity: Dict) -> TradeExecutionResult:
        """Execute a complete arbitrage trade"""
        trade_id = f"trade_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
        
        logger.info(f"Starting arbitrage trade {trade_id}: {opportunity['buy_exchange']} -> {opportunity['sell_exchange']}")
        
        try:
            # Check if trading is enabled
            if not self.is_trading_enabled:
                return TradeExecutionResult(
                    trade_id=trade_id,
                    status=TradeStatus.FAILED,
                    buy_order=None,
                    sell_order=None,
                    total_profit=0,
                    total_fees=0,
                    execution_time=0,
                    error_message="Trading is disabled"
                )
            
            # Check daily limits
            if await self._check_daily_limits():
                return TradeExecutionResult(
                    trade_id=trade_id,
                    status=TradeStatus.FAILED,
                    buy_order=None,
                    sell_order=None,
                    total_profit=0,
                    total_fees=0,
                    execution_time=0,
                    error_message="Daily trade limit exceeded"
                )
            
            # Validate opportunity
            if not self._validate_opportunity(opportunity):
                return TradeExecutionResult(
                    trade_id=trade_id,
                    status=TradeStatus.FAILED,
                    buy_order=None,
                    sell_order=None,
                    total_profit=0,
                    total_fees=0,
                    execution_time=0,
                    error_message="Invalid opportunity"
                )
            
            start_time = datetime.utcnow()
            
            # Calculate trade amount
            trade_amount = min(
                opportunity.get('max_trade_size', 100),
                self.max_trade_amount,
                opportunity.get('available_volume', 100)
            )
            
            # Execute buy order
            buy_order = await self._place_buy_order(
                opportunity['buy_exchange'],
                opportunity['symbol'],
                trade_amount,
                opportunity['buy_price']
            )
            
            if buy_order.status != OrderStatus.FILLED:
                return TradeExecutionResult(
                    trade_id=trade_id,
                    status=TradeStatus.FAILED,
                    buy_order=buy_order,
                    sell_order=None,
                    total_profit=0,
                    total_fees=buy_order.fee,
                    execution_time=(datetime.utcnow() - start_time).total_seconds(),
                    error_message=f"Buy order failed: {buy_order.error_message}"
                )
            
            # Execute sell order
            sell_order = await self._place_sell_order(
                opportunity['sell_exchange'],
                opportunity['symbol'],
                buy_order.filled_amount,
                opportunity['sell_price']
            )
            
            if sell_order.status != OrderStatus.FILLED:
                # Try to cancel buy order if sell fails
                await self._cancel_order(opportunity['buy_exchange'], buy_order.order_id)
                
                return TradeExecutionResult(
                    trade_id=trade_id,
                    status=TradeStatus.FAILED,
                    buy_order=buy_order,
                    sell_order=sell_order,
                    total_profit=0,
                    total_fees=buy_order.fee + sell_order.fee,
                    execution_time=(datetime.utcnow() - start_time).total_seconds(),
                    error_message=f"Sell order failed: {sell_order.error_message}"
                )
            
            # Calculate final profit
            total_profit = (sell_order.filled_price - buy_order.filled_price) * buy_order.filled_amount
            total_fees = buy_order.fee + sell_order.fee
            net_profit = total_profit - total_fees
            
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Store trade execution
            await self._store_trade_execution(trade_id, opportunity, buy_order, sell_order, net_profit, execution_time)
            
            # Broadcast trade completion
            if self.websocket_manager:
                await self._broadcast_trade_completion(trade_id, net_profit, execution_time)
            
            logger.info(f"Trade {trade_id} completed successfully. Net profit: ${net_profit:.4f}")
            
            return TradeExecutionResult(
                trade_id=trade_id,
                status=TradeStatus.COMPLETED,
                buy_order=buy_order,
                sell_order=sell_order,
                total_profit=net_profit,
                total_fees=total_fees,
                execution_time=execution_time
            )
            
        except Exception as e:
            logger.error(f"Error executing trade {trade_id}: {str(e)}")
            return TradeExecutionResult(
                trade_id=trade_id,
                status=TradeStatus.FAILED,
                buy_order=None,
                sell_order=None,
                total_profit=0,
                total_fees=0,
                execution_time=(datetime.utcnow() - start_time).total_seconds(),
                error_message=str(e)
            )
    
    async def _place_buy_order(self, exchange: str, symbol: str, amount: float, price: float) -> OrderResult:
        """Place a buy order"""
        try:
            logger.info(f"Placing buy order on {exchange}: {amount} {symbol} at ${price}")
            
            # Get exchange instance
            exchange_instance = self.exchange_manager.exchanges.get(exchange)
            if not exchange_instance:
                return OrderResult(
                    order_id=None,
                    status=OrderStatus.FAILED,
                    filled_amount=0,
                    filled_price=0,
                    remaining_amount=amount,
                    fee=0,
                    timestamp=datetime.utcnow(),
                    error_message=f"Exchange {exchange} not available"
                )
            
            # Place market buy order
            order = exchange_instance.create_market_buy_order(symbol, amount)
            
            # Wait for order to fill
            filled_order = await self._wait_for_order_fill(exchange, order['id'])
            
            return OrderResult(
                order_id=filled_order['id'],
                status=OrderStatus.FILLED,
                filled_amount=filled_order['filled'],
                filled_price=filled_order['average'],
                remaining_amount=filled_order['remaining'],
                fee=filled_order['fee']['cost'],
                timestamp=datetime.utcnow()
            )
            
        except Exception as e:
            logger.error(f"Error placing buy order on {exchange}: {str(e)}")
            return OrderResult(
                order_id=None,
                status=OrderStatus.FAILED,
                filled_amount=0,
                filled_price=0,
                remaining_amount=amount,
                fee=0,
                timestamp=datetime.utcnow(),
                error_message=str(e)
            )
    
    async def _place_sell_order(self, exchange: str, symbol: str, amount: float, price: float) -> OrderResult:
        """Place a sell order"""
        try:
            logger.info(f"Placing sell order on {exchange}: {amount} {symbol} at ${price}")
            
            # Get exchange instance
            exchange_instance = self.exchange_manager.exchanges.get(exchange)
            if not exchange_instance:
                return OrderResult(
                    order_id=None,
                    status=OrderStatus.FAILED,
                    filled_amount=0,
                    filled_price=0,
                    remaining_amount=amount,
                    fee=0,
                    timestamp=datetime.utcnow(),
                    error_message=f"Exchange {exchange} not available"
                )
            
            # Place market sell order
            order = exchange_instance.create_market_sell_order(symbol, amount)
            
            # Wait for order to fill
            filled_order = await self._wait_for_order_fill(exchange, order['id'])
            
            return OrderResult(
                order_id=filled_order['id'],
                status=OrderStatus.FILLED,
                filled_amount=filled_order['filled'],
                filled_price=filled_order['average'],
                remaining_amount=filled_order['remaining'],
                fee=filled_order['fee']['cost'],
                timestamp=datetime.utcnow()
            )
            
        except Exception as e:
            logger.error(f"Error placing sell order on {exchange}: {str(e)}")
            return OrderResult(
                order_id=None,
                status=OrderStatus.FAILED,
                filled_amount=0,
                filled_price=0,
                remaining_amount=amount,
                fee=0,
                timestamp=datetime.utcnow(),
                error_message=str(e)
            )
    
    async def _wait_for_order_fill(self, exchange: str, order_id: str, timeout: int = 30) -> Dict:
        """Wait for an order to fill"""
        start_time = datetime.utcnow()
        
        while (datetime.utcnow() - start_time).total_seconds() < timeout:
            try:
                exchange_instance = self.exchange_manager.exchanges.get(exchange)
                order = exchange_instance.fetch_order(order_id)
                
                if order['status'] == 'closed':
                    return order
                elif order['status'] == 'canceled':
                    raise Exception("Order was cancelled")
                
                await asyncio.sleep(1)  # Wait 1 second before checking again
                
            except Exception as e:
                logger.error(f"Error checking order status: {str(e)}")
                await asyncio.sleep(1)
        
        raise Exception(f"Order {order_id} did not fill within {timeout} seconds")
    
    async def _cancel_order(self, exchange: str, order_id: str) -> bool:
        """Cancel an order"""
        try:
            exchange_instance = self.exchange_manager.exchanges.get(exchange)
            if exchange_instance:
                exchange_instance.cancel_order(order_id)
                logger.info(f"Cancelled order {order_id} on {exchange}")
                return True
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {str(e)}")
        return False
    
    def _validate_opportunity(self, opportunity: Dict) -> bool:
        """Validate arbitrage opportunity"""
        try:
            # Check profit threshold
            if opportunity.get('profit_percentage', 0) < self.min_profit_threshold:
                return False
            
            # Check risk score
            if opportunity.get('risk_score', 100) > 80:
                return False
            
            # Check if exchanges are available
            if opportunity['buy_exchange'] not in self.exchange_manager.exchanges:
                return False
            if opportunity['sell_exchange'] not in self.exchange_manager.exchanges:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating opportunity: {str(e)}")
            return False
    
    async def _check_daily_limits(self) -> bool:
        """Check if daily trade limits are exceeded"""
        try:
            db = next(get_db())
            try:
                today = datetime.utcnow().date()
                daily_trades = db.query(TradeExecution).filter(
                    TradeExecution.timestamp >= today
                ).all()
                
                total_amount = sum(trade.trade_amount for trade in daily_trades)
                return total_amount >= self.daily_trade_limit
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error checking daily limits: {str(e)}")
            return False
    
    async def _store_trade_execution(self, trade_id: str, opportunity: Dict, 
                                   buy_order: OrderResult, sell_order: OrderResult, 
                                   net_profit: float, execution_time: float):
        """Store trade execution in database"""
        try:
            db = next(get_db())
            try:
                trade_record = TradeExecution(
                    trade_id=trade_id,
                    symbol=opportunity['symbol'],
                    buy_exchange=opportunity['buy_exchange'],
                    sell_exchange=opportunity['sell_exchange'],
                    buy_order_id=buy_order.order_id,
                    sell_order_id=sell_order.order_id,
                    trade_amount=buy_order.filled_amount,
                    buy_price=buy_order.filled_price,
                    sell_price=sell_order.filled_price,
                    total_fees=buy_order.fee + sell_order.fee,
                    net_profit=net_profit,
                    execution_time=execution_time,
                    status='completed',
                    timestamp=datetime.utcnow()
                )
                db.add(trade_record)
                db.commit()
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error storing trade execution: {str(e)}")
    
    async def _broadcast_trade_completion(self, trade_id: str, net_profit: float, execution_time: float):
        """Broadcast trade completion via WebSocket"""
        try:
            message = {
                'type': 'trade_completed',
                'data': {
                    'trade_id': trade_id,
                    'net_profit': net_profit,
                    'execution_time': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }
            await self.websocket_manager.broadcast(json.dumps(message))
            
        except Exception as e:
            logger.error(f"Error broadcasting trade completion: {str(e)}")
    
    def enable_trading(self):
        """Enable trading"""
        self.is_trading_enabled = True
        logger.info("Trading enabled")
    
    def disable_trading(self):
        """Disable trading"""
        self.is_trading_enabled = False
        logger.info("Trading disabled")
    
    def get_trading_status(self) -> Dict:
        """Get current trading status"""
        return {
            'enabled': self.is_trading_enabled,
            'active_trades': len(self.active_trades),
            'max_concurrent_trades': self.max_concurrent_trades,
            'max_trade_amount': self.max_trade_amount,
            'daily_trade_limit': self.daily_trade_limit,
            'min_profit_threshold': self.min_profit_threshold
        }
