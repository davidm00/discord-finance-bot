from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytz
import requests


ET_TZ = pytz.timezone("America/New_York")


def _to_dt(iso_ts: str) -> datetime | None:
    try:
        # Discord timestamps are ISO8601 (e.g., 2026-05-15T01:23:45.678Z)
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_et(iso_ts: str) -> str:
    try:
        dt = _to_dt(iso_ts)
        if not dt:
            return ""
        return dt.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")
    except Exception:
        return ""


def _extract_reports(messages: list[dict[str, Any]], limit: int, since_dt_utc: datetime | None = None) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []

    for m in messages:
        if len(reports) >= limit:
            break
        try:
            author = m.get("author") or {}
            is_bot = bool(author.get("bot"))
            is_webhook = m.get("webhook_id") is not None
            embeds = m.get("embeds") or []
            if not ((is_bot or is_webhook) and embeds):
                continue

            ts_iso = str(m.get("timestamp") or "")
            dt = _to_dt(ts_iso)
            if since_dt_utc is not None:
                if dt is None:
                    continue
                # dt from Discord is timezone-aware (UTC offset). Normalize to UTC.
                dt_utc = dt.astimezone(timezone.utc)
                if dt_utc < since_dt_utc:
                    continue

            e0 = embeds[0] or {}
            title = str(e0.get("title") or "").strip()
            desc = str(e0.get("description") or "").strip()
            ts_et = _to_et(ts_iso)

            t_l = title.lower()
            if "pre-market" in t_l:
                rt = "pre-market"
            elif "post-market" in t_l:
                rt = "post-market"
            else:
                rt = "unknown"

            fields_dict: dict[str, str] = {}
            for f in (e0.get("fields") or []):
                name = str(f.get("name") or "").strip()
                value = str(f.get("value") or "").strip()
                if name:
                    fields_dict[name] = value

            reports.append(
                {
                    "report_type": rt,
                    "timestamp_et": ts_et,
                    "analysis": desc,
                    "fields": fields_dict,
                }
            )
        except Exception as exc:
            print(f"[history_fetcher] WARNING: {exc}")

    return reports


import re


def extract_structured_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Extract key structured data from a previous report for continuity context.

    Returns a compact dict with prices, tickers watched, and predictions —
    suitable for inclusion in Claude prompt without excessive token usage.
    """
    summary: dict[str, Any] = {
        "report_type": report.get("report_type", "unknown"),
        "timestamp_et": report.get("timestamp_et", ""),
        "prices": {},
        "tickers_watched": [],
        "predictions": [],
        "key_theme": "",
    }

    fields = report.get("fields") or {}
    analysis = report.get("analysis") or ""

    # Extract equity prices from fields
    eq_field = fields.get("\U0001f1fa\U0001f1f8 Equities", "")  # 🇺🇸
    for line in eq_field.split("\n"):
        m = re.match(r"(\w+):\s*\$?([\d,.]+)\s*\(([▲▼])\s*([\d.]+)%\)", line)
        if m:
            summary["prices"][m.group(1)] = {
                "price": m.group(2),
                "direction": "up" if m.group(3) == "\u25b2" else "down",
                "pct": m.group(4),
            }

    # Extract crypto prices from fields
    cr_field = fields.get("\u20bf Crypto", "") or fields.get("₿ Crypto", "")
    for line in cr_field.split("\n"):
        m = re.match(r"(\w+):\s*\$?([\d,.]+)\s*\(([▲▼])\s*([\d.]+)%\)", line)
        if m:
            summary["prices"][m.group(1)] = {
                "price": m.group(2),
                "direction": "up" if m.group(3) == "\u25b2" else "down",
                "pct": m.group(4),
            }

    # Extract tickers watched from analysis text
    ticker_pattern = re.compile(
        r"\*\*(\w{1,5})\s*[—–-]\s*.*?\*\*.*?Rating:\s*(BUY|SELL|HOLD|WATCH)",
        re.DOTALL,
    )
    # Common words that aren't tickers
    non_tickers = {"Pre", "Post", "The", "This", "What", "How", "Why", "When", "Bull", "Bear"}
    for match in ticker_pattern.finditer(analysis):
        sym = match.group(1)
        if sym not in non_tickers and sym.isupper():
            summary["tickers_watched"].append({
                "ticker": sym,
                "rating": match.group(2),
            })

    # Extract predictions from "Tomorrow Watch" or "What to Watch" sections
    watch_pattern = re.compile(
        r"(?:Tomorrow Watch|What to Watch)[*\s]*\n([\s\S]*?)(?:\n---|\n\*\*|\Z)",
        re.IGNORECASE,
    )
    watch_match = watch_pattern.search(analysis)
    if watch_match:
        for line in watch_match.group(1).strip().split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-") or line.startswith("•")):
                cleaned = re.sub(r"^[\d]+[.)]\s*", "", line).strip()
                cleaned = re.sub(r"^[-•]\s*", "", cleaned).strip()
                if cleaned and len(cleaned) > 20:
                    summary["predictions"].append(cleaned[:200])

    # Extract key theme (first substantive paragraph, skip headers)
    paragraphs = [p.strip() for p in analysis.split("\n\n") if p.strip() and not p.strip().startswith("---")]
    for para in paragraphs:
        clean = para.replace("**", "").replace("#", "").strip()
        # Remove leading emoji
        clean = re.sub(r"^[\U0001f300-\U0001fad6\u2600-\u27bf\U0001f900-\U0001f9ff]+\s*", "", clean)
        # Skip header-like lines (dates, briefing titles)
        if any(x in clean.lower() for x in ["briefing", "recap", "summary", "market wrap"]):
            continue
        # Take the first real sentence from multi-line paragraphs
        first_line = clean.split("\n")[0].strip()
        if len(first_line) > 50:
            first_sentence = first_line.split(".")[0] + "." if "." in first_line else first_line[:150]
            summary["key_theme"] = first_sentence[:200]
            break

    return summary


def format_prior_context_for_prompt(reports: list[dict[str, Any]]) -> str:
    """Format previous reports into a concise structured context block for Claude.

    Uses ~400-600 chars instead of ~8000 chars of raw text.
    """
    if not reports:
        return ""

    lines = ["PREVIOUS REPORT CONTEXT (reference these for continuity):"]

    for r in reports[:2]:
        summary = extract_structured_summary(r)
        rt = summary["report_type"]
        ts = summary["timestamp_et"]
        lines.append(f"\n--- {rt} from {ts} ---")

        # Prices
        if summary["prices"]:
            price_parts = []
            for sym, data in summary["prices"].items():
                price_parts.append(f"{sym}: ${data['price']} ({data['direction']} {data['pct']}%)")
            lines.append(f"Closing data: {'; '.join(price_parts)}")

        # Tickers watched
        if summary["tickers_watched"]:
            tw = ", ".join(f"{t['ticker']} ({t['rating']})" for t in summary["tickers_watched"])
            lines.append(f"Tickers flagged: {tw}")

        # Predictions
        valid_predictions = [p for p in summary["predictions"] if p.strip()]
        if valid_predictions:
            lines.append("Predictions made:")
            for p in valid_predictions[:3]:
                lines.append(f"  - {p}")

        # Theme
        if summary["key_theme"]:
            lines.append(f"Key theme: {summary['key_theme']}")

    lines.append("\nWhen writing today's report, note what was flagged previously and whether those predictions or signals played out.")
    return "\n".join(lines)


def fetch_previous_reports() -> list[dict[str, Any]]:
    token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    channel_id = (os.getenv("DISCORD_CHANNEL_ID") or "").strip()

    if not token or not channel_id:
        print("[history_fetcher] WARNING: DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID not set; skipping history.")
        return []

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

    print(f"[history_fetcher] Fetching last 10 messages from channel {channel_id}...")
    try:
        resp = requests.get(
            url,
            params={"limit": 10},
            headers={"Authorization": f"Bot {token}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"[history_fetcher] WARNING: {exc}")
        return []

    print(f"[history_fetcher] HTTP response status: {resp.status_code}")
    if not (200 <= resp.status_code < 300):
        print(f"[history_fetcher] WARNING: Non-2xx response: {resp.text[:500]}")
        return []

    try:
        messages = resp.json()
    except Exception as exc:
        print(f"[history_fetcher] WARNING: Failed to parse JSON: {exc}")
        return []

    if not isinstance(messages, list):
        print("[history_fetcher] WARNING: Unexpected response shape.")
        return []

    print(f"[history_fetcher] Found {len(messages)} total messages")

    bot_msgs = []
    for m in messages:
        try:
            author = m.get("author") or {}
            is_bot = bool(author.get("bot"))
            is_webhook = m.get("webhook_id") is not None
            embeds = m.get("embeds") or []
            if not ((is_bot or is_webhook) and embeds):
                continue

            e0 = embeds[0] or {}
            title = str(e0.get("title") or "").strip()
            title_l = title.lower()
            ts_et = _to_et(str(m.get("timestamp") or ""))

            # Skip weekly summaries explicitly
            if "weekly market summary" in title_l:
                print(f"[history_fetcher] Skipping weekly summary message from {ts_et}")
                continue

            # Only accept daily reports
            if ("pre-market briefing" not in title_l) and ("post-market recap" not in title_l):
                continue

            bot_msgs.append(m)
        except Exception:
            continue

    print(f"[history_fetcher] Found {len(bot_msgs)} bot/webhook messages with embeds")

    reports = _extract_reports(bot_msgs, limit=2)

    for r in reports:
        print(f"[history_fetcher] Extracted report: {r.get('report_type')} from {r.get('timestamp_et')}")

    print(f"[history_fetcher] Returning {len(reports)} previous reports")
    return reports


def fetch_weekly_history() -> list[dict[str, Any]]:
    token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    channel_id = (os.getenv("DISCORD_CHANNEL_ID") or "").strip()

    if not token or not channel_id:
        print("[history_fetcher] WARNING: DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID not set; skipping history.")
        return []

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

    print("[history_fetcher] fetch_weekly_history: fetching last 20 messages...")

    try:
        resp = requests.get(
            url,
            params={"limit": 20},
            headers={"Authorization": f"Bot {token}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"[history_fetcher] WARNING: {exc}")
        return []

    if not (200 <= resp.status_code < 300):
        print(f"[history_fetcher] WARNING: Non-2xx response: {resp.status_code}: {resp.text[:500]}")
        return []

    try:
        messages = resp.json()
    except Exception as exc:
        print(f"[history_fetcher] WARNING: Failed to parse JSON: {exc}")
        return []

    if not isinstance(messages, list):
        print("[history_fetcher] WARNING: Unexpected response shape.")
        return []

    since_dt = datetime.now(timezone.utc) - timedelta(days=7)

    candidates = []
    for m in messages:
        try:
            author = m.get("author") or {}
            is_bot = bool(author.get("bot"))
            is_webhook = m.get("webhook_id") is not None
            embeds = m.get("embeds") or []
            if not ((is_bot or is_webhook) and embeds):
                continue

            # Only include daily reports; ignore weekly summaries or other embeds.
            title = str((embeds[0] or {}).get("title") or "").lower()
            if "pre-market" not in title and "post-market" not in title:
                continue

            # Apply 7-day cutoff
            ts_iso = str(m.get("timestamp") or "")
            dt = _to_dt(ts_iso)
            if dt is None:
                continue
            if dt.astimezone(timezone.utc) < since_dt:
                continue

            candidates.append(m)
        except Exception:
            continue

    reports = _extract_reports(candidates, limit=10, since_dt_utc=since_dt)

    # Sort ascending by ET timestamp (oldest first)
    def _sort_key(r: dict[str, Any]):
        ts = str(r.get("timestamp_et") or "")
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M ET")
        except Exception:
            return datetime.min

    reports.sort(key=_sort_key)

    print(f"[history_fetcher] fetch_weekly_history: found {len(reports)} reports in last 7 days")
    print(f"[history_fetcher] fetch_weekly_history: returning {len(reports)} reports (oldest first)")
    return reports
