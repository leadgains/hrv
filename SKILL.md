# Polymarket Penny Bot — OpenClaw Skill

AI-powered Polymarket penny trading bot. Scans for shares priced 1-9¢, uses Claude to identify mispriced opportunities, and auto-buys the best ones.

## Capabilities

### Market Scanning
- Scan all active Polymarket markets for penny-priced shares (1-9 cents)
- Show potential payout per position
- Filter by category (crypto, politics, sports, Musk tweets)

### AI Research
- Claude analyzes each penny opportunity for mispricing
- Estimates true probability vs market price
- Only recommends BUY when estimated value is 2x+ the market price
- Scores each opportunity 0-100

### Musk Tweet Strategy (Annica-style)
- Specialized module for Elon Musk tweet count markets
- Analyzes posting patterns, current news, Tesla/SpaceX events
- Picks underpriced tweet ranges and allocates budget
- Based on the strategy of top trader "Annica" ($267K profit, 84.8% win rate)

### Trading
- Auto-buys AI-recommended positions via Polymarket CLOB API
- Budget limits, daily loss limits, max per trade
- Persistent trade logging (trades.json)
- Telegram notifications for every buy

### Portfolio Monitoring
- Track all open positions
- Check which markets resolved (won/lost)
- Calculate current P&L

## Commands

### Scan for opportunities
```bash
scripts/penny.sh scan
```
Lists all penny-priced shares with payout math.

### AI research (analyze without buying)
```bash
scripts/penny.sh research
```
Claude analyzes all penny opportunities and ranks them by mispricing score.

### Run one full cycle (scan + AI + buy)
```bash
scripts/penny.sh trade
```
Scans, analyzes, and buys the top AI-recommended positions.

### Musk tweet strategy
```bash
scripts/penny.sh musk
```
Analyzes Musk tweet markets and picks the best ranges.

### Musk tweet strategy (preview only)
```bash
scripts/penny.sh musk-dry
```
Shows what Claude would pick without buying.

### Check portfolio
```bash
scripts/penny.sh portfolio
```
Shows current positions, P&L, and budget status.

### Start 24/7 bot
```bash
scripts/penny.sh start
```
Starts the bot in continuous mode. Scans every 60 seconds.

### Stop bot
```bash
scripts/penny.sh stop
```
Stops the running bot.

### Bot status
```bash
scripts/penny.sh status
```
Shows if the bot is running and recent activity.

## Configuration

Config file: `config.json` in the skill directory.

```json
{
  "polymarket_private_key": "your_wallet_private_key",
  "polymarket_funder": "your_wallet_address",
  "anthropic_api_key": "your_anthropic_api_key",
  "telegram_bot_token": "your_telegram_bot_token",
  "telegram_chat_id": "your_chat_id",
  "total_budget": 20.0,
  "max_spend_per_trade": 4.0,
  "daily_loss_limit": 5.0,
  "max_price_cents": 9,
  "min_price_cents": 1,
  "check_interval_seconds": 60
}
```

## Usage Examples

- "Scan polymarket for penny opportunities"
- "What are the cheap shares on polymarket right now?"
- "Analyze the penny markets with AI"
- "Buy the best penny positions"
- "How is Musk's tweet week looking?"
- "Run the musk tweet strategy"
- "Show my polymarket portfolio"
- "Start the penny bot"
- "Stop the penny bot"
- "How much have I spent so far?"
- "What's my P&L?"

## References

- [Polymarket CLOB API](https://docs.polymarket.com/)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
- Strategy inspired by trader [Annica](https://polymarket.com/@Annica) — $267K profit on Musk tweet markets
