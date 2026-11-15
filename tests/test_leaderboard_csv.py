import csv
import io
import json

from rich.table import Table

from elf import OutputFormat, get_private_leaderboard
from elf.leaderboard import format_leaderboard_as_csv
from elf.models import Leaderboard

CSV_FIELDS = [
    "year",
    "board_id",
    "rank",
    "member_id",
    "name",
    "stars",
    "local_score",
    "first_star_utc",
    "last_star_utc",
]


def _payload():
    return {
        "num_days": 12,
        "event": "2025",
        "day1_ts": 1764565200,
        "owner_id": 1,
        "members": {
            "30": {
                "id": 30,
                "name": "Zero",
                "last_star_ts": 0,
                "stars": 0,
                "local_score": 0,
            },
            "20": {
                "id": 20,
                "name": None,
                "last_star_ts": 1764567000,
                "stars": 1,
                "local_score": 50,
                "completion_day_level": {"1": {"1": {"get_star_ts": 1764567000, "star_index": 5}}},
            },
            "10": {
                "id": 10,
                "name": 'Døe, "Elf" 🎄\nJr.',
                "last_star_ts": 1765005300,
                "stars": 3,
                "local_score": 100,
                "completion_day_level": {
                    "6": {"1": {"get_star_ts": 1765005300, "star_index": 4}},
                    "1": {
                        "2": {"get_star_ts": 1764567900, "star_index": 2},
                        "1": {"get_star_ts": 1764565800, "star_index": 1},
                    },
                },
            },
            "1": {
                "id": 1,
                "name": "Alice",
                "last_star_ts": 1764567900,
                "stars": 3,
                "local_score": 100,
                "completion_day_level": {"1": {"1": {"get_star_ts": 1764566100, "star_index": 3}}},
            },
            "5": {
                "id": 5,
                "name": "Five",
                "last_star_ts": 1764568000,
                "stars": 2,
                "local_score": 100,
                "completion_day_level": {},
            },
        },
    }


def _read_csv(data: str):
    reader = csv.DictReader(io.StringIO(data))
    return reader.fieldnames, list(reader)


def test_csv_schema_values_escaping_and_deterministic_sorting():
    leaderboard = Leaderboard.model_validate(_payload())

    csv_data = format_leaderboard_as_csv(leaderboard, year=2025, board_id=123456)
    fieldnames, rows = _read_csv(csv_data)

    assert fieldnames == CSV_FIELDS
    assert [row["member_id"] for row in rows] == ["1", "10", "5", "20", "30"]
    assert [row["rank"] for row in rows] == ["1", "2", "3", "4", "5"]
    assert rows[1]["name"] == 'Døe, "Elf" 🎄\nJr.'
    assert rows[1]["first_star_utc"] == "2025-12-01T05:10:00Z"
    assert rows[1]["last_star_utc"] == "2025-12-06T07:15:00Z"
    assert rows[2]["first_star_utc"] == ""
    assert rows[2]["last_star_utc"] == "2025-12-01T05:46:40Z"
    assert rows[3]["name"] == "<anonymous>"
    assert rows[4]["stars"] == "0"
    assert rows[4]["first_star_utc"] == ""
    assert rows[4]["last_star_utc"] == ""
    assert csv_data == format_leaderboard_as_csv(leaderboard, year=2025, board_id=123456)


def test_empty_leaderboard_csv_contains_stable_header():
    payload = _payload()
    payload["members"] = {}

    fieldnames, rows = _read_csv(
        format_leaderboard_as_csv(Leaderboard.model_validate(payload), year=2025, board_id=123456)
    )

    assert fieldnames == CSV_FIELDS
    assert rows == []


def test_public_api_returns_csv_and_unchanged_other_formats(monkeypatch):
    payload = _payload()
    monkeypatch.setattr("elf.leaderboard._read_fresh_cache", lambda _path: payload)

    csv_output = get_private_leaderboard(
        2025,
        board_id=123456,
        session="session",
        fmt=OutputFormat.CSV,
    )
    json_output = get_private_leaderboard(
        2025,
        board_id=123456,
        session="session",
        fmt=OutputFormat.JSON,
    )
    model_output = get_private_leaderboard(
        2025,
        board_id=123456,
        session="session",
        fmt=OutputFormat.MODEL,
    )
    table_output = get_private_leaderboard(
        2025,
        board_id=123456,
        session="session",
        fmt=OutputFormat.TABLE,
    )

    assert isinstance(csv_output, str)
    assert isinstance(json_output, str)
    assert json.loads(json_output) == payload
    assert isinstance(model_output, Leaderboard)
    assert isinstance(table_output, Table)
