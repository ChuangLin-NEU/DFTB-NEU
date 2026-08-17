"""轻量读取 templates/playbooks 元数据。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from ..config import settings


def _playbooks_dir() -> Path:
    return settings.root / "templates" / "playbooks"


@lru_cache(maxsize=32)
def load_playbook(family: str) -> Optional[dict[str, Any]]:
    """按 dftb_family 查找 playbook（文件名 dftb_<family>.json）。"""
    fid = (family or "").strip()
    if not fid:
        return None
    candidates = [
        _playbooks_dir() / f"dftb_{fid}.json",
        _playbooks_dir() / f"{fid}.json",
    ]
    # electronic → dftb_electronic.json；geometry_vib → dftb_opt_vib.json
    aliases = {
        "geometry_vib": "dftb_opt_vib",
        "linresp": "dftb_td",
        "md": "dftb_md",
        "xtb_in_dftb": "dftb_xtb",
        "defect_2d": "dftb_defect_2d",
        "phonon": "dftb_phonon",
        "transport": "dftb_transport",
        "electronic": "dftb_electronic",
    }
    alias = aliases.get(fid)
    if alias:
        candidates.insert(0, _playbooks_dir() / f"{alias}.json")
    for path in candidates:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def playbook_meta(family: str) -> dict[str, Any]:
    pb = load_playbook(family)
    if not pb:
        return {}
    defaults = pb.get("method_defaults") or {}
    return {
        "playbook_id": pb.get("id") or "",
        "playbook_name": pb.get("name") or "",
        "success_criteria": list(pb.get("success_criteria") or []),
        "sk_set_default": defaults.get("sk_set") or "",
        "maturity": pb.get("maturity") or "",
        "maturity_note": pb.get("maturity_note") or "",
    }
