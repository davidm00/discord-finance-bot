from __future__ import annotations

import json
import os
import sys
from typing import Any

from anthropic import Anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"

THEMATIC_WATCHLIST = {
    "defense": ["LMT", "RTX", "NOC", "GD", "BA", "LDOS", "SAIC", "BAH", "HII", "TDG"],
    "cyber": ["CRWD", "PANW", "ZS", "FTNT", "S", "CYBR", "PLTR"],
    "energy": ["XOM", "CVX", "COP", "SLB", "HAL", "EOG", "MPC"],
    "tech": ["NVDA", "AMD", "MSFT", "GOOGL", "META", "AMZN", "AAPL"],
}

DISCLAIMER_LINE = "⚠️ Not financial advice. For informational purposes only. Always do your own research."


def generate_analysis(
    market_data: dict[str, Any],
    crypto_data: dict[str, Any] | None,
    news_items: list[dict[str, str]] | None,
    political_data: dict[str, Any] | None,
    previous_reports: list[dict[str, Any]] | None,
    earnings: list[dict[str, Any]] | None,
    report_type: str,
    macro_context: dict[str, Any] | None = None,
    recent_signals: list[dict[str, str]] | None = None,
    signal_scorecard: str | None = None,
) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[claude] WARNING: ANTHROPIC_API_KEY is not set; skipping analysis.")
        return "Analysis unavailable at this time.\n\n" + DISCLAIMER_LINE

    print(f"[claude] Building prompt for {report_type}...")

    news_items = news_items or []
    previous_reports = previous_reports or []
    earnings = earnings or []

    print(f"[claude] Previous reports included: {len(previous_reports)}")
    print(f"[claude] Earnings included: {len(earnings)}")

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

    # (2) Crypto data block
    if crypto_data is None:
        crypto_block = "Crypto market data:\nCrypto data unavailable."
    else:
        major = crypto_data.get("major", {}) if isinstance(crypto_data, dict) else {}
        movers = crypto_data.get("notable_movers", []) if isinstance(crypto_data, dict) else []

        lines: list[str] = [
            "Crypto market data:",
            "For each major crypto, add a plain-English signal: is the price action suggesting continuation, reversal, or uncertainty? Keep it to one short sentence.",
        ]
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
        lines.append("Notable altcoin movers (>=8% move):")
        if movers:
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
            lines.append("No notable altcoin movers in top 20.")

        crypto_block = "\n".join(lines)

    # (3) News headlines block — with source weights and event classification
    if news_items:
        # Group headlines by event type
        event_groups: dict[str, list] = {}
        for it in news_items:
            et = it.get("event_type", "general")
            if et not in event_groups:
                event_groups[et] = []
            event_groups[et].append(it)

        event_emoji = {
            "earnings": "📊", "merger_acquisition": "🔀", "regulatory": "⚖️",
            "geopolitical": "🌍", "macro": "📈", "executive": "👔",
            "crypto": "₿", "general": "📰",
        }

        hl_parts = ["Recent headlines (tagged with source reliability 0.0-1.0 and event type):"]
        idx = 1
        for et, items_group in event_groups.items():
            emoji = event_emoji.get(et, "📰")
            label = et.upper().replace("_", " ")
            for it in items_group:
                source = it.get("source", "Unknown")
                weight = it.get("weight", "0.4")
                headline = it.get("headline", '').strip()
                pub = it.get("published_et", '').strip()
                hl_parts.append(f"{idx}. {emoji} {label}: [{source} {weight}] {headline} ({pub})")
                idx += 1
        headlines_block = "\n".join(hl_parts)
    else:
        headlines_block = "Recent headlines:\n(no headlines available)"

    # (4) Political block (same format as Phase 5)
    def _political_block() -> str:
        if political_data is None or not isinstance(political_data, dict):
            trades = []
            contracts = []
            correlations = []
        else:
            trades = political_data.get("trades") or []
            contracts = political_data.get("contracts") or []
            correlations = political_data.get("correlations") or []

        lines: list[str] = ["Recent congressional trades (>= $25K, last 7 days):"]
        if trades:
            for t in trades[:10]:
                pol = str(t.get("politician") or "").strip()
                party = str(t.get("party") or "?").strip()
                chamber = str(t.get("chamber") or "?").strip()
                tt = str(t.get("trade_type") or "?").upper()
                tick = str(t.get("ticker") or "").strip().upper()
                amt = str(t.get("amount_range") or "").strip()
                td = str(t.get("trade_date") or "").strip()
                lines.append(f"{pol} ({party}/{chamber}): {tt} {tick} | {amt} | traded {td}")
        else:
            lines.append("No recent trades above $25K.")

        lines.append("")
        lines.append("Major government contracts (>= $50M, last 30 days, defense/energy/tech):")
        if contracts:
            for c in contracts[:10]:
                rec = str(c.get("recipient") or "").strip()
                amt = str(c.get("amount_human") or c.get("amount") or "").strip()
                agency = str(c.get("agency") or "").strip()
                cd = str(c.get("date") or "").strip()
                desc = str(c.get("description") or "").strip()
                lines.append(f"{rec}: {amt} | {agency} | {cd}")
                if desc:
                    lines.append(f"Description: {desc[:240]}")
        else:
            lines.append("No major contracts found.")

        lines.append("")
        lines.append("Potential correlations (same company in trades + contracts within 30 days):")
        if correlations:
            for x in correlations[:10]:
                comp = str(x.get("company") or "").strip()
                tick = str(x.get("ticker") or "").strip().upper()
                ca = str(x.get("contract_amount") or "").strip()
                cdate = str(x.get("contract_date") or "").strip()
                pol = str(x.get("politician") or "").strip()
                ttype = str(x.get("trade_type") or "").strip().upper()
                tamt = str(x.get("trade_amount_range") or "").strip()
                tdate = str(x.get("trade_date") or "").strip()
                days = str(x.get("days_apart") or "")
                lines.append(
                    f"{comp} ({tick}): Contract {ca} on {cdate} | {pol} {ttype} {tamt} on {tdate} ({days} days apart)"
                )
        else:
            lines.append("No correlations detected.")

        return "\n".join(lines)

    political_block = _political_block()

    # (5) Earnings section
    earnings_block = ""
    if earnings:
        lines = ["Upcoming earnings (next 3 days):"]
        for e in earnings:
            sym = str(e.get("symbol") or "").upper().strip()
            comp = str(e.get("company") or "").strip()
            d = str(e.get("date") or "").strip()
            t = str(e.get("time") or "").strip() or "Unknown"
            eps = e.get("eps_estimate")
            eps_str = str(eps) if eps is not None else "Unknown"
            lines.append(f"{sym} ({comp}): {d} {t}")
            lines.append(f"EPS estimate: {eps_str}")
        earnings_block = "\n".join(lines)

    # (6) Thematic watchlist
    watchlist_block = (
        "Thematic watchlist for reference:\n"
        "Defense: LMT, RTX, NOC, GD, BA, LDOS, SAIC, BAH, HII, TDG\n"
        "Cyber: CRWD, PANW, ZS, FTNT, S, CYBR, PLTR\n"
        "Energy: XOM, CVX, COP, SLB, HAL, EOG, MPC\n"
        "Tech: NVDA, AMD, MSFT, GOOGL, META, AMZN, AAPL\n"
        "Flag any of these tickers that appear in today's news, contracts, or political trades."
    )

    # (7) Previous reports — use structured extraction for token efficiency
    prev_block = ""
    if previous_reports:
        from history_fetcher import format_prior_context_for_prompt
        prev_block = format_prior_context_for_prompt(previous_reports)

    # System prompt + instructions
    if report_type == "pre-market":
        system_prompt = (
            "You are a sharp, plain-spoken financial analyst writing a morning briefing for a small "
            "group of everyday investors who are smart but not finance professionals. Write like a "
            "knowledgeable friend texting them what they need to know before the market opens — "
            "clear, direct, and useful. No jargon. Instead of 'risk-on sentiment', say 'investors "
            "are feeling confident'. Instead of 'institutional conviction', say 'big money is buying'. "
            "Instead of 'macro headwinds', say 'the broader economy is creating problems'. Always "
            "explain WHY something matters, not just WHAT happened. When you reference previous "
            "reports, explicitly note what was predicted and whether it played out. Always include "
            "ET timestamps.\n\n"
            "CRITICAL LENGTH CONSTRAINT: Your ENTIRE response must be under 2800 characters total "
            "(including tickers section). This is a quick-read morning brief — not a deep dive. "
            "Each paragraph should be 2-3 sentences MAX. Each ticker entry should be under 250 characters. "
            "Use **bold** for section headers (not # markdown). Separate sections with ---."
        )
        analysis_instruction = (
            "Write a 4-paragraph pre-market briefing (keep each paragraph 2–3 sentences max):\n"
            "Paragraph 1: What the equity market data is telling us right now and why it matters.\n"
            "Paragraph 2: Crypto conditions and any plain-English signals on BTC, ETH, SOL.\n"
            "Paragraph 3: The most important catalyst driving markets today, labeling it in plain English as one of earnings/guidance, macro/rates, geopolitical, political trade, government contract, news, technical, sentiment, crypto, valuation, or sector rotation. Explain how it connects to any political trades or government contracts if relevant.\n"
            "Paragraph 4: If there are previous reports, note what was flagged and whether it played out. If not, skip this paragraph.\n"
            "Then add a 'What to Watch' section with exactly 3 numbered bullet points (1 sentence each) — specific, plain-English things to watch at the 9:30 AM ET open.\n"
            "Do not omit any required sections; if you're running long, shorten Paragraphs 1–3 instead of dropping sections."
        )
    else:
        system_prompt = (
            "You are a sharp, plain-spoken financial analyst writing an end-of-day recap for a small "
            "group of everyday investors who are smart but not finance professionals. Write like a "
            "knowledgeable friend explaining what happened today and what it means for tomorrow — "
            "clear, direct, and useful. No jargon. Instead of 'profit-taking', say 'investors sold "
            "to lock in gains'. Instead of 'oversold conditions', say 'the stock has dropped a lot "
            "and may be due for a bounce'. Always explain WHY something matters, not just WHAT "
            "happened. When you reference previous reports, explicitly note what was predicted and "
            "whether it played out. Always include ET timestamps.\n\n"
            "CRITICAL LENGTH CONSTRAINT: Your ENTIRE response must be under 2800 characters total "
            "(including tickers section). This is a quick-read end-of-day recap — not a deep dive. "
            "Each paragraph should be 2-3 sentences MAX. Each ticker entry should be under 250 characters. "
            "Use **bold** for section headers (not # markdown). Separate sections with ---."
        )
        analysis_instruction = (
            "Write a 4-paragraph post-market recap (keep each paragraph 2–3 sentences max):\n"
            "Paragraph 1: How equities closed today and the main reason why in plain terms.\n"
            "Paragraph 2: Crypto performance today and what it suggests for overnight/tomorrow.\n"
            "Paragraph 3: The biggest catalyst of the day, labeling it in plain English as one of earnings/guidance, macro/rates, geopolitical, political trade, government contract, news, technical, sentiment, crypto, valuation, or sector rotation. Explain how it connected to market moves and mention any political trades or contracts that are relevant.\n"
            "Paragraph 4: If there are previous reports, note what was flagged and whether it played out. If not, skip this paragraph.\n"
            "Then add a 'Tomorrow Watch' section with exactly 3 numbered bullet points (1 sentence each).\n"
            "Do not omit any required sections; if you're running long, shorten Paragraphs 1–3 instead of dropping sections."
        )

    ticker_instruction = (
        "Finally, add a 'Tickers to Watch' section with exactly 3-5 tickers (prefer 3 unless there are truly strong signals for more).\n\n"
        "Action calibration from prior signal tracking: avoid defaulting to WATCH just because markets are noisy. "
        "Use BUY or SELL when the bull/bear balance clearly points to a near-term directional trade with a catalyst, a confirming data point, an identifiable risk, and a 1-day/5-day/next-catalyst horizon. "
        "Use WATCH only when the setup is interesting but a required trigger is still missing; name the missing trigger in the Reason. "
        "Use HOLD only when the best decision is explicitly to wait or maintain a prior view. "
        "Do not force weak BUY/SELL calls, but do not hide actionable conviction behind WATCH.\n\n"
        "For each ticker, structure your analysis in three steps before giving a rating:\n\n"
        "BULL CASE: In one sentence, what is the strongest argument FOR this ticker right now based on today's data?\n\n"
        "BEAR CASE: In one sentence, what is the strongest argument AGAINST this ticker right now based on today's data?\n\n"
        "VERDICT: Weigh both sides and provide:\n"
        "- Rating: BUY / SELL / HOLD / WATCH\n"
        "- Catalyst Type: one of earnings, guidance, macro, rates, inflation, geopolitical, political_trade, government_contract, news, technical, sentiment, crypto, valuation, sector_rotation, other\n"
        "- Catalyst Detail: the specific event or data point that caused the call\n"
        "- Horizon: 1D / 5D / next catalyst, or the named event/date if known\n"
        "- Risk Trigger: what would invalidate or delay the call\n"
        "- Confidence: HIGH / MEDIUM / LOW\n"
        "- One plain-English sentence explaining the verdict, citing the specific data point that tips the balance and the intended near-term horizon (1 day, 5 days, or next known catalyst)\n\n"
        "Format each ticker exactly like this:\n\n"
        "**TICKER — Company Name**\n"
        "Bull: [bull case sentence]\n"
        "Bear: [bear case sentence]\n"
        "Rating: BUY/SELL/HOLD/WATCH\n"
        "Catalyst Type: [one allowed catalyst type]\n"
        "Catalyst Detail: [specific catalyst/event/data point]\n"
        "Horizon: [1D/5D/next catalyst or named event/date]\n"
        "Risk Trigger: [specific invalidation or delay trigger]\n"
        "Reason: [verdict sentence citing specific data + horizon]\n"
        "Confidence: HIGH/MEDIUM/LOW\n\n"
        "Do not put the company name on the Rating line. Do not put a rating on the Confidence line. "
        "Only recommend tickers that appear in today's actual data — news, contracts, political trades, market movers, or the thematic watchlist. "
        "Do not invent recommendations.\n"
        "Do not omit this section; if you're running long, shorten earlier paragraphs.\n"
        "End with this exact disclaimer on its own line (no quotes):\n"
        f"{DISCLAIMER_LINE}"
    )

    source_weight_instruction = (
        "News headlines are tagged with source reliability scores (0.0-1.0). "
        "Weight higher-scored sources more heavily in your analysis. "
        "Sources scoring below 0.5 should only be used if no higher-quality source covers the same story."
    )

    event_classification_instruction = (
        "Headlines are pre-classified by event type. For each type present, "
        "apply the appropriate analytical lens:\n"
        "- EARNINGS: focus on beat/miss vs estimates and forward guidance\n"
        "- GEOPOLITICAL: assess direct market impact and sector exposure\n"
        "- MACRO: evaluate Fed/rate implications for equities and crypto\n"
        "- M&A: consider sector implications and target/acquirer dynamics\n"
        "- REGULATORY: assess risk exposure for named companies\n"
        "- CRYPTO: note correlation to broader risk sentiment"
    )

    sections = [
        "Market data (JSON):\n" + market_block,
    ]

    # Macro context (TNX, DXY, Fear & Greed) — injected between market data and crypto
    if macro_context and isinstance(macro_context, dict):
        macro_lines = ["Macro context:"]
        if macro_context.get("treasury_10y") is not None:
            macro_lines.append(f"10-Year Treasury Yield: {macro_context['treasury_10y']}% (higher = pressure on growth stocks)")
        if macro_context.get("dollar_index") is not None:
            macro_lines.append(f"US Dollar Index (DXY): {macro_context['dollar_index']} (higher = pressure on commodities/crypto)")
        if macro_context.get("fear_greed_score") is not None:
            rating = macro_context.get("fear_greed_rating") or "Unknown"
            macro_lines.append(f"Fear & Greed Index: {macro_context['fear_greed_score']}/100 — {rating}")
            macro_lines.append("(0=Extreme Fear, 100=Extreme Greed; contrarian signal — extreme fear = potential buy)")
        if len(macro_lines) > 1:
            sections.append("\n".join(macro_lines))

    sections.append(crypto_block)
    sections.append(headlines_block)
    sections.append(political_block)

    if earnings_block:
        sections.append(earnings_block)

    sections.append(watchlist_block)

    if prev_block:
        sections.append(prev_block)

    # Outcome scorecard — compact feedback loop for calibrating future picks.
    if signal_scorecard:
        sections.append(signal_scorecard.strip())
    # Raw recent signals are a fallback when the outcome tracker has no data yet.
    elif recent_signals:
        sig_lines = [
            "RECENT SIGNALS (outcome scorecard unavailable; use cautiously to calibrate today's picks):",
            "Date | Ticker | Rating | Entry Price | Current Price | P&L",
        ]
        for s in recent_signals:
            sig_lines.append(
                f"{s.get('date_et','')} | {s.get('ticker','')} | {s.get('action','')} | "
                f"${s.get('price_at_signal','N/A')} | ${s.get('current_price','N/A')} | {s.get('pnl_pct','N/A')}"
            )
        sig_lines.append(
            "If re-recommending a ticker, reference your prior call and whether the thesis is playing out. "
            "You may absolutely re-recommend a ticker even if your prior call was wrong — just acknowledge the miss and explain your updated reasoning."
        )
        sections.append("\n".join(sig_lines))

    full_prompt = "\n\n".join(sections + [analysis_instruction, source_weight_instruction, event_classification_instruction, ticker_instruction])

    print(f"[claude] Prompt token estimate: ~{len(full_prompt) // 4} tokens")
    print(f"[claude] Calling Claude API (model={DEFAULT_MODEL})...")

    try:
        client = Anthropic(api_key=api_key)

        print("[claude] Prompt caching enabled on system prompt")
        msg = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=1500,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": full_prompt}],
        )

        # Log cache usage if available
        usage = getattr(msg, "usage", None)
        if usage:
            cache_creation = getattr(usage, "cache_creation_input_tokens", None)
            cache_read = getattr(usage, "cache_read_input_tokens", None)
            if cache_creation is not None:
                print(f"[claude] cache_creation_input_tokens: {cache_creation}")
            if cache_read is not None:
                print(f"[claude] cache_read_input_tokens: {cache_read}")

        parts = getattr(msg, "content", None)
        if not parts:
            return "Analysis unavailable at this time.\n\n" + DISCLAIMER_LINE

        text = getattr(parts[0], "text", None)
        out = (str(text).strip() if text else "").strip()
        if not out:
            return "Analysis unavailable at this time.\n\n" + DISCLAIMER_LINE

        print(f"[claude] Response received: {len(out)} chars")

        if DISCLAIMER_LINE not in out:
            out = out.rstrip() + "\n" + DISCLAIMER_LINE

        return out
    except Exception as exc:
        print(f"[claude] WARNING: {exc}")
        return "Analysis unavailable at this time.\n\n" + DISCLAIMER_LINE
