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
    preview = pipeline.preview_hsd(prompt)
    print("PREVIEW_OK", preview.get("ok"), preview.get("kind"), preview.get("sk_set"))
    if not preview.get("ok"):
        print(preview.get("message"))
        return 2

    td = Path(tempfile.mkdtemp(prefix="dftb_si_"))
    for name, content in (preview.get("files") or {}).items():
        (td / name).write_text(
            content.replace("$HOME/.cmats", "$HOME/.dftb-neu"), encoding="utf-8"
        )
    wsl_src = "/mnt/" + td.drive[0].lower() + "/" + "/".join(td.parts[1:])
    print("SRC", wsl_src, "exists_win", td.exists())

    job_id = "edu_e2e_si_band"
    # Keep script simple; avoid nested quotes issues
    launch = (
        f"JD=$HOME/.dftb-neu/jobs/{job_id}; "
        f"rm -rf \"$JD\"; mkdir -p \"$JD\"; "
        f"cp -a {wsl_src}/. \"$JD/\"; "
        f"sed -i \"s|\\$HOME|$HOME|g\" \"$JD/dftb_in.hsd\"; "
        f"export PATH=$HOME/.dftb-neu/envs/dftbplus/bin:$PATH; "
        f"cd \"$JD\"; "
        f"echo running > status; "
        f"dftb+ > dftb.log 2>&1; echo EXIT:$?; "
        f"tail -n 80 dftb.log; "
        f"ls -la band.out detailed.out band_meta.json 2>&1"
    )
    print("LAUNCH_LEN", len(launch))
    r = run_wsl(launch, timeout=600, distro="Ubuntu")
    print("RC", r.returncode)
    out = r.stdout or ""
    err = r.stderr or ""
    log_path = Path(r"C:\Users\13919\Projects\dftb-neu\data\e2e_si_wsl.log")
    log_path.write_text(out + "\n---STDERR---\n" + err, encoding="utf-8")
    print("LOG_FILE", log_path, "OUT_LEN", len(out), "ERR_LEN", len(err))
    print("HAS_EXIT0", "EXIT:0" in out)
    if "EXIT:0" not in out:
        # print ascii-safe snippet
        safe = out.encode("ascii", "replace").decode("ascii")
        print("STDOUT_SAFE_TAIL", safe[-1500:])
        return 3

    eng = DftbEngine(wsl_distro="Ubuntu")
    arts = eng.fetch_artifacts(job_id)
    print("ARTIFACTS", sorted(arts.keys()))
    print("BAND_META", (arts.get("band_meta.json") or "")[:200])
    print("BAND_OUT_LINES", len((arts.get("band.out") or "").splitlines()))
    analysis = eng.analyze(arts)
    print(
        "ANALYSIS",
        {
            "ok": analysis.get("ok"),
            "E": analysis.get("total_energy"),
            "Ef": analysis.get("fermi_energy"),
            "nk": (analysis.get("band") or {}).get("nk"),
        },
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
        (SHOW / p.name).write_bytes(p.read_bytes())
        print("COPIED", p.name, p.stat().st_size)
    if not {"dftb_bands.png", "dftb_dos.png"} & {p.name for p in plots}:
        return 5
    print("E2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
