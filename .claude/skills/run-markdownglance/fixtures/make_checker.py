#!/usr/bin/env python3
"""Write checker.png beside this file: a 160 x 64 green/yellow checkerboard.

Standard library only, so the fixture can be regenerated anywhere.
"""

import os
import struct
import zlib

WIDTH, HEIGHT, CELL = 160, 64, 16
GREEN, YELLOW = (46, 160, 67), (255, 200, 0)


def chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


rows = []
for y in range(HEIGHT):
    row = bytearray([0])
    for x in range(WIDTH):
        row += bytes(GREEN if (x // CELL + y // CELL) % 2 == 0 else YELLOW)
    rows.append(bytes(row))
png = b"\x89PNG\r\n\x1a\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
png += chunk(b"IEND", b"")
with open(os.path.join(os.path.dirname(__file__), "checker.png"), "wb") as handle:
    handle.write(png)
