"""能力成熟度：如实标注哪些 kind/family 已闭环、部分可用或仅骨架。"""

from __future__ import annotations

from typing import Any, Optional

# ready: 课堂主路径可端到端跑通并出合理产物
# partial: 能跑通但科学上有已知简化，或依赖额外条件
# skeleton: 仅生成输入/说明，未形成完整科研/教学闭环 —— 默认禁止投递
KIND_MATURITY: dict[str, dict[str, Any]] = {
    "dftb_scc": {
        "status": "ready",
        "label": "已可用",
        "note": "单点 SCC；分子/周期均可。",
    },
    "dftb_opt": {
        "status": "ready",
        "label": "已可用",
        "note": "几何优化；可查看能量轨迹与优化后结构。",
    },
    "dftb_band": {
        "status": "ready",
        "label": "已可用",
        "note": "先几何优化再沿高对称路径算能带；若同时要 DOS 会另跑均匀 k 网格。",
    },
    "dftb_dos": {
        "status": "ready",
        "label": "已可用",
        "note": "先优化再用均匀 k 网格估算态密度。",
    },
    "dftb_defect": {
        "status": "partial",
        "label": "可用（有简化）",
        "note": "二维空位/掺杂：默认较大超胞+自旋+预优化；电荷态与收敛仍属课堂级近似。",
    },
    "dftb_vib": {
        "status": "ready",
        "label": "已可用",
        "note": "默认先短几何优化再求振动频率（需本机 modes）。",
    },
    "dftb_md": {
        "status": "partial",
        "label": "可用（演示步数）",
        "note": "BOMD 可跑通，默认步数偏短，适合流程演示而非长时间采样。",
    },
    "dftb_md_anneal": {
        "status": "partial",
        "label": "可用（演示步数）",
        "note": "退火 MD 可跑通，参数偏课堂演示。",
    },
    "dftb_td": {
        "status": "ready",
        "label": "已可用",
        "note": "Casida 吸收光谱；默认先短优化；需分子结构。",
    },
    "dftb_td_relax": {
        "status": "partial",
        "label": "可用（有简化）",
        "note": "激发态几何弛豫可生成输入并尝试运行；结果解读需谨慎。",
    },
    "dftb_xtb": {
        "status": "ready",
        "label": "已可用",
        "note": "GFN2-xTB 几何优化。",
    },
    "dftb_solv": {
        "status": "partial",
        "label": "可用（依赖参数文件）",
        "note": "隐式溶剂优化依赖本机 ALPB/GB 参数文件是否已部署。",
    },
    "dftb_edyn": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "可生成 ElectronDynamics Kick 输入，但时域光谱/电荷转移图件与后处理尚未闭环。",
    },
    "dftb_ehrenfest": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "Ehrenfest 输入骨架已有，完整动力学分析与出图尚未实现。",
    },
    "dftb_phonon": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "仅提供力计算器与 phonopy 配置草稿，未自动跑位移超胞与声子带。",
    },
    "dftb_barrier": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "能垒扫描需多帧几何与批量投递，当前仅说明文件，未自动扫描。",
    },
    "dftb_reks": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "可写入 REKS SSR22 块，态能量解析与成图尚未完善。",
    },
    "dftb_transport": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "ContactHamiltonian 等为模板，缺少结几何分区校验与透射谱后处理。",
    },
    "dftb_boundary": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "螺旋边界尚未真正注入可执行 HelicalUniform 采样，目前接近普通 SCC。",
    },
    "dftb_gsm": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "仅 GSM 对接说明，未内置增长串驱动。",
    },
    "dftb_ase": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "提供最小 ASE 示例脚本，不由本工作台自动执行与出图。",
    },
    "dftb_ipi": {
        "status": "skeleton",
        "label": "未闭环",
        "note": "提供 i-PI 客户端草稿，需外部 i-PI 主进程，本台未闭环。",
    },
}

FAMILY_MATURITY: dict[str, str] = {
    "electronic": "ready",
    "geometry_vib": "ready",
    "md": "partial",
    "solvation": "partial",
    "defect_2d": "partial",
    "linresp": "ready",
    "xtb_in_dftb": "ready",
    "electronic_dynamics": "skeleton",
    "properties": "skeleton",
    "reks": "skeleton",
    "transport": "skeleton",
    "boundary": "skeleton",
    "gsm": "skeleton",
    "interfaces": "skeleton",
}


def maturity_for_kind(kind: str) -> dict[str, Any]:
    k = (kind or "").strip().lower()
    info = dict(KIND_MATURITY.get(k) or {})
    if not info:
        return {
            "status": "skeleton",
            "label": "未闭环",
            "note": "该任务类型尚未纳入已验证流程。",
            "kind": k,
            "allow_submit": False,
        }
    status = str(info.get("status") or "skeleton")
    info["kind"] = k
    info["allow_submit"] = status in ("ready", "partial")
    return info


def maturity_for_family(family_id: str) -> str:
    return FAMILY_MATURITY.get((family_id or "").strip(), "skeleton")


def submit_blocked_message(kind: str) -> Optional[str]:
    info = maturity_for_kind(kind)
    if info.get("allow_submit"):
        return None
    label = info.get("label") or "未闭环"
    note = info.get("note") or ""
    return (
        f"该功能尚未闭环（{label}）：{note}"
        " 当前不会投递计算。可用主路径：能带/DOS、几何优化、振动、分子吸收光谱、"
        "xTB 优化、石墨烯空位/掺杂（课堂近似）等。"
    )
