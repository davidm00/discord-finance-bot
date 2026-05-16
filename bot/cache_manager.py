"""HTTP caching via requests-cache with SQLite backend and per-URL TTL rules."""

from __future__ import annotations

import os
from datetime import timedelta

import requests_cache


CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "http_cache")


def install_cache():
    """Install requests-cache with SQLite backend and per-URL TTL rules."""
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)

    urls_expire_after = {
        # Crypto — 5 minutes
        "api.coingecko.com": 300,
        "api.binance.us": 300,
        # News — 30 minutes
        "finnhub.io/api/v1/news*": 1800,
        "feeds.bloomberg.com": 1800,
        "search.cnbc.com": 1800,
        "feeds.content.dowjones.io": 1800,
        # Political trades — 12 hours
        "www.capitoltrades.com": 43200,
        # Government contracts — 24 hours
        "api.usaspending.gov": 86400,
        # Earnings calendar — 1 hour
        "finnhub.io/api/v1/calendar*": 3600,
        # Fear & Greed — 1 hour
        "api.alternative.me": 3600,
        "production.dataviz.cnn.io": 3600,
        # Default — 15 minutes
        "*": 900,
    }

    requests_cache.install_cache(
        cache_name=CACHE_PATH,
        backend="sqlite",
        urls_expire_after=urls_expire_after,
        stale_if_error=timedelta(hours=6),
    )
    print(f"[cache] HTTP cache installed at {CACHE_PATH}.sqlite")


def get_cache_info() -> str:
    """Return basic cache stats for logging."""
    try:
        session = requests_cache.get_cache()
        count = len(session.responses) if hasattr(session, "responses") else "unknown"
        return f"[cache] Cache entries: {count}"
    except Exception:
        return "[cache] Cache stats unavailable"
