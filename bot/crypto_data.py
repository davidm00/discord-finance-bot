from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import pytz
import requests


ET_TZ = pytz.timezone("America/New_York")

COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"


def fetch_crypto_data() -> dict[str, Any] | None:
    """Fetch enhanced crypto market data from CoinGecko (no API key).

    Returns:
    {
      "major": {
        "BTC": {"price": float, "pct_change_24h": float, "volume": float, "market_cap": float},
        "ETH": {...},
        "SOL": {...}
      },
      "notable_movers": [
        {"symbol": str, "name": str, "price": float, "pct_change_24h": float, "volume": float},
        ...
      ],
      "fetched_at_et": "YYYY-MM-DD HH:MM ET"
    }

    If the entire fetch fails, returns None.
    """

    fetched_at_et = datetime.now(ET_TZ).strftime("%Y-%m-%d %H:%M ET")

    print("Fetching enhanced crypto data via CoinGecko...", file=sys.stdout)

    try:
        resp = requests.get(
            COINGECKO_MARKETS,
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 20,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"WARNING: CoinGecko request failed: {exc}", file=sys.stderr)
        return None

    if not (200 <= resp.status_code < 300):
        print(f"WARNING: CoinGecko returned {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        return None

    try:
        data = resp.json()
    except Exception as exc:
        print(f"WARNING: CoinGecko JSON parse failed: {exc}", file=sys.stderr)
        return None

    if not isinstance(data, list) or not data:
        print("WARNING: CoinGecko returned empty results.", file=sys.stderr)
        return None

    majors_wanted = {"BTC", "ETH", "SOL"}

    major: dict[str, Any] = {}
    movers: list[dict[str, Any]] = []

    for coin in data:
        try:
            symbol = str(coin.get("symbol") or "").upper().strip()
            name = str(coin.get("name") or "").strip()

            price = coin.get("current_price")
            pct = coin.get("price_change_percentage_24h")
            vol = coin.get("total_volume")
            mcap = coin.get("market_cap")

            # Coerce to floats when possible.
            price_f = float(price) if price is not None else None
            pct_f = float(pct) if pct is not None else None
            vol_f = float(vol) if vol is not None else None
            mcap_f = float(mcap) if mcap is not None else None

            if symbol in majors_wanted:
                if price_f is None or pct_f is None:
                    continue
                major[symbol] = {
                    "price": price_f,
                    "pct_change_24h": pct_f,
                    "volume": float(vol_f) if vol_f is not None else 0.0,
                    "market_cap": float(mcap_f) if mcap_f is not None else 0.0,
                }
            else:
                if pct_f is None or price_f is None:
                    continue
                if abs(pct_f) >= 8.0:
                    movers.append(
                        {
                            "symbol": symbol,
                            "name": name,
                            "price": price_f,
                            "pct_change_24h": pct_f,
                            "volume": float(vol_f) if vol_f is not None else 0.0,
                        }
                    )
        except Exception:
            continue

    # Ensure majors exist if present; missing majors are fine (degrade gracefully).

    # Cap notable movers at 3, sorted by abs(24h change) desc.
    movers.sort(key=lambda x: abs(float(x.get("pct_change_24h") or 0.0)), reverse=True)
    movers = movers[:3]

    return {
        "major": major,
        "notable_movers": movers,
        "fetched_at_et": fetched_at_et,
    }
