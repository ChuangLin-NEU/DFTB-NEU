"""Make teacher app icon: keep lattice artwork, kill white corner triangles (true alpha)."""
from __future__ import annotations

from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
REPO = ROOT.parents[1]


def clear_white_corners(im: Image.Image, thresh: int = 245) -> Image.Image:
    """Flood-fill near-white from the four corners → transparent."""
    rgba = im.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    q: deque[tuple[int, int]] = deque()
    seen = [[False] * h for _ in range(w)]

    def is_white(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        if a < 10:
            return True
        return r >= thresh and g >= thresh and b >= thresh

    for sx, sy in seeds:
        if is_white(sx, sy) and not seen[sx][sy]:
            q.append((sx, sy))
            seen[sx][sy] = True

    while q:
        x, y = q.popleft()
        r, g, b, _a = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[nx][ny] and is_white(nx, ny):
                seen[nx][ny] = True
                q.append((nx, ny))
    return rgba


def render_size(src: Image.Image, size: int) -> Image.Image:
    # 只去白角，不另加更狠的圆角遮罩（避免把原图海军蓝边再切掉一圈）
    base = src.resize((size, size), Image.Resampling.LANCZOS)
    return clear_white_corners(base, thresh=242)


def save_ico(path: Path, icons: list[Image.Image]) -> None:
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
    src_path = BUILD / "icon-src.png"
    if not src_path.is_file():
        src_path = BUILD / "icon.png"
    src = clear_white_corners(Image.open(src_path))

    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    icons = [render_size(src, s) for s in sizes]

    ico = BUILD / "icon-teacher.ico"
    png = BUILD / "icon-teacher.png"
    save_ico(ico, icons)
    icons[-1].save(png)
    render_size(src, 512).save(BUILD / "icon-teacher-512.png")

    # Teacher packaging points at build/icon.ico — keep in sync
    (BUILD / "icon.ico").write_bytes(ico.read_bytes())
    icons[-1].save(BUILD / "icon.png")

    for dest_dir in (ROOT / "installer-ui-teacher", ROOT / "teacher-electron"):
        if dest_dir.is_dir():
            (dest_dir / "icon.ico").write_bytes(ico.read_bytes())
            (dest_dir / "icon.png").write_bytes(png.read_bytes())

    brand = REPO / "apps" / "teacher_web" / "brand-icon.png"
    if brand.parent.is_dir():
        icons[-1].save(brand)

    im = icons[-1]
    print(
        f"ok {ico} ({ico.stat().st_size} bytes) "
        f"corner={im.getpixel((0, 0))} mid={im.getpixel((128, 128))}"
    )


if __name__ == "__main__":
    main()
