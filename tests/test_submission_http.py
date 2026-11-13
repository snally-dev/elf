from datetime import UTC, datetime, timedelta
from typing import ClassVar

import httpx
import pytest

from elf.answer import submit_to_aoc
from elf.cache import get_cache_guess_file
from elf.exceptions import SubmissionError
from elf.models import SubmissionStatus
from elf.utils import read_guesses


class _FakeSubmissionClient:
    response: ClassVar[httpx.Response | Exception]

    def __init__(self, session_token: str):
        self.session_token = session_token

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def submit_answer(self, year: int, day: int, answer: str, part: int):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _response(status: int, text: str) -> httpx.Response:
    return httpx.Response(
        status,
        text=text,
        request=httpx.Request("POST", "https://adventofcode.com/test"),
    )


def test_correct_submission_is_parsed_and_cached_for_its_account(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.answer.AOCClient", _FakeSubmissionClient)
    _FakeSubmissionClient.response = _response(
        200,
        "<article>That's the right answer! You are one gold star closer.</article>",
    )

    result = submit_to_aoc(2025, 1, 1, "42", "account-a")

    assert result.result is SubmissionStatus.CORRECT
    assert result.is_correct is True
    assert result.is_cached is False
    assert get_cache_guess_file(2025, 1, "account-a").exists()
    assert not get_cache_guess_file(2025, 1, "account-b").exists()


@pytest.mark.parametrize(
    "html",
    [
        "<article>To play, please identify yourself.</article>",
        '<html><form action="/auth/login"><input name="session"></form></html>',
    ],
)
def test_authentication_html_is_rejected_without_caching(monkeypatch, tmp_path, html):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.answer.AOCClient", _FakeSubmissionClient)
    _FakeSubmissionClient.response = _response(200, html)

    with pytest.raises(SubmissionError, match="invalid or expired"):
        submit_to_aoc(2025, 1, 1, "42", "expired")

    assert not get_cache_guess_file(2025, 1, "expired").exists()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_response(500, "server error"), "Server error"),
        (httpx.ReadTimeout("slow response"), "Timed out"),
    ],
)
def test_submission_http_failures_are_wrapped(monkeypatch, response, message):
    monkeypatch.setattr("elf.answer.AOCClient", _FakeSubmissionClient)
    _FakeSubmissionClient.response = response

    with pytest.raises(SubmissionError, match=message):
        submit_to_aoc(2025, 1, 1, "42", "account")


def test_cache_failure_does_not_hide_submission_result(monkeypatch):
    monkeypatch.setattr("elf.answer.AOCClient", _FakeSubmissionClient)
    monkeypatch.setattr(
        "elf.answer.write_guess_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("read-only cache")),
    )
    _FakeSubmissionClient.response = _response(
        200,
        "<article>That's the right answer! You are one gold star closer.</article>",
    )

    with pytest.warns(RuntimeWarning, match="could not update"):
        result = submit_to_aoc(2025, 1, 1, "42", "account")

    assert result.result is SubmissionStatus.CORRECT


def test_wait_response_persists_server_retry_deadline(monkeypatch, tmp_path):
    monkeypatch.setenv("ELF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("elf.answer.AOCClient", _FakeSubmissionClient)
    _FakeSubmissionClient.response = _response(
        200,
        ("<article>You gave an answer too recently. You have 2m 5s left to wait.</article>"),
    )
    before = datetime.now(UTC)

    result = submit_to_aoc(2025, 1, 1, "42", "account")

    assert result.result is SubmissionStatus.WAIT
    assert result.retry_at is not None
    assert (
        before + timedelta(seconds=124)
        <= result.retry_at
        <= datetime.now(UTC) + timedelta(seconds=126)
    )
    assert result.retry_at.strftime("%Y-%m-%d %H:%M:%S UTC") in result.message
    [guess] = read_guesses(2025, 1, session_token="account")
    assert guess.retry_at == result.retry_at
