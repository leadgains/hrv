# Polymarket Penny Trading Reference

## What is Penny Trading?
Buying prediction market shares priced between 1-9 cents. These represent events the market considers highly unlikely (1-9% probability). If the event happens, each share pays $1 — a 10x to 100x return.

## How the Bot Works
1. **Scan** — Fetches all active Polymarket markets, filters for shares priced 1-9¢
2. **Research** — Sends opportunities to Claude for AI analysis
3. **Score** — Claude estimates true probability vs market price
4. **Buy** — Only buys shares where AI estimate is 2x+ the market price
5. **Wait** — Holds positions until market resolves
6. **Profit/Loss** — Winners pay $1/share, losers go to $0

## Musk Tweet Strategy (Annica-style)
Based on trader "Annica" who made $267K with 84.8% win rate on Musk tweet markets.

**How it works:**
- Polymarket has weekly markets: "How many tweets will Elon post?"
- Multiple ranges: 0-79, 80-159, 160-239, 240-319, etc.
- Each range trades at a price reflecting its probability
- Bot analyzes Musk's patterns + current news to predict the likely range
- Buys 3-5 adjacent ranges cheaply, ensuring coverage

**Musk's typical patterns:**
- Quiet weeks: 80-150 posts (travel, focus periods)
- Normal weeks: 150-250 posts
- Busy weeks: 300-500+ posts (political events, Tesla/SpaceX news)

## Risk Management
- **Budget limit**: Total amount the bot can spend (default $20)
- **Per-trade limit**: Max spend on any single position (default $4)
- **Daily limit**: Max loss per day (default $5)
- **No duplicate buys**: Won't buy the same position twice

## Expected Outcomes
With $20 across 5 positions:
- Most likely: 3-4 positions lose ($12-16 lost), 1-2 win ($25-100 gained)
- Best case: Multiple wins on cheap shares = 10x+ return
- Worst case: All 5 lose = $20 total loss (your full budget)

This is high-risk, high-reward. Only use money you can afford to lose.
