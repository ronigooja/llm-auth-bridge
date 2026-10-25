"""Fail-closed RFB client stream filter for the live, read-only account viewer.

The internal x11vnc uses RFB 3.8 with None security. WebSocket messages are
transport chunks, not RFB messages: no partial message is forwarded.
"""

import struct


class InvalidRFB(ValueError):
    pass


class ReadOnlyRFB:
    MAX_BUFFER = 65536
    # Image encodings and passive server notifications only. In particular, do
    # not negotiate continuous updates, clipboard, fence requests or input APIs.
    ENCODINGS = {0, 1, 2, 4, 5, 6, 7, 16, 21, -223, -224, -232, -239, -240, -307}

    def __init__(self):
        self.buffer = bytearray()
        self.stage = 0

    def feed(self, data: bytes) -> list[bytes]:
        if not isinstance(data, bytes) or len(self.buffer) + len(data) > self.MAX_BUFFER:
            raise InvalidRFB("invalid or oversized RFB client stream")
        self.buffer.extend(data)
        output = []
        while self.buffer:
            if self.stage < 3:
                expected = (b"RFB 003.008\n", b"\x01", b"\x01")[self.stage]
                size = len(expected)
                if len(self.buffer) < size:
                    if not expected.startswith(self.buffer):
                        raise InvalidRFB("unsupported RFB handshake")
                    break
                if self.buffer[:size] != expected:
                    raise InvalidRFB("unsupported RFB handshake")
                message = bytes(self.buffer[:size])
                self.stage += 1
            else:
                kind = self.buffer[0]
                if kind == 0:  # SetPixelFormat
                    size = 20
                elif kind == 2:  # SetEncodings
                    if len(self.buffer) < 4:
                        break
                    count = int.from_bytes(self.buffer[2:4], "big")
                    if count > 256:
                        raise InvalidRFB("too many RFB encodings")
                    size = 4 + count * 4
                elif kind == 3:  # FramebufferUpdateRequest
                    size = 10
                elif kind == 248:  # Fence reply, never a request/block operation
                    if len(self.buffer) < 9:
                        break
                    if self.buffer[8] > 64 or any(self.buffer[1:8]):
                        raise InvalidRFB("unsupported RFB fence")
                    size = 9 + self.buffer[8]
                else:
                    raise InvalidRFB("RFB client operation is not read-only")
                if len(self.buffer) < size:
                    break
                message = bytes(self.buffer[:size])
                if kind == 0:
                    bpp, depth, endian, true_color = message[4:8]
                    if (bpp not in (8, 16, 32) or not 0 < depth <= bpp
                            or endian not in (0, 1) or true_color != 1):
                        raise InvalidRFB("unsupported RFB pixel format")
                    maxima = struct.unpack(">HHH", message[8:14])
                    shifts = message[14:17]
                    masks = []
                    for maximum, shift in zip(maxima, shifts):
                        if (not maximum or maximum & (maximum + 1)
                                or shift + maximum.bit_length() > bpp):
                            raise InvalidRFB("invalid RFB color channel")
                        masks.append(maximum << shift)
                    if any(masks[i] & masks[j] for i, j in ((0, 1), (0, 2), (1, 2))):
                        raise InvalidRFB("overlapping RFB color channels")
                elif kind == 2:
                    encodings = [value[0] for value in struct.iter_unpack(">i", message[4:])
                                 if value[0] in self.ENCODINGS]
                    message = struct.pack(">BBH", 2, 0, len(encodings)) + b"".join(
                        struct.pack(">i", value) for value in encodings)
                elif kind == 3 and message[1] not in (0, 1):
                    raise InvalidRFB("invalid RFB framebuffer request")
            del self.buffer[:size]
            output.append(message)
        return output
