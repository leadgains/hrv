#!/usr/bin/env python3
"""
Polymarket Penny Bot 🎰
Automatically buys shares priced 1-9 cents on Polymarket.
Sends notifications via Telegram.
"""

import logging
import time
import random
import sys
from py_clob_client.client import ClobClient

from config import Config
from scanner import scan_for_pennies
from trader import Trader
from notifier import TelegramNotifier

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


def pick_best_opportunities(opportunities, max_picks=5):
    """Score and rank penny opportunities.

    Prefers:
    - Lower prices (more upside)
    - Markets expiring soon (faster resolution)
    """
    scored = []
    for opp in opportunities:
        # Lower price = higher score (more upside)
        price_score = (10 - opp.price * 100) / 10
        scored.append((price_score, opp))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Add some randomness - don't always pick the same ones
    top = scored[:max_picks * 3]
    if len(top) > max_picks:
        random.shuffle(top)
        top = top[:max_picks]

    return [opp for _, opp in top]


def run_scan_cycle(client, trader, notifier, config):
    """Run one scan + trade cycle."""
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

    picks = pick_best_opportunities(new_opps, max_picks=3)

    for opp in picks:
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
                f"🎰 <b>Penny Buy!</b>\n"
                f"Market: {opp.market_question[:80]}\n"
                f"Side: {opp.outcome} @ {opp.price*100:.1f}¢\n"
                f"Spent: ${amount:.2f}\n"
                f"Shares: {amount/opp.price:.0f}\n"
                f"Max payout: ${amount/opp.price:.2f}"
            )
            notifier.send_sync(msg)
            log.info(f"Trade sent to Telegram")

            # Small delay between trades
            time.sleep(2)


def main():
    config = Config()
    log.info("Starting Polymarket Penny Bot 🎰")
    log.info(f"Budget: ${config.total_budget} | Max per trade: ${config.max_spend_per_trade}")
    log.info(f"Price range: {config.min_price_cents}¢ - {config.max_price_cents}¢")
    log.info(f"Check interval: {config.check_interval}s")

    client = create_client(config)
    trader = Trader(config=config, client=client)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    notifier.send_sync(
        f"🚀 <b>Penny Bot Started</b>\n"
        f"Budget: ${config.total_budget}\n"
        f"Range: {config.min_price_cents}¢-{config.max_price_cents}¢\n"
        f"Max/trade: ${config.max_spend_per_trade}"
    )

    # Show current state
    log.info(trader.get_summary())

    if "--once" in sys.argv:
        log.info("Running single scan cycle (--once mode)")
        run_scan_cycle(client, trader, notifier, config)
        log.info(trader.get_summary())
        return

    if "--scan" in sys.argv:
        log.info("Scan-only mode (no trading)")
        opps = scan_for_pennies(client, config.min_price_cents, config.max_price_cents)
        for o in opps[:20]:
            print(f"  {o.outcome} @ {o.price*100:.1f}¢ — {o.market_question[:70]}")
        print(f"\nTotal: {len(opps)} penny opportunities")
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
