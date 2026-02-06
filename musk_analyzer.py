"""Elon Musk Tweet Analyzer — Real-time tweet counting + range prediction."""
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
from tweet_tracker import fetch_musk_tweets, count_tweets_this_week, get_musk_activity_summary

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
    if httpx is None:
        return "No news (httpx not installed)"

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
                    text = resp.text
                    titles = []
                    for item in text.split("<item>")[1:6]:
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
    budget: float = 100.0,
    max_positions: int = 5,
) -> list[dict]:
    """Analyze Musk tweet markets using REAL tweet data + AI.

    The strategy:
    1. Fetch Musk's actual tweets this week
    2. Calculate posting speed (tweets/hour)
    3. Project weekly total
    4. Find ranges the market is underpricing
    5. AI validates and picks best entries
    """
    if not opportunities:
        log.info("No Musk tweet markets found")
        return []

    # === STEP 1: Get REAL tweet data ===
    tweets = fetch_musk_tweets()
    tweet_stats = count_tweets_this_week(tweets)
    tweet_summary = get_musk_activity_summary()
    log.info(f"Tweet data: {tweet_stats['tweets_this_week']} this week, "
             f"speed {tweet_stats['posting_speed_per_hour']}/hr, "
             f"projected {tweet_stats['projected_weekly_total']}")

    # === STEP 2: Get news context ===
    news = fetch_recent_news()

    # === STEP 3: Build market overview ===
    markets_text = ""
    for i, opp in enumerate(opportunities, 1):
        markets_text += (
            f"{i}. \"{opp.market_question}\" — {opp.outcome} @ "
            f"{opp.price*100:.1f}c (expires: {opp.end_date})\n"
        )

    # === STEP 4: AI analysis with real data ===
    if not ANTHROPIC_API_KEY or httpx is None:
        # No AI — use pure math projection
        return _math_only_picks(opportunities, tweet_stats, budget, max_positions)

    prompt = f"""You are a Polymarket trading bot specializing in Elon Musk tweet count markets.
You have REAL-TIME data on Musk's posting activity this week.

=== REAL TWEET DATA (LIVE) ===
{tweet_summary}

Projected weekly total: {tweet_stats['projected_weekly_total']} tweets
Projected range: {tweet_stats['projected_range']}
Current speed: {tweet_stats['posting_speed_per_hour']} tweets/hour
Hours remaining this week: {tweet_stats['hours_remaining']}

=== RECENT NEWS CONTEXT ===
{news}

=== AVAILABLE MARKETS ===
{markets_text}

=== YOUR STRATEGY ===
Based on the REAL posting data:
1. The projected total is {tweet_stats['projected_weekly_total']} ({tweet_stats['projected_range']})
2. Find markets where the outcome matches this projection but is priced LOW
3. Also consider: will Musk speed up or slow down? News events can change his pace
4. Buy ranges that OVERLAP with the projection — the market is undervaluing these
5. Spread ${budget:.0f} across {max_positions} positions max

KEY INSIGHT: If projected range is 200-280 and a "200-280" outcome is priced at 5c,
that's massively underpriced — the math says it should be much higher.

Respond in JSON:
{{
  "week_assessment": "busy/normal/quiet",
  "reasoning": "Based on real data: X tweets in Y hours = Z/hour, projecting to...",
  "estimated_tweet_range": "{tweet_stats['projected_range']}",
  "confidence_pct": 65,
  "picks": [
    {{
      "market_number": 1,
      "outcome": "YES/NO",
      "price_cents": 5,
      "allocate_usd": 5.00,
      "reasoning": "Projected range overlaps, market underpricing at 5c"
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
        return _math_only_picks(opportunities, tweet_stats, budget, max_positions)

    content = data.get("content", [{}])[0].get("text", "")

    try:
        text = content.strip()
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
        analysis = json.loads(text)
    except (json.JSONDecodeError, IndexError) as e:
        log.error(f"Failed to parse Claude response: {e}")
        return _math_only_picks(opportunities, tweet_stats, budget, max_positions)

    # Map picks back to opportunities
    results = []
    for pick in analysis.get("picks", []):
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
                "tweet_stats": tweet_stats,
            })

    log.info(
        f"Musk analysis: {analysis.get('week_assessment', '?')} week, "
        f"real data says {tweet_stats['projected_weekly_total']} projected, "
        f"{len(results)} picks"
    )
    return results


def _math_only_picks(
    opportunities: list[PennyOpportunity],
    stats: dict,
    budget: float,
    max_positions: int,
) -> list[dict]:
    """Pure math picks without AI — buys ranges that overlap with projection."""
    projected = stats["projected_weekly_total"]
    low = int(projected * 0.8)
    high = int(projected * 1.2)

    scored = []
    for opp in opportunities:
        # Try to extract numbers from outcome (e.g. "200-280" or "Yes" for "Will there be 200+ tweets")
        outcome_lower = opp.outcome.lower()
        question_lower = opp.market_question.lower()

        # Check if the outcome/question contains numbers that overlap with our range
        import re
        numbers = [int(n) for n in re.findall(r'\d+', outcome_lower + " " + question_lower)]

        overlap = False
        for n in numbers:
            if low <= n <= high:
                overlap = True
                break

        if overlap and opp.price < 0.20:
            # Score: cheaper = better (more upside)
            score = (1.0 / opp.price) if opp.price > 0 else 0
            scored.append((opp, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    results = []
    per_trade = budget / max_positions
    for opp, score in scored[:max_positions]:
        results.append({
            "opportunity": opp,
            "amount": per_trade,
            "reasoning": f"Math pick: projected {projected} ({stats['projected_range']}), price {opp.price*100:.1f}c",
            "confidence": "math_only",
            "estimated_range": stats["projected_range"],
            "week_reasoning": f"Based on {stats['tweets_this_week']} tweets in {stats['hours_elapsed']:.0f}h",
            "tweet_stats": stats,
        })

    log.info(f"Math picks: {len(results)} positions for projected {projected} tweets")
    return results


def format_musk_analysis_telegram(results: list[dict]) -> str:
    """Format Musk analysis for Telegram."""
    if not results:
        return "No Musk tweet markets found or analysis failed."

    first = results[0]
    stats = first.get("tweet_stats", {})

    msg = (
        f"<b>Musk Tweet Analysis</b>\n"
        f"Week: {first['confidence']}\n"
        f"Projected: {first['estimated_range']} tweets\n"
    )

    if stats:
        msg += (
            f"Live data: {stats.get('tweets_this_week', '?')} tweets in "
            f"{stats.get('hours_elapsed', '?')}h\n"
            f"Speed: {stats.get('posting_speed_per_hour', '?')}/hr\n"
        )

    msg += f"\nReason: {first['week_reasoning'][:150]}\n\n<b>Picks:</b>\n"

    total = 0
    for r in results:
        opp = r["opportunity"]
        potential = r["amount"] / opp.price if opp.price > 0 else 0
        msg += (
            f"  {opp.outcome} @ {opp.price*100:.1f}c — ${r['amount']:.2f}\n"
            f"    {opp.market_question[:60]}\n"
            f"    Potential: ${potential:.0f} | {r['reasoning'][:60]}\n\n"
        )
        total += r["amount"]

    msg += f"Total: ${total:.2f}"
    return msg
