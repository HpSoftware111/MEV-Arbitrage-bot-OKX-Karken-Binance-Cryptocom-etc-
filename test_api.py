"""
Test script for MEV Bot API endpoints
"""

import requests
import json
import time

def test_api_endpoints():
    """Test all API endpoints"""
    base_url = "http://localhost:8000"
    
    print("Testing MEV Bot API Endpoints")
    print("=" * 40)
    
    # Test 1: Health check
    print("\n1. Testing Health Check...")
    try:
        response = requests.get(f"{base_url}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test 2: Root endpoint
    print("\n2. Testing Root Endpoint...")
    try:
        response = requests.get(f"{base_url}/")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test 3: Current prices
    print("\n3. Testing Current Prices...")
    try:
        response = requests.get(f"{base_url}/prices")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            prices = response.json()
            print(f"Found {len(prices)} price records")
            for price in prices:
                print(f"  {price['exchange']}: ${price['last_price']:.4f}")
        else:
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test 4: Exchange status
    print("\n4. Testing Exchange Status...")
    try:
        response = requests.get(f"{base_url}/exchanges/status")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            status = response.json()
            for exchange, data in status.items():
                print(f"  {exchange}: {data['status']} - ${data['last_price']}")
        else:
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test 5: Arbitrage opportunities
    print("\n5. Testing Arbitrage Opportunities...")
    try:
        response = requests.get(f"{base_url}/arbitrage/opportunities")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            opportunities = response.json()
            print(f"Found {len(opportunities)} opportunities")
            for opp in opportunities[:3]:  # Show first 3
                print(f"  {opp['buy_exchange']} -> {opp['sell_exchange']}: {opp['profit_percentage']:.2f}%")
        else:
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test 6: Live arbitrage opportunities
    print("\n6. Testing Live Arbitrage Opportunities...")
    try:
        response = requests.get(f"{base_url}/arbitrage/opportunities/live")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Current prices: {len(data.get('current_prices', []))}")
            print(f"Opportunities: {len(data.get('opportunities', []))}")
        else:
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Test 7: Statistics
    print("\n7. Testing Statistics...")
    try:
        response = requests.get(f"{base_url}/stats")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            stats = response.json()
            print(f"Total price records: {stats['total_price_records']}")
            print(f"Total opportunities: {stats['total_arbitrage_opportunities']}")
            print(f"Profitable opportunities: {stats['profitable_opportunities']}")
            print(f"Monitoring status: {stats['monitoring_status']}")
        else:
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Make sure the MEV Bot is running on http://localhost:8000")
    print("Starting API tests in 3 seconds...")
    time.sleep(3)
    
    test_api_endpoints()
    
    print("\n" + "=" * 40)
    print("API Testing Complete!")
    print("Visit http://localhost:8000/docs for interactive API documentation")
