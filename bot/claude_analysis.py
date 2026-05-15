from __future__ import annotations

import json
import os
import sys
from typing import Any

from anthropic import Anthropic


DEFAULT_MODEL = "claude-sonnet-4-6"  # Use exactly this model id


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

    model = DEFAULT_MODEL

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
        # Log the real error details for debugging in GitHub Actions logs.
        print("ERROR: Claude API call failed.", file=sys.stderr)
        print(f"ERROR_TYPE: {type(exc).__name__}", file=sys.stderr)
        print(f"ERROR_MESSAGE: {exc}", file=sys.stderr)

        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            print(f"HTTP_STATUS: {status_code}", file=sys.stderr)

        request_id = getattr(exc, "request_id", None)
        if request_id:
            print(f"REQUEST_ID: {request_id}", file=sys.stderr)

        body = getattr(exc, "body", None)
        if body is not None:
            try:
                print("ERROR_BODY:", json.dumps(body, indent=2, default=str)[:8000], file=sys.stderr)
            except Exception:
                print(f"ERROR_BODY: {body}", file=sys.stderr)

        response = getattr(exc, "response", None)
        if response is not None:
            # Avoid dumping request headers; just summarize response if possible.
            try:
                resp_status = getattr(response, "status_code", None)
                if resp_status is not None:
                    print(f"RESPONSE_STATUS: {resp_status}", file=sys.stderr)
                resp_text = None
                if hasattr(response, "text"):
                    resp_text = response.text
                if resp_text:
                    print("RESPONSE_TEXT:", str(resp_text)[:8000], file=sys.stderr)
            except Exception:
                print(f"RESPONSE: {response}", file=sys.stderr)

        return "Analysis unavailable at this time."
