"""Estremi UTC e ultima giornata conclusa secondo il calendario Europe/Rome."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")


def gas_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(6), ROME).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(6), ROME).astimezone(timezone.utc)
    return start, end


def closed_gas_day(now: datetime) -> date:
    if now.utcoffset() is None:
        raise ValueError("La data di riferimento deve includere il fuso orario.")
    local = now.astimezone(ROME)
    active = local.date() if local.hour >= 6 else local.date() - timedelta(days=1)
    return active - timedelta(days=1)
