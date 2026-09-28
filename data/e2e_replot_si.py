# -*- coding: utf-8 -*-
import shutil
import sys
from pathlib import Path

API = Path(r"C:\Users\13919\AppData\Local\Programs\dftb-neu\resources\api")
ENG = Path(r"C:\Users\13919\AppData\Local\Programs\dftb-neu\resources\engines\dftb_agent")
OUT = Path(r"C:\Users\13919\Projects\dftb-neu\data\e2e_nl_demo")
SHOW = Path(r"C:\Users\13919\.cursor\projects\c-Users-13919-Projects-dftb-neu\assets\e2e_plots")
sys.path[:0] = [str(API), str(ENG)]

from dftb_engine.service import DftbEngine

eng = DftbEngine(wsl_distro="Ubuntu")
arts = eng.fetch_artifacts("edu_e2e_si_band")
print("nk", eng.analyze(arts).get("n_kpoints") or (eng.analyze(arts).get("band") or {}).get("nk"))
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
plots = eng.plot(arts, OUT)
SHOW.mkdir(parents=True, exist_ok=True)
for old in SHOW.glob("*.png"):
    old.unlink()
for p in plots:
    (SHOW / p.name).write_bytes(p.read_bytes())
    print("COPIED", p.name, p.stat().st_size)
print("OK")
