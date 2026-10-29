"""Synthetic route timezone checks; no external requests or credentials."""

import httpx
import pytest

from app.route_timezone import GEOLOCATION_URL, MAX_RESPONSE_BYTES, resolve_timezone
from app.routing import RouteError
from app.queue import Cancelled, LeaseLost


def payload():
    return dict(success=True, ip="8.8.8.8", timezone={"id": "America/Los_Angeles"})


def test_timezone_uses_supplied_route_and_caller_ip_mapping():
    requests = []
    def respond(request):
        requests.append(request)
        assert str(request.url) == GEOLOCATION_URL
        assert request.extensions['timeout'] == dict(connect=10, read=5, write=10, pool=10)
        # The provider determines the caller's public address; it is not supplied.
        assert not request.url.query
        assert request.headers['x-synthetic-route'] == 'account-route'
        return httpx.Response(200, json=payload())
    with httpx.Client(transport=httpx.MockTransport(respond), headers={'x-synthetic-route': 'account-route'}) as session:
        assert resolve_timezone(session) == 'America/Los_Angeles'
    assert len(requests) == 1


@pytest.mark.parametrize('data', [
    {'success': False, 'message': 'synthetic provider failure'},
    {'success': True, 'ip': '127.0.0.1', 'timezone': {'id': 'UTC'}},
    {'success': True, 'ip': '10.0.0.2', 'timezone': {'id': 'UTC'}},
    {'success': True, 'ip': '192.0.2.1', 'timezone': {'id': 'UTC'}},
    {'success': True, 'ip': 'ff02::1', 'timezone': {'id': 'UTC'}},
    {'success': True, 'ip': 'not-an-ip', 'timezone': {'id': 'UTC'}},
    {'success': True, 'ip': 134744072, 'timezone': {'id': 'UTC'}},
    {'success': True, 'ip': '8.8.8.8', 'timezone': {'id': 'Invalid/Zone'}},
    {'success': True, 'ip': '8.8.8.8', 'timezone': {'id': '../UTC'}},
    {'success': True, 'ip': '8.8.8.8', 'timezone': {'id': None}},
    {'success': True, 'ip': '8.8.8.8', 'timezone': {}},
    [], None,
])
def test_invalid_provider_data_fails_closed(data):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))) as session:
        with pytest.raises(RouteError, match='^Could not verify account route timezone$'):
            resolve_timezone(session)


@pytest.mark.parametrize('status', [301, 302, 307, 429, 500])
def test_redirect_and_http_error_never_followed(status):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={'location': 'https://redirect.example/'}, json=payload())
    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as session:
        with pytest.raises(RouteError):
            resolve_timezone(session)
    assert len(requests) == 1


@pytest.mark.parametrize('body', [b'{invalid', b'x' * (MAX_RESPONSE_BYTES + 1)])
def test_invalid_or_oversized_body(body):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as session:
        with pytest.raises(RouteError):
            resolve_timezone(session)


@pytest.mark.parametrize('error', [httpx.ReadTimeout, httpx.ConnectError])
def test_route_failure_does_not_expose_sensitive_error(error):
    def respond(request):
        raise error('http://synthetic-user:synthetic-password@proxy.example/', request=request)
    with httpx.Client(transport=httpx.MockTransport(respond)) as session:
        with pytest.raises(RouteError) as raised:
            resolve_timezone(session)
    assert str(raised.value) == 'Could not verify account route timezone'
    assert raised.value.__suppress_context__


def test_socket_route_failure_is_normalized():
    def respond(request):
        raise OSError("synthetic proxy socket failure")
    with httpx.Client(transport=httpx.MockTransport(respond)) as session:
        with pytest.raises(RouteError, match='^Could not verify account route timezone$'):
            resolve_timezone(session)


def test_total_deadline_stops_trickling_response(monkeypatch):
    clock = [0]
    monkeypatch.setattr('app.route_timezone.time.monotonic', lambda: clock[0])
    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(10):
                clock[0] += 4
                yield b' '
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Trickle()))) as session:
        with pytest.raises(RouteError, match='^Could not verify account route timezone$'):
            resolve_timezone(session)
    assert clock[0] == 16


@pytest.mark.parametrize('error', [Cancelled, LeaseLost])
@pytest.mark.parametrize('boundary', [1, 2, 3, 4, 5])
def test_checkpoint_errors_propagate_at_io_boundaries(error, boundary):
    calls = []
    def checkpoint():
        calls.append(True)
        if len(calls) == boundary:
            raise error()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload()))) as session:
        with pytest.raises(error):
            resolve_timezone(session, checkpoint=checkpoint)
    assert len(calls) == boundary
