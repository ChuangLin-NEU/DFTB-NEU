"""简易课题存储（JSON 文件）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import settings


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def projects_dir() -> Path:
    d = settings.store / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_dir(project_id: str) -> Path:
    d = projects_dir() / project_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "figures").mkdir(exist_ok=True)
    (d / "artifacts").mkdir(exist_ok=True)
    return d


def _meta_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def create_project(title: str, idea: Optional[dict] = None) -> dict[str, Any]:
    pid = uuid.uuid4().hex[:12]
    proj = {
        "id": pid,
        "title": title or "DFTB+ 课题",
        "created_at": _now(),
        "phase": "draft",
        "idea": idea or {},
        "protocol": {},
        "job": None,
        "assets": [],
        "manuscript": {},
        "activity": [],
    }
    _meta_path(pid).write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
    return proj


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    p = _meta_path(project_id)
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def update_project(project_id: str, **kwargs: Any) -> Optional[dict[str, Any]]:
    proj = get_project(project_id)
    if not proj:
        return None
    proj.update(kwargs)
    proj["updated_at"] = _now()
    _meta_path(project_id).write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
    return proj


def list_projects() -> list[dict[str, Any]]:
    rows = []
    for p in projects_dir().iterdir():
        if p.is_dir() and (p / "project.json").is_file():
            meta = json.loads((p / "project.json").read_text(encoding="utf-8"))
            job = meta.get("job") or {}
            protocol = meta.get("protocol") or {}
            structure = meta.get("structure") or {}
            rows.append(
                {
                    "id": meta.get("id"),
                    "title": meta.get("title"),
                    "phase": meta.get("phase"),
                    "created_at": meta.get("created_at"),
                    "job": {"job_id": job.get("job_id"), "status": job.get("status")} if job else None,
                    "kind": protocol.get("kind"),
                    "sk_set": protocol.get("sk_set"),
                    "has_structure": bool(structure.get("poscar") or structure.get("gen")),
                    "lesson_id": protocol.get("lesson_id"),
                }
            )
    rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return rows


def delete_project(project_id: str) -> bool:
    import shutil

    root = projects_dir() / project_id
    if not root.is_dir():
        return False
    shutil.rmtree(root, ignore_errors=True)
    return not root.exists()


def append_activity(project_id: str, message: str, phase: str = "") -> None:
    proj = get_project(project_id)
    if not proj:
        return
    act = list(proj.get("activity") or [])
    act.append({"at": _now(), "message": message, "phase": phase or proj.get("phase")})
    update_project(project_id, activity=act[-100:], phase=phase or proj.get("phase"))
