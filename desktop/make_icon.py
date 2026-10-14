"""Draws game.ico: a little map, like the area maps on the Explore tab.

Standard library only. Run once before build.bat, or after changing the design (the icons are kept in git too).
"""
import struct
import zlib
from pathlib import Path

# 16x16 design, one letter per pixel: . background, # border, then terrain and buildings
DESIGN = """
................
.##############.
.#ggppwwppffhh#.
.#ggppwwppffhh#.
.#ppHHwwppffhh#.
.#ppHHwwHHffpp#.
.#ffppwwHHffpp#.
.#ffppwwwwwwpp#.
.#ffffppppwwpp#.
.#HHffppHHwwdd#.
.#HHffppHHwwdd#.
.#ppppppppwwdd#.
.#hhhhppppwwdd#.
.#hhhhppppwwdd#.
.##############.
................
"""
COLOURS = {
    ".": (0, 0, 0, 0), "#": (24, 32, 28, 255),
    "g": (127, 201, 127, 255), "p": (155, 190, 90, 255), "f": (46, 122, 62, 255),
    "w": (90, 167, 216, 255), "h": (176, 150, 110, 255), "d": (230, 195, 92, 255),
    "H": (255, 255, 255, 255),
}
ROWS = [row for row in DESIGN.strip().splitlines()]


def pixels(size):
    """RGBA rows, top first, scaled up from the 16x16 design."""
    return [[COLOURS[ROWS[y * 16 // size][x * 16 // size]] for x in range(size)] for y in range(size)]


def bmp_entry(size):
    """An icon image in the classic BMP form: 32-bit pixels bottom row first, then an all-clear AND mask."""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    body = b"".join(bytes((b, g, r, a)) for row in reversed(pixels(size)) for r, g, b, a in row)
    mask = b"\0" * (((size + 31) // 32) * 4 * size)
    return header + body + mask


def png_entry(size):
    raw = b"".join(b"\0" + b"".join(bytes(px) for px in row) for row in pixels(size))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


images = [(16, bmp_entry(16)), (32, bmp_entry(32)), (48, bmp_entry(48)), (256, png_entry(256))]
out, offset = [], 6 + 16 * len(images)
directory = struct.pack("<HHH", 0, 1, len(images))
for size, data in images:
    directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
    offset += len(data)
icon = directory + b"".join(data for _, data in images)
here = Path(__file__).parent
(here / "game.ico").write_bytes(icon)
# The packaged app (desktop-app) uses the same picture: the .ico for Windows, a large .png for Linux.
packaged = here.parent / "desktop-app" / "build"
packaged.mkdir(parents=True, exist_ok=True)
(packaged / "icon.ico").write_bytes(icon)
(packaged / "icon.png").write_bytes(png_entry(512))
print("wrote game.ico, desktop-app/build/icon.ico and icon.png")
