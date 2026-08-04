#!/usr/bin/env python3
"""Rasterise the Energy IQ brand assets.

The SVG sources in this directory are authoritative. This script produces the
PNG variants that some consumers cannot take as SVG — notably the GitHub social
preview, which only accepts PNG/JPG/GIF, and the favicon sizes.

Run from the repository root::

    backend/venv/bin/python3 assets/branding/generate_raster.py

Everything is drawn at 4x and downsampled, because Pillow's drawing primitives
are not antialiased. Requires only Pillow and the DejaVu fonts.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - dependency guard
    sys.exit("Pillow is required: backend/venv/bin/python3 -m pip install Pillow")

HERE = Path(__file__).resolve().parent

SS = 4  # supersampling factor

# ── Palette (keep in step with assets/branding/palette.md) ───────────────────
BLUE = (59, 130, 246)
BLUE_DEEP = (29, 78, 216)
BLUE_PALE = (191, 219, 254)
BLUE_TEXT = (147, 197, 253)
AMBER = (245, 158, 11)
AMBER_TEXT = (252, 211, 77)
INK = (11, 17, 32)
INK_MID = (17, 28, 51)
SLATE_100 = (241, 245, 249)
SLATE_300 = (203, 213, 225)
SLATE_400 = (148, 163, 184)
SLATE_500 = (100, 116, 139)
WHITE = (255, 255, 255)

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"
BOOK = FONT_DIR / "DejaVuSans.ttf"


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size * SS)


def linear_gradient(size: tuple[int, int], start, end, diagonal: bool = True) -> Image.Image:
    """A two-stop linear gradient, top-left to bottom-right or top to bottom."""
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = ((x / max(w - 1, 1)) + (y / max(h - 1, 1))) / 2 if diagonal else y / max(h - 1, 1)
            px[x, y] = tuple(int(s + (e - s) * t) for s, e in zip(start, end))
    return img


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius, fill=255)
    return mask


def bolt(scale: float, offset: tuple[float, float] = (0, 0)) -> list[tuple[float, float]]:
    """The mark's lightning bolt, in the 96-unit design grid."""
    pts = [(56, 16), (32, 52), (46, 52), (40, 80), (66, 42), (51, 42)]
    ox, oy = offset
    return [(x * scale + ox, y * scale + oy) for x, y in pts]


def trace(scale: float, offset: tuple[float, float] = (0, 0)) -> list[tuple[float, float]]:
    """The measurement trace under the bolt."""
    pts = [(14, 66), (26, 66), (32, 52), (38, 74), (44, 60), (50, 60)]
    ox, oy = offset
    return [(x * scale + ox, y * scale + oy) for x, y in pts]


def draw_mark(px: int, with_trace: bool = True) -> Image.Image:
    """The square app mark at `px` logical pixels."""
    s = px * SS
    scale = s / 96

    tile = linear_gradient((s, s), BLUE, BLUE_DEEP)
    tile.putalpha(rounded_mask((s, s), int(24 * scale)))

    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if with_trace:
        d.line(trace(scale), fill=BLUE_PALE + (140,), width=max(int(3 * scale), 1), joint="curve")
    d.polygon(bolt(scale), fill=WHITE)

    out = Image.alpha_composite(tile, layer)
    return out.resize((px, px), Image.LANCZOS)


def write(img: Image.Image, name: str) -> None:
    path = HERE / name
    img.save(path, optimize=True)
    print(f"  {path.relative_to(HERE.parents[1])}  {img.size[0]}x{img.size[1]}")


def build_marks() -> None:
    print("marks:")
    write(draw_mark(512), "logo-mark-512.png")
    write(draw_mark(256), "logo-mark-256.png")
    # The trace is illegible below ~64 px, so the small icons carry the bolt only.
    write(draw_mark(64, with_trace=False), "favicon-64.png")
    write(draw_mark(32, with_trace=False), "favicon-32.png")
    write(draw_mark(180, with_trace=False), "apple-touch-icon.png")


def load_curve(w: int, h: int) -> list[tuple[float, float]]:
    """A stylised day of campus demand, sampled for polyline drawing.

    Confined to the lower quarter of the canvas so it reads as a ground-line
    motif rather than competing with the wordmark.
    """
    import math

    pts = []
    for i in range(0, w + 1, max(w // 500, 1)):
        t = i / w
        # Overnight base, morning ramp, afternoon peak, evening decay.
        v = (
            0.30
            + 0.42 * math.exp(-((t - 0.46) ** 2) / 0.022)
            + 0.30 * math.exp(-((t - 0.71) ** 2) / 0.013)
            + 0.035 * math.sin(t * 26)
        )
        pts.append((i, h * (0.925 - 0.21 * min(v, 1.0))))
    return pts


def build_social() -> None:
    """1280x640 GitHub social preview."""
    print("social preview:")
    W, H = 1280 * SS, 640 * SS
    img = linear_gradient((W // SS, H // SS), INK, INK_MID, diagonal=True).resize((W, H))
    img = img.convert("RGBA")

    # Translucent furniture goes on its own layer: ImageDraw writes alpha
    # verbatim instead of compositing, so drawing it straight onto `img`
    # punches holes in the background rather than tinting it.
    wash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wash)

    # Measurement grid
    for gy in range(0, H, 80 * SS):
        wd.line([(0, gy), (W, gy)], fill=(255, 255, 255, 12), width=SS)
    for gx in range(0, W, 80 * SS):
        wd.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 12), width=SS)

    # Load curve with an area fill underneath
    curve = load_curve(W, H)
    wd.polygon(curve + [(W, H), (0, H)], fill=BLUE + (30,))
    wd.line(curve, fill=BLUE + (200,), width=3 * SS, joint="curve")

    img = Image.alpha_composite(img, wash)
    d = ImageDraw.Draw(img)

    # Mark
    mark = draw_mark(120).resize((120 * SS, 120 * SS), Image.LANCZOS)
    img.alpha_composite(mark, (96 * SS, 150 * SS))

    f_title = font(BOLD, 76)
    f_sub = font(BOOK, 25)
    f_label = font(BOLD, 14)
    f_stat = font(BOLD, 38)
    f_chip = font(BOLD, 17)

    d.text((248 * SS, 152 * SS), "Energy IQ", font=f_title, fill=SLATE_100)
    d.text((252 * SS, 244 * SS), "Distributed energy monitoring, forecasting", font=f_sub, fill=SLATE_400)
    d.text((252 * SS, 280 * SS), "and alerting for university campuses", font=f_sub, fill=SLATE_400)

    # Capability chips
    chips = [
        ("Raspberry Pi edge", BLUE, BLUE_TEXT),
        ("FastAPI", BLUE, BLUE_TEXT),
        ("React 19", BLUE, BLUE_TEXT),
        ("39 health rules", AMBER, AMBER_TEXT),
    ]
    chip_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chip_layer)
    x = 252 * SS
    placed = []
    for label, accent, text_colour in chips:
        tw = d.textlength(label, font=f_chip)
        cw = int(tw + 34 * SS)
        cd.rounded_rectangle(
            [x, 336 * SS, x + cw, 336 * SS + 40 * SS],
            radius=20 * SS,
            fill=accent + (38,),
            outline=accent + (110,),
            width=SS,
        )
        placed.append((x + 17 * SS, label, text_colour))
        x += cw + 14 * SS
    img = Image.alpha_composite(img, chip_layer)
    d = ImageDraw.Draw(img)
    for cx, label, text_colour in placed:
        d.text((cx, 347 * SS), label, font=f_chip, fill=text_colour)

    # Figures. Keep in step with README.md.
    stats = [("MEASUREMENTS", "255K"), ("EDGE NODES", "3"), ("API ROUTES", "90"), ("HEALTH RULES", "39")]
    sx = 252 * SS
    for label, value in stats:
        d.text((sx, 440 * SS), label, font=f_label, fill=SLATE_500)
        d.text((sx, 462 * SS), value, font=f_stat, fill=SLATE_300)
        sx += 190 * SS

    d.text(
        (252 * SS, 556 * SS),
        "Raspberry Pi  ·  FastAPI  ·  SQLite WAL  ·  React  ·  scikit-learn  ·  systemd",
        font=font(BOOK, 19),
        fill=SLATE_500,
    )

    write(img.convert("RGB").resize((1280, 640), Image.LANCZOS), "social-preview.png")


if __name__ == "__main__":
    build_marks()
    build_social()
    print("\ndone.")
