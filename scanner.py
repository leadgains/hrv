"""Scans Polymarket for penny opportunities (shares priced 1-9 cents)."""

import logging
from dataclasses import dataclass
from py_clob_client.client import ClobClient

log = logging.getLogger(__name__)


@dataclass
class PennyOpportunity:
    market_question: str
    market_slug: str
    token_id: str
    outcome: str  # YES or NO
    price: float  # e.g. 0.03 = 3 cents
    condition_id: str
    end_date: str


def scan_for_pennies(
    client: ClobClient,
    min_cents: int = 1,
    max_cents: int = 9,
) -> list[PennyOpportunity]:
    """Find all shares priced between min_cents and max_cents."""
    opportunities = []
    min_price = min_cents / 100
    max_price = max_cents / 100

    log.info(f"Scanning for shares between {min_cents}¢ and {max_cents}¢...")

    next_cursor = ""
    page = 0
    while True:
        page += 1
        try:
            if next_cursor:
                resp = client.get_simplified_markets(next_cursor=next_cursor)
            else:
                resp = client.get_simplified_markets()
        except Exception as e:
            log.error(f"Failed to fetch markets page {page}: {e}")
            break

        markets = resp.get("data", [])
        if not markets:
            break

        for market in markets:
            if not market.get("active", False):
                continue
            if market.get("closed", True):
                continue

            question = market.get("question", "")
            slug = market.get("market_slug", "")
            condition_id = market.get("condition_id", "")
            end_date = market.get("end_date_iso", "")

            tokens = market.get("tokens", [])
            for token in tokens:
                token_id = token.get("token_id", "")
                outcome = token.get("outcome", "")
                price = token.get("price", 1.0)

                try:
                    price = float(price)
                except (ValueError, TypeError):
                    continue

                if min_price <= price <= max_price:
                    opportunities.append(PennyOpportunity(
                        market_question=question,
                        market_slug=slug,
                        token_id=token_id,
                        outcome=outcome,
                        price=price,
                        condition_id=condition_id,
                        end_date=end_date,
                    ))

        next_cursor = resp.get("next_cursor", "")
        if not next_cursor or next_cursor == "LTE=":
            break

    log.info(f"Found {len(opportunities)} penny opportunities across {page} pages")
    return opportunities
