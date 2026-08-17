"""固体物理课次：读取 templates/courses 并预填教学演示上下文。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..config import settings


def _courses_dir() -> Path:
    return settings.root / "templates" / "courses"


def _load_course_file(name: str = "solid_state_physics.json") -> dict[str, Any]:
    path = _courses_dir() / name
    if not path.is_file():
        return {"id": "solid_state_physics", "title": "固体物理课堂演示", "lessons": []}
    return json.loads(path.read_text(encoding="utf-8"))


def list_courses() -> list[dict[str, Any]]:
    course = _load_course_file()
    lessons = course.get("lessons") or []
    return [
        {
            "id": course.get("id"),
            "title": course.get("title"),
            "description": course.get("description"),
            "curriculum_note": course.get("curriculum_note") or "",
            "lesson_count": len(lessons),
            "lessons": [
                {
                    "id": L.get("id"),
                    "index": L.get("index"),
                    "title": L.get("title"),
                    "chapter": L.get("chapter") or "",
                    "topic": L.get("topic"),
                    "knowledge": L.get("knowledge") or "",
                    "objectives": L.get("objectives") or [],
                    "expected_observables": L.get("expected_observables") or [],
                    "quiz": L.get("quiz") or "",
                    "structure_hint": L.get("structure_hint") or "",
                    "needs_structure": bool(L.get("needs_structure")),
                    # 内部字段仍返回，供计算管线；前端不展示
                    "capability_family": L.get("capability_family"),
                    "kind": L.get("kind"),
                }
                for L in lessons
            ],
        }
    ]


def get_lesson(lesson_id: str) -> Optional[dict[str, Any]]:
    course = _load_course_file()
    for L in course.get("lessons") or []:
        if L.get("id") == lesson_id:
            out = dict(L)
            out["course_id"] = course.get("id")
            out["course_title"] = course.get("title")
            return out
    return None


def _read_structure(filename: str) -> str:
    if not filename:
        return ""
    path = _courses_dir() / "structures" / filename
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def start_lesson(lesson_id: str) -> dict[str, Any]:
    """返回课次教学上下文：知识点、prompt、内置结构。"""
    lesson = get_lesson(lesson_id)
    if not lesson:
        return {"ok": False, "message": f"未找到课次：{lesson_id}"}
    poscar = _read_structure(str(lesson.get("structure_file") or ""))
    chapter = lesson.get("chapter") or ""
    title = lesson.get("title") or ""
    msg = f"已载入教学演示「{title}」"
    if chapter:
        msg += f"（{chapter}）"
    msg += "。"
    if poscar:
        msg += " 已填入指令与结构；若要生成 HSD，请点「预览输入文件」，或回课程用「生成输入文件」。"
    elif lesson.get("needs_structure"):
        msg += " 请先准备结构。"
    return {
        "ok": True,
        "lesson": lesson,
        "prompt": lesson.get("prompt") or "",
        "poscar": poscar,
        "gen": "",
        "family": lesson.get("capability_family"),
        "kind": lesson.get("kind"),
        "needs_structure": bool(lesson.get("needs_structure")),
        "structure_ready": bool(poscar) or not lesson.get("needs_structure"),
        "expected_observables": lesson.get("expected_observables") or [],
        "message": msg,
    }


def run_lesson_recipe(lesson_id: str) -> dict[str, Any]:
    """一键复现：载入课次 + 生成 HSD 方案（不自动投递）。"""
    from . import pipeline

    base = start_lesson(lesson_id)
    if not base.get("ok"):
        return base
    if base.get("needs_structure") and not base.get("structure_ready"):
        base["recipe_ready"] = False
        base["message"] = (base.get("message") or "") + " 缺少结构，无法一键生成输入。"
        return base

    prompt = base.get("prompt") or ""
    poscar = base.get("poscar") or ""
    preview = pipeline.preview_hsd(
        prompt,
        poscar=poscar,
        gen="",
        family_hint=str(base.get("family") or ""),
        kind_hint=str(base.get("kind") or ""),
    )
    if preview.get("needs_structure") and not preview.get("ok"):
        base["preview"] = preview
        base["recipe_ready"] = False
        base["message"] = preview.get("message") or "需要结构文件。"
        return base

    from .. import db

    title = (base.get("lesson") or {}).get("title") or prompt[:40] or "课例复现"
    proj = db.create_project(title=title, idea={"prompt": prompt})
    hsd_text = preview.get("hsd_preview") or ""
    protocol = {
        "dftb_family": preview.get("family"),
        "kind": preview.get("kind"),
        "sk_set": preview.get("sk_set"),
        "prompt": prompt,
        "hsd_preview": hsd_text,
        "hsd_default": hsd_text,
        "playbook_id": (preview.get("playbook") or {}).get("playbook_id"),
        "success_criteria": (preview.get("playbook") or {}).get("success_criteria") or [],
        "expected_observables": base.get("expected_observables") or [],
        "lesson_id": lesson_id,
        "param_tips": pipeline._param_tips(preview.get("kind") or "", preview.get("sk_set") or ""),
    }
    structure: dict = {}
    if poscar:
        structure["poscar"] = poscar
    if preview.get("mp"):
        structure["mp"] = preview["mp"]
    mp_id = (base.get("lesson") or {}).get("mp_id")
    if mp_id and "mp" not in structure:
        structure["mp"] = {"material_id": mp_id}
    db.update_project(proj["id"], protocol=protocol, phase="protocol", structure=structure)
    preview["param_tips"] = protocol["param_tips"]
    preview["hsd_default"] = hsd_text
    return {
        **base,
        "ok": True,
        "recipe_ready": True,
        "project_id": proj["id"],
        "preview": preview,
        "message": f"已为课例「{title}」生成输入文件（HSD），请核对后确认计算。",
    }
