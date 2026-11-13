import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from elf.answer import write_guess_cache
from elf.cache import (
    CacheLockTimeoutError,
    atomic_write_text,
    cache_file_lock,
    get_cache_guess_file,
    get_cache_input_file,
    get_cache_leaderboard_file,
    migrate_legacy_cache_file,
)
from elf.models import SubmissionStatus
from elf.utils import read_guesses


def test_private_cache_paths_are_isolated_without_exposing_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))

    first = get_cache_input_file(2024, 1, "account-one-secret")
    second = get_cache_input_file(2024, 1, "account-two-secret")
    view = get_cache_leaderboard_file(
        2025,
        123,
        session_token=None,
        view_key="private-view-key",
    )

    assert first != second
    assert "account-one-secret" not in str(first)
    assert "account-two-secret" not in str(second)
    assert "private-view-key" not in str(view)


def test_legacy_cache_is_preserved_and_claimed_by_only_one_account(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    legacy = get_cache_guess_file(2024, 2)
    first = get_cache_guess_file(2024, 2, "first-account")
    second = get_cache_guess_file(2024, 2, "second-account")
    atomic_write_text(legacy, "historical guesses")

    assert migrate_legacy_cache_file(legacy, first) is True
    assert migrate_legacy_cache_file(legacy, second) is False

    assert legacy.read_text() == "historical guesses"
    assert first.read_text() == "historical guesses"
    assert not second.exists()


def test_atomic_cache_writes_replace_content_and_use_private_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    path = get_cache_input_file(2024, 3, "account")

    atomic_write_text(path, "first")
    atomic_write_text(path, "second")

    assert path.read_text() == "second"
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_cache_lock_times_out_and_reclaims_stale_leases(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    path = get_cache_input_file(2024, 4, "account")

    with (
        cache_file_lock(path),
        pytest.raises(CacheLockTimeoutError),
        cache_file_lock(path, timeout=0.01, stale_after=60),
    ):
        pass

    lock_file = path.with_name(f".{path.name}.lock")
    lock_file.write_text("abandoned", encoding="utf-8")
    stale_time = lock_file.stat().st_mtime - timedelta(minutes=5).total_seconds()
    os.utime(lock_file, (stale_time, stale_time))

    with cache_file_lock(path, timeout=0.1, stale_after=1):
        assert lock_file.exists()
    assert not lock_file.exists()


def test_concurrent_guess_writes_do_not_lose_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))

    def write(guess: int) -> None:
        write_guess_cache(
            2024,
            5,
            1,
            guess,
            SubmissionStatus.INCORRECT,
            session_token="account",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(20)))

    guesses = read_guesses(2024, 5, session_token="account")
    assert {guess.guess for guess in guesses} == set(range(20))
