from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from elf.events import (
    default_event_day,
    default_event_year,
    event_day_count,
    validate_event_day,
)

AOC_TZ = ZoneInfo("America/New_York")


def _aoc_time(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, tzinfo=AOC_TZ)


def test_event_lengths_cover_full_and_reduced_formats():
    assert event_day_count(2015) == 25
    assert event_day_count(2024) == 25
    assert event_day_count(2025) == 12
    assert event_day_count(2026) == 12

    validate_event_day(2024, 25)
    validate_event_day(2025, 12)
    with pytest.raises(ValueError, match="days 1–12"):
        validate_event_day(2025, 13)


def test_defaults_use_latest_event_outside_december():
    now = _aoc_time(2026, 7, 1)

    assert default_event_year(now) == 2025
    assert default_event_day(now=now) == 12
    assert default_event_day(2024, now=now) == 25


def test_defaults_follow_active_event_and_stop_at_its_last_day():
    assert default_event_year(_aoc_time(2026, 12, 5)) == 2026
    assert default_event_day(now=_aoc_time(2026, 12, 5)) == 5
    assert default_event_day(now=_aoc_time(2026, 12, 20)) == 12
