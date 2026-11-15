import csv
import io
import json
from pathlib import Path

from typer.testing import CliRunner

from elf.cli import app
from elf.models import OutputFormat, SubmissionResult, SubmissionStatus

runner = CliRunner()


def test_input_cmd_invokes_get_input(monkeypatch):
    captured = {}

    def fake_get_input(year, day, session):
        captured.update({"year": year, "day": day, "session": session})
        return "cached-input"

    monkeypatch.setattr("elf.cli.get_input", fake_get_input)

    result = runner.invoke(app, ["input", "2024", "2", "--session", "session-token"])

    assert result.exit_code == 0
    assert result.stdout == "cached-input"
    assert captured == {"year": 2024, "day": 2, "session": "session-token"}


def test_answer_cmd_exit_codes(monkeypatch):
    def make_result(status):
        return SubmissionResult(
            guess="42",
            result=status,
            message=f"result-{status.value}",
            is_correct=status == SubmissionStatus.CORRECT,
            is_cached=False,
        )

    monkeypatch.setattr(
        "elf.cli.submit_answer", lambda **kwargs: make_result(SubmissionStatus.CORRECT)
    )
    success = runner.invoke(
        app,
        ["answer", "2024", "2", "1", "123", "--session", "token"],
    )
    assert success.exit_code == 0
    assert "result-correct" in success.stdout

    monkeypatch.setattr(
        "elf.cli.submit_answer", lambda **kwargs: make_result(SubmissionStatus.WAIT)
    )
    wait = runner.invoke(
        app,
        ["answer", "2024", "2", "1", "123", "--session", "token"],
    )
    assert wait.exit_code == 2


def test_leaderboard_cmd_forwards_options(monkeypatch):
    captured = {}

    def fake_get_leaderboard(year, session, board_id, view_key, fmt):
        captured.update(
            {
                "year": year,
                "session": session,
                "board_id": board_id,
                "view_key": view_key,
                "fmt": fmt,
            }
        )
        return "leaderboard-output"

    monkeypatch.setattr("elf.cli.get_leaderboard", fake_get_leaderboard)

    result = runner.invoke(
        app,
        [
            "leaderboard",
            "2024",
            "12345",
            "--view-key",
            "secret",
            "--format",
            "json",
            "--session",
            "token",
        ],
    )

    assert result.exit_code == 0
    assert "leaderboard-output" in result.stdout
    assert captured["fmt"] == OutputFormat.JSON


def test_json_output_is_not_interpreted_as_rich_markup(monkeypatch):
    payload = '{"name": "[red]literal[/red]"}'
    monkeypatch.setattr("elf.cli.get_leaderboard", lambda *args, **kwargs: payload)

    result = runner.invoke(
        app,
        ["leaderboard", "2024", "12345", "--view-key", "secret", "--format", "json"],
    )

    assert result.exit_code == 0
    assert result.stdout == f"{payload}\n"
    assert json.loads(result.stdout) == {"name": "[red]literal[/red]"}


def test_csv_output_is_raw_machine_readable_data(monkeypatch):
    payload = 'name,stars\n"[red]Elf, One[/red]",2\n'
    monkeypatch.setattr("elf.cli.get_leaderboard", lambda *args, **kwargs: payload)

    result = runner.invoke(
        app,
        ["leaderboard", "2025", "12345", "--view-key", "secret", "--format", "csv"],
    )

    assert result.exit_code == 0
    assert result.stdout == payload
    assert list(csv.DictReader(io.StringIO(result.stdout))) == [
        {"name": "[red]Elf, One[/red]", "stars": "2"}
    ]


def test_leaderboard_authentication_errors_stay_on_stderr(monkeypatch):
    monkeypatch.delenv("AOC_SESSION", raising=False)

    result = runner.invoke(app, ["leaderboard", "2025", "12345", "--format", "csv"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "AOC_SESSION" in result.stderr


def test_status_rejects_csv_without_advertising_it():
    help_result = runner.invoke(app, ["status", "--help"])
    csv_result = runner.invoke(
        app,
        ["status", "2025", "--session", "token", "--format", "csv"],
    )

    assert help_result.exit_code == 0
    assert "csv" not in help_result.stdout.lower()
    assert csv_result.exit_code == 2
    assert "invalid value" in csv_result.stderr.lower()


def test_status_cmd_outputs(monkeypatch):
    def fake_get_status(year, session, fmt):
        return f"status-{year}-{fmt.value}"

    monkeypatch.setattr("elf.cli.get_status", fake_get_status)

    result = runner.invoke(app, ["status", "2023", "--format", "table", "--session", "token"])
    assert result.exit_code == 0
    assert "status-2023-table" in result.stdout


def test_cache_cmd_handles_empty_dir(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("elf.cli.get_cache_dir", lambda: cache_dir)

    result = runner.invoke(app, ["cache"])

    assert result.exit_code == 0
    assert "No cache directory found yet" in result.stdout


def test_guesses_cmd_invokes_reader(monkeypatch):
    monkeypatch.setattr("elf.cli.get_guesses", lambda year, day, session: "guess-history")

    result = runner.invoke(app, ["guesses", "2024", "3"])

    assert result.exit_code == 0
    assert "guess-history" in result.stdout


def test_open_cmd_prints_message(monkeypatch):
    monkeypatch.setattr("elf.cli.open_page", lambda year, day, kind: "opened")

    result = runner.invoke(app, ["open", "2024", "1", "--kind", "input"])

    assert result.exit_code == 0
    assert "opened" in result.stdout


def test_new_cmd_creates_template_and_refuses_overwrite(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    created = runner.invoke(app, ["new", "2025", "1"])
    customized = runner.invoke(
        app,
        ["new", "2025", "2", "--output", "solutions/custom.py"],
    )
    duplicate = runner.invoke(app, ["new", "2025", "1"])

    assert created.exit_code == 0
    assert f"Created {Path('2025') / 'day01.py'}" in created.stdout
    assert (tmp_path / "2025" / "day01.py").is_file()
    assert customized.exit_code == 0
    assert (tmp_path / "solutions" / "custom.py").is_file()
    assert duplicate.exit_code == 1
    assert duplicate.stdout == ""
    assert "Refusing to overwrite" in duplicate.stderr
