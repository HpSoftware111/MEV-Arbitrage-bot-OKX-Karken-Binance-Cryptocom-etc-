"""
Real-time price monitoring service
"""

import asyncio
import logging
import json
from typing import Dict, List, Optional
from datetime import datetime, timezone
from exchanges import ExchangeManager
from database import PriceData, ArbitrageOpportunity, BalanceData, get_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class PriceMonitor:
    """Real-time price monitoring for XRP across multiple exchanges"""
    
    def __init__(self, websocket_manager=None):
        import os
        self.exchange_manager = ExchangeManager()
        self.is_running = False
        self.symbol = "XRPUSDT"
        self.exchanges = ['kraken', 'binanceus', 'okx', 'cryptocom']  # All exchanges for price monitoring
        self.arbitrage_exchanges = ['kraken', 'binanceus', 'okx', 'cryptocom']  # All exchanges for arbitrage detection
        self.min_profit_threshold = float(os.getenv('MIN_PROFIT_THRESHOLD', 0.05))  # 0.05% minimum profit (configurable)
        self.max_trade_amount = float(os.getenv('MAX_TRADE_AMOUNT', 1000))  # Maximum trade amount in USDT
        self.min_volume_threshold = float(os.getenv('MIN_VOLUME_THRESHOLD', 1000))  # Minimum volume for trading
        self.websocket_manager = websocket_manager
        self.balance_update_interval = int(os.getenv('BALANCE_UPDATE_INTERVAL', 300))  # Update balances every 300 seconds (5 minutes)
        self.last_balance_update = None
        
        # Exchange fee structure (maker/taker fees) - Updated with accurate rates
        self.exchange_fees = {
            'kraken': {'maker': 0.16, 'taker': 0.26},      # 0.16%/0.26%
            'okx': {'maker': 0.08, 'taker': 0.10},         # 0.08%/0.10%
            'binanceus': {'maker': 0.10, 'taker': 0.10},   # 0.10%/0.10%
            'binance': {'maker': 0.10, 'taker': 0.10},    # Fallback for binance
            'cryptocom': {'maker': 0.10, 'taker': 0.10}   # 0.10%/0.10%
        }
        
        # Slippage estimates (percentage) - Based on market depth and liquidity
        self.slippage_estimates = {
            'kraken': 0.05,      # 0.05% - Lower liquidity
            'okx': 0.03,         # 0.03% - Good liquidity
            'binanceus': 0.02,   # 0.02% - Very liquid
            'binance': 0.02,     # Fallback for binance
            'cryptocom': 0.05    # 0.05% - Moderate liquidity
        }
        
        # Network transfer costs and times (in minutes)
        self.transfer_costs = {
            'kraken': {'cost_usdt': 0.0, 'time_minutes': 0},      # Internal transfer
            'okx': {'cost_usdt': 0.0, 'time_minutes': 0},        # Internal transfer
            'binanceus': {'cost_usdt': 0.0, 'time_minutes': 0},  # Internal transfer
            'binance': {'cost_usdt': 0.0, 'time_minutes': 0},    # Fallback for binance
            'cryptocom': {'cost_usdt': 0.0, 'time_minutes': 0}   # Internal transfer
        }
        
        # Minimum order sizes per exchange
        self.min_order_sizes = {
            'kraken': 10.0,      # $10 minimum
            'okx': 5.0,          # $5 minimum
            'binanceus': 10.0,   # $10 minimum
            'binance': 10.0,     # Fallback for binance
            'cryptocom': 10.0    # $10 minimum
        }
        
    async def start_monitoring(self):
        """Start real-time price monitoring"""
        self.is_running = True
        logger.info("Starting XRP price monitoring...")
        
        async with self.exchange_manager:
            while self.is_running:
                try:
                    await self.fetch_and_store_prices()
                    await self.detect_arbitrage_opportunities()
                    
                    # Update balances every 60 seconds
                    if (self.last_balance_update is None or 
                        (datetime.now(timezone.utc) - self.last_balance_update).seconds >= self.balance_update_interval):
                        await self.fetch_and_store_balances()
                        self.last_balance_update = datetime.now(timezone.utc)
                    
                    await asyncio.sleep(1)  # Update every second
                    
                except Exception as e:
                    logger.error(f"Error in price monitoring: {str(e)}")
                    await asyncio.sleep(5)  # Wait before retrying
    
    async def stop_monitoring(self):
        """Stop price monitoring"""
        self.is_running = False
        logger.info("Stopping price monitoring...")
    
    async def fetch_and_store_prices(self):
        """Fetch prices from all exchanges and store in database"""
        tasks = []
        
        for exchange in self.exchanges:
            task = self.fetch_single_exchange_price(exchange)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Store results in database
        db = next(get_db())
        try:
            valid_prices = []
            for result in results:
                if isinstance(result, dict) and 'exchange' in result:
                    await self.store_price_data(db, result)
                    valid_prices.append(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error fetching price: {result}")
            
            db.commit()
            
            # Broadcast prices via WebSocket
            if self.websocket_manager and valid_prices:
                await self.broadcast_prices(valid_prices)
                
        finally:
            db.close()
    
    async def fetch_single_exchange_price(self, exchange_name: str) -> Optional[Dict]:
        """Fetch price from a single exchange"""
        try:
            return await self.exchange_manager.get_public_ticker(exchange_name, self.symbol)
        except Exception as e:
            logger.error(f"Error fetching from {exchange_name}: {str(e)}")
            return None
    
    async def store_price_data(self, db: Session, price_data: Dict):
        """Store price data in database"""
        try:
            price_record = PriceData(
                exchange=price_data['exchange'],
                symbol=price_data['symbol'],
                bid_price=price_data['bid'],
                ask_price=price_data['ask'],
                last_price=price_data['last'],
                volume=price_data.get('volume'),
                timestamp=price_data['timestamp']
            )
            db.add(price_record)
        except Exception as e:
            logger.error(f"Error storing price data: {str(e)}")
    
    async def detect_arbitrage_opportunities(self):
        """Detect arbitrage opportunities between exchanges"""
        db = next(get_db())
        try:
            # Get latest prices from all exchanges
            latest_prices = self.get_latest_prices(db)
            
            logger.debug(f"Detecting arbitrage opportunities with {len(latest_prices)} exchanges")
            
            if len(latest_prices) < 2:
                logger.debug("Not enough exchanges for arbitrage detection")
                return
            
            # Log current prices for debugging
            for price in latest_prices:
                logger.debug(f"Price - {price['exchange']}: Ask={price['ask']:.5f}, Bid={price['bid']:.5f}, Last={price['last']:.5f}")
            
            # Find arbitrage opportunities
            opportunities = self.calculate_arbitrage_opportunities(latest_prices)
            
            logger.info(f"Found {len(opportunities)} total arbitrage opportunities")
            
            # Store opportunities in database and broadcast via WebSocket
            profitable_opportunities = []
            for opportunity in opportunities:
                if opportunity['profit_percentage'] >= self.min_profit_threshold:
                    logger.info(
                        f"Arbitrage Opportunity: Buy {opportunity['buy_exchange']} @ {opportunity['buy_price']:.5f}, "
                        f"Sell {opportunity['sell_exchange']} @ {opportunity['sell_price']:.5f}, "
                        f"Profit: {opportunity['profit_percentage']:.3f}% "
                        f"({opportunity['profit_amount']:.2f} USDT), "
                        f"Risk Score: {opportunity.get('risk_score', 'N/A')}"
                    )
                    await self.store_arbitrage_opportunity(db, opportunity)
                    profitable_opportunities.append(opportunity)
            
            db.commit()
            
            if profitable_opportunities:
                logger.info(f"Stored {len(profitable_opportunities)} profitable opportunities")
            else:
                logger.debug(f"No profitable opportunities found (threshold: {self.min_profit_threshold}%)")
            
            # Broadcast profitable opportunities via WebSocket
            if profitable_opportunities and self.websocket_manager:
                await self.broadcast_opportunities(profitable_opportunities)
            
        finally:
            db.close()
    
    async def fetch_and_store_balances(self):
        """Fetch balances from all exchanges and store in database"""
        try:
            balances = await self.exchange_manager.get_all_balances()
            db = next(get_db())
            
            try:
                for exchange_name, balance_data in balances.items():
                    if balance_data['status'] == 'authenticated':
                        for currency, balance_info in balance_data['balances'].items():
                            balance_record = BalanceData(
                                exchange=exchange_name,
                                currency=currency,
                                free_balance=balance_info['free'],
                                used_balance=balance_info['used'],
                                total_balance=balance_info['total'],
                                timestamp=balance_data['timestamp']
                            )
                            db.add(balance_record)
                
                db.commit()
                
                # Broadcast balances via WebSocket
                if self.websocket_manager:
                    await self.broadcast_balances(balances)
                    
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error fetching and storing balances: {str(e)}")
    
    def get_latest_prices(self, db: Session) -> List[Dict]:
        """Get latest prices from database for arbitrage detection"""
        try:
            # Get latest price for each arbitrage exchange only
            latest_prices = []
            for exchange in self.arbitrage_exchanges:
                price_record = db.query(PriceData).filter(
                    PriceData.exchange == exchange,
                    PriceData.symbol == self.symbol
                ).order_by(PriceData.timestamp.desc()).first()
                
                if price_record:
                    latest_prices.append({
                        'exchange': price_record.exchange,
                        'bid': price_record.bid_price,
                        'ask': price_record.ask_price,
                        'last': price_record.last_price,
                        'timestamp': price_record.timestamp
                    })
            
            return latest_prices
        except Exception as e:
            logger.error(f"Error getting latest prices: {str(e)}")
            return []
    
    def calculate_arbitrage_opportunities(self, prices: List[Dict]) -> List[Dict]:
        """Calculate arbitrage opportunities between exchanges with fees and slippage"""
        opportunities = []
        
        for i in range(len(prices)):
            for j in range(i + 1, len(prices)):
                exchange1 = prices[i]
                exchange2 = prices[j]
                
                # Calculate opportunities in both directions
                opportunity1 = self._calculate_directional_opportunity(
                    exchange1, exchange2, "buy_exchange1_sell_exchange2"
                )
                opportunity2 = self._calculate_directional_opportunity(
                    exchange2, exchange1, "buy_exchange2_sell_exchange1"
                )
                
                if opportunity1:
                    opportunities.append(opportunity1)
                if opportunity2:
                    opportunities.append(opportunity2)
        
        return opportunities
    
    def _calculate_directional_opportunity(self, buy_exchange: Dict, sell_exchange: Dict, direction: str) -> Optional[Dict]:
        """Calculate arbitrage opportunity for a specific direction with enhanced logic"""
        try:
            buy_price = buy_exchange['ask']
            sell_price = sell_exchange['bid']
            
            # Calculate gross profit
            gross_profit = sell_price - buy_price
            
            if gross_profit <= 0:
                return None
            
            # Calculate optimal trade amount based on available liquidity
            buy_volume = buy_exchange.get('volume', 0)
            sell_volume = sell_exchange.get('volume', 0)
            available_volume = min(buy_volume, sell_volume, self.max_trade_amount)
            
            # Skip if volume is too low
            if available_volume < self.min_volume_threshold:
                return None
            
            # Calculate fees (using taker fees for immediate execution)
            buy_fee_rate = self.exchange_fees.get(buy_exchange['exchange'], {}).get('taker', 0.10) / 100
            sell_fee_rate = self.exchange_fees.get(sell_exchange['exchange'], {}).get('taker', 0.10) / 100
            
            buy_fee = buy_price * buy_fee_rate
            sell_fee = sell_price * sell_fee_rate
            total_fees = buy_fee + sell_fee
            
            # Calculate slippage costs based on trade size
            buy_slippage_rate = self.slippage_estimates.get(buy_exchange['exchange'], 0.05) / 100
            sell_slippage_rate = self.slippage_estimates.get(sell_exchange['exchange'], 0.05) / 100
            
            # Adjust slippage based on trade size (larger trades = more slippage)
            size_multiplier = min(available_volume / 1000, 2.0)  # Cap at 2x for large trades
            buy_slippage = buy_price * buy_slippage_rate * size_multiplier
            sell_slippage = sell_price * sell_slippage_rate * size_multiplier
            total_slippage = buy_slippage + sell_slippage
            
            # Calculate transfer costs (if applicable)
            transfer_cost = self.transfer_costs.get(buy_exchange['exchange'], {}).get('cost_usdt', 0)
            transfer_time = self.transfer_costs.get(buy_exchange['exchange'], {}).get('time_minutes', 0)
            
            # Calculate net profit
            net_profit = gross_profit - total_fees - total_slippage - transfer_cost
            net_profit_percentage = (net_profit / buy_price) * 100
            
            # Calculate profit per trade amount
            profit_per_usdt = net_profit_percentage / 100
            
            # Calculate minimum viable trade size
            min_trade_size = max(
                self.min_order_sizes.get(buy_exchange['exchange'], 10),
                self.min_order_sizes.get(sell_exchange['exchange'], 10)
            )
            
            # Calculate maximum profitable trade size
            max_profitable_trade = available_volume
            
            # Calculate expected profit for different trade sizes
            small_trade_profit = min_trade_size * profit_per_usdt
            large_trade_profit = max_profitable_trade * profit_per_usdt
            
            # Risk assessment
            price_spread_percentage = (gross_profit / buy_price) * 100
            risk_score = self._calculate_risk_score(buy_exchange, sell_exchange, price_spread_percentage)
            
            # Only return opportunities with positive net profit above threshold
            if net_profit > 0 and net_profit_percentage >= self.min_profit_threshold:
                return {
                    'symbol': self.symbol,
                    'buy_exchange': buy_exchange['exchange'],
                    'sell_exchange': sell_exchange['exchange'],
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'gross_profit': gross_profit,
                    'buy_fee': buy_fee,
                    'sell_fee': sell_fee,
                    'total_fees': total_fees,
                    'buy_slippage': buy_slippage,
                    'sell_slippage': sell_slippage,
                    'total_slippage': total_slippage,
                    'transfer_cost': transfer_cost,
                    'transfer_time_minutes': transfer_time,
                    'profit_amount': net_profit,
                    'profit_percentage': net_profit_percentage,
                    'available_volume': available_volume,
                    'min_trade_size': min_trade_size,
                    'max_trade_size': max_profitable_trade,
                    'small_trade_profit': small_trade_profit,
                    'large_trade_profit': large_trade_profit,
                    'risk_score': risk_score,
                    'price_spread_percentage': price_spread_percentage,
                    'timestamp': datetime.now(timezone.utc),
                    'direction': direction
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error calculating directional opportunity: {str(e)}")
            return None
    
    def _calculate_risk_score(self, buy_exchange: Dict, sell_exchange: Dict, price_spread: float) -> float:
        """Calculate risk score for arbitrage opportunity (0-100, lower is better)"""
        try:
            risk_score = 0
            
            # Volume risk (lower volume = higher risk)
            buy_volume = buy_exchange.get('volume', 0)
            sell_volume = sell_exchange.get('volume', 0)
            avg_volume = (buy_volume + sell_volume) / 2
            
            if avg_volume < 10000:
                risk_score += 30
            elif avg_volume < 50000:
                risk_score += 15
            elif avg_volume < 100000:
                risk_score += 5
            
            # Price spread risk (very high spreads might indicate manipulation)
            if price_spread > 2.0:
                risk_score += 25
            elif price_spread > 1.0:
                risk_score += 15
            elif price_spread > 0.5:
                risk_score += 5
            
            # Exchange reliability (based on known exchange characteristics)
            exchange_risk = {
                'binanceus': 5,    # Binance.US - Most reliable
                'binance': 5,      # Binance - Most reliable (fallback)
                'okx': 8,          # OKX - Very reliable
                'kraken': 10,      # Kraken - Reliable but slower
                'cryptocom': 15    # Crypto.com - Less reliable
            }
            
            risk_score += exchange_risk.get(buy_exchange['exchange'], 20)
            risk_score += exchange_risk.get(sell_exchange['exchange'], 20)
            
            # Time risk (if transfer time is high)
            transfer_time = self.transfer_costs.get(buy_exchange['exchange'], {}).get('time_minutes', 0)
            if transfer_time > 10:
                risk_score += 20
            elif transfer_time > 5:
                risk_score += 10
            
            return min(risk_score, 100)  # Cap at 100
            
        except Exception as e:
            logger.error(f"Error calculating risk score: {str(e)}")
            return 50  # Default moderate risk
    
    async def store_arbitrage_opportunity(self, db: Session, opportunity: Dict):
        """Store arbitrage opportunity in database"""
        try:
            opportunity_record = ArbitrageOpportunity(
                symbol=opportunity['symbol'],
                buy_exchange=opportunity['buy_exchange'],
                sell_exchange=opportunity['sell_exchange'],
                buy_price=opportunity['buy_price'],
                sell_price=opportunity['sell_price'],
                gross_profit=opportunity.get('gross_profit'),
                buy_fee=opportunity.get('buy_fee'),
                sell_fee=opportunity.get('sell_fee'),
                total_fees=opportunity.get('total_fees'),
                buy_slippage=opportunity.get('buy_slippage'),
                sell_slippage=opportunity.get('sell_slippage'),
                total_slippage=opportunity.get('total_slippage'),
                transfer_cost=opportunity.get('transfer_cost', 0),
                transfer_time_minutes=opportunity.get('transfer_time_minutes', 0),
                profit_amount=opportunity['profit_amount'],
                profit_percentage=opportunity['profit_percentage'],
                available_volume=opportunity.get('available_volume'),
                min_trade_size=opportunity.get('min_trade_size'),
                max_trade_size=opportunity.get('max_trade_size'),
                small_trade_profit=opportunity.get('small_trade_profit'),
                large_trade_profit=opportunity.get('large_trade_profit'),
                risk_score=opportunity.get('risk_score'),
                price_spread_percentage=opportunity.get('price_spread_percentage'),
                volume=opportunity.get('volume', opportunity.get('available_volume', 0)),
                timestamp=opportunity['timestamp'],
                direction=opportunity.get('direction')
            )
            db.add(opportunity_record)
        except Exception as e:
            logger.error(f"Error storing arbitrage opportunity: {str(e)}")
    
    async def broadcast_balances(self, balances: Dict):
        """Broadcast balance updates via WebSocket"""
        try:
            # Convert the balance data format to match the REST API format
            serializable_balances = {}
            for exchange, balance_data in balances.items():
                if balance_data.get('status') == 'authenticated' and 'balances' in balance_data:
                    # Convert from {status: 'authenticated', balances: {...}} to direct balance format
                    serializable_balances[exchange] = balance_data['balances']
                elif balance_data.get('status') == 'demo' and 'balances' in balance_data:
                    # Handle demo mode
                    serializable_balances[exchange] = balance_data['balances']
            
            message = {
                'type': 'balances',
                'data': serializable_balances,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            await self.websocket_manager.broadcast(json.dumps(message))
        except Exception as e:
            logger.error(f"Error broadcasting balances: {str(e)}")
    
    def get_current_balances(self) -> Dict[str, Dict]:
        """Get current balances from database or live API"""
        # First try to get from database
        db = next(get_db())
        try:
            balances = {}
            has_recent_data = False
            
            for exchange in self.exchanges:
                exchange_balances = {}
                for currency in ['USDT', 'XRP', 'BTC', 'ETH']:
                    balance_record = db.query(BalanceData).filter(
                        BalanceData.exchange == exchange,
                        BalanceData.currency == currency
                    ).order_by(BalanceData.timestamp.desc()).first()
                    
                    if balance_record:
                        exchange_balances[currency] = {
                            'free': balance_record.free_balance,
                            'used': balance_record.used_balance,
                            'total': balance_record.total_balance,
                            'timestamp': balance_record.timestamp
                        }
                        # Check if data is recent (within last 5 minutes)
                        if balance_record.timestamp:
                            # Ensure both datetimes are timezone-aware
                            record_time = balance_record.timestamp
                            if record_time.tzinfo is None:
                                record_time = record_time.replace(tzinfo=timezone.utc)
                            if (datetime.now(timezone.utc) - record_time).seconds < 300:
                                has_recent_data = True
                    else:
                        exchange_balances[currency] = {
                            'free': 0,
                            'used': 0,
                            'total': 0,
                            'timestamp': None
                        }
                
                balances[exchange] = exchange_balances
            
            # If no recent data, try to fetch live balances
            if not has_recent_data and len(self.exchange_manager.exchanges) > 0:
                logger.info("No recent balance data, attempting live fetch...")
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    live_balances = loop.run_until_complete(self.exchange_manager.get_all_balances())
                    loop.close()
                    
                    # Convert live balances to the expected format
                    converted_balances = {}
                    for exchange, balance_data in live_balances.items():
                        if balance_data.get('status') in ['authenticated', 'demo']:
                            converted_balances[exchange] = balance_data.get('balances', {})
                        else:
                            converted_balances[exchange] = {}
                    
                    return converted_balances
                except Exception as e:
                    logger.error(f"Error fetching live balances: {str(e)}")
            
            return balances
        except Exception as e:
            logger.error(f"Error getting current balances: {str(e)}")
            return {}
        finally:
            db.close()
    
    def get_current_prices(self) -> List[Dict]:
        """Get current prices from database"""
        db = next(get_db())
        try:
            latest_prices = []
            for exchange in self.exchanges:
                price_record = db.query(PriceData).filter(
                    PriceData.exchange == exchange,
                    PriceData.symbol == self.symbol
                ).order_by(PriceData.timestamp.desc()).first()
                
                if price_record:
                    latest_prices.append({
                        'exchange': price_record.exchange,
                        'symbol': price_record.symbol,
                        'bid_price': price_record.bid_price,
                        'ask_price': price_record.ask_price,
                        'last_price': price_record.last_price,
                        'volume': price_record.volume,
                        'timestamp': price_record.timestamp
                    })
                else:
                    # Add offline exchange with null values
                    latest_prices.append({
                        'exchange': exchange,
                        'symbol': self.symbol,
                        'bid_price': None,
                        'ask_price': None,
                        'last_price': None,
                        'volume': None,
                        'timestamp': None
                    })
            
            return latest_prices
        except Exception as e:
            logger.error(f"Error getting current prices: {str(e)}")
            return []
        finally:
            db.close()
    
    def get_recent_opportunities(self, limit: int = 10) -> List[Dict]:
        """Get recent arbitrage opportunities"""
        db = next(get_db())
        try:
            opportunities = db.query(ArbitrageOpportunity).order_by(
                ArbitrageOpportunity.timestamp.desc()
            ).limit(limit).all()
            
            return [{
                'id': opp.id,
                'symbol': opp.symbol,
                'buy_exchange': opp.buy_exchange,
                'sell_exchange': opp.sell_exchange,
                'buy_price': opp.buy_price,
                'sell_price': opp.sell_price,
                'gross_profit': opp.gross_profit,
                'buy_fee': opp.buy_fee,
                'sell_fee': opp.sell_fee,
                'total_fees': opp.total_fees,
                'buy_slippage': opp.buy_slippage,
                'sell_slippage': opp.sell_slippage,
                'total_slippage': opp.total_slippage,
                'profit_amount': opp.profit_amount,
                'profit_percentage': opp.profit_percentage,
                'volume': opp.volume,
                'timestamp': opp.timestamp,
                'is_executed': opp.is_executed,
                'direction': opp.direction
            } for opp in opportunities]
        finally:
            db.close()
    
    async def broadcast_prices(self, prices: List[Dict]):
        """Broadcast current prices via WebSocket"""
        try:
            # Convert datetime objects to strings for JSON serialization
            serializable_prices = []
            for price in prices:
                serializable_price = price.copy()
                if 'timestamp' in serializable_price and hasattr(serializable_price['timestamp'], 'isoformat'):
                    serializable_price['timestamp'] = serializable_price['timestamp'].isoformat()
                # Convert field names for API compatibility
                if 'bid' in serializable_price:
                    serializable_price['bid_price'] = serializable_price.pop('bid')
                if 'ask' in serializable_price:
                    serializable_price['ask_price'] = serializable_price.pop('ask')
                if 'last' in serializable_price:
                    serializable_price['last_price'] = serializable_price.pop('last')
                serializable_prices.append(serializable_price)
            
            message = {
                'type': 'prices',
                'data': serializable_prices,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            await self.websocket_manager.broadcast(json.dumps(message))
        except Exception as e:
            logger.error(f"Error broadcasting prices: {str(e)}")
    
    async def broadcast_opportunities(self, opportunities: List[Dict]):
        """Broadcast arbitrage opportunities via WebSocket"""
        try:
            # Convert datetime objects to strings for JSON serialization
            serializable_opportunities = []
            for opp in opportunities:
                serializable_opp = opp.copy()
                if 'timestamp' in serializable_opp and hasattr(serializable_opp['timestamp'], 'isoformat'):
                    serializable_opp['timestamp'] = serializable_opp['timestamp'].isoformat()
                serializable_opportunities.append(serializable_opp)
            
            message = {
                'type': 'opportunities',
                'data': serializable_opportunities,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            await self.websocket_manager.broadcast(json.dumps(message))
        except Exception as e:
            logger.error(f"Error broadcasting opportunities: {str(e)}")
