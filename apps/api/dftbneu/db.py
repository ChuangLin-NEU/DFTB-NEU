"""简易课题存储（JSON 文件）。"""

from __future__ import annotations

import json
import os
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


def _as_map(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """同目录临时文件 + replace，避免列表读取到半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


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
    _write_json(_meta_path(pid), proj)
    return proj


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    return _read_json(_meta_path(project_id))


def update_project(project_id: str, **kwargs: Any) -> Optional[dict[str, Any]]:
    proj = get_project(project_id)
    if not proj:
        return None
    proj.update(kwargs)
    proj["updated_at"] = _now()
    _write_json(_meta_path(project_id), proj)
    return proj


def list_projects() -> list[dict[str, Any]]:
    rows = []
    root = projects_dir()
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for p in entries:
        try:
            if not p.is_dir() or not (p / "project.json").is_file():
                continue
            meta = _read_json(p / "project.json")
            if not meta:
                continue
            job = _as_map(meta.get("job"))
            protocol = _as_map(meta.get("protocol"))
            structure = _as_map(meta.get("structure"))
            job_id = job.get("job_id") or protocol.get("job_id") or ""
            job_status = job.get("status") or ""
            rows.append(
                {
                    "id": meta.get("id") or p.name,
                    "title": meta.get("title"),
                    "phase": meta.get("phase"),
                    "created_at": meta.get("created_at"),
                    "job": {"job_id": job_id, "status": job_status} if job_id or job_status else None,
                    "protocol_job_id": protocol.get("job_id") or "",
                    "kind": protocol.get("kind"),
                    "sk_set": protocol.get("sk_set"),
                    "has_structure": bool(structure.get("poscar") or structure.get("gen")),
                    "lesson_id": protocol.get("lesson_id"),
                }
            )
        except Exception:
            continue
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
