import pytest

from elf.client import (
    get_private_leaderboard,
    get_puzzle_input,
    get_user_status,
    submit_puzzle_answer,
)
from elf.models import OutputFormat


def test_get_puzzle_input_forwards_session_once(monkeypatch):
    called = []

    def fake_get_input(year, day, session):
        called.append((year, day, session))
        return "input-data"

    monkeypatch.setattr("elf.client.get_input", fake_get_input)

    assert get_puzzle_input(2023, 5, session="manual-session") == "input-data"
    assert get_puzzle_input(2024, 1) == "input-data"
    assert called == [(2023, 5, "manual-session"), (2024, 1, None)]


def test_submit_puzzle_answer_forwards_session_and_args(monkeypatch):
    submitted = []

    def fake_submit(year, day, level, answer, session):
        submitted.append((year, day, level, answer, session))
        return "submission-result"

    monkeypatch.setattr("elf.client.submit_answer", fake_submit)

    result = submit_puzzle_answer(
        year=2023,
        day=2,
        part=1,
        answer=12345,
        session="manual-session",
    )

    assert result == "submission-result"
    assert submitted == [(2023, 2, 1, 12345, "manual-session")]


def test_get_private_leaderboard_forwards_credentials(monkeypatch):
    calls = []

    def fake_get_leaderboard(year, session, board_id, view_key, fmt):
        calls.append((year, session, board_id, view_key, fmt))
        return "leaderboard-data"

    monkeypatch.setattr("elf.client.get_leaderboard", fake_get_leaderboard)

    assert (
        get_private_leaderboard(
            2023,
            board_id=10,
            session="explicit-session",
            fmt=OutputFormat.JSON,
        )
        == "leaderboard-data"
    )
    assert (
        get_private_leaderboard(
            2024,
            board_id=123,
            view_key="view-key-abc",
        )
        == "leaderboard-data"
    )
    assert calls == [
        (2023, "explicit-session", 10, None, OutputFormat.JSON),
        (2024, None, 123, "view-key-abc", OutputFormat.MODEL),
    ]


@pytest.mark.parametrize(
    ("year", "board_id"),
    [(None, 123), (2023, None), (None, None)],
)
def test_get_private_leaderboard_invalid_inputs(year, board_id):
    with pytest.raises(TypeError):
        get_private_leaderboard(year, board_id=board_id)


def test_get_user_status_forwards_session_and_default_format(monkeypatch):
    calls = []

    def fake_get_status(year, session, fmt):
        calls.append((year, session, fmt))
        return "status-data"

    monkeypatch.setattr("elf.client.get_status", fake_get_status)

    assert get_user_status(2023, session="manual-session", fmt=OutputFormat.JSON) == "status-data"
    assert get_user_status(2024) == "status-data"
    assert calls == [
        (2023, "manual-session", OutputFormat.JSON),
        (2024, None, OutputFormat.MODEL),
    ]


def test_status_csv_is_rejected_before_authentication(monkeypatch):
    monkeypatch.delenv("AOC_SESSION", raising=False)

    with pytest.raises(ValueError, match="only supported for private leaderboards"):
        get_user_status(2025, fmt=OutputFormat.CSV)
