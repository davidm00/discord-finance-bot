from __future__ import annotations

import json
import os
import sys
from typing import Any

from anthropic import Anthropic


DEFAULT_MODEL = "claude-sonnet-4-5-20251001"  # Requested by spec


def generate_analysis(market_data: dict[str, Any], report_type: str) -> str:
    """Generate a 3-paragraph analysis using Anthropic Claude.

    Args:
      market_data: dict returned from bot/market_data.py
      report_type: "pre-market" or "post-market"

    Returns:
      analysis text, or a fallback string if the API call fails.
    """

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY is not set; skipping analysis.", file=sys.stderr)
        return "Analysis unavailable at this time."

    model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

    if report_type == "pre-market":
        system_prompt = (
            "You are a concise financial analyst writing a pre-market briefing for a small group "
            "of personal investors. Your tone is clear, direct, and informative — not hype. "
            "Focus on what the data suggests investors should watch today. "
            "Always include ET timestamps when referencing timing."
        )
        user_prompt = (
            "Write a 3-paragraph pre-market briefing covering: "
            "(1) overnight/early equity market conditions based on the data, "
            "(2) crypto market conditions and any notable moves, "
            "(3) 2-3 specific things to watch when the market opens at 9:30 AM ET today.\n\n"
            "Market data (JSON):\n"
            f"```json\n{json.dumps(market_data, indent=2, sort_keys=True)}\n```"
        )
    else:
        system_prompt = (
            "You are a concise financial analyst writing a post-market recap for a small group of personal investors. "
            "Your tone is clear, direct, and informative — not hype. Focus on what happened today, "
            "why it likely happened, and what it might mean for tomorrow. Always include ET timestamps "
            "when referencing timing."
        )
        user_prompt = (
            "Write a 3-paragraph post-market recap covering: "
            "(1) how equities closed and what drove the day, "
            "(2) crypto performance and correlation to equities if notable, "
            "(3) what today's action suggests for tomorrow's open.\n\n"
            "Market data (JSON):\n"
            f"```json\n{json.dumps(market_data, indent=2, sort_keys=True)}\n```"
        )

    try:
        print(f"Calling Claude API (model={model})...", file=sys.stdout)
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # SDK returns a structured content list
        parts = getattr(msg, "content", None)
        if not parts:
            return "Analysis unavailable at this time."

        text = getattr(parts[0], "text", None)
        if not text:
            return "Analysis unavailable at this time."

        return str(text).strip()
    except Exception as exc:
        print(f"WARNING: Claude API call failed: {exc}", file=sys.stderr)
        return "Analysis unavailable at this time."
