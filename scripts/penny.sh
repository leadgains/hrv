#!/bin/bash
# OpenClaw entry point for the Polymarket Penny Bot
# Usage: penny.sh <command>

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
PIDFILE="$BOT_DIR/.bot.pid"
LOGFILE="$BOT_DIR/penny_bot.log"

# Load config.json into env vars if it exists
if [ -f "$BOT_DIR/config.json" ]; then
    export POLYMARKET_PRIVATE_KEY=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('polymarket_private_key',''))" 2>/dev/null)
    export POLYMARKET_FUNDER=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('polymarket_funder',''))" 2>/dev/null)
    export ANTHROPIC_API_KEY=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('anthropic_api_key',''))" 2>/dev/null)
    export TELEGRAM_BOT_TOKEN=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('telegram_bot_token',''))" 2>/dev/null)
    export TELEGRAM_CHAT_ID=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('telegram_chat_id',''))" 2>/dev/null)
    export TOTAL_BUDGET=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('total_budget',20.0))" 2>/dev/null)
    export MAX_SPEND_PER_TRADE=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('max_spend_per_trade',4.0))" 2>/dev/null)
    export DAILY_LOSS_LIMIT=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('daily_loss_limit',5.0))" 2>/dev/null)
    export MAX_PRICE_CENTS=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('max_price_cents',9))" 2>/dev/null)
    export MIN_PRICE_CENTS=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('min_price_cents',1))" 2>/dev/null)
    export CHECK_INTERVAL_SECONDS=$(python3 -c "import json; print(json.load(open('$BOT_DIR/config.json')).get('check_interval_seconds',60))" 2>/dev/null)
fi

# Also load .env if it exists
if [ -f "$BOT_DIR/.env" ]; then
    set -a
    source "$BOT_DIR/.env"
    set +a
fi

CMD="${1:-help}"

case "$CMD" in
    scan)
        cd "$BOT_DIR" && python3 bot.py --scan
        ;;
    research)
        cd "$BOT_DIR" && python3 bot.py --research
        ;;
    trade)
        cd "$BOT_DIR" && python3 bot.py --once
        ;;
    musk)
        cd "$BOT_DIR" && python3 bot.py --musk
        ;;
    musk-dry)
        cd "$BOT_DIR" && python3 bot.py --musk --dry
        ;;
    portfolio)
        cd "$BOT_DIR" && python3 -c "
from trader import Trader
from config import Config
config = Config()
trader = Trader(config=config, client=None)
print(trader.get_summary())
if trader.trades:
    print()
    for t in trader.trades[-10:]:
        icon = {'open': '⏳', 'won': '✅', 'lost': '❌'}.get(t.status, '❓')
        print(f'  {icon} {t.outcome} @ {t.price*100:.1f}¢ — \${t.amount:.2f} — {t.market[:60]}')
"
        ;;
    start)
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "Bot is already running (PID: $(cat "$PIDFILE"))"
        else
            cd "$BOT_DIR" && nohup python3 bot.py > "$LOGFILE" 2>&1 &
            echo $! > "$PIDFILE"
            echo "Bot started (PID: $!)"
            echo "Logs: $LOGFILE"
        fi
        ;;
    stop)
        if [ -f "$PIDFILE" ]; then
            PID=$(cat "$PIDFILE")
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID"
                rm "$PIDFILE"
                echo "Bot stopped (PID: $PID)"
            else
                rm "$PIDFILE"
                echo "Bot was not running (stale PID file removed)"
            fi
        else
            echo "Bot is not running"
        fi
        ;;
    status)
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "Bot is RUNNING (PID: $(cat "$PIDFILE"))"
            echo ""
            echo "Last 10 log lines:"
            tail -10 "$LOGFILE" 2>/dev/null || echo "No logs yet"
        else
            echo "Bot is STOPPED"
        fi
        ;;
    help|*)
        echo "Polymarket Penny Bot — Commands:"
        echo "  scan       — List penny-priced shares"
        echo "  research   — AI analysis of opportunities"
        echo "  trade      — Run one full cycle (scan + AI + buy)"
        echo "  musk       — Musk tweet strategy (buy)"
        echo "  musk-dry   — Musk tweet strategy (preview)"
        echo "  portfolio  — Show positions and P&L"
        echo "  start      — Start 24/7 bot"
        echo "  stop       — Stop the bot"
        echo "  status     — Check if bot is running"
        ;;
esac
