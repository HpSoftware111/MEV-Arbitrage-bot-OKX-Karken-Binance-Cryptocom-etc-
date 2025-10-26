# MEV Bot - XRP Price Monitor

A FastAPI-based real-time XRP price monitoring system that tracks prices across multiple exchanges and detects arbitrage opportunities.

## Features

- **Real-time Price Monitoring**: Tracks XRP prices across OKX, Kraken, Binance, and Crypto.com
- **Arbitrage Detection**: Automatically detects profitable arbitrage opportunities
- **REST API**: FastAPI-based API for accessing price data and opportunities
- **SQLite Database**: Stores historical price data and arbitrage opportunities
- **Exchange Authentication**: Supports API authentication for all major exchanges

## Exchanges Supported

- **Kraken** - Primary exchange with reliable API
- **OKX** - Global exchange with good liquidity
- **Binance** - Largest exchange (may be geo-restricted)
- **Crypto.com** - Popular exchange with competitive fees

## Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd mev-bot
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set up environment variables**
```bash
cp env_example.txt .env
# Edit .env with your API credentials
```

4. **Configure API Keys**
Edit the `.env` file with your exchange API credentials:
```env
KRAKEN_API_KEY=your_kraken_api_key_here
KRAKEN_API_SECRET=your_kraken_api_secret_here

OKX_API_KEY=your_okx_api_key_here
OKX_API_SECRET=your_okx_api_secret_here
OKX_PASSPHRASE=your_okx_passphrase_here

BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_api_secret_here

CRYPTO_COM_API_KEY=your_crypto_com_api_key_here
CRYPTO_COM_API_SECRET=your_crypto_com_api_secret_here
```

## Usage

### Start the Bot
```bash
python start.py
```

The bot will start on `http://localhost:8000`

### API Endpoints

#### Get Current Prices
```bash
GET /prices
```

#### Get Arbitrage Opportunities
```bash
GET /arbitrage/opportunities?limit=10&min_profit=0.1
```

#### Get Live Arbitrage Opportunities
```bash
GET /arbitrage/opportunities/live
```

#### Get Exchange Status
```bash
GET /exchanges/status
```

#### Get Statistics
```bash
GET /stats
```

#### Control Monitoring
```bash
POST /monitor/start
POST /monitor/stop
```

### Example API Response

#### Current Prices
```json
[
  {
    "exchange": "kraken",
    "symbol": "XRP/USDT",
    "bid_price": 2.6047,
    "ask_price": 2.6048,
    "last_price": 2.6047,
    "volume": 1234567.89,
    "timestamp": "2024-01-15T10:30:00Z"
  }
]
```

#### Arbitrage Opportunities
```json
[
  {
    "id": 1,
    "symbol": "XRP/USDT",
    "buy_exchange": "kraken",
    "sell_exchange": "okx",
    "buy_price": 2.6047,
    "sell_price": 2.6052,
    "profit_amount": 0.0005,
    "profit_percentage": 0.019,
    "volume": 1000.0,
    "timestamp": "2024-01-15T10:30:00Z",
    "is_executed": false
  }
]
```

## Database Schema

### PriceData Table
- `id`: Primary key
- `exchange`: Exchange name
- `symbol`: Trading pair (XRP/USDT)
- `bid_price`: Best bid price
- `ask_price`: Best ask price
- `last_price`: Last traded price
- `volume`: 24h volume
- `timestamp`: Price timestamp

### ArbitrageOpportunity Table
- `id`: Primary key
- `symbol`: Trading pair
- `buy_exchange`: Exchange to buy from
- `sell_exchange`: Exchange to sell to
- `buy_price`: Buy price
- `sell_price`: Sell price
- `profit_amount`: Profit in USDT
- `profit_percentage`: Profit percentage
- `volume`: Available volume
- `timestamp`: Opportunity timestamp
- `is_executed`: Execution status

## Configuration

### Environment Variables
- `DATABASE_URL`: SQLite database URL
- `DEBUG`: Debug mode (True/False)
- `LOG_LEVEL`: Logging level (INFO, DEBUG, etc.)

### Exchange API Setup
1. **Kraken**: https://www.kraken.com/u/security/api
2. **OKX**: https://www.okx.com/account/my-api
3. **Binance**: https://www.binance.com/en/my/settings/api-management
4. **Crypto.com**: https://crypto.com/exchange/user/settings/api

## Monitoring

The bot monitors XRP prices every second and:
1. Fetches current prices from all exchanges
2. Stores price data in SQLite database
3. Calculates arbitrage opportunities
4. Stores profitable opportunities (>0.1%)

## API Documentation

Once the bot is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Troubleshooting

### Common Issues

1. **Exchange API Errors**
   - Check API credentials in `.env` file
   - Verify API permissions (read-only for monitoring)
   - Check if exchange is geo-restricted

2. **Database Errors**
   - Ensure SQLite database file is writable
   - Check database permissions

3. **No Price Data**
   - Verify internet connection
   - Check exchange API status
   - Review logs for error messages

### Logs
Check the console output for detailed logs and error messages.

## Development

### Project Structure
```
mev-bot/
├── main.py              # FastAPI application
├── start.py             # Startup script
├── database.py          # Database models and configuration
├── exchanges.py         # Exchange API management
├── price_monitor.py     # Price monitoring service
├── requirements.txt     # Python dependencies
├── env_example.txt      # Environment variables template
└── README.md           # This file
```

### Adding New Exchanges
1. Add exchange configuration in `exchanges.py`
2. Update `price_monitor.py` to include new exchange
3. Add API credentials to `.env` file

## License

This project is for educational purposes. Use at your own risk.

## Disclaimer

Cryptocurrency trading involves substantial risk. This bot is for monitoring purposes only. Always do your own research and never invest more than you can afford to lose.
