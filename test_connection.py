"""
Test network connectivity to exchanges
"""

import asyncio
import aiohttp
import requests
from datetime import datetime

async def test_kraken_connection():
    """Test Kraken API connectivity"""
    print("Testing Kraken API connection...")
    
    try:
        # Test with requests first
        url = "https://api.kraken.com/0/public/Ticker?pair=XRPUSDT"
        response = requests.get(url, timeout=10)
        print(f"Requests: Status {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Kraken data: {data}")
            return True
    except Exception as e:
        print(f"Requests error: {e}")
    
    try:
        # Test with aiohttp
        async with aiohttp.ClientSession() as session:
            url = "https://api.kraken.com/0/public/Ticker?pair=XRPUSDT"
            async with session.get(url, timeout=10) as response:
                print(f"Aiohttp: Status {response.status}")
                if response.status == 200:
                    data = await response.json()
                    print(f"Kraken data: {data}")
                    return True
    except Exception as e:
        print(f"Aiohttp error: {e}")
    
    return False

async def test_okx_connection():
    """Test OKX API connectivity"""
    print("\nTesting OKX API connection...")
    
    try:
        url = "https://www.okx.com/api/v5/market/ticker?instId=XRP-USDT"
        response = requests.get(url, timeout=10)
        print(f"OKX Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"OKX data: {data}")
            return True
    except Exception as e:
        print(f"OKX error: {e}")
    
    return False

async def test_binance_connection():
    """Test Binance API connectivity"""
    print("\nTesting Binance API connection...")
    
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr?symbol=XRPUSDT"
        response = requests.get(url, timeout=10)
        print(f"Binance Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Binance data: {data}")
            return True
    except Exception as e:
        print(f"Binance error: {e}")
    
    return False

async def main():
    """Test all exchange connections"""
    print("=" * 50)
    print("Testing Exchange API Connections")
    print("=" * 50)
    
    results = {}
    
    results['kraken'] = await test_kraken_connection()
    results['okx'] = await test_okx_connection()
    results['binance'] = await test_binance_connection()
    
    print("\n" + "=" * 50)
    print("Connection Results:")
    print("=" * 50)
    
    for exchange, success in results.items():
        status = "WORKING" if success else "FAILED"
        print(f"{exchange.upper()}: {status}")
    
    working_exchanges = [ex for ex, success in results.items() if success]
    
    if working_exchanges:
        print(f"\nWorking exchanges: {', '.join(working_exchanges)}")
        print("You can use these exchanges in your MEV bot.")
    else:
        print("\nNo exchanges are working. Check your internet connection.")
        print("This might be due to:")
        print("- Network restrictions")
        print("- Firewall blocking HTTPS requests")
        print("- DNS resolution issues")
        print("- Exchange API maintenance")

if __name__ == "__main__":
    asyncio.run(main())
