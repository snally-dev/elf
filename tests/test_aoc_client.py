import os

import httpx
import pytest

from elf.aoc_client import (
    AOCClient,
    _default_user_agent,
    _user_agent_prefix,
    _validate_user_agent,
)


@pytest.fixture
def aoc_client():
    def _make():
        return AOCClient("fake_session")

    return _make


@pytest.mark.parametrize(
    ("aoc_user_agent", "ok"),
    [("", False), ("invalid", False), ("valid@email.com", True)],
)
def test_user_agent_header_validation(monkeypatch, aoc_user_agent, ok):
    monkeypatch.setenv("AOC_USER_AGENT", aoc_user_agent)
    user_agent = os.getenv("AOC_USER_AGENT")
    assert _validate_user_agent(user_agent) == ok


def test_user_agent_set_in_AOCClient(monkeypatch, aoc_client):
    user_agent = "valid@email.com"
    monkeypatch.setenv("AOC_USER_AGENT", user_agent)
    client = aoc_client()
    httpx_client: httpx.Client = client._client
    user_agent_header = httpx_client.headers.get("User-Agent", "")
    assert user_agent in user_agent_header
    assert _user_agent_prefix in user_agent_header
    client.close()


def test_default_user_agent_set_in_AOCClient(monkeypatch, aoc_client):
    # Simulate no AOC_USER_AGENT set in the environment so we hit the default UA path
    monkeypatch.delenv("AOC_USER_AGENT", raising=False)

    with pytest.warns(RuntimeWarning):
        client = aoc_client()

    httpx_client: httpx.Client = client._client
    user_agent_header = httpx_client.headers.get("User-Agent", "")
    assert _default_user_agent in user_agent_header
    assert _user_agent_prefix in user_agent_header
    client.close()


def test_invalid_user_agent_warning_does_not_echo_value(monkeypatch, aoc_client):
    secret = "not-an-email-secret-value"
    monkeypatch.setenv("AOC_USER_AGENT", secret)

    with pytest.warns(RuntimeWarning) as warning_list:
        client = aoc_client()

    assert secret not in str(warning_list[0].message)
    client.close()


def test_context_manager_closes_owned_client(monkeypatch):
    monkeypatch.setenv("AOC_USER_AGENT", "valid@email.com")

    with AOCClient("fake_session") as client:
        assert client._client.is_closed is False

    assert client._client.is_closed is True


def test_injected_http_client_is_not_closed(monkeypatch):
    monkeypatch.setenv("AOC_USER_AGENT", "valid@email.com")
    transport = httpx.Client()

    with AOCClient("fake_session", http_client=transport):
        pass

    assert transport.is_closed is False
    transport.close()
