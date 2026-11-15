from __future__ import annotations

import os
import re
import time
import warnings
from types import TracebackType
from typing import Self

import httpx

from .constants import VERSION

_user_agent_prefix = f"elf/{VERSION}"
_default_user_agent = "+https://github.com/snally-dev/elf"


def _build_http_client() -> httpx.Client:
    """Create an HTTP client with elf's headers, timeouts, and limits."""
    user_agent = os.getenv("AOC_USER_AGENT")
    if user_agent is not None:
        user_agent = user_agent.replace("\r", "").replace("\n", "").strip()

    if not _validate_user_agent(user_agent):
        if user_agent is None:
            warning = (
                "User-Agent should include an email address. "
                "Please set AOC_USER_AGENT in your environment."
            )
        else:
            warning = (
                "AOC_USER_AGENT is invalid (value hidden). "
                "It should include an email address. "
                "Please set AOC_USER_AGENT in your environment."
            )
        warnings.warn(warning, RuntimeWarning, stacklevel=2)
        user_agent = _default_user_agent

    assert user_agent is not None
    return httpx.Client(
        headers={"User-Agent": _construct_user_agent(user_agent)},
        follow_redirects=True,
        timeout=httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=20.0),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
    )


def _construct_user_agent(user_agent: str) -> str:
    return f"{_user_agent_prefix} ({user_agent})"


def _validate_user_agent(user_agent: str | None) -> bool:
    """
    Very minimal check that the user agent string contains something that
    looks like an email address so Eric Wastl can contact the user.
    """
    return user_agent is not None and re.search(r"[^@]+@[^.]+\..+", user_agent) is not None


class AOCClient:
    def __init__(
        self,
        session_token: str | None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = "https://adventofcode.com"
        self.session_token = session_token
        self._client = http_client if http_client is not None else _build_http_client()
        self._owns_client = http_client is None

    def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        cookies = {"session": self.session_token} if self.session_token else None
        return self._client.get(f"{self.base_url}{path}", params=params, cookies=cookies)

    def _post(self, path: str, data: dict[str, str]) -> httpx.Response:
        cookies = {"session": self.session_token} if self.session_token else None
        return self._client.post(f"{self.base_url}{path}", data=data, cookies=cookies)

    def _get_with_retries(
        self,
        path: str,
        *,
        retries: int = 2,
        backoff: float = 0.5,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """
        Basic retry wrapper for idempotent GETs to smooth over transient network hiccups.
        """
        attempt = 0
        while True:
            try:
                return self._get(path, params=params)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt >= retries:
                    raise
                time.sleep(backoff * (2**attempt))
                attempt += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the internally owned HTTP client."""
        if self._owns_client and not self._client.is_closed:
            self._client.close()

    def fetch_input(self, year: int, day: int) -> httpx.Response:
        """
        Fetch the puzzle input for a specific year and day.
        """
        return self._get_with_retries(f"/{year}/day/{day}/input")

    def submit_answer(self, year: int, day: int, answer: str, part: int) -> httpx.Response:
        """
        Submit an answer for a specific year, day, and part.
        """
        data = {"level": str(part), "answer": answer}
        response = self._post(f"/{year}/day/{day}/answer", data=data)
        return response

    def fetch_leaderboard(
        self, year: int, board_id: int, view_key: str | None = None
    ) -> httpx.Response:
        """
        Fetch a private leaderboard for a specific year.
        If a view_key is provided, it will be included in the request.
        """
        params = {"view_key": view_key} if view_key else None
        response = self._get_with_retries(
            f"/{year}/leaderboard/private/view/{board_id}.json",
            params=params,
        )
        return response

    def fetch_event(self, year: int) -> httpx.Response:
        """
        Fetch general event information for a specific year (html).
        """
        return self._get_with_retries(f"/{year}")
