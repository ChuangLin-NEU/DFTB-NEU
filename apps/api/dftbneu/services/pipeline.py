"""自然语言 → 方案 → 投递 → 出图 → 成稿。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from dftb_engine.capability import (
    default_kind_for_family,
    list_supported_commands,
    match_family_from_text,
)
from dftb_engine.inputs import build_inputs_for_kind
from dftb_engine.maturity import maturity_for_kind, submit_blocked_message
from dftb_engine.service import DftbEngine

from .. import db
from ..config import load_user_config, settings
from . import deepseek
from . import playbooks as pb_svc
from . import structure_mp


# 课堂示例：已测通；每种材料只出现一次，覆盖多类性质
EXAMPLES = [
    {
        "id": "si_band",
        "title": "硅 · 能带与 DOS",
        "prompt": "用 DFTB+ 计算硅晶体能带和 DOS",
        "family": "electronic",
        "kind": "dftb_band",
        "needs_structure": True,
        "structure_file": "si_diamond.poscar",
        "formula": "Si",
        "group": "solid",
        "sk_set": "pbc",
    },
    {
        "id": "graphene_band",
        "title": "石墨烯 · 能带",
        "prompt": "用 DFTB+ 计算石墨烯能带结构",
        "family": "electronic",
        "kind": "dftb_band",
        "needs_structure": True,
        "structure_file": "graphene.poscar",
        "formula": "C",
        "group": "solid",
        "params": {"third_order": False},
    },
    {
        "id": "h2o_opt",
        "title": "水 · 几何优化",
        "prompt": "用 DFTB+ 对水分子做几何优化",
        "family": "geometry_vib",
        "use_recipes_water": True,
        "kind": "dftb_opt",
        "formula": "H2O",
        "group": "research",
        "params": {"max_steps": 50},
    },
    {
        "id": "ch4_vib",
        "title": "甲烷 · 振动频率",
        "prompt": "用 DFTB+ 计算甲烷分子（CH4）振动频率",
        "family": "geometry_vib",
        "kind": "dftb_vib",
        "needs_structure": True,
        "structure_file": "ch4.gen",
        "formula": "CH4",
        "group": "research",
    },
    {
        "id": "nh3_md",
        "title": "氨 · BOMD 动力学",
        "prompt": "用 DFTB+ 跑氨分子（NH3）短程 BOMD",
        "family": "md",
        "kind": "dftb_md",
        "needs_structure": True,
        "structure_file": "nh3.gen",
        "formula": "NH3",
        "group": "research",
        "params": {"md_steps": 80, "timestep_fs": 0.5},
    },
    {
        "id": "casida",
        "title": "苯 · Casida 吸收光谱",
        "prompt": "用 DFTB+ Casida 线性响应计算苯分子（C6H6）吸收光谱",
        "family": "linresp",
        "kind": "dftb_td",
        "needs_structure": True,
        "structure_file": "benzene.gen",
        "formula": "C6H6",
        "group": "research",
        "params": {"n_excitations": 6},
    },
    {
        "id": "h2co_xtb",
        "title": "甲醛 · GFN2-xTB 优化",
        "prompt": "用 DFTB+ 内置 GFN2-xTB 优化甲醛分子（H2CO）",
        "family": "xtb_in_dftb",
        "kind": "dftb_xtb",
        "needs_structure": True,
        "structure_file": "h2co.gen",
        "formula": "H2CO",
        "group": "research",
        "params": {"max_steps": 50},
    },
]

# 无结构时禁止默认水分子的能力族 / kind
_STRUCTURE_FAMILIES = {"defect_2d", "phonon", "transport", "boundary"}
_STRUCTURE_KINDS = {"dftb_band", "dftb_phonon", "dftb_transport"}
_SOLID_HINTS = (
    "硅",
    "Si",
    "晶体",
    "能带",
    "DOS",
    "石墨烯",
    "二维",
    "缺陷",
    "空位",
    "声子",
    "周期",
    "POSCAR",
    "超胞",
    "布里渊",
    "纳米带",
    "钝化",
)


def _is_custom_structure_request(text: str) -> bool:
    """纳米带/钝化等定制结构：可先用近似模板生成，并提示用户上传覆盖。"""
    t = text or ""
    low = t.lower()
    keys = (
        "纳米带",
        "nanoribbon",
        "nano-ribbon",
        "nano ribbon",
        "钝化",
        "passivat",
        "扶手椅",
        "锯齿",
        "armchair",
        "zigzag",
        "zig-zag",
    )
    return any(k in t or k in low for k in keys)


# 兼容旧名
def _needs_uploaded_structure(text: str) -> bool:
    return _is_custom_structure_request(text)


def teaching_examples() -> list[dict]:
    return EXAMPLES


def _engine() -> DftbEngine:
    from dftb_engine.local_runner import resolve_wsl_distro

    cfg = load_user_config()
    preferred = str(cfg.get("wsl_distro") or settings.wsl_distro or "")
    distro = resolve_wsl_distro(preferred)
    if distro and distro != cfg.get("wsl_distro"):
        cfg["wsl_distro"] = distro
        try:
            from ..config import save_user_config

            save_user_config(cfg)
        except Exception:
            pass
    return DftbEngine(wsl_distro=distro)


def _mentions_water(text: str) -> bool:
    return any(k in (text or "") for k in ("水", "H2O", "h2o"))


def _is_absorb_or_td_request(text: str, family: str = "", kind: str = "") -> bool:
    """吸收光谱 / Casida / TD-DFTB 类请求。"""
    if family == "linresp" or kind in ("dftb_td", "dftb_td_relax"):
        return True
    return any(
        k in (text or "")
        for k in ("吸收光谱", "Casida", "casida", "TD-DFTB", "td-dftb", "线性响应", "激发态光谱")
    )


def _allows_water_default(text: str, family: str, kind: str, *, example_water: bool) -> bool:
    """仅在明确提到水、或命中含水分子示例时，才默认为 H2O。

    不再因单独出现「分子 / Casida」而静默套用水分子。
    """
    if example_water:
        return True
    if family in _STRUCTURE_FAMILIES or kind in _STRUCTURE_KINDS:
        return False
    if any(h in text for h in _SOLID_HINTS) and not _mentions_water(text):
        return False
    return _mentions_water(text)


def _requires_structure(text: str, family: str, kind: str, *, example_water: bool) -> bool:
    if example_water:
        return False
    if family in _STRUCTURE_FAMILIES or kind in _STRUCTURE_KINDS:
        return True
    if any(h in text for h in _SOLID_HINTS) and not _mentions_water(text):
        return True
    # 吸收光谱未点名分子时，要求用户补充材料（勿静默用水）
    if _is_absorb_or_td_request(text, family, kind) and not _mentions_water(text):
        return True
    return False


def _missing_structure_message(
    text: str, family: str, kind: str, *, mp_info: Optional[dict[str, Any]] = None
) -> str:
    mp_info = mp_info or {}
    if _is_absorb_or_td_request(text, family, kind) and not _mentions_water(text):
        return (
            "计算吸收光谱需要指定分子。"
            "请写明分子名称（如「苯分子」「C6H6」），或上传 GEN/POSCAR；"
            "也可点击主页举例「苯 · 吸收光谱」。"
        )
    err = mp_info.get("error") or ""
    q = mp_info.get("query") or ""
    if q:
        return (
            f"该任务需要晶体/周期结构。内置库中无「{q}」，且从 Materials Project 获取失败：{err}。"
            "请上传 POSCAR/GEN，或在「课程」页载入结构。"
        )
    if family in _STRUCTURE_FAMILIES or kind in _STRUCTURE_KINDS or any(
        h in text for h in _SOLID_HINTS
    ):
        return (
            "该任务需要晶体/周期结构。内置示例未命中，也未能识别可拉取的材料。"
            "请上传 POSCAR/GEN，或在「课程」页载入结构。"
        )
    return (
        "请先指定材料或提供结构文件。"
        "分子任务可写明「水分子/H2O」使用内置几何，或上传 GEN/POSCAR。"
    )


def _refine_kind(text: str, family: str, kind: str) -> tuple[str, dict[str, Any]]:
    """按自然语言细化 kind（能带 / DOS 等）。"""
    params: dict[str, Any] = {"prompt": text}
    low = (text or "").lower()
    has_band = any(k in text for k in ("能带", "band", "Band")) or "band" in low
    has_dos = any(k in text for k in ("态密度", "DOS", "dos", "PDOS", "pdos"))
    intent = None
    try:
        from dftb_engine import structure_intent as si

        intent = si.parse_structure_intent(text)
    except Exception:
        intent = None
    is_vacancy = bool(intent and intent.get("vacancy")) or any(
        k in text for k in ("空位", "vacancy")
    ) or "vacancy" in low
    is_doped = bool(intent and intent.get("substitute")) or any(
        k in text for k in ("掺杂", "掺氮", "掺硼", "掺磷")
    ) or "doped" in low
    is_2d_host = bool(
        intent
        and intent.get("material") in {"graphene", "MoS2", "WS2", "BN"}
    ) or any(k in text for k in ("石墨烯", "二硫化钼", "二硫化钨", "氮化硼")) or any(
        k in low for k in ("graphene", "mos2", "ws2", "hbn")
    )
    is_defect = (is_vacancy or is_doped) and is_2d_host
    if has_band:
        kind = "dftb_band"
        family = "electronic"
    if has_dos and not has_band:
        kind = "dftb_dos"
        family = "electronic"
    if has_dos:
        params["want_dos"] = True
    if has_band and has_dos:
        kind = "dftb_band"
        params["want_dos"] = True
    # 二维缺陷/掺杂：无显式能带/DOS 时走 defect；自旋由意图或空位默认开启
    if is_defect:
        if not has_band and not has_dos:
            kind = "dftb_defect"
            family = "defect_2d"
        if intent and intent.get("spin_polarized"):
            params["spin_polarized"] = True
            params["spin_constants"] = True
            if intent.get("unpaired_electrons") is not None:
                params.setdefault(
                    "unpaired_electrons", float(intent.get("unpaired_electrons") or 0.0)
                )
            else:
                params.setdefault("unpaired_electrons", 1.0)
        elif is_vacancy:
            params["spin_polarized"] = True
            params["spin_constants"] = True
            params.setdefault("unpaired_electrons", 1.0)
        params.setdefault("dimensionality", "2d")
    elif intent and intent.get("spin_polarized"):
        params["spin_polarized"] = True
        params["spin_constants"] = True
        if intent.get("unpaired_electrons") is not None:
            params.setdefault(
                "unpaired_electrons", float(intent.get("unpaired_electrons") or 0.0)
            )
        else:
            params.setdefault("unpaired_electrons", 1.0)
    # 周期电子结构 / 振动 / Casida：默认先几何优化
    if kind in ("dftb_band", "dftb_dos", "dftb_defect"):
        params.setdefault("pre_relax", True)
        params.setdefault("max_steps", 80)
    if kind in ("dftb_vib", "dftb_td"):
        params.setdefault("pre_relax", True)
        params.setdefault("max_steps", 50)
    return kind, params


def _read_bundled_structure(fname: str, *, formula: str = "", query: str = "") -> dict[str, Any]:
    """读取随软件分发的课次/示例结构（POSCAR 或分子 GEN）。"""
    from pathlib import Path

    if not fname:
        return {}
    candidates = []
    try:
        candidates.append(settings.root / "templates" / "courses" / "structures" / fname)
    except Exception:
        pass
    candidates.extend(
        [
            Path(__file__).resolve().parents[4] / "templates" / "courses" / "structures" / fname,
            Path(__file__).resolve().parents[3] / "templates" / "courses" / "structures" / fname,
        ]
    )
    lower = fname.lower()
    for p in candidates:
        try:
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
            out: dict[str, Any] = {
                "material_id": f"local:{fname}",
                "formula": formula or "",
                "source": "local-template",
                "query": query or formula or fname,
            }
            if lower.endswith(".gen") or lower.endswith(".xyz"):
                out["gen"] = text
                out["poscar"] = ""
            else:
                out["poscar"] = text
                out["gen"] = ""
            return out
        except Exception:
            continue
    return {}


def _structure_hit(info: dict[str, Any]) -> bool:
    return bool((info or {}).get("poscar") or (info or {}).get("gen"))


def _local_structure_fallback(query: str, text: str) -> dict[str, Any]:
    """优先匹配内置示例结构；再按关键词映射本地 POSCAR。"""
    q = (query or "").strip()
    t = text or ""
    low = t.lower()

    for ex in EXAMPLES:
        fname = str(ex.get("structure_file") or "")
        if not fname:
            continue
        if ex["prompt"] in t or ex["title"] in t or ex.get("id") == q:
            hit = _read_bundled_structure(
                fname, formula=str(ex.get("formula") or ""), query=q or str(ex.get("formula") or "")
            )
            if _structure_hit(hit):
                return hit

    fname = ""
    formula = ""
    # 空位/缺陷：不在此处直接返回预制空位文件；由上层「完美结构→挖空」生成
    if q == "Si" or "硅" in t or "silicon" in low:
        fname, formula = "si_diamond.poscar", "Si"
    elif q in ("石墨烯", "Graphene", "C") or "石墨烯" in t or "graphene" in low:
        fname, formula = "graphene.poscar", "C"
    elif any(k in t for k in ("苯", "benzene", "C6H6", "c6h6")) or q in (
        "苯",
        "benzene",
        "C6H6",
    ):
        fname, formula = "benzene.gen", "C6H6"
    elif any(k in t for k in ("甲烷", "CH4", "ch4")) or q in ("甲烷", "CH4"):
        fname, formula = "ch4.gen", "CH4"
    elif any(k in t for k in ("氨", "NH3", "nh3")) or q in ("氨", "NH3"):
        fname, formula = "nh3.gen", "NH3"
    elif any(k in t for k in ("甲醛", "H2CO", "h2co", "CH2O")) or q in ("甲醛", "H2CO"):
        fname, formula = "h2co.gen", "H2CO"
    elif q == "MoS2" or "二硫化钼" in t:
        return {}
    if not fname:
        return {}
    return _read_bundled_structure(fname, formula=formula, query=q or formula)


def _pristine_structure_for_material(material: str, text: str = "", *, intent: Optional[dict] = None) -> dict[str, Any]:
    """获取完美晶体（本地模板优先，再 MP），供后续改造。"""
    from dftb_engine.band_paths import infer_mp_query

    intent = intent or {}
    mat = (material or "").strip()
    fname = str(intent.get("file") or "")
    formula = str(intent.get("formula") or "")
    q = str(intent.get("mp_query") or mat)
    if fname:
        hit = _read_bundled_structure(fname, formula=formula, query=q or formula)
        if _structure_hit(hit):
            return hit
    if mat == "graphene" and not fname:
        hit = _read_bundled_structure("graphene.poscar", formula="C", query="石墨烯")
        if _structure_hit(hit):
            return hit
        q = "石墨烯"
    elif mat == "Si" and not fname:
        hit = _read_bundled_structure("si_diamond.poscar", formula="Si", query="Si")
        if _structure_hit(hit):
            return hit
        q = "Si"
    else:
        q = q or infer_mp_query(text) or mat
        local = _local_structure_fallback(q, text)
        if _structure_hit(local):
            return local
    if not q:
        return {}
    try:
        data = structure_mp.fetch_poscar(q)
        return {
            "poscar": data.get("poscar") or "",
            "material_id": data.get("material_id"),
            "formula": data.get("formula"),
            "source": "materials-project",
            "query": q,
        }
    except Exception as e:
        return {"error": str(e), "query": q}


def _build_derived_structure(text: str) -> dict[str, Any]:
    """通用流程：解析意图 → 完美结构 → 超胞/空位/掺杂等变换。"""
    from dftb_engine import structure_intent as si

    intent = si.parse_structure_intent(text)
    if not intent:
        return {}
    # 仅复杂定制且无宿主：无法自动生成
    if intent.get("need_upload") and not intent.get("material"):
        return {
            "error": "需要上传定制结构",
            "query": "定制结构",
            "approximate": True,
            "approx_note": "纳米带/钝化等复杂几何请上传 GEN/POSCAR。",
        }
    pristine = _pristine_structure_for_material(
        str(intent.get("material") or ""), text, intent=intent
    )
    if not _structure_hit(pristine):
        # 石墨烯空位最后回退旧模板
        if intent.get("vacancy") and intent.get("material") == "graphene":
            return _read_bundled_structure(
                "graphene_vacancy.poscar", formula="C", query="石墨烯空位"
            )
        return pristine

    transforms = list(intent.get("transforms") or [])
    # 只要完美结构、无变换（例如仅 need_upload 的纳米带）：返回近似完美结构并提示上传
    if not transforms:
        note = si.describe_intent(intent)
        out = dict(pristine)
        out["approximate"] = True
        out["approx_note"] = note
        out["message"] = note
        out["structure_intent"] = intent
        out["source"] = out.get("source") or "local-template"
        return out

    try:
        poscar = si.apply_structure_transforms(str(pristine.get("poscar") or ""), intent)
    except Exception:
        if intent.get("vacancy") and intent.get("material") == "graphene":
            return _read_bundled_structure(
                "graphene_vacancy.poscar", formula="C", query="石墨烯空位"
            )
        return {}

    note = si.describe_intent(intent)
    ops = "-".join(tr.get("op", "") for tr in transforms)
    return {
        "poscar": poscar,
        "material_id": f"derived:{ops}:{intent.get('material') or 'mat'}",
        "formula": str(pristine.get("formula") or intent.get("formula") or ""),
        "source": "pristine+derived",
        "query": f"{intent.get('material')}-{ops}",
        "structure_intent": intent,
        "vacancy": intent.get("vacancy"),
        "substitute": intent.get("substitute"),
        "approx_note": note,
        "message": note,
        "approximate": bool(intent.get("need_upload")),
    }


def _try_fetch_mp_structure(text: str) -> dict[str, Any]:
    """缺结构时：若有改造意图则「完美结构→按需修改」；否则内置模板 / MP。"""
    from dftb_engine.band_paths import infer_mp_query
    from dftb_engine import structure_intent as si

    # 1) 通用衍生：超胞 / 空位 / 掺杂 / 复杂定制提示
    if si.parse_structure_intent(text):
        built = _build_derived_structure(text)
        if _structure_hit(built):
            return built

    local = _local_structure_fallback("", text)
    if _structure_hit(local):
        if _is_custom_structure_request(text):
            local = dict(local)
            local["approximate"] = True
            local["approx_note"] = (
                "当前为内置近似结构（非边缘氢钝化纳米带）。"
                "若不符合需求，请上传自己的 GEN/POSCAR 覆盖后再确认计算。"
            )
        return local

    q = infer_mp_query(text)
    if not q:
        return {}
    local_q = _local_structure_fallback(q, text)
    if _structure_hit(local_q):
        if _is_custom_structure_request(text):
            local_q = dict(local_q)
            local_q["approximate"] = True
            local_q["approx_note"] = (
                "当前为内置近似结构。若需边缘氢钝化纳米带等定制几何，请上传 GEN/POSCAR 覆盖。"
            )
        return local_q
    try:
        data = structure_mp.fetch_poscar(q)
        out = {
            "poscar": data.get("poscar") or "",
            "material_id": data.get("material_id"),
            "formula": data.get("formula"),
            "source": "materials-project",
            "query": q,
        }
        if _is_custom_structure_request(text):
            out["approximate"] = True
            out["approx_note"] = (
                "当前结构来自材料库近似匹配。若不符合纳米带/钝化等定制需求，请上传 GEN/POSCAR 覆盖。"
            )
        return out
    except Exception as e:
        return {"error": str(e), "query": q}


def preview_hsd(
    text: str,
    *,
    poscar: str = "",
    gen: str = "",
    family_hint: str = "",
    kind_hint: str = "",
) -> dict[str, Any]:
    # 用户一开始就上传了结构：后续勿提示「近似模板」
    struct_from_request = bool((poscar or "").strip() or (gen or "").strip())
    family = match_family_from_text(text) or "geometry_vib"
    kind = default_kind_for_family(family)
    example_water = False
    matched_ex: dict[str, Any] | None = None
    for ex in EXAMPLES:
        if ex["prompt"] in text or ex["title"] in text:
            family = ex["family"]
            kind = ex.get("kind") or kind
            example_water = bool(ex.get("use_recipes_water"))
            matched_ex = ex
            break
    if family_hint:
        family = family_hint
    if kind_hint:
        kind = kind_hint
    # 按关键词细化能带/DOS；已有 kind_hint / 示例 kind 时保留 kind，只补充 want_dos
    refined_kind, extra_params = _refine_kind(text, family, kind)
    if matched_ex:
        if matched_ex.get("sk_set"):
            extra_params["sk_set"] = str(matched_ex["sk_set"])
        for k, v in dict(matched_ex.get("params") or {}).items():
            extra_params.setdefault(k, v)
        if matched_ex.get("formula"):
            extra_params.setdefault("formula", str(matched_ex["formula"]))
    if not kind_hint:
        # 若示例已给出具体 kind，优先示例；否则用关键词细化
        matched_example = any(
            ex["prompt"] in text or ex["title"] in text for ex in EXAMPLES
        )
        if not matched_example:
            kind = refined_kind
    if any(k in text for k in ("能带", "DOS", "态密度", "band", "dos")):
        family = family_hint or "electronic"

    has_struct = bool(poscar or gen)
    needs_struct = _requires_structure(text, family, kind, example_water=example_water)
    mp_info: dict[str, Any] = {}
    if needs_struct and not has_struct:
        mp_info = _try_fetch_mp_structure(text)
        if mp_info.get("poscar"):
            poscar = str(mp_info["poscar"])
            has_struct = True
        elif mp_info.get("gen"):
            gen = str(mp_info["gen"])
            has_struct = True
        else:
            pb = pb_svc.playbook_meta(family)
            return {
                "ok": False,
                "needs_structure": True,
                "family": family,
                "kind": kind,
                "sk_set": pb.get("sk_set_default") or None,
                "elements": [],
                "files": {},
                "hsd_preview": "",
                "playbook": pb,
                "message": _missing_structure_message(
                    text, family, kind, mp_info=mp_info
                ),
                "mp_attempt": mp_info,
            }

    use_water = (not has_struct) and _allows_water_default(
        text, family, kind, example_water=example_water
    )
    if not has_struct and not use_water:
        mp_info = _try_fetch_mp_structure(text)
        if mp_info.get("poscar"):
            poscar = str(mp_info["poscar"])
            has_struct = True
            use_water = False
        elif mp_info.get("gen"):
            gen = str(mp_info["gen"])
            has_struct = True
            use_water = False
        else:
            pb = pb_svc.playbook_meta(family)
            return {
                "ok": False,
                "needs_structure": True,
                "family": family,
                "kind": kind,
                "sk_set": pb.get("sk_set_default") or None,
                "elements": [],
                "files": {},
                "hsd_preview": "",
                "playbook": pb,
                "message": _missing_structure_message(
                    text, family, kind, mp_info=mp_info
                ),
                "mp_attempt": mp_info,
            }

    # 示例命中时保留 kind；否则 _refine_kind 可能覆盖 —— 对已匹配示例再跑一次微调 DOS 标志
    if matched_ex:
        kind = matched_ex.get("kind") or kind
        if "DOS" in matched_ex.get("prompt", "") or "态密度" in text or "DOS" in text:
            extra_params["want_dos"] = True
    elif "DOS" in text or "态密度" in text:
        extra_params["want_dos"] = True

    if mp_info.get("formula"):
        extra_params.setdefault("formula", str(mp_info.get("formula") or ""))
    elif use_water:
        extra_params.setdefault("formula", "H2O")
    # 衍生空位/掺杂：即便文案未写「自旋」，也按意图默认开自旋极化
    mid = str(mp_info.get("material_id") or "") + " " + str(mp_info.get("query") or "")
    intent_mp = mp_info.get("structure_intent") or {}
    if (
        intent_mp.get("spin_polarized")
        or "vacancy" in mid.lower()
        or "空位" in mid
        or "substitute" in mid.lower()
    ):
        extra_params.setdefault("spin_polarized", True)
        extra_params.setdefault("spin_constants", True)
        if intent_mp.get("unpaired_electrons") is not None:
            extra_params.setdefault(
                "unpaired_electrons", float(intent_mp.get("unpaired_electrons") or 0.0)
            )
        else:
            extra_params.setdefault("unpaired_electrons", 1.0)
    extra_params.setdefault("prompt", text)
    sk_for_build = str(extra_params.get("sk_set") or (matched_ex or {}).get("sk_set") or "")
    built = build_inputs_for_kind(
        kind,
        poscar=poscar,
        gen=gen,
        sk_set=sk_for_build,
        params=extra_params,
        use_recipes_water=use_water,
    )
    for name, content in list(built["files"].items()):
        if name.endswith(".hsd"):
            built["files"][name] = content.replace(
                "$HOME/.cmats/share/dftb/sk",
                "$HOME/.dftb-neu/share/dftb/sk",
            )
    pb = pb_svc.playbook_meta(family)
    sk = built.get("sk_set") or pb.get("sk_set_default")
    maturity = maturity_for_kind(kind)
    sk_cov = built.get("sk_coverage") or (built.get("params") or {}).get("_sk_coverage") or {}
    tips = list(_param_tips(kind, sk or "", maturity=maturity, sk_coverage=sk_cov))
    out = {
        "ok": True,
        "needs_structure": False,
        "family": family,
        "kind": kind,
        "sk_set": sk,
        "elements": built.get("elements"),
        "files": built["files"],
        "hsd_preview": built["files"].get("dftb_in.hsd", "")[:4000],
        "playbook": pb,
        "used_default_water": use_water,
        "params": extra_params,
        "maturity": maturity,
        "allow_submit": bool(maturity.get("allow_submit")),
        "sk_coverage": sk_cov,
        "param_tips": tips,
    }
    # SK 缺失：允许预览，但禁止投递并如实说明
    if sk_cov and sk_cov.get("checked") and not sk_cov.get("ok"):
        out["allow_submit"] = False
        out["ok"] = True
        out["message"] = str(sk_cov.get("message") or "SK 参数不完整，暂不可投递。")
        tips.insert(
            0,
            {
                "key": "sk_missing",
                "title": "SK 不完整",
                "text": out["message"],
            },
        )
        out["param_tips"] = tips
    if not maturity.get("allow_submit"):
        out["allow_submit"] = False
        block = submit_blocked_message(kind) or maturity.get("note") or ""
        out["message"] = block
        tips.insert(
            0,
            {
                "key": "maturity",
                "title": f"功能状态：{maturity.get('label') or '未闭环'}",
                "text": block,
            },
        )
        out["param_tips"] = tips
    if poscar:
        out["poscar"] = poscar
    geo_gen = gen or (built.get("files") or {}).get("geo.gen") or ""
    if geo_gen and not poscar:
        out["gen"] = geo_gen
    if mp_info.get("material_id") or mp_info.get("source"):
        out["mp"] = {
            "material_id": mp_info.get("material_id"),
            "formula": mp_info.get("formula"),
            "query": mp_info.get("query"),
            "source": mp_info.get("source") or "",
            "approximate": bool(mp_info.get("approximate")),
            "approx_note": str(mp_info.get("approx_note") or ""),
            "vacancy": mp_info.get("vacancy") or {},
            "substitute": mp_info.get("substitute") or {},
            "structure_intent": mp_info.get("structure_intent") or {},
        }
    elif use_water:
        out["mp"] = {"formula": "H2O", "source": "recipes-water", "query": "water"}
    # 自然语言先生成结构（完美晶体→按需改造）；用户不满意可再上传覆盖
    derived_src = str(mp_info.get("source") or "")
    if (not struct_from_request) and (
        mp_info.get("approximate")
        or derived_src in ("pristine+vacancy", "pristine+derived")
        or str(mp_info.get("material_id") or "").startswith("derived:")
        or _is_custom_structure_request(text)
    ):
        note = str(mp_info.get("approx_note") or mp_info.get("message") or "").strip() or (
            "当前为系统生成的结构；若不满意，请上传自己的 GEN/POSCAR 覆盖后再确认计算。"
        )
        tips.insert(
            0,
            {
                "key": "structure_override",
                "title": "结构可覆盖",
                "text": note,
            },
        )
        out["param_tips"] = tips
        out["structure_approximate"] = True
        if out.get("allow_submit", True):
            out["message"] = note
    return out


def _structure_source_label(mp: dict[str, Any]) -> str:
    """结构来源文案：区分内置模板、衍生改造与 Materials Project。"""
    if not mp:
        return ""
    mid = str(mp.get("material_id") or "")
    formula = str(mp.get("formula") or "").strip()
    source = str(mp.get("source") or "")
    formula_bit = f"（{formula}）" if formula else ""
    intent = mp.get("structure_intent") or {}
    if source in ("pristine+vacancy", "pristine+derived") or mid.startswith("derived:"):
        note = str(mp.get("approx_note") or "").strip()
        if note:
            return f"结构：{note}"
        bits: list[str] = ["完美晶体"]
        sc = intent.get("supercell")
        if sc and tuple(sc) != (1, 1, 1):
            bits.append(f"{sc[0]}×{sc[1]}×{sc[2]} 超胞")
        vac = mp.get("vacancy") or intent.get("vacancy") or {}
        if vac:
            bits.append(f"挖空 {vac.get('n_remove', '?')}×{vac.get('element', '?')}")
        sub = mp.get("substitute") or intent.get("substitute") or {}
        if sub:
            bits.append(f"{sub.get('host', '?')}→{sub.get('dopant', '?')} 掺杂")
        return f"结构：{' → '.join(bits)}{formula_bit}。"
    is_local = source in ("local-template", "local") or mid.startswith("local:")
    name = mid
    if is_local and mid.startswith("local:"):
        name = mid.split(":", 1)[1]
    if is_local:
        return f"结构：内置模板 `{name}`{formula_bit}。"
    if mid or formula:
        return f"结构：Materials Project `{mid or formula}`{formula_bit if mid else ''}。"
    return ""


def _structure_source_short(mp: dict[str, Any]) -> str:
    """任务讲义等处的短标签。"""
    if not mp:
        return ""
    mid = str(mp.get("material_id") or "")
    formula = str(mp.get("formula") or "").strip()
    source = str(mp.get("source") or "")
    intent = mp.get("structure_intent") or {}
    if source in ("pristine+vacancy", "pristine+derived") or mid.startswith("derived:"):
        tags: list[str] = ["完美→改造"]
        if intent.get("vacancy") or mp.get("vacancy"):
            tags.append("空位")
        if intent.get("substitute") or mp.get("substitute"):
            tags.append("掺杂")
        sc = intent.get("supercell")
        if sc and tuple(sc) != (1, 1, 1):
            tags.append(f"{sc[0]}×{sc[1]}×{sc[2]}")
        return " · ".join(tags) + (f"（{formula}）" if formula else "")
    is_local = source in ("local-template", "local") or mid.startswith("local:")
    if is_local:
        name = mid.split(":", 1)[1] if mid.startswith("local:") else (mid or "内置")
        return f"内置模板 · {name}" + (f"（{formula}）" if formula else "")
    if mid or formula:
        return (mid or "") + (f"（{formula}）" if formula else "")
    return ""


async def handle_chat(
    message: str,
    *,
    project_id: Optional[str] = None,
    poscar: str = "",
    gen: str = "",
    hsd: str = "",
    confirm_submit: bool = False,
    family_hint: str = "",
    kind_hint: str = "",
) -> dict[str, Any]:
    """对话编排：匹配能力族 → 预览 HSD →（确认后）投递。"""
    msg = (message or "").strip()
    if not msg:
        return {"reply": "请描述计算意图，例如「用 DFTB+ 计算硅晶体能带」。", "actions": []}

    if any(k in msg for k in ("部署", "安装 DFTB", "隔离部署", "一键部署", "一件部署")):
        return {
            "reply": "请打开「环境」页，确认 WSL2 就绪后执行「部署到本机」。",
            "actions": [{"type": "open_deploy"}],
        }

    # 确认投递：直接使用课题已存 protocol/structure，避免输入被清空后重推断失败
    if confirm_submit and project_id:
        return submit_project(project_id, poscar=poscar, gen=gen, hsd=hsd)

    if project_id and (not family_hint or not kind_hint):
        existing = db.get_project(project_id) or {}
        proto = existing.get("protocol") or {}
        family_hint = family_hint or str(proto.get("dftb_family") or "")
        kind_hint = kind_hint or str(proto.get("kind") or "")

    preview = preview_hsd(
        msg, poscar=poscar, gen=gen, family_hint=family_hint, kind_hint=kind_hint
    )
    if preview.get("needs_structure") and not preview.get("ok"):
        return {
            "reply": preview.get("message") or "需要结构文件。",
            "project_id": project_id,
            "preview": preview,
            "actions": [{"type": "need_structure"}, {"type": "open_courses"}],
            "ok": False,
        }

    if not project_id:
        proj = db.create_project(title=msg[:40] or "DFTB+ 任务", idea={"prompt": msg})
        project_id = proj["id"]
    else:
        proj = db.get_project(project_id) or db.create_project(title=msg[:40])
        project_id = proj["id"]

    hsd_text = preview.get("hsd_preview") or ""
    tips = list(preview.get("param_tips") or []) or _param_tips(
        preview.get("kind") or "", preview.get("sk_set") or ""
    )
    protocol = {
        "dftb_family": preview["family"],
        "kind": preview["kind"],
        "sk_set": preview.get("sk_set"),
        "prompt": msg,
        "hsd_preview": hsd_text,
        "hsd_default": hsd_text,
        "playbook_id": (preview.get("playbook") or {}).get("playbook_id"),
        "success_criteria": (preview.get("playbook") or {}).get("success_criteria") or [],
        "param_tips": tips,
        "maturity": preview.get("maturity") or maturity_for_kind(preview.get("kind") or ""),
        "allow_submit": bool(preview.get("allow_submit", True)),
    }
    structure: dict[str, Any] = {}
    # 优先用本次预览结构（含内置模板 / MP / 默认水分子 geo.gen）
    files_prev = preview.get("files") or {}
    poscar_eff = poscar or preview.get("poscar") or files_prev.get("POSCAR") or ""
    gen_eff = gen or preview.get("gen") or files_prev.get("geo.gen") or ""
    # 只保留一种主结构，避免 POSCAR（如石墨烯）与旧 GEN（如苯）并存污染投递
    if poscar_eff:
        structure["poscar"] = poscar_eff
    elif gen_eff:
        structure["gen"] = gen_eff
    if preview.get("mp"):
        structure["mp"] = preview["mp"]
    # 始终写入本次结构，避免空 dict 被当成 falsy 而残留上一任务晶体
    db.update_project(
        project_id,
        protocol=protocol,
        phase="protocol",
        idea={"prompt": msg},
        structure=structure,
    )

    llm_note = _local_calc_brief(preview, msg)
    try:
        llm_reply = await deepseek.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 DFTB+ 课堂助教。用简短中文说明将做的计算（方法、SK、任务类型），"
                        "不要营销话术，不要说「一键」。不超过 120 字。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"用户：{msg}\n能力族：{preview['family']}\nkind：{preview['kind']}\n"
                        f"SK：{preview.get('sk_set')}\nplaybook：{(preview.get('playbook') or {}).get('playbook_name')}"
                    ),
                },
            ]
        )
        if (llm_reply or "").strip():
            llm_note = llm_reply.strip()
    except Exception as e:
        # 助教说明失败不影响计算；本地 brief 已写好，仅附一句短提示
        err = str(e)
        if "欠费" in err or "账户异常" in err or "暂不可用" in err:
            llm_note = f"{llm_note}\n（{err}）"
        else:
            llm_note = f"{llm_note}\n（课堂助教说明暂不可用，不影响计算。）"

    criteria = (preview.get("playbook") or {}).get("success_criteria") or []
    crit_line = ("验收：" + "；".join(criteria[:2]) + "。") if criteria else ""
    mp = preview.get("mp") or {}
    mp_line = _structure_source_label(mp)
    if mp_line:
        mp_line += "\n"
    approx_line = ""
    if preview.get("structure_approximate") or mp.get("approximate"):
        approx_line = (
            str(preview.get("message") or mp.get("approx_note") or "").strip()
            or "当前为系统近似结构；若不满意请上传 GEN/POSCAR 覆盖。"
        )
        approx_line += "\n"
    mat = preview.get("maturity") or maturity_for_kind(preview.get("kind") or "")
    mat_line = f"功能状态：{mat.get('label') or '未知'} — {mat.get('note') or ''}\n"
    allow = bool(preview.get("allow_submit", True))
    if allow:
        next_line = "请确认后开始本机计算。"
    else:
        next_line = (
            str(preview.get("message") or submit_blocked_message(preview.get("kind") or "") or "")
            or "该功能尚未闭环，当前不会投递计算。"
        )
    reply = (
        f"已匹配能力族 `{preview['family']}`（`{preview['kind']}`），SK：`{preview.get('sk_set')}`。\n"
        f"{mat_line}"
        f"{mp_line}"
        f"{approx_line}"
        f"{llm_note}\n"
        f"{crit_line}"
        f"{next_line}"
    )

    if confirm_submit:
        return submit_project(project_id, poscar=poscar, gen=gen, hsd=hsd)

    preview = dict(preview)
    preview["param_tips"] = tips
    preview["hsd_default"] = hsd_text
    preview["maturity"] = mat
    preview["allow_submit"] = allow
    actions = (
        [{"type": "confirm_submit", "project_id": project_id}]
        if allow
        else [{"type": "feature_unavailable", "project_id": project_id}]
    )
    return {
        "reply": reply,
        "project_id": project_id,
        "preview": preview,
        "actions": actions,
        "pipeline_steps": build_pipeline_steps(db.get_project(project_id) or {}, ""),
        "next_action": next_action_hint(db.get_project(project_id) or {}, ""),
    }


def submit_project(
    project_id: str, *, poscar: str = "", gen: str = "", hsd: str = ""
) -> dict[str, Any]:
    proj = db.get_project(project_id)
    if not proj:
        return {"reply": "任务不存在", "ok": False}
    protocol = dict(proj.get("protocol") or {})
    kind = protocol.get("kind") or "dftb_opt"
    family = protocol.get("dftb_family") or ""
    blocked = submit_blocked_message(str(kind))
    if blocked:
        db.append_activity(project_id, f"拒绝投递未闭环功能：{kind}", "error")
        return {
            "reply": blocked,
            "ok": False,
            "project_id": project_id,
            "maturity": maturity_for_kind(str(kind)),
            "allow_submit": False,
        }
    st = proj.get("structure") or {}
    # 请求体优先；勿在已有 POSCAR 时再拼上库里残留的旧 GEN
    poscar = (poscar or "").strip() or str(st.get("poscar") or "").strip()
    gen = (gen or "").strip() or str(st.get("gen") or "").strip()
    if poscar:
        gen = ""  # 有 POSCAR 时一律由其生成 geo，杜绝上一任务分子 GEN 残留
    hsd_eff = (hsd or protocol.get("hsd_preview") or "").strip()
    # 结构与 HSD 的 MaxAngularMomentum 元素不一致时，丢弃旧 HSD 并重生成
    if hsd_eff and (poscar or gen):
        try:
            from dftb_engine import geometry as geo_mod

            els = set(
                geo_mod.elements_from_poscar(poscar)
                if poscar
                else geo_mod.elements_from_gen(gen)
            )
            mam = re.search(
                r"MaxAngularMomentum\s*=\s*\{([^}]*)\}", hsd_eff, flags=re.I | re.S
            )
            if mam and els:
                hsd_els = set(re.findall(r"\b([A-Z][a-z]?)\s*=", mam.group(1)))
                if hsd_els != els:
                    hsd_eff = ""
        except Exception:
            pass
    if hsd_eff:
        protocol["hsd_preview"] = hsd_eff
        db.update_project(project_id, protocol=protocol)
    prompt = (proj.get("idea") or {}).get("prompt") or protocol.get("prompt") or ""
    example_water = False
    for ex in EXAMPLES:
        if ex.get("use_recipes_water") and (
            ex["prompt"] in prompt or ex["title"] in prompt
        ):
            example_water = True
            break
    use_water = (not poscar and not gen) and _allows_water_default(
        prompt, family, kind, example_water=example_water
    )
    if not poscar and not gen and not use_water:
        mp_info = _try_fetch_mp_structure(prompt)
        if _structure_hit(mp_info):
            st = dict(st)
            if mp_info.get("poscar"):
                poscar = str(mp_info["poscar"])
                st["poscar"] = poscar
            if mp_info.get("gen"):
                gen = str(mp_info["gen"])
                st["gen"] = gen
            if mp_info.get("material_id") or mp_info.get("source"):
                st["mp"] = {
                    "material_id": mp_info.get("material_id"),
                    "formula": mp_info.get("formula"),
                    "source": mp_info.get("source") or "",
                    "query": mp_info.get("query"),
                }
            db.update_project(project_id, structure=st)
        else:
            return {
                "reply": "计算失败：缺少结构。请上传 POSCAR/GEN、从课程页载入，或在指令中写明材料（如硅/石墨烯）以便从 Materials Project 获取。",
                "ok": False,
                "project_id": project_id,
            }
    _, job_params = _refine_kind(prompt, family, kind)
    for ex in EXAMPLES:
        if ex["prompt"] in prompt or ex["title"] in prompt:
            if "DOS" in ex.get("prompt", "") or "态密度" in prompt or "DOS" in prompt:
                job_params["want_dos"] = True
            if ex.get("sk_set"):
                job_params.setdefault("sk_set", str(ex["sk_set"]))
            for k, v in dict(ex.get("params") or {}).items():
                job_params.setdefault(k, v)
            break
    # 投递前再查 SK：本机缺参数对则如实拒绝，避免作业必然失败
    try:
        from dftb_engine import geometry as geo_mod
        from dftb_engine import sk_resolver as sk_mod

        els_chk = (
            geo_mod.elements_from_poscar(poscar)
            if poscar
            else geo_mod.elements_from_gen(gen)
            if gen
            else []
        )
        sk_name = str(protocol.get("sk_set") or job_params.get("sk_set") or "")
        if not sk_name and els_chk:
            sk_name = sk_mod.choose_sk_set(els_chk)
        if els_chk and sk_name:
            cov = sk_mod.sk_coverage_report(els_chk, sk_name)
            if cov.get("checked") and not cov.get("ok"):
                msg = str(cov.get("message") or "SK 参数不完整，拒绝投递。")
                db.append_activity(project_id, msg, "error")
                return {
                    "reply": msg,
                    "ok": False,
                    "project_id": project_id,
                    "allow_submit": False,
                    "sk_coverage": cov,
                }
    except Exception:
        pass
    eng = _engine()
    result = eng.submit_job(
        kind=kind,
        poscar=poscar,
        gen=gen,
        use_recipes_water=use_water,
        sk_set=protocol.get("sk_set") or job_params.get("sk_set") or "",
        params=job_params,
        hsd_override=hsd_eff,
    )
    if result.get("status") != "ok":
        # 尽量保留 job_id，便于任务页查看日志 / 诊断
        bad_job = str(result.get("job_id") or "").strip()
        if bad_job:
            protocol["job_id"] = bad_job
            db.update_project(
                project_id,
                protocol=protocol,
                phase="error",
                job={"job_id": bad_job, "status": "error"},
            )
        db.append_activity(project_id, f"计算失败：{result.get('message')}", "error")
        return {
            "reply": f"计算失败：{result.get('message')}",
            "ok": False,
            "project_id": project_id,
            "result": result,
        }
    job_id = result["job_id"]
    protocol["job_id"] = job_id
    db.update_project(
        project_id, protocol=protocol, phase="running", job={"job_id": job_id, "status": "running"}
    )
    db.append_activity(project_id, f"已开始本机作业 {job_id}", "running")
    return {
        "reply": f"已开始本机作业 `{job_id}`。可在「任务」页查看进度与图件。",
        "ok": True,
        "project_id": project_id,
        "job_id": job_id,
        "result": result,
    }


def _local_calc_brief(preview: dict[str, Any], prompt: str = "") -> str:
    """LLM 不可用时的本地简短说明（不依赖外网）。"""
    kind = str(preview.get("kind") or "")
    sk = str(preview.get("sk_set") or "默认")
    formula = ""
    mp = preview.get("mp") or {}
    if mp.get("formula"):
        formula = str(mp.get("formula"))
    elif (preview.get("params") or {}).get("formula"):
        formula = str((preview.get("params") or {}).get("formula"))
    host = formula or "当前结构"
    if kind == "dftb_band":
        if preview.get("params", {}).get("want_dos") or "DOS" in (prompt or "") or "态密度" in (
            prompt or ""
        ):
            return (
                f"将对「{host}」用 DFTB+（SK={sk}）先几何优化，再算高对称路径能带，"
                "并另跑均匀 k 网格得到 DOS；能量相对 Fermi 归零后出图。"
            )
        return f"将对「{host}」用 DFTB+（SK={sk}）先几何优化，再沿高对称路径计算能带并出图。"
    if kind == "dftb_dos":
        return f"将对「{host}」用 DFTB+（SK={sk}）先几何优化，再以均匀 k 网格估算态密度。"
    if kind == "dftb_defect":
        return f"将对「{host}」做二维缺陷电子结构（含自旋与预优化，课堂近似）。"
    if kind == "dftb_opt":
        return f"将对「{host}」做 DFTB+ 几何优化（SK={sk}）。"
    if kind == "dftb_vib":
        return f"将对「{host}」先短优化再计算振动频率（需本机 modes）。"
    if kind == "dftb_td":
        return f"将对「{host}」先短优化再做 Casida 吸收光谱。"
    if kind == "dftb_xtb":
        return f"将对「{host}」用 GFN2-xTB 做几何优化。"
    if kind in ("dftb_md", "dftb_md_anneal"):
        return f"将对「{host}」跑 BOMD/退火（演示步数，SK={sk}）。"
    mat = preview.get("maturity") or {}
    if mat.get("note"):
        return str(mat.get("note"))
    return f"已按能力矩阵生成 DFTB+ 输入（{kind or '任务'}，SK={sk}）。"


def _param_tips(
    kind: str,
    sk_set: str,
    *,
    maturity: Optional[dict[str, Any]] = None,
    sk_coverage: Optional[dict[str, Any]] = None,
) -> list[dict[str, str]]:
    """关键参数的课堂说明，供前端 HSD 旁展示。"""
    tips = [
        {
            "key": "hsd",
            "title": "HSD",
            "text": "DFTB+ 的主输入脚本；确认计算时以当前编辑内容为准。",
        },
        {
            "key": "sk",
            "title": "SK 参数集",
            "text": f"当前使用「{sk_set or '默认'}」。不同参数集适合不同元素与体系，课堂演示请勿随意混用。",
        },
    ]
    mat = maturity or maturity_for_kind(kind)
    tips.insert(
        0,
        {
            "key": "maturity",
            "title": f"功能状态：{mat.get('label') or '未知'}",
            "text": str(mat.get("note") or ""),
        },
    )
    if sk_coverage and sk_coverage.get("message"):
        tips.append(
            {
                "key": "sk_coverage",
                "title": "SK 覆盖",
                "text": str(sk_coverage.get("message") or ""),
            }
        )
    k = (kind or "").lower()
    if "band" in k or "dos" in k or "defect" in k:
        tips.append(
            {
                "key": "band",
                "title": "能带 / DOS",
                "text": (
                    "投递后先几何优化；能带沿高对称路径，若同时要 DOS 会再跑均匀 k 网格。"
                    "图中能量相对 Fermi 归零。优化失败或缺少 geo_end.gen 时不会静默用未优化结构。"
                ),
            }
        )
        tips.append(
            {
                "key": "prerelax",
                "title": "先优化再电子结构",
                "text": "作业内多阶段：dftb_in_opt →（可选）能带 HSD →（可选）dftb_in_dos 均匀网格。界面编辑的是主电子结构 HSD。",
            }
        )
    if "defect" in k:
        tips.append(
            {
                "key": "spin",
                "title": "自旋极化",
                "text": "二维空位/掺杂默认共线自旋；默认超胞已加大（如石墨烯 4×4）。仍属课堂近似，电荷态未自动扫描。",
            }
        )
    if "vib" in k:
        tips.append(
            {
                "key": "vib",
                "title": "振动",
                "text": "默认先短几何优化再求频率；需本机 modes。完整声子（phonopy）流程尚未闭环。",
            }
        )
    if "td" in k:
        tips.append(
            {
                "key": "td",
                "title": "Casida",
                "text": "默认先短优化再算激发；Casida 与三阶 DFTB 互斥，已自动关闭三阶。",
            }
        )
    if "scc" in k or k.endswith("_scc"):
        tips.append(
            {
                "key": "scc",
                "title": "SCC 自洽",
                "text": "自洽电荷迭代至收敛后给出总能量与 Fermi 能级，是几何优化与能带的基础。",
            }
        )
    if "phonon" in k:
        tips.append(
            {
                "key": "phonon",
                "title": "声子（未闭环）",
                "text": "仅生成力计算器与 phonopy 草稿，不会自动算声子带；默认禁止投递。",
            }
        )
    tips.append(
        {
            "key": "restore",
            "title": "恢复默认",
            "text": "若编辑后不确定，可点「恢复推荐默认」回到本次预览生成的 HSD。",
        }
    )
    return tips


_STATUS_ZH = {
    "pending": "排队中",
    "running": "计算中",
    "done": "已完成",
    "error": "失败",
    "cancelled": "已取消",
    "not_found": "未找到",
    "unknown": "未知",
}

_PHASE_ZH = {
    "draft": "草稿",
    "protocol": "方案就绪",
    "running": "计算中",
    "analyzed": "已完成",
    "manuscript": "文稿",
    "cancelled": "已取消",
    "error": "失败",
}


def status_label_zh(status: str) -> str:
    return _STATUS_ZH.get((status or "").lower(), status or "未知")


def phase_label_zh(phase: str) -> str:
    return _PHASE_ZH.get((phase or "").lower(), phase or "—")


def build_pipeline_steps(proj: dict[str, Any], job_status: str = "") -> list[dict[str, str]]:
    """方案→投递→运行→完成 流水线步骤，供任务页展示。"""
    phase = (proj.get("phase") or "draft").lower()
    st = (job_status or (proj.get("job") or {}).get("status") or "").lower()
    protocol = proj.get("protocol") or {}
    has_hsd = bool(protocol.get("hsd_preview") or protocol.get("hsd_default"))
    has_job = bool((proj.get("job") or {}).get("job_id") or protocol.get("job_id"))

    def state_for(step: str) -> str:
        if phase in ("cancelled",) and step in ("run", "done"):
            return "error" if step == "run" else "idle"
        if phase == "error" and step == "run":
            return "error"
        if st == "error" and step == "run":
            return "error"
        if st == "cancelled" and step == "run":
            return "error"
        order = ["draft", "protocol", "submit", "run", "done"]
        # 映射当前进度索引
        idx = 0
        if phase == "analyzed" or st == "done":
            idx = 4
        elif st == "running":
            idx = 3
        elif st == "pending" or phase == "running":
            idx = 3 if st == "running" else 2
        elif has_job:
            idx = 2
        elif has_hsd or phase == "protocol":
            idx = 1
        else:
            idx = 0
        if phase == "running" and st in ("", "unknown"):
            idx = max(idx, 2)
        si = order.index(step)
        if st in ("error", "cancelled") and si == 3:
            return "error"
        if si < idx:
            return "done"
        if si == idx:
            return "active"
        return "idle"

    # pending 时高亮「运行」前的投递/排队
    if st == "pending":
        steps_override = {
            "draft": "done",
            "protocol": "done",
            "submit": "done",
            "run": "active",
            "done": "idle",
        }
    elif st == "running":
        steps_override = {
            "draft": "done",
            "protocol": "done",
            "submit": "done",
            "run": "active",
            "done": "idle",
        }
    elif st == "done" or phase == "analyzed":
        steps_override = {k: "done" for k in ("draft", "protocol", "submit", "run", "done")}
    elif st == "error" or phase == "error":
        steps_override = {
            "draft": "done",
            "protocol": "done" if has_hsd else "idle",
            "submit": "done" if has_job else "idle",
            "run": "error",
            "done": "idle",
        }
    elif st == "cancelled" or phase == "cancelled":
        steps_override = {
            "draft": "done",
            "protocol": "done" if has_hsd else "idle",
            "submit": "done" if has_job else "idle",
            "run": "error",
            "done": "idle",
        }
    else:
        steps_override = None

    labels = [
        ("draft", "草稿"),
        ("protocol", "方案就绪"),
        ("submit", "已投递"),
        ("run", "运行中"),
        ("done", "已完成"),
    ]
    out = []
    for key, label in labels:
        state = steps_override[key] if steps_override else state_for(key)
        out.append({"id": key, "label": label, "state": state})
    return out


def next_action_hint(proj: dict[str, Any], job_status: str = "", message: str = "") -> str:
    phase = (proj.get("phase") or "").lower()
    st = (job_status or "").lower()
    if st == "error" or phase == "error":
        return message or "计算失败：请查看诊断与日志，取消或删除后重新预览并确认计算。"
    if st == "cancelled" or phase == "cancelled":
        return "任务已取消：可回到「计算」页重新预览输入文件并确认计算。"
    if st in ("pending", "running"):
        return "计算进行中：可在本页查看实时日志；若长时间无进展请取消后重试。"
    if st == "done" or phase == "analyzed":
        return "已完成：请阅读下方结果摘要与结果图。"
    protocol = proj.get("protocol") or {}
    if protocol.get("hsd_preview") or phase == "protocol":
        return "方案已就绪：请核对 HSD 后点击「确认计算」。"
    return "请先在「计算」页描述任务并预览输入文件。"


def lecture_summary(proj: dict[str, Any], analysis: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """课堂讲义式结果摘要（按任务类型裁剪字段）。"""
    from dftb_engine import kind_profile as kp

    protocol = proj.get("protocol") or {}
    analysis = analysis or protocol.get("analysis") or {}
    detailed = analysis.get("detailed") or {}
    perf = protocol.get("performance") or analysis.get("performance") or {}
    gap = analysis.get("band_gap") or {}
    meta = analysis.get("band_meta") or {}
    structure = proj.get("structure") or {}
    mp = structure.get("mp") or {}
    kind = str(protocol.get("kind") or "")
    items = [
        {"key": "title", "label": "课题", "value": proj.get("title") or "—"},
        {"key": "phase", "label": "阶段", "value": phase_label_zh(proj.get("phase") or "")},
        {"key": "kind", "label": "任务类型", "value": kind or "—"},
        {"key": "sk", "label": "SK 参数集", "value": protocol.get("sk_set") or "—"},
    ]
    src_short = _structure_source_short(mp)
    if src_short:
        items.append({"key": "mp", "label": "结构来源", "value": src_short})
    energy = analysis.get("total_energy")
    if energy is None:
        energy = detailed.get("total_energy_eV")
    if energy is not None:
        items.append({"key": "energy", "label": "总能量 (eV)", "value": f"{float(energy):.6f}"})
    if kp.shows_fermi(kind):
        fermi = analysis.get("fermi_energy")
        if fermi is None:
            fermi = detailed.get("fermi_eV")
        if fermi is not None:
            items.append({"key": "fermi", "label": "Fermi (eV)", "value": f"{float(fermi):.6f}"})
    if kp.shows_band_gap(kind) and gap.get("gap_eV") is not None:
        g = float(gap["gap_eV"])
        tip = "近似零隙/金属特征" if gap.get("gap_type") == "metallic_or_zero" else "存在带隙（定性）"
        items.append({"key": "gap", "label": "带隙 (eV)", "value": f"{g:.3f}（{tip}）"})
    if kp.shows_kpath(kind):
        if meta.get("path_name"):
            ticks = meta.get("ticks") or []
            path_lbl = (
                "–".join(str(t.get("label") or "") for t in ticks)
                if ticks
                else str(meta.get("path_name"))
            )
            items.append({"key": "path", "label": "k 路径", "value": path_lbl.replace("G", "Γ")})
        if analysis.get("n_kpoints"):
            items.append({"key": "nk", "label": "k 点数", "value": str(analysis["n_kpoints"])})
    if kp.shows_opt_metrics(kind):
        opt_e = detailed.get("opt_energies_eV") or analysis.get("opt_energies_eV") or []
        if isinstance(opt_e, list) and len(opt_e) >= 2:
            items.append({"key": "opt_steps", "label": "优化步数", "value": str(len(opt_e))})
            try:
                dE = float(opt_e[-1]) - float(opt_e[0])
                items.append({"key": "opt_de", "label": "ΔE (eV)", "value": f"{dE:.6f}"})
            except (TypeError, ValueError):
                pass
    if kp.shows_excitations(kind):
        exc = analysis.get("excitations") or detailed.get("excitations") or []
        if exc:
            items.append({"key": "n_exc", "label": "激发态数", "value": str(len(exc))})
            try:
                e0 = float(exc[0].get("energy"))
                items.append({"key": "exc0", "label": "最低激发 (eV)", "value": f"{e0:.3f}"})
            except (TypeError, ValueError, AttributeError, IndexError):
                pass
    if kp.shows_vibrations(kind):
        vib = analysis.get("vibrations") or []
        if vib:
            items.append({"key": "n_vib", "label": "振动模数", "value": str(len(vib))})
            real = [
                float(v.get("freq_cm1") or 0.0)
                for v in vib
                if float(v.get("freq_cm1") or 0.0) > 50
            ]
            if real:
                items.append(
                    {
                        "key": "vib_range",
                        "label": "频率范围 (cm⁻¹)",
                        "value": f"{min(real):.1f} – {max(real):.1f}",
                    }
                )
            # 列出主要正频率（跳过近似平动/转动的近零模）
            top = sorted(real, reverse=True)[:6]
            if top:
                items.append(
                    {
                        "key": "vib_top",
                        "label": "主要频率 (cm⁻¹)",
                        "value": "、".join(f"{x:.1f}" for x in top),
                    }
                )
            n_imag = sum(1 for v in vib if float(v.get("freq_cm1") or 0.0) < -1.0)
            if n_imag:
                items.append({"key": "vib_imag", "label": "虚频模数", "value": str(n_imag)})
    if kp.shows_md_metrics(kind):
        md_e = analysis.get("md_energies_eV") or detailed.get("md_energies_eV") or []
        if isinstance(md_e, list) and len(md_e) >= 2:
            items.append({"key": "md_steps", "label": "MD 步数", "value": str(len(md_e))})
            try:
                dE = float(md_e[-1]) - float(md_e[0])
                items.append({"key": "md_de", "label": "ΔE (eV)", "value": f"{dE:.6f}"})
            except (TypeError, ValueError):
                pass
        md_t = analysis.get("md_temps_K") or detailed.get("md_temps_K") or []
        t_mean = analysis.get("md_temp_mean_K")
        if t_mean is None and isinstance(md_t, list) and md_t:
            try:
                t_mean = sum(float(x) for x in md_t) / len(md_t)
            except (TypeError, ValueError):
                t_mean = None
        if t_mean is not None:
            items.append({"key": "md_tmean", "label": "平均温度 (K)", "value": f"{float(t_mean):.1f}"})
            try:
                items.append(
                    {
                        "key": "md_trange",
                        "label": "温度范围 (K)",
                        "value": f"{min(float(x) for x in md_t):.1f} – {max(float(x) for x in md_t):.1f}",
                    }
                )
            except (TypeError, ValueError):
                pass
    scc_ok = analysis.get("scc_converged")
    geo_ok = analysis.get("geometry_converged")
    if scc_ok is not None or geo_ok is not None:
        bits = []
        if scc_ok is not None:
            bits.append("SCC：" + ("是" if scc_ok else "否"))
        if geo_ok is not None and (kp.shows_opt_metrics(kind) or geo_ok):
            bits.append("几何：" + ("是" if geo_ok else "否"))
        if bits:
            items.append({"key": "conv", "label": "收敛", "value": " · ".join(bits)})
    if perf.get("scc_iterations") is not None and (
        kp.shows_fermi(kind) or kp.shows_opt_metrics(kind) or not kind
    ):
        items.append({"key": "scc", "label": "SCC 迭代", "value": str(perf["scc_iterations"])})
    criteria = protocol.get("success_criteria") or []
    observables = protocol.get("expected_observables") or []
    return {
        "items": items,
        "success_criteria": criteria,
        "expected_observables": observables,
        "narrative": _lecture_narrative(analysis, protocol, gap, meta),
        "show_structure_compare": kp.shows_structure_compare(kind),
    }


def _lecture_narrative(
    analysis: dict[str, Any],
    protocol: dict[str, Any],
    gap: dict[str, Any],
    meta: dict[str, Any],
) -> str:
    from dftb_engine import kind_profile as kp

    parts = []
    kind = protocol.get("kind") or ""
    sk = protocol.get("sk_set") or ""
    if kind:
        parts.append(f"本任务类型为 {kind}" + (f"，SK 参数集 {sk}" if sk else "") + "。")
    if kp.shows_band_gap(kind) and gap.get("gap_eV") is not None:
        g = float(gap["gap_eV"])
        if gap.get("gap_type") == "metallic_or_zero":
            parts.append(f"由能带估算的带隙约 {g:.3f} eV，接近零隙，课堂讨论时注意与实验带隙的定性差异。")
        else:
            parts.append(f"由能带估算的带隙约 {g:.3f} eV（相对 Fermi，课堂定性参考）。")
    if kp.shows_kpath(kind) and meta.get("path_name"):
        parts.append(f"能带路径：{meta.get('path_name')}。")
    if kp.shows_opt_metrics(kind):
        detailed = analysis.get("detailed") or {}
        opt_e = detailed.get("opt_energies_eV") or analysis.get("opt_energies_eV") or []
        if isinstance(opt_e, list) and len(opt_e) >= 2:
            parts.append(f"几何优化共 {len(opt_e)} 步，请对比优化前后结构与能量轨迹。")
    if kp.shows_excitations(kind):
        n_exc = analysis.get("n_excitations") or len(analysis.get("excitations") or [])
        if n_exc:
            parts.append(f"共解析 {n_exc} 个激发态，见吸收光谱图。")
    if kp.shows_vibrations(kind):
        vib = analysis.get("vibrations") or []
        if vib:
            real = [float(v.get("freq_cm1") or 0.0) for v in vib if float(v.get("freq_cm1") or 0.0) > 50]
            if real:
                parts.append(
                    f"共 {len(vib)} 个振动模，真实频率约 {min(real):.0f}–{max(real):.0f} cm⁻¹；"
                    "请对照谱图与主要频率列表。"
                )
            else:
                parts.append(f"共解析 {len(vib)} 个振动模，见频率谱图。")
    if kp.shows_md_metrics(kind):
        md_e = analysis.get("md_energies_eV") or (analysis.get("detailed") or {}).get("md_energies_eV") or []
        if isinstance(md_e, list) and len(md_e) >= 2:
            t_mean = analysis.get("md_temp_mean_K")
            if t_mean is not None:
                parts.append(
                    f"MD 轨迹共 {len(md_e)} 步，平均温度约 {float(t_mean):.0f} K；见能量/温度轨迹图。"
                )
            else:
                parts.append(f"MD 轨迹共 {len(md_e)} 步，见能量随步数变化图。")
    energy = analysis.get("total_energy")
    if energy is not None:
        parts.append(f"总能量 {float(energy):.6f} eV。")
    if not parts:
        return "结果已解析；请结合下方卡片与图件阅读。"
    return "".join(parts)


def poll_and_finalize(project_id: str, *, force_replot: bool = False) -> dict[str, Any]:
    proj = db.get_project(project_id)
    if not proj:
        return {"ok": False, "message": "任务不存在"}
    job_id = (proj.get("job") or {}).get("job_id") or (proj.get("protocol") or {}).get("job_id")
    if not job_id:
        analysis = (proj.get("protocol") or {}).get("analysis") or {}
        return {
            "ok": True,
            "status": "none",
            "status_zh": "未投递",
            "phase_zh": phase_label_zh(proj.get("phase") or "draft"),
            "job_id": "",
            "note": next_action_hint(proj, ""),
            "pipeline_steps": build_pipeline_steps(proj, ""),
            "next_action": next_action_hint(proj, ""),
            "lecture": lecture_summary(proj, analysis),
            "cancellable": False,
            "partial_analysis": analysis,
        }
    eng = _engine()
    st = eng.get_status(job_id)
    status = st.get("status")
    job_payload: dict[str, Any] = {"job_id": job_id, "status": status}
    if st.get("timing"):
        job_payload["timing"] = st["timing"]
    db.update_project(project_id, job=job_payload)
    if status != "done":
        # 运行中也返回日志与部分解析，供任务页实时监测
        arts = eng.fetch_artifacts(
            job_id,
            [
                "dftb.log",
                "runner.log",
                "detailed.out",
                "md.out",
                "status",
                "started_at",
                "finished_at",
                "wall_seconds",
            ],
        )
        log = arts.get("dftb.log") or ""
        if not log.strip():
            log = arts.get("runner.log") or ""
        lines = log.splitlines()
        log_tail = "\n".join(lines[-50:])
        partial: dict[str, Any] = {}
        try:
            if arts.get("detailed.out") or (arts.get("dftb.log") or "").strip():
                partial = eng.analyze(arts)
        except Exception:
            partial = {}
        if status == "cancelled":
            db.update_project(project_id, phase="cancelled")
        elif status == "error":
            db.update_project(project_id, phase="error")
        note = {
            "pending": "作业排队中，等待 DFTB+ 启动。",
            "running": "本机 DFTB+ 正在计算，下方为实时日志。",
            "error": st.get("message") or "计算失败，请查看日志后重新确认计算。",
            "cancelled": "作业已取消。",
            "not_found": "未找到作业目录。",
        }.get(status, "作业进行中。")
        if status == "pending" and not log_tail.strip():
            note = "作业已提交，正在启动本机 DFTB+…若长时间无日志，请取消后重新确认计算。"
        proj2 = db.get_project(project_id) or proj
        return {
            "ok": True,
            "status": status,
            "status_zh": status_label_zh(status),
            "phase_zh": phase_label_zh(proj2.get("phase") or status),
            "job_id": job_id,
            "timing": st.get("timing") or {},
            "log_tail": log_tail or ("（尚无引擎日志）" if status == "pending" else ""),
            "partial_analysis": partial,
            "note": note,
            "diag": st.get("diag") or {},
            "message": st.get("message") or "",
            "cancellable": status in ("pending", "running"),
            "pipeline_steps": build_pipeline_steps(proj2, status),
            "next_action": next_action_hint(proj2, status, st.get("message") or ""),
            "lecture": lecture_summary(proj2, partial),
        }

    fig_dir = db.project_dir(project_id) / "figures"
    protocol_cached = dict(proj.get("protocol") or {})
    cached_analysis = protocol_cached.get("analysis") or {}
    skip = {
        "dftb_total_energy.png",
        "dftb_performance.png",
        "dftb_total_energy.pdf",
        "dftb_performance.pdf",
        "dftb_total_energy.svg",
        "dftb_performance.svg",
    }

    def _list_pngs() -> list[str]:
        if not fig_dir.is_dir():
            return []
        return [
            str(p)
            for p in sorted(fig_dir.iterdir())
            if p.suffix.lower() == ".png" and p.name.lower() not in skip
        ]

    # 已分析且无需强制重绘：走缓存，展开任务时更快
    # 但 MD/振动若缺关键图或轨迹数据，则强制重解析（兼容旧缓存）
    from dftb_engine import kind_profile as kp

    job_kind_cached = str(protocol_cached.get("kind") or "")
    png_names = {Path(p).name for p in _list_pngs()}
    cache_stale = False
    if kp.shows_md_metrics(job_kind_cached):
        md_e = cached_analysis.get("md_energies_eV") or []
        if len(md_e) < 2 or "dftb_md_energy.png" not in png_names:
            cache_stale = True
    if kp.shows_vibrations(job_kind_cached):
        vib = cached_analysis.get("vibrations") or []
        if not vib or "dftb_vibrations.png" not in png_names:
            cache_stale = True
    if (
        not force_replot
        and not cache_stale
        and (proj.get("phase") or "").lower() == "analyzed"
        and cached_analysis
        and _list_pngs()
    ):
        art = db.project_dir(project_id) / "artifacts"
        log_tail = ""
        try:
            lp = art / "dftb.log"
            if lp.is_file():
                log_tail = lp.read_text(encoding="utf-8", errors="replace")[-2000:]
        except Exception:
            pass
        png_plots = _list_pngs()
        return {
            "ok": True,
            "status": "done",
            "status_zh": status_label_zh("done"),
            "phase_zh": phase_label_zh("analyzed"),
            "job_id": job_id,
            "analysis": cached_analysis,
            "figures": png_plots,
            "performance": protocol_cached.get("performance") or cached_analysis.get("performance") or {},
            "timing": (proj.get("job") or {}).get("timing") or st.get("timing") or {},
            "log_tail": log_tail,
            "cancellable": False,
            "note": "作业已完成，结果已解析。",
            "pipeline_steps": build_pipeline_steps(proj, "done"),
            "next_action": next_action_hint(proj, "done"),
            "lecture": lecture_summary(proj, cached_analysis),
            "diag": st.get("diag") or {},
            "partial_analysis": cached_analysis,
            "cached": True,
        }

    artifacts = eng.fetch_artifacts(job_id)
    analysis = eng.analyze(artifacts)
    protocol = dict(proj.get("protocol") or {})
    job_kind = str(protocol.get("kind") or "")
    plots = []
    plot_error = ""
    try:
        plots = [str(p) for p in eng.plot(artifacts, fig_dir, kind=job_kind)]
    except Exception as e:
        plots = []
        plot_error = str(e)
    # 清理不再展示的旧图 / 串类型残留图
    png_plots = [
        p
        for p in plots
        if str(p).lower().endswith(".png") and Path(p).name.lower() not in skip
    ]
    produced_names = {Path(p).name for p in png_plots}
    if fig_dir.is_dir():
        for name in list(skip) + kp.stale_figure_names(job_kind, produced_names):
            try:
                (fig_dir / name).unlink(missing_ok=True)
            except Exception:
                pass
    if not png_plots:
        png_plots = [
            p
            for p in _list_pngs()
            if Path(p).name not in skip
            and Path(p).name not in set(kp.stale_figure_names(job_kind, produced_names))
        ]
    protocol["analysis"] = analysis
    protocol["figures"] = png_plots
    if plot_error:
        protocol["plot_error"] = plot_error
    perf = analysis.get("performance") or {}
    if perf:
        protocol["performance"] = perf
    db.update_project(
        project_id,
        protocol=protocol,
        phase="analyzed",
        assets=png_plots,
        job={
            "job_id": job_id,
            "status": "done",
            "timing": st.get("timing") or {},
        },
    )
    note = "作业完成，已解析结果"
    if png_plots:
        note += f"并出图 {len(png_plots)} 张"
    elif plot_error:
        note += f"；出图失败：{plot_error[:120]}"
    else:
        note += "（无可绘制数据）"
    db.append_activity(project_id, note, "analyzed")
    art = db.project_dir(project_id) / "artifacts"
    for name, content in artifacts.items():
        (art / name).write_text(content, encoding="utf-8", errors="replace")
    proj_done = db.get_project(project_id) or proj
    return {
        "ok": True,
        "status": "done",
        "status_zh": status_label_zh("done"),
        "phase_zh": phase_label_zh("analyzed"),
        "job_id": job_id,
        "analysis": analysis,
        "figures": png_plots,
        "performance": perf,
        "timing": st.get("timing") or {},
        "log_tail": (artifacts.get("dftb.log") or "")[-2000:],
        "cancellable": False,
        "note": "作业已完成，结果已解析。",
        "pipeline_steps": build_pipeline_steps(proj_done, "done"),
        "next_action": next_action_hint(proj_done, "done"),
        "lecture": lecture_summary(proj_done, analysis),
        "diag": st.get("diag") or {},
        "partial_analysis": analysis,
    }


def cancel_project(project_id: str) -> dict[str, Any]:
    proj = db.get_project(project_id)
    if not proj:
        return {"ok": False, "message": "任务不存在"}
    job_id = (proj.get("job") or {}).get("job_id") or (proj.get("protocol") or {}).get("job_id")
    if not job_id:
        return {"ok": False, "message": "当前任务没有可取消的作业"}
    eng = _engine()
    result = eng.cancel_job(job_id)
    status = result.get("status") or "cancelled"
    db.update_project(
        project_id,
        phase="cancelled" if result.get("ok") else proj.get("phase"),
        job={"job_id": job_id, "status": status},
    )
    if result.get("ok"):
        db.append_activity(project_id, f"已取消作业 {job_id}", "cancelled")
    return {
        "ok": bool(result.get("ok")),
        "message": result.get("message") or ("已取消" if result.get("ok") else "取消失败"),
        "status": status,
        "status_zh": status_label_zh(status),
        "job_id": job_id,
        "result": result,
    }


def commands() -> list[dict]:
    return list_supported_commands()
