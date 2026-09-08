from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

# AKAIROS payroll corrections/pay cycles use Sunday through Saturday.
DEFAULT_START_WEEKDAY = 6  # Python: Monday=0 ... Sunday=6


def week_start_for(value: date | datetime | pd.Timestamp, start_weekday: int = DEFAULT_START_WEEKDAY) -> date:
    """Return the calendar date that starts the configured workweek."""
    if isinstance(value, pd.Timestamp):
        d = value.date()
    elif isinstance(value, datetime):
        d = value.date()
    else:
        d = value
    delta = (d.weekday() - int(start_weekday)) % 7
    return d - timedelta(days=delta)


def week_end_for(value: date | datetime | pd.Timestamp, start_weekday: int = DEFAULT_START_WEEKDAY) -> date:
    return week_start_for(value, start_weekday) + timedelta(days=6)


def week_key_for(value: date | datetime | pd.Timestamp, start_weekday: int = DEFAULT_START_WEEKDAY) -> str:
    start = week_start_for(value, start_weekday)
    end = start + timedelta(days=6)
    return f"{start.isoformat()}_{end.isoformat()}"


def as_timestamp(value: date | datetime | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()
