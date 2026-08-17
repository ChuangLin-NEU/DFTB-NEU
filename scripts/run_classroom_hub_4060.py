"""Start DFTB classroom hub on 4060 (Windows)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(r"D:\dftb-neu")
APPS = ROOT / "apps"
DATA = ROOT / "data" / "classroom"
DATA.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("DFTB_CLASS_HOST", "0.0.0.0")
os.environ.setdefault("DFTB_CLASS_PORT", "8791")
os.environ.setdefault("DFTB_CLASS_DATA", str(DATA))
os.environ.setdefault("DFTB_CLASS_TEACHER_PASSWORD", "zl303@")
os.environ.setdefault("DFTB_CLASS_ADMIN_SECRET", "zl303@")
os.environ.setdefault("DFTB_CLASS_TOKEN_SECRET", "zl303@")

env_file = Path(r"D:\cmats-lab\.env")
if env_file.is_file():
    mapping = {
        "CMATS_DEEPSEEK_API_KEY": "DFTB_CLASS_DEEPSEEK_API_KEY",
        "CMATS_LLM_API_KEY": "DFTB_CLASS_LLM_API_KEY",
        "CMATS_MP_API_KEY": "DFTB_CLASS_MP_API_KEY",
        "CMATS_LLM_PROVIDER": "DFTB_CLASS_LLM_PROVIDER",
        "CMATS_DEEPSEEK_BASE_URL": "DFTB_CLASS_DEEPSEEK_BASE_URL",
        "CMATS_DEEPSEEK_MODEL": "DFTB_CLASS_DEEPSEEK_MODEL",
        "CMATS_LLM_BASE_URL": "DFTB_CLASS_LLM_BASE_URL",
        "CMATS_LLM_MODEL": "DFTB_CLASS_LLM_MODEL",
    }
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        dst = mapping.get(k.strip())
        if dst and v.strip() and dst not in os.environ:
            os.environ[dst] = v.strip()

os.environ.setdefault("DFTB_CLASS_LLM_PROVIDER", "deepseek")

sys.path.insert(0, str(APPS))

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("DFTB_CLASS_HOST", "0.0.0.0")
    port = int(os.environ.get("DFTB_CLASS_PORT", "8791"))
    uvicorn.run("classroom_hub.main:app", host=host, port=port, app_dir=str(APPS))
