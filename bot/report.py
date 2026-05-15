"""Phase 1: skeleton / pipeline test.

This script exists to validate the GitHub Actions cron pipeline and Discord webhook delivery.
It will be replaced in Phase 2 with real market data fetching and report generation.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pytz
import requests


ET_TZ = pytz.timezone("America/New_York")


def _label_for_run(now_et: datetime) -> str:
    # Requirement: distinguish runs by checking the current hour in ET.
    return "pre-market" if now_et.hour < 12 else "post-market"


def main() -> int:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(
            "ERROR: DISCORD_WEBHOOK_URL is not set. Add it as a GitHub Actions secret named DISCORD_WEBHOOK_URL.",
            file=sys.stderr,
        )
        return 0

    now_et = datetime.now(ET_TZ)
    label = _label_for_run(now_et)

    content = f"✅ Finance bot is alive. Pipeline test successful. [{label}]"
    payload = {"content": content}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
    except requests.RequestException as exc:
        print(f"ERROR: Webhook POST failed: {exc}", file=sys.stderr)
        return 1

    if not (200 <= resp.status_code < 300):
        print(f"ERROR: Webhook POST failed with {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1

    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
