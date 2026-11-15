import csv
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from elf.answer import check_cached_guesses, submit_answer, write_guess_cache
from elf.models import SubmissionResult, SubmissionStatus


@pytest.fixture
def cache_dir(monkeypatch, tmp_path):
    path = tmp_path / "cache"
    monkeypatch.setenv("ELF_CACHE_DIR", str(path))
    return path


def test_duplicate_guess_short_circuits(cache_dir):
    write_guess_cache(2025, 1, 1, 42, SubmissionStatus.INCORRECT)

    result = check_cached_guesses(
        year=2025,
        day=1,
        level=1,
        answer=42,
        numeric_answer=42,
    )

    assert result.status is SubmissionStatus.INCORRECT
    assert result.previous_guess == 42
    assert "You already tried" in result.message


def test_wait_cache_prevents_retry(cache_dir):
    write_guess_cache(2025, 1, 1, 7, SubmissionStatus.WAIT)

    result = check_cached_guesses(
        year=2025,
        day=1,
        level=1,
        answer=7,
        numeric_answer=7,
    )

    assert result.status is SubmissionStatus.WAIT
    assert "try again after" in result.message


def test_bounds_inferred_from_cache(cache_dir):
    write_guess_cache(2025, 1, 1, 10, SubmissionStatus.TOO_LOW)
    write_guess_cache(2025, 1, 1, 20, SubmissionStatus.TOO_HIGH)

    result = check_cached_guesses(
        year=2025,
        day=1,
        level=1,
        answer=9,
        numeric_answer=9,
    )

    assert result.status is SubmissionStatus.TOO_LOW
    assert result.previous_guess == 10
    assert "highest low" in result.message


def test_correct_guess_blocks_a_different_answer_for_completed_part(cache_dir):
    write_guess_cache(2025, 1, 1, 42, SubmissionStatus.CORRECT)

    result = check_cached_guesses(
        year=2025,
        day=1,
        level=1,
        answer=43,
        numeric_answer=43,
    )

    assert result.status is SubmissionStatus.COMPLETED
    assert "already completed" in result.message


def test_later_correct_guess_supersedes_older_failure_and_cooldown(cache_dir):
    cache_file = cache_dir / "2025" / "01" / "guesses.csv"
    cache_file.parent.mkdir(parents=True)
    now = datetime.now(UTC)
    with cache_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "part", "guess", "status"])
        writer.writerow([(now - timedelta(seconds=20)).isoformat(), 1, 41, "INCORRECT"])
        writer.writerow([(now - timedelta(seconds=10)).isoformat(), 1, 42, "WAIT"])
        writer.writerow([now.isoformat(), 1, 43, "CORRECT"])

    result = check_cached_guesses(
        year=2025,
        day=1,
        level=1,
        answer=41,
        numeric_answer=41,
    )

    assert result.status is SubmissionStatus.COMPLETED
    assert "already completed" in result.message


def test_submission_guardrails_are_isolated_between_accounts(cache_dir, monkeypatch):
    write_guess_cache(
        2025,
        1,
        1,
        42,
        SubmissionStatus.INCORRECT,
        session_token="account-a",
    )
    submitted = []

    def fake_submit(year, day, level, answer, session_token):
        submitted.append(session_token)
        return "network-result"

    monkeypatch.setattr("elf.answer.submit_to_aoc", fake_submit)

    cached = submit_answer(2025, 1, 1, 42, "account-a")
    fresh = submit_answer(2025, 1, 1, 42, "account-b")

    assert cached.is_cached is True
    assert fresh == "network-result"
    assert submitted == ["account-b"]


def test_concurrent_submissions_are_checked_and_sent_once(cache_dir, monkeypatch):
    submitted = []

    def fake_submit(year, day, level, answer, session_token):
        submitted.append(answer)
        time.sleep(0.02)
        write_guess_cache(
            year,
            day,
            level,
            answer,
            SubmissionStatus.CORRECT,
            session_token=session_token,
        )
        return SubmissionResult(
            guess=answer,
            result=SubmissionStatus.CORRECT,
            message="correct",
            is_correct=True,
            is_cached=False,
        )

    monkeypatch.setattr("elf.answer.submit_to_aoc", fake_submit)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _index: submit_answer(2025, 1, 1, 42, "account"),
                range(4),
            )
        )

    assert submitted == [42]
    assert sum(not result.is_cached for result in results) == 1
