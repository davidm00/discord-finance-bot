"""Market state detection using exchange-calendars (NYSE)."""

from __future__ import annotations

from datetime import datetime

import pytz

ET = pytz.timezone("America/New_York")


def get_market_state() -> dict:
    """
    Returns a dict describing current US equity market state.
    {
      "state": "open" | "pre_market" | "post_market" | "closed" | "holiday" | "unknown",
      "label": str,
      "is_trading_day": bool,
      "holiday_name": str or None,
      "next_open_et": str or None,
    }
    """
    try:
        import exchange_calendars as xcals

        cal = xcals.get_calendar("XNYS")
        now_et = datetime.now(ET)
        today = now_et.date()

        is_session = cal.is_session(today)

        if not is_session:
            # Check if it's a named holiday
            holiday_name = None
            try:
                holidays = cal.regular_holidays
                if holidays is not None:
                    hol_dates = holidays.holidays()
                    import pandas as pd
                    today_ts = pd.Timestamp(today)
                    if today_ts in hol_dates:
                        holiday_name = "Market Holiday"
            except Exception:
                pass

            # If it's a weekend, label accordingly
            if today.weekday() >= 5:
                holiday_name = None  # weekend, not a holiday

            try:
                next_open = cal.next_open(now_et)
                next_open_et = next_open.astimezone(ET).strftime("%A %b %d at %I:%M %p ET")
            except Exception:
                next_open_et = None

            label = "🔴 Markets Closed"
            if holiday_name:
                label += f" — {holiday_name}"

            state = "holiday" if holiday_name else "closed"
            print(f"[calendar] Market state: {state} — {label}")
            if next_open_et:
                print(f"[calendar] Next market open: {next_open_et}")

            return {
                "state": state,
                "label": label,
                "is_trading_day": False,
                "holiday_name": holiday_name,
                "next_open_et": next_open_et,
            }

        # It's a trading day — determine session state by time
        market_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        pre_market_start_et = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
        post_market_end_et = now_et.replace(hour=20, minute=0, second=0, microsecond=0)

        if pre_market_start_et <= now_et < market_open_et:
            state = "pre_market"
            label = "🟡 Pre-Market"
        elif market_open_et <= now_et < market_close_et:
            state = "open"
            label = "🟢 Market Open"
        elif market_close_et <= now_et < post_market_end_et:
            state = "post_market"
            label = "🟠 Post-Market"
        else:
            state = "closed"
            label = "🔴 Markets Closed"

        print(f"[calendar] Market state: {state} — {label}")

        return {
            "state": state,
            "label": label,
            "is_trading_day": True,
            "holiday_name": None,
            "next_open_et": None,
        }

    except Exception as e:
        print(f"[calendar] WARNING: market state detection failed: {e}")
        return {
            "state": "unknown",
            "label": "⚪ Market Status Unknown",
            "is_trading_day": True,
            "holiday_name": None,
            "next_open_et": None,
        }
