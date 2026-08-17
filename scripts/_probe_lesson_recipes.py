#!/usr/bin/env python3
"""逐个调用课堂「一键复现」/recipe，检验是否都能生成 HSD。"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "templates" / "courses" / "solid_state_physics.json"
STRUCT = ROOT / "templates" / "courses" / "structures"
BASE = "http://127.0.0.1:8765"


def http_json(method: str, path: str, body: dict | None = None, timeout: float = 120.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"raw": raw[:500]}
        return e.code, payload
    except Exception as e:
        return 0, {"error": str(e)}


def main() -> int:
    course = json.loads(COURSE.read_text(encoding="utf-8"))
    lessons = course.get("lessons") or []
    struct_files = {p.name for p in STRUCT.glob("*")} if STRUCT.is_dir() else set()

    print(f"course={course.get('title')} lessons={len(lessons)}")
    print(f"structure_files={sorted(struct_files)}")

    st, health = http_json("GET", "/api/health", timeout=5)
    print(f"health status={st} body={health}")
    if st != 200:
        print("API 不可用，中止")
        return 2

    st, lic = http_json("GET", "/api/license", timeout=5)
    print(f"license status={st} ok={lic.get('ok')} active={lic.get('active')} msg={lic.get('message') or lic.get('detail')}")

    results = []
    for L in lessons:
        lid = L.get("id")
        title = L.get("title")
        sfile = str(L.get("structure_file") or "")
        needs = bool(L.get("needs_structure"))
        file_ok = (not sfile) or (sfile in struct_files)
        t0 = time.time()
        code, data = http_json("POST", f"/api/courses/lessons/{lid}/recipe", {}, timeout=180)
        dt = time.time() - t0
        preview = data.get("preview") or {}
        hsd = preview.get("hsd_preview") or ""
        mat = preview.get("maturity") or {}
        allow = preview.get("allow_submit")
        if allow is None:
            allow = True
        ok = (
            code == 200
            and bool(data.get("ok"))
            and bool(data.get("recipe_ready"))
            and bool(hsd.strip())
            and allow is not False
        )
        row = {
            "id": lid,
            "index": L.get("index"),
            "title": title,
            "kind": L.get("kind") or preview.get("kind"),
            "structure_file": sfile,
            "file_present": file_ok,
            "needs_structure": needs,
            "http": code,
            "ok_flag": data.get("ok"),
            "recipe_ready": data.get("recipe_ready"),
            "allow_submit": allow,
            "hsd_len": len(hsd),
            "project_id": data.get("project_id"),
            "sk_set": preview.get("sk_set"),
            "maturity": mat.get("label") or mat.get("status"),
            "message": (data.get("message") or preview.get("message") or data.get("detail") or data.get("error") or "")[:180],
            "seconds": round(dt, 2),
            "pass": ok,
        }
        results.append(row)
        mark = "PASS" if ok else "FAIL"
        print(
            f"[{mark}] #{row['index']} {lid} | http={code} recipe={row['recipe_ready']} "
            f"hsd={row['hsd_len']} allow={allow} file={file_ok} {dt:.1f}s | {title}"
        )
        if not ok:
            print(f"       msg: {row['message']}")

    n_ok = sum(1 for r in results if r["pass"])
    n_fail = len(results) - n_ok
    print("=" * 60)
    print(f"SUMMARY: {n_ok}/{len(results)} PASS, {n_fail} FAIL")
    out = ROOT / "scripts" / "_lesson_recipe_probe_result.json"
    out.write_text(json.dumps({"results": results, "pass": n_ok, "fail": n_fail}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
