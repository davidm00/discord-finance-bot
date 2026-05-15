from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pytz
import requests


ET_TZ = pytz.timezone("America/New_York")


def _to_et(iso_ts: str) -> str:
    try:
        # Discord timestamps are ISO8601 (e.g., 2026-05-15T01:23:45.678Z)
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")
    except Exception:
        return ""


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
            if (is_bot or is_webhook) and embeds:
                bot_msgs.append(m)
        except Exception:
            continue

    print(f"[history_fetcher] Found {len(bot_msgs)} bot/webhook messages with embeds")

    reports: list[dict[str, Any]] = []

    for m in bot_msgs:
        if len(reports) >= 2:
            break
        try:
            embeds = m.get("embeds") or []
            if not embeds:
                continue

            e0 = embeds[0] or {}
            title = str(e0.get("title") or "").strip()
            desc = str(e0.get("description") or "").strip()
            ts_et = _to_et(str(m.get("timestamp") or ""))

            rt = ""
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

            print(f"[history_fetcher] Extracted report: {rt} from {ts_et}")
        except Exception as exc:
            print(f"[history_fetcher] WARNING: {exc}")

    print(f"[history_fetcher] Returning {len(reports)} previous reports")
    return reports
