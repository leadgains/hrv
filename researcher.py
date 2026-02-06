"""AI Research Layer — Uses Claude to analyze penny opportunities before buying."""
from __future__ import annotations

import os
import json
import logging
try:
    import httpx
except ImportError:
    httpx = None
from dataclasses import dataclass

from scanner import PennyOpportunity

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")


@dataclass
class ResearchResult:
    opportunity: PennyOpportunity
    score: float  # 0-100, higher = more likely mispriced (good buy)
    reasoning: str
    fair_value_estimate: float  # estimated true probability
    recommendation: str  # "BUY", "SKIP", "WATCH"
    confidence: str  # "LOW", "MEDIUM", "HIGH"


def build_research_prompt(opportunities: list[PennyOpportunity]) -> str:
    """Build prompt for Claude to analyze penny opportunities."""
    markets_text = ""
    for i, opp in enumerate(opportunities, 1):
        markets_text += (
            f"\n{i}. Market: \"{opp.market_question}\"\n"
            f"   Outcome: {opp.outcome}\n"
            f"   Current price: {opp.price*100:.1f}¢ (market says {opp.price*100:.1f}% chance)\n"
            f"   Expires: {opp.end_date}\n"
            f"   Slug: {opp.market_slug}\n"
        )

    return f"""You are a Polymarket prediction market analyst. Your job is to find MISPRICED shares — outcomes the market is undervaluing.

You're looking at shares priced between 1-9 cents. Most of these are correctly priced (very unlikely events). But some are genuinely undervalued — the true probability is higher than the market price suggests.

ANALYZE each market below. For each one:
1. Consider what the question is actually asking
2. Think about current events, trends, and real-world context (use your knowledge)
3. Estimate the TRUE probability of the outcome happening
4. Compare your estimate to the market price
5. If your estimate is significantly higher than the market price → it's a BUY

Be rigorous. Most penny shares ARE correctly priced. Only recommend BUY if you have a genuine reason to think the market is wrong.

MARKETS TO ANALYZE:
{markets_text}

Respond in JSON format:
{{
  "analyses": [
    {{
      "market_number": 1,
      "market_question": "...",
      "outcome": "YES/NO",
      "current_price_cents": 3,
      "your_estimated_probability_pct": 8,
      "reasoning": "Brief explanation of why you think this is mispriced or correctly priced",
      "recommendation": "BUY" or "SKIP" or "WATCH",
      "confidence": "LOW" or "MEDIUM" or "HIGH",
      "score": 0-100
    }}
  ]
}}

IMPORTANT RULES:
- Only recommend BUY if your estimated probability is at least 2x the current price
- A 3¢ share means the market thinks there's a 3% chance. If you think it's really 6%+, that's a BUY.
- Consider timing — events happening soon with new information the market hasn't priced in are the best opportunities
- Be honest when you don't know enough about a topic — mark those as SKIP with LOW confidence
- Think about what could cause a surprise outcome that the crowd is underestimating"""


def research_opportunities(
    opportunities: list[PennyOpportunity],
    batch_size: int = 10,
) -> list[ResearchResult]:
    """Send opportunities to Claude for analysis. Returns scored results."""
    if not ANTHROPIC_API_KEY:
        log.warning("No ANTHROPIC_API_KEY set — skipping AI research, buying blind")
        return [
            ResearchResult(
                opportunity=opp,
                score=50,
                reasoning="No AI analysis (API key not set)",
                fair_value_estimate=opp.price,
                recommendation="BUY",
                confidence="LOW",
            )
            for opp in opportunities
        ]

    results = []

    # Process in batches
    for i in range(0, len(opportunities), batch_size):
        batch = opportunities[i:i + batch_size]
        batch_results = _analyze_batch(batch)
        results.extend(batch_results)

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)
    return results


def _analyze_batch(opportunities: list[PennyOpportunity]) -> list[ResearchResult]:
    """Analyze a batch of opportunities with Claude."""
    prompt = build_research_prompt(opportunities)

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
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

    except Exception as e:
        log.error(f"Claude API call failed: {e}")
        return [
            ResearchResult(
                opportunity=opp, score=50, reasoning=f"API error: {e}",
                fair_value_estimate=opp.price, recommendation="SKIP", confidence="LOW",
            )
            for opp in opportunities
        ]

    # Parse Claude's response
    content = data.get("content", [{}])[0].get("text", "")
    return _parse_research_response(content, opportunities)


def _parse_research_response(
    response_text: str, opportunities: list[PennyOpportunity]
) -> list[ResearchResult]:
    """Parse Claude's JSON response into ResearchResults."""
    results = []

    try:
        # Find JSON in the response (Claude sometimes wraps in markdown)
        text = response_text.strip()
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
        data = json.loads(text)
        analyses = data.get("analyses", [])
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        log.error(f"Failed to parse Claude response: {e}")
        log.debug(f"Response was: {response_text[:500]}")
        return [
            ResearchResult(
                opportunity=opp, score=50, reasoning="Parse error",
                fair_value_estimate=opp.price, recommendation="SKIP", confidence="LOW",
            )
            for opp in opportunities
        ]

    for analysis in analyses:
        idx = analysis.get("market_number", 0) - 1
        if 0 <= idx < len(opportunities):
            opp = opportunities[idx]
            results.append(ResearchResult(
                opportunity=opp,
                score=analysis.get("score", 50),
                reasoning=analysis.get("reasoning", ""),
                fair_value_estimate=analysis.get("your_estimated_probability_pct", opp.price * 100) / 100,
                recommendation=analysis.get("recommendation", "SKIP"),
                confidence=analysis.get("confidence", "LOW"),
            ))

    # Add any opportunities that weren't in the response
    analyzed_indices = {a.get("market_number", 0) - 1 for a in analyses}
    for i, opp in enumerate(opportunities):
        if i not in analyzed_indices:
            results.append(ResearchResult(
                opportunity=opp, score=0, reasoning="Not analyzed",
                fair_value_estimate=opp.price, recommendation="SKIP", confidence="LOW",
            ))

    return results


def format_research_for_telegram(results: list[ResearchResult], top_n: int = 5) -> str:
    """Format research results for Telegram notification."""
    buys = [r for r in results if r.recommendation == "BUY"]
    watches = [r for r in results if r.recommendation == "WATCH"]

    msg = f"🧠 <b>AI Research Complete</b>\n"
    msg += f"Analyzed: {len(results)} markets\n"
    msg += f"Buy signals: {len(buys)} | Watch: {len(watches)}\n\n"

    for r in buys[:top_n]:
        opp = r.opportunity
        msg += (
            f"🟢 <b>BUY</b> — Score: {r.score}/100 ({r.confidence})\n"
            f"  {opp.market_question[:70]}\n"
            f"  {opp.outcome} @ {opp.price*100:.1f}¢ → est. {r.fair_value_estimate*100:.0f}%\n"
            f"  {r.reasoning[:100]}\n\n"
        )

    if not buys:
        msg += "No buy signals this cycle. All penny shares look correctly priced.\n"

    return msg
