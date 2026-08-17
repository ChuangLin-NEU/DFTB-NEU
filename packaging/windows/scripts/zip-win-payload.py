#!/usr/bin/env python3
"""把 win-unpacked 打成 UTF-8 zip，供现代 Setup 内嵌。"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: zip-win-payload.py <win-unpacked-dir> <out.zip>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    if not src.is_dir():
        print(f"missing dir: {src}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            arc = path.relative_to(src).as_posix()
            zf.write(path, arcname=arc)
            count += 1
    print(f"wrote {out} files={count} size_mb={out.stat().st_size / 1024 / 1024:.1f}")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    exes = [n for n in names if n.count("/") == 0 and n.lower().endswith(".exe")]
    if not exes:
        exes = [n for n in names if n.lower().endswith(".exe") and "uninstall" not in n.lower()][:8]
        print("WARN: 根目录无 exe，候选:", exes, file=sys.stderr)
        if not exes:
            return 1
    else:
        print("ok root exes:", ", ".join(exes[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
