from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from ..services import pipeline

router = APIRouter(tags=["chat"])


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    return v if isinstance(v, str) else str(v)


class ChatIn(BaseModel):
    message: str = ""
    project_id: str = ""
    poscar: str = ""
    gen: str = ""
    hsd: str = ""
    confirm_submit: bool = False
    family: str = ""
    kind: str = ""

    @field_validator("message", "project_id", "poscar", "gen", "hsd", "family", "kind", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> str:
        return _as_str(v)


@router.post("/chat")
async def chat(body: ChatIn):
    return await pipeline.handle_chat(
        body.message,
        project_id=body.project_id or None,
        poscar=body.poscar,
        gen=body.gen,
        hsd=body.hsd,
        confirm_submit=body.confirm_submit,
        family_hint=body.family or "",
        kind_hint=body.kind or "",
    )


@router.get("/examples")
def examples():
    return {"examples": pipeline.teaching_examples()}


@router.get("/commands")
def commands():
    return {"commands": pipeline.commands()}


@router.post("/preview")
def preview(body: ChatIn):
    return pipeline.preview_hsd(
        body.message,
        poscar=body.poscar,
        gen=body.gen,
        family_hint=body.family or "",
        kind_hint=body.kind or "",
    )
