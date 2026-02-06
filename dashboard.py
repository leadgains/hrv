"""Multi-strategy dashboard — runs 3 paper strategies side by side."""
from __future__ import annotations

import json
import threading
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

from config import Config
from scanner import scan_for_pennies, PennyOpportunity
from paper_trader import PaperTrader, PAPER_FILE
from researcher import research_opportunities
from musk_analyzer import fetch_musk_tweet_markets, analyze_musk_markets

try:
    from py_clob_client.client import ClobClient
except ImportError:
    ClobClient = None

log = logging.getLogger(__name__)

# Shared state
state = {
    "all_opportunities": [],
    "musk_opportunities": [],
    "last_scan": "Never",
    "scanning": False,
    "error": None,
    "strategies": {
        "penny_all": {"name": "All Penny (AI picks)", "file": "paper_penny_all.json", "trades": [], "spent": 0, "payout": 0},
        "penny_musk": {"name": "Musk Tweets Only", "file": "paper_penny_musk.json", "trades": [], "spent": 0, "payout": 0},
        "penny_blind": {"name": "Blind (no AI)", "file": "paper_penny_blind.json", "trades": [], "spent": 0, "payout": 0},
    },
}


def load_strategy(filepath):
    """Load paper trades from a JSON file."""
    p = Path(filepath)
    if p.exists():
        data = json.loads(p.read_text())
        return data.get("trades", []), data.get("total_spent", 0), data.get("total_payout", 0)
    return [], 0, 0


def save_strategy(filepath, trades, spent, payout):
    """Save paper trades to a JSON file."""
    data = {
        "total_spent": spent,
        "total_payout": payout,
        "bought_tokens": [t["token_id"] for t in trades],
        "trades": trades,
    }
    Path(filepath).write_text(json.dumps(data, indent=2))


def paper_buy(strategy, opp, amount):
    """Record a virtual buy for a strategy."""
    s = state["strategies"][strategy]
    # Check if already bought
    bought = {t["token_id"] for t in s["trades"]}
    if opp.token_id in bought:
        return False
    if s["spent"] + amount > 100:
        return False

    shares = amount / opp.price
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
    s["trades"].append(trade)
    s["spent"] += amount
    save_strategy(s["file"], s["trades"], s["spent"], s["payout"])
    log.info(f"[{strategy}] PAPER BUY: {opp.outcome} @ {opp.price*100:.1f}¢ — ${amount:.2f} — {opp.market_question[:50]}")
    return True


def scan_and_trade(config):
    """Background thread: scan markets and execute all 3 strategies."""
    while True:
        state["scanning"] = True
        state["error"] = None

        try:
            if ClobClient is None:
                state["error"] = "py-clob-client not installed — run: pip install py-clob-client"
                state["scanning"] = False
                time.sleep(config.check_interval)
                continue

            client = ClobClient(config.clob_url)

            # Scan all penny markets
            all_opps = scan_for_pennies(client, config.min_price_cents, config.max_price_cents)
            state["all_opportunities"] = all_opps

            # Filter Musk markets
            musk_opps = [o for o in all_opps if any(
                kw in o.market_question.lower() for kw in ["musk", "elon", "tweet", "@elonmusk", "x post"]
            )]
            state["musk_opportunities"] = musk_opps

            state["last_scan"] = datetime.now().strftime("%H:%M:%S")

            # Load existing strategies
            for key, s in state["strategies"].items():
                s["trades"], s["spent"], s["payout"] = load_strategy(s["file"])

            max_per_trade = config.max_spend_per_trade

            # === STRATEGY 1: All Penny with AI ===
            if all_opps:
                bought_tokens = {t["token_id"] for t in state["strategies"]["penny_all"]["trades"]}
                new_opps = [o for o in all_opps if o.token_id not in bought_tokens]
                if new_opps:
                    results = research_opportunities(new_opps[:15], batch_size=15)
                    buys = [r for r in results if r.recommendation == "BUY"]
                    buys.sort(key=lambda r: r.score, reverse=True)
                    for r in buys[:5]:
                        paper_buy("penny_all", r.opportunity, max_per_trade)

            # === STRATEGY 2: Musk Only ===
            if musk_opps:
                for opp in musk_opps:
                    if opp.price <= 0.09:
                        paper_buy("penny_musk", opp, max_per_trade)

            # === STRATEGY 3: Blind (cheapest first, no AI) ===
            if all_opps:
                sorted_opps = sorted(all_opps, key=lambda o: o.price)
                for opp in sorted_opps[:5]:
                    paper_buy("penny_blind", opp, max_per_trade)

            # Check resolutions for all strategies
            for key, s in state["strategies"].items():
                for t in s["trades"]:
                    if t["status"] != "open":
                        continue
                    try:
                        price = float(client.get_price(t["token_id"], side="BUY"))
                        t["current_price"] = price
                        if price >= 0.95:
                            t["status"] = "won"
                            t["payout"] = t["shares"]
                            t["resolved_at"] = datetime.utcnow().isoformat()
                            s["payout"] += t["payout"]
                        elif price <= 0.01 and t["buy_price"] > 0.01:
                            t["status"] = "lost"
                            t["payout"] = 0
                            t["resolved_at"] = datetime.utcnow().isoformat()
                    except Exception:
                        pass
                save_strategy(s["file"], s["trades"], s["spent"], s["payout"])

        except Exception as e:
            state["error"] = str(e)
            log.error(f"Scan error: {e}", exc_info=True)

        state["scanning"] = False
        time.sleep(config.check_interval)


def render_strategy_card(key, s):
    """Render one strategy card."""
    trades = s["trades"]
    spent = s["spent"]
    payout = s["payout"]
    pnl = payout - spent
    open_t = len([t for t in trades if t["status"] == "open"])
    won_t = len([t for t in trades if t["status"] == "won"])
    lost_t = len([t for t in trades if t["status"] == "lost"])
    unrealized = sum(t["shares"] * t["current_price"] for t in trades if t["status"] == "open")

    trade_rows = ""
    for t in trades[-10:]:
        icon = {"open": "⏳", "won": "✅", "lost": "❌"}.get(t["status"], "?")
        change = ((t["current_price"] - t["buy_price"]) / t["buy_price"] * 100) if t["buy_price"] > 0 else 0
        trade_rows += f"""
        <tr class="{t['status']}">
            <td>{icon}</td>
            <td>{t['outcome']}</td>
            <td>{t['buy_price']*100:.1f}¢</td>
            <td>{t['current_price']*100:.1f}¢</td>
            <td>{change:+.0f}%</td>
            <td>${t['amount']:.2f}</td>
            <td>{t['market'][:45]}</td>
        </tr>"""

    return f"""
    <div class="strategy">
        <h2>{s['name']}</h2>
        <div class="stats">
            <div class="stat"><div class="label">Spent</div><div class="value">${spent:.2f}</div></div>
            <div class="stat"><div class="label">P&L</div><div class="value {'green' if pnl >= 0 else 'red'}">${pnl:+.2f}</div></div>
            <div class="stat"><div class="label">Unrealized</div><div class="value yellow">${unrealized:.2f}</div></div>
            <div class="stat"><div class="label">Positions</div><div class="value">{open_t}⏳ {won_t}✅ {lost_t}❌</div></div>
        </div>
        {'<table><tr><th></th><th>Side</th><th>Buy</th><th>Now</th><th>Chg</th><th>$</th><th>Market</th></tr>' + trade_rows + '</table>' if trade_rows else '<p style="color:#555">No trades yet...</p>'}
    </div>"""


def render_dashboard(config):
    """Render the multi-strategy dashboard."""
    opps = state["all_opportunities"]
    musk_opps = state["musk_opportunities"]
    error_html = f'<div class="error">{state["error"]}</div>' if state["error"] else ""
    scanning = " 🔄" if state["scanning"] else ""

    # Render all 3 strategy cards
    cards = ""
    for key, s in state["strategies"].items():
        cards += render_strategy_card(key, s)

    # Top penny opportunities
    opp_rows = ""
    for o in opps[:15]:
        potential = 1.0 / o.price if o.price > 0 else 0
        is_musk = "🐦" if any(kw in o.market_question.lower() for kw in ["musk", "elon", "tweet"]) else ""
        opp_rows += f"""
        <tr>
            <td>{is_musk} {o.outcome}</td>
            <td>{o.price*100:.1f}¢</td>
            <td>${4 * potential:.0f}</td>
            <td>{o.market_question[:65]}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Penny Bot — 3 Strategies</title>
    <meta http-equiv="refresh" content="30">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        h1 {{ color: #00ff88; margin-bottom: 5px; }}
        h2 {{ color: #00ff88; margin: 0 0 10px; font-size: 18px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
        .time {{ color: #666; font-size: 13px; }}
        .error {{ background: #2a0a0a; color: #ff4444; padding: 10px; border-radius: 8px; margin: 10px 0; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin: 15px 0; }}
        .strategy {{ background: #111; border: 1px solid #222; border-radius: 10px; padding: 15px; }}
        .stats {{ display: flex; gap: 10px; margin: 10px 0; flex-wrap: wrap; }}
        .stat {{ background: #1a1a2e; padding: 8px 12px; border-radius: 6px; }}
        .stat .label {{ color: #888; font-size: 10px; }}
        .stat .value {{ font-size: 16px; font-weight: bold; margin-top: 2px; }}
        .green {{ color: #00ff88; }}
        .red {{ color: #ff4444; }}
        .yellow {{ color: #ffcc00; }}
        table {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 11px; }}
        th {{ text-align: left; padding: 4px 6px; color: #555; border-bottom: 1px solid #222; }}
        td {{ padding: 4px 6px; border-bottom: 1px solid #1a1a1a; }}
        tr:hover {{ background: #1a1a2e; }}
        tr.won {{ background: #0a2a0a; }}
        tr.lost {{ background: #2a0a0a; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; background: #ffcc0033; color: #ffcc00; }}
        .bottom {{ margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🎰 Polymarket Penny Bot — Strategy Race</h1>
            <span class="badge">PAPER TRADING $100 each</span>{scanning}
        </div>
        <div class="time">
            Scan: {state['last_scan']} | Markets: {len(opps)} penny, {len(musk_opps)} musk | Refresh: 30s
        </div>
    </div>

    {error_html}

    <div class="grid">
        {cards}
    </div>

    <div class="bottom">
        <h2>🔍 Live Penny Markets</h2>
        {'<table><tr><th>Side</th><th>Price</th><th>$4 Payout</th><th>Market</th></tr>' + opp_rows + '</table>' if opp_rows else '<p style="color:#555">Scanning...</p>'}
    </div>

    <p style="color:#333; margin-top:15px; font-size:10px;">
        3 strategies racing with $100 virtual each. Best P&L after 1 week wins.
    </p>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    config = None

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(render_dashboard(self.config).encode())

    def log_message(self, format, *args):
        pass


def run_dashboard(port=8888):
    config = Config()
    DashboardHandler.config = config

    # Start scanner + trader in background
    worker = threading.Thread(target=scan_and_trade, args=(config,), daemon=True)
    worker.start()

    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"\n{'='*50}")
    print(f"  🎰 Penny Bot — Strategy Race")
    print(f"  3 strategies, $100 each, 1 week")
    print(f"  Open: http://localhost:{port}")
    print(f"  Ctrl+C to stop")
    print(f"{'='*50}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard()
