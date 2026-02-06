"""Trade Analyzer — AI reviews every open/close and learns from results."""
from __future__ import annotations

import os
import json
import logging
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
LEARNING_FILE = Path("trade_learnings.json")


def _load_learnings() -> dict:
    """Load accumulated trade learnings."""
    if LEARNING_FILE.exists():
        return json.loads(LEARNING_FILE.read_text())
    return {
        "total_analyzed": 0,
        "wins": 0,
        "losses": 0,
        "open": 0,
        "insights": [],
        "pattern_notes": [],
        "strategy_scores": {},
        "trade_log": [],
    }


def _save_learnings(data: dict):
    """Save learnings to disk."""
    LEARNING_FILE.write_text(json.dumps(data, indent=2))


def get_learnings_summary() -> str:
    """Get a summary of accumulated learnings for the AI prompt."""
    data = _load_learnings()
    if not data["insights"]:
        return "No trade history yet — first trades."

    lines = [
        f"Trade history: {data['total_analyzed']} analyzed, {data['wins']} won, {data['losses']} lost",
    ]

    # Strategy performance
    for strat, scores in data.get("strategy_scores", {}).items():
        lines.append(f"  {strat}: {scores.get('wins', 0)}W/{scores.get('losses', 0)}L")

    # Recent insights (last 10)
    if data["insights"]:
        lines.append("\nKey learnings from past trades:")
        for insight in data["insights"][-10:]:
            lines.append(f"  - {insight}")

    # Pattern notes
    if data["pattern_notes"]:
        lines.append("\nPatterns observed:")
        for note in data["pattern_notes"][-5:]:
            lines.append(f"  - {note}")

    return "\n".join(lines)


def analyze_trade_open(trade: dict, strategy: str, all_trades: list[dict]) -> str | None:
    """AI analyzes a newly opened trade. Returns analysis text."""
    if not ANTHROPIC_API_KEY or httpx is None:
        return None

    learnings = get_learnings_summary()
    recent_trades = all_trades[-10:] if all_trades else []
    recent_text = ""
    for t in recent_trades:
        change = ((t["current_price"] - t["buy_price"]) / t["buy_price"] * 100) if t["buy_price"] > 0 else 0
        recent_text += f"  {t['status']}: {t['outcome']} @ {t['buy_price']*100:.1f}c -> {t['current_price']*100:.1f}c ({change:+.0f}%) — {t['market'][:50]}\n"

    prompt = f"""You are a trade analyst for a Polymarket penny bot. A new position was just opened.

NEW TRADE:
  Strategy: {strategy}
  Market: {trade['market']}
  Side: {trade['outcome']}
  Buy price: {trade['buy_price']*100:.1f} cents
  Amount: ${trade['amount']:.2f}
  Shares: {trade['shares']:.0f}
  Max payout if wins: ${trade['shares']:.2f}

RECENT TRADES IN THIS STRATEGY:
{recent_text if recent_text else "  (none yet)"}

PAST LEARNINGS:
{learnings}

ANALYZE THIS TRADE in 2-3 sentences:
1. Is this a good entry? Why or why not?
2. What would make this trade win or lose?
3. Any red flags based on past patterns?

Also provide ONE improvement suggestion for the strategy.

Respond in JSON:
{{
  "quality": "good" or "okay" or "risky",
  "analysis": "2-3 sentence analysis",
  "win_scenario": "what needs to happen to win",
  "risk": "main risk factor",
  "suggestion": "one concrete improvement idea"
}}"""

    try:
        with httpx.Client(timeout=30) as http:
            resp = http.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            content = resp.json().get("content", [{}])[0].get("text", "")
    except Exception as e:
        log.error(f"Trade analysis failed: {e}")
        return None

    # Parse and save
    try:
        text = content.strip()
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1]
        analysis = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        log.debug(f"Could not parse analysis: {content[:200]}")
        return content[:200]

    # Log it
    data = _load_learnings()
    data["total_analyzed"] += 1
    data["open"] += 1
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "open",
        "strategy": strategy,
        "market": trade["market"][:80],
        "outcome": trade["outcome"],
        "price": trade["buy_price"],
        "quality": analysis.get("quality", "?"),
        "analysis": analysis.get("analysis", ""),
        "suggestion": analysis.get("suggestion", ""),
    }
    data["trade_log"].append(entry)

    # Keep suggestion as insight if it's new
    suggestion = analysis.get("suggestion", "")
    if suggestion and suggestion not in data["insights"]:
        data["insights"].append(suggestion)
        # Keep max 20 insights
        if len(data["insights"]) > 20:
            data["insights"] = data["insights"][-20:]

    _save_learnings(data)

    quality_icon = {"good": "G", "okay": "O", "risky": "R"}.get(analysis.get("quality", ""), "?")
    result = (
        f"[{quality_icon}] {analysis.get('analysis', '')}\n"
        f"Win if: {analysis.get('win_scenario', '?')}\n"
        f"Risk: {analysis.get('risk', '?')}"
    )
    log.info(f"[{strategy}] ANALYSIS: {result[:150]}")
    return result


def analyze_trade_close(trade: dict, strategy: str, all_trades: list[dict]) -> str | None:
    """AI analyzes a closed trade (won/lost). Returns analysis + learnings."""
    if not ANTHROPIC_API_KEY or httpx is None:
        return None

    learnings = get_learnings_summary()
    won = trade["status"] == "won"
    pnl = trade.get("payout", 0) - trade["amount"]
    hold_time = ""
    if trade.get("resolved_at") and trade.get("timestamp"):
        try:
            opened = datetime.fromisoformat(trade["timestamp"])
            closed = datetime.fromisoformat(trade["resolved_at"])
            hours = (closed - opened).total_seconds() / 3600
            hold_time = f"{hours:.1f} hours" if hours < 48 else f"{hours/24:.1f} days"
        except (ValueError, TypeError):
            pass

    # Stats for this strategy
    strat_trades = [t for t in all_trades if t["status"] in ("won", "lost")]
    wins = len([t for t in strat_trades if t["status"] == "won"])
    losses = len([t for t in strat_trades if t["status"] == "lost"])

    prompt = f"""You are a trade analyst reviewing a CLOSED position on Polymarket.

CLOSED TRADE:
  Result: {"WON" if won else "LOST"}
  Strategy: {strategy}
  Market: {trade['market']}
  Side: {trade['outcome']}
  Buy price: {trade['buy_price']*100:.1f} cents
  Final price: {trade['current_price']*100:.1f} cents
  Amount spent: ${trade['amount']:.2f}
  Payout: ${trade.get('payout', 0):.2f}
  P&L: ${pnl:+.2f}
  Hold time: {hold_time or 'unknown'}

STRATEGY STATS: {wins}W / {losses}L out of {len(strat_trades)} resolved

PAST LEARNINGS:
{learnings}

ANALYZE in 2-3 sentences:
1. Why did this trade {"win" if won else "lose"}?
2. Was this predictable? Could we have avoided it (if loss) or repeated it (if win)?
3. What pattern does this reveal?

Respond in JSON:
{{
  "result_analysis": "2-3 sentence analysis of why it won/lost",
  "was_predictable": true/false,
  "pattern": "one pattern this reveals about the market/strategy",
  "adjustment": "concrete adjustment to improve the strategy",
  "confidence_in_strategy": "increase" or "decrease" or "same"
}}"""

    try:
        with httpx.Client(timeout=30) as http:
            resp = http.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            content = resp.json().get("content", [{}])[0].get("text", "")
    except Exception as e:
        log.error(f"Close analysis failed: {e}")
        return None

    try:
        text = content.strip()
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1]
        analysis = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        log.debug(f"Could not parse close analysis: {content[:200]}")
        return content[:200]

    # Save learnings
    data = _load_learnings()
    if won:
        data["wins"] += 1
    else:
        data["losses"] += 1
    data["open"] = max(0, data["open"] - 1)

    # Update strategy scores
    if strategy not in data["strategy_scores"]:
        data["strategy_scores"][strategy] = {"wins": 0, "losses": 0}
    if won:
        data["strategy_scores"][strategy]["wins"] += 1
    else:
        data["strategy_scores"][strategy]["losses"] += 1

    # Save pattern and adjustment as learnings
    pattern = analysis.get("pattern", "")
    adjustment = analysis.get("adjustment", "")
    if pattern and pattern not in data["pattern_notes"]:
        data["pattern_notes"].append(pattern)
        if len(data["pattern_notes"]) > 15:
            data["pattern_notes"] = data["pattern_notes"][-15:]
    if adjustment and adjustment not in data["insights"]:
        data["insights"].append(adjustment)
        if len(data["insights"]) > 20:
            data["insights"] = data["insights"][-20:]

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "close",
        "result": "won" if won else "lost",
        "strategy": strategy,
        "market": trade["market"][:80],
        "outcome": trade["outcome"],
        "buy_price": trade["buy_price"],
        "final_price": trade["current_price"],
        "pnl": pnl,
        "pattern": pattern,
        "adjustment": adjustment,
    }
    data["trade_log"].append(entry)
    _save_learnings(data)

    icon = "W" if won else "L"
    result = (
        f"[{icon}] {analysis.get('result_analysis', '')}\n"
        f"Pattern: {pattern}\n"
        f"Adjust: {adjustment}"
    )
    log.info(f"[{strategy}] CLOSE ANALYSIS: {result[:150]}")
    return result


def get_strategy_report() -> str:
    """Generate a full strategy report from learnings."""
    data = _load_learnings()
    lines = [
        "=== TRADE ANALYZER REPORT ===",
        f"Total analyzed: {data['total_analyzed']}",
        f"Results: {data['wins']}W / {data['losses']}L / {data['open']} open",
        "",
    ]

    for strat, scores in data.get("strategy_scores", {}).items():
        w = scores.get("wins", 0)
        l = scores.get("losses", 0)
        total = w + l
        wr = (w / total * 100) if total > 0 else 0
        lines.append(f"{strat}: {w}W/{l}L ({wr:.0f}% win rate)")

    if data["insights"]:
        lines.append("\nKey Insights:")
        for i in data["insights"][-10:]:
            lines.append(f"  * {i}")

    if data["pattern_notes"]:
        lines.append("\nPatterns:")
        for p in data["pattern_notes"][-5:]:
            lines.append(f"  * {p}")

    return "\n".join(lines)
