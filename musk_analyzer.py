"""Elon Musk Tweet Analyzer — Predicts weekly tweet ranges for Polymarket."""
from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timedelta
try:
    import httpx
except ImportError:
    httpx = None

from scanner import PennyOpportunity

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")


def fetch_musk_tweet_markets(client) -> list[PennyOpportunity]:
    """Find all active Elon Musk tweet count markets on Polymarket."""
    opportunities = []
    next_cursor = ""

    while True:
        try:
            if next_cursor:
                resp = client.get_simplified_markets(next_cursor=next_cursor)
            else:
                resp = client.get_simplified_markets()
        except Exception as e:
            log.error(f"Failed to fetch markets: {e}")
            break

        markets = resp.get("data", [])
        if not markets:
            break

        for market in markets:
            if not market.get("active", False) or market.get("closed", True):
                continue

            question = market.get("question", "").lower()
            # Match Musk tweet markets
            if not any(kw in question for kw in [
                "musk", "elon", "tweet", "post", "@elonmusk",
                "x post", "how many", "tweets will"
            ]):
                continue

            slug = market.get("market_slug", "")
            condition_id = market.get("condition_id", "")
            end_date = market.get("end_date_iso", "")
            tokens = market.get("tokens", [])

            for token in tokens:
                token_id = token.get("token_id", "")
                outcome = token.get("outcome", "")
                price = float(token.get("price", 1.0))

                opportunities.append(PennyOpportunity(
                    market_question=market.get("question", ""),
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

    log.info(f"Found {len(opportunities)} Musk tweet market positions")
    return opportunities


def fetch_recent_news() -> str:
    """Fetch recent Tesla/SpaceX/Musk news for context."""
    queries = [
        "Elon Musk Twitter activity today",
        "Tesla SpaceX news today",
        "DOGE government Elon Musk",
    ]
    news_context = []

    for query in queries:
        try:
            with httpx.Client(timeout=15) as http:
                resp = http.get(
                    "https://news.google.com/rss/search",
                    params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                )
                if resp.status_code == 200:
                    # Simple XML title extraction
                    text = resp.text
                    titles = []
                    for item in text.split("<item>")[1:6]:  # top 5 items
                        title_start = item.find("<title>") + 7
                        title_end = item.find("</title>")
                        if title_start > 6 and title_end > title_start:
                            titles.append(item[title_start:title_end])
                    news_context.append(f"Query '{query}': {'; '.join(titles)}")
        except Exception as e:
            log.debug(f"News fetch failed for '{query}': {e}")

    return "\n".join(news_context) if news_context else "No recent news available."


def analyze_musk_markets(
    opportunities: list[PennyOpportunity],
    budget: float = 20.0,
    max_positions: int = 5,
) -> list[dict]:
    """Use Claude to analyze Musk tweet markets and pick best ranges.

    Returns list of {opportunity, amount, reasoning, confidence}.
    """
    if not opportunities:
        log.info("No Musk tweet markets found")
        return []

    if not ANTHROPIC_API_KEY:
        log.warning("No ANTHROPIC_API_KEY — cannot analyze Musk markets")
        return []

    # Fetch news context
    news = fetch_recent_news()

    # Build market overview
    markets_text = ""
    for i, opp in enumerate(opportunities, 1):
        markets_text += (
            f"{i}. \"{opp.market_question}\" — {opp.outcome} @ "
            f"{opp.price*100:.1f}¢ (expires: {opp.end_date})\n"
        )

    prompt = f"""You are an expert analyst of Elon Musk's Twitter/X posting behavior.
You're helping a trader decide which tweet-count ranges to buy on Polymarket.

BUDGET: ${budget:.2f}
MAX POSITIONS: {max_positions}

CURRENT MUSK-RELATED NEWS:
{news}

AVAILABLE MARKETS AND PRICES:
{markets_text}

YOUR TASK:
1. Based on Musk's typical posting patterns:
   - Normal weeks: 150-250 posts
   - Busy weeks (political drama, Tesla/SpaceX events): 300-500+ posts
   - Quiet weeks (travel, focus periods): 80-150 posts

2. Analyze the current news to determine if this is likely a busy, normal, or quiet week

3. Pick the {max_positions} best positions to buy. Focus on:
   - Ranges the market is UNDERPRICING (price too low for the actual probability)
   - Cheap shares (under 20¢) where a small bet gives huge upside
   - Spread across 2-3 adjacent ranges for safety

4. Allocate the ${budget:.2f} budget across your picks

Respond in JSON:
{{
  "week_assessment": "busy/normal/quiet",
  "reasoning": "Why you think this week will be busy/normal/quiet",
  "estimated_tweet_range": "e.g. 200-300",
  "picks": [
    {{
      "market_number": 1,
      "outcome": "YES/NO",
      "price_cents": 5,
      "allocate_usd": 4.00,
      "reasoning": "Why this range is underpriced"
    }}
  ]
}}"""

    try:
        with httpx.Client(timeout=60) as http:
            resp = http.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 2048,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.error(f"Claude API failed: {e}")
        return []

    content = data.get("content", [{}])[0].get("text", "")

    # Parse response
    try:
        text = content.strip()
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
        analysis = json.loads(text)
    except (json.JSONDecodeError, IndexError) as e:
        log.error(f"Failed to parse Claude response: {e}")
        log.debug(f"Response: {content[:500]}")
        return []

    # Map picks back to opportunities
    results = []
    picks = analysis.get("picks", [])

    for pick in picks:
        idx = pick.get("market_number", 0) - 1
        if 0 <= idx < len(opportunities):
            opp = opportunities[idx]
            results.append({
                "opportunity": opp,
                "amount": pick.get("allocate_usd", budget / max_positions),
                "reasoning": pick.get("reasoning", ""),
                "confidence": analysis.get("week_assessment", "unknown"),
                "estimated_range": analysis.get("estimated_tweet_range", "?"),
                "week_reasoning": analysis.get("reasoning", ""),
            })

    log.info(
        f"Musk analysis: {analysis.get('week_assessment', '?')} week, "
        f"est. {analysis.get('estimated_tweet_range', '?')} tweets, "
        f"{len(results)} picks"
    )
    return results


def format_musk_analysis_telegram(results: list[dict]) -> str:
    """Format Musk analysis for Telegram."""
    if not results:
        return "🔍 No Musk tweet markets found or analysis failed."

    first = results[0]
    msg = (
        f"🐦 <b>Musk Tweet Analysis</b>\n"
        f"Week type: {first['confidence']}\n"
        f"Estimated range: {first['estimated_range']} tweets\n"
        f"Reason: {first['week_reasoning'][:150]}\n\n"
        f"<b>Picks:</b>\n"
    )

    total = 0
    for r in results:
        opp = r["opportunity"]
        msg += (
            f"  {'🟢' if opp.price < 0.10 else '🟡'} {opp.outcome} @ "
            f"{opp.price*100:.1f}¢ — ${r['amount']:.2f}\n"
            f"    {opp.market_question[:60]}\n"
            f"    {r['reasoning'][:80]}\n\n"
        )
        total += r["amount"]

    msg += f"Total allocation: ${total:.2f}"
    return msg
