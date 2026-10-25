"""Synthetic RFB streams: WebSocket chunks never establish message boundaries."""

import struct

import pytest

from app.rfb_monitor import InvalidRFB, ReadOnlyRFB


HELLO = b"RFB 003.008\n\x01\x01"
PIXEL_FORMAT = b"\x00\0\0\0" + bytes([32, 24, 0, 1]) + struct.pack(
    ">HHHBBB3x", 255, 255, 255, 16, 8, 0
)
UPDATE = struct.pack(">BBHHHH", 3, 1, 0, 0, 1024, 768)


def ready():
    parser = ReadOnlyRFB()
    assert b"".join(parser.feed(HELLO)) == HELLO
    return parser


def test_fragmented_handshake_configuration_and_framebuffer_request():
    parser = ReadOnlyRFB()
    stream = HELLO + PIXEL_FORMAT + UPDATE
    received = []
    for byte in stream:
        received.extend(parser.feed(bytes([byte])))
    assert b"".join(received) == stream
    assert not parser.buffer


def test_encoding_negotiation_removes_active_extensions():
    parser = ready()
    encodings = (0, 7, -223, -308, -309, -312, -313, -316, 123456)
    packet = struct.pack(">BBH", 2, 0, len(encodings)) + struct.pack(">9i", *encodings)
    assert parser.feed(packet) == [struct.pack(">BBH3i", 2, 0, 3, 0, 7, -223)]


@pytest.mark.parametrize("packet", [
    b"\x04\x01\0\0\0\0\0a",  # KeyEvent
    b"\x05\x01\0\0\0\0",  # PointerEvent
    b"\x06\0\0\0\0\0\0\x04paste",  # ClientCutText
    b"\xfb",  # SetDesktopSize
    b"\x96",  # EnableContinuousUpdates
    b"\xff",  # unknown extension
    b"\xf8\0\0\0\x80\0\0\0\0",  # Fence request
    b"\xf8\0\0\0\0\0\0\0\x41",  # oversized Fence
    b"\x02\0\x01\x01",  # unbounded SetEncodings
    "text",
])
def test_control_messages_fail_closed(packet):
    with pytest.raises(InvalidRFB):
        ready().feed(packet)


def test_valid_prefix_with_input_in_same_chunk_is_not_forwarded():
    with pytest.raises(InvalidRFB):
        ready().feed(UPDATE + b"\x04")


@pytest.mark.parametrize("hello", [b"RFB 003.003\n", b"RFB 003.008\n\x02", b"RFB 003.008\n\x01\0"])
def test_unsupported_handshake_and_exclusive_client_are_rejected(hello):
    with pytest.raises(InvalidRFB):
        ReadOnlyRFB().feed(hello)


def test_bounds_and_passive_fence_reply():
    parser = ready()
    packet = b"\xf8" + b"\0" * 7 + b"\x04ping"
    assert parser.feed(packet[:7]) == []
    assert parser.feed(packet[7:]) == [packet]
    with pytest.raises(InvalidRFB):
        parser.feed(b"x" * 65537)
