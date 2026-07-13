# TESTING PHILOSOPHY
# ==================
# Tier 1 — API Connectivity (TEST_LIVE=1):
#   Confirms external APIs are reachable and returning expected structure.
#   Run occasionally, not on every change.
#
# Tier 2 — Data Integrity (TEST_MOCK=1, Groups 1-2):
#   Confirms data structures are correct and feature logic works.
#   Run on every code change before committing.
#
# Tier 3 — Pipeline Flow (TEST_MOCK=1, Group 3):
#   Confirms all modules compose correctly end-to-end.
#   Run before every push to main.
#
# Agent instructions: Always run TEST_MOCK=1 before committing.
# If any test fails, fix the issue and re-run before pushing.
# Never commit with failing tests.

"""Test runner for Discord finance bot — mock and live test modes."""

from __future__ import annotations

import csv
import hashlib
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from typing import Any

# Ensure bot/ is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytz

ET_TZ = pytz.timezone("America/New_York")


def _load_env_local() -> None:
    """Load .env.local from repo root for local testing."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(repo_root, ".env.local")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        print("[test] Loaded .env.local")
    except Exception:
        pass


class TestRunner:
    """Tracks test results and prints summary."""

    def __init__(self, mode: str):
        self.mode = mode
        self.results: list[tuple[str, bool, str]] = []  # (name, passed, detail)

    def record(self, name: str, passed: bool, detail: str = ""):
        status = "PASS" if passed else "FAIL"
        detail_str = f" — {detail}" if detail and not passed else ""
        print(f"  {status}  {name}{detail_str}")
        self.results.append((name, passed, detail))

    def summary(self) -> int:
        total = len(self.results)
        passed = sum(1 for _, p, _ in self.results if p)
        failed = total - passed
        exit_code = 0 if failed == 0 else 1

        print("")
        print("=" * 50)
        print(f"TEST RESULTS — {self.mode} MODE")
        print("=" * 50)
        for name, p, detail in self.results:
            status = "PASS" if p else "FAIL"
            detail_str = f" — {detail}" if detail and not p else ""
            print(f"  {status}  {name}{detail_str}")
        print("-" * 50)
        print(f"Total: {total} tests | {passed} passed | {failed} failed")
        print(f"Exit code: {exit_code}")
        print("=" * 50)

        if failed > 0:
            print("\n\u26a0\ufe0f Fix failing tests before committing.")
        else:
            print("\n\u2705 All tests passed. Safe to commit.")

        return exit_code


# ============================================================
# MOCK MODE TESTS
# ============================================================

def run_mock_tests() -> int:
    """Run all mock-based tests."""
    runner = TestRunner("MOCK")
    print("\n[test] Running MOCK mode tests...\n")

    from mock_data import (
        MOCK_MARKET_DATA,
        MOCK_CRYPTO_DATA,
        MOCK_NEWS_ITEMS,
        MOCK_POLITICAL_DATA,
        MOCK_EARNINGS,
        MOCK_MACRO_CONTEXT,
        MOCK_PREVIOUS_REPORTS,
        MOCK_BROKEN_MARKET_DATA,
        MOCK_BROKEN_POLITICAL_DATA,
        MOCK_CLAUDE_RESPONSE,
    )

    # === Group 1: Data Structure Validation ===
    print("--- Group 1: Data Structure Validation ---")

    # test_market_data_structure
    try:
        data = MOCK_MARKET_DATA
        assert "equities" in data, "missing 'equities' key"
        assert "fetched_at_et" in data, "missing 'fetched_at_et' key"
        for ticker in ["SPY", "QQQ", "DIA", "^VIX"]:
            assert ticker in data["equities"], f"missing ticker {ticker}"
            t = data["equities"][ticker]
            assert "price" in t, f"{ticker} missing 'price'"
            assert "pct_change" in t, f"{ticker} missing 'pct_change'"
            assert isinstance(t["price"], (int, float, type(None))), f"{ticker} price wrong type"
        runner.record("test_market_data_structure", True)
    except Exception as e:
        runner.record("test_market_data_structure", False, str(e))

    # test_crypto_data_structure
    try:
        data = MOCK_CRYPTO_DATA
        assert "major" in data, "missing 'major' key"
        assert "notable_movers" in data, "missing 'notable_movers' key"
        assert isinstance(data["notable_movers"], list), "'notable_movers' not a list"
        assert "fetched_at_et" in data, "missing 'fetched_at_et' key"
        for coin in ["BTC", "ETH", "SOL"]:
            assert coin in data["major"], f"missing {coin}"
            c = data["major"][coin]
            assert "price" in c, f"{coin} missing 'price'"
            assert "pct_change_24h" in c, f"{coin} missing 'pct_change_24h'"
            assert "volume" in c, f"{coin} missing 'volume'"
        runner.record("test_crypto_data_structure", True)
    except Exception as e:
        runner.record("test_crypto_data_structure", False, str(e))

    # test_news_structure
    try:
        items = MOCK_NEWS_ITEMS
        assert isinstance(items, list) and len(items) > 0, "items empty or not list"
        for item in items:
            for key in ["headline", "source", "url", "published_et"]:
                assert key in item, f"missing key '{key}'"
                assert isinstance(item[key], str), f"'{key}' not a string"
        runner.record("test_news_structure", True)
    except Exception as e:
        runner.record("test_news_structure", False, str(e))

    # test_political_data_structure
    try:
        data = MOCK_POLITICAL_DATA
        for key in ["trades", "contracts", "correlations", "fetched_at_et"]:
            assert key in data, f"missing key '{key}'"
        for trade in data["trades"]:
            for k in ["politician", "ticker", "trade_type", "published_date", "amount_range"]:
                assert k in trade, f"trade missing '{k}'"
        for contract in data["contracts"]:
            for k in ["recipient", "amount", "agency", "is_recurring"]:
                assert k in contract, f"contract missing '{k}'"
        for corr in data["correlations"]:
            for k in ["company", "ticker", "days_apart"]:
                assert k in corr, f"correlation missing '{k}'"
        runner.record("test_political_data_structure", True)
    except Exception as e:
        runner.record("test_political_data_structure", False, str(e))

    # test_macro_context_structure
    try:
        data = MOCK_MACRO_CONTEXT
        for key in ["treasury_10y", "dollar_index", "fear_greed_score", "fear_greed_rating"]:
            assert key in data, f"missing key '{key}'"
        assert isinstance(data["treasury_10y"], float) and 0 <= data["treasury_10y"] <= 20, \
            f"treasury_10y out of range: {data['treasury_10y']}"
        assert isinstance(data["dollar_index"], float) and 50 <= data["dollar_index"] <= 200, \
            f"dollar_index out of range: {data['dollar_index']}"
        assert isinstance(data["fear_greed_score"], int) and 0 <= data["fear_greed_score"] <= 100, \
            f"fear_greed_score out of range: {data['fear_greed_score']}"
        runner.record("test_macro_context_structure", True)
    except Exception as e:
        runner.record("test_macro_context_structure", False, str(e))

    # === Group 2: Feature Logic Validation ===
    print("\n--- Group 2: Feature Logic Validation ---")

    # test_news_deduplication
    try:
        # Replicate the dedup logic from news_fetcher.py inline
        items = []
        for item in MOCK_NEWS_ITEMS:
            items.append(dict(item))  # shallow copy

        total_before = len(items)

        seen_hashes: dict[str, dict[str, Any]] = {}
        deduped_items: list[dict[str, Any]] = []
        for it in items:
            headline_text = str(it.get("headline") or "").lower().strip()
            normalized = re.sub(r'[^a-z0-9 ]', '', headline_text)
            key = hashlib.sha256(normalized.encode()).hexdigest()[:16]

            if key in seen_hashes:
                existing = seen_hashes[key]
                existing_et = existing.get("published_et", "9999")
                current_et = it.get("published_et", "9999")
                if current_et < existing_et:
                    deduped_items = [x for x in deduped_items if x is not existing]
                    deduped_items.append(it)
                    seen_hashes[key] = it
            else:
                seen_hashes[key] = it
                deduped_items.append(it)

        total_after = len(deduped_items)
        duplicates_removed = total_before - total_after

        assert total_after < total_before, f"expected fewer items after dedup: {total_after} >= {total_before}"
        assert duplicates_removed == 1, f"expected 1 duplicate removed, got {duplicates_removed}"

        # Check the kept headline is the earlier one (CNBC at 07:30, not Reuters at 07:32)
        kept_china = [x for x in deduped_items if "china agrees" in x.get("headline", "").lower()]
        assert len(kept_china) == 1, f"expected 1 China headline, got {len(kept_china)}"
        assert kept_china[0]["source"] == "CNBC", f"expected CNBC kept (earlier), got {kept_china[0]['source']}"

        runner.record("test_news_deduplication", True)
    except Exception as e:
        runner.record("test_news_deduplication", False, str(e))

    # test_signal_logging
    try:
        import signal_logger

        test_csv = os.path.join(tempfile.gettempdir(), "test_signals.csv")
        test_errors_csv = os.path.join(tempfile.gettempdir(), "test_signal_errors.csv")
        for p in (test_csv, test_errors_csv):
            if os.path.exists(p):
                os.remove(p)

        # Monkeypatch CSV_PATH
        original_path = signal_logger.CSV_PATH
        original_errors_path = signal_logger.ERRORS_PATH
        signal_logger.CSV_PATH = test_csv
        signal_logger.ERRORS_PATH = test_errors_csv

        try:
            signal_logger.log_signal("TEST", "BUY", "HIGH", 100.00, "pre-market", "test reason for buy")

            assert os.path.isfile(test_csv), "CSV file not created"

            with open(test_csv, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)

            assert len(rows) >= 2, f"expected header + 1 row, got {len(rows)} rows"
            header = rows[0]
            assert "ticker" in header, "header missing 'ticker'"
            assert "action" in header, "header missing 'action'"

            data_row = rows[1]
            ticker_idx = header.index("ticker")
            action_idx = header.index("action")
            confidence_idx = header.index("confidence")
            price_idx = header.index("price_at_signal")

            assert data_row[ticker_idx] == "TEST", f"ticker mismatch: {data_row[ticker_idx]}"
            assert data_row[action_idx] == "BUY", f"action mismatch: {data_row[action_idx]}"
            assert data_row[confidence_idx] == "HIGH", f"confidence mismatch: {data_row[confidence_idx]}"
            assert data_row[price_idx] == "100.00", f"price mismatch: {data_row[price_idx]}"

            signal_logger.log_signal("BAD", "GENERAL DYNAMICS", "MEDIUM", 100.00, "weekly", "bad parser row")
            with open(test_csv, "r", encoding="utf-8") as f:
                rows_after_invalid = list(csv.reader(f))
            assert len(rows_after_invalid) == len(rows), "invalid action should not be appended"
            assert os.path.isfile(test_errors_csv), "signal_errors.csv should be created for invalid action"
            with open(test_errors_csv, "r", encoding="utf-8") as f:
                error_rows = list(csv.DictReader(f))
            assert len(error_rows) == 1, f"expected 1 error row, got {len(error_rows)}"
            assert error_rows[0]["ticker"] == "BAD", f"error ticker mismatch: {error_rows[0]}"
            assert error_rows[0]["action"] == "GENERAL DYNAMICS", f"error action mismatch: {error_rows[0]}"
            assert error_rows[0]["error"] == "invalid action", f"error reason mismatch: {error_rows[0]}"

            captured_symbols = []
            original_ticker = signal_logger.yf.Ticker

            class FakeClose:
                @property
                def iloc(self):
                    return self

                def __getitem__(self, idx):
                    assert idx == -1
                    return 1805.25

            class FakeHistory:
                empty = False

                def __getitem__(self, key):
                    assert key == "Close"
                    return FakeClose()

            class FakeTicker:
                def __init__(self, symbol):
                    captured_symbols.append(symbol)

                def history(self, period):
                    assert period == "2d"
                    return FakeHistory()

            signal_logger.yf.Ticker = FakeTicker
            try:
                eth_price = signal_logger.fetch_price_for_ticker("ETH")
            finally:
                signal_logger.yf.Ticker = original_ticker

            assert captured_symbols == ["ETH-USD"], f"expected ETH-USD mapping, got {captured_symbols}"
            assert eth_price == 1805.25, f"expected mapped ETH price, got {eth_price}"

            runner.record("test_signal_logging", True)
        finally:
            signal_logger.CSV_PATH = original_path
            signal_logger.ERRORS_PATH = original_errors_path
            for p in (test_csv, test_errors_csv):
                if os.path.exists(p):
                    os.remove(p)
    except Exception as e:
        runner.record("test_signal_logging", False, str(e))

    # test_recommendation_parser
    try:
        import recommendation_parser

        # Daily format
        daily_response = """
**Tickers to Watch**

**XOM — ExxonMobil**
Rating: BUY
Reason: Iran war driving energy demand higher with 4.59% Treasury yield.
Confidence: HIGH

**HD — Home Depot**
Rating: WATCH
Reason: Earnings Tuesday with margin pressure from rising costs.
Confidence: MEDIUM
"""
        results = recommendation_parser.parse_recommendations(daily_response)
        assert len(results) == 2, f"daily: expected 2 recs, got {len(results)}"
        assert results[0]["ticker"] == "XOM", f"daily: expected XOM, got {results[0]['ticker']}"
        assert results[0]["rating"] == "BUY", f"daily: expected BUY, got {results[0]['rating']}"
        assert results[0]["confidence"] == "HIGH", f"daily: expected HIGH, got {results[0]['confidence']}"
        assert len(results[0]["reason"]) > 10, "daily: reason too short"

        # Weekly format
        weekly_response = """
**Tickers to Watch Next Week**

**DAL (Delta Air Lines)** \u2014 WATCH
Berkshire just put $2.6 billion behind this stock.
Confidence: Medium

**QQQ (Nasdaq-100 ETF)** \u2014 HOLD
Tech finished the week in the red.
Confidence: Medium-High
"""
        results = recommendation_parser.parse_recommendations(weekly_response)
        assert len(results) == 2, f"weekly: expected 2 recs, got {len(results)}"
        assert results[0]["ticker"] == "DAL", f"weekly: expected DAL, got {results[0]['ticker']}"
        assert results[0]["rating"] == "WATCH", f"weekly: expected WATCH, got {results[0]['rating']}"
        assert results[1]["confidence"] == "HIGH", f"weekly: Medium-High should normalize to HIGH, got {results[1]['confidence']}"
        assert len(results[0]["reason"]) > 10, "weekly: reason too short"

        # Regression: do not treat company names as ratings/actions.
        malformed_weekly_response = """
**Tickers to Watch Next Week**

**GD — General Dynamics**
WATCH
Defense contract momentum is real, but wait for confirmation.
Confidence: Medium

**XOM — ExxonMobil**
Rating: SELL
Reason: Crude risk premium is fading into the 5-day horizon.
Confidence: HIGH
"""
        results = recommendation_parser.parse_recommendations(malformed_weekly_response)
        assert len(results) == 2, f"malformed weekly: expected 2 recs, got {len(results)}"
        assert results[0]["ticker"] == "GD", f"malformed weekly: expected GD, got {results[0]['ticker']}"
        assert results[0]["rating"] == "WATCH", f"malformed weekly: expected WATCH, got {results[0]['rating']}"
        assert not results[0]["reason"].startswith("General Dynamics"), f"company name leaked into reason: {results[0]['reason']}"
        assert results[1]["rating"] == "SELL", f"malformed weekly: expected SELL, got {results[1]['rating']}"

        runner.record("test_recommendation_parser", True)
    except Exception as e:
        runner.record("test_recommendation_parser", False, str(e))

    # test_contracts_labeling
    try:
        contracts = MOCK_POLITICAL_DATA["contracts"]
        assert contracts[0]["is_recurring"] is False, f"Lockheed should be False, got {contracts[0]['is_recurring']}"
        assert contracts[1]["is_recurring"] is True, f"Sandia should be True, got {contracts[1]['is_recurring']}"
        runner.record("test_contracts_labeling", True)
    except Exception as e:
        runner.record("test_contracts_labeling", False, str(e))

    # test_broken_data_handling
    try:
        # Test that embed building doesn't crash with broken market data
        equities = MOCK_BROKEN_MARKET_DATA.get("equities", {})
        eq_lines = []
        for ticker in ["SPY", "QQQ", "DIA", "^VIX"]:
            t = equities.get(ticker) or {}
            price = t.get("price")
            pct = t.get("pct_change")
            if price is not None:
                line = f"{ticker}: ${price:.2f}"
            else:
                line = f"{ticker}: Data unavailable"
            if pct is not None:
                line += f" ({pct:+.2f}%)"
            eq_lines.append(line)
        eq_str = "\n".join(eq_lines)
        assert isinstance(eq_str, str) and len(eq_str) > 0, "embed string empty"

        # Test political with broken data
        trades = MOCK_BROKEN_POLITICAL_DATA.get("trades", [])
        trade_lines = []
        for t in trades:
            politician = t.get("politician", "Unknown")
            ticker = t.get("ticker") or "N/A"
            trade_type = str(t.get("trade_type", "?")).upper()
            trade_lines.append(f"{politician}: {trade_type} ${ticker}")
        pol_str = "\n".join(trade_lines)
        assert isinstance(pol_str, str), "political string not a string"

        runner.record("test_broken_data_handling", True)
    except Exception as e:
        runner.record("test_broken_data_handling", False, str(e))

    # test_market_calendar
    try:
        from market_calendar import get_market_state
        result = get_market_state()
        assert isinstance(result, dict), f"expected dict, got {type(result)}"
        assert "state" in result, "missing 'state' key"
        assert result["state"] in ["open", "pre_market", "post_market", "closed", "holiday", "unknown"], \
            f"unexpected state: {result['state']}"
        assert "label" in result, "missing 'label' key"
        assert isinstance(result["label"], str) and len(result["label"]) > 0, "label empty"
        assert "is_trading_day" in result, "missing 'is_trading_day' key"
        assert isinstance(result["is_trading_day"], bool), "is_trading_day not bool"
        runner.record("test_market_calendar", True, f"state={result['state']}")
    except Exception as e:
        runner.record("test_market_calendar", False, str(e))

    # test_source_weighting
    try:
        from news_fetcher import get_source_weight
        assert get_source_weight("Reuters") == 1.0, f"Reuters: {get_source_weight('Reuters')}"
        assert get_source_weight("Bloomberg") == 0.9, f"Bloomberg: {get_source_weight('Bloomberg')}"
        assert get_source_weight("CNBC") == 0.8, f"CNBC: {get_source_weight('CNBC')}"
        assert get_source_weight("Unknown Source XYZ") == 0.4, f"Unknown: {get_source_weight('Unknown Source XYZ')}"
        assert get_source_weight("Google News RSS") == 0.3, f"Google: {get_source_weight('Google News RSS')}"
        runner.record("test_source_weighting", True)
    except Exception as e:
        runner.record("test_source_weighting", False, str(e))

    # test_event_classification
    try:
        from news_fetcher import classify_event
        assert classify_event("Fed raises interest rates amid inflation") == "macro", \
            f"got: {classify_event('Fed raises interest rates amid inflation')}"
        assert classify_event("Apple acquires startup for $2B") == "merger_acquisition", \
            f"got: {classify_event('Apple acquires startup for $2B')}"
        assert classify_event("Nike earnings beat estimates") == "earnings", \
            f"got: {classify_event('Nike earnings beat estimates')}"
        assert classify_event("Iran war pushes oil prices higher") == "geopolitical", \
            f"got: {classify_event('Iran war pushes oil prices higher')}"
        assert classify_event("CEO resigns after board pressure") == "executive", \
            f"got: {classify_event('CEO resigns after board pressure')}"
        assert classify_event("Bitcoin hits new high") == "crypto", \
            f"got: {classify_event('Bitcoin hits new high')}"
        assert classify_event("Random news story") == "general", \
            f"got: {classify_event('Random news story')}"
        runner.record("test_event_classification", True)
    except Exception as e:
        runner.record("test_event_classification", False, str(e))

    # test_bull_bear_parser
    try:
        import recommendation_parser

        response = """
**Tickers to Watch**

**XOM — ExxonMobil**
Bull: Iran war driving energy demand higher with direct tailwind for US exporters.
Bear: Any diplomatic resolution could instantly deflate the oil price premium.
Rating: WATCH
Reason: Geopolitical tailwind is real but binary — watch for resolution signals.
Confidence: MEDIUM

**LMT — Lockheed Martin**
Bull: $2.3B DoD contract + senator buy 3 days before announcement is a strong signal.
Bear: Defense stocks already priced in elevated spending; contract may already be in the price.
Rating: BUY
Reason: Contract-politician trade correlation within 3 days is the strongest signal type we track.
Confidence: HIGH
"""
        results = recommendation_parser.parse_recommendations(response)
        assert len(results) == 2, f"expected 2 recs, got {len(results)}"
        assert results[0]["ticker"] == "XOM", f"expected XOM, got {results[0]['ticker']}"
        assert results[0]["bull_case"] is not None, "XOM bull_case is None"
        assert results[0]["bear_case"] is not None, "XOM bear_case is None"
        assert len(results[0]["bull_case"]) > 10, f"bull_case too short: {results[0]['bull_case']}"
        assert len(results[0]["bear_case"]) > 10, f"bear_case too short: {results[0]['bear_case']}"
        assert results[1]["rating"] == "BUY", f"expected BUY, got {results[1]['rating']}"
        assert results[1]["confidence"] == "HIGH", f"expected HIGH, got {results[1]['confidence']}"
        assert results[1]["bull_case"] is not None, "LMT bull_case is None"
        assert results[1]["bear_case"] is not None, "LMT bear_case is None"
        runner.record("test_bull_bear_parser", True)
    except Exception as e:
        runner.record("test_bull_bear_parser", False, str(e))

    # === Group 3: End-to-End Pipeline (Mock) ===
    print("\n--- Group 3: End-to-End Pipeline (Mock) ---")

    # test_e2e_mock_pipeline
    try:
        import signal_logger
        import recommendation_parser

        # Set up temp CSV for signal logging
        test_csv = os.path.join(tempfile.gettempdir(), "test_e2e_signals.csv")
        if os.path.exists(test_csv):
            os.remove(test_csv)
        original_csv_path = signal_logger.CSV_PATH
        signal_logger.CSV_PATH = test_csv

        try:
            # Use mock Claude response
            analysis = MOCK_CLAUDE_RESPONSE

            # Parse recommendations
            recs = recommendation_parser.parse_recommendations(analysis)

            # Log signals (without fetching real prices — monkeypatch fetch_price)
            original_fetch = signal_logger.fetch_price_for_ticker
            signal_logger.fetch_price_for_ticker = lambda ticker: {"LMT": 465.32, "XOM": 159.44}.get(ticker, 100.0)

            try:
                if recs:
                    signal_logger.log_recommendations(recs, "pre-market")
            finally:
                signal_logger.fetch_price_for_ticker = original_fetch

            # Build embed using all mock data
            market_data = MOCK_MARKET_DATA
            crypto_data = MOCK_CRYPTO_DATA
            political_data = MOCK_POLITICAL_DATA
            headlines = MOCK_NEWS_ITEMS[:5]
            earnings = MOCK_EARNINGS
            now_et = datetime.now(ET_TZ)
            date_et = now_et.strftime("%Y-%m-%d")

            equities = market_data.get("equities", {})
            eq_lines = []
            for t_name in ["SPY", "QQQ", "DIA", "^VIX"]:
                t = equities.get(t_name) or {}
                price = t.get("price")
                pct = t.get("pct_change")
                label = t_name.replace("^", "")
                if price is not None:
                    arrow = "\u25b2" if (pct or 0) >= 0 else "\u25bc"
                    eq_lines.append(f"{label}: ${price:,.2f} ({arrow} {abs(pct or 0):.2f}%)")
                else:
                    eq_lines.append(f"{label}: Data unavailable")

            major = crypto_data.get("major", {})
            cr_lines = []
            for coin in ["BTC", "ETH", "SOL"]:
                c = major.get(coin) or {}
                price = c.get("price")
                pct = c.get("pct_change_24h")
                if price is not None:
                    arrow = "\u25b2" if (pct or 0) >= 0 else "\u25bc"
                    cr_lines.append(f"{coin}: ${price:,.2f} ({arrow} {abs(pct or 0):.2f}%)")

            movers = crypto_data.get("notable_movers", [])
            if movers:
                movers_str = ", ".join(f"{m['symbol']} \u25b2{m['pct_change_24h']:.2f}%" for m in movers)
                cr_lines.append(f"\U0001f4e2 Movers: {movers_str}")

            trades = political_data.get("trades", [])
            trade_lines = [
                f"{t['politician']} ({t['party']}): {t['trade_type'].upper()} ${t['ticker']} | {t['amount_range']} | published: {t['published_date']}"
                for t in trades[:5]
            ]
            trades_value = "\n".join(trade_lines) if trade_lines else "No recent trades above $25K."

            contracts = political_data.get("contracts", [])
            contract_lines = []
            for c in contracts[:3]:
                prefix = "\U0001f501" if c.get("is_recurring") else "\U0001f195"
                contract_lines.append(f"{prefix} {c['recipient']}: ${c['amount']:,.0f} | {c['agency']}")
            contracts_value = "\n".join(contract_lines)

            hl_lines = [f"[{h['headline']}]({h['url']}) \u2014 {h['source']}" for h in headlines[:5]]
            headlines_value = "\n".join(hl_lines)

            e_lines = [f"{e['symbol']}: {e['date']} ({e['time']}) | EPS est: {e['eps_estimate']}" for e in earnings]
            earnings_value = "\n".join(e_lines)

            if recs:
                rec_parts = []
                for r in recs[:5]:
                    rec_parts.append(f"{r['ticker']} \u2014 {r['rating']} ({r['confidence']})")
                    rec_parts.append(r.get("reason", ""))
                    rec_parts.append("")
                rec_parts.append("\u26a0\ufe0f Not financial advice. For informational purposes only.")
                rec_value = "\n".join(rec_parts).strip()
            else:
                rec_value = "No strong signals identified today."

            embed = {
                "title": f"\U0001f4c8 Pre-Market Briefing \u2014 {date_et} ET",
                "color": 3066993,
                "description": analysis[:4096],
                "fields": [
                    {"name": "\U0001f1fa\U0001f1f8 Equities", "value": "\n".join(eq_lines), "inline": True},
                    {"name": "\u20bf Crypto", "value": "\n".join(cr_lines), "inline": True},
                    {"name": "\U0001f3db\ufe0f Political Trades", "value": trades_value, "inline": False},
                    {"name": "\U0001f4cb Gov Contracts", "value": contracts_value, "inline": False},
                    {"name": "\U0001f4f0 Top Headlines", "value": headlines_value, "inline": False},
                    {"name": "\U0001f4c5 Upcoming Earnings", "value": earnings_value, "inline": False},
                    {"name": "\U0001f3af Tickers to Watch", "value": rec_value, "inline": False},
                ],
                "footer": {"text": f"Data fetched at {market_data['fetched_at_et']} | Personal use only"},
            }

            # Validate embed
            field_names = [f["name"] for f in embed["fields"]]
            expected_fields = [
                "\U0001f1fa\U0001f1f8 Equities", "\u20bf Crypto", "\U0001f3db\ufe0f Political Trades",
                "\U0001f4cb Gov Contracts", "\U0001f4f0 Top Headlines", "\U0001f4c5 Upcoming Earnings",
                "\U0001f3af Tickers to Watch",
            ]
            for ef in expected_fields:
                assert ef in field_names, f"missing embed field: {ef}"

            assert "Pre-Market Briefing" in embed["title"], "title missing 'Pre-Market Briefing'"
            assert len(embed["description"]) > 100, f"description too short: {len(embed['description'])} chars"

            # Total char count
            total_chars = len(embed.get("title", "")) + len(embed.get("description", ""))
            for f in embed["fields"]:
                total_chars += len(f.get("name", "")) + len(f.get("value", ""))
            total_chars += len(embed.get("footer", {}).get("text", ""))
            assert total_chars <= 6000, f"embed too large: {total_chars} chars > 6000"

            assert "\u26a0\ufe0f" in (embed.get("description", "") + rec_value), "disclaimer not found"

            # Verify signal logging
            assert os.path.isfile(test_csv), "signals CSV not created"
            with open(test_csv, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            # Header + at least 2 data rows (LMT, XOM)
            assert len(rows) >= 3, f"expected 3+ rows in CSV, got {len(rows)}"
            header = rows[0]
            ticker_idx = header.index("ticker")
            action_idx = header.index("action")
            tickers_logged = [rows[i][ticker_idx] for i in range(1, len(rows))]
            actions_logged = [rows[i][action_idx] for i in range(1, len(rows))]
            assert "LMT" in tickers_logged, f"LMT not in signals: {tickers_logged}"
            assert "XOM" in tickers_logged, f"XOM not in signals: {tickers_logged}"
            assert "BUY" in actions_logged, f"BUY not in actions: {actions_logged}"
            assert "WATCH" in actions_logged, f"WATCH not in actions: {actions_logged}"

            runner.record("test_e2e_mock_pipeline", True)
        finally:
            signal_logger.CSV_PATH = original_csv_path
            if os.path.exists(test_csv):
                os.remove(test_csv)
    except Exception as e:
        runner.record("test_e2e_mock_pipeline", False, str(e))

    # test_signal_outcome_tracking
    try:
        import signal_outcomes

        test_signals = os.path.join(tempfile.gettempdir(), "test_signal_outcomes_signals.csv")
        test_outcomes = os.path.join(tempfile.gettempdir(), "test_signal_outcomes.csv")
        for p in (test_signals, test_outcomes):
            if os.path.exists(p):
                os.remove(p)

        with open(test_signals, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "date_et", "time_et", "ticker", "action", "confidence",
                "price_at_signal", "report_type", "reasoning_summary",
            ])
            writer.writeheader()
            writer.writerow({
                "date_et": "2026-01-02",
                "time_et": "08:01",
                "ticker": "XOM",
                "action": "BUY",
                "confidence": "HIGH",
                "price_at_signal": "100.00",
                "report_type": "pre-market",
                "reasoning_summary": "test buy",
            })
            writer.writerow({
                "date_et": "2026-01-02",
                "time_et": "16:15",
                "ticker": "XOM",
                "action": "SELL",
                "confidence": "MEDIUM",
                "price_at_signal": "100.00",
                "report_type": "post-market",
                "reasoning_summary": "test sell",
            })
            writer.writerow({
                "date_et": "2026-01-03",
                "time_et": "08:01",
                "ticker": "XOM",
                "action": "BUY",
                "confidence": "MEDIUM",
                "price_at_signal": "101.00",
                "report_type": "pre-market",
                "reasoning_summary": "repeat buy",
            })
            writer.writerow({
                "date_et": "2026-01-02",
                "time_et": "08:01",
                "ticker": "BAD",
                "action": "GENERAL DYNAMICS",
                "confidence": "MEDIUM",
                "price_at_signal": "100.00",
                "report_type": "weekly",
                "reasoning_summary": "bad row",
            })

        original_history_points = signal_outcomes._history_points
        fake_points = [
            (datetime(2026, 1, 2).date(), 100.0),
            (datetime(2026, 1, 3).date(), 101.0),
            (datetime(2026, 1, 4).date(), 102.0),
            (datetime(2026, 1, 5).date(), 103.0),
            (datetime(2026, 1, 6).date(), 104.0),
            (datetime(2026, 1, 7).date(), 105.0),
            (datetime(2026, 1, 8).date(), 106.0),
            (datetime(2026, 1, 9).date(), 107.0),
            (datetime(2026, 1, 10).date(), 108.0),
            (datetime(2026, 1, 11).date(), 109.0),
            (datetime(2026, 1, 12).date(), 110.0),
        ]
        signal_outcomes._history_points = lambda ticker, period="6mo": fake_points

        try:
            count = signal_outcomes.update_signal_outcomes(test_signals, test_outcomes)
        finally:
            signal_outcomes._history_points = original_history_points

        assert count == 3, f"expected 3 outcome rows, got {count}"
        with open(test_outcomes, "r", newline="", encoding="utf-8") as f:
            outcome_rows = list(csv.DictReader(f))

        assert len(outcome_rows) == 3, f"expected 3 written rows, got {len(outcome_rows)}"
        buy = outcome_rows[0]
        sell = outcome_rows[1]
        repeat_buy = outcome_rows[2]
        assert buy["ticker"] == "XOM" and buy["action"] == "BUY", f"bad buy row: {buy}"
        assert buy["idea_key"] == "XOM:BUY", f"bad buy idea key: {buy}"
        assert buy["is_repeat_5d"] == "false", f"first BUY should not be repeat: {buy}"
        assert buy["return_5d_pct"] == "4.00", f"expected BUY 5d raw return 4.00, got {buy['return_5d_pct']}"
        assert buy["signal_return_5d_pct"] == "4.00", f"expected BUY signal return 4.00, got {buy['signal_return_5d_pct']}"
        assert sell["action"] == "SELL", f"bad sell row: {sell}"
        assert sell["idea_key"] == "XOM:SELL", f"bad sell idea key: {sell}"
        assert sell["is_repeat_5d"] == "false", f"SELL should not repeat BUY idea: {sell}"
        assert sell["return_5d_pct"] == "5.00", f"expected SELL raw return 5.00, got {sell['return_5d_pct']}"
        assert sell["signal_return_5d_pct"] == "-5.00", f"expected SELL directional return -5.00, got {sell['signal_return_5d_pct']}"
        assert repeat_buy["action"] == "BUY", f"bad repeat row: {repeat_buy}"
        assert repeat_buy["is_repeat_5d"] == "true", f"second XOM BUY should be repeat: {repeat_buy}"
        assert repeat_buy["repeat_of_signal_id"] == buy["signal_id"], f"repeat should point at first BUY: {repeat_buy}"

        for p in (test_signals, test_outcomes):
            if os.path.exists(p):
                os.remove(p)

        runner.record("test_signal_outcome_tracking", True)
    except Exception as e:
        runner.record("test_signal_outcome_tracking", False, str(e))

    # test_signal_scorecard_prompt_summary
    try:
        import signal_scorecard

        test_outcomes = os.path.join(tempfile.gettempdir(), "test_signal_scorecard.csv")
        today = datetime.now(ET_TZ).strftime("%Y-%m-%d")
        with open(test_outcomes, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "signal_id", "date_et", "time_et", "ticker", "action", "confidence",
                "price_at_signal", "report_type", "expected_direction", "actionable",
                "idea_key", "is_repeat_5d", "repeat_of_signal_id",
                "price_1d", "return_1d_pct", "signal_return_1d_pct",
                "price_5d", "return_5d_pct", "signal_return_5d_pct",
                "price_10d", "return_10d_pct", "signal_return_10d_pct",
                "spy_return_5d_pct", "qqq_return_5d_pct", "status", "updated_at_et",
            ])
            writer.writeheader()
            writer.writerow({
                "signal_id": "a", "date_et": today, "time_et": "08:01", "ticker": "XOM",
                "action": "SELL", "confidence": "HIGH", "price_at_signal": "100.00",
                "report_type": "pre-market", "expected_direction": "short", "actionable": "true",
                "idea_key": "XOM:SELL", "is_repeat_5d": "false", "repeat_of_signal_id": "",
                "price_1d": "99.00", "return_1d_pct": "-1.00", "signal_return_1d_pct": "1.00",
                "price_5d": "95.00", "return_5d_pct": "-5.00", "signal_return_5d_pct": "5.00",
                "price_10d": "94.00", "return_10d_pct": "-6.00", "signal_return_10d_pct": "6.00",
                "spy_return_5d_pct": "1.00", "qqq_return_5d_pct": "2.00", "status": "complete",
                "updated_at_et": today,
            })
            writer.writerow({
                "signal_id": "b", "date_et": today, "time_et": "16:15", "ticker": "LMT",
                "action": "BUY", "confidence": "MEDIUM", "price_at_signal": "100.00",
                "report_type": "post-market", "expected_direction": "long", "actionable": "true",
                "idea_key": "LMT:BUY", "is_repeat_5d": "false", "repeat_of_signal_id": "",
                "price_1d": "101.00", "return_1d_pct": "1.00", "signal_return_1d_pct": "1.00",
                "price_5d": "98.00", "return_5d_pct": "-2.00", "signal_return_5d_pct": "-2.00",
                "price_10d": "", "return_10d_pct": "", "signal_return_10d_pct": "",
                "spy_return_5d_pct": "1.00", "qqq_return_5d_pct": "2.00", "status": "partial",
                "updated_at_et": today,
            })
            writer.writerow({
                "signal_id": "c", "date_et": today, "time_et": "08:01", "ticker": "RTX",
                "action": "WATCH", "confidence": "MEDIUM", "price_at_signal": "100.00",
                "report_type": "pre-market", "expected_direction": "neutral", "actionable": "false",
                "idea_key": "", "is_repeat_5d": "false", "repeat_of_signal_id": "",
                "price_1d": "101.00", "return_1d_pct": "1.00", "signal_return_1d_pct": "",
                "price_5d": "102.00", "return_5d_pct": "2.00", "signal_return_5d_pct": "",
                "price_10d": "103.00", "return_10d_pct": "3.00", "signal_return_10d_pct": "",
                "spy_return_5d_pct": "1.00", "qqq_return_5d_pct": "2.00", "status": "complete",
                "updated_at_et": today,
            })

            writer.writerow({
                "signal_id": "d", "date_et": today, "time_et": "16:16", "ticker": "XOM",
                "action": "SELL", "confidence": "HIGH", "price_at_signal": "100.00",
                "report_type": "post-market", "expected_direction": "short", "actionable": "true",
                "idea_key": "XOM:SELL", "is_repeat_5d": "true", "repeat_of_signal_id": "a",
                "price_1d": "99.00", "return_1d_pct": "-1.00", "signal_return_1d_pct": "1.00",
                "price_5d": "94.00", "return_5d_pct": "-6.00", "signal_return_5d_pct": "6.00",
                "price_10d": "93.00", "return_10d_pct": "-7.00", "signal_return_10d_pct": "7.00",
                "spy_return_5d_pct": "1.00", "qqq_return_5d_pct": "2.00", "status": "complete",
                "updated_at_et": today,
            })

        scorecard = signal_scorecard.build_signal_scorecard(days=14, outcomes_path=test_outcomes)
        assert "SIGNAL SCORECARD" in scorecard, "missing scorecard header"
        assert "Unique actionable BUY/SELL ideas, 5D directional performance: n=2" in scorecard, scorecard
        assert "Raw actionable calls, including repeats: n=3" in scorecard, scorecard
        assert "repeats excluded from unique score: 1" in scorecard, scorecard
        assert "avg=+1.50%" in scorecard, scorecard
        assert "WATCH=1" in scorecard, scorecard
        assert "Recent measured unique BUY/SELL ideas" in scorecard, scorecard

        if os.path.exists(test_outcomes):
            os.remove(test_outcomes)

        runner.record("test_signal_scorecard_prompt_summary", True)
    except Exception as e:
        runner.record("test_signal_scorecard_prompt_summary", False, str(e))

    return runner.summary()


# ============================================================
# LIVE MODE TESTS
# ============================================================

def run_live_tests() -> int:
    """Run live API connectivity tests."""
    # Load .env.local for API keys
    _load_env_local()

    runner = TestRunner("LIVE")
    print("\n[test] Running LIVE mode tests (real API calls)...\n")

    # test_live_yfinance
    try:
        import yfinance as yf
        ticker = yf.Ticker("SPY")
        hist = ticker.history(period="1d")
        assert hist is not None and not hist.empty, "SPY history empty"
        assert "Close" in hist.columns, "no 'Close' column"
        price = float(hist["Close"].iloc[-1])
        assert price > 0, f"SPY price not positive: {price}"
        runner.record("test_live_yfinance", True)
        print(f"    SPY price: ${price:.2f}")
    except Exception as e:
        runner.record("test_live_yfinance", False, str(e))

    # test_live_coingecko
    try:
        import requests
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "per_page": 3},
            timeout=15,
        )
        assert resp.status_code == 200, f"status {resp.status_code}"
        data = resp.json()
        assert isinstance(data, list) and len(data) == 3, f"expected 3 items, got {len(data) if isinstance(data, list) else type(data)}"
        assert "current_price" in data[0], "missing 'current_price'"
        btc_price = data[0]["current_price"]
        runner.record("test_live_coingecko", True)
        print(f"    BTC price: ${btc_price:,.2f}")
    except Exception as e:
        runner.record("test_live_coingecko", False, str(e))

    # test_live_finnhub_news
    try:
        import requests
        api_key = os.getenv("FINNHUB_API_KEY", "")
        if not api_key:
            runner.record("test_live_finnhub_news", False, "FINNHUB_API_KEY not set")
        else:
            resp = requests.get(
                "https://finnhub.io/api/v1/news",
                params={"category": "general", "token": api_key},
                timeout=15,
            )
            assert resp.status_code == 200, f"status {resp.status_code}"
            data = resp.json()
            assert isinstance(data, list) and len(data) > 0, "empty response"
            assert "headline" in data[0], "missing 'headline'"
            runner.record("test_live_finnhub_news", True)
            print(f"    Headlines: {len(data)}")
    except Exception as e:
        runner.record("test_live_finnhub_news", False, str(e))

    # test_live_usaspending
    try:
        import requests
        resp = requests.post(
            "https://api.usaspending.gov/api/v2/search/spending_by_award/",
            json={
                "filters": {
                    "time_period": [{"start_date": "2026-01-01", "end_date": "2026-05-19"}],
                    "award_type_codes": ["A", "B", "C", "D"],
                },
                "fields": ["Award ID", "Recipient Name", "Award Amount"],
                "limit": 1,
            },
            timeout=15,
        )
        assert resp.status_code == 200, f"status {resp.status_code}"
        data = resp.json()
        assert "results" in data, "missing 'results' key"
        runner.record("test_live_usaspending", True)
    except Exception as e:
        runner.record("test_live_usaspending", False, str(e))

    # test_live_capitol_trades
    try:
        import requests
        resp = requests.get(
            "https://www.capitoltrades.com/trades?pageSize=5&sortBy=-txDate",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        assert resp.status_code == 200, f"status {resp.status_code}"
        text = resp.text.lower()
        assert "politician" in text or "traded" in text or "trade" in text, "page content doesn't look like Capitol Trades"
        runner.record("test_live_capitol_trades", True)
        print(f"    Status: {resp.status_code}, content length: {len(resp.text)}")
    except Exception as e:
        runner.record("test_live_capitol_trades", False, str(e))

    # test_live_fear_greed
    try:
        import requests
        score = None
        source_name = None

        # Endpoint 1: CNN
        try:
            resp = requests.get(
                "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                fg = data.get("fear_and_greed") or {}
                s = fg.get("score")
                if s is not None:
                    score = int(round(float(s)))
                    source_name = "CNN"
        except Exception:
            pass

        # Endpoint 2: Alternative.me
        if score is None:
            try:
                resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data") or []
                    if items:
                        score = int(items[0].get("value", 0))
                        source_name = "Alternative.me"
            except Exception:
                pass

        assert score is not None, "all Fear & Greed endpoints failed"
        assert 0 <= score <= 100, f"score out of range: {score}"
        runner.record("test_live_fear_greed", True)
        print(f"    Score: {score} (source: {source_name})")
    except Exception as e:
        runner.record("test_live_fear_greed", False, str(e))

    # test_live_macro_context
    try:
        from market_data import fetch_macro_context
        result = fetch_macro_context()
        assert isinstance(result, dict), f"expected dict, got {type(result)}"
        assert result.get("treasury_10y") is not None and result["treasury_10y"] > 0, \
            f"treasury_10y invalid: {result.get('treasury_10y')}"
        assert result.get("dollar_index") is not None and result["dollar_index"] > 0, \
            f"dollar_index invalid: {result.get('dollar_index')}"
        runner.record("test_live_macro_context", True)
        print(f"    TNX: {result['treasury_10y']}% | DXY: {result['dollar_index']} | F&G: {result.get('fear_greed_score')}")
    except Exception as e:
        runner.record("test_live_macro_context", False, str(e))

    return runner.summary()


# ============================================================
# MAIN
# ============================================================

def main():
    # Ensure UTF-8 output on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    test_mock = os.getenv("TEST_MOCK", "").strip().lower() in {"1", "true", "yes"}
    test_live = os.getenv("TEST_LIVE", "").strip().lower() in {"1", "true", "yes"}

    if not test_mock and not test_live:
        print("Discord Finance Bot — Test Runner")
        print("=" * 40)
        print("")
        print("Usage:")
        print("  $env:TEST_MOCK='1'; python bot\\test_runner.py   # Offline mock tests")
        print("  $env:TEST_LIVE='1'; python bot\\test_runner.py   # Live API connectivity")
        print("")
        print("Set TEST_MOCK=1 for data integrity + pipeline tests (no API calls).")
        print("Set TEST_LIVE=1 for API connectivity tests (minimal real calls).")
        sys.exit(0)

    exit_code = 0

    if test_mock:
        exit_code = run_mock_tests()

    if test_live:
        code = run_live_tests()
        if code != 0:
            exit_code = code

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
