from __future__ import annotations

import json
import os
import sys
from typing import Any

from anthropic import Anthropic


DEFAULT_MODEL = "claude-sonnet-4-6"  # Use exactly this model id


def generate_analysis(
    market_data: dict[str, Any],
    report_type: str,
    news_items: list[dict[str, str]] | None = None,
    crypto_data: dict[str, Any] | None = None,
) -> str:
    """Generate a 3-paragraph analysis using Anthropic Claude.

    Args:
      market_data: dict returned from bot/market_data.py
      report_type: "pre-market" or "post-market"
      news_items: list of headline dicts from bot/news_fetcher.py
      crypto_data: dict returned from bot/crypto_data.py (CoinGecko)

    Returns:
      analysis text, or a fallback string if the API call fails.
    """

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY is not set; skipping analysis.", file=sys.stderr)
        return "Analysis unavailable at this time."

    model = DEFAULT_MODEL

    news_items = news_items or []
    if news_items:
        headlines_block = "Recent headlines:\n" + "\n".join(
            f"{i}. [{it.get('source','Unknown')}] {it.get('headline','').strip()} ({it.get('published_et','').strip()})"
            for i, it in enumerate(news_items, start=1)
        )
    else:
        headlines_block = "Recent headlines:\n(no headlines available)"

    market_block = f"```json\n{json.dumps(market_data, indent=2, sort_keys=True)}\n```"

    def _arrow(pct: float) -> str:
        return "▲" if pct >= 0 else "▼"

    def _fmt_price(v: float) -> str:
        return f"${v:,.2f}"

    def _fmt_vol_usd(v: float) -> str:
        if v >= 1_000_000_000:
            return f"${v / 1_000_000_000:,.2f}B"
        if v >= 1_000_000:
            return f"${v / 1_000_000:,.2f}M"
        return f"${v:,.0f}"

    if crypto_data is None:
        crypto_block = "Crypto data unavailable."
    else:
        major = crypto_data.get("major", {}) if isinstance(crypto_data, dict) else {}
        movers = crypto_data.get("notable_movers", []) if isinstance(crypto_data, dict) else []

        lines: list[str] = ["Crypto market data:"]
        for sym in ("BTC", "ETH", "SOL"):
            d = major.get(sym) or {}
            price = d.get("price")
            pct = d.get("pct_change_24h")
            vol = d.get("volume")
            if price is None or pct is None:
                lines.append(f"{sym}: n/a")
                continue
            vol_str = _fmt_vol_usd(float(vol)) if vol is not None else "n/a"
            lines.append(
                f"{sym}: {_fmt_price(float(price))} ({_arrow(float(pct))} {abs(float(pct)):.2f}% 24h) | Vol: {vol_str}"
            )

        lines.append("")
        if movers:
            lines.append("Notable altcoin movers (>=8% move):")
            for m in movers:
                ms = str(m.get("symbol") or "").upper()
                name = str(m.get("name") or "").strip()
                price = m.get("price")
                pct = m.get("pct_change_24h")
                if price is None or pct is None:
                    continue
                lines.append(
                    f"{ms} ({name}): {_fmt_price(float(price))} ({_arrow(float(pct))} {abs(float(pct)):.2f}% 24h)"
                )
        else:
            lines.append("Notable altcoin movers (>=8% move):")
            lines.append("No notable altcoin movers in top 20.")

        crypto_block = "\n".join(lines)

    if report_type == "pre-market":
        system_prompt = (
            "You are a concise financial analyst writing a pre-market briefing for a small group "
            "of personal investors. Your tone is clear, direct, and informative — not hype. "
            "Focus on what the data suggests investors should watch today. "
            "Always include ET timestamps when referencing timing."
        )
        instruction = (
            "Write a 3-paragraph pre-market briefing covering: "
            "(1) overnight/early equity market conditions based on the data, "
            "(2) crypto market conditions and any notable moves, "
            "(3) 2-3 specific things to watch when the market opens at 9:30 AM ET today."
        )
    else:
        system_prompt = (
            "You are a concise financial analyst writing a post-market recap for a small group of personal investors. "
            "Your tone is clear, direct, and informative — not hype. Focus on what happened today, "
            "why it likely happened, and what it might mean for tomorrow. Always include ET timestamps "
            "when referencing timing."
        )
        instruction = (
            "Write a 3-paragraph post-market recap covering: "
            "(1) how equities closed and what drove the day, "
            "(2) crypto performance and correlation to equities if notable, "
            "(3) what today's action suggests for tomorrow's open."
        )

    user_prompt = (
        "Market data (JSON):\n"
        f"{market_block}\n\n"
        f"{headlines_block}\n\n"
        f"{crypto_block}\n\n"
        f"{instruction}"
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
