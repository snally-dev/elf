import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from elf.cache import atomic_write_text, get_cache_leaderboard_file
from elf.exceptions import LeaderboardFetchError
from elf.leaderboard import LEADERBOARD_CACHE_TTL, get_leaderboard
from elf.models import OutputFormat


def _payload(name: str = "Elf") -> dict:
    return {
        "num_days": 12,
        "event": "2025",
        "day1_ts": 1764565200,
        "owner_id": 1,
        "members": {
            "1": {
                "id": 1,
                "name": name,
                "last_star_ts": 1764565200,
                "stars": 2,
                "local_score": 10,
                "completion_day_level": {},
            }
        },
    }


class _FakeClient:
    calls = 0

    def __init__(self, session_token):
        self.session_token = session_token

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def fetch_leaderboard(self, year, board_id, view_key):
        type(self).calls += 1
        request = httpx.Request("GET", "https://adventofcode.com/test")
        return httpx.Response(200, json=_payload(), request=request)


def test_leaderboard_uses_fresh_persistent_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.leaderboard.AOCClient", _FakeClient)
    _FakeClient.calls = 0

    first = get_leaderboard(2025, "session-a", 42, None, OutputFormat.MODEL)
    second = get_leaderboard(2025, "session-a", 42, None, OutputFormat.JSON)

    assert first.members[1].name == "Elf"
    assert json.loads(second)["members"]["1"]["name"] == "Elf"
    assert _FakeClient.calls == 1


def test_leaderboard_cache_is_scoped_by_account_and_view_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.leaderboard.AOCClient", _FakeClient)
    _FakeClient.calls = 0

    get_leaderboard(2025, "session-a", 42, None)
    get_leaderboard(2025, "session-b", 42, None)
    get_leaderboard(2025, None, 42, "view-key")
    get_leaderboard(2024, "session-a", 42, None)

    assert _FakeClient.calls == 4


def test_fresh_malformed_cache_does_not_trigger_an_early_request(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.leaderboard.AOCClient", _FakeClient)
    _FakeClient.calls = 0
    cache_file = get_cache_leaderboard_file(
        2025,
        42,
        session_token="session-a",
        view_key=None,
    )

    atomic_write_text(cache_file, "not json")
    with pytest.raises(LeaderboardFetchError, match="will not request"):
        get_leaderboard(2025, "session-a", 42, None)
    assert _FakeClient.calls == 0

    stale_time = time.time() - LEADERBOARD_CACHE_TTL.total_seconds() - 1
    os.utime(cache_file, (stale_time, stale_time))
    get_leaderboard(2025, "session-a", 42, None)
    assert _FakeClient.calls == 1


def test_concurrent_leaderboard_reads_share_one_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.leaderboard.AOCClient", _FakeClient)
    _FakeClient.calls = 0

    def read(_index):
        return get_leaderboard(2025, "session-a", 99, None)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(read, range(4)))

    assert all(result.members[1].name == "Elf" for result in results)
    assert _FakeClient.calls == 1
