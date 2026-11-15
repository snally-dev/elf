import socket

import pytest


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Make accidental HTTP calls fail before they can leave the test process."""

    def blocked(*args, **kwargs):
        pytest.fail("Network access is disabled during tests; mock the HTTP interaction.")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
