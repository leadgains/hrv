"""Executes penny trades on Polymarket."""
from __future__ import annotations

import logging
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import MarketOrderArgs, OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY
except ImportError:
    ClobClient = None  # Demo mode — no trading

from config import Config
from scanner import PennyOpportunity

log = logging.getLogger(__name__)

TRADES_FILE = Path("trades.json")


@dataclass
class TradeRecord:
    timestamp: str
    market: str
    outcome: str
    token_id: str
    price: float
    amount: float
    shares: float
    status: str  # "open", "won", "lost"


@dataclass
class Trader:
    config: Config
    client: ClobClient
    total_spent: float = 0.0
    daily_spent: float = 0.0
    daily_date: str = ""
    trades: list[TradeRecord] = field(default_factory=list)
    bought_tokens: set = field(default_factory=set)

    def __post_init__(self):
        self._load_trades()

    def _load_trades(self):
        if TRADES_FILE.exists():
            data = json.loads(TRADES_FILE.read_text())
            self.total_spent = data.get("total_spent", 0.0)
            self.bought_tokens = set(data.get("bought_tokens", []))
            self.trades = [TradeRecord(**t) for t in data.get("trades", [])]
            log.info(f"Loaded {len(self.trades)} previous trades, ${self.total_spent:.2f} spent")

    def _save_trades(self):
        data = {
            "total_spent": self.total_spent,
            "bought_tokens": list(self.bought_tokens),
            "trades": [
                {
                    "timestamp": t.timestamp,
                    "market": t.market,
                    "outcome": t.outcome,
                    "token_id": t.token_id,
                    "price": t.price,
                    "amount": t.amount,
                    "shares": t.shares,
                    "status": t.status,
                }
                for t in self.trades
            ],
        }
        TRADES_FILE.write_text(json.dumps(data, indent=2))

    def _reset_daily_if_needed(self):
        today = date.today().isoformat()
        if self.daily_date != today:
            self.daily_date = today
            self.daily_spent = 0.0

    def can_trade(self, amount: float) -> tuple[bool, str]:
        self._reset_daily_if_needed()

        if self.total_spent + amount > self.config.total_budget:
            return False, f"Total budget ${self.config.total_budget} reached (spent: ${self.total_spent:.2f})"

        if self.daily_spent + amount > self.config.daily_loss_limit:
            return False, f"Daily limit ${self.config.daily_loss_limit} reached (today: ${self.daily_spent:.2f})"

        if amount > self.config.max_spend_per_trade:
            return False, f"Trade ${amount} exceeds max ${self.config.max_spend_per_trade} per trade"

        return True, "OK"

    def execute_trade(self, opp: PennyOpportunity, amount: float) -> dict | None:
        """Buy penny shares. Returns order response or None on failure."""
        if opp.token_id in self.bought_tokens:
            log.info(f"Already bought {opp.outcome} on '{opp.market_question[:50]}', skipping")
            return None

        can, reason = self.can_trade(amount)
        if not can:
            log.warning(f"Cannot trade: {reason}")
            return None

        shares = amount / opp.price

        log.info(
            f"BUYING {shares:.0f} shares of {opp.outcome} @ {opp.price*100:.1f}¢ "
            f"for ${amount:.2f} on '{opp.market_question[:60]}'"
        )

        try:
            # Use limit order at the penny price to avoid slippage
            order_args = OrderArgs(
                token_id=opp.token_id,
                price=opp.price,
                size=shares,
                side=BUY,
            )
            signed_order = self.client.create_order(order_args)
            resp = self.client.post_order(signed_order, OrderType.GTC)

            log.info(f"Order placed: {resp}")

            trade = TradeRecord(
                timestamp=datetime.utcnow().isoformat(),
                market=opp.market_question,
                outcome=opp.outcome,
                token_id=opp.token_id,
                price=opp.price,
                amount=amount,
                shares=shares,
                status="open",
            )
            self.trades.append(trade)
            self.total_spent += amount
            self.daily_spent += amount
            self.bought_tokens.add(opp.token_id)
            self._save_trades()

            return resp

        except Exception as e:
            log.error(f"Trade failed: {e}")
            return None

    def get_summary(self) -> str:
        open_trades = [t for t in self.trades if t.status == "open"]
        won = [t for t in self.trades if t.status == "won"]
        lost = [t for t in self.trades if t.status == "lost"]
        return (
            f"📊 Portfolio Summary\n"
            f"Total spent: ${self.total_spent:.2f} / ${self.config.total_budget:.2f}\n"
            f"Open positions: {len(open_trades)}\n"
            f"Won: {len(won)} | Lost: {len(lost)}\n"
            f"Potential max payout: ${sum(t.shares for t in open_trades):.2f}"
        )
