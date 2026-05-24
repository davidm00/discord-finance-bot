from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from typing import Any

import pytz
import requests


THEMATIC_WATCHLIST = {
    "defense": ["LMT", "RTX", "NOC", "GD", "BA", "LDOS", "SAIC", "BAH", "HII", "TDG"],
    "cyber": ["CRWD", "PANW", "ZS", "FTNT", "S", "CYBR", "PLTR"],
    "energy": ["XOM", "CVX", "COP", "SLB", "HAL", "EOG", "MPC"],
    "tech": ["NVDA", "AMD", "MSFT", "GOOGL", "META", "AMZN", "AAPL"],
}

WATCHLIST_TICKERS = {t for lst in THEMATIC_WATCHLIST.values() for t in lst}

MAJOR_TICKERS = {
    # Index / market proxies
    "SPY",
    "QQQ",
    "DIA",

    # Financials
    "JPM",
    "BAC",
    "GS",
    "MS",
    "WFC",
    "C",
    "BRK.B",
    "V",
    "MA",
    "PYPL",

    # Retail / consumer
    "HD",
    "WMT",
    "TGT",
    "COST",
    "MCD",
    "SBUX",
    "NKE",

    # Media / internet / mega-cap
    "DIS",
    "NFLX",
    "TSLA",
    "UBER",
    "LYFT",
    "ABNB",

    # Enterprise / semis / cloud
    "CRM",
    "ORCL",
    "IBM",
    "INTC",
    "QCOM",
    "TXN",
    "MU",
    "AVGO",
    "NOW",
    "SNOW",

    # Momentum / meme-ish / fintech
    "PLTR",
    "COIN",
    "HOOD",
    "RBLX",
    "SHOP",
    "SQ",
    "ROKU",
    "ZM",
    "DOCU",
    "TWLO",
    "NET",
    "DDOG",

    # Healthcare
    "PFE",
    "JNJ",
    "MRNA",
    "ABBV",
    "LLY",
    "UNH",
    "CVS",
    "WBA",

    # Industrials / defense
    "BA",
    "CAT",
    "DE",
    "MMM",
    "GE",
    "HON",
    "RTX",
    "LMT",
    "NOC",

    # Energy
    "XOM",
    "CVX",
    "COP",
    "OXY",
    "MPC",
    "PSX",
    "VLO",
}


def fetch_upcoming_earnings() -> list[dict[str, Any]]:
    key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not key:
        print("[earnings_fetcher] WARNING: FINNHUB_API_KEY not set; skipping earnings.")
        return []

    ET_TZ = pytz.timezone("America/New_York")
    today = datetime.now(ET_TZ).date()
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

            # Relevance criteria (include if ANY pass):
            # 1) The symbol is in the thematic watchlist
            # 2) The symbol is in our hardcoded major tickers list
            # 3) EPS estimate exists and abs(EPS) > 0.10
            passes_watchlist = sym in WATCHLIST_TICKERS
            passes_major = sym in MAJOR_TICKERS
            passes_eps = eps_est_f is not None and abs(float(eps_est_f)) > 0.10

            relevant = passes_watchlist or passes_major or passes_eps
            if not relevant:
                continue

            # Prioritize watchlist + major tickers over EPS-only names.
            score = 3 if passes_watchlist else (2 if passes_major else 1)
            abs_eps = abs(float(eps_est_f)) if eps_est_f is not None else 0.0

            out.append(
                {
                    "symbol": sym,
                    "company": company,
                    "date": d,
                    "time": time,
                    "eps_estimate": eps_est_f,
                    "_score": score,
                    "_abs_eps": abs_eps,
                    "_passes_watchlist": passes_watchlist,
                    "_passes_major": passes_major,
                    "_passes_eps": passes_eps,
                }
            )
        except Exception:
            continue

    # Prefer watchlist/major tickers first; within EPS-only, prefer bigger abs EPS; then by date.
    out.sort(
        key=lambda x: (
            -(x.get("_score") or 0),
            -(x.get("_abs_eps") or 0.0),
            x.get("date") or "",
            x.get("symbol") or "",
        )
    )

    # Log match breakdown (cheap, helps tune quickly)
    watch_ct = sum(1 for x in out if x.get("_passes_watchlist"))
    major_ct = sum(1 for x in out if x.get("_passes_major"))
    eps_ct = sum(1 for x in out if x.get("_passes_eps"))

    out = out[:5]
    for x in out:
        x.pop("_score", None)
        x.pop("_abs_eps", None)
        x.pop("_passes_watchlist", None)
        x.pop("_passes_major", None)
        x.pop("_passes_eps", None)

    symbols_sample = [str(x.get("symbol") or "").upper() for x in out if x.get("symbol")]
    print(f"[earnings_fetcher] Filtered to {len(out)} relevant earnings")
    print(f"[earnings_fetcher] Sample of filtered symbols: {symbols_sample}")
    print(f"[earnings_fetcher] Matches — watchlist: {watch_ct}, major: {major_ct}, eps(|eps|>0.10): {eps_ct}")
    return out
