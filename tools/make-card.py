"""Render img/card.png, the 1200x630 image a link preview shows.

The card is redrawn here rather than screenshotted so it can be regenerated when the title or the
palette changes, and so the text is laid out to fit rather than trusting a viewport. The artwork
is the same gradient, grid, bars and trend line as img/bg-index.svg, at the card's aspect ratio,
and the type is the site's own Plus Jakarta Sans from assets/css/.

    python3 tools/make-card.py

Both text colours are measured against the darkest and the brightest thing they can land on; the
check at the bottom fails the build rather than shipping a card that is hard to read.
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
ROOT = pathlib.Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "css"

GRAD_TOP, GRAD_BOTTOM = (0x19, 0x23, 0x28), (0x0B, 0x0E, 0x0D)
GRID = (0xDE, 0xE3, 0xDF)
ACCENT = (0x2E, 0x6B, 0x5E)
SCRIM = (0x14, 0x18, 0x1B)              # --band, the same colour the page scrim uses
TITLE_FILL = (255, 255, 255)
# What .page-header .project-tagline actually renders: white at opacity 0.88, flattened against
# the band. Not --accent-on-dark, which is for links on the bar and is too dark here - it put the
# subtitle at 5.20:1 where the trend line passes behind it.
SUB_FILL = (0xE5, 0xEA, 0xE9)

TITLE = "AI Agents Field Notes"
SUBTITLE = "Inference tuning, context discipline, and the numbers behind both."

MARGIN = 84
SS = 2                                  # supersample, for clean diagonals on the trend line


def luminance(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def artwork():
    """The bg-index.svg motif at the card's proportions: gradient, grid, bars, trend line."""
    w, h = W * SS, H * SS
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)

    # Diagonal gradient, approximated by interpolating along x+y as the SVG's linearGradient does.
    for y in range(h):
        for_row = y / (h - 1)
        # one row is a horizontal ramp of its own; drawing per-row keeps this to h line ops
        for x_block in range(0, w, 8):
            t = min(1.0, (x_block / (w - 1) + for_row) / 2)
            c = tuple(round(GRAD_TOP[i] + (GRAD_BOTTOM[i] - GRAD_TOP[i]) * t) for i in range(3))
            d.line([(x_block, y), (x_block + 8, y)], fill=c)

    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step_y, step_x = h / 8, w / 12
    for i in range(1, 8):
        gd.line([(0, i * step_y), (w, i * step_y)], fill=GRID + (13,), width=SS)
    for i in range(1, 12):
        gd.line([(i * step_x, 0), (i * step_x, h)], fill=GRID + (13,), width=SS)
    img = Image.alpha_composite(img.convert("RGBA"), grid)

    bars = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bars)
    base = h * 0.94
    for i in range(11):
        bx = w * (0.06 + i * 0.075)
        bh = h * (0.0 + i * 0.026)
        alpha = round((0.10 + i * 0.03) * 255)
        bd.rectangle([bx, base - bh, bx + w * 0.03, base], fill=ACCENT + (alpha,))
    img = Image.alpha_composite(img, bars)

    line = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    pts = []
    for i in range(61):
        t = i / 60
        x = t * w
        # the same flattening rise as the SVG: fast early, level by the right edge
        y = h * (0.86 - 0.52 * (1 - (1 - t) ** 2.2))
        pts.append((x, y))
    ld.line(pts, fill=ACCENT + (217,), width=3 * SS, joint="curve")
    img = Image.alpha_composite(img, line)

    # The same two-stop scrim the title band carries in _includes/head.html: 0.30 down to 0.20 of
    # --band. Without it the trend line runs behind the subtitle and takes it to 3.9:1. It also
    # means the card and the page a reader then lands on are the same picture.
    scrim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for y in range(h):
        a = 0.30 + (0.20 - 0.30) * (y / (h - 1))
        sd.line([(0, y), (w, y)], fill=SCRIM + (round(a * 255),))
    img = Image.alpha_composite(img, scrim)

    return img.convert("RGB").resize((W, H), Image.LANCZOS)


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def fit(draw, text, name, start, max_width):
    """Largest size at which `text` fits `max_width` on one line."""
    size = start
    while size > 12:
        f = font(name, size)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 2
    return font(name, 12)


def main():
    img = artwork()
    d = ImageDraw.Draw(img)
    avail = W - MARGIN * 2

    title_font = fit(d, TITLE, "PlusJakartaSans-Bold.ttf", 96, avail)
    sub_font = fit(d, SUBTITLE, "PlusJakartaSans-Medium.ttf", 38, avail)

    t_box = d.textbbox((0, 0), TITLE, font=title_font)
    s_box = d.textbbox((0, 0), SUBTITLE, font=sub_font)
    gap = 26
    block_h = (t_box[3] - t_box[1]) + gap + (s_box[3] - s_box[1])
    top = (H - block_h) / 2 - 20

    # Sample the ground before any text is drawn on it: measuring afterwards finds the glyphs
    # themselves and reports white against white.
    band = img.crop((MARGIN, max(0, int(top) - 10), W - MARGIN, min(H, int(top + block_h) + 10)))
    brightest = max(band.getdata(), key=luminance)

    d.text((MARGIN, top - t_box[1]), TITLE, font=title_font, fill=TITLE_FILL)
    d.text((MARGIN, top + (t_box[3] - t_box[1]) + gap - s_box[1]), SUBTITLE,
           font=sub_font, fill=SUB_FILL)

    out = ROOT / "img" / "card.png"
    img.save(out, optimize=True)

    worst_title = contrast(TITLE_FILL, brightest)
    worst_sub = contrast(SUB_FILL, brightest)
    print("wrote %s  (%d x %d, %.1f kB)" % (out, img.width, img.height, out.stat().st_size / 1024))
    print("  title %-22s %5.2f:1 on the brightest pixel behind it %s" % (TITLE_FILL, worst_title, brightest))
    print("  subtitle %-19s %5.2f:1" % (SUB_FILL, worst_sub))
    if min(worst_title, worst_sub) < 5.5:
        sys.exit("FAIL: text on the card falls below the site's 5.5:1 floor")
    print("  both clear the site's 5.5:1 floor")


if __name__ == "__main__":
    main()
