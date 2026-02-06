# Polymarket Penny Bot — OpenClaw Skill

AI-powered Polymarket penny trading bot. Scans for shares priced 1-9c, tracks Elon Musk's real-time tweet activity, uses Claude to find mispriced opportunities, and auto-trades the best ones.

## Capabilities

### Market Scanning
- Scan all active Polymarket markets for penny-priced shares (1-9 cents)
- Show potential payout per position
- Filter by category (crypto, politics, sports, Musk tweets)

### AI Research
- Claude analyzes each penny opportunity for mispricing
- Estimates true probability vs market price
- Only recommends BUY when estimated value is 2x+ the market price
- Learns from past trades and feeds insights back into future picks

### Musk Tweet Strategy (Real-Time)
- Tracks Elon Musk's actual posting activity via fxtwitter/nitter
- Calculates posting speed (tweets/hour) and projects weekly total
- Finds tweet-count ranges the market is underpricing
- AI validates picks using news context + real tweet data
- Falls back to pure math projection if no AI key

### Trade Analysis (Self-Improving)
- AI reviews every trade on open and close
- Tracks patterns: what works, what doesn't
- Accumulates learnings in trade_learnings.json
- Feeds past insights into future research prompts

### 3-Strategy Race (Paper Trading)
- Strategy 1: All Penny with AI picks
- Strategy 2: Musk Tweets Only (real tweet data)
- Strategy 3: Blind (cheapest first, no AI)
- Each gets $100 virtual, best P&L wins
- Live web dashboard at localhost:8888

### Portfolio Monitoring
- Track all open positions
- Check which markets resolved (won/lost)
- Calculate current P&L

## Commands

### Start Telegram bot (recommended)
```bash
scripts/penny.sh telegram
```
Control everything via Telegram — /scan, /research, /musk, /tweets, /portfolio, /report, /start, /stop.

### Start dashboard
```bash
scripts/penny.sh dashboard
```
Web dashboard at localhost:8888 — shows strategies, tweet tracker, AI analysis.

### Scan for opportunities
```bash
scripts/penny.sh scan
```

### AI research (analyze without buying)
```bash
scripts/penny.sh research
```

### Run one full cycle (scan + AI + buy)
```bash
scripts/penny.sh trade
```

### Musk tweet tracker
```bash
scripts/penny.sh tweets
```
Shows Musk's current posting speed, projected weekly total, activity level.

### Musk tweet strategy
```bash
scripts/penny.sh musk
```

### Check portfolio
```bash
scripts/penny.sh portfolio
```

### Trade analysis report
```bash
scripts/penny.sh report
```
Shows accumulated AI learnings and strategy performance.

### Start 24/7 bot
```bash
scripts/penny.sh start
```

### Stop bot
```bash
scripts/penny.sh stop
```

### Bot status
```bash
scripts/penny.sh status
```

## Configuration

Set via `.env` file or `config.json`:

```
POLYMARKET_PRIVATE_KEY=your_wallet_private_key
POLYMARKET_FUNDER=your_wallet_address
ANTHROPIC_API_KEY=your_anthropic_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TOTAL_BUDGET=100.0
MAX_SPEND_PER_TRADE=5.0
DAILY_LOSS_LIMIT=20.0
CHECK_INTERVAL_SECONDS=60
```

### Start Telegram bot
```bash
scripts/penny.sh telegram
```
Or directly: `python3 telegram_bot.py`

## Quick Start (Telegram)

1. Set your `TELEGRAM_BOT_TOKEN` in `.env` (get from @BotFather)
2. Set your `TELEGRAM_CHAT_ID` in `.env`
3. Run: `scripts/penny.sh telegram`
4. Send `/help` to your bot on Telegram
5. Send `/start` to begin auto-trading

## Usage Examples

- "Start the Telegram bot"
- "Start the dashboard"
- "Scan polymarket for penny opportunities"
- "How many tweets has Musk posted this week?"
- "Analyze the penny markets with AI"
- "Run the musk tweet strategy"
- "Show my portfolio"
- "Show the trade analysis report"
- "Start the penny bot"
