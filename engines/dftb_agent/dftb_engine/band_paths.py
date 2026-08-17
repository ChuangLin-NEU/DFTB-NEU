"""高对称 k 路径（分数坐标）与 DOS 网格辅助。"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


# (n_points, kx, ky, kz, label) — n_points=1 用于段起点
PathSeg = tuple[int, float, float, float, str]


def fcc_diamond_path() -> list[PathSeg]:
    """FCC / 金刚石（Si 等）：G–X–W–K–G–L（标签用 ASCII，兼容 HSD）。"""
    return [
        (1, 0.0, 0.0, 0.0, "G"),
        (20, 0.5, 0.0, 0.5, "X"),
        (20, 0.5, 0.25, 0.75, "W"),
        (20, 0.375, 0.375, 0.75, "K"),
        (20, 0.0, 0.0, 0.0, "G"),
        (20, 0.5, 0.5, 0.5, "L"),
    ]


def graphene_hex_path() -> list[PathSeg]:
    """二维六角（石墨烯）：G–M–K–G。"""
    return [
        (1, 0.0, 0.0, 0.0, "G"),
        (30, 0.5, 0.0, 0.0, "M"),
        (30, 1.0 / 3.0, 1.0 / 3.0, 0.0, "K"),
        (30, 0.0, 0.0, 0.0, "G"),
    ]


def simple_cubic_path() -> list[PathSeg]:
    return [
        (1, 0.0, 0.0, 0.0, "G"),
        (20, 0.5, 0.0, 0.0, "X"),
        (20, 0.5, 0.5, 0.0, "M"),
        (20, 0.0, 0.0, 0.0, "G"),
        (20, 0.5, 0.5, 0.5, "R"),
    ]


def _lattice_lengths_from_poscar(poscar: str) -> Optional[tuple[float, float, float]]:
    lines = [ln.strip() for ln in (poscar or "").splitlines() if ln.strip()]
    if len(lines) < 5:
        return None
    try:
        scale = float(lines[1].split()[0])
        vecs = []
        for i in range(2, 5):
            parts = [float(x) for x in lines[i].split()[:3]]
            vecs.append(parts)
        import math

        def norm(v: list[float]) -> float:
            return scale * math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)

        return norm(vecs[0]), norm(vecs[1]), norm(vecs[2])
    except Exception:
        return None


def infer_path(
    *,
    elements: Optional[list[str]] = None,
    poscar: str = "",
    prompt: str = "",
    params: Optional[dict[str, Any]] = None,
) -> tuple[list[PathSeg], str]:
    p = dict(params or {})
    force = str(p.get("band_path") or "").strip().lower()
    text = prompt or ""
    els = [str(e).capitalize() for e in (elements or [])]

    if force in ("graphene", "hex", "2d"):
        return graphene_hex_path(), "graphene"
    if force in ("fcc", "diamond", "si"):
        return fcc_diamond_path(), "fcc"
    if force in ("cubic", "sc"):
        return simple_cubic_path(), "cubic"

    if any(k in text for k in ("石墨烯", "graphene", "Graphene")):
        return graphene_hex_path(), "graphene"
    if any(k in text for k in ("硅", "silicon", "Si 晶体", "金刚石")):
        return fcc_diamond_path(), "fcc"

    lengths = _lattice_lengths_from_poscar(poscar)
    if lengths:
        a, b, c = lengths
        if c > 2.8 * max(a, b) and els == ["C"]:
            return graphene_hex_path(), "graphene"
        if abs(a - b) < 0.2 * a and abs(a - c) < 0.2 * a and set(els) <= {"Si", "C", "Ge"}:
            return fcc_diamond_path(), "fcc"

    if els == ["C"] and lengths and lengths[2] > 2.5 * max(lengths[0], lengths[1]):
        return graphene_hex_path(), "graphene"
    if "Si" in els:
        return fcc_diamond_path(), "fcc"
    if els == ["C"]:
        return graphene_hex_path(), "graphene"
    return simple_cubic_path(), "cubic"


def path_tick_indices(path: list[PathSeg]) -> list[tuple[int, str]]:
    """DFTB+ band.out 从 1 起编号；段终点索引累计。"""
    ticks: list[tuple[int, str]] = []
    idx = 0
    for n, _x, _y, _z, lab in path:
        idx += int(n)
        ticks.append((idx, lab))
    return ticks


def klines_hsd_block(path: list[PathSeg], *, indent: str = "    ") -> str:
    ind2 = indent + "  "
    lines = [f"{indent}KPointsAndWeights = Klines {{"]
    for n, x, y, z, lab in path:
        lines.append(f"{ind2}{int(n)}  {x:.6f}  {y:.6f}  {z:.6f}    # {lab}")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


def dos_mesh_hsd_block(*, nx: int = 16, ny: int = 16, nz: int = 16, indent: str = "    ") -> str:
    ind2 = indent + "  "
    return "\n".join(
        [
            f"{indent}KPointsAndWeights = SupercellFolding {{",
            f"{ind2}{int(nx)} 0 0",
            f"{ind2}0 {int(ny)} 0",
            f"{ind2}0 0 {int(nz)}",
            f"{ind2}0.0 0.0 0.0",
            f"{indent}}}",
        ]
    )


def band_meta_json(
    path: list[PathSeg],
    *,
    path_name: str,
    want_dos: bool,
    mode: str,
    formula: str = "",
    title_hint: str = "",
    dos_note: str = "",
) -> str:
    return json.dumps(
        {
            "path_name": path_name,
            "mode": mode,
            "want_dos": bool(want_dos),
            "dos_note": (dos_note or "").strip(),
            "formula": (formula or "").strip(),
            "title_hint": (title_hint or "").strip(),
            "ticks": [{"index": i, "label": lab} for i, lab in path_tick_indices(path)],
            "segments": [
                {"n": n, "k": [x, y, z], "label": lab} for n, x, y, z, lab in path
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def infer_mp_query(text: str) -> str:
    """从自然语言推断 Materials Project 查询式。"""
    t = text or ""
    low = t.lower()
    if any(k in t for k in ("石墨烯",)) or "graphene" in low:
        return "石墨烯"
    if re.search(r"\bMoS2\b", t, re.I) or "二硫化钼" in t:
        return "MoS2"
    if re.search(r"\bWS2\b", t, re.I):
        return "WS2"
    if re.search(r"\bBN\b", t) or "氮化硼" in t:
        return "BN"
    if "硅" in t or re.search(r"\bsilicon\b", low) or re.search(r"\bSi\b", t):
        return "Si"
    m = re.search(r"\b(mp-\d+)\b", low)
    if m:
        return m.group(1)
    m = re.search(r"化学式\s*([A-Za-z0-9]+)", t)
    if m:
        return m.group(1)
    return ""
