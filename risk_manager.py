"""
Risk Management System for MEV Bot
Comprehensive risk controls including stop-loss, position sizing, and safety features
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import json
import statistics
from collections import defaultdict

from database import (
    TradeExecution, Position, PortfolioSnapshot, RiskEvent, 
    StopLossOrder, PositionSize, SafetyRule, get_db
)
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class SafetyRuleType(Enum):
    MAX_POSITION_SIZE = "max_position_size"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_DRAWDOWN = "max_drawdown"
    VOLATILITY_LIMIT = "volatility_limit"
    CORRELATION_LIMIT = "correlation_limit"
    EXCHANGE_LIMIT = "exchange_limit"
    TIME_LIMIT = "time_limit"

@dataclass
class RiskMetrics:
    current_exposure: float
    max_exposure: float
    daily_pnl: float
    daily_loss_limit: float
    max_drawdown: float
    max_drawdown_limit: float
    volatility: float
    volatility_limit: float
    correlation_risk: float
    correlation_limit: float
    risk_score: float
    safety_status: str

@dataclass
class PositionSizing:
    optimal_size: float
    max_size: float
    min_size: float
    kelly_percentage: float
    risk_adjusted_size: float
    volatility_adjusted_size: float

@dataclass
class StopLossConfig:
    enabled: bool
    stop_loss_percentage: float
    trailing_stop: bool
    trailing_percentage: float
    time_based_stop: bool
    max_hold_time: int  # minutes

class RiskManager:
    """Comprehensive risk management system"""
    
    def __init__(self, websocket_manager=None):
        self.websocket_manager = websocket_manager
        self.safety_rules = {}
        self.active_stop_losses = {}
        self.risk_events = []
        
        # Load configuration from environment
        import os
        self.max_position_size = float(os.getenv('MAX_POSITION_SIZE', 1000))  # USDT
        self.daily_loss_limit = float(os.getenv('DAILY_LOSS_LIMIT', 500))     # USDT
        self.max_drawdown_limit = float(os.getenv('MAX_DRAWDOWN_LIMIT', 0.1)) # 10%
        self.volatility_limit = float(os.getenv('VOLATILITY_LIMIT', 0.05))    # 5%
        self.correlation_limit = float(os.getenv('CORRELATION_LIMIT', 0.8))    # 80%
        self.max_exchanges_per_trade = int(os.getenv('MAX_EXCHANGES_PER_TRADE', 2))
        self.max_hold_time = int(os.getenv('MAX_HOLD_TIME', 60))  # minutes
        
        # Risk thresholds
        self.risk_thresholds = {
            RiskLevel.LOW: 0.3,
            RiskLevel.MEDIUM: 0.6,
            RiskLevel.HIGH: 0.8,
            RiskLevel.CRITICAL: 1.0
        }
        
        self.load_safety_rules()
    
    def load_safety_rules(self):
        """Load safety rules from database"""
        try:
            db = next(get_db())
            try:
                rules = db.query(SafetyRule).filter(SafetyRule.enabled == True).all()
                
                for rule in rules:
                    self.safety_rules[rule.rule_type] = {
                        'value': rule.value,
                        'enabled': rule.enabled,
                        'description': rule.description
                    }
                
                logger.info(f"Loaded {len(self.safety_rules)} safety rules")
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error loading safety rules: {str(e)}")
    
    async def assess_trade_risk(self, opportunity: Dict) -> Tuple[bool, str, float]:
        """Assess risk for a potential trade"""
        try:
            risk_factors = []
            risk_score = 0.0
            
            # Position size risk
            trade_amount = opportunity.get('max_trade_size', 0)
            if trade_amount > self.max_position_size:
                risk_factors.append(f"Trade size {trade_amount} exceeds limit {self.max_position_size}")
                risk_score += 0.3
            
            # Profit margin risk
            profit_percentage = opportunity.get('profit_percentage', 0)
            if profit_percentage < 0.1:  # Less than 0.1% profit
                risk_factors.append(f"Low profit margin: {profit_percentage:.2f}%")
                risk_score += 0.2
            
            # Volume risk
            available_volume = opportunity.get('available_volume', 0)
            if available_volume < 1000:  # Less than $1000 volume
                risk_factors.append(f"Low volume: ${available_volume}")
                risk_score += 0.2
            
            # Exchange risk
            buy_exchange = opportunity.get('buy_exchange', '')
            sell_exchange = opportunity.get('sell_exchange', '')
            
            # Check exchange reliability
            exchange_risk_scores = {
                'binance': 0.1,
                'okx': 0.15,
                'kraken': 0.2,
                'cryptocom': 0.25
            }
            
            buy_risk = exchange_risk_scores.get(buy_exchange, 0.3)
            sell_risk = exchange_risk_scores.get(sell_exchange, 0.3)
            risk_score += (buy_risk + sell_risk) / 2
            
            # Transfer time risk
            transfer_time = opportunity.get('transfer_time_minutes', 0)
            if transfer_time > 10:  # More than 10 minutes
                risk_factors.append(f"Long transfer time: {transfer_time} minutes")
                risk_score += 0.2
            
            # Risk score assessment
            risk_level = self._calculate_risk_level(risk_score)
            
            # Check if trade should be allowed
            allowed = risk_score < 0.8  # Allow trades with risk score < 80%
            
            risk_message = f"Risk Level: {risk_level.value.upper()} (Score: {risk_score:.2f})"
            if risk_factors:
                risk_message += f" - Factors: {', '.join(risk_factors)}"
            
            return allowed, risk_message, risk_score
            
        except Exception as e:
            logger.error(f"Error assessing trade risk: {str(e)}")
            return False, f"Risk assessment error: {str(e)}", 1.0
    
    async def calculate_position_size(self, opportunity: Dict, account_balance: float) -> PositionSizing:
        """Calculate optimal position size using multiple methods"""
        try:
            # Kelly Criterion calculation
            win_rate = await self._get_historical_win_rate()
            avg_win = await self._get_average_win()
            avg_loss = await self._get_average_loss()
            
            kelly_percentage = 0.0
            if avg_loss != 0 and win_rate > 0:
                kelly_percentage = (win_rate * avg_win - (1 - win_rate) * abs(avg_loss)) / avg_win
                kelly_percentage = max(0, min(kelly_percentage, 0.25))  # Cap at 25%
            
            # Risk-adjusted position sizing
            profit_percentage = opportunity.get('profit_percentage', 0)
            risk_score = opportunity.get('risk_score', 0.5)
            
            # Base size calculation
            base_size = min(account_balance * 0.02, self.max_position_size)  # 2% of account
            
            # Adjust for risk
            risk_adjusted_size = base_size * (1 - risk_score)
            
            # Adjust for volatility
            volatility = await self._get_market_volatility()
            volatility_adjusted_size = base_size * (1 - volatility)
            
            # Final size calculation
            optimal_size = min(
                base_size * kelly_percentage,
                risk_adjusted_size,
                volatility_adjusted_size,
                opportunity.get('max_trade_size', base_size)
            )
            
            # Ensure minimum viable size
            min_size = max(10.0, account_balance * 0.001)  # Minimum $10 or 0.1% of account
            optimal_size = max(optimal_size, min_size)
            
            return PositionSizing(
                optimal_size=optimal_size,
                max_size=min(self.max_position_size, account_balance * 0.05),  # Max 5% of account
                min_size=min_size,
                kelly_percentage=kelly_percentage,
                risk_adjusted_size=risk_adjusted_size,
                volatility_adjusted_size=volatility_adjusted_size
            )
            
        except Exception as e:
            logger.error(f"Error calculating position size: {str(e)}")
            return PositionSizing(
                optimal_size=100.0,
                max_size=self.max_position_size,
                min_size=10.0,
                kelly_percentage=0.0,
                risk_adjusted_size=100.0,
                volatility_adjusted_size=100.0
            )
    
    async def create_stop_loss(self, position_id: int, config: StopLossConfig) -> bool:
        """Create a stop-loss order for a position"""
        try:
            db = next(get_db())
            try:
                position = db.query(Position).filter(Position.id == position_id).first()
                
                if not position:
                    logger.error(f"Position {position_id} not found")
                    return False
                
                # Create stop-loss order
                stop_loss = StopLossOrder(
                    position_id=position_id,
                    stop_price=position.entry_price * (1 - config.stop_loss_percentage / 100),
                    trailing_stop=config.trailing_stop,
                    trailing_percentage=config.trailing_percentage,
                    time_based=config.time_based_stop,
                    max_hold_time=config.max_hold_time,
                    created_at=datetime.utcnow(),
                    status='active'
                )
                
                db.add(stop_loss)
                db.commit()
                
                # Store in active stop-losses
                self.active_stop_losses[position_id] = {
                    'stop_loss_id': stop_loss.id,
                    'config': config,
                    'created_at': datetime.utcnow()
                }
                
                logger.info(f"Stop-loss created for position {position_id}")
                return True
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error creating stop-loss: {str(e)}")
            return False
    
    async def monitor_stop_losses(self):
        """Monitor active stop-loss orders"""
        try:
            db = next(get_db())
            try:
                active_stops = db.query(StopLossOrder).filter(
                    StopLossOrder.status == 'active'
                ).all()
                
                for stop_loss in active_stops:
                    position = db.query(Position).filter(
                        Position.id == stop_loss.position_id
                    ).first()
                    
                    if not position or position.status != 'open':
                        # Position closed, cancel stop-loss
                        stop_loss.status = 'cancelled'
                        db.commit()
                        continue
                    
                    # Get current price
                    current_price = await self._get_current_price(position.symbol, position.exchange)
                    
                    if not current_price:
                        continue
                    
                    # Check stop-loss trigger
                    should_trigger = False
                    trigger_reason = ""
                    
                    # Price-based stop-loss
                    if current_price <= stop_loss.stop_price:
                        should_trigger = True
                        trigger_reason = f"Price {current_price} <= Stop {stop_loss.stop_price}"
                    
                    # Time-based stop-loss
                    if stop_loss.time_based:
                        hold_time = (datetime.utcnow() - position.opened_at).total_seconds() / 60
                        if hold_time >= stop_loss.max_hold_time:
                            should_trigger = True
                            trigger_reason = f"Hold time {hold_time:.1f}min >= Max {stop_loss.max_hold_time}min"
                    
                    # Trailing stop-loss
                    if stop_loss.trailing_stop and current_price > position.entry_price:
                        new_stop_price = current_price * (1 - stop_loss.trailing_percentage / 100)
                        if new_stop_price > stop_loss.stop_price:
                            stop_loss.stop_price = new_stop_price
                            db.commit()
                            logger.info(f"Trailing stop updated for position {position.id}: {new_stop_price}")
                    
                    if should_trigger:
                        # Execute stop-loss
                        await self._execute_stop_loss(stop_loss, position, trigger_reason)
                        
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error monitoring stop-losses: {str(e)}")
    
    async def check_safety_rules(self) -> Tuple[bool, List[str]]:
        """Check all safety rules and return violations"""
        try:
            violations = []
            
            # Check daily loss limit
            daily_pnl = await self._get_daily_pnl()
            if daily_pnl < -self.daily_loss_limit:
                violations.append(f"Daily loss ${abs(daily_pnl):.2f} exceeds limit ${self.daily_loss_limit}")
            
            # Check max drawdown
            max_drawdown = await self._get_max_drawdown()
            if max_drawdown > self.max_drawdown_limit:
                violations.append(f"Max drawdown {max_drawdown:.2%} exceeds limit {self.max_drawdown_limit:.2%}")
            
            # Check volatility
            volatility = await self._get_market_volatility()
            if volatility > self.volatility_limit:
                violations.append(f"Market volatility {volatility:.2%} exceeds limit {self.volatility_limit:.2%}")
            
            # Check correlation risk
            correlation_risk = await self._get_correlation_risk()
            if correlation_risk > self.correlation_limit:
                violations.append(f"Correlation risk {correlation_risk:.2%} exceeds limit {self.correlation_limit:.2%}")
            
            # Check position concentration
            position_concentration = await self._get_position_concentration()
            if position_concentration > 0.5:  # More than 50% in single position
                violations.append(f"Position concentration {position_concentration:.2%} too high")
            
            # Check exchange concentration
            exchange_concentration = await self._get_exchange_concentration()
            if exchange_concentration > 0.7:  # More than 70% on single exchange
                violations.append(f"Exchange concentration {exchange_concentration:.2%} too high")
            
            # Log violations
            if violations:
                await self._log_risk_event("safety_rule_violation", violations)
            
            return len(violations) == 0, violations
            
        except Exception as e:
            logger.error(f"Error checking safety rules: {str(e)}")
            return False, [f"Safety check error: {str(e)}"]
    
    async def get_risk_metrics(self) -> RiskMetrics:
        """Get comprehensive risk metrics"""
        try:
            current_exposure = await self._get_current_exposure()
            daily_pnl = await self._get_daily_pnl()
            max_drawdown = await self._get_max_drawdown()
            volatility = await self._get_market_volatility()
            correlation_risk = await self._get_correlation_risk()
            
            # Calculate overall risk score
            risk_score = self._calculate_overall_risk_score(
                current_exposure, daily_pnl, max_drawdown, volatility, correlation_risk
            )
            
            # Determine safety status
            safety_status = "SAFE"
            if risk_score > 0.8:
                safety_status = "CRITICAL"
            elif risk_score > 0.6:
                safety_status = "HIGH"
            elif risk_score > 0.4:
                safety_status = "MEDIUM"
            
            return RiskMetrics(
                current_exposure=current_exposure,
                max_exposure=self.max_position_size,
                daily_pnl=daily_pnl,
                daily_loss_limit=self.daily_loss_limit,
                max_drawdown=max_drawdown,
                max_drawdown_limit=self.max_drawdown_limit,
                volatility=volatility,
                volatility_limit=self.volatility_limit,
                correlation_risk=correlation_risk,
                correlation_limit=self.correlation_limit,
                risk_score=risk_score,
                safety_status=safety_status
            )
            
        except Exception as e:
            logger.error(f"Error getting risk metrics: {str(e)}")
            return RiskMetrics(
                current_exposure=0, max_exposure=0, daily_pnl=0, daily_loss_limit=0,
                max_drawdown=0, max_drawdown_limit=0, volatility=0, volatility_limit=0,
                correlation_risk=0, correlation_limit=0, risk_score=1.0, safety_status="UNKNOWN"
            )
    
    async def emergency_stop(self, reason: str) -> bool:
        """Emergency stop all trading activities"""
        try:
            # Close all open positions
            db = next(get_db())
            try:
                open_positions = db.query(Position).filter(Position.status == 'open').all()
                
                for position in open_positions:
                    # Force close position
                    position.status = 'closed'
                    position.closed_at = datetime.utcnow()
                
                # Cancel all active stop-losses
                active_stops = db.query(StopLossOrder).filter(StopLossOrder.status == 'active').all()
                for stop in active_stops:
                    stop.status = 'cancelled'
                
                db.commit()
                
                # Log emergency stop event
                await self._log_risk_event("emergency_stop", [reason])
                
                logger.critical(f"EMERGENCY STOP ACTIVATED: {reason}")
                return True
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in emergency stop: {str(e)}")
            return False
    
    def _calculate_risk_level(self, risk_score: float) -> RiskLevel:
        """Calculate risk level from score"""
        if risk_score >= self.risk_thresholds[RiskLevel.CRITICAL]:
            return RiskLevel.CRITICAL
        elif risk_score >= self.risk_thresholds[RiskLevel.HIGH]:
            return RiskLevel.HIGH
        elif risk_score >= self.risk_thresholds[RiskLevel.MEDIUM]:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW
    
    def _calculate_overall_risk_score(self, exposure: float, daily_pnl: float, 
                                    max_drawdown: float, volatility: float, 
                                    correlation: float) -> float:
        """Calculate overall risk score (0-1)"""
        risk_score = 0.0
        
        # Exposure risk (0-0.3)
        exposure_risk = min(exposure / self.max_position_size, 1.0) * 0.3
        risk_score += exposure_risk
        
        # Daily PnL risk (0-0.2)
        if daily_pnl < 0:
            pnl_risk = min(abs(daily_pnl) / self.daily_loss_limit, 1.0) * 0.2
            risk_score += pnl_risk
        
        # Drawdown risk (0-0.2)
        drawdown_risk = min(max_drawdown / self.max_drawdown_limit, 1.0) * 0.2
        risk_score += drawdown_risk
        
        # Volatility risk (0-0.15)
        volatility_risk = min(volatility / self.volatility_limit, 1.0) * 0.15
        risk_score += volatility_risk
        
        # Correlation risk (0-0.15)
        correlation_risk = min(correlation / self.correlation_limit, 1.0) * 0.15
        risk_score += correlation_risk
        
        return min(risk_score, 1.0)
    
    async def _get_historical_win_rate(self) -> float:
        """Get historical win rate"""
        try:
            db = next(get_db())
            try:
                total_trades = db.query(TradeExecution).filter(
                    TradeExecution.status == "completed"
                ).count()
                
                winning_trades = db.query(TradeExecution).filter(
                    and_(
                        TradeExecution.status == "completed",
                        TradeExecution.net_profit > 0
                    )
                ).count()
                
                return winning_trades / total_trades if total_trades > 0 else 0.5
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting win rate: {str(e)}")
            return 0.5
    
    async def _get_average_win(self) -> float:
        """Get average winning trade"""
        try:
            db = next(get_db())
            try:
                result = db.query(TradeExecution).filter(
                    and_(
                        TradeExecution.status == "completed",
                        TradeExecution.net_profit > 0
                    )
                ).with_entities(func.avg(TradeExecution.net_profit)).scalar()
                
                return result or 0.0
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting average win: {str(e)}")
            return 0.0
    
    async def _get_average_loss(self) -> float:
        """Get average losing trade"""
        try:
            db = next(get_db())
            try:
                result = db.query(TradeExecution).filter(
                    and_(
                        TradeExecution.status == "completed",
                        TradeExecution.net_profit < 0
                    )
                ).with_entities(func.avg(TradeExecution.net_profit)).scalar()
                
                return result or 0.0
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting average loss: {str(e)}")
            return 0.0
    
    async def _get_market_volatility(self) -> float:
        """Get current market volatility"""
        try:
            # This would typically use the analytics engine
            # For now, return a default value
            return 0.02  # 2% volatility
            
        except Exception as e:
            logger.error(f"Error getting market volatility: {str(e)}")
            return 0.05  # 5% default
    
    async def _get_current_price(self, symbol: str, exchange: str) -> Optional[float]:
        """Get current price for symbol on exchange"""
        try:
            # This would typically use the exchange manager
            # For now, return None
            return None
            
        except Exception as e:
            logger.error(f"Error getting current price: {str(e)}")
            return None
    
    async def _get_daily_pnl(self) -> float:
        """Get today's P&L"""
        try:
            db = next(get_db())
            try:
                today = datetime.utcnow().date()
                result = db.query(TradeExecution).filter(
                    and_(
                        TradeExecution.status == "completed",
                        TradeExecution.timestamp >= today
                    )
                ).with_entities(func.sum(TradeExecution.net_profit)).scalar()
                
                return result or 0.0
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting daily PnL: {str(e)}")
            return 0.0
    
    async def _get_max_drawdown(self) -> float:
        """Get maximum drawdown"""
        try:
            # This would typically use the analytics engine
            return 0.05  # 5% default
            
        except Exception as e:
            logger.error(f"Error getting max drawdown: {str(e)}")
            return 0.1  # 10% default
    
    async def _get_correlation_risk(self) -> float:
        """Get correlation risk"""
        try:
            # This would typically use the analytics engine
            return 0.3  # 30% default
            
        except Exception as e:
            logger.error(f"Error getting correlation risk: {str(e)}")
            return 0.5  # 50% default
    
    async def _get_position_concentration(self) -> float:
        """Get position concentration risk"""
        try:
            db = next(get_db())
            try:
                total_value = db.query(PortfolioSnapshot).order_by(
                    desc(PortfolioSnapshot.timestamp)
                ).first()
                
                if not total_value:
                    return 0.0
                
                # This is simplified - would need more complex calculation
                return 0.2  # 20% default
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting position concentration: {str(e)}")
            return 0.3  # 30% default
    
    async def _get_exchange_concentration(self) -> float:
        """Get exchange concentration risk"""
        try:
            # This would typically analyze portfolio allocation
            return 0.4  # 40% default
            
        except Exception as e:
            logger.error(f"Error getting exchange concentration: {str(e)}")
            return 0.5  # 50% default
    
    async def _get_current_exposure(self) -> float:
        """Get current total exposure"""
        try:
            db = next(get_db())
            try:
                result = db.query(Position).filter(
                    Position.status == 'open'
                ).with_entities(func.sum(Position.amount)).scalar()
                
                return result or 0.0
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting current exposure: {str(e)}")
            return 0.0
    
    async def _execute_stop_loss(self, stop_loss: StopLossOrder, position: Position, reason: str):
        """Execute stop-loss order"""
        try:
            # Close position
            position.status = 'closed'
            position.closed_at = datetime.utcnow()
            
            # Mark stop-loss as executed
            stop_loss.status = 'executed'
            stop_loss.executed_at = datetime.utcnow()
            stop_loss.execution_reason = reason
            
            # Log risk event
            await self._log_risk_event("stop_loss_executed", [reason])
            
            logger.info(f"Stop-loss executed for position {position.id}: {reason}")
            
        except Exception as e:
            logger.error(f"Error executing stop-loss: {str(e)}")
    
    async def _log_risk_event(self, event_type: str, details: List[str]):
        """Log risk event to database"""
        try:
            db = next(get_db())
            try:
                risk_event = RiskEvent(
                    event_type=event_type,
                    details=json.dumps(details),
                    timestamp=datetime.utcnow(),
                    severity=self._get_event_severity(event_type)
                )
                
                db.add(risk_event)
                db.commit()
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error logging risk event: {str(e)}")
    
    def _get_event_severity(self, event_type: str) -> str:
        """Get severity level for event type"""
        severity_map = {
            'emergency_stop': 'critical',
            'stop_loss_executed': 'high',
            'safety_rule_violation': 'medium',
            'risk_assessment': 'low'
        }
        return severity_map.get(event_type, 'medium')
