from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..services import deploy as deploy_svc

router = APIRouter(tags=["deploy"])


class DeployIn(BaseModel):
    distro: str = ""
    # 前端若已通过 Electron 提权启动过 WSL，可设为 False，避免重复弹出 UAC
    ensure_wsl: bool = True


@router.get("/deploy/status")
def status():
    return deploy_svc.deploy_status()


@router.get("/deploy/wsl")
def wsl():
    return deploy_svc.detect_wsl()


@router.post("/deploy/ensure-wsl")
def ensure_wsl():
    return deploy_svc.ensure_wsl()


@router.post("/deploy/run")
def run(body: Optional[DeployIn] = None):
    body = body or DeployIn()
    return deploy_svc.run_deploy(distro=body.distro, ensure_wsl_first=body.ensure_wsl)
