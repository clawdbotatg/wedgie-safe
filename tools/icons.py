# Makes safe_icons.bin: the main tokens' pictures, 24 and 16 px, in the screen's 16 colors (4 bits a pixel, the
# left pixel in the high bits, as framebuf.GS4_HMSB). Runs on a computer, never on a wedgie.
#   uv run -q --with pillow python3 tools/icons.py <dir of logos: eth usdc usdt wbtc cbbtc dai (.png/.webp)> [preview.png]
# Logos: trustwallet/assets (cbBTC from CoinGecko). Order = safe_icons.NAMES.
import os, sys
from PIL import Image

NAMES = ("eth", "usdc", "usdt", "wbtc", "cbbtc", "dai")
SIZES = (24, 16)
# lcd.PALETTE. Icons use only the slots blockies never tint (safe_blockie._FREE), so a tinted slot can't recolor
# them; KEY (a _FREE slot) is the clear around the circle.
PALETTE = ((0, 0, 0), (26, 27, 26), (60, 60, 60), (90, 91, 90), (120, 123, 120), (148, 149, 150),
           (169, 170, 171), (195, 196, 197), (216, 217, 218), (236, 237, 238), (254, 254, 254),
           (34, 196, 82), (22, 140, 52), (227, 49, 44), (255, 220, 0), (40, 100, 230))
USE = (0, 1, 4, 6, 10, 11, 12, 14, 15)      # no red: orange logos specked with it
KEY = 2


def near(r, g, b):
    return min(USE, key=lambda i: (r - PALETTE[i][0]) ** 2 * 3 + (g - PALETTE[i][1]) ** 2 * 4 + (b - PALETTE[i][2]) ** 2 * 2)


def icon(path, n):
    im = Image.open(path).convert("RGBA").resize((n, n), Image.LANCZOS)
    px = []
    for y in range(n):
        for x in range(n):
            r, g, b, a = im.getpixel((x, y))
            if a < 128:
                px.append(KEY)
            else:
                k = a / 255             # edge pixels: over the page's white
                px.append(near(int(r * k + 255 * (1 - k)), int(g * k + 255 * (1 - k)), int(b * k + 255 * (1 - k))))
    out = bytearray()
    for y in range(n):
        row = px[y * n:(y + 1) * n]
        for x in range(0, n, 2):
            out.append(row[x] << 4 | row[x + 1])
    return bytes(out), px


def main(src, preview=None):
    blob, shots = bytearray(), []
    for name in NAMES:
        path = next(os.path.join(src, name + e) for e in (".png", ".webp") if os.path.exists(os.path.join(src, name + e)))
        for n in SIZES:
            b, px = icon(path, n)
            blob += b
            shots.append((n, px))
    open(os.path.join(os.path.dirname(__file__), "..", "safe_icons.bin"), "wb").write(blob)
    print("safe_icons.bin: %d bytes" % len(blob))
    if preview:                         # each icon 8x up, on white, as the wedgie draws it
        s = 8
        im = Image.new("RGB", (sum(n + 4 for n, _ in shots) * s, 28 * s), (254, 254, 254))
        x0 = 0
        for n, px in shots:
            for i, c in enumerate(px):
                if c != KEY:
                    x, y = i % n, i // n
                    im.paste(PALETTE[c], (x0 + x * s, y * s, x0 + x * s + s, y * s + s))
            x0 += (n + 4) * s
        im.save(preview)


if __name__ == "__main__":
    main(*sys.argv[1:])
