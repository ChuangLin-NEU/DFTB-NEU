#!/usr/bin/env python3
"""检查各课例 HSD 引用的 SK 在 WSL Ubuntu 是否存在。"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request

BASE = "http://127.0.0.1:8765"
LESSONS = [
    "ssp01_crystal",
    "ssp02_binding",
    "ssp03_phonon",
    "ssp04_band",
    "ssp05_graphene",
    "ssp06_defect",
]


def post(path: str):
    req = urllib.request.Request(
        BASE + path,
        data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def wsl_exists(path: str) -> bool:
    path = path.replace("$HOME", "/home/neu123")
    cmd = [
        "wsl",
        "-d",
        "Ubuntu",
        "-e",
        "bash",
        "-lc",
        f'test -f "{path}" && echo OK || echo NO',
    ]
    out = subprocess.check_output(cmd, text=True, errors="replace").strip().splitlines()[-1]
    return out.strip() == "OK"


def main():
    fails = 0
    for lid in LESSONS:
        d = post(f"/api/courses/lessons/{lid}/recipe")
        hsd = (d.get("preview") or {}).get("hsd_preview") or ""
        sk = (d.get("preview") or {}).get("sk_set")
        m = re.search(r"Prefix\s*=\s*[\"']?([^\"'\s]+)", hsd)
        prefix = (m.group(1) if m else "").rstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        samples = []
        if "Si" in hsd or lid.startswith("ssp0") and lid <= "ssp04_band":
            samples.append(prefix + "Si-Si.skf")
        if "C-" in hsd or "C " in hsd or "graphene" in lid or "defect" in lid:
            samples.append(prefix + "C-C.skf")
        if "H" in hsd and ("3ob" in str(sk) or "mio" in str(sk)):
            samples.append(prefix + "C-H.skf")
        samples = list(dict.fromkeys(samples))
        missing = [p for p in samples if not wsl_exists(p)]
        ok = not missing and bool(samples)
        print(f"{'PASS' if ok else 'FAIL'} {lid} sk={sk} samples={samples} missing={missing}")
        if not ok:
            fails += 1
    print(f"SK SUMMARY fails={fails}/{len(LESSONS)}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
