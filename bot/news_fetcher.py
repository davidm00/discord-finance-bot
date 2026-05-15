from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import pytz
import requests


ET_TZ = pytz.timezone("America/New_York")

CNBC_RSS = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"
MARKETWATCH_RSS = "https://feeds.content.dowjones.io/public/rss/mw_topstories"
BLOOMBERG_RSS = "https://feeds.bloomberg.com/markets/news.rss"

FINNHUB_GENERAL_NEWS = "https://finnhub.io/api/v1/news"


def _dt_to_et_string(dt: datetime) -> str:
    return dt.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")


def _safe_source(val: Any) -> str:
    if not val:
        return "Unknown"
    return str(val).strip()


def _parse_rss_published(entry: dict[str, Any]) -> datetime:
    # Try to parse the published timestamp into a timezone-aware datetime.
    for key in ("published", "updated"):
        val = entry.get(key)
        if not val:
            continue
        try:
            dt = parsedate_to_datetime(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue

    # Fallback: use current time in ET.
    return datetime.now(ET_TZ)


def _parse_finnhub_unix(ts: Any) -> datetime:
    try:
        sec = int(ts)
    except Exception:
        return datetime.now(ET_TZ)
    return datetime.fromtimestamp(sec, tz=timezone.utc)


def _fetch_finnhub() -> list[dict[str, Any]]:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        print("WARNING: FINNHUB_API_KEY not set; skipping Finnhub news.", file=sys.stderr)
        return []

    print("Fetching Finnhub general market news...", file=sys.stdout)

    try:
        resp = requests.get(
            FINNHUB_GENERAL_NEWS,
            params={"category": "general", "token": api_key},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"WARNING: Finnhub request failed: {exc}", file=sys.stderr)
        return []

    if not (200 <= resp.status_code < 300):
        print(f"WARNING: Finnhub returned {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        return []

    try:
        data = resp.json()
    except Exception as exc:
        print(f"WARNING: Finnhub JSON parse failed: {exc}", file=sys.stderr)
        return []

    if not isinstance(data, list) or not data:
        print("WARNING: Finnhub returned empty news list.", file=sys.stderr)
        return []

    items: list[dict[str, Any]] = []
    for a in data[:10]:
        try:
            headline = str(a.get("headline") or "").strip()
            url = str(a.get("url") or "").strip()
            source = _safe_source(a.get("source"))
            published_dt = _parse_finnhub_unix(a.get("datetime"))

            if not headline or not url:
                continue

            items.append(
                {
                    "headline": headline,
                    "source": source,
                    "url": url,
                    "published_dt": published_dt,
                    "published_et": _dt_to_et_string(published_dt),
                }
            )
        except Exception:
            continue

    return items


def _fetch_rss_feed(url: str, source_name: str, limit: int = 5) -> list[dict[str, Any]]:
    print(f"Fetching RSS: {source_name}...", file=sys.stdout)

    try:
        parsed = feedparser.parse(url)
    except Exception as exc:
        print(f"WARNING: RSS parse failed for {source_name}: {exc}", file=sys.stderr)
        return []

    if getattr(parsed, "bozo", False):
        bozo_exc = getattr(parsed, "bozo_exception", None)
        if bozo_exc:
            print(f"WARNING: RSS bozo for {source_name}: {bozo_exc}", file=sys.stderr)

    entries = getattr(parsed, "entries", None) or []
    if not entries:
        print(f"WARNING: RSS feed empty for {source_name}", file=sys.stderr)
        return []

    items: list[dict[str, Any]] = []
    for e in entries[:limit]:
        try:
            title = str(e.get("title") or "").strip()
            link = str(e.get("link") or "").strip()
            if not title or not link:
                continue

            published_dt = _parse_rss_published(e)
            items.append(
                {
                    "headline": title,
                    "source": source_name,
                    "url": link,
                    "published_dt": published_dt,
                    "published_et": _dt_to_et_string(published_dt),
                }
            )
        except Exception:
            continue

    return items


def fetch_top_headlines() -> list[dict[str, str]]:
    """Fetch and aggregate top headlines from Finnhub + RSS.

    Returns top 10 most recent items:
      {"headline": str, "source": str, "url": str, "published_et": str}
    """

    all_items: list[dict[str, Any]] = []

    all_items.extend(_fetch_finnhub())

    all_items.extend(_fetch_rss_feed(CNBC_RSS, "CNBC", limit=5))
    all_items.extend(_fetch_rss_feed(MARKETWATCH_RSS, "MarketWatch", limit=5))
    all_items.extend(_fetch_rss_feed(BLOOMBERG_RSS, "Bloomberg", limit=5))

    if not all_items:
        print("WARNING: No headlines collected from Finnhub or RSS.", file=sys.stderr)
        return []

    # Deduplicate by URL.
    dedup: dict[str, dict[str, Any]] = {}
    for it in all_items:
        url = str(it.get("url") or "").strip()
        if not url:
            continue
        if url in dedup:
            # Keep the most recent timestamp.
            if it.get("published_dt") and dedup[url].get("published_dt"):
                if it["published_dt"] > dedup[url]["published_dt"]:
                    dedup[url] = it
            continue
        dedup[url] = it

    items = list(dedup.values())

    # Sort by published_dt descending.
    items.sort(key=lambda x: x.get("published_dt") or datetime.min.replace(tzinfo=ET_TZ), reverse=True)

    top = items[:10]

    result: list[dict[str, str]] = []
    for it in top:
        result.append(
            {
                "headline": str(it.get("headline") or "").strip(),
                "source": str(it.get("source") or "Unknown").strip(),
                "url": str(it.get("url") or "").strip(),
                "published_et": str(it.get("published_et") or "").strip(),
            }
        )

    if not result:
        print("WARNING: Headline aggregation produced zero items.", file=sys.stderr)

    return result
