from __future__ import annotations

import sys


RATINGS = {"BUY", "SELL", "HOLD", "WATCH"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}


def parse_recommendations(text: str):
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
            line = raw.strip()
            if not line:
                continue

            # New record if line starts with a likely ticker pattern: "TICKER — ..." or "TICKER - ..."
            sep = "—" if "—" in line else ("-" if "-" in line else None)
            if sep:
                left = line.split(sep, 1)[0].strip()
                if left.isalpha() and left.isupper() and 1 <= len(left) <= 6:
                    flush()
                    cur = {"ticker": left, "rating": "", "reason": "", "confidence": ""}
                    continue

            if cur is None:
                continue

            if line.lower().startswith("rating:"):
                val = line.split(":", 1)[1].strip().upper()
                cur["rating"] = val if val in RATINGS else val
                continue

            if line.lower().startswith("confidence:"):
                val = line.split(":", 1)[1].strip().upper()
                cur["confidence"] = val if val in CONFIDENCE else val
                continue

            if line.lower().startswith("reason:") or line.lower().startswith("why:"):
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
