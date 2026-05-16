from __future__ import annotations

import os
import re
import sys


RATINGS = {"BUY", "SELL", "HOLD", "WATCH"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}


_RATING_RE = re.compile(r"\b(BUY|SELL|HOLD|WATCH)\b", re.IGNORECASE)

# Matches: **TICKER (Company Name)** — RATING  or  **TICKER** — RATING
_HEADER_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*([A-Za-z][A-Za-z0-9.\-]{0,9})\s*(?:\([^\)]*\))?\s*(?:\*\*)?\s*[—–-]\s*(.*)$"
)


def _normalize_rating(raw: str) -> str:
    s = str(raw or "").strip()
    s = s.replace("**", "").replace("*", "").strip()
    m = _RATING_RE.search(s)
    normalized = m.group(1).upper() if m else (s.upper() if s else "")
    print(f"[parser] Normalized rating: {raw!r} → {normalized}")
    return normalized


def _normalize_confidence(raw: str) -> str:
    s = str(raw or "").strip()
    s = s.replace("**", "").replace("*", "").strip()
    low = s.lower()
    if "high" in low:
        normalized = "HIGH"
    elif "medium" in low:
        normalized = "MEDIUM"
    elif "low" in low:
        normalized = "LOW"
    else:
        normalized = s
    print(f"[parser] Normalized confidence: {raw!r} → {normalized}")
    return normalized


def _detect_format(block_lines: list[str]) -> str:
    """Return 'daily' if block contains 'Rating:' label, else 'weekly'."""
    for line in block_lines:
        if re.search(r"\brating\s*:", line, re.IGNORECASE):
            return "daily"
    return "weekly"


def _parse_block(block_lines: list[str], ticker: str, header_rating: str) -> dict | None:
    """Parse a single ticker block into a recommendation dict."""
    fmt = _detect_format(block_lines)
    print(f"[parser] Detected format: {fmt}")

    rating = ""
    reason = ""
    confidence = ""

    if fmt == "daily":
        # Daily: explicit Rating:/Reason:/Confidence: labels
        reason_lines = []
        in_reason = False
        for line in block_lines:
            stripped = line.strip()
            if not stripped:
                if in_reason:
                    reason_lines.append("")
                continue

            m_rating = re.search(r"\brating\s*[:\-—–]\s*([^\n]+)", stripped, re.IGNORECASE)
            if m_rating:
                in_reason = False
                rating = _normalize_rating(m_rating.group(1).strip().replace("*", ""))
                continue

            m_conf = re.search(r"\bconfidence\s*[:\-—–]\s*([^\n]+)", stripped, re.IGNORECASE)
            if m_conf:
                in_reason = False
                confidence = _normalize_confidence(m_conf.group(1).strip().replace("*", ""))
                continue

            low = stripped.lower()
            if low.startswith("reason:") or low.startswith("why:"):
                in_reason = True
                reason_lines.append(stripped.split(":", 1)[1].strip())
                continue

            if in_reason:
                reason_lines.append(stripped)

        reason = " ".join(l for l in reason_lines if l).strip()
    else:
        # Weekly format: multiple possible sub-formats
        # A) Single-line: "**WATCH** | reason text | *Confidence: Medium*" (all in header_rating)
        # B) Multi-line header: "WATCH | Confidence: Medium" then body lines have the reason
        # C) Multi-line: "WATCH" on header, body has reason + separate Confidence: line
        header_str = (header_rating or "").strip()

        # Check if everything is on one line (reason + confidence in header via pipes)
        if "|" in header_str:
            parts = [p.strip().replace("**", "").replace("*", "").strip() for p in header_str.split("|")]

            # First part is always the rating
            rating = _normalize_rating(parts[0])

            # Scan remaining parts for confidence; everything else is reason
            reason_parts = []
            for p in parts[1:]:
                if "confidence" in p.lower():
                    m_conf = re.search(r"\bconfidence\s*[:\-—–]\s*(.+)", p, re.IGNORECASE)
                    if m_conf:
                        confidence = _normalize_confidence(m_conf.group(1).strip())
                else:
                    if p:
                        reason_parts.append(p)

            reason = " ".join(reason_parts).strip()
        else:
            rating = _normalize_rating(header_str)

        # Also scan body lines for additional reason text or confidence
        reason_lines = []
        for line in block_lines:
            stripped = line.strip()
            if not stripped:
                continue
            m_conf = re.search(r"\bconfidence\s*[:\-—–]\s*([^\n]+)", stripped, re.IGNORECASE)
            if m_conf:
                if not confidence:
                    confidence = _normalize_confidence(m_conf.group(1).strip().replace("*", ""))
                continue
            # Skip lines that are just the rating word or separators
            cleaned = stripped.replace("*", "").replace("-", "").strip()
            if cleaned.upper() in RATINGS or not cleaned:
                continue
            reason_lines.append(stripped)

        # If we already have reason from header pipe, body lines add to it
        # If we don't have reason yet, body IS the reason
        body_reason = " ".join(reason_lines).strip().replace("**", "").replace("*", "").strip()
        if not reason and body_reason:
            reason = body_reason
        elif reason and body_reason:
            reason = reason + " " + body_reason

    # Clean up reason: remove markdown bold/italic
    reason = reason.replace("**", "").replace("*", "").strip()

    print(f"[parser] Raw reason text: {reason[:100]}")

    if ticker and rating and confidence:
        print(f"[parser] Successfully parsed: {ticker} — {rating} ({confidence})")
        return {"ticker": ticker, "rating": rating, "reason": reason, "confidence": confidence}
    return None


def parse_recommendations(text: str):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("[parser] Parsing ticker recommendations from Claude response...")

    try:
        lines = (text or "").splitlines()
        start = None
        for i, line in enumerate(lines):
            if "tickers to watch" in line.lower():
                start = i
                break

        found = start is not None
        print(f"[parser] Found 'Tickers to Watch' section: {found}")
        if start is None:
            return []

        # Collect until disclaimer or end.
        buf = []
        for line in lines[start + 1 :]:
            if "\u26a0\ufe0f" in line and "not financial advice" in line.lower():
                break
            buf.append(line.rstrip())

        if (os.getenv("PARSER_DEBUG") or "").strip().lower() in {"1", "true", "yes"}:
            window = "\n".join(lines[start : start + 30])
            print(f"[parser] Section start line: {lines[start].strip()[:200]}")
            print(f"[parser] Section window: {window[:800]}")

        # Split buf into blocks, each starting with a ticker header line
        blocks: list[tuple[str, str, list[str]]] = []  # (ticker, header_rating, body_lines)
        cur_ticker = ""
        cur_rating = ""
        cur_body: list[str] = []

        for raw in buf:
            m_tick = _HEADER_RE.match(raw)
            if m_tick:
                if cur_ticker:
                    blocks.append((cur_ticker, cur_rating, cur_body))
                cur_ticker = (m_tick.group(1) or "").strip().upper()
                remainder = (m_tick.group(2) or "").strip().replace("**", "").replace("*", "").strip()
                cur_rating = remainder
                cur_body = []
            elif cur_ticker:
                cur_body.append(raw)

        if cur_ticker:
            blocks.append((cur_ticker, cur_rating, cur_body))

        recs = []
        for ticker, header_rating, body_lines in blocks:
            rec = _parse_block(body_lines, ticker, header_rating)
            if rec:
                recs.append(rec)

        print(f"[parser] Parsed {len(recs)} recommendations")
        for r in recs:
            print(f"[parser] Recommendation: {r.get('ticker')} — {r.get('rating')} ({r.get('confidence')})")

        return recs
    except Exception as exc:
        print(f"[parser] WARNING: parsing failed — {exc}")
        return []
