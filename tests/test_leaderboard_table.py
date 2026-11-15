import json
import time

import pytest
from rich.console import Console

from elf.leaderboard import (
    _first_star_timestamp,
    _format_utc_timestamp,
    format_leaderboard_as_table,
    get_leaderboard,
)
from elf.models import Leaderboard, Member, OutputFormat


def _member(
    *,
    member_id: int = 1,
    name: str = "Elf",
    last_star_ts: int = 0,
    stars: int = 0,
    local_score: int = 0,
    completion_day_level=None,
) -> Member:
    data = {
        "id": member_id,
        "name": name,
        "last_star_ts": last_star_ts,
        "stars": stars,
        "local_score": local_score,
    }
    if completion_day_level is not None:
        data["completion_day_level"] = completion_day_level
    return Member.model_validate(data)


def _leaderboard_payload():
    return {
        "num_days": 12,
        "event": "2025",
        "day1_ts": 1764565200,
        "owner_id": 1,
        "members": {
            "1": {
                "id": 1,
                "name": "Alice",
                "last_star_ts": 1765005300,
                "stars": 4,
                "local_score": 150,
                "completion_day_level": {
                    "6": {
                        "2": {"get_star_ts": 1765005300, "star_index": 4},
                        "1": {"get_star_ts": 1765004400, "star_index": 3},
                    },
                    "1": {
                        "2": {"get_star_ts": 1764567900, "star_index": 2},
                        "1": {"get_star_ts": 1764565800, "star_index": 1},
                    },
                },
            },
            "2": {
                "id": 2,
                "name": "Bob",
                "last_star_ts": 1764567000,
                "stars": 1,
                "local_score": 80,
                "completion_day_level": {"1": {"1": {"get_star_ts": 1764567000, "star_index": 5}}},
            },
            "3": {
                "id": 3,
                "name": "Carol",
                "last_star_ts": 0,
                "stars": 0,
                "local_score": 0,
            },
        },
    }


def _render_table(leaderboard: Leaderboard) -> str:
    console = Console(record=True, width=140, color_system=None)
    console.print(format_leaderboard_as_table(leaderboard))
    return console.export_text()


def test_first_star_uses_earliest_completion_independent_of_mapping_order():
    member = _member(
        completion_day_level={
            5: {
                2: {"get_star_ts": 500, "star_index": 4},
                1: {"get_star_ts": 400, "star_index": 3},
            },
            1: {
                2: {"get_star_ts": 200, "star_index": 2},
                1: {"get_star_ts": 100, "star_index": 1},
            },
        }
    )

    assert _first_star_timestamp(member) == 100


@pytest.mark.parametrize("completion_day_level", [None, {}])
def test_first_star_handles_missing_or_empty_completion_data(completion_day_level):
    member = _member(completion_day_level=completion_day_level)

    assert _first_star_timestamp(member) is None


def test_table_displays_first_and_last_stars_and_preserves_ranking():
    output = _render_table(Leaderboard.model_validate(_leaderboard_payload()))

    assert "First Star (UTC)" in output
    assert "Last Star (UTC)" in output
    assert "2025-12-01 05:10:00" in output
    assert output.count("2025-12-01 05:30:00") == 2
    assert output.index("Alice") < output.index("Bob") < output.index("Carol")
    assert "│    1 │ Alice" in output
    assert "│    2 │ Bob" in output
    assert "│    3 │ Carol" in output
    assert "│ Carol │     0 │           0 │ -" in output


def test_timestamp_formatting_is_utc_regardless_of_machine_timezone(monkeypatch):
    if hasattr(time, "tzset"):
        with monkeypatch.context() as timezone:
            timezone.setenv("TZ", "Pacific/Honolulu")
            time.tzset()
            assert _format_utc_timestamp(1764565800) == "2025-12-01 05:10:00"
        time.tzset()
    else:
        assert _format_utc_timestamp(1764565800) == "2025-12-01 05:10:00"


def test_json_and_model_outputs_are_unchanged(monkeypatch):
    payload = _leaderboard_payload()
    monkeypatch.setattr("elf.leaderboard._read_fresh_cache", lambda _path: payload)

    json_output = get_leaderboard(2025, "session", 1, None, OutputFormat.JSON)
    model_output = get_leaderboard(2025, "session", 1, None, OutputFormat.MODEL)

    assert json.loads(json_output) == payload
    assert isinstance(model_output, Leaderboard)
    assert not hasattr(model_output.members[1], "first_star_ts")
