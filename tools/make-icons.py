"""Render the PNG fallbacks from the same geometry as img/favicon.svg.

No SVG rasteriser is installed, and a Quick Look thumbnail is not a controlled render, so the
shapes are redrawn here from the identical numbers. Supersampled 8x and reduced, which is what
keeps the 2px bar corners from crawling at 48px.
"""
import sys
from PIL import Image, ImageDraw

GROUND = "#14181b"
BARS = [  # x, y, w, h, fill  - the viewBox 0 0 64 64 coordinates from favicon.svg
    (9, 34, 12, 13, "#ffffff"),
    (26, 27, 12, 20, "#ffffff"),
    (43, 20, 12, 27, "#4f9e8a"),
]
BAR_RX = 2
CARD_RX = 12
SS = 8  # supersample factor


def render(size, rounded):
    s = size * SS
    k = s / 64.0
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=CARD_RX * k, fill=GROUND)
    else:
        # apple-touch-icon: full bleed and fully opaque. iOS applies its own mask and a
        # transparent or pre-rounded icon shows the home screen through the corners.
        d.rectangle([0, 0, s - 1, s - 1], fill=GROUND)
    for x, y, w, h, fill in BARS:
        d.rounded_rectangle([x * k, y * k, (x + w) * k - 1, (y + h) * k - 1],
                            radius=BAR_RX * k, fill=fill)
    out = img.resize((size, size), Image.LANCZOS)
    return out.convert("RGB") if not rounded else out


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "img"
    render(48, rounded=True).save("%s/favicon-48.png" % base, optimize=True)
    render(180, rounded=False).save("%s/apple-touch-icon.png" % base, optimize=True)
    print("wrote favicon-48.png and apple-touch-icon.png")
