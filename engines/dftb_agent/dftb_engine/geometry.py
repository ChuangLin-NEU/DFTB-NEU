"""几何：POSCAR/xyz → gen；对照 Manual GenFormat / VaspFormat / xyzFormat。"""

from __future__ import annotations

import math
import re
from typing import Any, Optional


def parse_poscar(text: str) -> dict[str, Any]:
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip() or True]
    # 保留空行语义较松：过滤全空
    raw = [ln.rstrip("\n") for ln in (text or "").splitlines()]
    nonempty = [ln for ln in raw if ln.strip()]
    if len(nonempty) < 8:
        raise ValueError("POSCAR 过短")
    scale = float(nonempty[1].split()[0])
    lattice = []
    for i in range(2, 5):
        lattice.append([float(x) * scale for x in nonempty[i].split()[:3]])
    # species line then counts, or selective dynamics
    species = nonempty[5].split()
    # if species are integers, it's old format without symbols
    if all(re.match(r"^\d+$", s) for s in species):
        counts = [int(x) for x in species]
        symbols = [f"X{i+1}" for i in range(len(counts))]
        idx = 6
    else:
        symbols = species
        counts = [int(x) for x in nonempty[6].split()[: len(symbols)]]
        idx = 7
    # coord type
    coord_line = nonempty[idx].strip().lower()
    if coord_line.startswith("s"):  # Selective dynamics
        idx += 1
        coord_line = nonempty[idx].strip().lower()
    idx += 1
    cart = coord_line.startswith("c") or coord_line.startswith("k")
    nat = sum(counts)
    coords: list[list[float]] = []
    frac_coords: list[list[float]] = []
    types: list[int] = []
    type_of: list[str] = []
    ti = 0
    # lattice inverse for cart → frac
    try:
        det = (
            lattice[0][0] * (lattice[1][1] * lattice[2][2] - lattice[1][2] * lattice[2][1])
            - lattice[0][1] * (lattice[1][0] * lattice[2][2] - lattice[1][2] * lattice[2][0])
            + lattice[0][2] * (lattice[1][0] * lattice[2][1] - lattice[1][1] * lattice[2][0])
        )
    except Exception:
        det = 0.0
    inv = None
    if abs(det) > 1e-18:
        inv = [
            [
                (lattice[1][1] * lattice[2][2] - lattice[1][2] * lattice[2][1]) / det,
                (lattice[0][2] * lattice[2][1] - lattice[0][1] * lattice[2][2]) / det,
                (lattice[0][1] * lattice[1][2] - lattice[0][2] * lattice[1][1]) / det,
            ],
            [
                (lattice[1][2] * lattice[2][0] - lattice[1][0] * lattice[2][2]) / det,
                (lattice[0][0] * lattice[2][2] - lattice[0][2] * lattice[2][0]) / det,
                (lattice[0][2] * lattice[1][0] - lattice[0][0] * lattice[1][2]) / det,
            ],
            [
                (lattice[1][0] * lattice[2][1] - lattice[1][1] * lattice[2][0]) / det,
                (lattice[0][1] * lattice[2][0] - lattice[0][0] * lattice[2][1]) / det,
                (lattice[0][0] * lattice[1][1] - lattice[0][1] * lattice[1][0]) / det,
            ],
        ]
    for si, (sym, n) in enumerate(zip(symbols, counts)):
        for _ in range(n):
            parts = nonempty[idx + ti].split()
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            if not cart:
                fx, fy, fz = x, y, z
                x = fx * lattice[0][0] + fy * lattice[1][0] + fz * lattice[2][0]
                y = fx * lattice[0][1] + fy * lattice[1][1] + fz * lattice[2][1]
                z = fx * lattice[0][2] + fy * lattice[1][2] + fz * lattice[2][2]
            else:
                if inv is None:
                    raise ValueError("无法将笛卡尔坐标转为分数坐标")
                fx = x * inv[0][0] + y * inv[1][0] + z * inv[2][0]
                fy = x * inv[0][1] + y * inv[1][1] + z * inv[2][1]
                fz = x * inv[0][2] + y * inv[1][2] + z * inv[2][2]
            coords.append([x, y, z])
            frac_coords.append([fx, fy, fz])
            types.append(si + 1)
            type_of.append(sym)
            ti += 1
    return {
        "symbols": symbols,
        "counts": counts,
        "lattice": lattice,
        "coords": coords,
        "frac_coords": frac_coords,
        "types": types,
        "elements": type_of,
        "periodic": True,
        "natoms": nat,
        "comment": (nonempty[0] if nonempty else "structure").strip(),
    }


def poscar_from_data(
    *,
    lattice: list[list[float]],
    symbols: list[str],
    counts: list[int],
    frac_coords: list[list[float]],
    comment: str = "dftb-neu",
) -> str:
    """由分数坐标写出 POSCAR。"""
    lines = [
        comment,
        "1.0",
        f"  {lattice[0][0]:.10f}  {lattice[0][1]:.10f}  {lattice[0][2]:.10f}",
        f"  {lattice[1][0]:.10f}  {lattice[1][1]:.10f}  {lattice[1][2]:.10f}",
        f"  {lattice[2][0]:.10f}  {lattice[2][1]:.10f}  {lattice[2][2]:.10f}",
        " ".join(symbols),
        " ".join(str(int(c)) for c in counts),
        "Direct",
    ]
    # 按元素顺序写出
    by_el: dict[str, list[list[float]]] = {s: [] for s in symbols}
    # frac_coords 与 counts 对齐：调用方保证顺序与 symbols/counts 一致
    cursor = 0
    for sym, n in zip(symbols, counts):
        for _ in range(n):
            by_el[sym].append(frac_coords[cursor])
            cursor += 1
    for sym in symbols:
        for fx, fy, fz in by_el[sym]:
            lines.append(f"  {fx:.9f}  {fy:.9f}  {fz:.9f}")
    return "\n".join(lines) + "\n"


def make_supercell(data: dict[str, Any], nx: int = 1, ny: int = 1, nz: int = 1) -> dict[str, Any]:
    """分数坐标超胞扩展。"""
    nx, ny, nz = max(1, int(nx)), max(1, int(ny)), max(1, int(nz))
    lat0 = data["lattice"]
    lattice = [
        [lat0[0][0] * nx, lat0[0][1] * nx, lat0[0][2] * nx],
        [lat0[1][0] * ny, lat0[1][1] * ny, lat0[1][2] * ny],
        [lat0[2][0] * nz, lat0[2][1] * nz, lat0[2][2] * nz],
    ]
    frac0 = data.get("frac_coords") or []
    els0 = list(data.get("elements") or [])
    new_frac: list[list[float]] = []
    new_els: list[str] = []
    for (fx, fy, fz), el in zip(frac0, els0):
        for ix in range(nx):
            for iy in range(ny):
                for iz in range(nz):
                    new_frac.append([(fx + ix) / nx, (fy + iy) / ny, (fz + iz) / nz])
                    new_els.append(el)
    # 按元素重排并统计
    order: list[str] = []
    for el in new_els:
        if el not in order:
            order.append(el)
    counts = [new_els.count(s) for s in order]
    ordered_frac: list[list[float]] = []
    for s in order:
        for el, fc in zip(new_els, new_frac):
            if el == s:
                ordered_frac.append(fc)
    # 笛卡尔
    coords = []
    for fx, fy, fz in ordered_frac:
        coords.append(
            [
                fx * lattice[0][0] + fy * lattice[1][0] + fz * lattice[2][0],
                fx * lattice[0][1] + fy * lattice[1][1] + fz * lattice[2][1],
                fx * lattice[0][2] + fy * lattice[1][2] + fz * lattice[2][2],
            ]
        )
    types = []
    for i, s in enumerate(order, start=1):
        types.extend([i] * counts[i - 1])
    return {
        "symbols": order,
        "counts": counts,
        "lattice": lattice,
        "coords": coords,
        "frac_coords": ordered_frac,
        "types": types,
        "elements": [order[t - 1] for t in types],
        "periodic": True,
        "natoms": sum(counts),
        "comment": str(data.get("comment") or "supercell"),
    }


def _min_image_frac_dist(a: list[float], b: list[float], lattice: list[list[float]]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    dx -= round(dx)
    dy -= round(dy)
    dz -= round(dz)
    cart = [
        dx * lattice[0][0] + dy * lattice[1][0] + dz * lattice[2][0],
        dx * lattice[0][1] + dy * lattice[1][1] + dz * lattice[2][1],
        dx * lattice[0][2] + dy * lattice[1][2] + dz * lattice[2][2],
    ]
    return math.sqrt(cart[0] ** 2 + cart[1] ** 2 + cart[2] ** 2)


def remove_vacancies(
    data: dict[str, Any],
    *,
    element: str = "C",
    n_remove: int = 1,
) -> dict[str, Any]:
    """从超胞中移除 n_remove 个指定元素原子（单空位取首个；双空位取最近邻对）。"""
    el = (element or "C").strip().capitalize()
    n_remove = max(1, int(n_remove))
    frac = list(data["frac_coords"])
    els = list(data["elements"])
    lattice = data["lattice"]
    idxs = [i for i, e in enumerate(els) if e == el]
    if len(idxs) <= n_remove:
        raise ValueError(f"原子数不足以挖空位：{el} 仅 {len(idxs)} 个，需移除 {n_remove}")
    remove: list[int] = []
    if n_remove == 1:
        remove = [idxs[0]]
    else:
        # 取距离最近的一对，再按需扩展
        best = (1e99, idxs[0], idxs[1])
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                d = _min_image_frac_dist(frac[idxs[i]], frac[idxs[j]], lattice)
                if d < best[0]:
                    best = (d, idxs[i], idxs[j])
        remove = [best[1], best[2]]
        while len(remove) < n_remove:
            # 再找离已删集合最近的同种原子
            cand = None
            cand_d = 1e99
            for i in idxs:
                if i in remove:
                    continue
                d = min(_min_image_frac_dist(frac[i], frac[r], lattice) for r in remove)
                if d < cand_d:
                    cand_d = d
                    cand = i
            if cand is None:
                break
            remove.append(cand)
    keep = [i for i in range(len(els)) if i not in set(remove)]
    new_els = [els[i] for i in keep]
    new_frac = [frac[i] for i in keep]
    order: list[str] = []
    for e in new_els:
        if e not in order:
            order.append(e)
    counts = [new_els.count(s) for s in order]
    ordered_frac: list[list[float]] = []
    ordered_els: list[str] = []
    for s in order:
        for e, fc in zip(new_els, new_frac):
            if e == s:
                ordered_frac.append(fc)
                ordered_els.append(e)
    coords = []
    for fx, fy, fz in ordered_frac:
        coords.append(
            [
                fx * lattice[0][0] + fy * lattice[1][0] + fz * lattice[2][0],
                fx * lattice[0][1] + fy * lattice[1][1] + fz * lattice[2][1],
                fx * lattice[0][2] + fy * lattice[1][2] + fz * lattice[2][2],
            ]
        )
    types = []
    for i, s in enumerate(order, start=1):
        types.extend([i] * counts[i - 1])
    return {
        "symbols": order,
        "counts": counts,
        "lattice": lattice,
        "coords": coords,
        "frac_coords": ordered_frac,
        "types": types,
        "elements": ordered_els,
        "periodic": True,
        "natoms": sum(counts),
        "comment": str(data.get("comment") or "vacancy"),
        "removed": len(remove),
    }


def parse_vacancy_intent(text: str) -> Optional[dict[str, Any]]:
    """兼容旧调用：委托给 structure_intent。"""
    from .structure_intent import parse_vacancy_intent as _p

    return _p(text)


def introduce_vacancy_from_pristine(
    pristine_poscar: str,
    *,
    nx: int = 2,
    ny: int = 2,
    nz: int = 1,
    n_remove: int = 1,
    element: str = "C",
    comment: str = "",
) -> str:
    """完美晶体 → 超胞 → 挖空位，返回 POSCAR。"""
    data = parse_poscar(pristine_poscar)
    sc = make_supercell(data, nx=nx, ny=ny, nz=nz)
    vac = remove_vacancies(sc, element=element, n_remove=n_remove)
    note = comment or (
        f"{data.get('comment') or 'pristine'} -> {nx}x{ny}x{nz} supercell, "
        f"remove {n_remove} {element}"
    )
    return poscar_from_data(
        lattice=vac["lattice"],
        symbols=vac["symbols"],
        counts=vac["counts"],
        frac_coords=vac["frac_coords"],
        comment=note,
    )


def poscar_to_gen(poscar: str, *, cluster: bool = False) -> str:
    """写出 .gen（Å）。cluster=True 用 C（分子），否则 S（超胞）。"""
    data = parse_poscar(poscar)
    mode = "C" if cluster else "S"
    n = data["natoms"]
    syms = data["symbols"]
    lines = [f"{n} {mode}", " ".join(syms)]
    for i, (t, xyz) in enumerate(zip(data["types"], data["coords"]), start=1):
        lines.append(f"{i:6d} {t:3d} {xyz[0]:22.12E} {xyz[1]:22.12E} {xyz[2]:22.12E}")
    if not cluster:
        lines.append("0.0 0.0 0.0")
        for vec in data["lattice"]:
            lines.append(f"{vec[0]:22.12E} {vec[1]:22.12E} {vec[2]:22.12E}")
    return "\n".join(lines) + "\n"


def water_gen_from_recipes() -> str:
    """DFTB+ Recipes firstcalc H2O 几何（Å，cluster）。

    相对原 Recipes 坐标绕 y 轴旋转 90°，键长/键角不变；
    默认相机沿 z 看时呈清晰 V 形，避免两个 H 在投影上重叠。
    """
    return """3 C
 O H
    1    1    0.00000000000E+00  -1.00000000000E+00   0.00000000000E+00
    2    2    0.78306400000E+00   0.00000000000E+00   0.00000000000E+00
    3    2   -0.78306400000E+00   0.00000000000E+00   0.00000000000E+00
"""


def gen_mode(gen: str) -> str:
    """DFTB+ GenFormat 模式字母：C / S / F（无法识别时默认 C）。"""
    lines = [ln for ln in (gen or "").splitlines() if ln.strip()]
    if not lines:
        return "C"
    head = lines[0].split()
    if len(head) < 2:
        return "C"
    mode = head[1].strip().upper()[:1]
    return mode if mode in {"C", "S", "F"} else "C"


def gen_is_cluster(gen: str) -> bool:
    """C = 分子/cluster；S/F = 周期超胞。"""
    return gen_mode(gen) == "C"


def elements_from_gen(gen: str) -> list[str]:
    lines = [ln for ln in gen.splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    return lines[1].split()


def natoms_from_gen(gen: str) -> int:
    """GEN 首行原子数。"""
    lines = [ln for ln in (gen or "").splitlines() if ln.strip()]
    if not lines:
        return 0
    head = lines[0].split()
    if not head:
        return 0
    try:
        return int(head[0])
    except ValueError:
        return 0


def elements_from_poscar(poscar: str) -> list[str]:
    try:
        return list(parse_poscar(poscar)["symbols"])
    except Exception:
        return []


def _format_hill_formula(symbols: list[str], counts: list[int]) -> str:
    """按 Hill 惯例拼化学式（有 C 时 C→H→其余；否则字母序）。"""
    items = [(str(s), int(c)) for s, c in zip(symbols, counts) if s and int(c) > 0]
    if not items:
        return ""
    has_c = any(s == "C" for s, _ in items)

    def sort_key(sc: tuple[str, int]) -> tuple:
        s = sc[0]
        if has_c:
            if s == "C":
                return (0, s)
            if s == "H":
                return (1, s)
            return (2, s)
        return (0, s)

    items.sort(key=sort_key)
    parts: list[str] = []
    for sym, n in items:
        parts.append(sym if n == 1 else f"{sym}{n}")
    return "".join(parts)


def formula_from_gen(gen: str) -> str:
    """从 GEN 统计原子得到化学式。勿用首行数字（那是原子数）。"""
    lines = [ln for ln in (gen or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return ""
    head = lines[0].split()
    if not head or not head[0].isdigit():
        return ""
    syms = lines[1].split()
    if not syms:
        return ""
    counts = [0] * len(syms)
    for ln in lines[2:]:
        parts = ln.split()
        if len(parts) < 2:
            continue
        try:
            t = int(parts[1])
        except ValueError:
            continue
        if 1 <= t <= len(syms):
            counts[t - 1] += 1
    if sum(counts) <= 0:
        # 无坐标行时退回「每种一个」仅作元素标签，仍比原子数好
        counts = [1] * len(syms)
    return _format_hill_formula(syms, counts)


def formula_from_poscar(poscar: str) -> str:
    try:
        data = parse_poscar(poscar)
        return _format_hill_formula(list(data["symbols"]), list(data["counts"]))
    except Exception:
        return ""


def looks_like_formula_label(text: str) -> bool:
    """判断字符串是否像化学式/体系名（排除纯数字原子数等）。"""
    s = (text or "").strip()
    if not s or len(s) > 40:
        return False
    if s.isdigit():
        return False
    if s.lower().startswith("generated"):
        return False
    return any(c.isalpha() for c in s)
