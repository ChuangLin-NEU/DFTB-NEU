from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..services import llm
from ..services.secrets import public_settings, save_llm_settings

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    llm_provider: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    mp_api_key: str = ""
    wsl_distro: str = ""


@router.get("/settings")
def get_settings():
    return public_settings()


@router.post("/settings")
async def post_settings(body: SettingsIn):
    out = save_llm_settings(
        api_key=body.api_key,
        base_url=body.base_url,
        model=body.model,
        llm_provider=body.llm_provider,
        llm_api_key=body.llm_api_key,
        llm_base_url=body.llm_base_url,
        llm_model=body.llm_model,
        mp_api_key=body.mp_api_key,
        wsl_distro=body.wsl_distro,
    )
    probe = await llm.probe("all")
    return {"settings": out, "probe": probe}


@router.post("/settings/probe")
async def probe_settings():
    return await llm.probe("all")
