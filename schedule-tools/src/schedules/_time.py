from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def pacific_today() -> date:
    return datetime.now(PACIFIC_TZ).date()
