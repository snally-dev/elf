import csv
from datetime import UTC, datetime, timedelta

import pytest

from elf.answer import check_cached_guesses, write_guess_cache
from elf.cache import get_cache_guess_file
from elf.models import SubmissionStatus


def _write_guess_csv(cache_file, rows):
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with cache_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "part", "guess", "status"])
        writer.writerows(rows)


def test_check_cached_guesses_respects_wait_ttl(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    cache_file = get_cache_guess_file(2025, 1)

    wait_timestamp = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    _write_guess_csv(
        cache_file,
        [
            (
                wait_timestamp,
                "1",
                "500",
                "WAIT",
            ),
        ],
    )

    result = check_cached_guesses(
        year=2025,
        day=1,
        level=1,
        answer="600",
        numeric_answer=600,
    )

    assert result.status == SubmissionStatus.WAIT
    assert "Cached locally" in result.message


def test_server_retry_deadline_overrides_legacy_wait_ttl(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    cache_file = get_cache_guess_file(2025, 1)
    now = datetime.now(UTC)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with cache_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "part", "guess", "status", "retry_at"])
        writer.writerow(
            [
                (now - timedelta(minutes=5)).isoformat(),
                "1",
                "500",
                "WAIT",
                (now + timedelta(minutes=2)).isoformat(),
            ]
        )

    result = check_cached_guesses(2025, 1, 1, "600", 600)

    assert result.status is SubmissionStatus.WAIT
    assert result.retry_at is not None
    assert result.retry_at > now + timedelta(minutes=1)


def test_expired_server_retry_deadline_does_not_block(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    cache_file = get_cache_guess_file(2025, 1)
    now = datetime.now(UTC)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with cache_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "part", "guess", "status", "retry_at"])
        writer.writerow(
            [
                now.isoformat(),
                "1",
                "500",
                "WAIT",
                (now - timedelta(seconds=1)).isoformat(),
            ]
        )

    result = check_cached_guesses(2025, 1, 1, "600", 600)

    assert result.status is SubmissionStatus.UNKNOWN


def test_writing_upgrades_legacy_guess_csv_without_losing_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    cache_file = get_cache_guess_file(2025, 1)
    _write_guess_csv(
        cache_file,
        [(datetime.now(UTC).isoformat(), "1", "41", "INCORRECT")],
    )

    retry_at = datetime.now(UTC) + timedelta(minutes=3)
    write_guess_cache(2025, 1, 1, 42, SubmissionStatus.WAIT, retry_at=retry_at)

    with cache_file.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert [row["guess"] for row in rows] == ["41", "42"]
    assert rows[0]["retry_at"] == ""
    assert datetime.fromisoformat(rows[1]["retry_at"]) == retry_at


def test_writing_refuses_to_overwrite_malformed_guess_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    cache_file = get_cache_guess_file(2025, 1)
    cache_file.parent.mkdir(parents=True)
    original = "unexpected,columns\nkeep,this\n"
    cache_file.write_text(original, encoding="utf-8")

    with pytest.raises(RuntimeError, match="malformed header"):
        write_guess_cache(2025, 1, 1, 42, SubmissionStatus.INCORRECT)

    assert cache_file.read_text(encoding="utf-8") == original


def test_check_cached_guesses_short_circuits_completed(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    cache_file = get_cache_guess_file(2025, 2)

    _write_guess_csv(
        cache_file,
        [
            (
                datetime.now(UTC).isoformat(),
                "1",
                "123",
                "COMPLETED",
            ),
        ],
    )

    result = check_cached_guesses(
        year=2025,
        day=2,
        level=1,
        answer="999",
        numeric_answer=999,
    )

    assert result.status == SubmissionStatus.COMPLETED


def test_check_cached_guesses_infers_bounds(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    cache_file = get_cache_guess_file(2025, 3)

    _write_guess_csv(
        cache_file,
        [
            (
                datetime.now(UTC).isoformat(),
                "1",
                "40",
                "TOO_LOW",
            ),
            (
                (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "1",
                "100",
                "TOO_HIGH",
            ),
        ],
    )

    low_result = check_cached_guesses(
        year=2025,
        day=3,
        level=1,
        answer="20",
        numeric_answer=20,
    )
    assert low_result.status == SubmissionStatus.TOO_LOW
    assert low_result.previous_guess == 40

    high_result = check_cached_guesses(
        year=2025,
        day=3,
        level=1,
        answer="250",
        numeric_answer=250,
    )
    assert high_result.status == SubmissionStatus.TOO_HIGH
    assert high_result.previous_guess == 100
