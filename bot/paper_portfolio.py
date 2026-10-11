"""Deterministic, zero-cost paper portfolio driven by logged recommendations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

import exchange_calendars as xcals
import pytz
import yfinance as yf

from portfolio_policy import DEFAULT_POLICY, PortfolioPolicy


ET = pytz.timezone("America/New_York")
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIGNALS_PATH = REPO_ROOT / "data" / "signals.csv"
DEFAULT_STATE_DIR = REPO_ROOT / "data" / "paper_portfolio" / "forward"
DEFAULT_BACKTEST_DIR = REPO_ROOT / "data" / "paper_portfolio" / "backtest"
METADATA_FILE = "account.json"

ORDER_HEADERS = [
    "order_id",
    "signal_id",
    "submitted_at_et",
    "eligible_date",
    "ticker",
    "side",
    "action",
    "confidence",
    "report_type",
    "signal_price",
    "target_notional",
    "status",
    "filled_at_et",
    "fill_price",
    "shares",
    "reason",
    "policy_version",
]

LEDGER_HEADERS = [
    "event_id",
    "occurred_at_et",
    "event_type",
    "order_id",
    "signal_id",
    "ticker",
    "shares",
    "price",
    "cash_delta",
    "reason",
    "policy_version",
]

SNAPSHOT_HEADERS = [
    "date_et",
    "recorded_at_et",
    "cash",
    "market_value",
    "equity",
    "realized_pnl",
    "unrealized_pnl",
    "return_pct",
    "spy_return_pct",
    "positions_json",
    "policy_version",
]

DIAGNOSTIC_HEADERS = ["recorded_at_et", "stage", "severity", "message"]


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: float | None, places: int = 4) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.{places}f}"


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(str(value or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_signal_datetime(row: dict[str, str]) -> datetime | None:
    raw = f"{row.get('date_et', '').strip()} {row.get('time_et', '').strip()}".strip()
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return ET.localize(datetime.strptime(raw, pattern))
        except ValueError:
            continue
    return None


def signal_identity(row: dict[str, str]) -> str:
    """Match the identity fields used by signal_outcomes.py."""
    raw = "|".join(
        [
            row.get("date_et", "").strip(),
            row.get("time_et", "").strip(),
            row.get("ticker", "").strip().upper(),
            row.get("action", "").strip().upper(),
            row.get("confidence", "").strip().upper(),
            row.get("price_at_signal", "").strip(),
            row.get("report_type", "").strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _atomic_write_csv(path: Path, headers: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
    os.replace(temp, path)


@dataclass
class Position:
    ticker: str
    shares: float
    average_entry: float
    opened_at: str
    signal_id: str

    @property
    def cost_basis(self) -> float:
        return self.shares * self.average_entry


@dataclass
class AccountState:
    cash: float
    positions: dict[str, Position]
    realized_pnl: float


class PriceProvider:
    """Cached daily OHLC provider using the repository's existing free data source."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[date, dict[str, float]]] = {}

    def history(self, ticker: str) -> dict[date, dict[str, float]]:
        ticker = ticker.upper()
        if ticker in self._cache:
            return self._cache[ticker]

        history = yf.Ticker(ticker).history(period="2y", interval="1d", auto_adjust=False)
        rows: dict[date, dict[str, float]] = {}
        if history is not None and not history.empty:
            for index, row in history.iterrows():
                day = index.date() if hasattr(index, "date") else _parse_date(str(index))
                if day is None:
                    continue
                values = {
                    key.lower(): _safe_float(row.get(key))
                    for key in ("Open", "High", "Low", "Close")
                }
                if all(values.values()):
                    rows[day] = {key: float(value) for key, value in values.items() if value is not None}
        self._cache[ticker] = rows
        return rows

    def bar(self, ticker: str, day: date) -> dict[str, float] | None:
        return self.history(ticker).get(day)

    def latest_bar(self, ticker: str, as_of: date) -> tuple[date, dict[str, float]] | None:
        candidates = [(day, bar) for day, bar in self.history(ticker).items() if day <= as_of]
        return max(candidates, key=lambda item: item[0]) if candidates else None


class PaperPortfolio:
    def __init__(
        self,
        state_dir: Path = DEFAULT_STATE_DIR,
        policy: PortfolioPolicy = DEFAULT_POLICY,
        prices: PriceProvider | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.policy = policy
        self.prices = prices or PriceProvider()
        self.orders_path = self.state_dir / "orders.csv"
        self.ledger_path = self.state_dir / "ledger.csv"
        self.snapshots_path = self.state_dir / "snapshots.csv"
        self.diagnostics_path = self.state_dir / "diagnostics.csv"
        self.metadata_path = self.state_dir / METADATA_FILE
        self.calendar = xcals.get_calendar("XNYS")

    def initialize(self, inception_date: date) -> dict[str, Any]:
        if self.metadata_path.is_file():
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            if metadata.get("policy_version") != self.policy.version:
                raise ValueError(
                    f"Account policy {metadata.get('policy_version')!r} does not match "
                    f"runtime policy {self.policy.version!r}"
                )
            return metadata
        metadata = {
            "account_type": "forward" if self.state_dir == DEFAULT_STATE_DIR else "simulation",
            "inception_date": inception_date.isoformat(),
            "initial_capital": self.policy.initial_capital,
            "policy_version": self.policy.version,
            "created_at_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        }
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp = self.metadata_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, self.metadata_path)
        return metadata

    def _diagnose(self, stage: str, severity: str, message: str) -> None:
        rows = _read_csv(self.diagnostics_path)
        rows.append(
            {
                "recorded_at_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
                "stage": stage,
                "severity": severity,
                "message": str(message)[:500],
            }
        )
        _atomic_write_csv(self.diagnostics_path, DIAGNOSTIC_HEADERS, rows)
        print(f"[portfolio] {severity}: {stage}: {message}", file=sys.stderr if severity == "ERROR" else sys.stdout)

    def _next_session(self, day: date, include_current: bool) -> date:
        start = day if include_current else day + timedelta(days=1)
        sessions = self.calendar.sessions_in_range(start.isoformat(), (start + timedelta(days=14)).isoformat())
        if len(sessions) == 0:
            raise ValueError(f"No market session found after {day}")
        return sessions[0].date()

    def eligible_date(self, row: dict[str, str]) -> date:
        signal_dt = _parse_signal_datetime(row)
        if signal_dt is None:
            raise ValueError("invalid signal timestamp")
        report_type = row.get("report_type", "").strip().lower()
        pre_market = report_type == "pre-market" or (
            report_type not in {"post-market", "weekly"} and signal_dt.time() < time(9, 30)
        )
        return self._next_session(signal_dt.date(), include_current=pre_market)

    def reconstruct(self) -> AccountState:
        cash = self.policy.initial_capital
        realized = 0.0
        positions: dict[str, Position] = {}
        seen_events: set[str] = set()

        for event in _read_csv(self.ledger_path):
            event_id = event.get("event_id", "")
            if not event_id or event_id in seen_events:
                raise ValueError(f"duplicate or missing ledger event id: {event_id!r}")
            seen_events.add(event_id)
            cash_delta = _safe_float(event.get("cash_delta"))
            shares = _safe_float(event.get("shares"))
            price = _safe_float(event.get("price"))
            ticker = event.get("ticker", "").upper()
            event_type = event.get("event_type", "").upper()
            if cash_delta is None or shares is None or price is None or shares <= 0 or price <= 0:
                raise ValueError(f"invalid ledger event {event_id}")
            cash += cash_delta

            if event_type == "BUY":
                if ticker in positions:
                    raise ValueError(f"multiple open lots are not supported for {ticker}")
                positions[ticker] = Position(
                    ticker=ticker,
                    shares=shares,
                    average_entry=price,
                    opened_at=event.get("occurred_at_et", ""),
                    signal_id=event.get("signal_id", ""),
                )
            elif event_type in {"SELL", "STOP", "TIME_EXIT"}:
                position = positions.get(ticker)
                if position is None or abs(position.shares - shares) > 0.000001:
                    raise ValueError(f"closing event does not reconcile for {ticker}")
                realized += (price - position.average_entry) * shares
                del positions[ticker]
            else:
                raise ValueError(f"unknown ledger event type {event_type!r}")

        if cash < -0.01:
            raise ValueError(f"portfolio cash is negative: {cash:.2f}")
        return AccountState(cash=cash, positions=positions, realized_pnl=realized)

    def _mark_prices(self, state: AccountState, as_of: date) -> dict[str, float]:
        marked: dict[str, float] = {}
        for ticker in state.positions:
            latest = self.prices.latest_bar(ticker, as_of)
            if latest:
                marked[ticker] = latest[1]["close"]
        return marked

    def account_values(self, state: AccountState, as_of: date) -> tuple[float, float, float, dict[str, float]]:
        marks = self._mark_prices(state, as_of)
        market_value = sum(position.shares * marks.get(ticker, position.average_entry) for ticker, position in state.positions.items())
        unrealized = sum(
            position.shares * (marks.get(ticker, position.average_entry) - position.average_entry)
            for ticker, position in state.positions.items()
        )
        return market_value, state.cash + market_value, unrealized, marks

    def _append_order(
        self,
        orders: list[dict[str, str]],
        row: dict[str, str],
        side: str,
        status: str,
        reason: str,
        target_notional: float = 0.0,
    ) -> None:
        signal_id = signal_identity(row)
        order_id = _stable_id("ord", signal_id, side or "NONE", self.policy.version)
        signal_dt = _parse_signal_datetime(row)
        eligible = ""
        if side:
            eligible = self.eligible_date(row).isoformat()
        orders.append(
            {
                "order_id": order_id,
                "signal_id": signal_id,
                "submitted_at_et": signal_dt.strftime("%Y-%m-%d %H:%M ET") if signal_dt else "",
                "eligible_date": eligible,
                "ticker": row.get("ticker", "").strip().upper(),
                "side": side,
                "action": row.get("action", "").strip().upper(),
                "confidence": row.get("confidence", "").strip().upper(),
                "report_type": row.get("report_type", "").strip(),
                "signal_price": _fmt(_safe_float(row.get("price_at_signal")), 2),
                "target_notional": _fmt(target_notional, 2),
                "status": status,
                "filled_at_et": "",
                "fill_price": "",
                "shares": "",
                "reason": reason,
                "policy_version": self.policy.version,
            }
        )

    def ingest_signals(self, signal_rows: list[dict[str, str]], as_of: date) -> int:
        orders = _read_csv(self.orders_path)
        consumed = {row.get("signal_id", "") for row in orders}
        state = self.reconstruct()
        _, equity, _, marks = self.account_values(state, as_of)
        open_market_value = sum(
            position.shares * marks.get(ticker, position.average_entry)
            for ticker, position in state.positions.items()
        )
        pending_buy_notional = sum(
            _safe_float(order.get("target_notional")) or 0.0
            for order in orders
            if order.get("side") == "BUY" and order.get("status") == "pending"
        )
        open_market_value += pending_buy_notional
        available_cash = state.cash - pending_buy_notional
        added = 0

        for row in sorted(signal_rows, key=lambda item: (item.get("date_et", ""), item.get("time_et", ""))):
            signal_id = signal_identity(row)
            if signal_id in consumed:
                continue
            consumed.add(signal_id)
            added += 1
            ticker = row.get("ticker", "").strip().upper()
            action = row.get("action", "").strip().upper()
            confidence = row.get("confidence", "").strip().upper()
            signal_price = _safe_float(row.get("price_at_signal"))

            if action in {"WATCH", "HOLD"}:
                self._append_order(orders, row, "", "ignored", f"{action} does not transact")
                continue
            if action not in {"BUY", "SELL"}:
                self._append_order(orders, row, "", "rejected", "invalid action")
                continue
            if not ticker or ticker in self.policy.excluded_tickers:
                self._append_order(orders, row, "", "rejected", "asset excluded from v1")
                continue
            if confidence not in self.policy.eligible_confidence:
                self._append_order(orders, row, "", "rejected", "confidence below execution threshold")
                continue
            if signal_price is None or signal_price <= 0:
                self._append_order(orders, row, "", "rejected", "missing valid signal price")
                continue

            if action == "SELL":
                if ticker not in state.positions:
                    pending_buy = next(
                        (
                            order
                            for order in orders
                            if order.get("ticker") == ticker
                            and order.get("side") == "BUY"
                            and order.get("status") == "pending"
                        ),
                        None,
                    )
                    if pending_buy:
                        pending_buy["status"] = "cancelled"
                        pending_buy["reason"] = f"cancelled by later SELL signal {signal_id}"
                    self._append_order(orders, row, "", "ignored", "SELL has no held long position")
                else:
                    self._append_order(orders, row, "SELL", "pending", "exit held long")
                continue

            if ticker in state.positions or any(
                order.get("ticker") == ticker
                and order.get("side") == "BUY"
                and order.get("status") == "pending"
                for order in orders
            ):
                self._append_order(orders, row, "", "ignored", "position or BUY order already exists")
                continue

            signal_day = _parse_date(row.get("date_et", ""))
            repeated = False
            if signal_day:
                for prior in orders:
                    prior_day = _parse_date(prior.get("submitted_at_et", ""))
                    if (
                        prior.get("ticker") == ticker
                        and prior.get("side") == "BUY"
                        and prior.get("status") in {"pending", "filled"}
                        and prior_day
                        and timedelta(0) <= signal_day - prior_day <= timedelta(days=self.policy.repeat_window_days)
                    ):
                        repeated = True
                        break
            if repeated:
                self._append_order(orders, row, "", "ignored", "repeat BUY inside policy window")
                continue

            target_notional = round(equity * self.policy.position_allocation_pct, 2)
            if open_market_value + target_notional > equity * self.policy.max_gross_exposure_pct + 0.01:
                self._append_order(orders, row, "", "rejected", "maximum gross exposure reached")
                continue
            if target_notional > available_cash + 0.01:
                self._append_order(orders, row, "", "rejected", "insufficient cash")
                continue
            self._append_order(orders, row, "BUY", "pending", "eligible recommendation", target_notional)
            open_market_value += target_notional
            available_cash -= target_notional

        _atomic_write_csv(self.orders_path, ORDER_HEADERS, orders)
        if added:
            print(f"[portfolio] Consumed {added} new signal(s)")
        return added

    def _append_event(
        self,
        ledger: list[dict[str, str]],
        occurred_at: str,
        event_type: str,
        order_id: str,
        signal_id: str,
        ticker: str,
        shares: float,
        price: float,
        reason: str,
    ) -> None:
        cash_delta = shares * price * (-1 if event_type == "BUY" else 1)
        event_id = _stable_id("evt", occurred_at, event_type, order_id, ticker, _fmt(shares, 6), _fmt(price, 4))
        ledger.append(
            {
                "event_id": event_id,
                "occurred_at_et": occurred_at,
                "event_type": event_type,
                "order_id": order_id,
                "signal_id": signal_id,
                "ticker": ticker,
                "shares": _fmt(shares, 6),
                "price": _fmt(price, 4),
                "cash_delta": _fmt(cash_delta, 4),
                "reason": reason,
                "policy_version": self.policy.version,
            }
        )

    def settle_orders(self, as_of: date) -> int:
        orders = _read_csv(self.orders_path)
        ledger = _read_csv(self.ledger_path)
        state = self.reconstruct()
        filled = 0
        slip = self.policy.slippage_bps / 10_000.0

        for order in orders:
            if order.get("status") != "pending":
                continue
            eligible = _parse_date(order.get("eligible_date", ""))
            if eligible is None or eligible > as_of:
                continue
            ticker = order.get("ticker", "")
            bar = self.prices.bar(ticker, eligible)
            if not bar:
                continue
            signal_price = _safe_float(order.get("signal_price"))
            if signal_price is None:
                order["status"] = "rejected"
                order["reason"] = "signal price unavailable at settlement"
                continue
            gap = abs(bar["open"] - signal_price) / signal_price
            if gap > self.policy.max_open_gap_pct:
                order["status"] = "rejected"
                order["reason"] = f"opening gap {gap:.2%} exceeded {self.policy.max_open_gap_pct:.2%}"
                continue

            side = order.get("side")
            occurred_at = f"{eligible.isoformat()} 09:30 ET"
            if side == "BUY":
                if ticker in state.positions:
                    order["status"] = "cancelled"
                    order["reason"] = "position already open at settlement"
                    continue
                target = _safe_float(order.get("target_notional")) or 0.0
                fill_price = bar["open"] * (1 + slip)
                notional = min(target, state.cash)
                shares = math.floor((notional / fill_price) * 1_000_000) / 1_000_000
                if shares <= 0:
                    order["status"] = "rejected"
                    order["reason"] = "insufficient cash at settlement"
                    continue
                self._append_event(
                    ledger,
                    occurred_at,
                    "BUY",
                    order["order_id"],
                    order["signal_id"],
                    ticker,
                    shares,
                    fill_price,
                    "next eligible open with adverse slippage",
                )
                state.cash -= shares * fill_price
                state.positions[ticker] = Position(ticker, shares, fill_price, occurred_at, order["signal_id"])
            elif side == "SELL":
                position = state.positions.get(ticker)
                if position is None:
                    order["status"] = "cancelled"
                    order["reason"] = "position no longer open at settlement"
                    continue
                fill_price = bar["open"] * (1 - slip)
                shares = position.shares
                self._append_event(
                    ledger,
                    occurred_at,
                    "SELL",
                    order["order_id"],
                    order["signal_id"],
                    ticker,
                    shares,
                    fill_price,
                    "SELL recommendation at next eligible open",
                )
                state.cash += shares * fill_price
                state.realized_pnl += (fill_price - position.average_entry) * shares
                del state.positions[ticker]
            else:
                order["status"] = "rejected"
                order["reason"] = "invalid order side"
                continue

            order["status"] = "filled"
            order["filled_at_et"] = occurred_at
            order["fill_price"] = _fmt(fill_price, 4)
            order["shares"] = _fmt(shares, 6)
            filled += 1

        _atomic_write_csv(self.orders_path, ORDER_HEADERS, orders)
        _atomic_write_csv(self.ledger_path, LEDGER_HEADERS, ledger)
        return filled

    def evaluate_risk_exits(self, as_of: date) -> int:
        state = self.reconstruct()
        ledger = _read_csv(self.ledger_path)
        closed = 0
        slip = self.policy.slippage_bps / 10_000.0

        for ticker, position in list(state.positions.items()):
            opened = _parse_date(position.opened_at)
            if opened is None:
                continue
            bars = sorted(
                (day, bar)
                for day, bar in self.prices.history(ticker).items()
                if opened <= day <= as_of
            )
            if not bars:
                continue
            stop_price = position.average_entry * (1 - self.policy.stop_loss_pct)
            exit_kind = ""
            exit_day: date | None = None
            exit_price = 0.0
            reason = ""

            for index, (day, bar) in enumerate(bars):
                if bar["open"] <= stop_price:
                    exit_kind = "STOP"
                    exit_day = day
                    exit_price = bar["open"] * (1 - slip)
                    reason = "opened below stop threshold"
                    break
                if bar["low"] <= stop_price:
                    exit_kind = "STOP"
                    exit_day = day
                    exit_price = stop_price * (1 - slip)
                    reason = f"{self.policy.stop_loss_pct:.0%} stop loss"
                    break
                if index + 1 >= self.policy.max_holding_sessions:
                    exit_kind = "TIME_EXIT"
                    exit_day = day
                    exit_price = bar["close"] * (1 - slip)
                    reason = f"{self.policy.max_holding_sessions}-session safety exit"
                    break

            if not exit_kind or exit_day is None:
                continue
            event_id = _stable_id("risk", position.signal_id, exit_kind, exit_day.isoformat())
            if any(event.get("order_id") == event_id for event in ledger):
                continue
            self._append_event(
                ledger,
                f"{exit_day.isoformat()} 16:00 ET",
                exit_kind,
                event_id,
                position.signal_id,
                ticker,
                position.shares,
                exit_price,
                reason,
            )
            closed += 1

        _atomic_write_csv(self.ledger_path, LEDGER_HEADERS, ledger)
        return closed

    def write_snapshot(self, as_of: date) -> dict[str, str]:
        state = self.reconstruct()
        market_value, equity, unrealized, marks = self.account_values(state, as_of)
        positions = [
            {
                "ticker": ticker,
                "purchase_date": position.opened_at[:10],
                "shares": round(position.shares, 6),
                "average_entry": round(position.average_entry, 4),
                "current_price": round(marks.get(ticker, position.average_entry), 4),
                "market_value": round(position.shares * marks.get(ticker, position.average_entry), 2),
                "pnl_pct": round(
                    ((marks.get(ticker, position.average_entry) - position.average_entry) / position.average_entry) * 100,
                    2,
                ),
            }
            for ticker, position in sorted(state.positions.items())
        ]
        snapshots = _read_csv(self.snapshots_path)
        metadata = self.initialize(as_of)
        account_start = _parse_date(metadata.get("inception_date", "")) or as_of
        spy_return = ""
        spy = self.prices.history("SPY")
        if spy and account_start:
            start_day = min((day for day in spy if day >= account_start), default=None)
            latest = max((day for day in spy if day <= as_of), default=None)
            if start_day and latest and latest >= start_day:
                spy_return = _fmt(((spy[latest]["close"] - spy[start_day]["close"]) / spy[start_day]["close"]) * 100, 2)

        row = {
            "date_et": as_of.isoformat(),
            "recorded_at_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
            "cash": _fmt(state.cash, 2),
            "market_value": _fmt(market_value, 2),
            "equity": _fmt(equity, 2),
            "realized_pnl": _fmt(state.realized_pnl, 2),
            "unrealized_pnl": _fmt(unrealized, 2),
            "return_pct": _fmt(((equity / self.policy.initial_capital) - 1) * 100, 2),
            "spy_return_pct": spy_return,
            "positions_json": json.dumps(positions, separators=(",", ":")),
            "policy_version": self.policy.version,
        }
        snapshots = [snapshot for snapshot in snapshots if snapshot.get("date_et") != row["date_et"]]
        snapshots.append(row)
        snapshots.sort(key=lambda snapshot: snapshot.get("date_et", ""))
        _atomic_write_csv(self.snapshots_path, SNAPSHOT_HEADERS, snapshots)
        return row

    def process(self, signal_rows: list[dict[str, str]], as_of: date) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        metadata = self.initialize(as_of)
        inception = _parse_date(metadata.get("inception_date", "")) or as_of
        eligible_signals = [
            row
            for row in signal_rows
            if inception <= (_parse_date(row.get("date_et", "")) or date.min) <= as_of
        ]
        existing_orders = _read_csv(self.orders_path)
        consumed_ids = {row.get("signal_id", "") for row in existing_orders}
        unseen = [
            row for row in eligible_signals if signal_identity(row) not in consumed_ids
        ]
        unseen.sort(key=lambda row: (row.get("date_et", ""), row.get("time_et", "")))

        filled = self.settle_orders(as_of)
        consumed = 0
        open_phase: list[dict[str, str]] = []
        close_phase: list[dict[str, str]] = []
        for row in unseen:
            try:
                eligible_day = self.eligible_date(row)
            except ValueError:
                close_phase.append(row)
                continue
            if (
                eligible_day <= as_of
                and row.get("report_type", "").strip().lower() == "pre-market"
            ):
                open_phase.append(row)
            else:
                close_phase.append(row)

        for row in open_phase:
            consumed += self.ingest_signals([row], as_of)
            filled += self.settle_orders(as_of)

        risk_exits = self.evaluate_risk_exits(as_of)

        for row in close_phase:
            consumed += self.ingest_signals([row], as_of)
            signal_day = _parse_date(row.get("date_et", ""))
            try:
                eligible_day = self.eligible_date(row)
            except ValueError:
                eligible_day = None
            if eligible_day and eligible_day <= as_of and signal_day and signal_day < as_of:
                filled += self.settle_orders(as_of)

        snapshot = self.write_snapshot(as_of)
        self.reconstruct()
        print(
            f"[portfolio] Processed account: consumed={consumed}, filled={filled}, "
            f"risk_exits={risk_exits}, equity=${snapshot['equity']}"
        )
        return {
            "consumed": consumed,
            "filled": filled,
            "risk_exits": risk_exits,
            "snapshot": snapshot,
        }


def load_signals(path: Path = DEFAULT_SIGNALS_PATH) -> list[dict[str, str]]:
    return _read_csv(Path(path))


def run_backtest(
    signals_path: Path = DEFAULT_SIGNALS_PATH,
    state_dir: Path = DEFAULT_BACKTEST_DIR,
    prices: PriceProvider | None = None,
) -> dict[str, Any]:
    signals = load_signals(signals_path)
    if not signals:
        raise ValueError("No signals available for historical replay")
    state_dir = Path(state_dir)
    if state_dir.exists():
        shutil.rmtree(state_dir)
    engine = PaperPortfolio(state_dir=state_dir, prices=prices)

    grouped: dict[date, list[dict[str, str]]] = {}
    for row in signals:
        signal_day = _parse_date(row.get("date_et", ""))
        if signal_day:
            grouped.setdefault(signal_day, []).append(row)
    first_day = min(grouped)
    engine.initialize(first_day)
    last_day = min(date.today(), max(grouped) + timedelta(days=20))
    day = first_day
    all_seen: list[dict[str, str]] = []
    while day <= last_day:
        day_rows = sorted(grouped.get(day, []), key=lambda row: row.get("time_et", ""))
        pre_rows = [
            row
            for row in day_rows
            if row.get("report_type", "").lower() == "pre-market"
            or row.get("report_type", "").lower() == "weekly"
        ]
        post_rows = [row for row in day_rows if row not in pre_rows]
        all_seen.extend(pre_rows)
        engine.process(all_seen, day)
        all_seen.extend(post_rows)
        if post_rows:
            engine.process(all_seen, day)
        day += timedelta(days=1)
    engine.process(all_seen, last_day)
    snapshots = _read_csv(engine.snapshots_path)
    return {
        "signals": len(signals),
        "orders": len(_read_csv(engine.orders_path)),
        "events": len(_read_csv(engine.ledger_path)),
        "snapshots": len(snapshots),
        "ending_equity": snapshots[-1].get("equity") if snapshots else "",
        "state_dir": str(state_dir),
    }


def _today_et() -> date:
    return datetime.now(ET).date()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the paper portfolio engine")
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS_PATH)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--as-of", type=str, default="")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        as_of = _parse_date(args.as_of) if args.as_of else _today_et()
        if as_of is None:
            raise ValueError(f"Invalid --as-of date: {args.as_of}")
        if args.backtest:
            target = args.state_dir if args.state_dir != DEFAULT_STATE_DIR else DEFAULT_BACKTEST_DIR
            if args.dry_run:
                target = REPO_ROOT / "local-output" / "paper_portfolio_backtest"
            result = run_backtest(args.signals, target)
        else:
            target = args.state_dir
            if args.dry_run:
                target = REPO_ROOT / "local-output" / "paper_portfolio_preview"
                if target.exists():
                    shutil.rmtree(target)
                if args.state_dir.exists():
                    shutil.copytree(args.state_dir, target)
            result = PaperPortfolio(target).process(load_signals(args.signals), as_of)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"[portfolio] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
