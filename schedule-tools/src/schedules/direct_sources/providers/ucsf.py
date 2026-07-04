from __future__ import annotations

import re

from ..errors import DirectSourceError
from ..parsing import _access_hour, _html_text, _parse_hours_range, _payload


def _extract_ucsf_fitness(html: str) -> dict:
    text = _html_text(html)
    match = re.search(
        r"Facility Hours:\s*Monday-Friday,\s*([^;]+);\s*Saturday-Sunday,\s*([^<]+?)(?:William|Millberry|2026|Parking|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise DirectSourceError("UCSF page did not expose facility hours.")
    weekday_hours, weekend_hours = match.groups()
    weekday_start, weekday_end = _parse_hours_range(weekday_hours)
    weekend_start, weekend_end = _parse_hours_range(weekend_hours)
    return _payload(
        "facility_hours",
        [],
        access_hours=[
            *[
                _access_hour(day, weekday_start, weekday_end, "Facility hours", f"Facility Hours: Monday-Friday, {weekday_hours}")
                for day in ("monday", "tuesday", "wednesday", "thursday", "friday")
            ],
            _access_hour("saturday", weekend_start, weekend_end, "Facility hours", f"Facility Hours: Saturday-Sunday, {weekend_hours}"),
            _access_hour("sunday", weekend_start, weekend_end, "Facility hours", f"Facility Hours: Saturday-Sunday, {weekend_hours}"),
        ],
    )


def _extract_ucsf_bakar(html: str) -> dict:
    return _extract_ucsf_fitness(html)
