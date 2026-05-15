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
