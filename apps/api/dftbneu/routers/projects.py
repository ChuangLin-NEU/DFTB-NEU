from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db
from ..services import manuscript as ms_svc
from ..services import pipeline

router = APIRouter(tags=["projects"])


class CreateIn(BaseModel):
    title: str = "DFTB+ 课题"
    prompt: str = ""


class SubmitIn(BaseModel):
    poscar: str = ""
    gen: str = ""


class PollIn(BaseModel):
    force_replot: bool = False


@router.get("/projects")
def list_projects():
    return {"projects": db.list_projects()}


@router.post("/projects")
def create(body: CreateIn):
    return db.create_project(body.title, idea={"prompt": body.prompt})


@router.get("/projects/{project_id}")
def get_one(project_id: str):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(404, "课题不存在")
    return p


@router.post("/projects/{project_id}/submit")
def submit(project_id: str, body: Optional[SubmitIn] = None):
    body = body or SubmitIn()
    return pipeline.submit_project(project_id, poscar=body.poscar, gen=body.gen)


@router.post("/projects/{project_id}/poll")
def poll(project_id: str, body: Optional[PollIn] = None):
    body = body or PollIn()
    return pipeline.poll_and_finalize(project_id, force_replot=bool(body.force_replot))


@router.post("/projects/{project_id}/cancel")
def cancel(project_id: str):
    data = pipeline.cancel_project(project_id)
    if not data.get("ok"):
        raise HTTPException(400, data.get("message") or "取消失败")
    return data


@router.delete("/projects/{project_id}")
def delete(project_id: str):
    from .. import db as db_mod

    if not db_mod.get_project(project_id):
        raise HTTPException(404, "任务不存在")
    # 尽量先取消进行中的作业
    try:
        pipeline.cancel_project(project_id)
    except Exception:
        pass
    if not db_mod.delete_project(project_id):
        raise HTTPException(500, "删除失败")
    return {"ok": True, "message": "已删除方案"}


@router.post("/projects/{project_id}/manuscript")
def manuscript(project_id: str):
    try:
        return ms_svc.build_manuscript(project_id, use_llm=True)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/projects/{project_id}/export/{fmt}")
def export(project_id: str, fmt: str):
    p = db.project_dir(project_id)
    if fmt == "md":
        path = p / "artifacts" / "manuscript.md"
    elif fmt == "html":
        path = p / "artifacts" / "manuscript.html"
    else:
        raise HTTPException(400, "仅支持 md / html")
    if not path.is_file():
        ms_svc.build_manuscript(project_id, use_llm=False)
    if not path.is_file():
        raise HTTPException(404, "文稿尚未生成")
    return FileResponse(path)
