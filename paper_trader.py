"""Paper trading engine — tracks virtual positions with real market data."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path

from config import Config
from scanner import PennyOpportunity

log = logging.getLogger(__name__)

PAPER_FILE = Path("paper_trades.json")


@dataclass
class PaperTrade:
    timestamp: str
    market: str
    market_slug: str
    outcome: str
    token_id: str
    condition_id: str
    buy_price: float  # e.g. 0.03
    amount: float  # USD spent
    shares: float  # amount / buy_price
    current_price: float  # last known price
    status: str  # "open", "won", "lost"
    resolved_at: str = ""
    payout: float = 0.0


@dataclass
class PaperTrader:
    config: Config
    budget: float = 100.0
    total_spent: float = 0.0
    total_payout: float = 0.0
    daily_spent: float = 0.0
    daily_date: str = ""
    trades: list[PaperTrade] = field(default_factory=list)
    bought_tokens: set = field(default_factory=set)

    def __post_init__(self):
        self._load()

    def _load(self):
        if PAPER_FILE.exists():
            data = json.loads(PAPER_FILE.read_text())
            self.budget = data.get("budget", self.budget)
            self.total_spent = data.get("total_spent", 0.0)
            self.total_payout = data.get("total_payout", 0.0)
            self.bought_tokens = set(data.get("bought_tokens", []))
            self.trades = [PaperTrade(**t) for t in data.get("trades", [])]
            log.info(
                f"Loaded {len(self.trades)} paper trades, "
                f"${self.total_spent:.2f} spent, ${self.total_payout:.2f} won"
            )

    def save(self):
        data = {
            "budget": self.budget,
            "total_spent": self.total_spent,
            "total_payout": self.total_payout,
            "bought_tokens": list(self.bought_tokens),
            "started_at": self.trades[0].timestamp if self.trades else "",
            "trades": [
                {
                    "timestamp": t.timestamp,
                    "market": t.market,
                    "market_slug": t.market_slug,
                    "outcome": t.outcome,
                    "token_id": t.token_id,
                    "condition_id": t.condition_id,
                    "buy_price": t.buy_price,
                    "amount": t.amount,
                    "shares": t.shares,
                    "current_price": t.current_price,
                    "status": t.status,
                    "resolved_at": t.resolved_at,
                    "payout": t.payout,
                }
                for t in self.trades
            ],
        }
        PAPER_FILE.write_text(json.dumps(data, indent=2))

    def _reset_daily_if_needed(self):
        today = date.today().isoformat()
        if self.daily_date != today:
            self.daily_date = today
            self.daily_spent = 0.0

    def can_trade(self, amount: float) -> tuple[bool, str]:
        self._reset_daily_if_needed()
        remaining = self.budget - self.total_spent
        if amount > remaining:
            return False, f"Budget op: ${remaining:.2f} over van ${self.budget:.2f}"
        if self.daily_spent + amount > self.config.daily_loss_limit:
            return False, f"Daglimiet ${self.config.daily_loss_limit} bereikt"
        if amount > self.config.max_spend_per_trade:
            return False, f"Max ${self.config.max_spend_per_trade} per trade"
        return True, "OK"

    def buy(self, opp: PennyOpportunity, amount: float) -> PaperTrade | None:
        if opp.token_id in self.bought_tokens:
            return None

        can, reason = self.can_trade(amount)
        if not can:
            log.warning(f"Paper trade blocked: {reason}")
            return None

        shares = amount / opp.price
        trade = PaperTrade(
            timestamp=datetime.utcnow().isoformat(),
            market=opp.market_question,
            market_slug=opp.market_slug,
            outcome=opp.outcome,
            token_id=opp.token_id,
            condition_id=opp.condition_id,
            buy_price=opp.price,
            amount=amount,
            shares=shares,
            current_price=opp.price,
            status="open",
        )

        self.trades.append(trade)
        self.total_spent += amount
        self.daily_spent += amount
        self.bought_tokens.add(opp.token_id)
        self.save()

        log.info(
            f"PAPER BUY: {shares:.0f}x {opp.outcome} @ {opp.price*100:.1f}¢ "
            f"for ${amount:.2f} — {opp.market_question[:60]}"
        )
        return trade

    def check_resolutions(self, client) -> list[PaperTrade]:
        """Check which open positions have resolved. Returns newly resolved trades."""
        resolved = []
        for trade in self.trades:
            if trade.status != "open":
                continue

            # Try to get current price — if market resolved, price goes to 1.0 or 0.0
            try:
                price = float(client.get_price(trade.token_id, side="BUY"))
                trade.current_price = price

                if price >= 0.95:  # Resolved YES — we won
                    trade.status = "won"
                    trade.payout = trade.shares * 1.0
                    trade.resolved_at = datetime.utcnow().isoformat()
                    self.total_payout += trade.payout
                    resolved.append(trade)
                    log.info(
                        f"WON: {trade.outcome} — {trade.market[:50]} "
                        f"(${trade.amount:.2f} → ${trade.payout:.2f})"
                    )
                elif price <= 0.01 and trade.buy_price > 0.01:
                    trade.status = "lost"
                    trade.payout = 0.0
                    trade.resolved_at = datetime.utcnow().isoformat()
                    resolved.append(trade)
                    log.info(f"LOST: {trade.outcome} — {trade.market[:50]} (${trade.amount:.2f} → $0)")

            except Exception:
                pass  # Market still active or API error

        if resolved:
            self.save()
        return resolved

    def get_summary(self) -> str:
        open_trades = [t for t in self.trades if t.status == "open"]
        won = [t for t in self.trades if t.status == "won"]
        lost = [t for t in self.trades if t.status == "lost"]

        remaining = self.budget - self.total_spent
        pnl = self.total_payout - self.total_spent
        roi = (pnl / self.total_spent * 100) if self.total_spent > 0 else 0

        # Unrealized value of open positions at current prices
        unrealized = sum(t.shares * t.current_price for t in open_trades)

        lines = [
            f"📊 PAPER TRADING — Week Report",
            f"{'='*40}",
            f"Budget:     ${self.budget:.2f}",
            f"Spent:      ${self.total_spent:.2f}",
            f"Remaining:  ${remaining:.2f}",
            f"",
            f"Positions:  {len(self.trades)} total",
            f"  Open:     {len(open_trades)}",
            f"  Won:      {len(won)}",
            f"  Lost:     {len(lost)}",
            f"",
            f"Payouts:    ${self.total_payout:.2f}",
            f"Unrealized: ${unrealized:.2f}",
            f"P&L:        ${pnl:+.2f} ({roi:+.1f}%)",
            f"{'='*40}",
        ]

        if open_trades:
            lines.append("")
            lines.append("Open positions:")
            for t in open_trades:
                change = ((t.current_price - t.buy_price) / t.buy_price * 100) if t.buy_price > 0 else 0
                lines.append(
                    f"  ⏳ {t.outcome} @ {t.buy_price*100:.1f}¢ → {t.current_price*100:.1f}¢ "
                    f"({change:+.0f}%) — {t.market[:50]}"
                )

        if won:
            lines.append("")
            lines.append("Wins:")
            for t in won:
                lines.append(f"  ✅ ${t.amount:.2f} → ${t.payout:.2f} — {t.market[:50]}")

        if lost:
            lines.append("")
            lines.append("Losses:")
            for t in lost:
                lines.append(f"  ❌ ${t.amount:.2f} → $0 — {t.market[:50]}")

        return "\n".join(lines)

    def get_summary_short(self) -> str:
        open_t = len([t for t in self.trades if t.status == "open"])
        won = len([t for t in self.trades if t.status == "won"])
        lost = len([t for t in self.trades if t.status == "lost"])
        pnl = self.total_payout - self.total_spent
        return (
            f"Paper: ${self.total_spent:.0f} spent | "
            f"{open_t} open, {won} won, {lost} lost | "
            f"P&L: ${pnl:+.2f}"
        )
