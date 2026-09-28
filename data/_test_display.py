#!/usr/bin/env python3
"""端到端验证各性质：计算 → 解析 → 出图 → 课堂摘要字段。"""
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
os.environ["PYTHONPATH"] = (
    str(ROOT / "engines" / "dftb_agent") + os.pathsep + str(ROOT / "apps" / "api")
)

from dftb_engine.analysis import analyze_artifacts  # noqa: E402
from dftb_engine.hsd_builder import ensure_parser_version  # noqa: E402
from dftb_engine.inputs import build_inputs_for_kind  # noqa: E402
from dftb_engine.plot_bands_dos import plot_from_artifacts  # noqa: E402

EXAMPLES = [
    {
        "id": "si_band",
        "kind": "dftb_band",
        "structure_file": "si_diamond.poscar",
        "sk_set": "pbc",
        "params": {"prompt": "硅能带 DOS", "want_dos": True},
        "timeout": 300,
        "expect_keys": ["total_energy", "fermi_energy", "band_gap_eV", "n_kpoints"],
        "expect_figs": ["dftb_bands.png", "dftb_dos.png"],
    },
    {
        "id": "graphene_band",
        "kind": "dftb_band",
        "structure_file": "graphene.poscar",
        "sk_set": "3ob",
        "params": {"prompt": "石墨烯能带", "third_order": False, "dimensionality": "2d"},
        "timeout": 240,
        "expect_keys": ["total_energy", "fermi_energy", "n_kpoints"],
        "expect_figs": ["dftb_bands.png"],
    },
    {
        "id": "h2o_opt",
        "kind": "dftb_opt",
        "use_recipes_water": True,
        "params": {"prompt": "水优化", "max_steps": 40},
        "timeout": 180,
        "expect_keys": ["total_energy", "opt_energies_eV"],
        "expect_figs": ["dftb_opt_energy.png"],
        "min_opt_steps": 2,
    },
    {
        "id": "ch4_vib",
        "kind": "dftb_vib",
        "structure_file": "ch4.gen",
        "params": {"prompt": "甲烷振动"},
        "timeout": 300,
        "need_modes": True,
        "expect_keys": ["vibrations", "n_vibrations", "vib_freq_max_cm1"],
        "expect_figs": ["dftb_vibrations.png"],
        "min_vib": 9,
    },
    {
        "id": "nh3_md",
        "kind": "dftb_md",
        "structure_file": "nh3.gen",
        "params": {"prompt": "氨 BOMD", "md_steps": 60, "timestep_fs": 0.5},
        "timeout": 180,
        "expect_keys": ["md_energies_eV", "md_steps", "md_temps_K", "md_temp_mean_K"],
        "expect_figs": ["dftb_md_energy.png"],
        "min_md": 20,
    },
    {
        "id": "casida",
        "kind": "dftb_td",
        "structure_file": "benzene.gen",
        "params": {"prompt": "苯 Casida", "n_excitations": 6},
        "timeout": 240,
        "expect_keys": ["excitations", "n_excitations"],
        "expect_figs": ["dftb_absorption.png"],
        "min_exc": 1,
    },
    {
        "id": "h2co_xtb",
        "kind": "dftb_xtb",
        "structure_file": "h2co.gen",
        "params": {"prompt": "甲醛 xTB", "max_steps": 40},
        "timeout": 180,
        "expect_keys": ["total_energy", "opt_energies_eV"],
        "expect_figs": ["dftb_opt_energy.png"],
        "min_opt_steps": 2,
    },
]


def win_to_wsl(path: Path) -> str:
    win = str(path.resolve())
    if len(win) >= 3 and win[1:3] == ":\\":
        return "/mnt/" + win[0].lower() + win[2:].replace("\\", "/")
    return win.replace("\\", "/")


def wsl_run(job_dir: Path, timeout_s: int, *, need_modes: bool = False) -> tuple[int, str]:
    wsl_path = win_to_wsl(job_dir)
    for name in ("dftb_in.hsd", "modes_in.hsd"):
        p = job_dir / name
        if p.is_file():
            p.write_text(
                p.read_text(encoding="utf-8").replace("$HOME", "/home/neu123"),
                encoding="utf-8",
            )
    modes_cmd = ""
    if need_modes:
        modes_cmd = (
            ' && if [ -f modes_in.hsd ] && [ -f hessian.out ] && command -v modes >/dev/null; then '
            "modes > modes.log 2>&1; echo MODES:$?; fi"
        )
    script = (
        'export PATH="$HOME/.dftb-neu/envs/dftbplus/bin:$PATH"; '
        f'cd "{wsl_path}" && timeout {timeout_s}s dftb+ > dftb.log 2>&1; echo EXIT:$?'
        f"{modes_cmd}"
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
    return code, out


def load_arts(job_dir: Path) -> dict[str, str]:
    names = [
        "detailed.out",
        "dftb.log",
        "band.out",
        "band_meta.json",
        "EXC.DAT",
        "geo.gen",
        "geo_end.gen",
        "POSCAR",
        "modes.log",
        "vibrations.tag",
        "md.out",
        "hessian.out",
        "status",
    ]
    arts: dict[str, str] = {"status": "done"}
    for n in names:
        p = job_dir / n
        if p.is_file():
            arts[n] = p.read_text(encoding="utf-8", errors="replace")
    return arts


def check_one(ex: dict) -> dict:
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
    td = Path(tempfile.mkdtemp(prefix=f"disp_{eid}_", dir=str(ROOT / "data")))
    fig_dir = td / "figures"
    fig_dir.mkdir()
    for name, content in built["files"].items():
        text = content
        if name.endswith(".hsd"):
            text = ensure_parser_version(text, kind)
        (td / name).write_text(text, encoding="utf-8")
    # band_meta for plotting titles / DOS gate
    if built.get("band_meta"):
        (td / "band_meta.json").write_text(
            json.dumps(built["band_meta"], ensure_ascii=False), encoding="utf-8"
        )

    code, _out = wsl_run(td, int(ex.get("timeout") or 180), need_modes=bool(ex.get("need_modes")))
    arts = load_arts(td)
    analysis = analyze_artifacts(arts)
    plots = [p.name for p in plot_from_artifacts(arts, fig_dir, kind=kind)]

    missing_keys = [k for k in ex.get("expect_keys") or [] if analysis.get(k) in (None, "", [], {})]
    missing_figs = [f for f in ex.get("expect_figs") or [] if f not in plots]
    notes: list[str] = []
    if ex.get("min_opt_steps"):
        n = len(analysis.get("opt_energies_eV") or [])
        if n < int(ex["min_opt_steps"]):
            missing_keys.append(f"opt_energies_eV(<{ex['min_opt_steps']})")
            notes.append(f"opt_steps={n}")
    if ex.get("min_vib"):
        n = len(analysis.get("vibrations") or [])
        if n < int(ex["min_vib"]):
            missing_keys.append(f"vibrations(<{ex['min_vib']})")
            notes.append(f"nvib={n}")
    if ex.get("min_md"):
        n = len(analysis.get("md_energies_eV") or [])
        if n < int(ex["min_md"]):
            missing_keys.append(f"md_energies_eV(<{ex['min_md']})")
            notes.append(f"md_steps={n}")
    if ex.get("min_exc"):
        n = len(analysis.get("excitations") or [])
        if n < int(ex["min_exc"]):
            missing_keys.append(f"excitations(<{ex['min_exc']})")
            notes.append(f"nexc={n}")

    # 计算本身失败也记 FAIL
    compute_ok = code == 0 or analysis.get("ok") is True
    if not compute_ok:
        notes.append(f"exit={code}")
        err = [
            ln
            for ln in (arts.get("dftb.log") or "").splitlines()
            if "ERROR" in ln or "Fatal" in ln or "NOT converged" in ln
        ][:4]
        notes.extend(err)

    ok = compute_ok and not missing_keys and not missing_figs
    dt = round(time.time() - t0, 1)
    row = {
        "id": eid,
        "kind": kind,
        "ok": ok,
        "sec": dt,
        "exit": code,
        "plots": plots,
        "missing_keys": missing_keys,
        "missing_figs": missing_figs,
        "notes": notes,
        "summary": {
            "energy": analysis.get("total_energy"),
            "fermi": analysis.get("fermi_energy"),
            "gap": analysis.get("band_gap_eV"),
            "nk": analysis.get("n_kpoints"),
            "opt_steps": len(analysis.get("opt_energies_eV") or []),
            "nvib": analysis.get("n_vibrations"),
            "vib_range": (
                f"{analysis.get('vib_freq_min_cm1'):.1f}-{analysis.get('vib_freq_max_cm1'):.1f}"
                if analysis.get("vib_freq_min_cm1") is not None
                else None
            ),
            "md_steps": analysis.get("md_steps"),
            "tmean": analysis.get("md_temp_mean_K"),
            "nexc": analysis.get("n_excitations"),
        },
        "dir": str(td) if not ok else "",
    }
    if ok:
        shutil.rmtree(td, ignore_errors=True)
    status = "OK" if ok else "FAIL"
    print(
        status,
        eid,
        kind,
        f"{dt}s",
        "plots=",
        plots,
        "summary=",
        {k: v for k, v in row["summary"].items() if v is not None},
    )
    if not ok:
        print("  missing_keys=", missing_keys, "missing_figs=", missing_figs, "notes=", notes)
    return row


def main() -> int:
    rows = [check_one(ex) for ex in EXAMPLES]
    out = ROOT / "data" / "_display_test_results.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    fails = [r for r in rows if not r["ok"]]
    print("--- DISPLAY FAILS", len(fails), "/", len(rows))
    for f in fails:
        print(json.dumps(f, ensure_ascii=False))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
