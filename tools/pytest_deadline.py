"""Bound each synthetic CI test, including fixture setup and teardown, on Linux."""

import signal

import pytest


TEST_TIMEOUT_SECONDS = 90


def _expired(signum, frame):
    pytest.fail("test exceeded the 90 second CI deadline", pytrace=False)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    previous = signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, TEST_TIMEOUT_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
