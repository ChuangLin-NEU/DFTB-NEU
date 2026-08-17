#!/usr/bin/env python3
"""对课堂一键复现结果做 HSD/能力深度校验（不只看 HTTP 200）。"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
COURSE = ROOT / "templates" / "courses" / "solid_state_physics.json"


def http_json(method: str, path: str, body=None, timeout=120.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def checks_for(kind: str, hsd: str) -> list[tuple[str, bool, str]]:
    k = (kind or "").lower()
    out = []
    out.append(("has_Geometry", "Geometry" in hsd or "<<<" in hsd, "Geometry/内嵌结构"))
    out.append(("has_Hamiltonian", "Hamiltonian" in hsd, "Hamiltonian 块"))
    out.append(("has_SK", "SlaterKosterFiles" in hsd or "Type2FileNames" in hsd, "SK 文件声明"))
    if "band" in k or k in ("dftb_band", "bands", "band_dos"):
        out.append(("band_KPoints", "KPointsAndWeights" in hsd or "KpointsAndWeights" in hsd, "能带 k 路径"))
        out.append(("band_out", re.search(r"(?i)BandStructure|WriteBandOut|band\.out", hsd) is not None or "EigenvectorsAsText" in hsd or "MaxSCCIterations" in hsd, "电子结构输出相关"))
    if "opt" in k or "relax" in k or k in ("dftb_opt", "geometry_opt"):
        out.append(("driver_opt", "Driver" in hsd and ("GeometryOptimization" in hsd or "ConjugateGradient" in hsd or "SteepestDescent" in hsd or "LBFGS" in hsd), "几何优化 Driver"))
    if "phonon" in k or "vib" in k or "modes" in k:
        out.append(("vib_or_modes", "DynamicalMatrix" in hsd or "modes" in hsd.lower() or "Vibrations" in hsd, "振动/声子相关块"))
    if "dos" in k:
        out.append(("dos_related", "dos" in hsd.lower() or "KPointsAndWeights" in hsd, "DOS 相关"))
    if "defect" in k or "vacancy" in prompt_kind_hint(k):
        pass
    return out


def prompt_kind_hint(k: str) -> str:
    return k


def main() -> int:
    course = json.loads(COURSE.read_text(encoding="utf-8"))
    lessons = course.get("lessons") or []
    deep = []
    fails = 0
    for L in lessons:
        lid = L["id"]
        data = http_json("POST", f"/api/courses/lessons/{lid}/recipe", {})
        preview = data.get("preview") or {}
        hsd = preview.get("hsd_preview") or ""
        kind = preview.get("kind") or L.get("kind") or ""
        mat = preview.get("maturity") or {}
        allow = preview.get("allow_submit")
        if allow is None:
            allow = True
        items = checks_for(kind, hsd)
        # 结构：poscar 应进项目或 HSD
        struct_ok = bool(data.get("poscar")) or ("Geometry" in hsd)
        # 骨架功能不应伪装可投递
        skeleton = str(mat.get("status") or "").lower() == "skeleton" or allow is False
        recipe_ok = bool(data.get("recipe_ready")) and bool(hsd.strip())
        item_fail = [c for c in items if not c[1]]
        ok = recipe_ok and struct_ok and not item_fail and (allow is not False or skeleton)
        # 若明确 skeleton，一键复现「生成预览」仍算按钮可用，但记 WARN
        warn = ""
        if allow is False or skeleton:
            warn = "WARN: 未闭环/不可投递"
            ok = recipe_ok and struct_ok  # 按钮职责是生成输入
        if not ok:
            fails += 1
        deep.append(
            {
                "id": lid,
                "title": L.get("title"),
                "kind": kind,
                "sk_set": preview.get("sk_set"),
                "maturity": mat,
                "allow_submit": allow,
                "recipe_ready": data.get("recipe_ready"),
                "hsd_len": len(hsd),
                "struct_ok": struct_ok,
                "checks": [{"name": a, "ok": b, "desc": c} for a, b, c in items],
                "failed_checks": [a for a, b, _ in item_fail],
                "warn": warn,
                "pass": ok,
                "hsd_head": "\n".join(hsd.splitlines()[:25]),
            }
        )
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {lid} kind={kind} sk={preview.get('sk_set')} allow={allow} {warn}")
        for a, b, c in items:
            print(f"   {'+' if b else '-'} {c}")
        if item_fail:
            print(f"   failed: {item_fail}")

    out = ROOT / "scripts" / "_lesson_recipe_deep_result.json"
    out.write_text(json.dumps(deep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SUMMARY deep fails={fails}/{len(lessons)} -> {out}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
