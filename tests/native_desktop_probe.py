"""CI-only production-image probe: native window, RFB resizing, and text scale."""

import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

from camoufox.sync_api import Camoufox

from app.browser import fit_browser_window
from app.browser_identity import context_options, generate_profile


def exact(stream, count):
    data = bytearray()
    while len(data) < count:
        part = stream.recv(count - len(data))
        if not part:
            raise RuntimeError("Desktop transport closed")
        data.extend(part)
    return bytes(data)


def connect_desktop():
    stream = socket.create_connection(("127.0.0.1", 5900), timeout=10)
    assert exact(stream, 12) == b"RFB 003.008\n"
    stream.sendall(b"RFB 003.008\n")
    assert 1 in exact(stream, exact(stream, 1)[0])
    stream.sendall(b"\x01")
    assert exact(stream, 4) == b"\0" * 4
    stream.sendall(b"\x01")
    init = exact(stream, 24)
    exact(stream, int.from_bytes(init[20:24], "big"))
    stream.sendall(struct.pack(">BBH2i", 2, 0, 2, 0, -308))
    stream.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, 1, 1))
    screen_id = None
    while screen_id is None:
        assert exact(stream, 1) == b"\0"
        _, count = struct.unpack(">BH", exact(stream, 3))
        for _ in range(count):
            x, y, width, height, encoding = struct.unpack(">HHHHi", exact(stream, 12))
            if encoding == -308:
                screens = exact(stream, 4)[0]
                layout = exact(stream, screens * 16)
                screen_id = int.from_bytes(layout[:4], "big")
            elif encoding == 0:
                exact(stream, width * height * (init[4] // 8))
            else:
                raise RuntimeError(f"Unexpected encoding: {encoding}")
    return stream, screen_id


def main():
    with tempfile.TemporaryDirectory(prefix="native-desktop-") as temporary:
        root = Path(temporary)
        env = {**os.environ, "DISPLAY": ":99"}
        processes = []
        log = (root / "display.log").open("w+")
        try:
            processes.append(subprocess.Popen([
                "Xtigervnc", ":99", "-geometry", "1920x1080", "-depth", "24", "-rfbport", "5900",
                "-localhost", "-SecurityTypes", "None", "-AlwaysShared", "-AcceptSetDesktopSize=1", "-nolisten", "tcp",
            ], env=env, stdout=log, stderr=subprocess.STDOUT))
            deadline = time.monotonic() + 15
            while not Path("/tmp/.X11-unix/X99").exists():
                assert time.monotonic() < deadline
                time.sleep(0.1)
            processes.append(subprocess.Popen(["openbox", "--sm-disable"], env=env, stdout=log, stderr=subprocess.STDOUT))
            while b"window id" not in subprocess.run(["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"], env=env, capture_output=True).stdout:
                assert time.monotonic() < deadline
                time.sleep(0.1)
            with Camoufox(
                user_data_dir=str(root / "synthetic-profile"), persistent_context=True,
                headless=False, os="windows", env=env,
                **context_options(generate_profile(), native_window=True),
            ) as context:
                page = context.new_page()
                page.set_content('<p style="font:16px sans-serif">Synthetic native text</p>')
                fit_browser_window(context, page)
                stream, screen_id = connect_desktop()
                with stream:
                    for width, height in ((1100, 820), (1400, 700), (900, 1000)):
                        stream.sendall(struct.pack(">BBHHBBIHHHHI", 251, 0, width, height, 1, 0, screen_id, 0, 0, width, height, 0))
                        page.wait_for_function("""size => screen.width === size.width && screen.height === size.height
                            && Math.abs(outerWidth-size.width) <= 1 && Math.abs(outerHeight-size.height) <= 1""",
                            arg={"width": width, "height": height}, timeout=15000)
                        assert page.locator("p").evaluate("e => getComputedStyle(e).fontSize") == "16px"
                        assert page.evaluate("devicePixelRatio") == 1
                        print(f"Production native desktop {width}x{height}: browser fits, font 16px, DPR 1", flush=True)
        except BaseException:
            log.flush()
            print((root / "display.log").read_text(), flush=True)
            raise
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    main()
