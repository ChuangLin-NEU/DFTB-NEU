"""DFTB+ 能力族意图识别、命令表与矩阵加载。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

MATRIX_PATH = Path(__file__).resolve().parents[3] / "templates" / "dftb_capability_matrix.json"


def load_matrix() -> dict[str, Any]:
    candidates = [
        MATRIX_PATH,
        Path(__file__).resolve().parents[2].parent / "templates" / "dftb_capability_matrix.json",
    ]
    try:
        from dftbneu.config import settings

        candidates.insert(0, settings.root / "templates" / "dftb_capability_matrix.json")
    except Exception:
        pass
    try:
        from cmats.config import settings as cmats_settings

        candidates.insert(0, cmats_settings.root / "templates" / "dftb_capability_matrix.json")
    except Exception:
        pass
    for p in candidates:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    return {"families": [], "nl_intent_keywords": {}, "nl_examples": []}


def match_family_from_text(text: str) -> Optional[str]:
    t = text or ""
    low = t.lower()
    matrix = load_matrix()
    hits: list[tuple[int, str, str]] = []
    for fam_id, keys in (matrix.get("nl_intent_keywords") or {}).items():
        for k in keys:
            if not k:
                continue
            if k.lower() in low or k in t:
                hits.append((len(str(k)), str(fam_id), str(k)))
    if not hits:
        if any(x in low or x in t for x in ("dftb", "DFTB", "紧束缚")):
            return "electronic"
        return None
    hits.sort(key=lambda x: x[0], reverse=True)
    best_len = hits[0][0]
    top = [h for h in hits if h[0] == best_len]
    # 并列时：优先非「electronic」的更具体族
    for _ln, fam, _k in top:
        if fam != "electronic":
            return fam
    return top[0][1]


def family_meta(family_id: str) -> Optional[dict[str, Any]]:
    for f in load_matrix().get("families") or []:
        if f.get("id") == family_id:
            return f
    return None


def default_kind_for_family(family_id: str) -> str:
    meta = family_meta(family_id) or {}
    kinds = list(meta.get("kinds") or ["dftb_scc"])
    return str(kinds[0])


def playbook_for_family(family_id: str) -> str:
    meta = family_meta(family_id) or {}
    return str(meta.get("playbook_id") or "dftb_electronic")


def list_supported_commands() -> list[dict[str, Any]]:
    """自然语言可触发的 DFTB+ 命令一览（面向用户/API）。"""
    from .maturity import maturity_for_family, maturity_for_kind

    matrix = load_matrix()
    rows: list[dict[str, Any]] = []
    examples = matrix.get("nl_examples") or []
    by_fam: dict[str, list[str]] = {}
    for ex in examples:
        fam = ex.get("family") or ""
        by_fam.setdefault(fam, []).append(str(ex.get("text") or ""))
    for f in matrix.get("families") or []:
        fid = f.get("id")
        kinds = list(f.get("kinds") or [])
        kind_status = {k: maturity_for_kind(k).get("status") for k in kinds}
        rows.append(
            {
                "family": fid,
                "playbook_id": f.get("playbook_id"),
                "kinds": kinds,
                "recipes": f.get("recipes"),
                "keywords": (matrix.get("nl_intent_keywords") or {}).get(fid) or [],
                "examples": by_fam.get(fid) or [],
                "env": f.get("env"),
                "status": f.get("status") or maturity_for_family(str(fid)),
                "status_note": f.get("status_note") or "",
                "submit_enabled": bool(f.get("submit_enabled", True)),
                "kind_status": kind_status,
            }
        )
    return rows


def commands_markdown() -> str:
    lines = [
        "# DFTB+ 自然语言命令（如实标注成熟度）",
        "",
        "说「用 DFTB+ / 紧束缚 / DFTB」会选引擎 `dftbplus`；再按下列意图匹配能力族。",
        "`ready`/`partial` 可投递；`skeleton` 仅说明/草稿，默认禁止投递。",
        "",
    ]
    for row in list_supported_commands():
        st = row.get("status") or "unknown"
        lines.append(f"## {row['family']} 〔{st}〕")
        lines.append(
            f"- playbook: `{row['playbook_id']}` · kinds: `{', '.join(row['kinds'] or [])}`"
        )
        lines.append(f"- Recipes: {row['recipes']}")
        if row.get("status_note"):
            lines.append(f"- 说明：{row['status_note']}")
        if row["keywords"]:
            lines.append("- 关键词：" + "、".join(f"`{k}`" for k in row["keywords"][:12]))
        for ex in (row["examples"] or [])[:4]:
            lines.append(f"- 示例：「{ex}」")
        lines.append("")
    return "\n".join(lines)
