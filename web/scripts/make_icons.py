"""Render the PWA icons (192 and 512 px PNG) from the same design as favicon.svg.

Run from web/:  uv run --no-project --with pillow python scripts/make_icons.py
The drawing keeps to the central 80 % so the 512 px icon also works as a maskable
icon. Shapes are drawn at 4x and downsampled, which gives smooth anti-aliased edges.
"""

from pathlib import Path

from PIL import Image, ImageDraw

BRAND, WHITE, MINT = (15, 93, 90), (255, 255, 255), (159, 216, 209)
SUPERSAMPLE = 4

# Strokes on the 40-unit grid of favicon.svg: (points, width, colour).
STROKES = [
    ([(9.5, 16), (17.5, 16)], 2.6, MINT),
    ([(9.5, 21), (17.5, 21)], 2.6, MINT),
    ([(9.5, 26), (17.5, 26)], 2.6, MINT),
    ([(20, 21), (23.5, 21)], 2.6, WHITE),
    ([(26.5, 14), (30.5, 12), (30.5, 28)], 2.8, WHITE),
]


def render(size: int, out: Path) -> None:
    big = size * SUPERSAMPLE
    image = Image.new("RGB", (big, big), BRAND)
    draw = ImageDraw.Draw(image)
    scale, inset = big * 0.8 / 40, big * 0.1  # safe zone for maskable icons
    for points, width, colour in STROKES:
        xy = [(inset + x * scale, inset + y * scale) for x, y in points]
        w = width * scale
        draw.line(xy, fill=colour, width=round(w), joint="curve")
        for x, y in (xy[0], xy[-1]):  # round caps
            draw.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=colour)
    image.resize((size, size), Image.Resampling.LANCZOS).save(out, optimize=True)


if __name__ == "__main__":
    public = Path(__file__).resolve().parents[1] / "public"
    for px in (192, 512):
        render(px, public / f"icon-{px}.png")
        print(f"wrote public/icon-{px}.png")
