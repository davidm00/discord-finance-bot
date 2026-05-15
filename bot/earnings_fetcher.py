from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Any

import requests


THEMATIC_WATCHLIST = {
    "defense": ["LMT", "RTX", "NOC", "GD", "BA", "LDOS", "SAIC", "BAH", "HII", "TDG"],
    "cyber": ["CRWD", "PANW", "ZS", "FTNT", "S", "CYBR", "PLTR"],
    "energy": ["XOM", "CVX", "COP", "SLB", "HAL", "EOG", "MPC"],
    "tech": ["NVDA", "AMD", "MSFT", "GOOGL", "META", "AMZN", "AAPL"],
}

WATCHLIST_TICKERS = {t for lst in THEMATIC_WATCHLIST.values() for t in lst}

# Simple "major tickers" set to approximate S&P 500 membership (not exhaustive).
MAJOR_SP500_TICKERS = {
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "AMD",
    "TSLA",
    "JPM",
    "BAC",
    "WMT",
    "COST",
    "UNH",
    "LLY",
    "XOM",
    "CVX",
    "BRK.B",
    "BRK.A",
    "V",
    "MA",
    "AVGO",
    "ORCL",
    "NFLX",
    "ADBE",
    "CRM",
}


def fetch_upcoming_earnings() -> list[dict[str, Any]]:
    key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not key:
        print("[earnings_fetcher] WARNING: FINNHUB_API_KEY not set; skipping earnings.")
        return []

    today = date.today()
    to_date = today + timedelta(days=3)

    print(f"[earnings_fetcher] Fetching earnings calendar from {today} to {to_date}...")

    url = "https://finnhub.io/api/v1/calendar/earnings"
    try:
        resp = requests.get(
            url,
            params={"from": today.strftime("%Y-%m-%d"), "to": to_date.strftime("%Y-%m-%d"), "token": key},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"[earnings_fetcher] WARNING: {exc}")
        return []

    print(f"[earnings_fetcher] HTTP response status: {resp.status_code}")
    if not (200 <= resp.status_code < 300):
        print(f"[earnings_fetcher] WARNING: Non-2xx response: {resp.text[:500]}")
        return []

    try:
        data = resp.json()
    except Exception as exc:
        print(f"[earnings_fetcher] WARNING: Failed to parse JSON: {exc}")
        return []

    raw = (data.get("earningsCalendar") or []) if isinstance(data, dict) else []
    print(f"[earnings_fetcher] Raw results count: {len(raw)}")

    out: list[dict[str, Any]] = []
    for r in raw:
        try:
            sym = str(r.get("symbol") or "").upper().strip()
            if not sym:
                continue
            company = str(r.get("company") or "").strip()
            d = str(r.get("date") or "").strip()
            hour = str(r.get("hour") or "").upper().strip()
            if hour == "BMO":
                time = "BMO"
            elif hour == "AMC":
                time = "AMC"
            else:
                time = hour or ""

            eps_est = r.get("epsEstimate")
            eps_est_f = float(eps_est) if eps_est is not None else None

            relevant = sym in WATCHLIST_TICKERS or (eps_est_f is not None and sym in MAJOR_SP500_TICKERS)
            if not relevant:
                continue

            out.append(
                {
                    "symbol": sym,
                    "company": company,
                    "date": d,
                    "time": time,
                    "eps_estimate": eps_est_f,
                }
            )
        except Exception:
            continue

    # Sort by date then symbol
    out.sort(key=lambda x: (x.get("date") or "", x.get("symbol") or ""))

    out = out[:5]
    print(f"[earnings_fetcher] Filtered to {len(out)} relevant earnings")
    return out
