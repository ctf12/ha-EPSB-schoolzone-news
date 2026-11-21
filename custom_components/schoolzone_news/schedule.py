"""Which times SchoolZone is checked on which days. No Home Assistant imports."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .const import SUNDAY_CHECK_TIME

SUNDAY_CHECK = time.fromisoformat(SUNDAY_CHECK_TIME)


def times_for_day(day: date, weekday_times: list[time]) -> list[time]:
    """Check times for a calendar day: none Saturday, 19:00 only Sunday."""
    weekday = day.weekday()
    if weekday == 5:
        return []
    if weekday == 6:
        return [SUNDAY_CHECK]
    return list(weekday_times)


def all_check_times(weekday_times: list[time]) -> list[time]:
    """Every time of day that needs a listener (days are filtered when it fires)."""
    return sorted({*weekday_times, SUNDAY_CHECK})


def last_slot(now: datetime, weekday_times: list[time]) -> datetime:
    """Most recent scheduled check at or before ``now``."""
    for back in range(8):
        day = now.date() - timedelta(days=back)
        slots = [
            datetime.combine(day, t, tzinfo=now.tzinfo)
            for t in times_for_day(day, weekday_times)
        ]
        slots = [s for s in slots if s <= now]
        if slots:
            return max(slots)
    return now - timedelta(days=8)
