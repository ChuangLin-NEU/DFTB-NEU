from __future__ import annotations

from fastapi import APIRouter

from ..services import deploy as deploy_svc
from ..services import llm
from ..services import license as lic
from ..services import structure_mp
from ..services.secrets import public_settings

router = APIRouter(tags=["status"])


@router.get("/status")
async def status():
    settings_pub = public_settings()
    deploy = deploy_svc.deploy_status()
    # 状态栏用轻量就绪检查，避免每次真实调用 LLM 导致登录后卡住
    llm_probe = llm.readiness()
    license_check = await lic.check_session(allow_offline_grace=True)
    return {
        "service": "dftb-neu",
        "version": "0.1.0",
        "settings": settings_pub,
        "license": lic.public_license_status(),
        "license_check": license_check,
        "llm": {
            "ok": llm_probe.get("ok"),
            "active_provider": llm_probe.get("active_provider"),
            "results": llm_probe.get("results"),
        },
        "materials_project": structure_mp.mp_status(),
        "deploy": {
            "wsl": deploy.get("wsl"),
            "dftb": deploy.get("dftb"),
            "smoke": deploy.get("smoke"),
            "readiness": deploy.get("readiness"),
        },
    }
