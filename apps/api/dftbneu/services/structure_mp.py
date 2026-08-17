"""Materials Project 结构拉取 → POSCAR（httpx，不强制 mp-api）。"""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from ..config import settings
from .secrets import reveal_mp_key


class StructureError(Exception):
    pass


_PREFERRED_MP_IDS: dict[str, list[str]] = {
    "MoS2": ["mp-2815", "mp-1434"],
    "WS2": ["mp-224"],
    "BN": ["mp-984"],
    "Si": ["mp-149"],
    "C": ["mp-48", "mp-169"],
    "Graphene": ["mp-48"],
    "石墨烯": ["mp-48"],
}


def _mp_key() -> str:
    return reveal_mp_key() or (settings.mp_api_key or "").strip()


def _mp_get(path: str, params: Optional[dict] = None) -> Any:
    key = _mp_key()
    if not key:
        raise StructureError("未配置 Materials Project API Key（设置页或 DFTB_NEU_MP_API_KEY / CMATS_MP_API_KEY）。")
    url = f"https://api.materialsproject.org{path}"
    headers = {
        "X-API-KEY": key,
        "Accept": "application/json",
        "User-Agent": "dftb-neu/0.1 (classroom DFTB+)",
    }
    with httpx.Client(timeout=45.0, headers=headers, follow_redirects=True, trust_env=False) as client:
        r = client.get(url, params=params or {})
        if r.status_code >= 400:
            raise StructureError(f"Materials Project HTTP {r.status_code}: {r.text[:400]}")
        return r.json()


def _structure_to_poscar(structure: dict, comment: str = "dftb-neu from MP") -> str:
    lattice = structure.get("lattice") or {}
    matrix = lattice.get("matrix")
    if not matrix:
        raise StructureError("结构缺少晶格矩阵")
    sites = structure.get("sites") or []
    if not sites:
        raise StructureError("结构无原子位点")
    order: list[str] = []
    counts: dict[str, int] = {}
    coords: list[tuple[str, list[float]]] = []
    for site in sites:
        species = site.get("species") or []
        if not species:
            continue
        el = species[0].get("element") or "?"
        if el not in counts:
            order.append(el)
            counts[el] = 0
        counts[el] += 1
        abc = site.get("abc") or site.get("frac_coords")
        if not abc:
            raise StructureError("位点缺少分数坐标")
        coords.append((el, [float(abc[0]), float(abc[1]), float(abc[2])]))
    lines = [
        comment,
        "1.0",
        f"{matrix[0][0]:.10f} {matrix[0][1]:.10f} {matrix[0][2]:.10f}",
        f"{matrix[1][0]:.10f} {matrix[1][1]:.10f} {matrix[1][2]:.10f}",
        f"{matrix[2][0]:.10f} {matrix[2][1]:.10f} {matrix[2][2]:.10f}",
        " ".join(order),
        " ".join(str(counts[e]) for e in order),
        "Direct",
    ]
    for el in order:
        for e, abc in coords:
            if e == el:
                lines.append(f"{abc[0]:.10f} {abc[1]:.10f} {abc[2]:.10f}")
    return "\n".join(lines) + "\n"


def _rank(cands: list[dict]) -> list[dict]:
    return sorted(
        cands,
        key=lambda x: (
            0 if x.get("is_stable") else 1,
            x.get("energy_above_hull") is None,
            float(x.get("energy_above_hull") or 0.0),
            int(x.get("nsites") or 9999),
        ),
    )


def search_materials(formula: str, limit: int = 8) -> list[dict]:
    formula = (formula or "").strip()
    if not formula:
        raise StructureError("化学式为空")
    try:
        from . import license as lic

        if lic.use_hub_proxy():
            return lic.hub_mp_search_sync(formula, limit=limit)
    except Exception as e:
        from . import license as lic

        if lic.use_hub_proxy():
            raise StructureError(str(e)) from e
    data = _mp_get(
        "/materials/summary/",
        {
            "formula": formula,
            "_limit": str(max(limit, 12)),
            "_fields": "material_id,formula_pretty,nsites,symmetry,energy_above_hull,is_stable",
        },
    )
    docs = data.get("data") or data.get("results") or []
    out = []
    for d in docs:
        out.append(
            {
                "material_id": d.get("material_id"),
                "formula": d.get("formula_pretty") or formula,
                "nsites": d.get("nsites"),
                "symmetry": (d.get("symmetry") or {}).get("symbol")
                if isinstance(d.get("symmetry"), dict)
                else d.get("symmetry"),
                "energy_above_hull": d.get("energy_above_hull"),
                "is_stable": d.get("is_stable"),
            }
        )
    return _rank(out)[:limit]


def fetch_poscar(query: str, *, material_id: str = "") -> dict[str, Any]:
    try:
        from . import license as lic

        if lic.use_hub_proxy():
            return lic.hub_mp_fetch_sync(query, material_id=material_id)
    except Exception as e:
        from . import license as lic

        if lic.use_hub_proxy():
            raise StructureError(str(e)) from e

    mid = (material_id or "").strip()
    q = (query or "").strip()
    if not mid:
        if q.lower().startswith("mp-") or q.lower().startswith("mvc-"):
            mid = q
        else:
            for pref in _PREFERRED_MP_IDS.get(q, []) + _PREFERRED_MP_IDS.get(q.replace(" ", ""), []):
                mid = pref
                break
            if not mid:
                cands = search_materials(q, limit=5)
                if not cands:
                    raise StructureError(f"未找到化学式 {q} 的结构")
                mid = str(cands[0].get("material_id") or "")
    if not mid:
        raise StructureError("无法确定 material_id")

    data = _mp_get(
        "/materials/summary/",
        {
            "material_ids": mid,
            "_limit": "1",
            "_fields": "material_id,formula_pretty,structure,energy_above_hull,nsites,is_stable",
        },
    )
    docs = data.get("data") or data.get("results") or []
    if not docs:
        raise StructureError(f"未找到 {mid}")
    doc = docs[0]
    structure = doc.get("structure")
    if not structure:
        raise StructureError(f"{mid} 无 structure 字段")
    formula = doc.get("formula_pretty") or q or mid
    poscar = _structure_to_poscar(structure, comment=f"{formula} ({mid}) via Materials Project")
    return {
        "material_id": mid,
        "formula": formula,
        "poscar": poscar,
        "nsites": doc.get("nsites"),
        "source": "materials-project",
    }


def mp_status() -> dict[str, Any]:
    try:
        from . import license as lic

        if lic.use_hub_proxy():
            return {"configured": True, "hint": "经登录代理", "mode": "hub"}
    except Exception:
        pass
    return {"configured": bool(_mp_key()), "hint": "已配置" if _mp_key() else "未配置", "mode": "local"}

