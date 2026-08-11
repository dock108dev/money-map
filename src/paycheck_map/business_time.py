"""Shared timezone conversion for the established Eastern business date."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

LOCAL_TIMEZONE = ZoneInfo("America/New_York")


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def local_business_date(value: datetime | None = None) -> date:
    instant = value or datetime.now(UTC)
    return as_utc(instant).astimezone(LOCAL_TIMEZONE).date()
