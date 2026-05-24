"""Phase 7: Weekly summary report.

Standalone script that posts a weekly wrap-up embed to Discord.

- Uses Discord channel history to build continuity and score prior calls.
- Degrades gracefully if any data source fails.
- Supports DRY_RUN=1 to avoid posting and to write markdown previews.
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import pytz
import requests
import yfinance as yf
from anthropic import Anthropic

from cache_manager import install_cache
install_cache()

from claude_analysis import DEFAULT_MODEL, DISCLAIMER_LINE
from history_fetcher import fetch_weekly_history
from market_calendar import get_market_state
from market_data import fetch_macro_context
from news_fetcher import fetch_top_headlines
from political_data import fetch_political_data
from recommendation_parser import parse_recommendations
from signal_logger import log_recommendations, CSV_PATH


ET_TZ = pytz.timezone("America/New_York")

DISCORD_EMBED_TOTAL_MAX = 6000
DISCORD_TITLE_MAX = 256
DISCORD_DESCRIPTION_MAX = 4096
DISCORD_FIELD_NAME_MAX = 256
DISCORD_FIELD_VALUE_MAX = 1024
DISCORD_FOOTER_TEXT_MAX = 2048


def _ensure_utf8_console() -> None:
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
        print("[weekly] Loaded .env.local for local testing")
    except Exception as exc:
        print(f"[weekly] WARNING: failed to load .env.local: {exc}")


def _clamp_text(s: str, limit: int, ellipsis: str = "…") -> str:
    s = str(s or "")
    if len(s) <= limit:
        return s
    if limit <= len(ellipsis):
        return s[:limit]
    return s[: limit - len(ellipsis)].rstrip() + ellipsis


def _section_aware_truncate(text: str, limit: int) -> str:
    """Truncate at the last section boundary (--- or **Header**) before the limit."""
    import re as _re
    if len(text) <= limit:
        return text
    boundaries = []
    for m in _re.finditer(r"\n---\n|\n\*\*[^*]+\*\*", text[:limit]):
        boundaries.append(m.start())
    if boundaries:
        cut_at = boundaries[-1]
        if cut_at > limit * 0.5:
            return text[:cut_at].rstrip()
    last_nl = text.rfind("\n", 0, limit)
    if last_nl > limit * 0.5:
        return text[:last_nl].rstrip()
    return text[:limit - 1].rstrip() + "…"


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

    total = _embed_char_count(embed)
    if total <= DISCORD_EMBED_TOTAL_MAX:
        return embed

    # Prefer shrinking description first.
    desc = str(embed.get("description") or "")
    if desc:
        over = total - DISCORD_EMBED_TOTAL_MAX
        min_desc = 600
        new_limit = max(min_desc, len(desc) - over)
        embed["description"] = _clamp_text(desc, new_limit)

    # If still too large, shrink long fields.
    shrink_order = [
        "🎯 Next Week Watchlist",
        "📋 Top Contracts",
        "🏛️ Political Activity",
        "📈 Weekly Performance",
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
                if len(v) <= 120:
                    continue
                new_limit = max(120, len(v) - over)
                f["value"] = _clamp_text(v, new_limit)
                reduced = True
                break
            if reduced:
                break

        if not reduced:
            break

    return embed


def _fmt_price(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"${v:,.2f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.2f}%"


def _write_local(path: str, text: str) -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir = os.path.join(repo_root, "local-output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write((text or "").rstrip() + "\n")
    print(f"[weekly] Wrote {out_path}")


def fetch_weekly_market_performance() -> dict[str, dict[str, Any]]:
    tickers = ["SPY", "QQQ", "DIA", "^VIX", "BTC-USD", "ETH-USD", "SOL-USD"]
    out: dict[str, dict[str, Any]] = {}

    print("[weekly] Fetching weekly market performance...")

    # Calculate most recent Monday-Friday range
    # If today is Saturday/Sunday, the week just ended is Mon-Fri
    # If called on a weekday, get the current week's Mon through today
    now_et = datetime.now(ET_TZ)
    today = now_et.date()
    weekday = today.weekday()  # Mon=0, Sun=6

    if weekday >= 5:  # Saturday(5) or Sunday(6)
        # Most recent Friday
        friday = today - __import__('datetime').timedelta(days=(weekday - 4))
        monday = friday - __import__('datetime').timedelta(days=4)
    else:
        # Current week
        monday = today - __import__('datetime').timedelta(days=weekday)
        friday = today

    # yfinance end is exclusive, add 1 day
    end_date = friday + __import__('datetime').timedelta(days=1)

    print(f"[weekly] Week range: {monday} to {friday}")

    for t in tickers:
        try:
            df = yf.download(t, start=str(monday), end=str(end_date), interval="1d", progress=False)
            if df is None or df.empty:
                continue

            # Normalize columns for both single and multi-index cases.
            def _col(name: str):
                v = None
                if name in df.columns:
                    v = df[name]
                elif getattr(df.columns, "nlevels", 1) > 1:
                    try:
                        v = df[(name, "")]
                    except Exception:
                        v = None

                # Ensure we return a 1-D series-like object
                try:
                    if v is not None and hasattr(v, "columns"):
                        v = v.iloc[:, 0]
                except Exception:
                    pass

                return v

            opens = _col("Open")
            closes = _col("Close")
            highs = _col("High")
            lows = _col("Low")

            if opens is None or closes is None or highs is None or lows is None:
                continue

            open_v = float(opens.iloc[0])
            close_v = float(closes.iloc[-1])
            high_v = float(highs.max())
            low_v = float(lows.min())
            pct = ((close_v - open_v) / open_v) * 100.0 if open_v else None

            # Daily % changes for mini-timeline
            daily_pcts = []
            for i in range(len(closes)):
                if i == 0:
                    day_pct = ((float(closes.iloc[0]) - open_v) / open_v) * 100.0 if open_v else 0
                else:
                    prev = float(closes.iloc[i - 1])
                    day_pct = ((float(closes.iloc[i]) - prev) / prev) * 100.0 if prev else 0
                daily_pcts.append(round(day_pct, 2))

            start_date = df.index[0]
            if hasattr(start_date, "date"):
                start_date_s = start_date.date().isoformat()
            else:
                start_date_s = str(start_date)[:10]

            out[t] = {
                "open": open_v,
                "close": close_v,
                "pct_change": pct,
                "high": high_v,
                "low": low_v,
                "week_start": start_date_s,
                "daily_pcts": daily_pcts,
            }
        except Exception as exc:
            print(f"[weekly] WARNING: weekly performance fetch failed for {t}: {exc}")

    print(f"[weekly] Weekly performance fetched for {len(out)} tickers")
    return out


def read_weekly_signals() -> list[dict[str, str]]:
    """Read signals.csv and return this week's entries with current prices."""
    import csv
    from datetime import timedelta

    if not os.path.isfile(CSV_PATH):
        print("[weekly] No signals.csv found — skipping signal history")
        return []

    now_et = datetime.now(ET_TZ)
    # Find most recent Monday
    days_since_monday = now_et.weekday()
    monday = (now_et - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    monday_str = monday.strftime("%Y-%m-%d")

    signals = []
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("date_et", "") >= monday_str:
                    signals.append(row)
    except Exception as exc:
        print(f"[weekly] WARNING: failed to read signals.csv: {exc}")
        return []

    if not signals:
        print("[weekly] No signals found for this week in CSV")
        return signals

    print(f"[weekly] Read {len(signals)} signals from CSV for week of {monday_str}")

    # Fetch current prices for unique tickers (batch, capped at 15)
    seen: set[str] = set()
    unique_tickers: list[str] = []
    for s in reversed(signals):
        t = s.get("ticker", "").upper().strip()
        if t and t not in seen:
            seen.add(t)
            unique_tickers.append(t)

    current_prices: dict[str, float] = {}
    for ticker in unique_tickers[:15]:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="2d")
            if hist is not None and not hist.empty:
                current_prices[ticker] = round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass

    # Enrich signals with current price and P&L
    for s in signals:
        ticker = s.get("ticker", "")
        entry_str = s.get("price_at_signal", "")
        if ticker in current_prices and entry_str and entry_str != "N/A":
            try:
                entry = float(entry_str)
                current = current_prices[ticker]
                pnl_pct = ((current - entry) / entry) * 100.0
                s["current_price"] = f"{current:.2f}"
                s["pnl_pct"] = f"{pnl_pct:+.2f}%"
            except (ValueError, ZeroDivisionError):
                s["current_price"] = "N/A"
                s["pnl_pct"] = "N/A"
        else:
            s["current_price"] = "N/A"
            s["pnl_pct"] = "N/A"

    return signals


def build_weekly_prompt(
    weekly_perf: dict[str, dict[str, Any]],
    weekly_history: list[dict[str, Any]],
    headlines: list[dict[str, Any]],
    political: dict[str, Any],
    weekly_signals: list[dict[str, str]] | None = None,
) -> str:
    lines: list[str] = []

    # 1) Weekly market performance
    lines.append("Weekly performance (Monday open → Friday close):")
    for t in ["SPY", "QQQ", "DIA", "^VIX", "BTC-USD", "ETH-USD", "SOL-USD"]:
        d = weekly_perf.get(t) or {}
        if not d:
            continue
        o = d.get("open")
        c = d.get("close")
        pct = d.get("pct_change")
        hi = d.get("high")
        lo = d.get("low")
        label = t.replace("-USD", "")
        lines.append(
            f"{label}: {_fmt_price(o)} → {_fmt_price(c)} ({_fmt_pct(pct)}) | High: {_fmt_price(hi)} | Low: {_fmt_price(lo)}"
        )

    # 2) Weekly Discord history
    if weekly_history:
        lines.append("")
        lines.append("This week's daily reports (oldest to newest):")
        for r in weekly_history:
            rt = r.get("report_type") or "unknown"
            ts = r.get("timestamp_et") or ""
            analysis = (r.get("analysis") or "").strip()
            fields = r.get("fields") or {}
            tickers_field = fields.get("🎯 Tickers to Watch") or fields.get("Tickers to Watch") or "(none)"

            lines.append(f"--- {rt} | {ts} ---")
            lines.append(analysis)
            lines.append(f"Tickers to Watch field: {tickers_field}")
            lines.append("---")

        lines.append(
            "Use these reports to: (a) identify the dominant themes of the week, (b) score any BUY/SELL/HOLD/WATCH calls against the weekly close data above, (c) note what the bot got right and wrong."
        )

    # 2b) Structured signal log (precise entry prices + current prices for scoring)
    if weekly_signals:
        lines.append("")
        lines.append("STRUCTURED SIGNAL LOG (exact entry prices from this week — use these for Bot Scorecard):")
        lines.append("Date | Time | Ticker | Rating | Confidence | Entry Price | Current Price | P&L")
        for s in weekly_signals:
            lines.append(
                f"{s.get('date_et','')} | {s.get('time_et','')} | {s.get('ticker','')} | "
                f"{s.get('action','')} | {s.get('confidence','')} | "
                f"${s.get('price_at_signal','N/A')} | ${s.get('current_price','N/A')} | {s.get('pnl_pct','N/A')}"
            )
        lines.append(
            "Use these EXACT prices in the Bot Scorecard — do not approximate. "
            "Entry Price is what the ticker was trading at when the call was made. "
            "Current Price is Friday's close. "
            "ALSO use this performance history when making Tickers to Watch Next Week picks: "
            "if a prior thesis played out, say whether it has further room to run. "
            "If you were wrong, acknowledge the miss and recalibrate your conviction. "
            "You may still re-recommend the same ticker — just explain what has changed or why you remain convicted despite the prior miss."
        )

    # 3) Headlines
    lines.append("")
    if headlines:
        lines.append("This week's top headlines:")
        for i, h in enumerate(headlines, start=1):
            lines.append(
                f"{i}. [{h.get('source','Unknown')}] {str(h.get('headline','')).strip()} ({str(h.get('published_et','')).strip()})"
            )
    else:
        lines.append("This week's top headlines:\n(no headlines available)")

    # 4/5) Political trades + contracts
    trades = (political or {}).get("trades") or []
    contracts = (political or {}).get("contracts") or []
    correlations = (political or {}).get("correlations") or []

    lines.append("")
    lines.append("Political trades this week (>= $25K, last 7 days):")
    if trades:
        for t in trades[:15]:
            lines.append(
                f"{t.get('politician','').strip()} ({t.get('party','?').strip()}/{t.get('chamber','?').strip()}): {str(t.get('trade_type','?')).upper()} {str(t.get('ticker','')).upper()} | {t.get('amount_range','')} | traded {t.get('trade_date','')}"
            )
    else:
        lines.append("No notable trades this week.")

    lines.append("")
    lines.append("Major government contracts this week ($10M+, last 7 days, defense/intel/energy/homeland filtered):")
    if contracts:
        for c in contracts[:10]:
            lines.append(
                f"{c.get('recipient','').strip()}: {c.get('amount_human', c.get('amount',''))} | {c.get('agency','').strip()} | {c.get('date','').strip()}"
            )
    else:
        lines.append("No major contracts found.")

    if correlations:
        lines.append("")
        lines.append("Potential correlations (same company in trades + contracts within 30 days):")
        for x in correlations[:10]:
            lines.append(
                f"{x.get('company','')} ({str(x.get('ticker','')).upper()}): Contract {x.get('contract_amount','')} on {x.get('contract_date','')} | {x.get('politician','')} {str(x.get('trade_type','')).upper()} {x.get('trade_amount_range','')} on {x.get('trade_date','')} ({x.get('days_apart','')} days apart)"
            )

    # 6) Instruction
    lines.append("")
    lines.append(
        "Write a weekly summary with the following sections. Use plain English throughout.\n\n"
        "**Week in Review** (2 paragraphs):\n"
        "Paragraph 1: How did markets perform this week overall and what was the dominant theme or catalyst? Reference specific price moves from the data.\n"
        "Paragraph 2: Crypto performance this week — what did BTC/ETH/SOL do and why? Any notable altcoin moves worth flagging?\n\n"
        "**Biggest Story of the Week** (1 paragraph):\n"
        "What was the single most important news event or theme this week and how did it affect markets? Be specific.\n\n"
        "**Political Trades & Contracts** (1 paragraph):\n"
        "Summarize any notable congressional trades or major government contracts from this week. If correlations exist between the two, call them out plainly. If nothing notable, say so briefly.\n\n"
        "**Bot Scorecard** (only include if previous daily reports are available):\n"
        "For each BUY/SELL/HOLD/WATCH call made in this week's daily reports, score it:\n"
        "- TICKER — original rating — specific entry price from the data (e.g., $745.64, not '~$118 area') — Friday close price — result: ✅ played out / ❌ did not play out / ⏳ too early to tell\n"
        "Use actual prices from the structured data fields, not approximations.\n"
        "Be honest. If the bot was wrong, say so plainly and briefly explain why.\n"
        "If no previous reports available, skip this section entirely.\n\n"
        "**Week Ahead** (bullet points):\n"
        "- List 3-5 specific things to watch next week: upcoming earnings, Fed events, macro data releases, or unresolved themes from this week\n"
        "- Keep each point to one plain-English sentence\n\n"
        "**Tickers to Watch Next Week**:\n"
        "Same format as daily report — 3-5 tickers with BUY/SELL/HOLD/WATCH rating, one-sentence reason, and confidence level. Based on weekly data and themes, not just today's snapshot.\n"
        f"End with the standard disclaimer on its own line:\n{DISCLAIMER_LINE}"
    )

    return "\n".join(lines).strip()


def main() -> int:
    _ensure_utf8_console()
    _load_env_local()
    start = time.monotonic()

    print("[weekly] Starting weekly summary report...")

    dry_run = (os.getenv("DRY_RUN") or "").strip().lower() in {"1", "true", "yes"}
    webhook_url = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()

    if not webhook_url and not dry_run:
        print("[weekly] WARNING: DISCORD_WEBHOOK_URL not set; cannot post.")
        return 0

    print("[weekly] Starting parallel data fetch (4 sources)...")
    fetch_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_weekly_market_performance): "weekly_perf",
            executor.submit(fetch_top_headlines): "headlines",
            executor.submit(fetch_political_data, 7): "political",
            executor.submit(fetch_macro_context): "macro",
        }
        results: dict[str, any] = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"[weekly] WARNING: {key} fetch failed in executor: {e}")
                results[key] = None

    weekly_perf = results.get("weekly_perf") or {}
    headlines = results.get("headlines") or []
    political = results.get("political") or {}
    macro_context = results.get("macro")

    fetch_elapsed = time.monotonic() - fetch_start
    print(f"[weekly] All data fetched in {fetch_elapsed:.1f}s")

    print("[weekly] Fetching weekly Discord history...")
    weekly_history: list[dict[str, Any]] = []
    try:
        weekly_history = fetch_weekly_history()
    except Exception as exc:
        print(f"[weekly] WARNING: weekly history fetch failed: {exc}")
        weekly_history = []
    print(f"[weekly] Weekly history: {len(weekly_history)} reports found")

    # Read structured signal log for Bot Scorecard accuracy
    print("[weekly] Reading signals.csv for this week...")
    weekly_signals: list[dict[str, str]] = []
    try:
        weekly_signals = read_weekly_signals()
    except Exception as exc:
        print(f"[weekly] WARNING: signal read failed: {exc}")
        weekly_signals = []

    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()

    system_prompt = (
        "You are a plain-spoken financial analyst writing a weekly wrap-up for a small group "
        "of everyday investors. Write like a knowledgeable friend summarizing what happened "
        "this week in markets — clear, direct, and useful. No jargon. Explain why things "
        "happened, not just what happened. Reference specific data points from the week. "
        "When the previous daily reports are available, synthesize them into a coherent "
        "weekly narrative and explicitly score any ticker calls the bot made — did the "
        "BUY/WATCH/HOLD calls play out? Be honest if they didn't. Always use ET timestamps.\n\n"
        "CRITICAL LENGTH CONSTRAINT: Your ENTIRE response must be under 3800 characters total. "
        "Budget per section: Week in Review (800 chars), Biggest Story (400 chars), "
        "Political Trades (400 chars), Bot Scorecard (600 chars), Week Ahead (300 chars), "
        "Tickers to Watch (500 chars). "
        "This is a quick-read weekly summary — not a deep research report. "
        "Use **bold** for section headers (not # markdown). Separate sections with ---."
    )

    print("[weekly] Building Claude prompt...")
    user_prompt = build_weekly_prompt(weekly_perf, weekly_history, headlines, political, weekly_signals)

    # Append macro context to user prompt if available
    if macro_context:
        macro_lines = ["\nMacro context:"]
        if macro_context.get("treasury_10y") is not None:
            macro_lines.append(f"10-Year Treasury Yield: {macro_context['treasury_10y']}% (higher = pressure on growth stocks)")
        if macro_context.get("dollar_index") is not None:
            macro_lines.append(f"US Dollar Index (DXY): {macro_context['dollar_index']} (higher = pressure on commodities/crypto)")
        if macro_context.get("fear_greed_score") is not None:
            rating = macro_context.get("fear_greed_rating", "Unknown")
            macro_lines.append(f"Fear & Greed Index: {macro_context['fear_greed_score']}/100 — {rating}")
            macro_lines.append("(0=Extreme Fear, 100=Extreme Greed; contrarian signal — extreme fear = potential buy)")
        if len(macro_lines) > 1:
            user_prompt += "\n" + "\n".join(macro_lines)

    print(f"[weekly] Prompt token estimate: ~{len(user_prompt)//4} tokens")

    analysis = ""
    recs = []
    if not api_key:
        print("[weekly] WARNING: ANTHROPIC_API_KEY not set; skipping Claude analysis.")
        analysis = "Weekly analysis unavailable at this time.\n\n" + DISCLAIMER_LINE
    else:
        try:
            print("[weekly] Calling Claude API...")
            client = Anthropic(api_key=api_key)

            print("[claude] Prompt caching enabled on system prompt")
            msg = client.messages.create(
                model=DEFAULT_MODEL,
                max_tokens=2000,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_prompt}],
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
            text = getattr(parts[0], "text", None) if parts else None
            analysis = (str(text).strip() if text else "").strip()
            if not analysis:
                analysis = "Weekly analysis unavailable at this time."

            if DISCLAIMER_LINE not in analysis:
                analysis = analysis.rstrip() + "\n" + DISCLAIMER_LINE

            print(f"[weekly] Response received: {len(analysis)} chars")

            # Parse tickers BEFORE truncation (truncation may cut the tickers section)
            print("[weekly] Parsing ticker recommendations...")
            try:
                recs = parse_recommendations(analysis)
            except Exception as exc:
                print(f"[weekly] WARNING: parser failed: {exc}")
                recs = []

            # Pre-flight: ensure analysis fits embed description (max 4096, target 3800)
            if len(analysis) > 3800:
                print(f"[weekly] WARNING: Analysis exceeds 3800 chars, truncating at section boundary")
                analysis = _section_aware_truncate(analysis, 3800)
        except Exception as exc:
            print(f"[weekly] WARNING: Claude call failed: {exc}")
            analysis = "Weekly analysis unavailable at this time.\n\n" + DISCLAIMER_LINE

    if not recs:
        print("[weekly] No recommendations parsed from analysis.")

    # Signal logging
    if recs:
        log_recommendations(recs, "weekly")
        print(f"[weekly] Signal logging complete: {len(recs)} signals logged")

    # Monday date for title/footer
    monday_date = ""
    for t in ("SPY", "QQQ", "DIA", "^VIX"):
        if t in weekly_perf and weekly_perf[t].get("week_start"):
            monday_date = str(weekly_perf[t]["week_start"])
            break
    if not monday_date:
        monday_date = datetime.now(ET_TZ).strftime("%Y-%m-%d")

    # Fields
    perf_lines = []
    for t in ["SPY", "QQQ", "DIA", "^VIX", "BTC-USD", "ETH-USD", "SOL-USD"]:
        d = weekly_perf.get(t) or {}
        if not d:
            continue
        label = t.replace("-USD", "")
        perf_lines.append(
            f"{label}: {_fmt_price(d.get('open'))}→{_fmt_price(d.get('close'))} ({_fmt_pct(d.get('pct_change'))}) | Range: {_fmt_price(d.get('low'))}–{_fmt_price(d.get('high'))}"
        )

    # Add daily arc timeline for SPY (market bellwether)
    spy_data = weekly_perf.get("SPY") or {}
    spy_daily = spy_data.get("daily_pcts") or []
    if spy_daily:
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri"]
        arc_parts = []
        for i, pct in enumerate(spy_daily[:5]):
            label = day_labels[i] if i < len(day_labels) else f"D{i+1}"
            arrow = "▲" if pct >= 0 else "▼"
            arc_parts.append(f"{label}: {arrow}{abs(pct):.1f}%")
        perf_lines.append(f"📊 SPY Daily Arc: {' → '.join(arc_parts)}")

    trades = (political or {}).get("trades") or []
    contracts = (political or {}).get("contracts") or []

    if trades:
        # Consolidate trades by politician + trade direction (same as daily report)
        from collections import OrderedDict
        grouped = OrderedDict()
        for t in trades:
            politician = t.get('politician', '').strip()
            party = t.get('party', '?').strip()
            direction = str(t.get('trade_type', '?')).upper()
            key = (politician, party, direction)
            if key not in grouped:
                grouped[key] = {"tickers": [], "non_stock_count": 0, "amounts": [], "date": ""}
            ticker = str(t.get('ticker', '')).upper()
            if ticker and ticker != "N/A":
                grouped[key]["tickers"].append(f"${ticker}")
            else:
                grouped[key]["non_stock_count"] += 1
            grouped[key]["amounts"].append(t.get('amount_range', '').strip())
            grouped[key]["date"] = t.get('published_date', '') or t.get('trade_date', '').strip()

        trade_lines = []
        for (politician, party, direction), info in grouped.items():
            parts = list(info["tickers"][:6])
            if len(info["tickers"]) > 6:
                parts.append(f"+{len(info['tickers']) - 6} more")
            if info["non_stock_count"] > 0:
                ns = info["non_stock_count"]
                parts.append(f"{ns} non-stock asset{'s' if ns > 1 else ''}")
            tickers_str = ", ".join(parts) if parts else "Non-stock assets"

            total_count = len(info["tickers"]) + info["non_stock_count"]
            count_label = f" ({total_count} trades)" if total_count > 1 else ""

            unique_amounts = list(dict.fromkeys(info["amounts"]))
            amount_display = unique_amounts[0] if len(unique_amounts) == 1 else f"{unique_amounts[0]} to {unique_amounts[-1]}"

            trade_lines.append(
                f"{politician} ({party}): {direction} {tickers_str}{count_label} | {amount_display} | {info['date']}"
            )
        political_value = "\n".join(trade_lines[:8]) if trade_lines else "No notable trades this week."
    else:
        political_value = "No notable trades this week."

    if contracts:
        contract_lines = []
        for c in contracts[:5]:
            prefix = "🔁" if c.get("is_recurring") else "🆕"
            suffix = " (long-term renewal)" if c.get("is_recurring") else ""
            contract_lines.append(
                f"{prefix} {c.get('recipient','').strip()}: {c.get('amount_human', c.get('amount',''))} | {c.get('agency','').strip()}{suffix}"
            )
        contracts_value = "\n".join(contract_lines) if contract_lines else "No major contracts found."
    else:
        contracts_value = "No major contracts found."

    if recs:
        parts = []
        for r in recs[:5]:
            parts.append(f"{r.get('ticker','').strip()} — {r.get('rating','').strip()} ({r.get('confidence','').strip()})")
            parts.append(str(r.get("reason") or "").strip())
            parts.append("")
        parts.append("⚠️ Not financial advice. For informational purposes only.")
        rec_value = "\n".join(parts).strip()
    else:
        rec_value = "No strong signals identified for next week."

    print("[weekly] Building Discord embed...")
    embed = {
        "title": f"📊 Weekly Market Summary — Week of {monday_date} ET",
        "color": 9442302,
        "description": analysis,
        "fields": [
            {"name": "📈 Weekly Performance", "value": "\n".join(perf_lines) or "Performance unavailable.", "inline": False},
            {"name": "🏛️ Political Activity", "value": political_value, "inline": False},
            {"name": "📋 Top Contracts", "value": contracts_value, "inline": False},
            {"name": "🎯 Next Week Watchlist", "value": rec_value, "inline": False},
        ],
        "footer": {"text": f"Weekly summary | Week of {monday_date} | Personal use only"},
    }

    embed = _sanitize_embed(embed)

    if dry_run:
        print("[weekly] DRY_RUN=1 set — not sending to Discord.")
        _write_local("latest_weekly_report.md", _render_markdown(embed))
        _write_local("latest_weekly_claude_response.md", analysis)
        elapsed = time.monotonic() - start
        print(f"[weekly] Weekly report complete. Runtime: {elapsed:.1f}s")
        return 0

    print("[weekly] Sending weekly report to Discord...")
    try:
        resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=20)
    except requests.RequestException as exc:
        print(f"[weekly] WARNING: Webhook POST failed: {exc}")
        return 1

    if not (200 <= resp.status_code < 300):
        print(f"[weekly] WARNING: Webhook POST failed with {resp.status_code}: {resp.text[:500]}")
        return 1

    elapsed = time.monotonic() - start
    print(f"[weekly] Weekly report complete. Runtime: {elapsed:.1f}s")
    return 0


def _render_markdown(embed: dict) -> str:
    title = str(embed.get("title") or "").strip()
    desc = str(embed.get("description") or "").strip()
    fields = embed.get("fields") or []

    parts: list[str] = []
    parts.append(f"# {title}" if title else "# Weekly Market Summary")
    parts.append("")
    parts.append("## Analysis")
    parts.append("")
    parts.append(desc or "(no analysis)")
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

    return "\n".join(parts).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
