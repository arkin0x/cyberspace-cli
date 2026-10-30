"""Test-wide network guard: tests must never touch the network.

Every test runs with socket connects and DNS lookups intercepted:

* Non-loopback hosts are always refused. The test fails with a message naming
  the host, even if the code under test swallows the error, because the
  attempt is recorded and the test is failed again at teardown.
* Loopback TCP (127.0.0.0/8, ::1, "localhost") is refused too, unless the
  test opts in with ``@pytest.mark.allow_loopback``. That marker is for tests
  that run their own server in this process (for example a local HOSAKA) and
  talk to it over 127.0.0.1. It never allows a non-loopback host.
* Unix domain sockets are always allowed (asyncio and friends use them
  internally; they cannot leave the machine).

urllib (the only HTTP client this repo uses) goes through
``socket.create_connection`` and ``socket.socket.connect``, so it is covered;
so is anything else built on the standard socket module (ssl, asyncio,
websockets, requests, httpx).

The guard patches this process only. A test that spawns a real subprocess
which opens sockets is not covered; stub ``subprocess.run`` as the existing
tests do.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, List

import pytest

# pytester runs the guard's own self-test (tests/test_network_guard.py).
pytest_plugins = ["pytester"]

ALLOW_LOOPBACK_MARKER = "allow_loopback"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{ALLOW_LOOPBACK_MARKER}: let this test connect to loopback servers it runs itself "
        "(127.0.0.1, ::1, localhost). Non-loopback hosts stay blocked.",
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item._netguard_call_failed = report.failed  # type: ignore[attr-defined]


def _host_text(host: Any) -> str:
    if isinstance(host, bytes):
        return host.decode("ascii", "replace")
    return str(host)


def _is_loopback_host(host: Any) -> bool:
    text = _host_text(host).strip().strip("[]")
    if text.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    allow_loopback = request.node.get_closest_marker(ALLOW_LOOPBACK_MARKER) is not None
    violations: List[str] = []

    def refuse(what: str, loopback: bool = False) -> None:
        msg = (
            f"Network access blocked in {request.node.nodeid}: {what}. "
            "Tests must never touch the network. Stub the client instead "
            "(for HOSAKA: set cloud_mode to 'off' or patch the HOSAKA client)."
        )
        if loopback:
            msg += f" If this test runs its own local server, mark it @pytest.mark.{ALLOW_LOOPBACK_MARKER}."
        violations.append(msg)
        pytest.fail(msg, pytrace=False)

    def check_host(host: Any, port: Any, how: str) -> None:
        if _is_loopback_host(host):
            if not allow_loopback:
                refuse(f"{how} to loopback host {_host_text(host)}:{port}", loopback=True)
            return
        refuse(f"{how} to non-loopback host {_host_text(host)}:{port}")

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def check_sock_address(sock: socket.socket, address: Any, how: str) -> None:
        if sock.family == getattr(socket, "AF_UNIX", None):
            return
        if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and address:
            check_host(address[0], address[1] if len(address) > 1 else "?", how)
            return
        refuse(f"{how} on socket family {sock.family!r} to {address!r}")

    def guarded_connect(self: socket.socket, address: Any) -> None:
        check_sock_address(self, address, "socket.connect")
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        check_sock_address(self, address, "socket.connect_ex")
        return real_connect_ex(self, address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        host, port = address[0], address[1]
        check_host(host, port, "socket.create_connection")
        return real_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any):
        # A DNS lookup for a real hostname is network traffic on its own.
        if host is not None and not _is_loopback_host(host):
            refuse(f"DNS lookup (getaddrinfo) for non-loopback host {_host_text(host)}:{port}")
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)

    yield

    if violations and not getattr(request.node, "_netguard_call_failed", False):
        # The code under test caught the failure (or the attempt ran in a
        # background thread) and the test went on to pass; fail it here so a
        # network attempt can never pass silently.
        pytest.fail("\n".join(violations), pytrace=False)
