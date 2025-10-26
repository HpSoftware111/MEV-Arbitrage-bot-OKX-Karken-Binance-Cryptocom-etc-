"""
Exchange authentication and API management
"""

import ccxt
import asyncio
import aiohttp
from typing import Dict, Optional, List
from datetime import datetime
import os
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

class ExchangeManager:
    """Manages authentication and API calls for multiple exchanges"""
    
    def __init__(self):
        self.exchanges = {}
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def get_exchange_config(self, exchange_name: str) -> Dict:
        """Get exchange configuration from environment variables"""
        configs = {
            'kraken': {
                'apiKey': os.getenv('KRAKEN_API_KEY'),
                'secret': os.getenv('KRAKEN_API_SECRET'),
                'sandbox': False,
                'enableRateLimit': True
            },
            'okx': {
                'apiKey': os.getenv('OKX_API_KEY'),
                'secret': os.getenv('OKX_API_SECRET'),
                'password': os.getenv('OKX_PASSPHRASE'),
                'sandbox': False,
                'enableRateLimit': True
            },
            'binance': {
                'apiKey': os.getenv('BINANCE_API_KEY'),
                'secret': os.getenv('BINANCE_API_SECRET'),
                'sandbox': False,
                'enableRateLimit': True
            },
            'cryptocom': {
                'apiKey': os.getenv('CRYPTO_COM_API_KEY'),
                'secret': os.getenv('CRYPTO_COM_API_SECRET'),
                'sandbox': False,
                'enableRateLimit': True
            }
        }
        return configs.get(exchange_name, {})
    
    async def initialize_exchange(self, exchange_name: str) -> Optional[ccxt.Exchange]:
        """Initialize and authenticate exchange"""
        try:
            config = self.get_exchange_config(exchange_name)
            
            if not config.get('apiKey') or not config.get('secret'):
                logger.warning(f"No API credentials found for {exchange_name}")
                return None
            
            # Create exchange instance
            exchange_class = getattr(ccxt, exchange_name)
            exchange = exchange_class(config)
            
            # Test connection
            await exchange.load_markets()
            
            # Test authentication with a simple API call
            if exchange_name == 'okx':
                # OKX requires different auth test
                balance = await exchange.fetch_balance()
            else:
                balance = await exchange.fetch_balance()
            
            logger.info(f"Successfully authenticated with {exchange_name}")
            self.exchanges[exchange_name] = exchange
            return exchange
            
        except Exception as e:
            logger.error(f"Failed to initialize {exchange_name}: {str(e)}")
            return None
    
    async def get_public_ticker(self, exchange_name: str, symbol: str) -> Optional[Dict]:
        """Get public ticker data without authentication"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            urls = {
                'kraken': f"https://api.kraken.com/0/public/Ticker?pair=XRPUSDT",
                'okx': f"https://www.okx.com/api/v5/market/ticker?instId=XRP-USDT",
                'binance': f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol=XRPUSDT",
                'cryptocom': f"https://api.crypto.com/v2/public/get-ticker?instrument_name=XRP_USDT"
            }
            
            url = urls.get(exchange_name)
            if not url:
                return None
            
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return self.parse_ticker_data(exchange_name, data, symbol)
                elif response.status == 451 and exchange_name == 'binance':
                    logger.warning(f"Binance API blocked in your region (451). Consider using a VPN or alternative exchange.")
                    return None
                elif response.status == 403:
                    logger.warning(f"Access forbidden for {exchange_name} (403). This may be due to geo-restrictions.")
                    return None
                else:
                    logger.warning(f"Failed to fetch {symbol} from {exchange_name}: {response.status}")
                    return None
                    
        except Exception as e:
            if "Cannot connect to host" in str(e) and exchange_name == "binance":
                logger.warning(f"Binance connection failed - likely geo-blocked. Error: {str(e)}")
            else:
                logger.error(f"Error fetching {symbol} from {exchange_name}: {str(e)}")
            return None
    
    def parse_ticker_data(self, exchange_name: str, data: Dict, symbol: str) -> Optional[Dict]:
        """Parse ticker data from different exchange formats"""
        try:
            if exchange_name == 'kraken':
                pair_key = 'XRPUSDT'
                if 'result' in data and pair_key in data['result']:
                    ticker = data['result'][pair_key]
                    return {
                        'exchange': exchange_name,
                        'symbol': 'XRPUSDT',
                        'bid': float(ticker['b'][0]),
                        'ask': float(ticker['a'][0]),
                        'last': float(ticker['c'][0]),
                        'volume': float(ticker['v'][1]),
                        'timestamp': datetime.utcnow()
                    }
            
            elif exchange_name == 'okx':
                if 'data' in data and len(data['data']) > 0:
                    ticker = data['data'][0]
                    return {
                        'exchange': exchange_name,
                        'symbol': 'XRPUSDT',
                        'bid': float(ticker['bidPx']),
                        'ask': float(ticker['askPx']),
                        'last': float(ticker['last']),
                        'volume': float(ticker['vol24h']),
                        'timestamp': datetime.utcnow()
                    }
            
            elif exchange_name == 'binance':
                return {
                    'exchange': exchange_name,
                    'symbol': 'XRPUSDT',
                    'bid': float(data['bidPrice']),
                    'ask': float(data['askPrice']),
                    'last': float(data['lastPrice']),
                    'volume': float(data['volume']),
                    'timestamp': datetime.utcnow()
                }
            
            elif exchange_name == 'cryptocom':
                if 'result' in data and 'data' in data['result'] and len(data['result']['data']) > 0:
                    ticker = data['result']['data'][0]  # Data is in an array
                    return {
                        'exchange': exchange_name,
                        'symbol': 'XRPUSDT',
                        'bid': float(ticker['b']),
                        'ask': float(ticker['k']),
                        'last': float(ticker['a']),
                        'volume': float(ticker['v']),
                        'timestamp': datetime.utcnow()
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error parsing {exchange_name} ticker data: {str(e)}")
            return None
    
    async def get_authenticated_balance(self, exchange_name: str) -> Optional[Dict]:
        """Get account balance using authenticated API"""
        try:
            if exchange_name not in self.exchanges:
                exchange = await self.initialize_exchange(exchange_name)
                if not exchange:
                    return None
            else:
                exchange = self.exchanges[exchange_name]
            
            balance = await exchange.fetch_balance()
            return balance
            
        except Exception as e:
            logger.error(f"Error fetching balance from {exchange_name}: {str(e)}")
            return None
    
    async def close(self):
        """Close all exchange connections"""
        for exchange in self.exchanges.values():
            if hasattr(exchange, 'close'):
                await exchange.close()
        
        if self.session:
            await self.session.close()
