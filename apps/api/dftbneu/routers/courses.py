from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services import courses as courses_svc

router = APIRouter(tags=["courses"])


@router.get("/courses")
def list_courses():
    return {"courses": courses_svc.list_courses()}


@router.get("/courses/lessons/{lesson_id}")
def get_lesson(lesson_id: str):
    lesson = courses_svc.get_lesson(lesson_id)
    if not lesson:
        raise HTTPException(404, f"未找到课次：{lesson_id}")
    return {"lesson": lesson}


@router.post("/courses/lessons/{lesson_id}/start")
def start_lesson(lesson_id: str):
    data = courses_svc.start_lesson(lesson_id)
    if not data.get("ok"):
        raise HTTPException(404, data.get("message") or "课次不存在")
    return data


@router.post("/courses/lessons/{lesson_id}/recipe")
def run_recipe(lesson_id: str):
    """一键复现：载入结构并生成 HSD 方案。"""
    data = courses_svc.run_lesson_recipe(lesson_id)
    if not data.get("ok"):
        raise HTTPException(404, data.get("message") or "课次不存在")
    return data
