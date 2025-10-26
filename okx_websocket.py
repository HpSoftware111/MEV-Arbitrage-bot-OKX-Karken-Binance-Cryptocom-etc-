"""
OKX WebSocket Integration for Real-time Price and Balance Data
"""

import asyncio
import json
import hmac
import hashlib
import base64
import logging
import websockets
from datetime import datetime, timezone
from typing import Dict, Optional, Callable
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class OKXWebSocketClient:
    """OKX WebSocket client for real-time data"""
    
    def __init__(self):
        self.api_key = os.getenv('OKX_API_KEY')
        self.api_secret = os.getenv('OKX_API_SECRET')
        self.passphrase = os.getenv('OKX_PASSPHRASE')
        # Using US region (confirmed working)
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/private"  # Private WebSocket (shared domain)
        self.public_ws_url = "wss://ws.okx.com:8443/ws/v5/public"  # Public WebSocket (shared domain)
        self.rest_url = "https://us.okx.com"  # US region for REST API
        self.websocket = None
        self.authenticated = False
        self.price_callbacks = []
        self.balance_callbacks = []
        
    def generate_signature(self, timestamp: str) -> str:
        """Generate OKX WebSocket signature
        
        Args:
            timestamp: Unix Epoch time in seconds (e.g., '1704876947')
        
        Returns:
            Base64-encoded HMAC SHA256 signature
        """
        try:
            # OKX WebSocket signature format: timestamp + 'GET' + '/users/self/verify'
            message = f"{timestamp}GET/users/self/verify"
            signature = base64.b64encode(
                hmac.new(
                    self.api_secret.encode('utf-8'),
                    message.encode('utf-8'),
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')
            return signature
        except Exception as e:
            logger.error(f"Error generating signature: {e}")
            return ""
    
    async def authenticate(self):
        """Authenticate with OKX WebSocket
        
        OKX WebSocket authentication requires:
        - timestamp: Unix Epoch time in seconds (e.g., '1704876947')
        - method: Always 'GET'
        - requestPath: Always '/users/self/verify'
        - sign: HMAC SHA256 signature of timestamp + method + requestPath
        """
        try:
            # Generate Unix timestamp in seconds (not milliseconds)
            timestamp = str(int(datetime.now(timezone.utc).timestamp()))
            signature = self.generate_signature(timestamp)
            
            logger.info(f"OKX: Generating WebSocket signature for timestamp: {timestamp}")
            
            auth_message = {
                "op": "login",
                "args": [
                    {
                        "apiKey": self.api_key,
                        "passphrase": self.passphrase,
                        "timestamp": timestamp,
                        "sign": signature
                    }
                ]
            }
            
            await self.websocket.send(json.dumps(auth_message))
            logger.info(f"OKX: WebSocket authentication sent (timestamp: {timestamp}, signature: {signature[:20]}...)")
            
            return timestamp
            
        except Exception as e:
            logger.error(f"OKX: WebSocket authentication error: {e}")
            return None
    
    async def subscribe_to_prices(self):
        """Subscribe to XRP-USDT ticker updates"""
        try:
            subscribe_message = {
                "op": "subscribe",
                "args": [{"channel": "tickers", "instId": "XRP-USDT"}]
            }
            
            await self.websocket.send(json.dumps(subscribe_message))
            logger.info("OKX: Subscribed to XRP-USDT ticker")
            
        except Exception as e:
            logger.error(f"OKX: Subscription error: {e}")
    
    async def subscribe_to_balance(self):
        """Subscribe to account balance updates"""
        try:
            subscribe_message = {
                "op": "subscribe",
                "args": [{"channel": "account", "instType": "SPOT"}]
            }
            
            await self.websocket.send(json.dumps(subscribe_message))
            logger.info("OKX: Subscribed to account balance")
            
        except Exception as e:
            logger.error(f"OKX: Balance subscription error: {e}")
    
    async def connect_and_listen(self):
        """Connect to OKX WebSocket and listen for updates"""
        try:
            logger.info("OKX: Connecting to WebSocket...")
            
            async with websockets.connect(self.ws_url) as websocket:
                self.websocket = websocket
                logger.info("OKX: WebSocket connected")
                
                # Authenticate
                await self.authenticate()
                
                # Wait for authentication response
                auth_response = await websocket.recv()
                auth_data = json.loads(auth_response)
                logger.info(f"OKX: Auth response: {auth_data}")
                
                if auth_data.get('event') == 'login' and auth_data.get('code') == '0':
                    self.authenticated = True
                    logger.info("OKX: WebSocket authenticated successfully!")
                    
                    # Subscribe to data
                    await self.subscribe_to_prices()
                    await self.subscribe_to_balance()
                    
                    # Listen for updates
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            await self.handle_message(data)
                        except Exception as e:
                            logger.error(f"OKX: Error processing message: {e}")
                else:
                    logger.error(f"OKX: Authentication failed: {auth_data}")
                    
        except Exception as e:
            logger.error(f"OKX: WebSocket connection error: {e}")
    
    async def handle_message(self, data: Dict):
        """Handle incoming WebSocket messages"""
        try:
            # Handle ticker updates
            if 'data' in data and 'arg' in data:
                arg = data['arg']
                
                if arg.get('channel') == 'tickers':
                    # Price update
                    for callback in self.price_callbacks:
                        await callback(data)
                
                elif arg.get('channel') == 'account':
                    # Balance update
                    for callback in self.balance_callbacks:
                        await callback(data)
                        
        except Exception as e:
            logger.error(f"OKX: Error handling message: {e}")
    
    def add_price_callback(self, callback: Callable):
        """Add callback for price updates"""
        self.price_callbacks.append(callback)
    
    def add_balance_callback(self, callback: Callable):
        """Add callback for balance updates"""
        self.balance_callbacks.append(callback)
    
    async def get_public_price(self) -> Optional[Dict]:
        """Get XRP price from public WebSocket"""
        try:
            async with websockets.connect(self.public_ws_url) as ws:
                # Subscribe to public ticker
                subscribe = {
                    "op": "subscribe",
                    "args": [{"channel": "tickers", "instId": "XRP-USDT"}]
                }
                await ws.send(json.dumps(subscribe))
                
                # Wait for initial snapshot
                while True:
                    message = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(message)
                    
                    if 'data' in data and len(data['data']) > 0:
                        ticker = data['data'][0]
                        return {
                            'exchange': 'okx',
                            'symbol': 'XRPUSDT',
                            'bid': float(ticker.get('bidPx', 0)),
                            'ask': float(ticker.get('askPx', 0)),
                            'last': float(ticker.get('last', 0)),
                            'volume': float(ticker.get('vol24h', 0)),
                            'timestamp': datetime.now(timezone.utc)
                        }
                        
        except Exception as e:
            logger.error(f"OKX: Public WebSocket error: {e}")
            return None

# Global instance
okx_ws_client: Optional[OKXWebSocketClient] = None

def get_okx_websocket_client() -> OKXWebSocketClient:
    """Get or create OKX WebSocket client instance"""
    global okx_ws_client
    if okx_ws_client is None:
        okx_ws_client = OKXWebSocketClient()
    return okx_ws_client
