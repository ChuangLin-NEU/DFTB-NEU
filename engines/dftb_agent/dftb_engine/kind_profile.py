"""按 DFTB 任务类型决定结果摘要字段与出图种类。"""

from __future__ import annotations

from typing import Iterable, Optional

# 电子结构相关（可展示 Fermi / 能带 / DOS / 带隙）
BAND_KINDS = frozenset({"dftb_band", "dftb_dos", "dftb_defect", "dftb_boundary"})
ELECTRONIC_KINDS = BAND_KINDS | frozenset({"dftb_scc"})

# 几何优化族（能量轨迹、优化前后结构）
OPT_KINDS = frozenset(
    {"dftb_opt", "dftb_xtb", "dftb_solv", "dftb_barrier", "dftb_td_relax"}
)

# 激发态 / 吸收
TD_KINDS = frozenset({"dftb_td", "dftb_td_relax"})

# MD
MD_KINDS = frozenset({"dftb_md", "dftb_md_anneal", "dftb_ehrenfest"})

# 振动
VIB_KINDS = frozenset({"dftb_vib"})


def normalize_kind(kind: str = "") -> str:
    return (kind or "").strip().lower()


def shows_fermi(kind: str = "") -> bool:
    k = normalize_kind(kind)
    # 单点 SCC 与能带/DOS 等电子结构任务展示 Fermi；纯几何优化不展示
    return k in ELECTRONIC_KINDS or k in BAND_KINDS


def shows_band_gap(kind: str = "") -> bool:
    return normalize_kind(kind) in BAND_KINDS


def shows_kpath(kind: str = "") -> bool:
    return normalize_kind(kind) in BAND_KINDS


def shows_opt_metrics(kind: str = "", *, pre_relax: bool = False) -> bool:
    return normalize_kind(kind) in OPT_KINDS or bool(pre_relax)


def shows_excitations(kind: str = "") -> bool:
    return normalize_kind(kind) in TD_KINDS


def shows_vibrations(kind: str = "") -> bool:
    return normalize_kind(kind) in VIB_KINDS


def shows_md_metrics(kind: str = "") -> bool:
    return normalize_kind(kind) in MD_KINDS


def shows_structure_compare(
    kind: str = "",
    *,
    pre_relax: bool = False,
    stages: Optional[Iterable[str]] = None,
) -> bool:
    if normalize_kind(kind) in OPT_KINDS or bool(pre_relax):
        return True
    stage_list = [str(s) for s in (stages or [])]
    return "opt" in stage_list


def want_plot_opt_energy(kind: str = "", *, has_opt_trace: bool = False) -> bool:
    del kind
    return bool(has_opt_trace)


def want_plot_bands(
    kind: str = "",
    *,
    has_band: bool = False,
    dos_mesh: bool = False,
    mode: str = "",
) -> bool:
    k = normalize_kind(kind)
    m = (mode or "").strip().lower()
    # 纯均匀网格 DOS 任务不出能带图；klines+dos_mesh 仍出能带
    if dos_mesh and "klines" not in m:
        return False
    if m == "dos_mesh":
        return False
    if k:
        return k in BAND_KINDS and k != "dftb_dos" and has_band
    return has_band


def want_plot_dos(
    kind: str = "",
    *,
    has_band: bool = False,
    want_dos_flag: bool = False,
    dos_mesh: bool = False,
    mode: str = "",
) -> bool:
    k = normalize_kind(kind)
    m = (mode or "").strip().lower()
    if k == "dftb_dos" or dos_mesh or "dos_mesh" in m:
        return has_band
    if k in BAND_KINDS:
        return has_band and want_dos_flag
    if k:
        return False
    return has_band and (want_dos_flag or dos_mesh or "dos_mesh" in m)


def want_plot_absorption(kind: str = "", *, has_exc: bool = False) -> bool:
    k = normalize_kind(kind)
    if k:
        return k in TD_KINDS and has_exc
    return has_exc


def want_plot_vibrations(kind: str = "", *, has_freqs: bool = False) -> bool:
    k = normalize_kind(kind)
    if k:
        return k in VIB_KINDS and has_freqs
    return has_freqs


def want_plot_md_energy(kind: str = "", *, has_trace: bool = False) -> bool:
    k = normalize_kind(kind)
    if k:
        return k in MD_KINDS and has_trace
    return has_trace


def stale_figure_names(kind: str = "", produced: Iterable[str] = ()) -> list[str]:
    """出图后清理：删除本次未生成的已知结果图（避免串类型残留）。"""
    del kind  # 保留参数以兼容调用方
    produced_set = {str(x) for x in produced}
    known = (
        "dftb_opt_energy.png",
        "dftb_bands.png",
        "dftb_dos.png",
        "dftb_absorption.png",
        "dftb_vibrations.png",
        "dftb_md_energy.png",
    )
    return [n for n in known if n not in produced_set]
