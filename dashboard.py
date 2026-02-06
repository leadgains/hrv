"""Simple web dashboard for the penny bot."""
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
from paper_trader import PaperTrader

try:
    from py_clob_client.client import ClobClient
except ImportError:
    ClobClient = None

log = logging.getLogger(__name__)

# Shared state
state = {
    "opportunities": [],
    "last_scan": "Never",
    "scanning": False,
    "error": None,
}


def scan_thread(config):
    """Background scanner that updates state."""
    while True:
        state["scanning"] = True
        state["error"] = None
        try:
            if ClobClient is None:
                state["error"] = "py-clob-client not installed — run: pip3 install py-clob-client"
                state["scanning"] = False
                time.sleep(config.check_interval)
                continue

            client = ClobClient(config.clob_url)
            opps = scan_for_pennies(client, config.min_price_cents, config.max_price_cents)
            state["opportunities"] = opps
            state["last_scan"] = datetime.now().strftime("%H:%M:%S")
            state["error"] = None
        except Exception as e:
            state["error"] = str(e)
        state["scanning"] = False
        time.sleep(config.check_interval)


def render_dashboard(config):
    """Render HTML dashboard."""
    paper = PaperTrader(config=config, budget=100.0)
    opps = state["opportunities"]

    # Opportunities table
    opp_rows = ""
    for o in opps[:30]:
        potential = 1.0 / o.price if o.price > 0 else 0
        opp_rows += f"""
        <tr>
            <td>{o.outcome}</td>
            <td>{o.price*100:.1f}¢</td>
            <td>${4 * potential:.0f}</td>
            <td>{o.market_question[:70]}</td>
            <td>{o.end_date[:10] if o.end_date else '?'}</td>
        </tr>"""

    # Paper trades table
    trade_rows = ""
    for t in paper.trades:
        icon = {"open": "⏳", "won": "✅", "lost": "❌"}.get(t.status, "?")
        change = ((t.current_price - t.buy_price) / t.buy_price * 100) if t.buy_price > 0 else 0
        trade_rows += f"""
        <tr class="{t.status}">
            <td>{icon} {t.status.upper()}</td>
            <td>{t.outcome}</td>
            <td>{t.buy_price*100:.1f}¢</td>
            <td>{t.current_price*100:.1f}¢</td>
            <td>{change:+.0f}%</td>
            <td>${t.amount:.2f}</td>
            <td>${t.shares:.2f}</td>
            <td>{t.market[:50]}</td>
        </tr>"""

    pnl = paper.total_payout - paper.total_spent
    open_count = len([t for t in paper.trades if t.status == "open"])
    won_count = len([t for t in paper.trades if t.status == "won"])
    lost_count = len([t for t in paper.trades if t.status == "lost"])

    error_html = f'<div class="error">{state["error"]}</div>' if state["error"] else ""
    scanning = "🔄 Scanning..." if state["scanning"] else ""

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Polymarket Penny Bot</title>
    <meta http-equiv="refresh" content="30">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, monospace; background: #0a0a0a; color: #e0e0e0; padding: 20px; }}
        h1 {{ color: #00ff88; margin-bottom: 5px; }}
        h2 {{ color: #888; margin: 20px 0 10px; font-size: 16px; }}
        .stats {{ display: flex; gap: 20px; margin: 15px 0; flex-wrap: wrap; }}
        .stat {{ background: #1a1a2e; padding: 15px 20px; border-radius: 8px; min-width: 140px; }}
        .stat .label {{ color: #888; font-size: 12px; }}
        .stat .value {{ font-size: 24px; font-weight: bold; margin-top: 4px; }}
        .stat .value.green {{ color: #00ff88; }}
        .stat .value.red {{ color: #ff4444; }}
        .stat .value.yellow {{ color: #ffcc00; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }}
        th {{ text-align: left; padding: 8px; color: #888; border-bottom: 1px solid #333; }}
        td {{ padding: 8px; border-bottom: 1px solid #1a1a1a; }}
        tr:hover {{ background: #1a1a2e; }}
        tr.won {{ background: #0a2a0a; }}
        tr.lost {{ background: #2a0a0a; }}
        .error {{ background: #2a0a0a; color: #ff4444; padding: 10px; border-radius: 8px; margin: 10px 0; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; }}
        .time {{ color: #666; font-size: 13px; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }}
        .badge.live {{ background: #00ff8833; color: #00ff88; }}
        .badge.paper {{ background: #ffcc0033; color: #ffcc00; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🎰 Polymarket Penny Bot</h1>
            <span class="badge paper">PAPER TRADING</span> {scanning}
        </div>
        <div class="time">Last scan: {state['last_scan']} | Auto-refresh: 30s</div>
    </div>

    {error_html}

    <div class="stats">
        <div class="stat">
            <div class="label">Budget</div>
            <div class="value">${paper.budget:.0f}</div>
        </div>
        <div class="stat">
            <div class="label">Spent</div>
            <div class="value">${paper.total_spent:.2f}</div>
        </div>
        <div class="stat">
            <div class="label">P&L</div>
            <div class="value {'green' if pnl >= 0 else 'red'}">${pnl:+.2f}</div>
        </div>
        <div class="stat">
            <div class="label">Positions</div>
            <div class="value yellow">{open_count} open</div>
        </div>
        <div class="stat">
            <div class="label">Won / Lost</div>
            <div class="value">{won_count} / {lost_count}</div>
        </div>
        <div class="stat">
            <div class="label">Penny Markets</div>
            <div class="value">{len(opps)}</div>
        </div>
    </div>

    <h2>📝 PAPER POSITIONS</h2>
    {'<table><tr><th>Status</th><th>Side</th><th>Buy</th><th>Now</th><th>Change</th><th>Spent</th><th>Payout</th><th>Market</th></tr>' + trade_rows + '</table>' if trade_rows else '<p style="color:#666">No positions yet. Run: python3 bot.py --paper --once</p>'}

    <h2>🔍 PENNY OPPORTUNITIES (1-9¢)</h2>
    {'<table><tr><th>Side</th><th>Price</th><th>$4 Payout</th><th>Market</th><th>Expires</th></tr>' + opp_rows + '</table>' if opp_rows else '<p style="color:#666">No penny shares found yet. Waiting for scan...</p>'}

    <p style="color:#444; margin-top:20px; font-size:11px;">
        Refresh: 30s | Scan interval: {config.check_interval}s | Price range: {config.min_price_cents}-{config.max_price_cents}¢
    </p>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    config = None

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = render_dashboard(self.config)
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # Suppress access logs


def run_dashboard(port=8888):
    config = Config()
    DashboardHandler.config = config

    # Start scanner in background
    scanner = threading.Thread(target=scan_thread, args=(config,), daemon=True)
    scanner.start()

    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"\n{'='*50}")
    print(f"  🎰 Penny Bot Dashboard")
    print(f"  Open in browser: http://localhost:{port}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*50}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard()
