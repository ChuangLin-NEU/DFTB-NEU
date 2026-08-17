"""自然语言结构意图：先取完美结构，再按需求做超胞/空位/掺杂等变换。"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import geometry as geo


# 宿主材料：别名 → 规范 id / 默认元素 / 默认超胞 / 本地文件名
_MATERIALS: dict[str, dict[str, Any]] = {
    "graphene": {
        "aliases": ("石墨烯", "graphene", "单层石墨烯", "石墨单层"),
        "element": "C",
        # 缺陷/掺杂默认至少 4×4，减轻缺陷–缺陷相互作用（课堂仍属近似）
        "default_sc": (4, 4, 1),
        "file": "graphene.poscar",
        "formula": "C",
        "mp_query": "石墨烯",
        "label": "石墨烯",
    },
    "Si": {
        "aliases": ("硅", "silicon", "硅晶体", "金刚石硅", "晶体硅"),
        "element": "Si",
        "default_sc": (2, 2, 2),
        "file": "si_diamond.poscar",
        "formula": "Si",
        "mp_query": "Si",
        "label": "硅",
    },
    "MoS2": {
        "aliases": ("二硫化钼", "MoS2", "mos2"),
        "element": "Mo",
        "default_sc": (4, 4, 1),
        "file": "",
        "formula": "MoS2",
        "mp_query": "MoS2",
        "label": "二硫化钼",
    },
    "WS2": {
        "aliases": ("二硫化钨", "WS2", "ws2"),
        "element": "W",
        "default_sc": (4, 4, 1),
        "file": "",
        "formula": "WS2",
        "mp_query": "WS2",
        "label": "二硫化钨",
    },
    "BN": {
        "aliases": ("氮化硼", "六方氮化硼", "hBN", "h-BN", "BN"),
        "element": "B",
        "default_sc": (4, 4, 1),
        "file": "",
        "formula": "BN",
        "mp_query": "BN",
        "label": "氮化硼",
    },
}

# 掺杂剂别名 → 元素
_DOPANTS: list[tuple[str, str]] = [
    ("氮", "N"),
    ("nitrogen", "N"),
    ("掺氮", "N"),
    ("氮掺", "N"),
    ("硼", "B"),
    ("boron", "B"),
    ("掺硼", "B"),
    ("磷", "P"),
    ("phosphorus", "P"),
    ("硫", "S"),
    ("sulfur", "S"),
    ("氧", "O"),
    ("oxygen", "O"),
    ("氟", "F"),
    ("fluorine", "F"),
    ("硅", "Si"),  # 作掺杂剂时需有「掺」语境
    ("silicon", "Si"),
]

_COMPLEX_HINTS = (
    "纳米带",
    "nanoribbon",
    "nano-ribbon",
    "钝化",
    "passivat",
    "扶手椅",
    "锯齿",
    "armchair",
    "zigzag",
    "zig-zag",
    "吸附",
    "adatom",
    "stone-wales",
    "Stone-Wales",
    "五七",
    "grain boundary",
    "晶界",
)


def _match_material(text: str) -> Optional[str]:
    t = text or ""
    low = t.lower()
    # 较长别名优先
    scored: list[tuple[int, str]] = []
    for mid, meta in _MATERIALS.items():
        for al in meta["aliases"]:
            if al in t or al.lower() in low:
                scored.append((len(al), mid))
                break
    if not scored:
        # 化学式兜底
        if re.search(r"\bMoS2\b", t, re.I):
            return "MoS2"
        if re.search(r"\bWS2\b", t, re.I):
            return "WS2"
        if re.search(r"\bBN\b", t) or "氮化硼" in t:
            return "BN"
        if re.search(r"\bSi\b", t) or "硅" in t:
            return "Si"
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def _parse_supercell(text: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    t = text or ""
    m = re.search(r"(\d+)\s*[x×X乘\*]\s*(\d+)(?:\s*[x×X乘\*]\s*(\d+))?", t)
    if m:
        nx, ny = int(m.group(1)), int(m.group(2))
        nz = int(m.group(3)) if m.group(3) else default[2]
        return max(1, nx), max(1, ny), max(1, nz)
    # 「二倍超胞 / 2倍超胞 / 扩成超胞」
    m2 = re.search(r"([2-6])\s*倍?\s*超胞", t)
    if m2:
        n = int(m2.group(1))
        return n, n, default[2]
    if any(k in t for k in ("超胞", "supercell", "扩胞", "扩大晶胞")):
        return default
    return (1, 1, 1)


def _parse_vacancy(text: str, host_element: str) -> Optional[dict[str, Any]]:
    t = text or ""
    low = t.lower()
    has = any(
        k in t
        for k in (
            "空位",
            "缺原子",
            "去掉一个",
            "拿掉一个",
            "挖掉一个",
            "移除一个碳",
            "去掉一个碳",
            "少一个碳",
            "缺一个碳",
        )
    ) or any(k in low for k in ("vacancy", "divacancy", "monovacancy", "single vacancy"))
    # 「缺陷」在二维材料语境常指空位类点缺陷（排除「缺陷计算」 alone 无材料时由上层处理）
    if not has and (any(k in t for k in ("缺陷", "点缺陷", "本征缺陷")) or "defect" in low):
        has = True
    if not has:
        return None
    n_remove = 1
    if any(k in t for k in ("双空位", "两个空位", "两空位", "二空位", "双缺")) or "divacancy" in low:
        n_remove = 2
    else:
        m = re.search(r"(\d+)\s*个?\s*(空位|缺陷)", t)
        if m:
            n_remove = max(1, min(int(m.group(1)), 4))
    el = host_element
    # 「碳空位 / 硅空位 / 硫空位 / 钼空位…」
    el_map = (
        (("碳空位", "C空位", "c vacancy", "carbon vacancy"), "C"),
        (("硅空位", "Si空位", "si vacancy", "silicon vacancy"), "Si"),
        (("硫空位", "S空位", "s vacancy", "sulfur vacancy"), "S"),
        (("钼空位", "Mo空位", "mo vacancy"), "Mo"),
        (("钨空位", "W空位", "w vacancy"), "W"),
        (("氮空位", "N空位", "n vacancy", "nitrogen vacancy"), "N"),
        (("硼空位", "B空位", "b vacancy", "boron vacancy"), "B"),
    )
    for keys, symbol in el_map:
        if any(k in t or k in low for k in keys):
            el = symbol
            break
    return {"element": el, "n_remove": n_remove}


_DOPANT_CN = {
    "氮": "N",
    "硼": "B",
    "磷": "P",
    "硫": "S",
    "氧": "O",
    "氟": "F",
    "硅": "Si",
}


def _parse_substitute(text: str, host_element: str) -> Optional[dict[str, Any]]:
    t = text or ""
    low = t.lower()
    dopant = ""
    n = 1
    # 「掺两个氮 / 掺 2 个 N / 掺杂两个硼」
    m_num = re.search(
        r"掺(?:杂)?\s*(?:了)?\s*([两二三四五六]|[1-6])\s*个?\s*"
        r"([A-Za-z]{1,2}|氮|硼|磷|硫|氧|氟|硅)",
        t,
    )
    if m_num:
        num_tok, el_tok = m_num.group(1), m_num.group(2)
        cn_num = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
        n = cn_num.get(num_tok, int(num_tok) if num_tok.isdigit() else 1)
        n = max(1, min(n, 4))
        dopant = _DOPANT_CN.get(el_tok, el_tok[:1].upper() + el_tok[1:].lower() if el_tok.isalpha() else "")
    # 明确「X掺杂 / 掺X / X-doped / N-doped graphene」
    if not dopant:
        for alias, el in _DOPANTS:
            patterns = (
                alias + "掺杂",
                "掺" + alias,
                alias + "掺",
                el + "掺杂",
                "掺" + el,
                el.lower() + "-doped",
                el.lower() + " doped",
                "doped with " + el.lower(),
                "doped-" + el.lower(),
                alias + "-doped",
            )
            if any(p in t or p in low for p in patterns):
                # 「硅」单独出现多为宿主；仅当有掺/掺杂字样时才作掺杂剂
                if el == "Si" and "硅" in t and not any(
                    k in t or k in low for k in ("掺", "掺杂", "doped")
                ):
                    continue
                dopant = el
                break
    # 「把一个碳换成氮 / 替换为N / 用氮取代碳」
    if not dopant:
        m = re.search(
            r"(?:换|替|取代|替换|改)\s*(?:成|为|作|成了)?\s*([A-Za-z]{1,2}|氮|硼|磷|硫|氧|氟|硅)",
            t,
        )
        if not m:
            m = re.search(
                r"用\s*([A-Za-z]{1,2}|氮|硼|磷|硫|氧|氟|硅)\s*(?:取代|替换|代替)",
                t,
            )
        if m:
            tok = m.group(1)
            dopant = _DOPANT_CN.get(
                tok, tok[:1].upper() + tok[1:].lower() if tok.isalpha() else ""
            )
    if not dopant:
        return None
    if n == 1:
        m = re.search(r"(\d+)\s*个?\s*(?:原子)?(?:的)?(?:掺|取代|替换)", t)
        if m:
            n = max(1, min(int(m.group(1)), 4))
        elif re.search(r"双掺|两个掺|两个氮|两个硼", t):
            n = 2
    host = host_element
    # 「把碳换成氮」时宿主明确为 C
    if any(k in t for k in ("碳换", "碳替", "碳取", "一个碳", "碳原子")):
        host = "C"
    return {"host": host, "dopant": dopant, "n": n}


def parse_structure_intent(text: str) -> Optional[dict[str, Any]]:
    """解析结构改造意图。无需改造时返回 None（走普通模板/MP）。"""
    t = (text or "").strip()
    if not t:
        return None
    material = _match_material(t)
    complex_need_upload = any(k in t or k.lower() in t.lower() for k in _COMPLEX_HINTS)

    # 无材料且不是复杂定制：不处理
    if not material and not complex_need_upload:
        return None

    # 复杂几何（纳米带/钝化等）：标记需上传，但仍可先给宿主近似
    if complex_need_upload and not material:
        if any(k in t for k in ("石墨烯", "graphene", "碳")):
            material = "graphene"
        else:
            return {
                "material": "",
                "need_upload": True,
                "transforms": [],
                "spin_polarized": False,
                "label": "定制结构",
            }

    meta = _MATERIALS.get(material or "", {})
    host_el = str(meta.get("element") or "C")
    default_sc = tuple(meta.get("default_sc") or (2, 2, 1))

    vacancy = _parse_vacancy(t, host_el)
    substitute = _parse_substitute(t, host_el)
    want_sc_words = any(k in t for k in ("超胞", "supercell", "扩胞", "扩大晶胞"))
    sc_explicit = bool(re.search(r"\d+\s*[x×X乘\*]\s*\d+", t))

    # 需要改造：空位 / 掺杂 / 显式超胞 / 复杂定制
    needs_derive = bool(vacancy or substitute or want_sc_words or sc_explicit or complex_need_upload)
    if not needs_derive:
        return None

    # 超胞：空位/掺杂默认用材料默认超胞；仅说超胞则解析或默认
    if vacancy or substitute or want_sc_words or sc_explicit:
        if sc_explicit or want_sc_words:
            nx, ny, nz = _parse_supercell(t, default_sc)
            if (nx, ny, nz) == (1, 1, 1) and (vacancy or substitute):
                nx, ny, nz = default_sc
        else:
            nx, ny, nz = default_sc
    else:
        nx, ny, nz = 1, 1, 1

    transforms: list[dict[str, Any]] = []
    if (nx, ny, nz) != (1, 1, 1):
        transforms.append({"op": "supercell", "nx": nx, "ny": ny, "nz": nz})
    if vacancy:
        transforms.append(
            {"op": "vacancy", "element": vacancy["element"], "n_remove": vacancy["n_remove"]}
        )
    if substitute:
        transforms.append(
            {
                "op": "substitute",
                "host": substitute["host"],
                "dopant": substitute["dopant"],
                "n": substitute["n"],
            }
        )

    spin = bool(vacancy) or (
        bool(substitute) and substitute.get("dopant") in {"N", "B", "P"}
    )
    unpaired = 0.0
    if vacancy:
        # 单空位常有局域磁矩；偶数空位默认不强制未配对电子
        unpaired = 1.0 if int(vacancy.get("n_remove") or 1) % 2 == 1 else 0.0
    elif substitute and substitute.get("dopant") in {"N", "B", "P"}:
        unpaired = 1.0 if int(substitute.get("n") or 1) % 2 == 1 else 0.0

    return {
        "material": material or "",
        "label": str(meta.get("label") or material or "材料"),
        "host_element": host_el,
        "file": str(meta.get("file") or ""),
        "formula": str(meta.get("formula") or ""),
        "mp_query": str(meta.get("mp_query") or material or ""),
        "transforms": transforms,
        "need_upload": complex_need_upload,
        "spin_polarized": spin,
        "unpaired_electrons": unpaired,
        "supercell": (nx, ny, nz),
        "vacancy": vacancy,
        "substitute": substitute,
    }


def substitute_atoms(
    data: dict[str, Any],
    *,
    host: str,
    dopant: str,
    n: int = 1,
) -> dict[str, Any]:
    """将 n 个 host 原子替换为 dopant。"""
    host_el = (host or "C").strip().capitalize()
    dop_el = (dopant or "N").strip().capitalize()
    n = max(1, int(n))
    els = list(data["elements"])
    frac = list(data["frac_coords"])
    lattice = data["lattice"]
    idxs = [i for i, e in enumerate(els) if e == host_el]
    if len(idxs) < n:
        raise ValueError(f"可替换的 {host_el} 不足：仅 {len(idxs)}，需要 {n}")
    for i in idxs[:n]:
        els[i] = dop_el
    order: list[str] = []
    for e in els:
        if e not in order:
            order.append(e)
    counts = [els.count(s) for s in order]
    ordered_frac: list[list[float]] = []
    ordered_els: list[str] = []
    for s in order:
        for e, fc in zip(els, frac):
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
        "comment": str(data.get("comment") or "substituted"),
    }


def apply_structure_transforms(pristine_poscar: str, intent: dict[str, Any]) -> str:
    """对完美结构依次应用 transforms，返回 POSCAR。"""
    data = geo.parse_poscar(pristine_poscar)
    steps: list[str] = [str(data.get("comment") or "pristine")]
    for tr in intent.get("transforms") or []:
        op = tr.get("op")
        if op == "supercell":
            data = geo.make_supercell(
                data, nx=int(tr["nx"]), ny=int(tr["ny"]), nz=int(tr["nz"])
            )
            steps.append(f"{tr['nx']}x{tr['ny']}x{tr['nz']} supercell")
        elif op == "vacancy":
            data = geo.remove_vacancies(
                data, element=str(tr["element"]), n_remove=int(tr["n_remove"])
            )
            steps.append(f"remove {tr['n_remove']} {tr['element']}")
        elif op == "substitute":
            data = substitute_atoms(
                data,
                host=str(tr["host"]),
                dopant=str(tr["dopant"]),
                n=int(tr["n"]),
            )
            steps.append(f"substitute {tr['n']} {tr['host']}->{tr['dopant']}")
    comment = " -> ".join(steps)
    return geo.poscar_from_data(
        lattice=data["lattice"],
        symbols=data["symbols"],
        counts=data["counts"],
        frac_coords=data["frac_coords"],
        comment=comment,
    )


def describe_intent(intent: dict[str, Any]) -> str:
    """给人看的简短说明。"""
    label = intent.get("label") or intent.get("material") or "材料"
    parts = [f"已先获取完美「{label}」结构"]
    for tr in intent.get("transforms") or []:
        op = tr.get("op")
        if op == "supercell":
            parts.append(f"扩为 {tr['nx']}×{tr['ny']}×{tr['nz']} 超胞")
        elif op == "vacancy":
            parts.append(f"挖去 {tr['n_remove']} 个 {tr['element']} 空位")
        elif op == "substitute":
            parts.append(f"将 {tr['n']} 个 {tr['host']} 替换为 {tr['dopant']}")
    if intent.get("need_upload"):
        parts.append("纳米带/钝化等复杂几何仍建议上传 GEN/POSCAR 覆盖")
    else:
        parts.append("若构型不符可上传自己的 GEN/POSCAR 覆盖")
    return "，".join(parts) + "。"


# 兼容旧接口
def parse_vacancy_intent(text: str) -> Optional[dict[str, Any]]:
    intent = parse_structure_intent(text)
    if not intent or not intent.get("vacancy"):
        return None
    vac = intent["vacancy"]
    sc = intent.get("supercell") or (2, 2, 1)
    return {
        "material": intent.get("material"),
        "element": vac["element"],
        "nx": sc[0],
        "ny": sc[1],
        "nz": sc[2],
        "n_remove": vac["n_remove"],
    }
