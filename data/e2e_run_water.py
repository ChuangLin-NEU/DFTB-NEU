# -*- coding: utf-8 -*-
import base64
import json
import shlex
import sys
import time
from pathlib import Path

API = Path(r"C:\Users\13919\AppData\Local\Programs\dftb-neu\resources\api")
ENG = Path(r"C:\Users\13919\AppData\Local\Programs\dftb-neu\resources\engines\dftb_agent")
OUT = Path(r"C:\Users\13919\Projects\dftb-neu\data\e2e_nl_demo")
sys.path[:0] = [str(API), str(ENG)]

from dftb_engine.local_runner import LocalDftbRunner, env_bin_prefix, run_wsl
from dftb_engine.service import DftbEngine
from dftbneu.services import pipeline


def main() -> int:
    # Diagnose PATH / dftb+
    script = (
        env_bin_prefix()
        + "whoami; echo HOME=$HOME; command -v dftb+; "
        + "dftb+ --version 2>&1 | head -n 4; "
        + 'find "$HOME/.dftb-neu/share/dftb/sk" -name "*.skf" 2>/dev/null | wc -l'
    )
    r = run_wsl(script, timeout=40, distro="Ubuntu")
    print("DIAG_RC", r.returncode)
    print("DIAG_OUT", (r.stdout or "")[:800])
    print("DIAG_ERR", (r.stderr or "")[:400])

    prompt = "用 DFTB+ 对水分子做几何优化"
    print("PROMPT", prompt)
    preview = pipeline.preview_hsd(prompt)
    print(
        "PREVIEW",
        json.dumps(
            {
                "ok": preview.get("ok"),
                "kind": preview.get("kind"),
                "sk": preview.get("sk_set"),
                "water": preview.get("used_default_water"),
            },
            ensure_ascii=False,
        ),
    )
    if not preview.get("ok"):
        print("FAIL_PREVIEW", preview.get("message"))
        return 2

    # Foreground run to capture log
    job_id = "edu_e2e_water"
    files = preview.get("files") or {}
    if not files:
        from dftb_engine.inputs import build_inputs_for_kind

        files = build_inputs_for_kind(
            preview["kind"], use_recipes_water=True, params=preview.get("params") or {}
        )["files"]
    parts = []
    for name, content in files.items():
        text = content.replace("$HOME/.cmats", "$HOME/.dftb-neu")
        b64 = base64.b64encode(text.encode()).decode()
        parts.append(f'echo {shlex.quote(b64)} | base64 -d > "$JD/{name}"')
    writes = "\n".join(parts)
    launch = f"""
set -e
JD="$HOME/.dftb-neu/jobs/{job_id}"
mkdir -p "$JD"
{writes}
if [ -f "$JD/dftb_in.hsd" ]; then sed -i "s|\\$HOME|$HOME|g" "$JD/dftb_in.hsd" || true; fi
export PATH="$HOME/.dftb-neu/envs/dftbplus/bin:$HOME/.dftb-neu/bin:$PATH"
cd "$JD"
echo running > status
dftb+ > dftb.log 2>&1
rc=$?
if [ $rc -eq 0 ]; then echo done > status; else echo error > status; fi
echo EXIT=$rc
echo '--- LOG TAIL ---'
tail -n 40 dftb.log
"""
    print("RUNNING_FOREGROUND...")
    r2 = run_wsl(launch, timeout=240, distro="Ubuntu")
    print("FG_RC", r2.returncode)
    print((r2.stdout or "")[-2500:])
    if r2.stderr:
        print("FG_ERR", r2.stderr[-500:])

    eng = DftbEngine(wsl_distro="Ubuntu")
    arts = eng.fetch_artifacts(job_id)
    print("ARTIFACTS", sorted(arts.keys()))
    analysis = eng.analyze(arts)
    print(
        "ANALYSIS",
        json.dumps(
            {
                "ok": analysis.get("ok"),
                "total_energy": analysis.get("total_energy"),
                "converged": analysis.get("converged"),
                "geo": (analysis.get("detailed") or {}).get("geo_converged"),
            },
            ensure_ascii=False,
        ),
    )
    if OUT.exists():
        import shutil

        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    plots = eng.plot(arts, OUT)
    print("PLOTS", [str(p) for p in plots])
    for p in plots:
        print("PLOT_FILE", p, p.stat().st_size)
    if not plots:
        return 5
    # Also copy into cursor project assets for display
    show = Path(r"C:\Users\13919\.cursor\projects\c-Users-13919-Projects-dftb-neu\assets\e2e_plots")
    show.mkdir(parents=True, exist_ok=True)
    for p in plots:
        target = show / p.name
        target.write_bytes(p.read_bytes())
        print("COPIED", target)
    print("E2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
