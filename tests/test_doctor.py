from datetime import datetime
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

from elf.cli import app
from elf.doctor import CheckStatus, run_doctor


def test_doctor_reports_configuration_without_exposing_secrets(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("ELF_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("AOC_SESSION", "super-secret-session")
    monkeypatch.setenv("AOC_USER_AGENT", "maintainer@example.com")

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "default puzzle" in result.stdout
    assert "AOC_SESSION is configured" in result.stdout
    assert "super-secret-session" not in result.stdout
    assert "maintainer@example.com" not in result.stdout


def test_doctor_uses_year_round_defaults_and_warns_for_missing_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("AOC_SESSION", raising=False)
    monkeypatch.delenv("AOC_USER_AGENT", raising=False)
    now = datetime(2026, 7, 1, 12, tzinfo=ZoneInfo("America/New_York"))

    report = run_doctor(now=now)

    assert report.has_errors is False
    assert any("2025-12-12" in check.detail for check in report.checks)
    warnings = [check for check in report.checks if check.status is CheckStatus.WARNING]
    assert {check.name for check in warnings} == {"Session", "User-Agent"}


def test_doctor_fails_when_cache_path_is_not_writable(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("blocked", encoding="utf-8")
    monkeypatch.setenv("ELF_CACHE_DIR", str(blocker / "cache"))

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "ERROR" in result.stdout
    assert "not writable" in result.stdout
