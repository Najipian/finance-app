"""Render the PWA icons (192 and 512 px PNG) from the same design as favicon.svg.

Run once from web/:  uv run --no-project --with pillow python scripts/make_icons.py
The 512 px icon keeps its drawing inside the central 80 % so it also works as a
maskable icon.
"""

from pathlib import Path

from PIL import Image, ImageDraw

BRAND, WHITE, GOLD = (15, 93, 90), (255, 255, 255), (233, 196, 106)
BARS = [(14, 34, 22, 50, WHITE), (28, 24, 36, 50, WHITE), (42, 14, 50, 50, GOLD)]  # 64-unit grid


def render(size: int, out: Path) -> None:
    image = Image.new("RGB", (size, size), BRAND)
    draw = ImageDraw.Draw(image)
    scale, inset = size * 0.8 / 64, size * 0.1  # safe zone for maskable icons
    for x0, y0, x1, y1, colour in BARS:
        box = [inset + x0 * scale, inset + y0 * scale, inset + x1 * scale, inset + y1 * scale]
        draw.rounded_rectangle(box, radius=2 * scale, fill=colour)
    image.save(out, optimize=True)


if __name__ == "__main__":
    public = Path(__file__).resolve().parents[1] / "public"
    for px in (192, 512):
        render(px, public / f"icon-{px}.png")
        print(f"wrote public/icon-{px}.png")
