"""Phase 6: tone rewrite + history + earnings + recommendations.

This script fetches equity market data, crypto data (CoinGecko), headlines (Finnhub+RSS),
political/contract context, previous reports from Discord, and upcoming earnings.
It then asks Claude for a plain-English briefing/recap with tickers to watch, and posts
an embed to Discord.
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pytz
import requests

from cache_manager import install_cache
install_cache()

from claude_analysis import DISCLAIMER_LINE, generate_analysis
from crypto_data import fetch_crypto_data
from earnings_fetcher import fetch_upcoming_earnings
from history_fetcher import fetch_previous_reports
from market_calendar import get_market_state
from market_data import fetch_market_data, fetch_macro_context
from news_fetcher import fetch_top_headlines
from political_data import fetch_political_data
from recommendation_parser import parse_recommendations
from signal_logger import log_recommendations


ET_TZ = pytz.timezone("America/New_York")


def _ensure_utf8_console() -> None:
    # Windows PowerShell can default to cp1252 and crash on emoji output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _load_env_local() -> None:
    """Load repo-root .env.local for local testing (gitignored).

    - Does nothing in GitHub Actions unless you also create that file there (you shouldn't).
    - Never overwrites real environment variables.
    """

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(repo_root, ".env.local")
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        print("[report] Loaded .env.local for local testing")
    except Exception as exc:
        print(f"[report] WARNING: failed to load .env.local: {exc}")


def _label_for_run(now_et: datetime) -> str:
    return "pre-market" if now_et.hour < 12 else "post-market"


def _arrow(pct: float) -> str:
    return "▲" if pct >= 0 else "▼"


def _fmt_price_usd(v: float) -> str:
    return f"${v:,.2f}"


def _fmt_line(label: str, price: float | None, pct: float | None) -> str:
    if price is None or pct is None:
        return f"{label}: n/a"
    return f"{label}: {_fmt_price_usd(price)} ({_arrow(pct)} {abs(pct):.2f}%)"


def _all_none(section: dict) -> bool:
    return all(v is None for v in section.values())


def _enforce_disclaimer(text: str) -> str:
    text = (text or "").strip()
    if DISCLAIMER_LINE in text:
        return text

    # Keep within embed limits and always include disclaimer.
    base = text
    if len(base) > 3900:
        base = base[:3900].rstrip() + "…"
    return base + "\n" + DISCLAIMER_LINE


def _write_local_preview_markdown(embed: dict) -> str | None:
    """Legacy single-embed version — delegates to multi."""
    return _write_local_preview_markdown_multi([embed])


def _write_local_preview_markdown_multi(embeds: list[dict]) -> str | None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir = os.path.join(repo_root, "local-output")
    out_path = os.path.join(out_dir, "latest_report.md")

    try:
        os.makedirs(out_dir, exist_ok=True)

        parts: list[str] = []
        for embed in embeds:
            title = str(embed.get("title") or "").strip()
            desc = str(embed.get("description") or "").strip()
            fields = embed.get("fields") or []

            if title:
                parts.append(f"# {title}")
                parts.append("")
            if desc:
                parts.append("## Analysis")
                parts.append("")
                parts.append(desc)
                parts.append("")

            for f in fields:
                name = str((f or {}).get("name") or "").strip()
                value = str((f or {}).get("value") or "").strip()
                if not name:
                    continue
                parts.append(f"## {name}")
                parts.append("")
                parts.append(value or "(empty)")
                parts.append("")

        if not parts:
            parts.append("# Discord Finance Bot — Local Preview")

        with open(out_path, "w", encoding="utf-8") as out:
            out.write("\n".join(parts).rstrip() + "\n")

        return out_path
    except Exception as exc:
        print(f"[report] WARNING: failed to write local preview markdown: {exc}")
        return None


def _write_local_full_analysis(analysis: str) -> str | None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir = os.path.join(repo_root, "local-output")
    out_path = os.path.join(out_dir, "latest_claude_response.md")

    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write((analysis or "").rstrip() + "\n")
        return out_path
    except Exception as exc:
        print(f"[report] WARNING: failed to write full analysis: {exc}")
        return None


# Discord embed constraints (most common failure cause for webhook 400s)
DISCORD_EMBED_TOTAL_MAX = 6000
DISCORD_TITLE_MAX = 256
DISCORD_DESCRIPTION_MAX = 4096
DISCORD_FIELD_NAME_MAX = 256
DISCORD_FIELD_VALUE_MAX = 1024
DISCORD_FOOTER_TEXT_MAX = 2048


def _clamp_text(s: str, limit: int, ellipsis: str = "…") -> str:
    s = str(s or "")
    if len(s) <= limit:
        return s
    if limit <= len(ellipsis):
        return s[:limit]
    return s[: limit - len(ellipsis)].rstrip() + ellipsis


def _embed_char_count(embed: dict) -> int:
    title = str(embed.get("title") or "")
    desc = str(embed.get("description") or "")
    footer = embed.get("footer") or {}
    footer_text = str((footer or {}).get("text") or "")

    total = len(title) + len(desc) + len(footer_text)

    for f in (embed.get("fields") or []):
        total += len(str((f or {}).get("name") or ""))
        total += len(str((f or {}).get("value") or ""))

    return total


def _sanitize_embed(embed: dict) -> dict:
    # Clamp individual parts
    embed["title"] = _clamp_text(embed.get("title") or "", DISCORD_TITLE_MAX)
    embed["description"] = _clamp_text(embed.get("description") or "", DISCORD_DESCRIPTION_MAX)

    footer = embed.get("footer") or {}
    footer_text = _clamp_text((footer or {}).get("text") or "", DISCORD_FOOTER_TEXT_MAX)
    embed["footer"] = {"text": footer_text} if footer_text else {}

    fields_out = []
    for f in (embed.get("fields") or [])[:25]:
        name = _clamp_text((f or {}).get("name") or "", DISCORD_FIELD_NAME_MAX)
        value = _clamp_text((f or {}).get("value") or "", DISCORD_FIELD_VALUE_MAX)
        inline = bool((f or {}).get("inline"))
        fields_out.append({"name": name, "value": value or "(empty)", "inline": inline})

    embed["fields"] = fields_out

    # Clamp total embed size (6000 chars across title/desc/fields/footer)
    total = _embed_char_count(embed)
    if total <= DISCORD_EMBED_TOTAL_MAX:
        return embed

    # Prefer shrinking description first
    desc = str(embed.get("description") or "")
    if desc:
        over = total - DISCORD_EMBED_TOTAL_MAX
        min_desc = 400
        new_limit = max(min_desc, len(desc) - over)
        embed["description"] = _clamp_text(desc, new_limit)

    # If still too large, shrink long fields in a stable order
    shrink_order = [
        "📰 Top Headlines",
        "🎯 Tickers to Watch",
        "📋 Gov Contracts",
        "🏛️ Political Trades",
        "📅 Upcoming Earnings",
        "₿ Crypto",
        "🇺🇸 Equities",
    ]

    while True:
        total = _embed_char_count(embed)
        if total <= DISCORD_EMBED_TOTAL_MAX:
            break

        reduced = False
        over = total - DISCORD_EMBED_TOTAL_MAX

        for target in shrink_order:
            for f in embed.get("fields") or []:
                if f.get("name") != target:
                    continue
                v = str(f.get("value") or "")
                if len(v) <= 80:
                    continue
                new_limit = max(80, len(v) - over)
                f["value"] = _clamp_text(v, new_limit)
                reduced = True
                break
            if reduced:
                break

        if not reduced:
            break

    return embed


def main() -> int:
    _ensure_utf8_console()

    start = time.monotonic()

    _load_env_local()

    dry_run = (os.getenv("DRY_RUN") or "").strip().lower() in {"1", "true", "yes"}

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL is not set.", file=sys.stderr)
        return 0

    now_et = datetime.now(ET_TZ)
    report_type = _label_for_run(now_et)
    date_et = now_et.strftime("%Y-%m-%d")

    # Market state detection
    market_state = get_market_state()
    print(f"[report] Market state: {market_state['state']} — {market_state['label']}")

    print(f"[report] Report type: {report_type} ({date_et} ET)")

    print("[report] Fetching previous Discord reports...")
    previous_reports = []
    try:
        previous_reports = fetch_previous_reports()
    except Exception as exc:
        print(f"[report] WARNING: history fetch failed: {exc}")
        previous_reports = []
    print(f"[report] Previous reports found: {len(previous_reports)}")

    print("[report] Starting parallel data fetch (6 sources)...")
    fetch_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(fetch_upcoming_earnings): "earnings",
            executor.submit(fetch_market_data): "market",
            executor.submit(fetch_crypto_data): "crypto",
            executor.submit(fetch_top_headlines): "news",
            executor.submit(fetch_political_data): "political",
            executor.submit(fetch_macro_context): "macro",
        }
        results: dict[str, any] = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"[report] WARNING: {key} fetch failed in executor: {e}")
                results[key] = None

    earnings = results.get("earnings") or []
    market_data = results.get("market")
    crypto_data = results.get("crypto")
    headlines = results.get("news") or []
    political_data = results.get("political") or {}
    macro_context = results.get("macro")

    fetch_elapsed = time.monotonic() - fetch_start
    print(f"[report] All data fetched in {fetch_elapsed:.1f}s")

    if not market_data or _all_none(market_data.get("equities", {})):
        ts = now_et.strftime("%Y-%m-%d %H:%M ET")
        content = f"⚠️ Market data fetch failed at {ts}."
        print("[report] Sending Discord fallback message...")
        try:
            resp = requests.post(webhook_url, json={"content": content}, timeout=15)
        except requests.RequestException as exc:
            print(f"ERROR: Webhook POST failed: {exc}", file=sys.stderr)
            return 1
        if not (200 <= resp.status_code < 300):
            print(f"ERROR: Webhook POST failed with {resp.status_code}: {resp.text}", file=sys.stderr)
            return 1
        print(content)
        return 0

    print("[report] All data fetched. Starting Claude analysis...")
    analysis = generate_analysis(
        market_data=market_data,
        crypto_data=crypto_data,
        news_items=headlines,
        political_data=political_data,
        previous_reports=previous_reports,
        earnings=earnings,
        report_type=report_type,
        macro_context=macro_context,
    )

    analysis = _enforce_disclaimer(analysis)
    print(f"[report] Claude response length: {len(analysis)} chars")

    print("[report] Parsing ticker recommendations...")
    recs = parse_recommendations(analysis)
    print(f"[report] Recommendations parsed: {len(recs)}")

    # Signal logging
    if recs:
        log_recommendations(recs, report_type)
        print(f"[report] Signal logging complete: {len(recs)} signals logged")

    equities = market_data.get("equities", {})

    eq_lines = [
        _fmt_line("SPY", (equities.get("SPY") or {}).get("price") if equities.get("SPY") else None,
                  (equities.get("SPY") or {}).get("pct_change") if equities.get("SPY") else None),
        _fmt_line("QQQ", (equities.get("QQQ") or {}).get("price") if equities.get("QQQ") else None,
                  (equities.get("QQQ") or {}).get("pct_change") if equities.get("QQQ") else None),
        _fmt_line("DIA", (equities.get("DIA") or {}).get("price") if equities.get("DIA") else None,
                  (equities.get("DIA") or {}).get("pct_change") if equities.get("DIA") else None),
        _fmt_line("VIX", (equities.get("^VIX") or {}).get("price") if equities.get("^VIX") else None,
                  (equities.get("^VIX") or {}).get("pct_change") if equities.get("^VIX") else None),
    ]

    if crypto_data is None:
        cr_lines = ["Crypto data unavailable."]
    else:
        major = crypto_data.get("major", {}) if isinstance(crypto_data, dict) else {}
        movers = crypto_data.get("notable_movers", []) if isinstance(crypto_data, dict) else []

        cr_lines = [
            _fmt_line("BTC", (major.get("BTC") or {}).get("price") if major.get("BTC") else None,
                      (major.get("BTC") or {}).get("pct_change_24h") if major.get("BTC") else None),
            _fmt_line("ETH", (major.get("ETH") or {}).get("price") if major.get("ETH") else None,
                      (major.get("ETH") or {}).get("pct_change_24h") if major.get("ETH") else None),
            _fmt_line("SOL", (major.get("SOL") or {}).get("price") if major.get("SOL") else None,
                      (major.get("SOL") or {}).get("pct_change_24h") if major.get("SOL") else None),
        ]

        if movers:
            movers_str = ", ".join(
                f"{m.get('symbol','').upper()} {_arrow(float(m.get('pct_change_24h',0.0)))}{abs(float(m.get('pct_change_24h',0.0))):.2f}%"
                for m in movers
                if m.get("symbol") and m.get("pct_change_24h") is not None
            )
            if movers_str:
                cr_lines.append("")
                cr_lines.append(f"📢 Movers: {movers_str}")

    # Headlines field
    if headlines:
        hl_lines = [
            f"[{h.get('headline','').strip()}]({h.get('url','').strip()}) — {h.get('source','').strip()}"
            for h in headlines[:5]
            if (h.get("headline") and h.get("url"))
        ]
        headlines_value = "\n".join(hl_lines) if hl_lines else "No headlines available at this time."
    else:
        headlines_value = "No headlines available at this time."

    # Political fields
    trades = (political_data or {}).get("trades", []) if isinstance(political_data, dict) else []
    contracts = (political_data or {}).get("contracts", []) if isinstance(political_data, dict) else []
    correlations = (political_data or {}).get("correlations", []) if isinstance(political_data, dict) else []

    if trades:
        trade_lines = [
            f"{t.get('politician','').strip()} ({t.get('party','?').strip()}): {str(t.get('trade_type','?')).upper()} ${str(t.get('ticker','')).upper()} | {t.get('amount_range','').strip()} | published: {t.get('published_date','') or t.get('trade_date','').strip()}"
            for t in trades[:5]
        ]
        trades_value = "\n".join(trade_lines) if trade_lines else "No recent trades above $25K."
    else:
        trades_value = "No recent trades above $25K."

    if contracts:
        contract_lines = []
        for c in contracts[:3]:
            prefix = "🔁" if c.get("is_recurring") else "🆕"
            suffix = " (long-term renewal)" if c.get("is_recurring") else ""
            contract_lines.append(
                f"{prefix} {c.get('recipient','').strip()}: {c.get('amount_human', c.get('amount',''))} | {c.get('agency','').strip()}{suffix}"
            )
        contracts_value = "\n".join(contract_lines) if contract_lines else "No major contracts found."
        if correlations:
            contracts_value += f"\n\n⚠️ {len(correlations)} correlation(s) detected — see analysis above"
    else:
        contracts_value = "No major contracts found."

    # Earnings field
    if earnings:
        e_lines = []
        for e in earnings:
            sym = str(e.get("symbol") or "").upper()
            d = str(e.get("date") or "")
            t = str(e.get("time") or "Unknown")
            eps = e.get("eps_estimate")
            eps_str = str(eps) if eps is not None else "Unknown"
            e_lines.append(f"{sym}: {d} ({t}) | EPS est: {eps_str}")
        earnings_value = "\n".join(e_lines) if e_lines else "No major earnings in the next 3 days."
    else:
        earnings_value = "No major earnings in the next 3 days."

    # Recommendations field — Bull/Bear format
    if recs:
        parts = []
        for r in recs[:5]:
            parts.append(
                f"{r.get('ticker','').strip()} — {r.get('rating','').strip()} ({r.get('confidence','').strip()})"
            )
            if r.get("bull_case"):
                parts.append(f"🐂 {r['bull_case']}")
            if r.get("bear_case"):
                parts.append(f"🐻 {r['bear_case']}")
            parts.append(str(r.get("reason") or "").strip())
            parts.append("")
        parts.append("⚠️ Not financial advice. For informational purposes only.")
        rec_value = "\n".join(parts).strip()
    else:
        rec_value = "No strong signals identified today."

    market_label = market_state.get("label", "")
    if report_type == "pre-market":
        title = f"📈 Pre-Market Briefing — {date_et} ET | {market_label}"
        color = 3066993
    else:
        title = f"📉 Post-Market Recap — {date_et} ET | {market_label}"
        color = 15158332

    fetched_at_et = market_data.get("fetched_at_et", now_et.strftime("%Y-%m-%d %H:%M ET"))

    print("[report] Building Discord embeds...")

    # Split into multiple embeds to avoid 6000 char total limit per embed.
    # Embed 1: Analysis narrative + market prices
    # Embed 2: Data fields (political, contracts, headlines, earnings, tickers)
    embed1 = {
        "title": title,
        "color": color,
        "description": analysis[:4096],
        "fields": [
            {"name": "🇺🇸 Equities", "value": "\n".join(eq_lines), "inline": True},
            {"name": "₿ Crypto", "value": "\n".join(cr_lines), "inline": True},
        ],
    }

    embed2_fields = [
        {"name": "🏛️ Political Trades", "value": trades_value, "inline": False},
        {"name": "📋 Gov Contracts", "value": contracts_value, "inline": False},
        {"name": "📰 Top Headlines", "value": headlines_value, "inline": False},
        {"name": "📅 Upcoming Earnings", "value": earnings_value, "inline": False},
    ]
    # Tickers to Watch often exceeds field limit (1024 chars) with bull/bear cases,
    # so it goes in the description (4096 char limit) instead of a field.
    tickers_header = "**🎯 Tickers to Watch**\n" if rec_value else ""
    embed2 = {
        "color": color,
        "description": (tickers_header + rec_value)[:4096] if rec_value else "",
        "fields": embed2_fields,
        "footer": {"text": f"Data fetched at {fetched_at_et} | Personal use only"},
    }

    embeds = []
    for i, emb in enumerate([embed1, embed2]):
        pre_chars = _embed_char_count(emb)
        emb = _sanitize_embed(emb)
        post_chars = _embed_char_count(emb)
        label = f"embed{i+1}"
        if post_chars != pre_chars:
            print(f"[report] {label} clamped: {pre_chars} -> {post_chars} chars")
        else:
            print(f"[report] {label} size: {post_chars} chars")
        embeds.append(emb)

    # Discord's 6000 char limit is across ALL embeds in one message.
    # Send each embed as a separate webhook POST to get full 6000 chars per message.
    payloads = [{"embeds": [emb]} for emb in embeds]

    if dry_run:
        print("[report] DRY_RUN=1 set — not sending to Discord.")
        for i, emb in enumerate(embeds):
            preview = {
                "title": emb.get("title"),
                "fields": [f.get("name") for f in emb.get("fields") or []],
                "description_chars": len(emb.get("description") or ""),
            }
            print(f"[report] Embed {i+1} preview: {preview}")

        # Write local preview combining all embeds
        md_path = _write_local_preview_markdown_multi(embeds)
        if md_path:
            print(f"[report] Wrote local preview markdown: {md_path}")

        full_path = _write_local_full_analysis(analysis)
        if full_path:
            print(f"[report] Wrote full Claude response: {full_path}")

        elapsed = time.monotonic() - start
        print(f"[report] Done. Total runtime: {elapsed:.1f}s")
        return 0

    print(f"[report] Sending to Discord ({len(payloads)} message(s))...")
    for i, payload in enumerate(payloads):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=15)
        except requests.RequestException as exc:
            print(f"ERROR: Webhook POST (message {i+1}) failed: {exc}", file=sys.stderr)
            return 1

        if not (200 <= resp.status_code < 300):
            print(f"ERROR: Webhook POST (message {i+1}) failed with {resp.status_code}: {resp.text}", file=sys.stderr)
            return 1

        print(f"[report] Message {i+1}/{len(payloads)} sent successfully.")
        # Brief pause between messages to maintain order in Discord
        if i < len(payloads) - 1:
            time.sleep(1)

    elapsed = time.monotonic() - start
    print(f"[report] Done. Total runtime: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
