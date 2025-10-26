# MEV Arbitrage Bot

A sophisticated cryptocurrency arbitrage bot that monitors multiple exchanges for profitable trading opportunities.

## 🚀 Features

- **Multi-Exchange Support**: Kraken, Binance.US, OKX, Crypto.com
- **Real-Time Monitoring**: Live price tracking and arbitrage detection
- **Risk Management**: Comprehensive risk controls and safety features
- **Portfolio Management**: Balance tracking and position management
- **Advanced Analytics**: Historical data analysis and performance metrics
- **Web Dashboard**: Real-time UI with WebSocket updates
- **Paper Trading**: Safe testing mode before live trading

## 📋 Prerequisites

- Python 3.8+
- API keys from supported exchanges
- Internet connection

## 🛠️ Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd mev-bot
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API keys**:
   ```bash
   cp config.example .env
   # Edit .env with your API keys
   ```

4. **Run the bot**:
   ```bash
   python main.py
   ```

5. **Access the dashboard**:
   Open http://localhost:8001 in your browser

## ⚙️ Configuration

### Exchange Setup

**Kraken**:
- Create API key with "Query Funds" permission
- No IP whitelist required

**Binance.US** (US users only):
- Create API key with "Spot Trading" permission
- Enable IP whitelist if required

**OKX**:
- Create API key with "Read" and "Trade" permissions
- Note your passphrase

**Crypto.com**:
- Create API key with "Balance" permission
- Configure IP whitelist if required

### Bot Settings

- `TRADING_MODE`: `paper` (testing) or `live` (real trading)
- `MIN_PROFIT_THRESHOLD`: Minimum profit percentage (0.005 = 0.005%)
- `MAX_TRADE_AMOUNT`: Maximum trade size in USDT
- `MIN_VOLUME_THRESHOLD`: Minimum volume requirement

## 📊 Usage

### Starting the Bot

```bash
python main.py
```

The bot will:
- Connect to all configured exchanges
- Start monitoring XRP prices
- Detect arbitrage opportunities
- Update the web dashboard in real-time

### Web Dashboard

Access http://localhost:8001 to view:
- **Live Prices**: Current XRP prices from all exchanges
- **Arbitrage Opportunities**: Detected profitable trades
- **Current Balances**: Your account balances
- **Risk Management**: Safety metrics and controls
- **Analytics**: Performance statistics

### 2-Hour Test Mode

For comprehensive testing:
```bash
python 2hour_test.py
```

This will:
- Monitor for 2 hours continuously
- Use ultra-low threshold (0.005%)
- Log all opportunities found
- Save detailed results

## 🔧 Troubleshooting

### Common Issues

**Authentication Errors**:
- Verify API keys are correct
- Check API key permissions
- Ensure IP whitelist is configured

**Geo-Restrictions**:
- Binance.US is US-only
- Use VPN if needed
- Bot will use demo mode automatically

**No Arbitrage Opportunities**:
- Market may be very efficient
- Lower `MIN_PROFIT_THRESHOLD`
- Monitor during high volatility periods

### Exchange Status

- **Kraken**: ✅ Working
- **Binance.US**: ⚠️ Geo-restricted (demo mode)
- **OKX**: ⚠️ Requires API key
- **Crypto.com**: ⚠️ Check authentication

## 📈 Performance

### Expected Results

- **Normal Market**: 0-5 opportunities per hour
- **Volatile Market**: 5-20 opportunities per hour
- **High Volatility**: 20+ opportunities per hour

### Best Times to Monitor

- **Market Open**: 9:30 AM EST
- **Market Close**: 4:00 PM EST
- **News Events**: Economic announcements
- **Weekend**: Lower liquidity periods

## 🛡️ Safety Features

- **Paper Trading Mode**: Test without real money
- **Risk Management**: Stop-loss and position sizing
- **Daily Limits**: Maximum trade amounts
- **Emergency Stop**: Instant trading halt
- **Balance Monitoring**: Real-time account tracking

## 📁 Project Structure

```
mev-bot/
├── main.py                 # Main application
├── exchanges.py           # Exchange integrations
├── price_monitor.py      # Price monitoring
├── trading_executor.py   # Trade execution
├── portfolio_manager.py  # Portfolio management
├── analytics_engine.py   # Analytics and metrics
├── risk_manager.py       # Risk management
├── database.py           # Database models
├── templates/            # Web UI templates
├── static/              # Static assets
├── requirements.txt     # Dependencies
├── config.example       # Configuration template
└── README.md           # This file
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## ⚠️ Disclaimer

This bot is for educational purposes. Cryptocurrency trading involves significant risk. Always:
- Test in paper mode first
- Start with small amounts
- Monitor your positions
- Understand the risks
- Never invest more than you can afford to lose

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.