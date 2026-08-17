from __future__ import annotations

from fastapi import APIRouter

from dftb_engine.service import DftbEngine

from ..config import load_user_config, settings

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    cfg = load_user_config()
    eng = DftbEngine(wsl_distro=str(cfg.get("wsl_distro") or settings.wsl_distro or ""))
    return eng.get_status(job_id)


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    cfg = load_user_config()
    eng = DftbEngine(wsl_distro=str(cfg.get("wsl_distro") or settings.wsl_distro or ""))
    return eng.cancel_job(job_id)
