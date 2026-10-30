"""The network guard in conftest.py does what it says.

The guard runs in a separate pytest process against the real conftest, so a
test that is supposed to be blocked is blocked by the guard itself and not by
this outer run. Targets are RFC 5737 TEST-NET addresses and the reserved
.invalid TLD, so even a broken guard cannot reach a real host.
"""

from pathlib import Path

INNER_TESTS = '''
import socket
import urllib.request

import pytest


def _listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)  # the backlog completes the handshake; no accept needed
    return srv


def test_urllib_to_external_host_fails():
    urllib.request.urlopen("http://netguard-probe.invalid/", timeout=1)


def test_raw_connect_to_external_ip_fails():
    with socket.socket() as s:
        s.settimeout(1)
        s.connect(("192.0.2.1", 80))


def test_swallowed_attempt_still_fails():
    try:
        urllib.request.urlopen("http://netguard-probe.invalid/", timeout=1)
    except BaseException:
        pass


def test_loopback_without_marker_fails():
    srv = _listener()
    with srv, socket.create_connection(srv.getsockname(), timeout=1):
        pass


@pytest.mark.allow_loopback
def test_loopback_with_marker_passes():
    srv = _listener()
    with srv, socket.create_connection(srv.getsockname(), timeout=1):
        pass


@pytest.mark.allow_loopback
def test_marker_does_not_allow_external_hosts():
    with socket.socket() as s:
        s.settimeout(1)
        s.connect_ex(("192.0.2.1", 80))


def test_unix_sockets_pass():
    a, b = socket.socketpair()
    with a, b:
        a.sendall(b"x")
        assert b.recv(1) == b"x"
'''


def test_guard_blocks_network_and_allows_loopback_only_on_opt_in(pytester):
    pytester.makeconftest(Path(__file__).with_name("conftest.py").read_text())
    pytester.makepyfile(test_inner=INNER_TESTS)
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    # The swallowed attempt passes its call phase and fails at teardown.
    result.assert_outcomes(passed=3, failed=4, errors=1)
    out = result.stdout.str()
    assert "non-loopback host netguard-probe.invalid" in out
    assert "non-loopback host 192.0.2.1:80" in out
    assert "test_swallowed_attempt_still_fails" in out
    assert "mark it @pytest.mark.allow_loopback" in out
