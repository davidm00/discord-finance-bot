from __future__ import annotations

import os
import re
import sys


RATINGS = {"BUY", "SELL", "HOLD", "WATCH"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}


_RATING_RE = re.compile(r"\b(BUY|SELL|HOLD|WATCH)\b", re.IGNORECASE)


def _normalize_rating(raw: str) -> str:
    s = str(raw or "").strip()
    s = s.replace("**", "").replace("*", "").strip()

    m = _RATING_RE.search(s)
    if m:
        return m.group(1).upper()

    return s.upper() if s else ""


def _normalize_confidence(raw: str) -> str:
    s = str(raw or "").strip()
    s = s.replace("**", "").replace("*", "").strip()

    low = s.lower()
    if "high" in low:
        return "HIGH"
    if "medium" in low:
        return "MEDIUM"
    if "low" in low:
        return "LOW"

    return s


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
            if "⚠️" in line and "not financial advice" in line.lower():
                break
            buf.append(line.rstrip())

        section_text = "\n".join(buf).strip()

        if (os.getenv("PARSER_DEBUG") or "").strip().lower() in {"1", "true", "yes"}:
            # Debug window so we can see what the parser matched.
            window = "\n".join(lines[start : start + 30])
            print(f"[parser] Section start line: {lines[start].strip()[:200]}")
            print(f"[parser] Section window: {window[:800]}")
            print(f"[parser] Raw section text: {section_text[:500]}")

        recs = []
        cur = None

        def flush():
            nonlocal cur
            if not cur:
                return
            if cur.get("ticker") and cur.get("rating") and cur.get("confidence"):
                recs.append(cur)
            cur = None

        ticker_line_re = re.compile(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?\s*([A-Za-z][A-Za-z0-9.\-]{0,9})\s*(?:\([^\)]*\))?\s*(?:\*\*)?\s*[—–-]\s*(.*)$"
        )

        for raw in buf:
            # Claude sometimes concatenates blocks like: "Confidence: MEDIUM---**NVDA — Nvidia**"
            # Split on common separators to keep parsing simple and robust.
            chunks = [c.strip() for c in raw.split("---") if c.strip()]
            for chunk in chunks:
                line = chunk.strip()
                if not line:
                    continue

                # New record if line contains a likely ticker header.
                m_tick = ticker_line_re.match(line)
                if m_tick:
                    flush()
                    ticker = (m_tick.group(1) or "").strip().upper()
                    cur = {"ticker": ticker, "rating": "", "reason": "", "confidence": ""}

                    remainder = (m_tick.group(2) or "").strip()
                    if remainder:
                        rem_low = remainder.lower()
                        if "confidence" in rem_low or "rating" in rem_low or "|" in remainder or _RATING_RE.search(remainder):
                            line = remainder
                        else:
                            continue
                    else:
                        continue

                if cur is None:
                    continue

                # Pipe-style weekly lines look like:
                # "**WATCH** | ...reason... | *Confidence: Medium-High*"
                if "|" in line:
                    parts = [p.strip() for p in line.split("|")]

                    if parts and not cur.get("rating"):
                        raw_rating = parts[0].strip()
                        normalized = _normalize_rating(raw_rating)
                        if normalized:
                            print(f"[parser] Normalized rating: {raw_rating} → {normalized}")
                            cur["rating"] = normalized

                    if len(parts) >= 2 and not cur.get("reason"):
                        reason_raw = parts[1].replace("**", "").replace("*", "").strip()
                        if reason_raw:
                            cur["reason"] = reason_raw

                    for p in parts[1:]:
                        if "confidence" in p.lower():
                            m_conf = re.search(r"\bconfidence\s*[:\-—–]\s*([^\n]+)", p, flags=re.IGNORECASE)
                            raw_conf = (m_conf.group(1) if m_conf else p).strip()
                            raw_conf = raw_conf.replace("*", "").strip()
                            normalized = _normalize_confidence(raw_conf)
                            if normalized:
                                print(f"[parser] Normalized confidence: {raw_conf} → {normalized}")
                                cur["confidence"] = normalized
                    continue

                low = line.lower()

                # Label-style parsing
                m_rating = re.search(r"\brating\s*[:\-—–]\s*([^\n]+)", line, flags=re.IGNORECASE)
                if m_rating:
                    raw_val = m_rating.group(1).strip().replace("*", "")
                    normalized = _normalize_rating(raw_val)
                    if normalized:
                        print(f"[parser] Normalized rating: {raw_val} → {normalized}")
                        cur["rating"] = normalized

                m_conf = re.search(r"\bconfidence\s*[:\-—–]\s*([^\n]+)", line, flags=re.IGNORECASE)
                if m_conf:
                    raw_val = m_conf.group(1).strip().replace("*", "")
                    normalized = _normalize_confidence(raw_val)
                    if normalized:
                        print(f"[parser] Normalized confidence: {raw_val} → {normalized}")
                        cur["confidence"] = normalized

                if low.startswith("reason:") or low.startswith("why:"):
                    cur["reason"] = line.split(":", 1)[1].strip()
                    continue

                # Fallback: if rating isn't labeled, grab the first BUY/SELL/HOLD/WATCH word.
                if not cur.get("rating"):
                    m = _RATING_RE.search(line)
                    if m:
                        raw_val = m.group(1)
                        normalized = _normalize_rating(raw_val)
                        if normalized:
                            print(f"[parser] Normalized rating: {raw_val} → {normalized}")
                            cur["rating"] = normalized

                # Fallback: if we don't have a reason yet, take the first free-form sentence.
                if not cur.get("reason"):
                    cur["reason"] = line

        flush()

        print(f"[parser] Parsed {len(recs)} recommendations")
        for r in recs:
            print(f"[parser] Recommendation: {r.get('ticker')} — {r.get('rating')} ({r.get('confidence')})")

        return recs
    except Exception as exc:
        print(f"[parser] WARNING: parsing failed — {exc}")
        return []
