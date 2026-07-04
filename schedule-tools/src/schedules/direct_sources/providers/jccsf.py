from __future__ import annotations

from ..parsing import (
    _closure_dates_from_text,
    _html_text,
    _payload,
    _require_text,
    _weekly_hours_sessions,
)

# The JCCSF rec-pool schedule is prose with multiple ranges per line, so the
# session tables below are hand-modeled rather than parsed. Each guard is the
# literal page text a table encodes — if JCCSF changes any posted hours, the
# missing guard fails the extraction loudly instead of publishing stale hours.
_JCCSF_HOUR_GUARDS = (
    "Monday – Friday: 5:30 am – 9:45 pm",
    "Saturday & Sunday: 7:00 am – 6:45 pm",
    "Monday, Wednesday: 5:30 am – Noon, 1:30 – 9:45 pm",
    "Tuesday: 5:30 – 11:30 am, 12:30 – 9:45 pm",
    "Thursday: 5:30 – Noon, 1:00 – 9:45 pm",
    "Friday: 5:30 – Noon, 1:30 – 9:45 pm",
    "Saturday & Sunday: 7:00 – 8:00 am, 2:00 – 6:45 pm",
)


def _extract_jccsf(html: str) -> dict:
    text = _html_text(html)
    sessions = [
        *_weekly_hours_sessions(
            "lap_swim",
            {
                "monday": ("05:30", "21:45"),
                "tuesday": ("05:30", "21:45"),
                "wednesday": ("05:30", "21:45"),
                "thursday": ("05:30", "21:45"),
                "friday": ("05:30", "21:45"),
                "saturday": ("07:00", "18:45"),
                "sunday": ("07:00", "18:45"),
            },
            evidence="The Lap Pool is available for lap swimming during Aquatics Center hours.",
        ),
        *_weekly_hours_sessions(
            "family_swim",
            {
                "monday": ("05:30", "12:00"),
                "wednesday": ("05:30", "12:00"),
                "tuesday": ("05:30", "11:30"),
                "thursday": ("05:30", "12:00"),
                "friday": ("05:30", "12:00"),
                "saturday": ("07:00", "08:00"),
                "sunday": ("07:00", "08:00"),
            },
            evidence="Recreation & Family Swim morning hours.",
        ),
        *_weekly_hours_sessions(
            "family_swim",
            {
                "monday": ("13:30", "21:45"),
                "wednesday": ("13:30", "21:45"),
                "tuesday": ("12:30", "21:45"),
                "thursday": ("13:00", "21:45"),
                "friday": ("13:30", "21:45"),
                "saturday": ("14:00", "18:45"),
                "sunday": ("14:00", "18:45"),
            },
            evidence="Recreation & Family Swim afternoon/evening hours.",
        ),
    ]
    _require_text(text, "Aquatics Center Hours")
    _require_text(text, "The Lap Pool is available for lap swimming during Aquatics Center hours")
    for guard in _JCCSF_HOUR_GUARDS:
        _require_text(text, guard)
    return _payload("swim_schedule", sessions, closures=_closure_dates_from_text(text))
