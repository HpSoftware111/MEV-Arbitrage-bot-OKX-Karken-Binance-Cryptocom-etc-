"""
Real-time price monitoring service
"""

import asyncio
import logging
import json
from typing import Dict, List, Optional
from datetime import datetime
from exchanges import ExchangeManager
from database import PriceData, ArbitrageOpportunity, get_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class PriceMonitor:
    """Real-time price monitoring for XRP across multiple exchanges"""
    
    def __init__(self, websocket_manager=None):
        self.exchange_manager = ExchangeManager()
        self.is_running = False
        self.symbol = "XRPUSDT"
        self.exchanges = ['kraken', 'okx', 'binance', 'cryptocom']  # All exchanges enabled
        self.min_profit_threshold = 0.1  # 0.1% minimum profit
        self.websocket_manager = websocket_manager
        
        # Exchange fee structure (maker/taker fees)
        self.exchange_fees = {
            'kraken': {'maker': 0.16, 'taker': 0.26},  # 0.16%/0.26%
            'okx': {'maker': 0.08, 'taker': 0.10},     # 0.08%/0.10%
            'binance': {'maker': 0.10, 'taker': 0.10}, # 0.10%/0.10%
            'cryptocom': {'maker': 0.10, 'taker': 0.10} # 0.10%/0.10%
        }
        
        # Slippage estimates (percentage)
        self.slippage_estimates = {
            'kraken': 0.05,    # 0.05%
            'okx': 0.03,       # 0.03%
            'binance': 0.02,   # 0.02%
            'cryptocom': 0.05  # 0.05%
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
            
            if len(latest_prices) < 2:
                return
            
            # Find arbitrage opportunities
            opportunities = self.calculate_arbitrage_opportunities(latest_prices)
            
            # Store opportunities in database and broadcast via WebSocket
            profitable_opportunities = []
            for opportunity in opportunities:
                if opportunity['profit_percentage'] >= self.min_profit_threshold:
                    await self.store_arbitrage_opportunity(db, opportunity)
                    profitable_opportunities.append(opportunity)
            
            db.commit()
            
            # Broadcast profitable opportunities via WebSocket
            if profitable_opportunities and self.websocket_manager:
                await self.broadcast_opportunities(profitable_opportunities)
            
        finally:
            db.close()
    
    def get_latest_prices(self, db: Session) -> List[Dict]:
        """Get latest prices from database"""
        try:
            # Get latest price for each exchange
            latest_prices = []
            for exchange in self.exchanges:
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
        """Calculate arbitrage opportunity for a specific direction"""
        try:
            buy_price = buy_exchange['ask']
            sell_price = sell_exchange['bid']
            
            # Calculate gross profit
            gross_profit = sell_price - buy_price
            
            if gross_profit <= 0:
                return None
            
            # Calculate fees
            buy_fee_rate = self.exchange_fees.get(buy_exchange['exchange'], {}).get('taker', 0.10) / 100
            sell_fee_rate = self.exchange_fees.get(sell_exchange['exchange'], {}).get('taker', 0.10) / 100
            
            buy_fee = buy_price * buy_fee_rate
            sell_fee = sell_price * sell_fee_rate
            total_fees = buy_fee + sell_fee
            
            # Calculate slippage costs
            buy_slippage = buy_price * (self.slippage_estimates.get(buy_exchange['exchange'], 0.05) / 100)
            sell_slippage = sell_price * (self.slippage_estimates.get(sell_exchange['exchange'], 0.05) / 100)
            total_slippage = buy_slippage + sell_slippage
            
            # Calculate net profit
            net_profit = gross_profit - total_fees - total_slippage
            net_profit_percentage = (net_profit / buy_price) * 100
            
            # Only return opportunities with positive net profit
            if net_profit > 0:
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
                    'profit_amount': net_profit,
                    'profit_percentage': net_profit_percentage,
                    'volume': min(buy_exchange.get('volume', 0), sell_exchange.get('volume', 0)),
                    'timestamp': datetime.utcnow(),
                    'direction': direction
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error calculating directional opportunity: {str(e)}")
            return None
    
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
                profit_amount=opportunity['profit_amount'],
                profit_percentage=opportunity['profit_percentage'],
                volume=opportunity['volume'],
                timestamp=opportunity['timestamp'],
                direction=opportunity.get('direction')
            )
            db.add(opportunity_record)
        except Exception as e:
            logger.error(f"Error storing arbitrage opportunity: {str(e)}")
    
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
                'timestamp': datetime.utcnow().isoformat()
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
                'timestamp': datetime.utcnow().isoformat()
            }
            await self.websocket_manager.broadcast(json.dumps(message))
        except Exception as e:
            logger.error(f"Error broadcasting opportunities: {str(e)}")
