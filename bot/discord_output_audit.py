from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytz
import requests

from recommendation_parser import parse_recommendations


ET_TZ = pytz.timezone("America/New_York")

DISCORD_EMBED_TOTAL_MAX = 6000
DISCORD_TITLE_MAX = 256
DISCORD_DESCRIPTION_MAX = 4096
DISCORD_FIELD_NAME_MAX = 256
DISCORD_FIELD_VALUE_MAX = 1024
DISCORD_FIELD_COUNT_MAX = 25


def _to_dt(iso_ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_et(iso_ts: str) -> str:
    dt = _to_dt(iso_ts)
    if not dt:
        return ""
    return dt.astimezone(ET_TZ).strftime("%Y-%m-%d %H:%M ET")


def _embed_char_count(embed: dict[str, Any]) -> int:
    total = len(str(embed.get("title") or ""))
    total += len(str(embed.get("description") or ""))
    footer = embed.get("footer") or {}
    total += len(str(footer.get("text") or ""))
    for field in embed.get("fields") or []:
        total += len(str(field.get("name") or ""))
        total += len(str(field.get("value") or ""))
    return total


def classify_embed(embed: dict[str, Any]) -> str:
    title = str(embed.get("title") or "").lower()
    field_names = " ".join(str(f.get("name") or "") for f in embed.get("fields") or []).lower()
    if "weekly market summary" in title:
        return "weekly"
    if "pre-market briefing" in title:
        return "pre-market"
    if "post-market recap" in title:
        return "post-market"
    if "equities" in field_names or "crypto" in field_names or "headlines" in field_names:
        return "data-fields"
    return "other"


def validate_embed(embed: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    title = str(embed.get("title") or "")
    desc = str(embed.get("description") or "")
    fields = embed.get("fields") or []
    total = _embed_char_count(embed)

    if total > DISCORD_EMBED_TOTAL_MAX:
        warnings.append(f"embed_total_chars>{DISCORD_EMBED_TOTAL_MAX} ({total})")
    if len(title) > DISCORD_TITLE_MAX:
        warnings.append(f"title_chars>{DISCORD_TITLE_MAX} ({len(title)})")
    if len(desc) > DISCORD_DESCRIPTION_MAX:
        warnings.append(f"description_chars>{DISCORD_DESCRIPTION_MAX} ({len(desc)})")
    if len(fields) > DISCORD_FIELD_COUNT_MAX:
        warnings.append(f"fields>{DISCORD_FIELD_COUNT_MAX} ({len(fields)})")

    for idx, field in enumerate(fields, start=1):
        name = str(field.get("name") or "")
        value = str(field.get("value") or "")
        if len(name) > DISCORD_FIELD_NAME_MAX:
            warnings.append(f"field_{idx}_name_chars>{DISCORD_FIELD_NAME_MAX} ({len(name)})")
        if len(value) > DISCORD_FIELD_VALUE_MAX:
            warnings.append(f"field_{idx}_value_chars>{DISCORD_FIELD_VALUE_MAX} ({len(value)})")
        if not value.strip():
            warnings.append(f"field_{idx}_empty_value")

    full_text = f"{title}\n{desc}\n" + "\n".join(
        f"{f.get('name') or ''}\n{f.get('value') or ''}" for f in fields
    )
    if re.search(r"\b(lorem ipsum|todo|placeholder|undefined|null)\b", full_text, re.I):
        warnings.append("placeholder_like_text")
    if "truncated" in full_text.lower():
        warnings.append("contains_truncation_marker")

    report_type = classify_embed(embed)
    if report_type in {"pre-market", "post-market", "weekly"}:
        if "not financial advice" not in full_text.lower():
            warnings.append("missing_financial_advice_disclaimer")
        if "tickers to watch" not in full_text.lower():
            warnings.append("missing_tickers_to_watch_section")
    if report_type in {"pre-market", "post-market", "weekly"}:
        if "vix" not in full_text.lower():
            warnings.append("missing_vix_reference")
        if "fear" not in full_text.lower() and "greed" not in full_text.lower():
            warnings.append("missing_fear_greed_reference")

    return warnings


def fetch_messages(token: str, channel_id: str, max_messages: int, days: int | None) -> list[dict[str, Any]]:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    before: str | None = None
    messages: list[dict[str, Any]] = []

    while len(messages) < max_messages:
        limit = min(100, max_messages - len(messages))
        params: dict[str, Any] = {"limit": limit}
        if before:
            params["before"] = before

        resp = requests.get(url, params=params, headers=headers, timeout=20)
        if resp.status_code == 429:
            retry_after = float((resp.json() or {}).get("retry_after") or 1)
            time.sleep(min(max(retry_after, 1), 10))
            continue
        if not (200 <= resp.status_code < 300):
            raise RuntimeError(f"Discord API returned {resp.status_code}: {resp.text[:500]}")

        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break

        stop_for_cutoff = False
        for message in batch:
            ts = str(message.get("timestamp") or "")
            dt = _to_dt(ts)
            if cutoff is not None and dt is not None and dt.astimezone(timezone.utc) < cutoff:
                stop_for_cutoff = True
                break
            messages.append(message)
            if len(messages) >= max_messages:
                break

        before = str(batch[-1].get("id") or "")
        if stop_for_cutoff or not before:
            break

    return messages


def summarize_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()
    ticker_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()

    for message in messages:
        author = message.get("author") or {}
        is_bot_or_webhook = bool(author.get("bot")) or message.get("webhook_id") is not None
        if not is_bot_or_webhook:
            continue
        for embed_idx, embed in enumerate(message.get("embeds") or [], start=1):
            report_type = classify_embed(embed)
            warnings = validate_embed(embed)
            desc = str(embed.get("description") or "")
            recs = []
            if "tickers to watch" in desc.lower():
                with contextlib.redirect_stdout(io.StringIO()):
                    recs = parse_recommendations(desc)
            for rec in recs:
                action_counts[str(rec.get("rating") or "").upper()] += 1
                ticker_counts[str(rec.get("ticker") or "").upper()] += 1
            type_counts[report_type] += 1
            for warning in warnings:
                warning_counts[warning.split(" (", 1)[0]] += 1

            rows.append(
                {
                    "message_id": str(message.get("id") or ""),
                    "timestamp_utc": str(message.get("timestamp") or ""),
                    "timestamp_et": _to_et(str(message.get("timestamp") or "")),
                    "embed_index": embed_idx,
                    "report_type": report_type,
                    "title": str(embed.get("title") or ""),
                    "embed_chars": _embed_char_count(embed),
                    "description_chars": len(desc),
                    "field_count": len(embed.get("fields") or []),
                    "field_names": " | ".join(str(f.get("name") or "") for f in embed.get("fields") or []),
                    "recommendation_count": len(recs),
                    "recommendations": "; ".join(
                        f"{r.get('ticker')}:{r.get('rating')}:{r.get('confidence')}" for r in recs
                    ),
                    "warnings": "; ".join(warnings),
                }
            )

    summary = {
        "messages_fetched": len(messages),
        "embeds_audited": len(rows),
        "report_type_counts": dict(type_counts),
        "warning_counts": dict(warning_counts),
        "action_counts": dict(action_counts),
        "top_tickers": dict(ticker_counts.most_common(20)),
        "oldest_message_utc": rows[-1]["timestamp_utc"] if rows else "",
        "newest_message_utc": rows[0]["timestamp_utc"] if rows else "",
    }
    return rows, summary


def write_outputs(rows: list[dict[str, Any]], summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "discord_audit_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "discord_audit_rows.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8"
    )

    fieldnames = [
        "timestamp_et",
        "report_type",
        "title",
        "embed_chars",
        "description_chars",
        "field_count",
        "recommendation_count",
        "recommendations",
        "warnings",
        "message_id",
        "timestamp_utc",
        "embed_index",
        "field_names",
    ]
    with (output_dir / "discord_audit_rows.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    lines = [
        "# Discord Output Audit",
        "",
        f"- Messages fetched: {summary['messages_fetched']}",
        f"- Embeds audited: {summary['embeds_audited']}",
        f"- Oldest message UTC: {summary['oldest_message_utc'] or 'n/a'}",
        f"- Newest message UTC: {summary['newest_message_utc'] or 'n/a'}",
        f"- Report types: {summary['report_type_counts']}",
        f"- Recommendation actions: {summary['action_counts']}",
        f"- Top tickers: {summary['top_tickers']}",
        f"- Warning counts: {summary['warning_counts']}",
        "",
        "## Recent audited embeds",
        "",
    ]
    for row in rows[:20]:
        warning_text = row["warnings"] or "none"
        lines.append(
            f"- {row['timestamp_et']} — {row['report_type']} — {row['title']} "
            f"({row['embed_chars']} chars, {row['recommendation_count']} recs) — warnings: {warning_text}"
        )
    (output_dir / "discord_audit_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Discord finance bot output embeds.")
    parser.add_argument("--max-messages", type=int, default=500)
    parser.add_argument("--days", type=int, default=0, help="0 means no age cutoff.")
    parser.add_argument("--output-dir", default="local-output/discord-audit")
    args = parser.parse_args()

    token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    channel_id = (os.getenv("DISCORD_CHANNEL_ID") or "").strip()
    if not token or not channel_id:
        print("ERROR: DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID are required.", file=sys.stderr)
        return 2

    messages = fetch_messages(
        token=token,
        channel_id=channel_id,
        max_messages=max(1, args.max_messages),
        days=args.days if args.days > 0 else None,
    )
    rows, summary = summarize_messages(messages)
    write_outputs(rows, summary, Path(args.output_dir))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
