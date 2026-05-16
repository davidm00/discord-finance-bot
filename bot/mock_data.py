"""Mock data for testing — single source of truth for all fake data."""

from __future__ import annotations

MOCK_MARKET_DATA = {
    "equities": {
        "SPY": {"price": 748.17, "prev_close": 739.17, "pct_change": 1.22, "volume": 45000000},
        "QQQ": {"price": 719.79, "prev_close": 708.93, "pct_change": 1.53, "volume": 33000000},
        "DIA": {"price": 500.80, "prev_close": 495.37, "pct_change": 1.10, "volume": 12000000},
        "^VIX": {"price": 17.26, "prev_close": 18.43, "pct_change": -6.34, "volume": 0},
    },
    "fetched_at_et": "2026-05-19 08:45 ET",
}

MOCK_CRYPTO_DATA = {
    "major": {
        "BTC": {"price": 80515.00, "pct_change_24h": 0.90, "volume": 44800000000, "market_cap": 1590000000000},
        "ETH": {"price": 2253.93, "pct_change_24h": -0.61, "volume": 17500000000, "market_cap": 271000000000},
        "SOL": {"price": 90.87, "pct_change_24h": -0.34, "volume": 3200000000, "market_cap": 39000000000},
    },
    "notable_movers": [
        {"symbol": "HYPE", "name": "Hyperliquid", "price": 45.89, "pct_change_24h": 18.13, "volume": 3220000000},
    ],
    "fetched_at_et": "2026-05-19 08:45 ET",
}

MOCK_NEWS_ITEMS = [
    {"headline": "China agrees to buy US crude oil following Trump-Xi summit", "source": "CNBC", "url": "https://cnbc.com/1", "published_et": "2026-05-19 07:30 ET"},
    {"headline": "Federal Reserve signals rate hold amid mixed inflation data", "source": "Bloomberg", "url": "https://bloomberg.com/1", "published_et": "2026-05-19 06:45 ET"},
    {"headline": "Nvidia earnings beat estimates, stock rises premarket", "source": "MarketWatch", "url": "https://marketwatch.com/1", "published_et": "2026-05-19 06:00 ET"},
    {"headline": "China agrees to buy US crude oil following Trump-Xi summit", "source": "Reuters", "url": "https://reuters.com/1", "published_et": "2026-05-19 07:32 ET"},
    {"headline": "Home Depot reports Q1 earnings Tuesday before open", "source": "CNBC", "url": "https://cnbc.com/2", "published_et": "2026-05-19 05:30 ET"},
    {"headline": "Iran war pushes diesel costs higher across supply chains", "source": "Bloomberg", "url": "https://bloomberg.com/2", "published_et": "2026-05-19 04:00 ET"},
]
# Note: headline index 0 and 3 are intentional duplicates to test dedup

MOCK_POLITICAL_DATA = {
    "trades": [
        {"politician": "Nancy Pelosi", "party": "D", "chamber": "House", "ticker": "NVDA", "company": "Nvidia Corp", "trade_type": "Buy", "trade_date": "2026-05-14", "published_date": "2026-05-16", "amount_range": "$250K-$500K"},
        {"politician": "Tommy Tuberville", "party": "R", "chamber": "Senate", "ticker": "LMT", "company": "Lockheed Martin", "trade_type": "Buy", "trade_date": "2026-05-12", "published_date": "2026-05-15", "amount_range": "$50K-$100K"},
    ],
    "contracts": [
        {"recipient": "Lockheed Martin Corporation", "amount": 2300000000, "date": "2026-05-15", "agency": "Department of Defense", "description": "F-35 aircraft maintenance and sustainment", "is_recurring": False},
        {"recipient": "Sandia National Laboratories", "amount": 42100000000, "date": "2026-05-01", "agency": "Department of Energy", "description": "Nuclear security laboratory management", "is_recurring": True},
    ],
    "correlations": [
        {"company": "Lockheed Martin", "ticker": "LMT", "contract_amount": "$2.3B", "contract_date": "2026-05-15", "contract_agency": "Dept of Defense", "politician": "Tommy Tuberville", "party": "R", "trade_type": "Buy", "trade_amount_range": "$50K-$100K", "trade_date": "2026-05-12", "days_apart": 3},
    ],
    "fetched_at_et": "2026-05-19 08:45 ET",
}

MOCK_EARNINGS = [
    {"symbol": "HD", "company": "Home Depot", "date": "2026-05-20", "time": "BMO", "eps_estimate": 3.51},
    {"symbol": "NVDA", "company": "Nvidia", "date": "2026-05-21", "time": "AMC", "eps_estimate": 0.89},
]

MOCK_MACRO_CONTEXT = {
    "treasury_10y": 4.59,
    "dollar_index": 99.27,
    "fear_greed_score": 38,
    "fear_greed_rating": "Fear",
}

MOCK_PREVIOUS_REPORTS = [
    {
        "report_type": "pre-market",
        "timestamp_et": "2026-05-16 08:45 ET",
        "analysis": "Markets opened cautiously with SPY at $748. Flagged XOM as WATCH due to Iran war tailwinds. BTC holding $80K level.",
        "fields": {
            "\U0001f1fa\U0001f1f8 Equities": "SPY: $748.17 (\u25b2 0.79%)\nQQQ: $719.79 (\u25b2 0.71%)",
            "\U0001f3af Tickers to Watch": "XOM \u2014 WATCH (MEDIUM)\nHD \u2014 WATCH (MEDIUM)",
        },
    }
]

# Broken data for error handling tests
MOCK_BROKEN_MARKET_DATA = {
    "equities": {
        "SPY": {"price": None, "prev_close": 739.17, "pct_change": None, "volume": 0},
        "QQQ": {"price": 719.79, "prev_close": 708.93, "pct_change": 1.53, "volume": 33000000},
    },
    "fetched_at_et": "2026-05-19 08:45 ET",
}

MOCK_BROKEN_POLITICAL_DATA = {
    "trades": [
        {"politician": "Jane Doe", "party": "D", "chamber": "House", "ticker": None, "company": "Unknown Corp", "trade_type": "Buy", "trade_date": None, "published_date": None, "amount_range": "$15K-$50K"},
    ],
    "contracts": [],
    "correlations": [],
    "fetched_at_et": "2026-05-19 08:45 ET",
}

MOCK_CLAUDE_RESPONSE = """\
**Pre-Market Briefing — Monday, May 19, 2026 | 8:45 AM ET**

**Equities**
Markets are pointing higher this morning with SPY up 1.2% and the fear
gauge (VIX) dropping 6% to 17.26 — investors are feeling more confident.

**Crypto**
BTC is holding above $80K with modest gains. HYPE is up 18% on
platform-specific momentum — treat with caution.

**Top Story**
China-US trade progress is the dominant theme. LMT is worth watching
given the $2.3B DoD contract and Tuberville's recent buy.

**Previous Report Check**
Last report flagged XOM as WATCH — energy stocks have continued moving
higher with Iran war tailwinds.

**What to Watch at 9:30 AM ET**
1. Watch SPY holding above $748 at the open.
2. Watch LMT given the DoD contract correlation with Tuberville trade.
3. Watch BTC holding $80K as a risk appetite signal.

**Tickers to Watch**

**LMT — Lockheed Martin**
Bull: $2.3B DoD contract + senator buy 3 days before announcement is a strong signal.
Bear: Defense stocks already priced in elevated spending; contract may already be in the price.
Rating: BUY
Reason: Contract-politician trade correlation within 3 days is the strongest signal type we track.
Confidence: HIGH

**XOM — ExxonMobil**
Bull: Iran war driving energy demand higher with direct tailwind for US exporters.
Bear: Any diplomatic resolution could instantly deflate the oil price premium.
Rating: WATCH
Reason: Geopolitical tailwind is real but binary — watch for resolution signals.
Confidence: MEDIUM

\u26a0\ufe0f Not financial advice. For informational purposes only. Always do your own research.
"""
