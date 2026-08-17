"""Build student app icon: green rounded D+ on transparent background (no white plate)."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"

# Match apps/web login brand-mark
GRAD_TOP = (10, 61, 59)      # #0a3d3b
GRAD_MID = (15, 110, 106)    # #0f6e6a
GRAD_BOT = (42, 107, 90)     # #2a6b5a
TEXT = (244, 250, 248)       # #f4faf8


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _rounded_mask(size: int, radius: float) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        # 160deg-ish: bias slightly toward bottom-right by mixing x
        for x in range(size):
            u = 0.85 * t + 0.15 * (x / max(1, size - 1))
            if u < 0.55:
                c = _lerp(GRAD_TOP, GRAD_MID, u / 0.55)
            else:
                c = _lerp(GRAD_MID, GRAD_BOT, (u - 0.55) / 0.45)
            px[x, y] = c
    return img


def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\times.ttf",
        r"C:\Windows\Fonts\timesbd.ttf",
        r"C:\Windows\Fonts\georgia.ttf",
        r"C:\Windows\Fonts\georgiab.ttf",
        r"C:\Windows\Fonts\seguihis.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_icon(size: int) -> Image.Image:
    # Super-sample then downscale for clean edges
    ss = 4
    canvas = size * ss
    radius = canvas * 0.22
    grad = _gradient(canvas)
    mask = _rounded_mask(canvas, radius)
    base = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    base.paste(grad, (0, 0), mask)

    draw = ImageDraw.Draw(base)
    font = _font(int(canvas * 0.48))
    text = "D+"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (canvas - tw) / 2 - bbox[0]
    y = (canvas - th) / 2 - bbox[1] - canvas * 0.02
    # subtle depth
    draw.text((x + ss, y + ss), text, font=font, fill=(0, 0, 0, 60))
    draw.text((x, y), text, font=font, fill=TEXT + (255,))

    out = base.resize((size, size), Image.Resampling.LANCZOS)
    # ensure exterior fully transparent (kill pale fringe)
    m = _rounded_mask(size, size * 0.22)
    cleaned = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cleaned.paste(out, (0, 0), m)
    return cleaned


def save_ico(path: Path, icons: list[Image.Image]) -> None:
    """Write a multi-size ICO; keep 256 as PNG-compressed entry for alpha."""
    # Pillow keeps alpha best when the primary image is the largest
    ordered = sorted(icons, key=lambda im: im.size[0])
    largest = ordered[-1]
    rest = ordered[:-1]
    largest.save(
        path,
        format="ICO",
        sizes=[(im.width, im.height) for im in ordered],
        append_images=rest,
    )


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    icons = [render_icon(s) for s in sizes]

    ico = BUILD / "icon-student.ico"
    save_ico(ico, icons)
    icons[-1].save(BUILD / "icon-student.png")
    render_icon(512).save(BUILD / "icon-student-512.png")
    icons[-1].save(BUILD / "icon-student-src.png")

    student_ui = ROOT / "installer-ui-student"
    if student_ui.is_dir():
        (student_ui / "icon.ico").write_bytes(ico.read_bytes())
        (student_ui / "icon.png").write_bytes((BUILD / "icon-student.png").read_bytes())

    # verify frames
    probe = Image.open(ico)
    n = getattr(probe, "n_frames", 1)
    im = icons[-1]
    print(
        f"ok {ico} ({ico.stat().st_size} bytes) frames={n} "
        f"corner={im.getpixel((0, 0))} mid={im.getpixel((128, 128))}"
    )


if __name__ == "__main__":
    main()
