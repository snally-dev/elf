from datetime import datetime

from .constants import AOC_TZ

FIRST_EVENT_YEAR = 2015
LAST_FULL_LENGTH_EVENT_YEAR = 2024
FULL_EVENT_DAYS = 25
REDUCED_EVENT_DAYS = 12


def event_day_count(year: int) -> int:
    """Return the number of puzzle days in an Advent of Code event."""
    if year < FIRST_EVENT_YEAR:
        raise ValueError(f"Invalid year {year!r}. Advent of Code started in {FIRST_EVENT_YEAR}.")
    if year <= LAST_FULL_LENGTH_EVENT_YEAR:
        return FULL_EVENT_DAYS
    return REDUCED_EVENT_DAYS


def validate_event_day(year: int, day: int) -> None:
    """Validate a year/day pair against that event's published format."""
    last_day = event_day_count(year)
    if not 1 <= day <= last_day:
        raise ValueError(
            f"Invalid day {day!r} for Advent of Code {year}. That event has days 1–{last_day}."
        )


def default_event_year(now: datetime | None = None) -> int:
    """Return the active event in December, otherwise the latest past event."""
    current = now.astimezone(AOC_TZ) if now else datetime.now(tz=AOC_TZ)
    return current.year if current.month == 12 else current.year - 1


def default_event_day(year: int | None = None, now: datetime | None = None) -> int:
    """Return a useful default day for the selected event."""
    current = now.astimezone(AOC_TZ) if now else datetime.now(tz=AOC_TZ)
    selected_year = default_event_year(current) if year is None else year
    last_day = event_day_count(selected_year)

    if selected_year < current.year:
        return last_day
    if selected_year > current.year or current.month < 12:
        return 1
    return min(current.day, last_day)
