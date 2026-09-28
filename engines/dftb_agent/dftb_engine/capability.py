"""DFTB+ 能力族意图识别、命令表与矩阵加载。"""

from __future__ import annotations

import json
import re
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


# ---------------------------------------------------------------------------
# 多步自然语言：先收集全部意图，再合成「一个作业里能跑的阶段链」
# 引擎实际阶段：dftb_in_opt → 主 dftb_in.hsd → 可选 dftb_in_dos → 可选 modes
# ---------------------------------------------------------------------------

STAGE_ZH = {
    "opt": "几何优化",
    "scc": "SCC 单点",
    "band": "能带与带隙",
    "dos": "态密度",
    "defect": "缺陷电子结构",
    "vib": "振动频率",
    "td": "吸收光谱",
    "td_relax": "激发态优化",
    "md": "分子动力学",
    "md_anneal": "退火 MD",
    "solv": "隐式溶剂",
    "xtb": "xTB 优化",
    "phonon": "声子（草稿）",
    "transport": "输运（草稿）",
    "barrier": "能垒（草稿）",
    "edyn": "电子动力学（草稿）",
    "ehrenfest": "Ehrenfest（草稿）",
    "reks": "REKS（草稿）",
    "gsm": "反应路径（草稿）",
    "boundary": "螺旋边界（草稿）",
    "ase": "ASE（草稿）",
    "ipi": "i-PI（草稿）",
}

_GEOM_OPT_KEYS = (
    "几何优化",
    "结构优化",
    "结构弛豫",
    "离子弛豫",
    "几何弛豫",
    "先优化",
    "优化",
    "geometry optimization",
    "geometry optimisation",
)
_SKIP_OPT_KEYS = ("不优化", "不要优化", "跳过优化", "无需优化", "without relax", "no relax")
_VIB_KEYS = ("振动频率", "振动谱", "红外光谱", "红外", "hessian", "简正模", "振动模", "IR spectrum")
_PHONON_KEYS = ("声子带", "声子谱", "phonopy", "声子")
_BAND_KEYS = ("能带结构", "能带", "band structure")
_GAP_KEYS = ("带隙", "能隙", "禁带宽度", "禁带", "bandgap", "band gap", "band-gap")
_DOS_KEYS = ("态密度", "PDOS", "pdos")
_TD_KEYS = ("吸收光谱", "紫外可见", "TD-DFTB", "td-dftb", "Casida", "线性响应", "振子强度")
_TD_RELAX_KEYS = ("激发态优化", "激发态几何", "激发态弛豫")
_MD_KEYS = ("分子动力学", "BOMD", "AIMD", "MD轨迹", "VelocityVerlet")
_ANNEAL_KEYS = ("模拟退火", "退火")
_SCC_KEYS = ("单点能量", "静态自洽", "单点计算")
_SOLV_KEYS = ("隐式溶剂", "ALPB", "GBSA", "logP", "logKow", "分配系数")
_XTB_KEYS = ("GFN2-xTB", "GFN2", "GFN1", "扩展紧束缚")
_TRANSPORT_KEYS = ("NEGF", "透射谱", "分子结", "局域电流", "ContactHamiltonian")
_BARRIER_KEYS = ("反应垒", "能垒", "势垒")
_EDYN_KEYS = ("电子动力学", "时域光谱", "Ehrenfest", "ElectronDynamics")
_REKS_KEYS = ("REKS", "SSR22", "多参考")
_GSM_KEYS = ("反应路径", "增长串", "Diels-Alder")
_BOUNDARY_KEYS = ("螺旋边界", "HelicalUniform", "螺旋几何")
_ASE_KEYS = ("ASE DFTB", "ASE接口", "i-PI")
_2D_HOST_KEYS = ("石墨烯", "石墨炔", "二硫化钼", "二硫化钨", "氮化硼", "graphene", "MoS2", "mos2", "WS2", "ws2", "hBN", "hbn")
_DEFECT_KEYS = ("缺陷", "空位", "vacancy", "掺杂", "掺氮", "掺硼", "掺磷", "doped")


def _text_has_any(text: str, keys: tuple[str, ...]) -> bool:
    t = text or ""
    low = t.lower()
    return any((k.lower() in low) or (k in t) for k in keys if k)


def _word(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, (text or "").lower()))


def has_electronic_observable(text: str) -> bool:
    t = text or ""
    if _text_has_any(t, _ELECTRONIC_OBS_KEYS):
        return True
    return _word(t, r"\bbands?\b") or _word(t, r"\bdos\b") or _word(t, r"\bpdos\b")


def _strip_skip_opt(text: str) -> str:
    t = text or ""
    for k in _SKIP_OPT_KEYS:
        t = t.replace(k, " ")
        t = t.replace(k.lower(), " ")
        t = t.replace(k.upper(), " ")
    return t


def has_geom_opt_intent(text: str) -> bool:
    t = _strip_skip_opt(text)
    if _text_has_any(t, _GEOM_OPT_KEYS):
        return True
    if _word(t, r"\brelax(?:ation|ed|es)?\b") or _word(t, r"\boptimi[sz]e\b"):
        return True
    return "弛豫" in t and "激发态" not in t


def _detect_flags(text: str) -> dict[str, bool]:
    t = text or ""
    low = t.lower()
    phonon = _text_has_any(t, _PHONON_KEYS) or _word(t, r"\bphonons?\b")
    phonon_gap = "声子带隙" in t or "phonon gap" in low
    gap = (_text_has_any(t, _GAP_KEYS) or _word(t, r"\bband[\s-]?gaps?\b")) and not phonon_gap
    defect = _text_has_any(t, _DEFECT_KEYS) and _text_has_any(t, _2D_HOST_KEYS)
    band = (
        _text_has_any(t, _BAND_KEYS)
        or _word(t, r"\bbands?\b")
        or gap
        or ("电子结构" in t and not phonon and not defect)
    )
    if phonon and not _text_has_any(t, _BAND_KEYS) and not _word(t, r"\bbands?\b"):
        # 「声子带隙 / 声子」不按电子能带处理
        band = False
        gap = False
    vib = _text_has_any(t, _VIB_KEYS) or ("振动" in t and not phonon) or _word(t, r"\bir\b")
    flags = {
        "opt": has_geom_opt_intent(t),
        "skip_opt": _text_has_any(t, _SKIP_OPT_KEYS),
        "band": band,
        "gap": gap,
        "dos": _text_has_any(t, _DOS_KEYS) or _word(t, r"\bdos\b") or _word(t, r"\bpdos\b"),
        "scc": _text_has_any(t, _SCC_KEYS) or ("单点" in t and not band and not gap),
        "vib": vib,
        "phonon": phonon or phonon_gap,
        "td": _text_has_any(t, _TD_KEYS) or _word(t, r"\bcasida\b"),
        "td_relax": _text_has_any(t, _TD_RELAX_KEYS),
        "md": _text_has_any(t, _MD_KEYS) or _word(t, r"\bbomd\b"),
        "anneal": _text_has_any(t, _ANNEAL_KEYS),
        "solv": _text_has_any(t, _SOLV_KEYS),
        "xtb": _text_has_any(t, _XTB_KEYS) or _word(t, r"\bxtb\b"),
        "transport": _text_has_any(t, _TRANSPORT_KEYS) or "输运" in t,
        "barrier": _text_has_any(t, _BARRIER_KEYS),
        "edyn": _text_has_any(t, _EDYN_KEYS) and "Ehrenfest" not in t and "ehrenfest" not in low,
        "ehrenfest": "Ehrenfest" in t or "ehrenfest" in low,
        "reks": _text_has_any(t, _REKS_KEYS),
        "gsm": _text_has_any(t, _GSM_KEYS) or _word(t, r"\bgsm\b"),
        "boundary": _text_has_any(t, _BOUNDARY_KEYS),
        "defect": defect,
        "ase": bool(re.search(r"(?:ASE\s*DFTB|ASE接口|ASE 调|\bASE\b)", t)),
        "ipi": "i-PI" in t or bool(re.search(r"\bi-?pi\b", low)),
    }
    if flags["opt"] and flags["skip_opt"]:
        flags["skip_opt"] = False
    return flags


def _compose_job(flags: dict[str, bool]) -> dict[str, Any]:
    """互斥主任务 + 可叠加的 opt / DOS 附属阶段。"""
    notes: list[str] = []
    electronic = flags["band"] or flags["gap"] or flags["dos"]
    # 主载荷优先级：特定物理 > 电子结构 > 振动/激发 > MD > 优化
    kind = ""
    family = ""
    if flags["reks"]:
        kind, family = "dftb_reks", "reks"
    elif flags["gsm"]:
        kind, family = "dftb_gsm", "gsm"
    elif flags["transport"]:
        kind, family = "dftb_transport", "transport"
    elif flags["ehrenfest"]:
        kind, family = "dftb_ehrenfest", "electronic_dynamics"
    elif flags["edyn"]:
        kind, family = "dftb_edyn", "electronic_dynamics"
    elif flags["boundary"]:
        kind, family = "dftb_boundary", "boundary"
    elif flags["phonon"]:
        kind, family = "dftb_phonon", "properties"
    elif flags["barrier"]:
        kind, family = "dftb_barrier", "properties"
    elif flags["ipi"]:
        kind, family = "dftb_ipi", "interfaces"
    elif flags["ase"] and not electronic and not flags["opt"]:
        kind, family = "dftb_ase", "interfaces"
    elif flags["td_relax"]:
        kind, family = "dftb_td_relax", "linresp"
    elif flags["td"] and not (flags["band"] or flags["gap"] or flags["defect"]):
        kind, family = "dftb_td", "linresp"
    elif flags["td"] and (flags["band"] or flags["gap"]):
        kind, family = "dftb_band" if (flags["band"] or flags["gap"]) else "dftb_dos", "electronic"
        notes.append("同时提到吸收光谱与电子结构时，本作业先跑能带/DOS；吸收光谱请另提一次。")
    elif flags.get("defect"):
        kind, family = "dftb_defect", "defect_2d"
    elif flags["band"] or flags["gap"]:
        kind, family = "dftb_band", "electronic"
    elif flags["dos"]:
        kind, family = "dftb_dos", "electronic"
    elif flags["vib"]:
        kind, family = "dftb_vib", "geometry_vib"
    elif flags["anneal"]:
        kind, family = "dftb_md_anneal", "md"
    elif flags["md"]:
        kind, family = "dftb_md", "md"
    elif flags["solv"]:
        kind, family = "dftb_solv", "solvation"
    elif flags["xtb"]:
        kind, family = "dftb_xtb", "xtb_in_dftb"
    elif flags["opt"]:
        kind, family = "dftb_opt", "geometry_vib"
    elif flags["scc"]:
        kind, family = "dftb_scc", "electronic"

    if flags["vib"] and kind in ("dftb_band", "dftb_dos", "dftb_defect"):
        notes.append("本作业按「先优化再电子结构」执行；振动/红外需另提一次。")
    if flags["md"] and kind in ("dftb_band", "dftb_dos", "dftb_vib", "dftb_td"):
        notes.append("本作业不包含分子动力学；MD 请另提一次。")

    already_opt = kind in ("dftb_opt", "dftb_xtb", "dftb_solv", "dftb_td_relax", "dftb_barrier")
    default_pre = kind in (
        "dftb_band",
        "dftb_dos",
        "dftb_defect",
        "dftb_vib",
        "dftb_td",
        "dftb_md",
        "dftb_md_anneal",
    )
    pre_relax = False
    if not already_opt:
        if flags["opt"]:
            pre_relax = True
        elif flags["skip_opt"]:
            pre_relax = False
        elif default_pre:
            pre_relax = True

    stages: list[str] = []
    if pre_relax or kind == "dftb_opt":
        stages.append("opt")
    payload = {
        "dftb_scc": "scc",
        "dftb_band": "band",
        "dftb_dos": "dos",
        "dftb_defect": "defect",
        "dftb_vib": "vib",
        "dftb_td": "td",
        "dftb_td_relax": "td_relax",
        "dftb_md": "md",
        "dftb_md_anneal": "md_anneal",
        "dftb_solv": "solv",
        "dftb_xtb": "xtb",
        "dftb_phonon": "phonon",
        "dftb_transport": "transport",
        "dftb_barrier": "barrier",
        "dftb_edyn": "edyn",
        "dftb_ehrenfest": "ehrenfest",
        "dftb_reks": "reks",
        "dftb_gsm": "gsm",
        "dftb_boundary": "boundary",
        "dftb_ase": "ase",
        "dftb_ipi": "ipi",
    }.get(kind or "", "")
    if payload and payload not in stages:
        stages.append(payload)
    if flags["dos"] and kind in ("dftb_band", "dftb_defect") and "dos" not in stages:
        stages.append("dos")

    params: dict[str, Any] = {}
    if pre_relax:
        params["pre_relax"] = True
        params["max_steps"] = 50 if kind in ("dftb_vib", "dftb_td") else 80
    elif flags["skip_opt"] and not already_opt:
        params["pre_relax"] = False
    if flags["dos"] and kind in ("dftb_band", "dftb_defect"):
        params["want_dos"] = True
    if flags["gap"]:
        params["want_gap"] = True
    params["stages"] = stages
    if notes:
        params["compound_notes"] = notes
    return {
        "family": family,
        "kind": kind,
        "params": params,
        "stages": stages,
        "notes": notes,
    }


def resolve_nl_intent(text: str) -> dict[str, Any]:
    """把一句（可含多步）中文/英文指令解析成单一作业的 kind + 阶段。"""
    flags = _detect_flags(text)
    composed = _compose_job(flags)
    composed["flags"] = flags
    if not composed.get("kind"):
        composed["params"] = {"prompt": text, "stages": []}
        composed["stages"] = []
        composed["notes"] = []
        composed["family"] = ""
    else:
        composed["params"] = {**composed["params"], "prompt": text}
    return composed


def match_family_from_text(text: str) -> Optional[str]:
    resolved = resolve_nl_intent(text)
    if resolved.get("family"):
        return str(resolved["family"])
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
