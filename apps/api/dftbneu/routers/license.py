from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import license as lic

router = APIRouter(tags=["license"])


class ActivateIn(BaseModel):
    code: str
    student_label: str = ""
    student_id: str = ""
    hub_url: str = ""


class HubSettingsIn(BaseModel):
    hub_url: str = ""
    license_required: Optional[bool] = None


class TeacherGateIn(BaseModel):
    teacher_password: str
    student_password: str
    hub_url: str = ""
    session_days: int = 30


@router.get("/license")
async def get_license():
    status = await lic.check_session(allow_offline_grace=True)
    return {"license": lic.public_license_status(), "check": status}


@router.post("/license/activate")
async def activate(body: ActivateIn):
    try:
        data = await lic.activate(
            code=body.code,
            student_label=body.student_label,
            student_id=body.student_id,
            hub=body.hub_url,
        )
        return {"ok": True, "activation": data, "license": lic.public_license_status()}
    except lic.LicenseError as e:
        raise HTTPException(403, str(e))


@router.post("/license/check")
async def check():
    return await lic.check_session(allow_offline_grace=True)


@router.post("/license/clear")
def clear():
    lic.clear_session()
    return {"ok": True, "license": lic.public_license_status()}


@router.post("/license/hub")
def set_hub(body: HubSettingsIn):
    lic.save_hub_settings(hub_url_value=body.hub_url, license_required_value=body.license_required)
    return {"ok": True, "license": lic.public_license_status()}


@router.post("/license/teacher/gate")
async def teacher_set_gate(body: TeacherGateIn):
    try:
        data = await lic.teacher_set_gate(
            teacher_password=body.teacher_password,
            student_password=body.student_password,
            hub=body.hub_url,
            session_days=body.session_days,
        )
        return {"ok": True, "gate": data}
    except lic.LicenseError as e:
        raise HTTPException(403, str(e))


@router.get("/license/teacher/gate")
async def teacher_get_gate(teacher_password: str = "", hub_url: str = ""):
    try:
        data = await lic.teacher_get_gate(teacher_password=teacher_password, hub=hub_url)
        return {"ok": True, "gate": data}
    except lic.LicenseError as e:
        raise HTTPException(403, str(e))
