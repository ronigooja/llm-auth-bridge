"""Verify the current account route's public egress timezone without storing IPs."""

import ipaddress
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .routing import RouteError

GEOLOCATION_URL = "https://ipwho.is/"
MAX_RESPONSE_BYTES = 64 * 1024


def resolve_timezone(session: httpx.Client) -> str:
    """Resolve the caller IP using the already configured account HTTP session.

    No proxy hostname lookup, direct client, redirect, or UTC fallback is used.
    All errors use a constant message to keep route credentials and IPs private.
    """
    try:
        with session.stream(
            "GET", GEOLOCATION_URL, timeout=10, follow_redirects=False
        ) as response:
            if response.status_code != 200:
                raise ValueError
            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ValueError
                body.extend(chunk)
        data = json.loads(body)
        if not isinstance(data, dict) or data.get("success") is not True:
            raise ValueError
        if not isinstance(data["ip"], str):
            raise ValueError
        ip = ipaddress.ip_address(data["ip"])
        if not ip.is_global or ip.is_multicast:
            raise ValueError
        timezone = data["timezone"]["id"]
        if not isinstance(timezone, str) or not timezone or len(timezone) > 255:
            raise ValueError
        ZoneInfo(timezone)
        return timezone
    except (
        httpx.HTTPError, ValueError, TypeError, KeyError, RecursionError,
        ZoneInfoNotFoundError,
    ):
        raise RouteError("Could not verify account route timezone") from None
