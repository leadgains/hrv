"""Musk Tweet Tracker — counts Elon's real-time posting activity."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

log = logging.getLogger(__name__)

CACHE_FILE = Path("musk_tweet_cache.json")

# Multiple sources to try, in order of reliability
SOURCES = [
    "fxtwitter",
    "syndication",
    "nitter",
]


def _fetch_fxtwitter() -> list[dict]:
    """Fetch recent Musk tweets via FixTweet API (no auth needed)."""
    tweets = []
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as http:
            # fxtwitter returns tweet data as JSON
            resp = http.get("https://api.fxtwitter.com/elonmusk")
            if resp.status_code == 200:
                data = resp.json()
                for tweet in data.get("tweets", []):
                    created = tweet.get("created_at", "")
                    tweets.append({
                        "text": tweet.get("text", "")[:200],
                        "created_at": created,
                        "id": tweet.get("id", ""),
                    })
            # Also try status-based to get more tweets
            resp2 = http.get("https://api.fxtwitter.com/elonmusk/status/latest")
            if resp2.status_code == 200:
                data2 = resp2.json()
                tweet = data2.get("tweet", {})
                if tweet.get("id"):
                    tweets.append({
                        "text": tweet.get("text", "")[:200],
                        "created_at": tweet.get("created_at", ""),
                        "id": tweet.get("id", ""),
                    })
    except Exception as e:
        log.debug(f"fxtwitter failed: {e}")
    return tweets


def _fetch_syndication() -> list[dict]:
    """Fetch via Twitter syndication endpoint."""
    tweets = []
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as http:
            resp = http.get(
                "https://syndication.twitter.com/srv/timeline-profile/screen-name/elonmusk",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                # Extract tweet text and timestamps from the HTML
                text = resp.text
                # Find tweet timestamps and text in the timeline HTML
                time_pattern = re.compile(r'datetime="([^"]+)"')
                tweet_pattern = re.compile(r'<p[^>]*dir="auto"[^>]*>([^<]+)</p>')
                times = time_pattern.findall(text)
                texts = tweet_pattern.findall(text)
                for i, t in enumerate(times[:50]):
                    tweets.append({
                        "text": texts[i][:200] if i < len(texts) else "",
                        "created_at": t,
                        "id": str(i),
                    })
    except Exception as e:
        log.debug(f"syndication failed: {e}")
    return tweets


def _fetch_nitter() -> list[dict]:
    """Fetch via Nitter RSS (public instances)."""
    tweets = []
    nitter_instances = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.net",
    ]
    for base in nitter_instances:
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as http:
                resp = http.get(f"{base}/elonmusk/rss")
                if resp.status_code == 200 and "<item>" in resp.text:
                    for item in resp.text.split("<item>")[1:50]:
                        title_start = item.find("<title>") + 7
                        title_end = item.find("</title>")
                        pub_start = item.find("<pubDate>") + 9
                        pub_end = item.find("</pubDate>")
                        if title_start > 6 and title_end > title_start:
                            tweets.append({
                                "text": item[title_start:title_end][:200],
                                "created_at": item[pub_start:pub_end] if pub_start > 8 else "",
                                "id": str(len(tweets)),
                            })
                    if tweets:
                        break
        except Exception as e:
            log.debug(f"nitter {base} failed: {e}")
            continue
    return tweets


def fetch_musk_tweets() -> list[dict]:
    """Fetch Musk's recent tweets from multiple sources. Returns list of tweet dicts."""
    if httpx is None:
        log.warning("httpx not installed — cannot fetch tweets")
        return []

    fetchers = {
        "fxtwitter": _fetch_fxtwitter,
        "syndication": _fetch_syndication,
        "nitter": _fetch_nitter,
    }

    all_tweets = []
    source_used = None

    for name, fetcher in fetchers.items():
        try:
            tweets = fetcher()
            if tweets:
                all_tweets = tweets
                source_used = name
                log.info(f"Got {len(tweets)} tweets from {name}")
                break
        except Exception as e:
            log.debug(f"Source {name} failed: {e}")

    if not all_tweets:
        log.warning("All tweet sources failed — using cache")
        return _load_cache()

    # Save to cache
    _save_cache(all_tweets, source_used)
    return all_tweets


def _parse_tweet_time(time_str: str) -> datetime | None:
    """Parse various tweet timestamp formats to UTC datetime."""
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%a, %d %b %Y %H:%M:%S %z",  # RSS pubDate format
        "%a, %d %b %Y %H:%M:%S GMT",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            continue
    return None


def count_tweets_this_week(tweets: list[dict]) -> dict:
    """Count tweets from the current week and calculate posting speed.

    Returns dict with:
        - tweets_this_week: int
        - tweets_today: int
        - posting_speed_per_hour: float
        - hours_elapsed: float (hours since Monday 00:00 UTC)
        - projected_weekly_total: int
        - projected_range: str (e.g. "200-280")
        - source_tweets: int (how many tweets we actually have data for)
    """
    now = datetime.now(timezone.utc)

    # Start of this week (Monday 00:00 UTC)
    days_since_monday = now.weekday()
    week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    tweets_this_week = 0
    tweets_today = 0

    for tweet in tweets:
        tweet_time = _parse_tweet_time(tweet.get("created_at", ""))
        if tweet_time is None:
            continue
        if tweet_time >= week_start:
            tweets_this_week += 1
        if tweet_time >= today_start:
            tweets_today += 1

    # Hours elapsed since week start
    hours_elapsed = max((now - week_start).total_seconds() / 3600, 1)
    hours_in_week = 168  # 7 * 24

    # Posting speed
    speed_per_hour = tweets_this_week / hours_elapsed if hours_elapsed > 0 else 0

    # Project to full week
    projected = int(speed_per_hour * hours_in_week)

    # Range estimate (±15%)
    low = int(projected * 0.85)
    high = int(projected * 1.15)

    return {
        "tweets_this_week": tweets_this_week,
        "tweets_today": tweets_today,
        "posting_speed_per_hour": round(speed_per_hour, 2),
        "hours_elapsed": round(hours_elapsed, 1),
        "hours_remaining": round(hours_in_week - hours_elapsed, 1),
        "projected_weekly_total": projected,
        "projected_range": f"{low}-{high}",
        "source_tweets": len(tweets),
    }


def get_musk_activity_summary() -> str:
    """Get a human-readable summary of Musk's current posting activity."""
    tweets = fetch_musk_tweets()
    if not tweets:
        return "Could not fetch Musk tweet data — all sources failed."

    stats = count_tweets_this_week(tweets)

    # Determine activity level
    speed = stats["posting_speed_per_hour"]
    if speed > 5:
        level = "VERY ACTIVE (storm mode)"
    elif speed > 3:
        level = "ACTIVE (busy week)"
    elif speed > 1.5:
        level = "NORMAL"
    elif speed > 0.5:
        level = "QUIET"
    else:
        level = "VERY QUIET"

    return (
        f"Musk Tweet Tracker:\n"
        f"  This week: {stats['tweets_this_week']} tweets in {stats['hours_elapsed']:.0f}h\n"
        f"  Today: {stats['tweets_today']} tweets\n"
        f"  Speed: {speed:.1f} tweets/hour\n"
        f"  Activity: {level}\n"
        f"  Projected week total: {stats['projected_weekly_total']} ({stats['projected_range']})\n"
        f"  Hours left: {stats['hours_remaining']:.0f}h\n"
        f"  Data from: {stats['source_tweets']} recent tweets"
    )


def _load_cache() -> list[dict]:
    """Load cached tweet data."""
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            return data.get("tweets", [])
        except (json.JSONDecodeError, KeyError):
            pass
    return []


def _save_cache(tweets: list[dict], source: str | None):
    """Cache tweet data."""
    data = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": source or "unknown",
        "count": len(tweets),
        "tweets": tweets[:100],  # Keep max 100
    }
    CACHE_FILE.write_text(json.dumps(data, indent=2))
