from __future__ import annotations

import os
import sys


RATINGS = {"BUY", "SELL", "HOLD", "WATCH"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}


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

        for raw in buf:
            # Claude sometimes concatenates blocks like: "Confidence: MEDIUM---**NVDA — Nvidia**"
            # Split on common separators to keep parsing simple and robust.
            chunks = [c.strip() for c in raw.split("---") if c.strip()]
            for chunk in chunks:
                line = chunk.strip()
                if not line:
                    continue

                # New record if line contains a likely ticker pattern: "**TICKER — ...**" or "TICKER — ..."
                if "—" in line or " - " in line:
                    sep = "—" if "—" in line else "-"
                    left = line.split(sep, 1)[0].strip()
                    left = left.replace("**", "").replace("*", "").lstrip("-").strip()

                    # Allow tickers like BRK.B
                    ticker = left
                    allowed = all(ch.isalnum() or ch in {".", "-"} for ch in ticker)
                    has_letter = any(ch.isalpha() for ch in ticker)
                    if allowed and has_letter and ticker.upper() == ticker and 1 <= len(ticker) <= 8:
                        flush()
                        cur = {"ticker": ticker, "rating": "", "reason": "", "confidence": ""}
                        continue

                if cur is None:
                    continue

                low = line.lower()

                if low.startswith("rating:"):
                    val = line.split(":", 1)[1].strip().upper()
                    cur["rating"] = val if val in RATINGS else val
                    continue

                if low.startswith("confidence:"):
                    val = line.split(":", 1)[1].strip().upper()
                    cur["confidence"] = val if val in CONFIDENCE else val
                    continue

                if low.startswith("reason:") or low.startswith("why:"):
                    cur["reason"] = line.split(":", 1)[1].strip()
                    continue

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
