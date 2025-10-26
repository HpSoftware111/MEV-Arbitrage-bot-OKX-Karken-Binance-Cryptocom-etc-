"""
Exchange authentication and API management
"""

import ccxt
import asyncio
import aiohttp
import hmac
import hashlib
import base64
from typing import Dict, Optional, List
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

# Import OKX WebSocket
from okx_websocket import get_okx_websocket_client

class ExchangeManager:
    """Manages authentication and API calls for multiple exchanges"""
    
    def __init__(self):
        self.exchanges = {}
        self.session = None
        self.load_exchanges()
        
    def load_exchanges(self):
        """Load and authenticate exchanges based on available API keys"""
        exchange_configs = {
            'kraken': {
                'class': ccxt.kraken,
                'config': self.get_exchange_config('kraken')
            },
            'binanceus': {
                'class': ccxt.binanceus,
                'config': self.get_exchange_config('binanceus')
            },
            'okx': {
                'class': ccxt.okx,
                'config': self.get_exchange_config('okx')
            },
            'cryptocom': {
                'class': ccxt.cryptocom,
                'config': self.get_exchange_config('cryptocom')
            }
        }
        
        for exchange_name, config in exchange_configs.items():
            api_config = config['config']
            if api_config.get('apiKey') and api_config.get('secret'):
                try:
                    exchange = config['class'](api_config)
                    exchange.load_markets()
                    self.exchanges[exchange_name] = exchange
                    logger.info(f"Successfully loaded {exchange_name.upper()} exchange")
                except Exception as e:
                    logger.error(f"Failed to load {exchange_name.upper()}: {str(e)}")
            else:
                logger.warning(f"No API keys found for {exchange_name.upper()}")
        
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
                'sandbox': False,  # Kraken doesn't have sandbox
                'enableRateLimit': True
            },
            'binanceus': {
                'apiKey': os.getenv('BINANCE_API_KEY'),
                'secret': os.getenv('BINANCE_API_SECRET'),
                'sandbox': False,  # Use live API since we confirmed it works
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',  # Use spot trading
                    'recvWindow': 10000,
                }
            },
            'okx': {
                'apiKey': os.getenv('OKX_API_KEY'),
                'secret': os.getenv('OKX_API_SECRET'),
                'password': os.getenv('OKX_PASSPHRASE'),
                'sandbox': False,  # Use live API
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',  # Use spot trading
                }
            },
            'cryptocom': {
                'apiKey': os.getenv('CRYPTO_COM_API_KEY'),
                'secret': os.getenv('CRYPTO_COM_API_SECRET'),
                'sandbox': False,  # Use live API
                'enableRateLimit': True
            }
        }
        return configs.get(exchange_name, {})
    
    async def okx_login_and_subscribe(self, exchange: ccxt.Exchange) -> bool:
        """OKX specific login and subscribe authentication using correct signature method"""
        try:
            # OKX requires specific authentication headers
            api_key = exchange.apiKey
            secret = exchange.secret
            passphrase = exchange.password
            
            if not all([api_key, secret, passphrase]):
                logger.error("OKX: Missing API credentials")
                return False
            
            # Test authentication with account balance endpoint
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            method = 'GET'
            request_path = '/api/v5/account/balance'
            body = ''
            
            # Create signature using the correct method from your working code
            # prehash = timestamp + method + path + body
            prehash = f"{timestamp}{method}{request_path}{body}"
            signature = base64.b64encode(
                hmac.new(
                    secret.encode('utf-8'),
                    prehash.encode('utf-8'),
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')
            
            logger.debug(f"OKX Signature Debug:")
            logger.debug(f"  Timestamp: {timestamp}")
            logger.debug(f"  Method: {method}")
            logger.debug(f"  Path: {request_path}")
            logger.debug(f"  Body: '{body}'")
            logger.debug(f"  Prehash: {prehash}")
            logger.debug(f"  Signature: {signature[:20]}...")
            
            # Make authenticated request
            headers = {
                'OK-ACCESS-KEY': api_key,
                'OK-ACCESS-SIGN': signature,
                'OK-ACCESS-TIMESTAMP': timestamp,
                'OK-ACCESS-PASSPHRASE': passphrase,
                'Content-Type': 'application/json'
            }
            
            url = f"https://www.okx.com{request_path}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        logger.info("OKX: Login successful")
                        return True
                    else:
                        logger.error(f"OKX: Login failed - {response.status}: {response_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"OKX: Login/subscribe error: {str(e)}")
            return False
    
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
            
            # Special handling for OKX authentication
            if exchange_name == 'okx':
                # OKX requires specific authentication flow
                login_success = await self.okx_login_and_subscribe(exchange)
                if not login_success:
                    logger.error(f"OKX login/subscribe failed")
                    return None
                logger.info(f"Successfully authenticated with {exchange_name}")
            else:
                # Test authentication with a simple API call for other exchanges
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
            # Use WebSocket for OKX
            if exchange_name == 'okx':
                try:
                    ws_client = get_okx_websocket_client()
                    ticker_data = await ws_client.get_public_price()
                    if ticker_data:
                        logger.debug(f"OKX: WebSocket price - {ticker_data['last']} USDT")
                        return ticker_data
                except Exception as ws_error:
                    logger.debug(f"OKX: WebSocket failed, falling back to REST: {ws_error}")
            
            # Fallback to REST API for OKX and other exchanges
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            urls = {
                'kraken': f"https://api.kraken.com/0/public/Ticker?pair=XRPUSDT",
                'binanceus': f"https://api.binance.us/api/v3/ticker/24hr?symbol=XRPUSDT",
                'okx': f"https://us.okx.com/api/v5/market/ticker?instId=XRP-USDT",
                'cryptocom': f"https://api.crypto.com/v2/public/get-ticker?instrument_name=XRP_USDT"
            }
            
            url = urls.get(exchange_name)
            if not url:
                return None
            
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return self.parse_ticker_data(exchange_name, data, symbol)
                elif response.status == 451 and exchange_name == 'binanceus':
                    logger.warning(f"Binance API blocked in your region (451). Consider using a VPN or alternative exchange.")
                    return None
                elif response.status == 403:
                    logger.warning(f"Access forbidden for {exchange_name} (403). This may be due to geo-restrictions.")
                    return None
                else:
                    logger.warning(f"Failed to fetch {symbol} from {exchange_name}: {response.status}")
                    return None
                    
        except Exception as e:
            if "Cannot connect to host" in str(e) and exchange_name == "binanceus":
                logger.warning(f"Binance connection failed - likely geo-blocked. Error: {str(e)}")
            elif exchange_name == "cryptocom":
                logger.error(f"Crypto.com API error: {str(e)}")
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
                        'timestamp': datetime.now(timezone.utc)
                    }
            
            elif exchange_name == 'binanceus':
                return {
                    'exchange': exchange_name,
                    'symbol': 'XRPUSDT',
                    'bid': float(data['bidPrice']),
                    'ask': float(data['askPrice']),
                    'last': float(data['lastPrice']),
                    'volume': float(data['volume']),
                    'timestamp': datetime.now(timezone.utc)
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
                        'timestamp': datetime.now(timezone.utc)
                    }
                else:
                    logger.warning(f"OKX unexpected data structure: {data}")
                    return None
            
            elif exchange_name == 'cryptocom':
                logger.debug(f"Crypto.com raw data: {data}")
                if 'result' in data and 'data' in data['result'] and len(data['result']['data']) > 0:
                    ticker = data['result']['data'][0]  # Data is in an array
                    logger.debug(f"Crypto.com ticker: {ticker}")
                    return {
                        'exchange': exchange_name,
                        'symbol': 'XRPUSDT',
                        'bid': float(ticker['b']),  # bid price
                        'ask': float(ticker['a']),  # ask price
                        'last': float(ticker['k']),  # last price
                        'volume': float(ticker['v']),  # volume
                        'timestamp': datetime.now(timezone.utc)
                    }
                else:
                    logger.warning(f"Crypto.com unexpected data structure: {data}")
                    return None
            
            return None
            
        except Exception as e:
            logger.error(f"Error parsing {exchange_name} ticker data: {str(e)}")
            return None
    
    async def get_authenticated_balance(self, exchange_name: str) -> Optional[Dict]:
        """Get account balance using authenticated API"""
        try:
            # OKX REST API for balance
            if exchange_name == 'okx':
                return await self.get_okx_balance_rest()
            
            if exchange_name not in self.exchanges:
                exchange = await self.initialize_exchange(exchange_name)
                if not exchange:
                    return None
            else:
                exchange = self.exchanges[exchange_name]
            
            # For Crypto.com, try to reload markets if balance fetch fails
            if exchange_name == 'cryptocom':
                try:
                    # Force reload markets to refresh authentication
                    exchange.load_markets(reload=True)
                except:
                    pass  # Ignore errors during reload
            
            balance = exchange.fetch_balance()
            return balance
            
        except Exception as e:
            logger.error(f"Error fetching balance from {exchange_name}: {str(e)}")
            return None
    
    async def get_all_balances(self) -> Dict[str, Dict]:
        """Get balances from all authenticated exchanges"""
        balances = {}
        
        # Check if we have any authenticated exchanges
        has_authenticated = len(self.exchanges) > 0
        
        if not has_authenticated:
            # Return demo balances if no API keys are configured
            logger.info("No API keys configured, returning demo balances")
            return self.get_demo_balances()
        
        # Add OKX to the list even if it's not in exchanges (uses REST API)
        exchange_names = list(self.exchanges.keys())
        if 'okx' not in exchange_names:
            exchange_names.append('okx')
        
        for exchange_name in exchange_names:
            try:
                balance_data = await self.get_authenticated_balance(exchange_name)
                
                # For OKX, try REST API for balance (using US region)
                if exchange_name == 'okx' and not balance_data:
                    okx_balance = await self.get_okx_balance_rest()
                    if okx_balance:
                        # Convert OKX balance format to standard format
                        balances['okx'] = {
                            'status': 'authenticated',
                            'balances': okx_balance,
                            'timestamp': datetime.now(timezone.utc)
                        }
                    else:
                        balances['okx'] = {
                            'status': 'not_authenticated',
                            'balances': {
                                'USDT': {'free': 0, 'used': 0, 'total': 0},
                                'XRP': {'free': 0, 'used': 0, 'total': 0},
                                'BTC': {'free': 0, 'used': 0, 'total': 0},
                                'ETH': {'free': 0, 'used': 0, 'total': 0}
                            },
                            'timestamp': datetime.now(timezone.utc)
                        }
                    continue
                
                if balance_data:
                    # Extract relevant balances (USDT, XRP, BTC, ETH)
                    relevant_balances = {}
                    for currency in ['USDT', 'XRP', 'BTC', 'ETH']:
                        if currency in balance_data:
                            relevant_balances[currency] = {
                                'free': balance_data[currency].get('free', 0),
                                'used': balance_data[currency].get('used', 0),
                                'total': balance_data[currency].get('total', 0)
                            }
                    
                    # Also check for Kraken-specific currency formats
                    kraken_currencies = {
                        'BTC.F': 'BTC',  # BTC Futures
                        'XXBT': 'BTC',   # Kraken BTC
                        'XXRP': 'XRP',   # Kraken XRP
                        'ZUSD': 'USD',   # Kraken USD
                    }
                    
                    for kraken_symbol, standard_symbol in kraken_currencies.items():
                        if kraken_symbol in balance_data and balance_data[kraken_symbol].get('total', 0) > 0:
                            if standard_symbol not in relevant_balances:
                                relevant_balances[standard_symbol] = {
                                    'free': 0, 'used': 0, 'total': 0
                                }
                            relevant_balances[standard_symbol]['total'] += balance_data[kraken_symbol]['total']
                            relevant_balances[standard_symbol]['free'] += balance_data[kraken_symbol]['free']
                            relevant_balances[standard_symbol]['used'] += balance_data[kraken_symbol]['used']
                    
                    # Convert BTC and XRP to USDT equivalent
                    usdt_total = 0
                    usdt_free = 0
                    usdt_used = 0
                    conversion_details = {}
                    
                    # Convert BTC to USDT
                    if 'BTC' in relevant_balances and relevant_balances['BTC']['total'] > 0:
                        try:
                            btc_price_usdt = self.get_btc_usdt_price()
                            if btc_price_usdt:
                                btc_total = relevant_balances['BTC']['total']
                                btc_free = relevant_balances['BTC']['free']
                                btc_used = relevant_balances['BTC']['used']
                                
                                btc_usdt_total = btc_total * btc_price_usdt
                                btc_usdt_free = btc_free * btc_price_usdt
                                btc_usdt_used = btc_used * btc_price_usdt
                                
                                usdt_total += btc_usdt_total
                                usdt_free += btc_usdt_free
                                usdt_used += btc_usdt_used
                                
                                conversion_details['BTC'] = {
                                    'amount': btc_total,
                                    'price': btc_price_usdt,
                                    'usdt_value': btc_usdt_total
                                }
                        except Exception as e:
                            logger.error(f"Error converting BTC to USDT: {str(e)}")
                    
                    # Convert XRP to USDT
                    if 'XRP' in relevant_balances and relevant_balances['XRP']['total'] > 0:
                        try:
                            xrp_price_usdt = self.get_xrp_usdt_price()
                            if xrp_price_usdt:
                                xrp_total = relevant_balances['XRP']['total']
                                xrp_free = relevant_balances['XRP']['free']
                                xrp_used = relevant_balances['XRP']['used']
                                
                                xrp_usdt_total = xrp_total * xrp_price_usdt
                                xrp_usdt_free = xrp_free * xrp_price_usdt
                                xrp_usdt_used = xrp_used * xrp_price_usdt
                                
                                usdt_total += xrp_usdt_total
                                usdt_free += xrp_usdt_free
                                usdt_used += xrp_usdt_used
                                
                                conversion_details['XRP'] = {
                                    'amount': xrp_total,
                                    'price': xrp_price_usdt,
                                    'usdt_value': xrp_usdt_total
                                }
                        except Exception as e:
                            logger.error(f"Error converting XRP to USDT: {str(e)}")
                    
                    # Add USDT equivalent if we have any conversions
                    if usdt_total > 0:
                        relevant_balances['USDT'] = {
                            'free': usdt_free,
                            'used': usdt_used,
                            'total': usdt_total,
                            'conversion_details': conversion_details
                        }
                    
                    balances[exchange_name] = {
                        'status': 'authenticated',
                        'balances': relevant_balances,
                        'timestamp': datetime.now(timezone.utc)
                    }
                else:
                    balances[exchange_name] = {
                        'status': 'error',
                        'balances': {},
                        'timestamp': datetime.now(timezone.utc)
                    }
            except Exception as e:
                logger.error(f"Error getting balance for {exchange_name}: {str(e)}")
                balances[exchange_name] = {
                    'status': 'error',
                    'balances': {},
                    'timestamp': datetime.now(timezone.utc)
                }
        
        return balances
    
    def get_demo_balances(self) -> Dict[str, Dict]:
        """Return demo balances for testing without API keys"""
        import random
        
        demo_balances = {}
        exchanges = ['kraken', 'binanceus', 'okx', 'cryptocom']
        
        for exchange in exchanges:
            # Generate random demo balances
            demo_balances[exchange] = {
                'status': 'demo',
                'balances': {
                    'USDT': {
                        'free': round(random.uniform(100, 1000), 2),
                        'used': round(random.uniform(0, 100), 2),
                        'total': round(random.uniform(100, 1000), 2)
                    },
                    'XRP': {
                        'free': round(random.uniform(50, 500), 2),
                        'used': round(random.uniform(0, 50), 2),
                        'total': round(random.uniform(50, 500), 2)
                    },
                    'BTC': {
                        'free': round(random.uniform(0.01, 0.1), 4),
                        'used': round(random.uniform(0, 0.01), 4),
                        'total': round(random.uniform(0.01, 0.1), 4)
                    },
                    'ETH': {
                        'free': round(random.uniform(0.1, 1.0), 3),
                        'used': round(random.uniform(0, 0.1), 3),
                        'total': round(random.uniform(0.1, 1.0), 3)
                    }
                },
                'timestamp': datetime.now(timezone.utc)
            }
        
        return demo_balances
    
    async def get_okx_balance_rest(self) -> Optional[Dict]:
        """Get OKX balance using REST API with correct timestamp format"""
        try:
            api_key = os.getenv('OKX_API_KEY')
            api_secret = os.getenv('OKX_API_SECRET')
            passphrase = os.getenv('OKX_PASSPHRASE')
            
            if not all([api_key, api_secret, passphrase]):
                logger.error("OKX: Missing API credentials")
                return None
            
            # REST API endpoint
            request_path = '/api/v5/account/balance'
            
            # Try different regional domains (US first since we know it works)
            domains_to_try = [
                "https://us.okx.com",   # United States (confirmed working)
            ]
            
            for base_url in domains_to_try:
                try:
                    logger.info(f"OKX: Trying domain: {base_url}")
                    
                    # Get server time first to ensure correct timestamp (CRITICAL FOR OKX)
                    async with aiohttp.ClientSession() as session:
                        time_url = f"{base_url}/api/v5/public/time"
                        async with session.get(time_url) as response:
                            if response.status == 200:
                                time_data = await response.json()
                                if time_data.get('code') == '0' and 'data' in time_data and len(time_data['data']) > 0:
                                    server_time = time_data['data'][0]['ts']
                                    server_time_seconds = int(server_time) / 1000
                                    dt = datetime.fromtimestamp(server_time_seconds, tz=timezone.utc)
                                    timestamp = dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                                    logger.info(f"OKX: Using server timestamp: {timestamp}")
                                else:
                                    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                                    logger.warning("OKX: Using client timestamp")
                            else:
                                timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                                logger.warning("OKX: Using client timestamp")
                    
                    # Create signature
                    method = 'GET'
                    body = ''
                    prehash = f"{timestamp}{method}{request_path}{body}"
                    
                    signature = base64.b64encode(
                        hmac.new(
                            api_secret.encode('utf-8'),
                            prehash.encode('utf-8'),
                            hashlib.sha256
                        ).digest()
                    ).decode('utf-8')
                    
                    # Prepare headers
                    headers = {
                        'OK-ACCESS-KEY': api_key,
                        'OK-ACCESS-SIGN': signature,
                        'OK-ACCESS-TIMESTAMP': timestamp,
                        'OK-ACCESS-PASSPHRASE': passphrase,
                        'Content-Type': 'application/json'
                    }
                    
                    url = f"{base_url}{request_path}"
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, headers=headers) as response:
                            response_text = await response.text()
                            
                            if response.status == 200:
                                data = await response.json()
                                if data.get('code') == '0' and 'data' in data and len(data['data']) > 0:
                                    balance_info = data['data'][0]
                                    balances = {}
                                    
                                    if 'details' in balance_info:
                                        for detail in balance_info['details']:
                                            currency = detail['ccy']
                                            if currency not in balances:
                                                balances[currency] = {'free': 0, 'used': 0, 'total': 0}
                                            
                                            balances[currency]['total'] = float(detail['cashBal'] or 0)
                                            balances[currency]['free'] = float(detail['availBal'] or 0)
                                            balances[currency]['used'] = float(detail['frozenBal'] or 0)
                                    
                                    logger.info(f"OKX: Balance fetched successfully from {base_url}")
                                    return balances
                                else:
                                    logger.warning(f"OKX: {base_url} returned error: {data.get('msg', 'Unknown')}")
                                    continue  # Try next domain
                            elif response.status == 401 and 'API key doesn\'t exist' in response_text:
                                logger.warning(f"OKX: {base_url} - API key doesn't exist (wrong region)")
                                continue  # Try next domain
                            else:
                                logger.warning(f"OKX: {base_url} - Status {response.status}: {response_text[:100]}")
                                continue  # Try next domain
                            
                except Exception as e:
                    logger.error(f"OKX: Error trying {base_url}: {e}")
                    continue  # Try next domain
            
            logger.error("OKX: All regional domains failed")
            return None
                        
        except Exception as e:
            logger.error(f"OKX: REST API balance error: {e}")
            return None
    
    def get_btc_usdt_price(self) -> Optional[float]:
        """Get current BTC/USDT price for conversion"""
        try:
            # Try to get BTC/USDT price from Kraken if available
            if 'kraken' in self.exchanges:
                try:
                    ticker = self.exchanges['kraken'].fetch_ticker('BTC/USDT')
                    return float(ticker['last'])
                except:
                    pass
            
            # Fallback: Use a simple API call to get BTC price
            import requests
            response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd', timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data['bitcoin']['usd'])
            
            # Another fallback: Use Binance public API
            response = requests.get('https://api.binance.us/api/v3/ticker/price?symbol=BTCUSDT', timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data['price'])
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching BTC/USDT price: {str(e)}")
            return None
    
    def get_xrp_usdt_price(self) -> Optional[float]:
        """Get current XRP/USDT price for conversion"""
        try:
            # Try to get XRP/USDT price from Kraken if available
            if 'kraken' in self.exchanges:
                try:
                    ticker = self.exchanges['kraken'].fetch_ticker('XRP/USDT')
                    return float(ticker['last'])
                except:
                    pass
            
            # Fallback: Use CoinGecko API
            import requests
            response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=ripple&vs_currencies=usd', timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data['ripple']['usd'])
            
            # Another fallback: Use Binance public API
            response = requests.get('https://api.binance.us/api/v3/ticker/price?symbol=XRPUSDT', timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data['price'])
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching XRP/USDT price: {str(e)}")
            return None
    
    async def close(self):
        """Close all exchange connections"""
        for exchange in self.exchanges.values():
            if hasattr(exchange, 'close'):
                await exchange.close()
        
        if self.session:
            await self.session.close()
