#!/usr/bin/env python3
"""Fixed remote-image endpoints for the guest's step 6 checks.

The guest reaches the host at 10.0.2.2 over QEMU's user-mode NAT, so these
five URLs give the fetcher one deterministic case each: a good image, a
redirect to it, a response that never arrives in time, something that is not
an image at all, and one whose header declares more pixels than the setting
allows. Nothing here reads the filesystem or takes a path from the request.

    python3 ~/vm/imgserver.py [--port 8100]
"""

import argparse
import struct
import sys
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SLOW_SECONDS = 20


def png(width, height, colours=((0, 160, 80), (240, 210, 40)), block=16):
    """A real, decodable checkerboard PNG."""
    rows = []
    for y in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            row += bytes(colours[((x // block) + (y // block)) % 2])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\x0a"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )


def oversized_header(width=8000, height=8000):
    """A PNG header that declares more pixels than `remote_max_dimension`.

    The whole point is that the fetcher rejects it on the declared size, so
    the body is never decoded and there is no reason to send 64 megapixels.
    """
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\x0a" + struct.pack(">I", len(header)) + b"IHDR" + header


OK = png(160, 64)
HUGE = oversized_header()
JUNK = b"this is not an image, it is a sentence about one\n" * 4


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        print("{}  {}".format(time.strftime("%H:%M:%S"), path))
        sys.stdout.flush()
        if path in ("/", "/ping"):
            return self._send(b"imgserver alive\n", "text/plain")
        if path == "/ok.png":
            return self._send(OK, "image/png")
        if path == "/redirect.png":
            self.send_response(302)
            self.send_header("Location", "/ok.png")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if path == "/slow.png":
            # Longer than any sane `remote_timeout_seconds`; the client gives
            # up first and the socket is closed under us, which is fine.
            time.sleep(SLOW_SECONDS)
            try:
                return self._send(OK, "image/png")
            except OSError:
                return
        if path == "/notimage.png":
            return self._send(JUNK, "image/png")
        if path == "/huge.png":
            return self._send(HUGE, "image/png")
        return self._send(b"no such fixture\n", "text/plain", 404)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    print("imgserver on :{}".format(args.port))
    sys.stdout.flush()
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
