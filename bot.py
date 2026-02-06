#!/usr/bin/env python3
"""
Polymarket Penny Bot 🎰 + AI Research 🧠
Scans Polymarket for 1-9¢ shares, uses Claude to identify mispriced
opportunities, then auto-buys the best ones.
"""

import logging
import time
import sys

DEMO_MODE = "--demo" in sys.argv
PAPER_MODE = "--paper" in sys.argv

try:
    from py_clob_client.client import ClobClient
except ImportError:
    ClobClient = None

from config import Config
from scanner import scan_for_pennies
from trader import Trader
from paper_trader import PaperTrader
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


def create_client(config: Config):
    """Create Polymarket CLOB client."""
    if DEMO_MODE:
        log.info("DEMO MODE — no real API connection")
        return None

    if ClobClient is None:
        log.warning("py-clob-client not installed — read-only mode")
        return None

    if not config.private_key:
        log.info("No wallet key — read-only mode (can scan but not trade)")
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


def run_paper_cycle(client, paper, notifier, config):
    """Paper trading cycle — real data, fake money."""

    # Scan real markets
    opportunities = get_opportunities(client, config)
    if not opportunities:
        log.info("No penny opportunities this cycle")
        return

    new_opps = [o for o in opportunities if o.token_id not in paper.bought_tokens]
    log.info(f"{len(new_opps)} new opportunities (of {len(opportunities)} total)")

    if not new_opps:
        # Still check resolutions on existing positions
        if client and not DEMO_MODE:
            resolved = paper.check_resolutions(client)
            if resolved:
                for t in resolved:
                    icon = "✅" if t.status == "won" else "❌"
                    notifier.send_sync(
                        f"{icon} <b>PAPER {t.status.upper()}</b>\n"
                        f"{t.market[:60]}\n"
                        f"${t.amount:.2f} → ${t.payout:.2f}"
                    )
        return

    # AI Research
    log.info(f"AI analyzing {len(new_opps)} opportunities...")
    results = research_opportunities(new_opps, batch_size=15)

    buys = [r for r in results if r.recommendation == "BUY"]
    buys.sort(key=lambda r: r.score, reverse=True)

    if not buys:
        log.info("AI found no mispriced opportunities")
        return

    log.info(f"AI recommends {len(buys)} buys")

    for result in buys:
        opp = result.opportunity
        amount = min(config.max_spend_per_trade, paper.budget - paper.total_spent)
        if amount < 0.10:
            break

        trade = paper.buy(opp, amount)
        if trade:
            msg = (
                f"📝 <b>PAPER BUY</b> (Score: {result.score}/100)\n"
                f"{opp.market_question[:70]}\n"
                f"{opp.outcome} @ {opp.price*100:.1f}¢ — ${amount:.2f}\n"
                f"AI: {result.reasoning[:100]}\n"
                f"If wins: ${trade.shares:.2f} payout"
            )
            notifier.send_sync(msg)
            log.info(msg.replace("<b>", "").replace("</b>", ""))
            time.sleep(1)

    # Check resolutions
    if client and not DEMO_MODE:
        paper.check_resolutions(client)

    log.info(paper.get_summary_short())


def run_scan_cycle(client, trader, notifier, config):
    """Real trading cycle — scan + AI research + trade."""

    opportunities = get_opportunities(client, config)
    if not opportunities:
        log.info("No penny opportunities found this cycle")
        return

    new_opps = [o for o in opportunities if o.token_id not in trader.bought_tokens]
    log.info(f"{len(new_opps)} new opportunities (of {len(opportunities)} total)")

    if not new_opps:
        log.info("No new opportunities to trade")
        return

    log.info(f"Sending {len(new_opps)} opportunities to Claude for analysis...")
    research_results = research_opportunities(new_opps, batch_size=15)

    research_msg = format_research_for_telegram(research_results)
    notifier.send_sync(research_msg)

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
            break

        if DEMO_MODE:
            shares = amount / opp.price
            log.info(
                f"DEMO BUY: {shares:.0f}x {opp.outcome} @ {opp.price*100:.1f}¢ "
                f"for ${amount:.2f} — {opp.market_question[:60]}"
            )
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

    mode = "DEMO" if DEMO_MODE else "PAPER $100" if PAPER_MODE else "LIVE"
    log.info(f"{'='*60}")
    log.info(f"  Polymarket Penny Bot — {mode} MODE")
    log.info(f"{'='*60}")
    log.info(f"Budget: ${config.total_budget} | Max/trade: ${config.max_spend_per_trade}")
    log.info(f"Price range: {config.min_price_cents}¢ - {config.max_price_cents}¢")

    client = create_client(config)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    # Paper trading mode
    if PAPER_MODE:
        paper = PaperTrader(config=config, budget=100.0)

        if "--status" in sys.argv:
            print(paper.get_summary())
            return

        notifier.send_sync(
            f"📝 <b>Paper Trading Started</b>\n"
            f"Virtual budget: $100\n"
            f"Scanning every {config.check_interval}s\n"
            f"AI analyzes before every buy"
        )

        log.info(paper.get_summary_short())

        if "--once" in sys.argv:
            run_paper_cycle(client, paper, notifier, config)
            print(paper.get_summary())
            return

        # 24/7 paper trading loop
        while True:
            try:
                run_paper_cycle(client, paper, notifier, config)
            except KeyboardInterrupt:
                log.info("Shutting down paper trader...")
                notifier.send_sync("🛑 Paper trading stopped")
                break
            except Exception as e:
                log.error(f"Cycle error: {e}", exc_info=True)

            log.info(f"Next scan in {config.check_interval}s... | {paper.get_summary_short()}")
            time.sleep(config.check_interval)

        print(paper.get_summary())
        return

    # Real/demo trading
    trader = Trader(config=config, client=client)

    # --scan
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
        print(f"\n  Budget: ${config.total_budget} | Strategy: AI picks mispriced ones\n")
        return

    # --research
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

    # --once
    if "--once" in sys.argv:
        run_scan_cycle(client, trader, notifier, config)
        print(f"\n{trader.get_summary()}")
        return

    # --musk
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

    # Main 24/7 loop
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
