from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pytz
import requests
from bs4 import BeautifulSoup


ET_TZ = pytz.timezone("America/New_York")

CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades?pageSize=96&sortBy=-pubDate"
USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

KNOWN_RECURRING_CONTRACTS = [
    "SANDIA",
    "UT-BATTELLE",
    "LAWRENCE LIVERMORE",
    "LOS ALAMOS",
    "TRIAD NATIONAL SECURITY",
    "SAVANNAH RIVER",
    "BROOKHAVEN",
    "OAK RIDGE",
    "PACIFIC NORTHWEST",
    "ARGONNE",
    "FERMI RESEARCH",
]


COMMON_CO_WORDS = {
    "inc",
    "inc.",
    "corp",
    "corp.",
    "co",
    "co.",
    "company",
    "corporation",
    "llc",
    "ltd",
    "plc",
    "the",
    "group",
    "holdings",
    "holding",
    "technologies",
    "technology",
}


def _now_et() -> datetime:
    return datetime.now(ET_TZ)


def _fmt_et(dt: datetime) -> str:
    return dt.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")


def _parse_amount_min(amount_range: str) -> float | None:
    """Parse the minimum amount from a Capitol Trades range string.

    Capitol Trades commonly shows ranges like "1K–15K", "50K–100K", "1M+", sometimes
    with or without "$" and using en dashes.
    """

    if not amount_range:
        return None

    s = amount_range.strip()
    s = s.replace(" ", "")
    s = s.replace("—", "-").replace("–", "-")
    s = s.replace("$", "")

    def _to_usd(num: float, suf: str) -> float:
        mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suf.upper(), 1)
        return num * mult

    # Single bound: 1M+
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)([KMB])\+?$", s, re.IGNORECASE)
    if m:
        return _to_usd(float(m.group(1)), m.group(2))

    # Range: 50K-100K
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)([KMB])\-([0-9]+(?:\.[0-9]+)?)([KMB])$", s, re.IGNORECASE)
    if m:
        return _to_usd(float(m.group(1)), m.group(2))

    # Fallback: first numeric token
    m = re.search(r"([0-9][0-9,]*)", s)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except Exception:
            return None

    return None


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in (
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",   # e.g., 15 Apr 2026
        "%d %B %Y",   # e.g., 15 April 2026
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _human_money(amount: float) -> str:
    if amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.0f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


def fetch_congressional_trades(lookback_days: int = 7) -> list[dict[str, Any]]:
    """Scrape recent trades from Capitol Trades.

    Returns up to 15 most recent trades (>= $25K minimum amount, last N days).
    On failure, returns empty list.
    """

    print("Fetching congressional trades from Capitol Trades...", file=sys.stdout)

    headers = {
        "User-Agent": "discord-finance-bot/1.0 (+https://github.com)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        resp = requests.get(CAPITOL_TRADES_URL, headers=headers, timeout=20)
    except requests.RequestException as exc:
        print(f"WARNING: Capitol Trades request failed: {exc}", file=sys.stderr)
        return []

    if not (200 <= resp.status_code < 300):
        print(f"WARNING: Capitol Trades returned {resp.status_code}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    table = soup.find("table")
    if not table:
        print("WARNING: Could not find trades table on Capitol Trades page.", file=sys.stderr)
        return []

    # Build header->index map
    headers_row = table.find("thead")
    header_map: dict[str, int] = {}
    if headers_row:
        ths = headers_row.find_all("th")
        for i, th in enumerate(ths):
            key = th.get_text(" ", strip=True).lower()
            if key:
                header_map[key] = i

    tbody = table.find("tbody")
    if not tbody:
        print("WARNING: Trades table missing tbody.", file=sys.stderr)
        return []

    rows = tbody.find_all("tr")
    if not rows:
        print("WARNING: Trades table empty.", file=sys.stderr)
        return []

    cutoff = (_now_et().date() - timedelta(days=int(lookback_days or 7)))

    trades: list[dict[str, Any]] = []

    for r in rows:
        tds = r.find_all("td")
        if not tds:
            continue

        def _idx(*names: str, default: int | None = None) -> int | None:
            for n in names:
                k = n.lower()
                if k in header_map:
                    return header_map[k]
            return default

        def _td(i: int | None):
            if i is None or i < 0 or i >= len(tds):
                return None
            return tds[i]

        # Column indices based on table header labels.
        pol_i = _idx("politician", default=0)
        issuer_i = _idx("traded issuer", default=1)
        published_i = _idx("published", default=2)
        traded_i = _idx("traded", default=3)
        type_i = _idx("type", default=6)
        size_i = _idx("size", default=7)

        pol_td = _td(pol_i)
        issuer_td = _td(issuer_i)
        published_td = _td(published_i)
        traded_td = _td(traded_i)
        type_td = _td(type_i)
        size_td = _td(size_i)

        politician = ""
        party = "?"
        chamber = "?"

        if pol_td is not None:
            a = pol_td.find("a")
            politician = a.get_text(" ", strip=True) if a else pol_td.get_text(" ", strip=True)

            party_txt = ""
            party_span = pol_td.select_one(".party")
            if party_span:
                party_txt = party_span.get_text(" ", strip=True)
            else:
                party_txt = pol_td.get_text(" ", strip=True)

            p_l = party_txt.lower()
            if "republic" in p_l:
                party = "R"
            elif "democrat" in p_l:
                party = "D"
            elif "independ" in p_l:
                party = "I"

            chamber_span = pol_td.select_one(".chamber")
            if chamber_span:
                chamber = chamber_span.get_text(" ", strip=True) or chamber
            else:
                ttxt = pol_td.get_text(" ", strip=True).lower()
                if "senate" in ttxt:
                    chamber = "Senate"
                elif "house" in ttxt:
                    chamber = "House"

        ticker = ""
        company = ""
        if issuer_td is not None:
            comp_a = issuer_td.find("a")
            if comp_a:
                company = comp_a.get_text(" ", strip=True)
            tick_span = issuer_td.select_one(".issuer-ticker")
            if tick_span:
                ticker = tick_span.get_text(" ", strip=True)
            else:
                txt = issuer_td.get_text(" ", strip=True)
                m = re.search(r"\b[A-Z]{1,5}(?::[A-Z]{2})?\b", txt)
                if m:
                    ticker = m.group(0)

        if ":" in ticker:
            ticker = ticker.split(":", 1)[0]

        ticker = ticker.strip().upper()
        if not ticker:
            continue

        trade_type = ""
        if type_td is not None:
            trade_type = type_td.get_text(" ", strip=True)

        trade_type_norm = ""
        if trade_type:
            if "buy" in trade_type.lower():
                trade_type_norm = "Buy"
            elif "sell" in trade_type.lower():
                trade_type_norm = "Sell"
            else:
                trade_type_norm = trade_type.strip()

        amount_range = ""
        if size_td is not None:
            size_txt = size_td.get_text(" ", strip=True)
            # Extract the range token (e.g., 1K–15K)
            m = re.search(r"([0-9]+(?:\.[0-9]+)?[KMB]\s*[–\-]\s*[0-9]+(?:\.[0-9]+)?[KMB]|[0-9]+(?:\.[0-9]+)?[KMB]\+?)", size_txt, re.IGNORECASE)
            amount_range = (m.group(1) if m else size_txt).strip()

        trade_date_s = traded_td.get_text(" ", strip=True) if traded_td is not None else ""

        report_date_s = ""
        if published_td is not None:
            pub_txt = published_td.get_text(" ", strip=True)
            if re.search(r"\btoday\b", pub_txt, re.IGNORECASE):
                report_date_s = _now_et().date().strftime("%Y-%m-%d")
            elif re.search(r"\byesterday\b", pub_txt, re.IGNORECASE):
                report_date_s = (_now_et().date() - timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                report_date_s = pub_txt

        trade_date = _parse_date(trade_date_s)
        report_date = _parse_date(report_date_s)

        if trade_date is None:
            # Skip if we can't parse; needed for last-7-days filter.
            continue

        # Filter by PUBLISHED date (disclosure date) instead of trade date
        if report_date and report_date < cutoff:
            continue
        elif not report_date and trade_date < cutoff:
            # Fall back to trade date if published date unavailable
            continue

        min_amt = _parse_amount_min(amount_range)
        if min_amt is None or min_amt < 25_000:
            continue

        trades.append(
            {
                "politician": politician.strip(),
                "party": party or "?",
                "chamber": chamber or "?",
                "ticker": ticker.strip().upper(),
                "company": company.strip() if company else "",
                "trade_type": trade_type_norm or "?",
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "published_date": report_date.strftime("%Y-%m-%d") if report_date else "",
                "report_date": report_date.strftime("%Y-%m-%d") if report_date else "",
                "amount_range": amount_range.strip() if amount_range else "",
                "_trade_date": trade_date,
                "_published_date": report_date,
            }
        )

    if not trades:
        print("WARNING: No recent trades >= $25K found (or scraping failed).", file=sys.stderr)
        return []

    # Sort by published/disclosure date descending (most recently disclosed first)
    print(f"[political] Sorting {len(trades)} trades by published/disclosure date")
    trades.sort(
        key=lambda x: x.get("_published_date") or x.get("_trade_date") or date.min,
        reverse=True,
    )
    if trades:
        top_pub = trades[0].get("published_date") or trades[0].get("trade_date") or "unknown"
        print(f"[political] Most recent disclosure: {top_pub}")

    trades = trades[:15]

    # Strip internal fields
    for t in trades:
        t.pop("_trade_date", None)
        t.pop("_published_date", None)

    return trades


def fetch_government_contracts() -> list[dict[str, Any]]:
    """Fetch major government contracts from USASpending.gov."""

    print("Fetching government contracts from USASpending.gov...", file=sys.stdout)

    today = _now_et().date()
    start = today - timedelta(days=7)

    body = {
        "filters": {
            "time_period": [{"start_date": start.strftime("%Y-%m-%d"), "end_date": today.strftime("%Y-%m-%d")}],
            "award_type_codes": ["A", "B", "C", "D"],
            "award_amounts": [{"lower_bound": 10_000_000}],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Start Date",
            "Last Modified Date",
            "Awarding Agency",
            "Description",
        ],
        "sort": "Start Date",
        "order": "desc",
        "limit": 20,
        "page": 1,
    }

    try:
        resp = requests.post(USASPENDING_URL, json=body, timeout=20)
    except requests.RequestException as exc:
        print(f"WARNING: USASpending request failed: {exc}", file=sys.stderr)
        return []

    if not (200 <= resp.status_code < 300):
        print(f"WARNING: USASpending returned {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        return []

    try:
        data = resp.json()
    except Exception as exc:
        print(f"WARNING: USASpending JSON parse failed: {exc}", file=sys.stderr)
        return []

    results = data.get("results") or []
    if not isinstance(results, list) or not results:
        print("WARNING: USASpending returned empty results.", file=sys.stderr)
        return []

    agency_kw = [
        "defense",
        "energy",
        "homeland",
        "navy",
        "army",
        "air force",
        "space force",
        "cyber",
        "intelligence",
    ]

    desc_kw = [
        "cyber",
        "defense",
        "missile",
        "aircraft",
        "satellite",
        "radar",
        "intelligence",
        "surveillance",
        "energy",
        "drone",
        "ai",
        "artificial intelligence",
    ]

    contracts: list[dict[str, Any]] = []
    for r in results:
        try:
            recipient = str(r.get("Recipient Name") or "").strip()
            agency = str(r.get("Awarding Agency") or "").strip()
            desc = str(r.get("Description") or "").strip()
            start_date = str(r.get("Start Date") or "").strip()
            amt = r.get("Award Amount")
            amt_f = float(amt) if amt is not None else None

            if not recipient or not agency or amt_f is None:
                continue

            agency_l = agency.lower()
            desc_l = desc.lower()

            relevant = any(k in agency_l for k in agency_kw) or any(k in desc_l for k in desc_kw)
            if not relevant:
                continue

            contracts.append(
                {
                    "recipient": recipient,
                    "amount": amt_f,
                    "amount_human": _human_money(amt_f),
                    "date": start_date,
                    "agency": agency,
                    "description": desc,
                }
            )
        except Exception:
            continue

    if not contracts:
        print("WARNING: No major contracts found after filtering.", file=sys.stderr)
        return []

    # Already sorted by Start Date desc from API; just cap to 10
    contracts = contracts[:10]

    # Tag recurring vs new contracts
    for c in contracts:
        recipient_upper = c.get("recipient", "").upper()
        c["is_recurring"] = any(frag in recipient_upper for frag in KNOWN_RECURRING_CONTRACTS)
        print(f"[political] Contract: {c.get('recipient','')} — is_recurring: {c['is_recurring']}")

    return contracts


def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokenize_company(name: str) -> set[str]:
    toks = [t for t in _normalize(name).split(" ") if t and len(t) > 3 and t not in COMMON_CO_WORDS]
    return set(toks)


def find_correlations(trades: list[dict[str, Any]], contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find loose matches between trades and contracts within 30 days."""

    correlations: list[dict[str, Any]] = []

    # Precompute trade tokens
    trade_entries: list[tuple[dict[str, Any], set[str]]] = []
    for t in trades:
        comp = str(t.get("company") or "")
        trade_entries.append((t, _tokenize_company(comp)))

    for c in contracts:
        recipient = str(c.get("recipient") or "")
        agency = str(c.get("agency") or "")
        c_date_s = str(c.get("date") or "")
        amt_h = str(c.get("amount_human") or _human_money(float(c.get("amount") or 0.0)))

        try:
            c_date = datetime.fromisoformat(c_date_s[:10]).date()
        except Exception:
            continue

        rec_norm = _normalize(recipient)
        rec_toks = set(rec_norm.split(" "))

        for t, comp_toks in trade_entries:
            ticker = str(t.get("ticker") or "").upper()
            company = str(t.get("company") or "").strip()
            pol = str(t.get("politician") or "")
            party = str(t.get("party") or "?")
            chamber = str(t.get("chamber") or "?")
            trade_type = str(t.get("trade_type") or "?")
            trade_amt = str(t.get("amount_range") or "")
            t_date_s = str(t.get("trade_date") or "")

            t_date = _parse_date(t_date_s)
            if not t_date:
                continue

            # Loose matching rules
            match = False

            if ticker and ticker.lower() in rec_toks:
                match = True

            if not match and company:
                # Require at least 2 meaningful token overlaps
                overlap = comp_toks.intersection(rec_toks)
                if len(overlap) >= 2:
                    match = True

            if not match:
                continue

            days_apart = abs((t_date - c_date).days)
            if days_apart > 30:
                continue

            correlations.append(
                {
                    "company": company or recipient,
                    "ticker": ticker,
                    "contract_amount": amt_h,
                    "contract_date": c_date.strftime("%Y-%m-%d"),
                    "contract_agency": agency,
                    "politician": pol,
                    "party": party,
                    "trade_type": trade_type,
                    "trade_amount_range": trade_amt,
                    "trade_date": t_date.strftime("%Y-%m-%d"),
                    "chamber": chamber,
                    "days_apart": days_apart,
                }
            )

    correlations.sort(key=lambda x: int(x.get("days_apart") or 999999))
    return correlations


def fetch_political_data(lookback_days: int = 7) -> dict[str, Any]:
    """Fetch trades + contracts + correlations. Never raises."""

    fetched_at_et = _fmt_et(_now_et())

    trades = []
    contracts = []
    correlations = []

    try:
        trades = fetch_congressional_trades(lookback_days=lookback_days)
    except Exception as exc:
        print(f"WARNING: Trades fetch failed: {exc}", file=sys.stderr)
        trades = []

    try:
        contracts = fetch_government_contracts()
    except Exception as exc:
        print(f"WARNING: Contracts fetch failed: {exc}", file=sys.stderr)
        contracts = []

    try:
        correlations = find_correlations(trades, contracts)
    except Exception as exc:
        print(f"WARNING: Correlation detection failed: {exc}", file=sys.stderr)
        correlations = []

    return {
        "trades": trades,
        "contracts": contracts,
        "correlations": correlations,
        "fetched_at_et": fetched_at_et,
    }
