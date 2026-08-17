"""Patch installed teacher app.asar (main.js / preload.js)."""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path

INSTALL = Path(r"C:\Users\13919\AppData\Local\Programs\dftb-neu-teacher")
ASAR = INSTALL / "resources" / "app.asar"
SRC = Path(__file__).resolve().parents[1] / "teacher-electron"


def _align4(n: int) -> int:
    return (n + 3) & ~3


def read_asar(path: Path) -> dict[str, bytes]:
    data = path.read_bytes()
    header_buf_size = struct.unpack_from("<I", data, 4)[0]
    header_buf = data[8 : 8 + header_buf_size]
    str_len = struct.unpack_from("<I", header_buf, 4)[0]
    header = json.loads(header_buf[8 : 8 + str_len].decode("utf-8"))
    base = 8 + header_buf_size
    files: dict[str, bytes] = {}

    def walk(node: dict, prefix: str = "") -> None:
        if "files" in node:
            for name, child in node["files"].items():
                walk(child, f"{prefix}/{name}" if prefix else name)
            return
        if "offset" in node and "size" in node:
            off = base + int(node["offset"])
            size = int(node["size"])
            files[prefix] = data[off : off + size]

    walk(header)
    return files


def integrity_for(content: bytes) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    return {
        "algorithm": "SHA256",
        "hash": digest,
        "blockSize": 4194304,
        "blocks": [digest],
    }


def write_asar(path: Path, files: dict[str, bytes]) -> None:
    root: dict = {"files": {}}
    blobs: list[bytes] = []
    offset = 0
    for name in sorted(files.keys()):
        content = files[name]
        parts = name.split("/")
        cur = root
        for i, part in enumerate(parts):
            fmap = cur.setdefault("files", {})
            if i == len(parts) - 1:
                fmap[part] = {
                    "size": len(content),
                    "offset": str(offset),
                    "integrity": integrity_for(content),
                }
            else:
                cur = fmap.setdefault(part, {"files": {}})
        blobs.append(content)
        offset += len(content)

    header_json = json.dumps(root, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    str_len = len(header_json)
    payload_size = _align4(4 + str_len)
    header_buf = struct.pack("<II", payload_size, str_len) + header_json
    header_buf += b"\0" * (payload_size - (4 + str_len))
    size_buf = struct.pack("<II", 4, len(header_buf))
    path.write_bytes(size_buf + header_buf + b"".join(blobs))


def main() -> None:
    if not ASAR.exists():
        raise SystemExit(f"missing {ASAR}")
    bak = ASAR.with_suffix(".asar.bak-teacher-pwd")
    if not bak.exists():
        shutil.copy2(ASAR, bak)
    files = read_asar(ASAR)
    for name in ("main.js", "preload.js", "package.json"):
        src = SRC / name
        if src.exists() and name in files:
            files[name] = src.read_bytes()
    write_asar(ASAR, files)
    print(f"patched {ASAR}; files={sorted(files)}")


if __name__ == "__main__":
    main()
