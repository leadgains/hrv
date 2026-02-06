#!/usr/bin/env python3
"""
Polymarket Penny Bot 🎰 + AI Research 🧠
Scans Polymarket for 1-9¢ shares, uses Claude to identify mispriced
opportunities, then auto-buys the best ones.
"""

import logging
import time
import sys
from py_clob_client.client import ClobClient

from config import Config
from scanner import scan_for_pennies
from trader import Trader
from notifier import TelegramNotifier
from researcher import research_opportunities, format_research_for_telegram
from musk_analyzer import (
    fetch_musk_tweet_markets,
    analyze_musk_markets,
    format_musk_analysis_telegram,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("penny_bot.log"),
    ],
)
log = logging.getLogger("penny_bot")


def create_client(config: Config) -> ClobClient:
    """Create authenticated Polymarket CLOB client."""
    if not config.private_key:
        log.error("No POLYMARKET_PRIVATE_KEY set. Running in read-only mode.")
        return ClobClient(config.clob_url)

    client = ClobClient(
        config.clob_url,
        key=config.private_key,
        chain_id=config.chain_id,
        signature_type=1,
        funder=config.funder,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    log.info("Authenticated with Polymarket CLOB")
    return client


def run_scan_cycle(client, trader, notifier, config):
    """Run one scan + AI research + trade cycle."""

    # Step 1: Scan for penny shares
    opportunities = scan_for_pennies(
        client,
        min_cents=config.min_price_cents,
        max_cents=config.max_price_cents,
    )

    if not opportunities:
        log.info("No penny opportunities found this cycle")
        return

    # Filter out already bought
    new_opps = [o for o in opportunities if o.token_id not in trader.bought_tokens]
    log.info(f"{len(new_opps)} new opportunities (of {len(opportunities)} total)")

    if not new_opps:
        log.info("No new opportunities to trade")
        return

    # Step 2: AI Research — Claude analyzes which ones are mispriced
    log.info(f"Sending {len(new_opps)} opportunities to Claude for analysis...")
    research_results = research_opportunities(new_opps, batch_size=15)

    # Send research summary to Telegram
    research_msg = format_research_for_telegram(research_results)
    notifier.send_sync(research_msg)
    log.info(research_msg)

    # Step 3: Only buy what Claude recommends
    buys = [r for r in research_results if r.recommendation == "BUY"]
    buys.sort(key=lambda r: r.score, reverse=True)

    if not buys:
        log.info("Claude found no mispriced opportunities this cycle")
        return

    log.info(f"Claude recommends {len(buys)} buys")

    for result in buys:
        opp = result.opportunity
        can, reason = trader.can_trade(config.max_spend_per_trade)
        if not can:
            log.warning(f"Stopping trades: {reason}")
            notifier.send_sync(f"⚠️ Trading paused: {reason}")
            break

        amount = min(config.max_spend_per_trade, config.total_budget - trader.total_spent)
        if amount < 0.10:
            log.info("Remaining budget too small, stopping")
            break

        resp = trader.execute_trade(opp, amount)
        if resp:
            msg = (
                f"🎰 <b>Penny Buy!</b> (AI Score: {result.score}/100)\n"
                f"Market: {opp.market_question[:80]}\n"
                f"Side: {opp.outcome} @ {opp.price*100:.1f}¢\n"
                f"AI estimate: {result.fair_value_estimate*100:.0f}% real chance\n"
                f"Reason: {result.reasoning[:120]}\n"
                f"Spent: ${amount:.2f} | Shares: {amount/opp.price:.0f}\n"
                f"Max payout: ${amount/opp.price:.2f}"
            )
            notifier.send_sync(msg)
            time.sleep(2)


def main():
    config = Config()
    log.info("Starting Polymarket Penny Bot 🎰🧠")
    log.info(f"Budget: ${config.total_budget} | Max per trade: ${config.max_spend_per_trade}")
    log.info(f"Price range: {config.min_price_cents}¢ - {config.max_price_cents}¢")
    log.info(f"Check interval: {config.check_interval}s")

    client = create_client(config)
    trader = Trader(config=config, client=client)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    notifier.send_sync(
        f"🚀 <b>Penny Bot + AI Research Started</b>\n"
        f"Budget: ${config.total_budget}\n"
        f"Range: {config.min_price_cents}¢-{config.max_price_cents}¢\n"
        f"Max/trade: ${config.max_spend_per_trade}\n"
        f"AI: Claude analyzes every opportunity before buying"
    )

    log.info(trader.get_summary())

    # --musk: Elon Musk tweet strategy (Annica-style)
    if "--musk" in sys.argv:
        log.info("Musk Tweet Strategy mode")
        musk_opps = fetch_musk_tweet_markets(client)
        if not musk_opps:
            log.info("No Musk tweet markets found")
            return

        picks = analyze_musk_markets(musk_opps, budget=config.total_budget)
        if not picks:
            log.info("Claude found no good Musk picks")
            return

        # Send analysis to Telegram
        notifier.send_sync(format_musk_analysis_telegram(picks))

        if "--dry" not in sys.argv:
            for pick in picks:
                opp = pick["opportunity"]
                amount = pick["amount"]
                can, reason = trader.can_trade(amount)
                if not can:
                    log.warning(f"Cannot trade: {reason}")
                    break
                resp = trader.execute_trade(opp, amount)
                if resp:
                    msg = (
                        f"🐦 <b>Musk Buy!</b>\n"
                        f"{opp.market_question[:80]}\n"
                        f"{opp.outcome} @ {opp.price*100:.1f}¢ — ${amount:.2f}\n"
                        f"Reason: {pick['reasoning'][:100]}"
                    )
                    notifier.send_sync(msg)
                    time.sleep(2)
            log.info(trader.get_summary())
        return

    # --research: AI analysis only, no trading
    if "--research" in sys.argv:
        log.info("Research-only mode (AI analysis, no trading)")
        opps = scan_for_pennies(client, config.min_price_cents, config.max_price_cents)
        if opps:
            results = research_opportunities(opps[:30])
            print(format_research_for_telegram(results, top_n=10))
            for r in results[:10]:
                print(
                    f"  [{r.recommendation}] {r.score}/100 — "
                    f"{r.opportunity.outcome} @ {r.opportunity.price*100:.1f}¢ — "
                    f"{r.opportunity.market_question[:60]}"
                )
                print(f"    Reason: {r.reasoning[:100]}")
        return

    # --scan: just list penny shares, no AI, no trading
    if "--scan" in sys.argv:
        log.info("Scan-only mode (no AI, no trading)")
        opps = scan_for_pennies(client, config.min_price_cents, config.max_price_cents)
        for o in opps[:20]:
            print(f"  {o.outcome} @ {o.price*100:.1f}¢ — {o.market_question[:70]}")
        print(f"\nTotal: {len(opps)} penny opportunities")
        return

    # --once: one full cycle (scan + AI + trade)
    if "--once" in sys.argv:
        log.info("Running single cycle (--once mode)")
        run_scan_cycle(client, trader, notifier, config)
        log.info(trader.get_summary())
        return

    # Main loop
    while True:
        try:
            run_scan_cycle(client, trader, notifier, config)
        except KeyboardInterrupt:
            log.info("Shutting down...")
            notifier.send_sync("🛑 Penny Bot stopped")
            break
        except Exception as e:
            log.error(f"Cycle error: {e}", exc_info=True)
            notifier.send_sync(f"❌ Bot error: {e}")

        log.info(f"Sleeping {config.check_interval}s until next scan...")
        time.sleep(config.check_interval)

    log.info(trader.get_summary())


if __name__ == "__main__":
    main()
