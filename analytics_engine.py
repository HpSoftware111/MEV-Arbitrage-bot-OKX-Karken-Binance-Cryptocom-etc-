"""
Advanced Analytics System for MEV Bot
Provides comprehensive historical data analysis, profit tracking, and performance metrics
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import json
import statistics
from collections import defaultdict

from database import (
    PriceData, ArbitrageOpportunity, TradeExecution, Position, 
    PortfolioSnapshot, BalanceData, get_db
)
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_

logger = logging.getLogger(__name__)

@dataclass
class PerformanceMetrics:
    total_return: float
    annualized_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    win_rate: float
    profit_factor: float
    average_win: float
    average_loss: float
    largest_win: float
    largest_loss: float
    consecutive_wins: int
    consecutive_losses: int

@dataclass
class MarketAnalysis:
    price_correlation: Dict[str, float]
    volatility_analysis: Dict[str, float]
    spread_analysis: Dict[str, Dict[str, float]]
    volume_analysis: Dict[str, Dict[str, float]]
    arbitrage_frequency: Dict[str, int]
    best_performing_pairs: List[Tuple[str, str, float]]

@dataclass
class TradingInsights:
    optimal_trade_size: float
    best_trading_hours: List[int]
    most_profitable_exchanges: List[Tuple[str, float]]
    risk_adjusted_returns: Dict[str, float]
    market_timing_accuracy: float
    seasonal_patterns: Dict[str, float]

class AnalyticsEngine:
    """Advanced analytics engine for comprehensive data analysis"""
    
    def __init__(self, websocket_manager=None):
        self.websocket_manager = websocket_manager
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes cache
        
    async def get_performance_metrics(self, days: int = 30) -> PerformanceMetrics:
        """Calculate comprehensive performance metrics"""
        try:
            db = next(get_db())
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                
                # Get all completed trades
                trades = db.query(TradeExecution).filter(
                    and_(
                        TradeExecution.status == "completed",
                        TradeExecution.timestamp >= cutoff_date
                    )
                ).order_by(TradeExecution.timestamp).all()
                
                if not trades:
                    return self._empty_performance_metrics()
                
                # Calculate basic metrics
                profits = [trade.net_profit for trade in trades]
                total_return = sum(profits)
                
                # Calculate returns percentage
                returns = []
                for trade in trades:
                    if trade.buy_price > 0:
                        returns.append(trade.net_profit / (trade.buy_price * trade.trade_amount))
                
                # Volatility (standard deviation of returns)
                volatility = statistics.stdev(returns) if len(returns) > 1 else 0
                
                # Annualized return
                days_trading = (datetime.utcnow() - trades[0].timestamp).days or 1
                annualized_return = (total_return / days_trading) * 365
                
                # Sharpe ratio (assuming risk-free rate = 0)
                sharpe_ratio = (statistics.mean(returns) / volatility) if volatility > 0 else 0
                
                # Sortino ratio (downside deviation)
                downside_returns = [r for r in returns if r < 0]
                downside_deviation = statistics.stdev(downside_returns) if len(downside_returns) > 1 else 0
                sortino_ratio = (statistics.mean(returns) / downside_deviation) if downside_deviation > 0 else 0
                
                # Max drawdown
                max_drawdown, max_drawdown_duration = self._calculate_max_drawdown(trades)
                
                # Calmar ratio
                calmar_ratio = (annualized_return / abs(max_drawdown)) if max_drawdown != 0 else 0
                
                # Win rate and profit factor
                winning_trades = [t for t in trades if t.net_profit > 0]
                losing_trades = [t for t in trades if t.net_profit < 0]
                
                win_rate = len(winning_trades) / len(trades) * 100
                
                total_wins = sum(t.net_profit for t in winning_trades)
                total_losses = abs(sum(t.net_profit for t in losing_trades))
                profit_factor = (total_wins / total_losses) if total_losses > 0 else float('inf')
                
                # Average win/loss
                average_win = statistics.mean([t.net_profit for t in winning_trades]) if winning_trades else 0
                average_loss = statistics.mean([t.net_profit for t in losing_trades]) if losing_trades else 0
                
                # Largest win/loss
                largest_win = max([t.net_profit for t in winning_trades]) if winning_trades else 0
                largest_loss = min([t.net_profit for t in losing_trades]) if losing_trades else 0
                
                # Consecutive wins/losses
                consecutive_wins, consecutive_losses = self._calculate_consecutive_streaks(trades)
                
                return PerformanceMetrics(
                    total_return=total_return,
                    annualized_return=annualized_return,
                    volatility=volatility,
                    sharpe_ratio=sharpe_ratio,
                    sortino_ratio=sortino_ratio,
                    calmar_ratio=calmar_ratio,
                    max_drawdown=max_drawdown,
                    max_drawdown_duration=max_drawdown_duration,
                    win_rate=win_rate,
                    profit_factor=profit_factor,
                    average_win=average_win,
                    average_loss=average_loss,
                    largest_win=largest_win,
                    largest_loss=largest_loss,
                    consecutive_wins=consecutive_wins,
                    consecutive_losses=consecutive_losses
                )
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error calculating performance metrics: {str(e)}")
            return self._empty_performance_metrics()
    
    async def get_market_analysis(self, days: int = 7) -> MarketAnalysis:
        """Analyze market conditions and arbitrage patterns"""
        try:
            db = next(get_db())
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                
                # Get price data
                prices = db.query(PriceData).filter(
                    PriceData.timestamp >= cutoff_date
                ).order_by(PriceData.timestamp).all()
                
                # Get arbitrage opportunities
                opportunities = db.query(ArbitrageOpportunity).filter(
                    ArbitrageOpportunity.timestamp >= cutoff_date
                ).all()
                
                # Price correlation analysis
                price_correlation = self._calculate_price_correlations(prices)
                
                # Volatility analysis
                volatility_analysis = self._calculate_volatility_by_exchange(prices)
                
                # Spread analysis
                spread_analysis = self._analyze_spreads(opportunities)
                
                # Volume analysis
                volume_analysis = self._analyze_volume_patterns(prices)
                
                # Arbitrage frequency
                arbitrage_frequency = self._analyze_arbitrage_frequency(opportunities)
                
                # Best performing pairs
                best_performing_pairs = self._find_best_performing_pairs(opportunities)
                
                return MarketAnalysis(
                    price_correlation=price_correlation,
                    volatility_analysis=volatility_analysis,
                    spread_analysis=spread_analysis,
                    volume_analysis=volume_analysis,
                    arbitrage_frequency=arbitrage_frequency,
                    best_performing_pairs=best_performing_pairs
                )
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error analyzing market: {str(e)}")
            return self._empty_market_analysis()
    
    async def get_trading_insights(self, days: int = 30) -> TradingInsights:
        """Generate trading insights and recommendations"""
        try:
            db = next(get_db())
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                
                # Get completed trades
                trades = db.query(TradeExecution).filter(
                    and_(
                        TradeExecution.status == "completed",
                        TradeExecution.timestamp >= cutoff_date
                    )
                ).all()
                
                if not trades:
                    return self._empty_trading_insights()
                
                # Optimal trade size analysis
                optimal_trade_size = self._calculate_optimal_trade_size(trades)
                
                # Best trading hours
                best_trading_hours = self._analyze_trading_hours(trades)
                
                # Most profitable exchanges
                most_profitable_exchanges = self._analyze_exchange_profitability(trades)
                
                # Risk-adjusted returns
                risk_adjusted_returns = self._calculate_risk_adjusted_returns(trades)
                
                # Market timing accuracy
                market_timing_accuracy = self._calculate_market_timing_accuracy(trades)
                
                # Seasonal patterns
                seasonal_patterns = self._analyze_seasonal_patterns(trades)
                
                return TradingInsights(
                    optimal_trade_size=optimal_trade_size,
                    best_trading_hours=best_trading_hours,
                    most_profitable_exchanges=most_profitable_exchanges,
                    risk_adjusted_returns=risk_adjusted_returns,
                    market_timing_accuracy=market_timing_accuracy,
                    seasonal_patterns=seasonal_patterns
                )
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error generating trading insights: {str(e)}")
            return self._empty_trading_insights()
    
    async def get_portfolio_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Comprehensive portfolio analytics"""
        try:
            db = next(get_db())
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                
                # Get portfolio snapshots
                snapshots = db.query(PortfolioSnapshot).filter(
                    PortfolioSnapshot.timestamp >= cutoff_date
                ).order_by(PortfolioSnapshot.timestamp).all()
                
                if not snapshots:
                    return {"error": "No portfolio data available"}
                
                # Portfolio value analysis
                portfolio_values = [s.total_value_usdt for s in snapshots]
                timestamps = [s.timestamp for s in snapshots]
                
                # Calculate portfolio metrics
                total_return = portfolio_values[-1] - portfolio_values[0] if len(portfolio_values) > 1 else 0
                return_percentage = (total_return / portfolio_values[0] * 100) if portfolio_values[0] > 0 else 0
                
                # Portfolio volatility
                returns = []
                for i in range(1, len(portfolio_values)):
                    if portfolio_values[i-1] > 0:
                        returns.append((portfolio_values[i] - portfolio_values[i-1]) / portfolio_values[i-1])
                
                portfolio_volatility = statistics.stdev(returns) if len(returns) > 1 else 0
                
                # Portfolio drawdown
                max_value = portfolio_values[0]
                max_drawdown = 0
                for value in portfolio_values:
                    if value > max_value:
                        max_value = value
                    drawdown = (max_value - value) / max_value
                    max_drawdown = max(max_drawdown, drawdown)
                
                # Asset allocation analysis
                asset_allocation = self._analyze_asset_allocation(snapshots)
                
                # Performance attribution
                performance_attribution = self._analyze_performance_attribution(snapshots)
                
                return {
                    "total_return": total_return,
                    "return_percentage": return_percentage,
                    "portfolio_volatility": portfolio_volatility,
                    "max_drawdown": max_drawdown * 100,
                    "asset_allocation": asset_allocation,
                    "performance_attribution": performance_attribution,
                    "value_history": [
                        {"timestamp": ts.isoformat(), "value": val} 
                        for ts, val in zip(timestamps, portfolio_values)
                    ]
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error analyzing portfolio: {str(e)}")
            return {"error": str(e)}
    
    async def get_risk_metrics(self, days: int = 30) -> Dict[str, Any]:
        """Calculate comprehensive risk metrics"""
        try:
            db = next(get_db())
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=days)
                
                # Get trades for VaR calculation
                trades = db.query(TradeExecution).filter(
                    and_(
                        TradeExecution.status == "completed",
                        TradeExecution.timestamp >= cutoff_date
                    )
                ).all()
                
                if not trades:
                    return {"error": "No trade data available"}
                
                profits = [trade.net_profit for trade in trades]
                
                # Value at Risk (VaR) - 95% confidence
                profits_sorted = sorted(profits)
                var_95 = profits_sorted[int(len(profits_sorted) * 0.05)] if profits_sorted else 0
                
                # Expected Shortfall (Conditional VaR)
                tail_trades = [p for p in profits if p <= var_95]
                expected_shortfall = statistics.mean(tail_trades) if tail_trades else 0
                
                # Maximum Adverse Excursion (MAE)
                mae = min(profits) if profits else 0
                
                # Maximum Favorable Excursion (MFE)
                mfe = max(profits) if profits else 0
                
                # Risk-adjusted metrics
                total_profit = sum(profits)
                risk_adjusted_return = total_profit / abs(var_95) if var_95 != 0 else 0
                
                return {
                    "var_95": var_95,
                    "expected_shortfall": expected_shortfall,
                    "maximum_adverse_excursion": mae,
                    "maximum_favorable_excursion": mfe,
                    "risk_adjusted_return": risk_adjusted_return,
                    "total_trades": len(trades),
                    "risk_score": self._calculate_overall_risk_score(profits)
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error calculating risk metrics: {str(e)}")
            return {"error": str(e)}
    
    def _calculate_max_drawdown(self, trades: List[TradeExecution]) -> Tuple[float, int]:
        """Calculate maximum drawdown and duration"""
        if not trades:
            return 0, 0
        
        cumulative_profit = 0
        peak = 0
        max_dd = 0
        dd_duration = 0
        current_dd_duration = 0
        
        for trade in trades:
            cumulative_profit += trade.net_profit
            
            if cumulative_profit > peak:
                peak = cumulative_profit
                current_dd_duration = 0
            else:
                current_dd_duration += 1
                drawdown = peak - cumulative_profit
                if drawdown > max_dd:
                    max_dd = drawdown
                    dd_duration = current_dd_duration
        
        return max_dd, dd_duration
    
    def _calculate_consecutive_streaks(self, trades: List[TradeExecution]) -> Tuple[int, int]:
        """Calculate consecutive wins and losses"""
        if not trades:
            return 0, 0
        
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0
        
        for trade in trades:
            if trade.net_profit > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            elif trade.net_profit < 0:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)
        
        return max_wins, max_losses
    
    def _calculate_price_correlations(self, prices: List[PriceData]) -> Dict[str, float]:
        """Calculate price correlations between exchanges"""
        # Group prices by timestamp
        price_groups = defaultdict(dict)
        for price in prices:
            price_groups[price.timestamp][price.exchange] = price.last_price
        
        # Calculate correlations
        correlations = {}
        exchanges = list(set(p.exchange for p in prices))
        
        for i, exchange1 in enumerate(exchanges):
            for exchange2 in exchanges[i+1:]:
                prices1 = []
                prices2 = []
                
                for timestamp, group in price_groups.items():
                    if exchange1 in group and exchange2 in group:
                        prices1.append(group[exchange1])
                        prices2.append(group[exchange2])
                
                if len(prices1) > 1:
                    correlation = statistics.correlation(prices1, prices2) if len(prices1) > 1 else 0
                    correlations[f"{exchange1}-{exchange2}"] = correlation
        
        return correlations
    
    def _calculate_volatility_by_exchange(self, prices: List[PriceData]) -> Dict[str, float]:
        """Calculate volatility by exchange"""
        exchange_prices = defaultdict(list)
        
        for price in prices:
            exchange_prices[price.exchange].append(price.last_price)
        
        volatilities = {}
        for exchange, price_list in exchange_prices.items():
            if len(price_list) > 1:
                returns = []
                for i in range(1, len(price_list)):
                    if price_list[i-1] > 0:
                        returns.append((price_list[i] - price_list[i-1]) / price_list[i-1])
                
                volatilities[exchange] = statistics.stdev(returns) if len(returns) > 1 else 0
        
        return volatilities
    
    def _analyze_spreads(self, opportunities: List[ArbitrageOpportunity]) -> Dict[str, Dict[str, float]]:
        """Analyze arbitrage spreads"""
        spreads = defaultdict(list)
        
        for opp in opportunities:
            spread = opp.sell_price - opp.buy_price
            spread_pct = (spread / opp.buy_price) * 100
            pair = f"{opp.buy_exchange}-{opp.sell_exchange}"
            spreads[pair].append(spread_pct)
        
        spread_analysis = {}
        for pair, spread_list in spreads.items():
            spread_analysis[pair] = {
                "average": statistics.mean(spread_list),
                "median": statistics.median(spread_list),
                "max": max(spread_list),
                "min": min(spread_list),
                "std": statistics.stdev(spread_list) if len(spread_list) > 1 else 0
            }
        
        return spread_analysis
    
    def _analyze_volume_patterns(self, prices: List[PriceData]) -> Dict[str, Dict[str, float]]:
        """Analyze volume patterns by exchange"""
        exchange_volumes = defaultdict(list)
        
        for price in prices:
            if price.volume:
                exchange_volumes[price.exchange].append(price.volume)
        
        volume_analysis = {}
        for exchange, volume_list in exchange_volumes.items():
            if volume_list:
                volume_analysis[exchange] = {
                    "average": statistics.mean(volume_list),
                    "median": statistics.median(volume_list),
                    "max": max(volume_list),
                    "min": min(volume_list),
                    "std": statistics.stdev(volume_list) if len(volume_list) > 1 else 0
                }
        
        return volume_analysis
    
    def _analyze_arbitrage_frequency(self, opportunities: List[ArbitrageOpportunity]) -> Dict[str, int]:
        """Analyze arbitrage opportunity frequency"""
        frequency = defaultdict(int)
        
        for opp in opportunities:
            pair = f"{opp.buy_exchange}-{opp.sell_exchange}"
            frequency[pair] += 1
        
        return dict(frequency)
    
    def _find_best_performing_pairs(self, opportunities: List[ArbitrageOpportunity]) -> List[Tuple[str, str, float]]:
        """Find best performing arbitrage pairs"""
        pair_profits = defaultdict(list)
        
        for opp in opportunities:
            pair = f"{opp.buy_exchange}-{opp.sell_exchange}"
            pair_profits[pair].append(opp.profit_percentage)
        
        best_pairs = []
        for pair, profits in pair_profits.items():
            avg_profit = statistics.mean(profits)
            exchanges = pair.split('-')
            best_pairs.append((exchanges[0], exchanges[1], avg_profit))
        
        return sorted(best_pairs, key=lambda x: x[2], reverse=True)[:5]
    
    def _calculate_optimal_trade_size(self, trades: List[TradeExecution]) -> float:
        """Calculate optimal trade size based on historical performance"""
        if not trades:
            return 0
        
        # Simple optimization based on profit per trade amount
        trade_amounts = [trade.trade_amount for trade in trades]
        profits = [trade.net_profit for trade in trades]
        
        # Find trade size with best profit ratio
        profit_ratios = []
        for i, amount in enumerate(trade_amounts):
            if amount > 0:
                profit_ratios.append(profits[i] / amount)
        
        if profit_ratios:
            # Return median trade size for profitable trades
            profitable_trades = [(amount, ratio) for amount, ratio in zip(trade_amounts, profit_ratios) if ratio > 0]
            if profitable_trades:
                return statistics.median([amount for amount, _ in profitable_trades])
        
        return statistics.median(trade_amounts) if trade_amounts else 0
    
    def _analyze_trading_hours(self, trades: List[TradeExecution]) -> List[int]:
        """Analyze best trading hours"""
        hour_profits = defaultdict(list)
        
        for trade in trades:
            hour = trade.timestamp.hour
            hour_profits[hour].append(trade.net_profit)
        
        hour_avg_profits = {}
        for hour, profits in hour_profits.items():
            hour_avg_profits[hour] = statistics.mean(profits)
        
        # Return top 3 hours
        best_hours = sorted(hour_avg_profits.items(), key=lambda x: x[1], reverse=True)
        return [hour for hour, _ in best_hours[:3]]
    
    def _analyze_exchange_profitability(self, trades: List[TradeExecution]) -> List[Tuple[str, float]]:
        """Analyze exchange profitability"""
        exchange_profits = defaultdict(list)
        
        for trade in trades:
            exchange_profits[trade.buy_exchange].append(trade.net_profit)
            exchange_profits[trade.sell_exchange].append(trade.net_profit)
        
        exchange_avg_profits = {}
        for exchange, profits in exchange_profits.items():
            exchange_avg_profits[exchange] = statistics.mean(profits)
        
        return sorted(exchange_avg_profits.items(), key=lambda x: x[1], reverse=True)
    
    def _calculate_risk_adjusted_returns(self, trades: List[TradeExecution]) -> Dict[str, float]:
        """Calculate risk-adjusted returns by exchange"""
        exchange_data = defaultdict(lambda: {'profits': [], 'volatility': 0})
        
        for trade in trades:
            exchange_data[trade.buy_exchange]['profits'].append(trade.net_profit)
            exchange_data[trade.sell_exchange]['profits'].append(trade.net_profit)
        
        risk_adjusted = {}
        for exchange, data in exchange_data.items():
            if len(data['profits']) > 1:
                avg_return = statistics.mean(data['profits'])
                volatility = statistics.stdev(data['profits'])
                risk_adjusted[exchange] = avg_return / volatility if volatility > 0 else 0
        
        return risk_adjusted
    
    def _calculate_market_timing_accuracy(self, trades: List[TradeExecution]) -> float:
        """Calculate market timing accuracy"""
        if not trades:
            return 0
        
        # Simple timing accuracy based on profit consistency
        profits = [trade.net_profit for trade in trades]
        positive_trades = len([p for p in profits if p > 0])
        
        return (positive_trades / len(profits)) * 100
    
    def _analyze_seasonal_patterns(self, trades: List[TradeExecution]) -> Dict[str, float]:
        """Analyze seasonal trading patterns"""
        day_profits = defaultdict(list)
        
        for trade in trades:
            day_of_week = trade.timestamp.strftime('%A')
            day_profits[day_of_week].append(trade.net_profit)
        
        seasonal_patterns = {}
        for day, profits in day_profits.items():
            seasonal_patterns[day] = statistics.mean(profits)
        
        return seasonal_patterns
    
    def _analyze_asset_allocation(self, snapshots: List[PortfolioSnapshot]) -> Dict[str, float]:
        """Analyze asset allocation over time"""
        # This would require parsing the portfolio_data JSON
        # For now, return empty dict
        return {}
    
    def _analyze_performance_attribution(self, snapshots: List[PortfolioSnapshot]) -> Dict[str, float]:
        """Analyze performance attribution"""
        # This would require more detailed portfolio data
        # For now, return empty dict
        return {}
    
    def _calculate_overall_risk_score(self, profits: List[float]) -> float:
        """Calculate overall risk score (0-100)"""
        if not profits:
            return 0
        
        # Risk score based on volatility and drawdown
        volatility = statistics.stdev(profits) if len(profits) > 1 else 0
        max_loss = min(profits) if profits else 0
        
        # Normalize to 0-100 scale
        risk_score = min(100, max(0, (volatility * 100) + abs(max_loss)))
        
        return risk_score
    
    def _empty_performance_metrics(self) -> PerformanceMetrics:
        """Return empty performance metrics"""
        return PerformanceMetrics(
            total_return=0, annualized_return=0, volatility=0,
            sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
            max_drawdown=0, max_drawdown_duration=0, win_rate=0,
            profit_factor=0, average_win=0, average_loss=0,
            largest_win=0, largest_loss=0, consecutive_wins=0, consecutive_losses=0
        )
    
    def _empty_market_analysis(self) -> MarketAnalysis:
        """Return empty market analysis"""
        return MarketAnalysis(
            price_correlation={}, volatility_analysis={}, spread_analysis={},
            volume_analysis={}, arbitrage_frequency={}, best_performing_pairs=[]
        )
    
    def _empty_trading_insights(self) -> TradingInsights:
        """Return empty trading insights"""
        return TradingInsights(
            optimal_trade_size=0, best_trading_hours=[], most_profitable_exchanges=[],
            risk_adjusted_returns={}, market_timing_accuracy=0, seasonal_patterns={}
        )
