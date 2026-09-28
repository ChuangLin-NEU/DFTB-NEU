#!/usr/bin/env python3
"""逐个生成并（经 WSL）运行课堂示例，确认能出结果。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(r"C:\Users\13919\Projects\dftb-neu")
STRUCT = ROOT / "templates" / "courses" / "structures"
os.environ["PYTHONPATH"] = str(ROOT / "engines" / "dftb_agent")

from dftb_engine.hsd_builder import ensure_parser_version  # noqa: E402
from dftb_engine.inputs import build_inputs_for_kind  # noqa: E402

# 与 pipeline.EXAMPLES 保持同步（避免拉取 pydantic）
EXAMPLES = [
    {
        "id": "si_band",
        "kind": "dftb_band",
        "structure_file": "si_diamond.poscar",
        "sk_set": "pbc",
        "params": {"prompt": "用 DFTB+ 计算硅晶体能带和 DOS", "want_dos": True},
    },
    {
        "id": "graphene_band",
        "kind": "dftb_band",
        "structure_file": "graphene.poscar",
        "sk_set": "3ob",
        "params": {"prompt": "用 DFTB+ 计算石墨烯能带结构", "third_order": False, "dimensionality": "2d"},
    },
    {
        "id": "h2o_opt",
        "kind": "dftb_opt",
        "use_recipes_water": True,
        "params": {"prompt": "用 DFTB+ 对水分子做几何优化", "max_steps": 50},
    },
    {
        "id": "ch4_vib",
        "kind": "dftb_vib",
        "structure_file": "ch4.gen",
        "params": {"prompt": "用 DFTB+ 计算甲烷分子（CH4）振动频率"},
    },
    {
        "id": "nh3_md",
        "kind": "dftb_md",
        "structure_file": "nh3.gen",
        "params": {"prompt": "用 DFTB+ 跑氨分子（NH3）短程 BOMD", "md_steps": 80, "timestep_fs": 0.5},
    },
    {
        "id": "casida",
        "kind": "dftb_td",
        "structure_file": "benzene.gen",
        "params": {"prompt": "用 DFTB+ Casida 线性响应计算苯分子（C6H6）吸收光谱", "n_excitations": 6},
    },
    {
        "id": "h2co_xtb",
        "kind": "dftb_xtb",
        "structure_file": "h2co.gen",
        "params": {"prompt": "用 DFTB+ 内置 GFN2-xTB 优化甲醛分子（H2CO）", "max_steps": 50},
    },
]


def win_to_wsl(path: Path) -> str:
    win = str(path.resolve())
    if len(win) >= 3 and win[1:3] == ":\\":
        return "/mnt/" + win[0].lower() + win[2:].replace("\\", "/")
    return win.replace("\\", "/")


def wsl_run_dftb(job_dir: Path, timeout_s: int) -> tuple[int, str]:
    wsl_path = win_to_wsl(job_dir)
    # 在 Windows 侧先把 $HOME 换成已知课堂家目录，避免 WSL heredoc 转义问题
    hsd = job_dir / "dftb_in.hsd"
    hsd.write_text(
        hsd.read_text(encoding="utf-8").replace("$HOME", "/home/neu123"),
        encoding="utf-8",
    )
    script = (
        'export PATH="$HOME/.dftb-neu/envs/dftbplus/bin:$PATH"; '
        f'cd "{wsl_path}" && timeout {timeout_s}s dftb+ > run.log 2>&1; echo EXIT:$?'
    )
    r = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "-e", "bash", "-lc", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    code = 1
    for ln in out.splitlines():
        if ln.startswith("EXIT:"):
            try:
                code = int(ln.split(":", 1)[1])
            except Exception:
                code = 1
    try:
        log = (job_dir / "run.log").read_text(encoding="utf-8", errors="replace")
    except Exception:
        log = out
    return code, log


def main() -> int:
    results = []
    for ex in EXAMPLES:
        eid = ex["id"]
        kind = ex["kind"]
        t0 = time.time()
        poscar = ""
        gen = ""
        sf = ex.get("structure_file") or ""
        if sf:
            raw = (STRUCT / sf).read_text(encoding="utf-8")
            if sf.endswith(".gen"):
                gen = raw
            else:
                poscar = raw
        built = build_inputs_for_kind(
            kind,
            poscar=poscar,
            gen=gen,
            sk_set=ex.get("sk_set") or "",
            params=dict(ex.get("params") or {}),
            use_recipes_water=bool(ex.get("use_recipes_water")),
        )
        td = Path(tempfile.mkdtemp(prefix=f"ex_{eid}_", dir=str(ROOT / "data")))
        for name, content in built["files"].items():
            text = content
            if name.endswith(".hsd"):
                text = ensure_parser_version(text, kind)
            (td / name).write_text(text, encoding="utf-8")
        timeout = 300 if kind in ("dftb_band", "dftb_vib") else 180
        code, log = wsl_run_dftb(td, timeout)
        detailed = ""
        if (td / "detailed.out").exists():
            detailed = (td / "detailed.out").read_text(encoding="utf-8", errors="replace")
        blob = log + "\n" + detailed
        bad = ("ERROR!" in blob and "WARNING!" not in blob) or "NOT converged" in blob
        # 有些 WARNING 后仍成功；以结果文件为准
        ok = (
            "Total energy" in detailed
            or (td / "band.out").exists()
            or (td / "EXC.DAT").exists()
            or (td / "autotest.tag").exists()
            or ("Geometry optimization" in detailed and "Total energy" in detailed)
            or ("MD" in detailed and "Total energy" in detailed)
            or ("Vibrational" in detailed)
            or ("Eigenvalues" in detailed and code == 0)
        )
        if "ERROR!" in blob:
            # 若最后仍写出 Total energy 且无 NOT converged，可算成功
            if "NOT converged" in blob or "missing" in blob.lower() or "Missing child" in blob:
                ok = False
            elif "Total energy" in detailed and code == 0:
                ok = True
                bad = False
        dt = time.time() - t0
        err_lines = [ln for ln in blob.splitlines() if ln.startswith("ERROR") or "NOT converged" in ln][:3]
        status = "OK" if ok and not ("NOT converged" in blob) else "FAIL"
        results.append(
            {
                "id": eid,
                "kind": kind,
                "status": status,
                "sk": built.get("sk_set"),
                "els": built.get("elements"),
                "sec": round(dt, 1),
                "errs": err_lines,
                "dir": str(td),
            }
        )
        print(status, eid, kind, f"{dt:.1f}s", "sk=", built.get("sk_set"), "els=", built.get("elements"))
        if status != "OK":
            print("  ", err_lines or blob[-300:])
        # 成功则清理；失败保留目录便于排查
        if status == "OK":
            shutil.rmtree(td, ignore_errors=True)

    out = ROOT / "data" / "_example_test_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    fails = [r for r in results if r["status"] != "OK"]
    print("--- FAILS", len(fails), "/", len(results))
    for f in fails:
        print(f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
