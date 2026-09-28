# -*- coding: utf-8 -*-
import json
import shutil
import sys
import tempfile
from pathlib import Path

API = Path(r"C:\Users\13919\AppData\Local\Programs\dftb-neu\resources\api")
ENG = Path(r"C:\Users\13919\AppData\Local\Programs\dftb-neu\resources\engines\dftb_agent")
OUT = Path(r"C:\Users\13919\Projects\dftb-neu\data\e2e_nl_demo")
SHOW = Path(r"C:\Users\13919\.cursor\projects\c-Users-13919-Projects-dftb-neu\assets\e2e_plots")
sys.path[:0] = [str(API), str(ENG)]

from dftb_engine.local_runner import run_wsl
from dftb_engine.service import DftbEngine
from dftbneu.services import pipeline


def main() -> int:
    prompt = "用 DFTB+ 计算硅晶体能带和 DOS"
    print("PROMPT", prompt)
    preview = pipeline.preview_hsd(prompt)
    print(
        "PREVIEW",
        json.dumps(
            {
                "ok": preview.get("ok"),
                "kind": preview.get("kind"),
                "sk": preview.get("sk_set"),
                "mp": preview.get("mp"),
                "klines": "Klines" in (preview.get("hsd_preview") or ""),
            },
            ensure_ascii=False,
        ),
    )
    if not preview.get("ok"):
        print("FAIL", preview.get("message"))
        return 2

    files = preview.get("files") or {}
    td = Path(tempfile.mkdtemp(prefix="dftb_si_"))
    for name, content in files.items():
        text = content.replace("$HOME/.cmats", "$HOME/.dftb-neu")
        (td / name).write_text(text, encoding="utf-8")

    r = run_wsl(f"wslpath -a '{td.as_posix()}'", timeout=30, distro="Ubuntu")
    # On Windows, Path may be C:\...; wslpath needs Windows form
    r = run_wsl(f"wslpath -a {json.dumps(str(td))}", timeout=30, distro="Ubuntu")
    print("WSLPATH_RC", r.returncode, "OUT", (r.stdout or "").strip(), "ERR", (r.stderr or "")[:200])
    wsl_src = (r.stdout or "").strip().splitlines()[-1] if (r.stdout or "").strip() else ""
    if not wsl_src.startswith("/"):
        # fallback: /mnt/c/...
        drive = td.drive.replace(":", "").lower()
        rest = td.as_posix().split(":/", 1)[-1] if ":/" in td.as_posix() else str(td).replace("\\", "/")[2:]
        if td.drive:
            wsl_src = f"/mnt/{td.drive[0].lower()}/{td.as_posix().split(':/')[-1] if ':/' in td.as_posix() else Path(*td.parts[1:]).as_posix()}"
        print("FALLBACK_SRC", wsl_src)

    job_id = "edu_e2e_si_band"
    launch = f"""
set -e
JD="$HOME/.dftb-neu/jobs/{job_id}"
rm -rf "$JD"
mkdir -p "$JD"
cp -a "{wsl_src}/." "$JD/"
if [ -f "$JD/dftb_in.hsd" ]; then sed -i "s|\\$HOME|$HOME|g" "$JD/dftb_in.hsd" || true; fi
export PATH="$HOME/.dftb-neu/envs/dftbplus/bin:$HOME/.dftb-neu/bin:$PATH"
cd "$JD"
echo running > status
dftb+ > dftb.log 2>&1
rc=$?
if [ $rc -eq 0 ]; then echo done > status; else echo error > status; fi
echo EXIT=$rc
echo '--- LOG TAIL ---'
tail -n 60 dftb.log
echo '--- FILES ---'
ls -la band.out band_meta.json detailed.out 2>&1 | head
"""
    print("RUNNING...")
    r2 = run_wsl(launch, timeout=600, distro="Ubuntu")
    print("RC", r2.returncode)
    print((r2.stdout or "")[-3500:])
    if r2.stderr:
        print("ERR", r2.stderr[-800:])
    if "EXIT=0" not in (r2.stdout or ""):
        return 3

    eng = DftbEngine(wsl_distro="Ubuntu")
    arts = eng.fetch_artifacts(job_id)
    print("ARTIFACTS", sorted(arts.keys()))
    analysis = eng.analyze(arts)
    print(
        "ANALYSIS",
        json.dumps(
            {
                "ok": analysis.get("ok"),
                "E": analysis.get("total_energy"),
                "Ef": analysis.get("fermi_energy"),
                "nk": (analysis.get("band") or {}).get("nk"),
            },
            ensure_ascii=False,
        ),
    )

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    plots = eng.plot(arts, OUT)
    print("PLOTS", [p.name for p in plots])
    SHOW.mkdir(parents=True, exist_ok=True)
    for old in SHOW.glob("*.png"):
        old.unlink()
    for p in plots:
        target = SHOW / p.name
        target.write_bytes(p.read_bytes())
        print("COPIED", target, target.stat().st_size)
    if not any(p.name in ("dftb_bands.png", "dftb_dos.png") for p in plots):
        print("MISSING_BAND_OR_DOS")
        return 5
    print("E2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
