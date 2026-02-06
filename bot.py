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

DEMO_MODE = "--demo" in sys.argv

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
    if DEMO_MODE:
        log.info("DEMO MODE — no real API connection")
        return None

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


def get_opportunities(client, config):
    """Get penny opportunities from API or demo data."""
    if DEMO_MODE:
        from demo_data import DEMO_MARKETS
        log.info(f"DEMO: Loaded {len(DEMO_MARKETS)} fake markets")
        return DEMO_MARKETS
    return scan_for_pennies(client, config.min_price_cents, config.max_price_cents)


def run_scan_cycle(client, trader, notifier, config):
    """Run one scan + AI research + trade cycle."""

    # Step 1: Scan for penny shares
    opportunities = get_opportunities(client, config)

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

        if DEMO_MODE:
            shares = amount / opp.price
            log.info(
                f"DEMO BUY: {shares:.0f}x {opp.outcome} @ {opp.price*100:.1f}¢ "
                f"for ${amount:.2f} — {opp.market_question[:60]}"
            )
            log.info(f"  AI reason: {result.reasoning[:100]}")
            log.info(f"  AI score: {result.score}/100 | est. value: {result.fair_value_estimate*100:.0f}%")
            log.info(f"  Max payout if wins: ${shares:.2f}")
            trader.total_spent += amount
            trader.bought_tokens.add(opp.token_id)
        else:
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

    if DEMO_MODE:
        log.info("=" * 60)
        log.info("  DEMO MODE — Simulated markets, no real trades")
        log.info("=" * 60)

    log.info("Starting Polymarket Penny Bot 🎰🧠")
    log.info(f"Budget: ${config.total_budget} | Max per trade: ${config.max_spend_per_trade}")
    log.info(f"Price range: {config.min_price_cents}¢ - {config.max_price_cents}¢")

    client = create_client(config)
    trader = Trader(config=config, client=client)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    # --demo --scan: show what penny markets look like
    if "--scan" in sys.argv:
        opps = get_opportunities(client, config)
        print(f"\n{'='*60}")
        print(f"  PENNY OPPORTUNITIES ({len(opps)} found)")
        print(f"{'='*60}\n")
        for o in opps:
            potential = 1.0 / o.price if o.price > 0 else 0
            print(
                f"  {o.outcome:3s} @ {o.price*100:4.1f}¢  |  "
                f"${config.max_spend_per_trade:.0f} bet → ${config.max_spend_per_trade * potential:.0f} max payout  |  "
                f"{o.market_question[:55]}"
            )
        print(f"\n  Budget: ${config.total_budget} over {len(opps)} markets")
        print(f"  Strategy: AI picks the mispriced ones, skips the rest\n")
        return

    # --demo --research: show AI analysis without trading
    if "--research" in sys.argv:
        opps = get_opportunities(client, config)
        if not opps:
            print("No opportunities found")
            return

        print(f"\n{'='*60}")
        print(f"  AI RESEARCH — Claude analyzes {len(opps)} markets")
        print(f"{'='*60}\n")

        results = research_opportunities(opps)
        buys = [r for r in results if r.recommendation == "BUY"]
        skips = [r for r in results if r.recommendation == "SKIP"]
        watches = [r for r in results if r.recommendation == "WATCH"]

        print(f"  Results: {len(buys)} BUY | {len(watches)} WATCH | {len(skips)} SKIP\n")

        for r in sorted(results, key=lambda x: x.score, reverse=True):
            opp = r.opportunity
            icon = {"BUY": "🟢", "WATCH": "🟡", "SKIP": "🔴"}.get(r.recommendation, "⚪")
            print(
                f"  {icon} [{r.recommendation:5s}] Score: {r.score:3.0f}/100  |  "
                f"{opp.outcome} @ {opp.price*100:.1f}¢  |  "
                f"AI says {r.fair_value_estimate*100:.0f}% real chance"
            )
            print(f"     {opp.market_question[:65]}")
            print(f"     {r.reasoning[:90]}")
            print()

        if buys:
            total_potential = sum(config.max_spend_per_trade / r.opportunity.price for r in buys)
            print(f"  If all {len(buys)} BUY picks win: ${total_potential:.2f} payout on ${len(buys) * config.max_spend_per_trade:.2f} spent")
        return

    # --once: full cycle (scan + AI + simulated trade)
    if "--once" in sys.argv:
        print(f"\n{'='*60}")
        print(f"  FULL CYCLE — Scan → AI Research → {'Demo ' if DEMO_MODE else ''}Trade")
        print(f"{'='*60}\n")
        run_scan_cycle(client, trader, notifier, config)
        print(f"\n{trader.get_summary()}")
        return

    # --musk: Elon Musk tweet strategy
    if "--musk" in sys.argv:
        if DEMO_MODE:
            from demo_data import DEMO_MARKETS
            musk_opps = [o for o in DEMO_MARKETS if "musk" in o.market_question.lower()]
        else:
            musk_opps = fetch_musk_tweet_markets(client)

        if not musk_opps:
            log.info("No Musk tweet markets found")
            return

        print(f"\n{'='*60}")
        print(f"  MUSK TWEET STRATEGY (Annica-style)")
        print(f"{'='*60}\n")
        print(f"  Found {len(musk_opps)} Musk tweet ranges:\n")
        for o in musk_opps:
            print(f"    {o.outcome} @ {o.price*100:.1f}¢ — {o.market_question}")

        picks = analyze_musk_markets(musk_opps, budget=config.total_budget)
        if picks:
            print(f"\n  Claude's picks:\n")
            for p in picks:
                opp = p["opportunity"]
                print(f"    → ${p['amount']:.2f} on {opp.outcome} @ {opp.price*100:.1f}¢ — {opp.market_question[:50]}")
                print(f"      Reason: {p['reasoning'][:80]}")
            print(f"\n  Week type: {picks[0].get('confidence', '?')}")
            print(f"  Expected range: {picks[0].get('estimated_range', '?')} tweets")
        return

    # Main loop (24/7)
    notifier.send_sync(
        f"🚀 <b>Penny Bot Started (24/7)</b>\n"
        f"Budget: ${config.total_budget}\n"
        f"AI research every {config.check_interval}s"
    )

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
