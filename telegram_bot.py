"""Standalone Telegram bot for the Polymarket Penny Bot.

Run directly — no OpenClaw needed:
    python3 telegram_bot.py

Control everything via Telegram:
    /scan      — List penny-priced shares
    /research  — AI analysis of opportunities
    /musk      — Musk tweet strategy
    /tweets    — Show Musk's live tweet activity
    /portfolio — Show positions and P&L
    /report    — AI trade analysis report
    /start     — Start auto-trading loop
    /stop      — Stop auto-trading loop
    /status    — Check bot status
    /help      — Show commands
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from config import Config

try:
    from telegram import Update, BotCommand
    from telegram.ext import Application, CommandHandler, ContextTypes
except ImportError:
    print("Install python-telegram-bot: pip install python-telegram-bot")
    raise

try:
    from scanner import scan_for_pennies, PennyOpportunity
    from researcher import research_opportunities, format_research_for_telegram
    from musk_analyzer import fetch_musk_tweet_markets, analyze_musk_markets, format_musk_analysis_telegram
    from tweet_tracker import fetch_musk_tweets, count_tweets_this_week, get_musk_activity_summary
    from trade_analyzer import get_strategy_report, get_learnings_summary
    from paper_trader import PaperTrader
except ImportError as e:
    print(f"Missing module: {e}")
    raise

try:
    from py_clob_client.client import ClobClient
except ImportError:
    ClobClient = None

log = logging.getLogger(__name__)

# Bot state
_auto_trading = False
_auto_thread = None
_config = Config()
_last_scan_time = None
_cached_opps = []


def _get_client():
    """Get a Polymarket CLOB client."""
    if ClobClient is None:
        return None
    return ClobClient(_config.clob_url)


def _truncate(text: str, limit: int = 4000) -> str:
    """Truncate text to fit Telegram message limit."""
    if len(text) <= limit:
        return text
    return text[:limit - 20] + "\n\n... (truncated)"


# ── Command handlers ──────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available commands."""
    await update.message.reply_text(
        "<b>Polymarket Penny Bot</b>\n\n"
        "/scan — List penny-priced shares\n"
        "/research — AI analysis of opportunities\n"
        "/musk — Musk tweet strategy (picks)\n"
        "/muskdry — Musk strategy (preview only)\n"
        "/tweets — Musk's live tweet activity\n"
        "/portfolio — Show positions & P&L\n"
        "/report — AI trade analysis report\n"
        "/start — Start auto-trading loop\n"
        "/stop — Stop auto-trading loop\n"
        "/status — Check bot status\n"
        "/help — This message\n\n"
        f"Budget: ${_config.total_budget:.0f} | "
        f"Per trade: ${_config.max_spend_per_trade:.0f} | "
        f"Daily limit: ${_config.daily_loss_limit:.0f}",
        parse_mode="HTML",
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan for penny-priced shares."""
    global _cached_opps, _last_scan_time
    await update.message.reply_text("Scanning Polymarket for penny shares...")

    client = _get_client()
    if client is None:
        await update.message.reply_text(
            "py-clob-client not installed.\n"
            "Run: pip install py-clob-client"
        )
        return

    try:
        opps = scan_for_pennies(client, _config.min_price_cents, _config.max_price_cents)
        _cached_opps = opps
        _last_scan_time = datetime.now()
    except Exception as e:
        await update.message.reply_text(f"Scan failed: {e}")
        return

    if not opps:
        await update.message.reply_text("No penny shares found right now.")
        return

    musk_count = sum(1 for o in opps if any(
        kw in o.market_question.lower() for kw in ["musk", "elon", "tweet"]
    ))

    msg = f"<b>Penny Scan Results</b>\n"
    msg += f"Found: {len(opps)} shares | {musk_count} Musk-related\n\n"

    for o in opps[:20]:
        potential = 1.0 / o.price if o.price > 0 else 0
        musk_tag = " [M]" if any(kw in o.market_question.lower() for kw in ["musk", "elon", "tweet"]) else ""
        msg += (
            f"• {o.outcome}{musk_tag} @ {o.price*100:.1f}c"
            f" → ${_config.max_spend_per_trade * potential:.0f} potential\n"
            f"  <i>{o.market_question[:60]}</i>\n"
        )

    msg += f"\n{len(opps) - 20} more..." if len(opps) > 20 else ""
    await update.message.reply_text(_truncate(msg), parse_mode="HTML")


async def cmd_research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI analysis of penny opportunities."""
    await update.message.reply_text("Running AI research on penny markets...")

    client = _get_client()
    if client is None:
        await update.message.reply_text("py-clob-client not installed.")
        return

    try:
        opps = scan_for_pennies(client, _config.min_price_cents, _config.max_price_cents)
        if not opps:
            await update.message.reply_text("No penny shares to analyze.")
            return

        results = research_opportunities(opps[:15], batch_size=15)
        msg = format_research_for_telegram(results, top_n=5)
        await update.message.reply_text(_truncate(msg), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Research failed: {e}")


async def cmd_musk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Musk tweet strategy — find underpriced tweet markets."""
    await update.message.reply_text("Analyzing Musk tweet markets with real tweet data...")

    client = _get_client()
    if client is None:
        await update.message.reply_text("py-clob-client not installed.")
        return

    try:
        musk_opps = fetch_musk_tweet_markets(client)
        if not musk_opps:
            await update.message.reply_text("No Musk tweet markets found on Polymarket.")
            return

        results = analyze_musk_markets(musk_opps, budget=_config.total_budget)
        msg = format_musk_analysis_telegram(results)
        await update.message.reply_text(_truncate(msg), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Musk analysis failed: {e}")


async def cmd_muskdry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Musk strategy preview (no buying)."""
    await cmd_musk(update, context)


async def cmd_tweets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show Musk's live tweet activity."""
    await update.message.reply_text("Fetching Musk's tweet activity...")

    try:
        summary = get_musk_activity_summary()
        tweets = fetch_musk_tweets()
        stats = count_tweets_this_week(tweets) if tweets else {}

        speed = stats.get("posting_speed_per_hour", 0)
        if speed > 5:
            level = "STORM"
        elif speed > 3:
            level = "ACTIVE"
        elif speed > 1.5:
            level = "NORMAL"
        elif speed > 0.5:
            level = "QUIET"
        else:
            level = "SILENT"

        msg = f"<b>Musk Tweet Tracker (LIVE)</b>\n\n"
        if stats:
            msg += (
                f"This week: {stats.get('tweets_this_week', '?')} tweets\n"
                f"Today: {stats.get('tweets_today', '?')} tweets\n"
                f"Speed: {speed:.1f} tweets/hour\n"
                f"Activity: {level}\n"
                f"Projected total: {stats.get('projected_weekly_total', '?')}\n"
                f"Range: {stats.get('projected_range', '?')}\n"
                f"Hours left: {stats.get('hours_remaining', 0):.0f}h\n"
            )
        else:
            msg += summary

        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Tweet fetch failed: {e}")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show portfolio positions and P&L."""
    try:
        from paper_trader import PAPER_FILE
        p = Path(PAPER_FILE)
        if not p.exists():
            # Check strategy files
            files = ["paper_penny_all.json", "paper_penny_musk.json", "paper_penny_blind.json"]
            msg = "<b>Portfolio — Strategy Race</b>\n\n"
            for f in files:
                fp = Path(f)
                if fp.exists():
                    data = json.loads(fp.read_text())
                    trades = data.get("trades", [])
                    spent = data.get("total_spent", 0)
                    payout = data.get("total_payout", 0)
                    pnl = payout - spent
                    open_t = len([t for t in trades if t.get("status") == "open"])
                    won_t = len([t for t in trades if t.get("status") == "won"])
                    lost_t = len([t for t in trades if t.get("status") == "lost"])

                    name = f.replace("paper_penny_", "").replace(".json", "").upper()
                    msg += (
                        f"<b>{name}</b>\n"
                        f"  Spent: ${spent:.2f} | P&L: ${pnl:+.2f}\n"
                        f"  Positions: {open_t} open / {won_t}W / {lost_t}L\n\n"
                    )

                    for t in trades[-5:]:
                        icon = {"open": "⏳", "won": "✅", "lost": "❌"}.get(t.get("status", ""), "?")
                        msg += f"  {icon} {t['outcome']} @ {t['buy_price']*100:.1f}c → {t['current_price']*100:.1f}c — {t['market'][:40]}\n"
                    msg += "\n"
            if msg == "<b>Portfolio — Strategy Race</b>\n\n":
                msg += "No trades yet. Use /start to begin auto-trading."
            await update.message.reply_text(_truncate(msg), parse_mode="HTML")
        else:
            data = json.loads(p.read_text())
            trades = data.get("trades", [])
            spent = data.get("total_spent", 0)
            payout = data.get("total_payout", 0)
            pnl = payout - spent

            msg = f"<b>Portfolio</b>\n"
            msg += f"Spent: ${spent:.2f} | Payout: ${payout:.2f} | P&L: ${pnl:+.2f}\n\n"

            for t in trades[-10:]:
                icon = {"open": "⏳", "won": "✅", "lost": "❌"}.get(t.get("status", ""), "?")
                msg += f"{icon} {t['outcome']} @ {t['buy_price']*100:.1f}c → {t['current_price']*100:.1f}c ${t['amount']:.2f}\n  {t['market'][:50]}\n\n"

            if not trades:
                msg += "No trades yet."
            await update.message.reply_text(_truncate(msg), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Portfolio error: {e}")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI trade analysis report."""
    try:
        report = get_strategy_report()
        if report:
            await update.message.reply_text(
                f"<b>Trade Analysis Report</b>\n\n<pre>{_truncate(report, 3800)}</pre>",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("No trade analysis data yet. Start trading first.")
    except Exception as e:
        await update.message.reply_text(f"Report error: {e}")


async def cmd_start_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the auto-trading loop."""
    global _auto_trading, _auto_thread

    if _auto_trading:
        await update.message.reply_text("Auto-trading is already running! Use /stop to stop.")
        return

    _auto_trading = True

    def _loop():
        global _auto_trading
        from dashboard import scan_and_trade
        config = Config()
        while _auto_trading:
            try:
                # Run one cycle from dashboard's scan_and_trade logic
                _run_one_cycle(config, context.application)
            except Exception as e:
                log.error(f"Auto-trade cycle error: {e}")
            time.sleep(config.check_interval)

    _auto_thread = threading.Thread(target=_loop, daemon=True)
    _auto_thread.start()

    await update.message.reply_text(
        "<b>Auto-trading STARTED</b>\n\n"
        f"Scanning every {_config.check_interval}s\n"
        f"Budget: ${_config.total_budget:.0f}\n"
        f"Per trade: ${_config.max_spend_per_trade:.0f}\n"
        "3 strategies racing: AI picks, Musk-only, Blind\n\n"
        "Use /stop to stop, /status to check",
        parse_mode="HTML",
    )


def _run_one_cycle(config, app):
    """Run one scan+trade cycle and send Telegram notifications for new trades."""
    global _cached_opps, _last_scan_time

    # Tweet tracking
    try:
        tweets = fetch_musk_tweets()
        if tweets:
            stats = count_tweets_this_week(tweets)
    except Exception:
        pass

    if ClobClient is None:
        return

    client = ClobClient(config.clob_url)

    try:
        opps = scan_for_pennies(client, config.min_price_cents, config.max_price_cents)
        _cached_opps = opps
        _last_scan_time = datetime.now()
    except Exception as e:
        log.error(f"Scan failed: {e}")
        return

    # Load strategy files
    strategies = {
        "penny_all": {"file": "paper_penny_all.json", "trades": [], "spent": 0, "payout": 0},
        "penny_musk": {"file": "paper_penny_musk.json", "trades": [], "spent": 0, "payout": 0},
        "penny_blind": {"file": "paper_penny_blind.json", "trades": [], "spent": 0, "payout": 0},
    }

    for key, s in strategies.items():
        fp = Path(s["file"])
        if fp.exists():
            data = json.loads(fp.read_text())
            s["trades"] = data.get("trades", [])
            s["spent"] = data.get("total_spent", 0)
            s["payout"] = data.get("total_payout", 0)

    max_per = config.max_spend_per_trade
    new_trades = []

    # Strategy 1: AI picks
    if opps:
        bought = {t["token_id"] for t in strategies["penny_all"]["trades"]}
        new_opps = [o for o in opps if o.token_id not in bought]
        if new_opps:
            results = research_opportunities(new_opps[:15], batch_size=15)
            buys = [r for r in results if r.recommendation == "BUY"]
            buys.sort(key=lambda r: r.score, reverse=True)
            for r in buys[:5]:
                if _paper_buy(strategies["penny_all"], r.opportunity, max_per):
                    new_trades.append(("AI", r.opportunity, r.reasoning[:80]))

    # Strategy 2: Musk
    musk_opps = [o for o in opps if any(
        kw in o.market_question.lower() for kw in ["musk", "elon", "tweet"]
    )]
    if musk_opps:
        picks = analyze_musk_markets(musk_opps, budget=100 - strategies["penny_musk"]["spent"])
        for pick in picks:
            opp = pick["opportunity"]
            if _paper_buy(strategies["penny_musk"], opp, min(pick["amount"], max_per)):
                new_trades.append(("MUSK", opp, pick.get("reasoning", "")[:80]))

    # Strategy 3: Blind
    if opps:
        sorted_opps = sorted(opps, key=lambda o: o.price)
        for opp in sorted_opps[:5]:
            if _paper_buy(strategies["penny_blind"], opp, max_per):
                new_trades.append(("BLIND", opp, "cheapest available"))

    # Save strategies
    for key, s in strategies.items():
        _save_strat(s)

    # Send notification for new trades
    if new_trades and app and _config.telegram_chat_id:
        msg = f"<b>New Trades ({len(new_trades)})</b>\n\n"
        for strat, opp, reason in new_trades:
            potential = _config.max_spend_per_trade / opp.price if opp.price > 0 else 0
            msg += (
                f"[{strat}] {opp.outcome} @ {opp.price*100:.1f}c\n"
                f"  {opp.market_question[:50]}\n"
                f"  Potential: ${potential:.0f} | {reason}\n\n"
            )
        try:
            asyncio.run_coroutine_threadsafe(
                app.bot.send_message(
                    chat_id=_config.telegram_chat_id,
                    text=_truncate(msg),
                    parse_mode="HTML",
                ),
                app.loop if hasattr(app, 'loop') else asyncio.get_event_loop(),
            )
        except Exception as e:
            log.debug(f"Notification send failed: {e}")


def _paper_buy(strategy, opp, amount):
    """Record a paper trade."""
    bought = {t["token_id"] for t in strategy["trades"]}
    if opp.token_id in bought:
        return False
    if strategy["spent"] + amount > 100:
        return False

    shares = amount / opp.price if opp.price > 0 else 0
    trade = {
        "timestamp": datetime.utcnow().isoformat(),
        "market": opp.market_question,
        "market_slug": opp.market_slug,
        "outcome": opp.outcome,
        "token_id": opp.token_id,
        "condition_id": opp.condition_id,
        "buy_price": opp.price,
        "amount": amount,
        "shares": shares,
        "current_price": opp.price,
        "status": "open",
        "resolved_at": "",
        "payout": 0,
    }
    strategy["trades"].append(trade)
    strategy["spent"] += amount
    _save_strat(strategy)
    return True


def _save_strat(s):
    """Save strategy to file."""
    data = {
        "total_spent": s["spent"],
        "total_payout": s["payout"],
        "bought_tokens": [t["token_id"] for t in s["trades"]],
        "trades": s["trades"],
    }
    Path(s["file"]).write_text(json.dumps(data, indent=2))


async def cmd_stop_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop the auto-trading loop."""
    global _auto_trading

    if not _auto_trading:
        await update.message.reply_text("Auto-trading is not running.")
        return

    _auto_trading = False
    await update.message.reply_text(
        "<b>Auto-trading STOPPED</b>\n\n"
        "Use /start to resume, /portfolio to see results.",
        parse_mode="HTML",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check bot status."""
    trading_status = "RUNNING" if _auto_trading else "STOPPED"
    scan_time = _last_scan_time.strftime("%H:%M:%S") if _last_scan_time else "Never"

    msg = f"<b>Bot Status</b>\n\n"
    msg += f"Auto-trading: {trading_status}\n"
    msg += f"Last scan: {scan_time}\n"
    msg += f"Cached markets: {len(_cached_opps)}\n"
    msg += f"Budget: ${_config.total_budget:.0f}\n"
    msg += f"Interval: {_config.check_interval}s\n"

    # Check strategy files
    for name, fname in [("AI Picks", "paper_penny_all.json"), ("Musk", "paper_penny_musk.json"), ("Blind", "paper_penny_blind.json")]:
        fp = Path(fname)
        if fp.exists():
            data = json.loads(fp.read_text())
            trades = data.get("trades", [])
            spent = data.get("total_spent", 0)
            payout = data.get("total_payout", 0)
            pnl = payout - spent
            msg += f"\n{name}: ${spent:.0f} spent, {len(trades)} trades, P&L ${pnl:+.2f}"

    await update.message.reply_text(msg, parse_mode="HTML")


async def post_init(app: Application):
    """Set bot commands in Telegram UI."""
    await app.bot.set_my_commands([
        BotCommand("scan", "List penny-priced shares"),
        BotCommand("research", "AI analysis of opportunities"),
        BotCommand("musk", "Musk tweet strategy"),
        BotCommand("tweets", "Musk's live tweet activity"),
        BotCommand("portfolio", "Show positions & P&L"),
        BotCommand("report", "AI trade analysis report"),
        BotCommand("start", "Start auto-trading"),
        BotCommand("stop", "Stop auto-trading"),
        BotCommand("status", "Check bot status"),
        BotCommand("help", "Show all commands"),
    ])


def main():
    """Start the Telegram bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    token = _config.telegram_bot_token
    if not token:
        print("ERROR: No TELEGRAM_BOT_TOKEN set!")
        print("Set it in .env or config.json")
        print("Get a token from @BotFather on Telegram")
        return

    print(f"\n{'='*50}")
    print(f"  Polymarket Penny Bot — Telegram Mode")
    print(f"  Budget: ${_config.total_budget:.0f}")
    print(f"  Send /help to your bot to get started")
    print(f"  Ctrl+C to stop")
    print(f"{'='*50}\n")

    app = Application.builder().token(token).post_init(post_init).build()

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_start_trading))
    app.add_handler(CommandHandler("stop", cmd_stop_trading))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("research", cmd_research))
    app.add_handler(CommandHandler("musk", cmd_musk))
    app.add_handler(CommandHandler("muskdry", cmd_muskdry))
    app.add_handler(CommandHandler("tweets", cmd_tweets))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("status", cmd_status))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
