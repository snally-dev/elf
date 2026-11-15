from typing import ClassVar

import httpx
import pytest

from elf.cache import atomic_write_text, get_cache_input_file
from elf.exceptions import InputFetchError
from elf.input import get_input


class _FakeInputClient:
    responses: ClassVar[dict[str, httpx.Response]] = {}
    calls: ClassVar[list[str]] = []

    def __init__(self, session_token: str):
        self.session_token = session_token

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def fetch_input(self, year: int, day: int) -> httpx.Response:
        type(self).calls.append(self.session_token)
        return type(self).responses[self.session_token]


def _response(text: str, content_type: str = "text/plain") -> httpx.Response:
    return httpx.Response(
        200,
        text=text,
        headers={"Content-Type": content_type},
        request=httpx.Request("GET", "https://adventofcode.com/test"),
    )


def test_input_cache_isolated_between_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.input.AOCClient", _FakeInputClient)
    _FakeInputClient.calls = []
    _FakeInputClient.responses = {"account-b": _response("input-for-b\n")}
    atomic_write_text(
        get_cache_input_file(2024, 1, "account-a"),
        "input-for-a\n",
    )

    assert get_input(2024, 1, "account-a") == "input-for-a\n"
    assert get_input(2024, 1, "account-b") == "input-for-b\n"
    assert _FakeInputClient.calls == ["account-b"]


def test_login_html_is_never_returned_or_cached_as_input(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.input.AOCClient", _FakeInputClient)
    _FakeInputClient.calls = []
    _FakeInputClient.responses = {
        "expired": _response(
            '<html><a href="/auth/login">Log in</a></html>',
            "text/html",
        )
    }
    cache_file = get_cache_input_file(2024, 1, "expired")
    atomic_write_text(cache_file, "To play, please identify yourself")

    with pytest.raises(InputFetchError, match="invalid or expired"):
        get_input(2024, 1, "expired")

    assert cache_file.read_text() == "To play, please identify yourself"
