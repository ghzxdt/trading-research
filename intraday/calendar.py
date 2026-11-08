"""Cash-equity sessions. Early closes verified against NYSE calendars for 2025–28.

The legacy helper supplies holidays/exceptional full-day closures. Outside this
published early-close coverage, hours are explicitly unverified and the baseline
abstains. This is not an options-exchange calendar.
Source: https://www.nyse.com/markets/hours-calendars
"""
from functools import lru_cache
import pandas as pd
from validation import equity_sessions

NY = "America/New_York"
EARLY_CLOSES = {
    "2025-07-03", "2025-11-28", "2025-12-24",
    "2026-11-27", "2026-12-24", "2027-11-26",
    "2028-07-03", "2028-11-24",
}


def utc(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("An explicit timezone is required")
    return stamp.tz_convert("UTC")


@lru_cache(maxsize=4096)
def session(date):
    day = pd.Timestamp(date).tz_localize(None).normalize()
    label = day.strftime("%Y-%m-%d")
    if not len(equity_sessions(day, day)):
        return {"date": label, "is_session": False, "calendar_verified": 2025 <= day.year <= 2028}
    early = label in EARLY_CLOSES
    opening = day.tz_localize(NY) + pd.Timedelta(hours=9, minutes=30)
    closing = day.tz_localize(NY) + pd.Timedelta(hours=13 if early else 16)
    return {"date": label, "is_session": True, "calendar_verified": 2025 <= day.year <= 2028,
            "open": opening.tz_convert("UTC").isoformat(),
            "close": closing.tz_convert("UTC").isoformat(), "early_close": early,
            "timezone": NY, "calendar_source": "NYSE published 2025–2028 cash-equity hours"}


def date_of(value):
    return utc(value).tz_convert(NY).strftime("%Y-%m-%d")
