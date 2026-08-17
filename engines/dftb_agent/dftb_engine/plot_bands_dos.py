"""DFTB+ 能带 / DOS / 能量 / 光谱出图。"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .analysis import (
    parse_band_out,
    parse_detailed_out,
    parse_exc_dat,
    parse_md_trajectory,
    parse_modes_log,
    parse_opt_energies,
    parse_vibrations_tag,
)


def _apply_style():
    try:
        from dftbneu.services import plot_style as ps

        ps.apply_plot_style()
        return ps
    except Exception:
        try:
            from cmats.services import plot_style as ps

            ps.apply_plot_style()
            return ps
        except Exception:
            return None


def _save(fig, path: Path, ps) -> None:
    if ps:
        ps.save_publication(fig, path)
    else:
        fig.savefig(path, dpi=200, bbox_inches="tight")


def _near_fermi_window(
    eigs_rel: list[float],
    *,
    half: float = 6.0,
    pad: float = 1.5,
    hard_cap: float = 12.0,
) -> tuple[float, float]:
    """能带/DOS 纵轴：默认聚焦费米能级附近，避免深能级/高空带把尺度拉爆。

    相对 EF 的本征值（eV）。金属或无能隙时用对称 ±half；
    有隙时保证 VBM/CBM 带一点边距可见，但不超过 ±hard_cap。
    """
    if not eigs_rel:
        return (-half, half)
    lo, hi = -float(half), float(half)
    below = [e for e in eigs_rel if e <= 0.05]
    above = [e for e in eigs_rel if e > 0.05]
    if below and above:
        vbm = max(below)
        cbm = min(above)
        # 隙两侧留 pad，并至少覆盖默认窗口
        lo = min(lo, vbm - pad)
        hi = max(hi, cbm + pad)
    # 防止再次扩到数十 eV
    lo = max(lo, -float(hard_cap))
    hi = min(hi, float(hard_cap))
    if hi - lo < 3.0:
        mid = 0.5 * (hi + lo)
        lo, hi = mid - 1.5, mid + 1.5
    return (lo, hi)


def _gaussian_dos(
    eigenvalues: list[float],
    *,
    sigma: float = 0.08,
    ngrid: int = 400,
    e_pad: float = 1.0,
    e_min: float | None = None,
    e_max: float | None = None,
) -> tuple[list[float], list[float]]:
    if not eigenvalues:
        return [], []
    if e_min is not None and e_max is not None and e_max > e_min:
        emin, emax = float(e_min), float(e_max)
    else:
        emin = min(eigenvalues) - e_pad
        emax = max(eigenvalues) + e_pad
    if emax <= emin:
        emax = emin + 1.0
    xs = [emin + (emax - emin) * i / (ngrid - 1) for i in range(ngrid)]
    inv = 1.0 / (sigma * math.sqrt(2.0 * math.pi))
    ys = []
    for x in xs:
        s = 0.0
        for e in eigenvalues:
            d = (x - e) / sigma
            s += inv * math.exp(-0.5 * d * d)
        ys.append(s)
    return xs, ys


def plot_from_artifacts(
    artifacts: dict[str, str], out_dir: Path, *, kind: str = ""
) -> list[Path]:
    from . import kind_profile as kp

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    ps = _apply_style()
    import matplotlib.pyplot as plt

    detailed = parse_detailed_out(artifacts.get("detailed.out") or "")
    meta: dict[str, Any] = {}
    try:
        meta = json.loads(artifacts.get("band_meta.json") or "{}")
    except Exception:
        meta = {}
    job_kind = (kind or str(meta.get("kind") or "")).strip()

    from . import geometry as geo

    formula = str(meta.get("formula") or "").strip()
    if not geo.looks_like_formula_label(formula):
        formula = ""
    if not formula:
        # POSCAR：优先用元素计数；首行仅在像化学式时采用（勿把 GEN 原子数当标题）
        for key in ("POSCAR", "poscar"):
            raw = artifacts.get(key) or ""
            if not raw.strip():
                continue
            formula = geo.formula_from_poscar(raw)
            if formula:
                break
            head = raw.strip().splitlines()[0].strip()
            token = head.split()[0] if head else ""
            if geo.looks_like_formula_label(token):
                formula = token
                break
    if not formula:
        gen_raw = artifacts.get("geo.gen") or ""
        formula = geo.formula_from_gen(gen_raw)

    def _sys_title(base: str) -> str:
        if formula:
            return f"{formula}: {base}"
        return base

    # 几何优化能量轨迹（仅优化类任务；轨迹多在 dftb.log）
    opt_e = detailed.get("opt_energies_eV") or []
    if len(opt_e) < 2 and kp.normalize_kind(job_kind) in kp.OPT_KINDS:
        log_txt = artifacts.get("dftb.log") or ""
        if not re.search(r"(?i)Total\s+MD\s+Energy|Molecular dynamics completed", log_txt):
            opt_e = parse_opt_energies(log_txt)
    if kp.want_plot_opt_energy(job_kind, has_opt_trace=len(opt_e) >= 2):
        fig, ax = plt.subplots(figsize=(4.6, 3.2))
        ax.plot(range(1, len(opt_e) + 1), opt_e, color="#0F6E6A", lw=1.4, marker="o", ms=3)
        ax.set_xlabel("Geometry step")
        ax.set_ylabel("Total energy (eV)")
        ax.set_title(_sys_title("Geometry optimization"))
        if ps and hasattr(ps, "force_axes_fonts"):
            try:
                ps.force_axes_fonts(ax)
            except Exception:
                pass
        p = out_dir / "dftb_opt_energy.png"
        _save(fig, p, ps)
        plt.close(fig)
        paths.append(p)

    band = parse_band_out(artifacts.get("band.out") or "")
    rows = band.get("rows") or []
    mode = str(meta.get("mode") or "")
    want_dos = bool(meta.get("want_dos")) or "dos_mesh" in mode
    dos_mesh = mode == "dos_mesh" or mode == "klines+dos_mesh"
    # 能带+DOS：DOS 优先用均匀网格产物 band_dos.out
    dos_band = parse_band_out(artifacts.get("band_dos.out") or "")
    dos_rows = dos_band.get("rows") or []
    # 需有 band_meta，或 band.out 足够像能带采样；再按任务类型门控
    has_band_data = bool(meta) or (len(rows) >= 8 and len((rows[0] if rows else [])) >= 3)
    is_band_job = has_band_data and (
        kp.want_plot_bands(job_kind, has_band=True, dos_mesh=dos_mesh, mode=mode)
        or kp.want_plot_dos(
            job_kind, has_band=True, want_dos_flag=want_dos, dos_mesh=dos_mesh, mode=mode
        )
    )

    def _tick_label(raw: str) -> str:
        s = str(raw or "").strip()
        mapping = {"G": "Γ", "GAMMA": "Γ", "Gamma": "Γ", "g": "Γ"}
        return mapping.get(s, s)

    def _to_ev(vals: list[float]) -> list[float]:
        """与 DOS / 带隙估算同一套单位判断：用全部本征值，避免浅能级误判为 Hartree。"""
        if not vals:
            return []
        if max(abs(v) for v in vals) < 4.0:
            return [v * 27.211386245988 for v in vals]
        return list(vals)

    fermi = detailed.get("fermi_eV")
    path_name = str(meta.get("path_name") or "").strip()
    all_raw = [float(v) for r in rows for v in r[1:] if len(r) > 1]
    all_ev = _to_ev(all_raw)
    # 建立「原始列 → eV」的换算因子（全谱一致）
    scale = 27.211386245988 if all_raw and max(abs(v) for v in all_raw) < 4.0 else 1.0
    shift = float(fermi) if fermi is not None else 0.0

    if (
        rows
        and len(rows[0]) >= 2
        and kp.want_plot_bands(
            job_kind, has_band=has_band_data, dos_mesh=dos_mesh, mode=mode
        )
    ):
        fig, ax = plt.subplots(figsize=(5.2, 3.6))
        xs = list(range(1, len(rows) + 1))
        # 画全部分带：此前 min(16,…) 会截掉导带，导致 EF=0 线看起来偏高
        ncols = max(0, len(rows[0]) - 1)
        band_ys_all: list[float] = []
        for bi in range(1, ncols + 1):
            ys = [(float(r[bi]) * scale) - shift for r in rows if len(r) > bi]
            if len(ys) == len(xs):
                ax.plot(xs, ys, lw=1.0, color="#1c2430", alpha=0.85)
                band_ys_all.extend(ys)
        if fermi is not None:
            ax.axhline(0.0, color="#b42318", lw=0.9, ls="--", label="E$_F$")
            ax.legend(frameon=False, fontsize=8, loc="upper right")
            ymin, ymax = _near_fermi_window(band_ys_all)
            ax.set_ylim(ymin, ymax)
        ticks = meta.get("ticks") or []
        path_txt = ""
        if ticks:
            positions = [int(t.get("index") or 0) for t in ticks]
            labels = [_tick_label(t.get("label") or "") for t in ticks]
            ax.set_xticks(positions)
            ax.set_xticklabels(labels)
            for pos in positions:
                ax.axvline(pos, color="#9aa3ad", lw=0.6, alpha=0.7)
            path_txt = "–".join(labels) if labels else ""
            if path_txt:
                ax.set_xlabel(path_txt)
        else:
            ax.set_xlabel("k-point index")
        ax.set_ylabel("E − E$_F$ (eV)" if fermi is not None else "Energy (eV)")
        title = _sys_title("Electronic band structure")
        if path_txt:
            title += f" ({path_txt})"
        elif path_name:
            title += f" ({path_name})"
        ax.set_title(title)
        if ps and hasattr(ps, "force_axes_fonts"):
            try:
                ps.force_axes_fonts(ax)
            except Exception:
                pass
        p = out_dir / "dftb_bands.png"
        _save(fig, p, ps)
        plt.close(fig)
        paths.append(p)

    if kp.want_plot_dos(
        job_kind, has_band=has_band_data or bool(dos_rows), want_dos_flag=want_dos, dos_mesh=dos_mesh, mode=mode
    ):
        # 优先均匀网格 DOS；缺省时才回退路径本征值（并在标题标明近似）
        use_mesh_dos = bool(dos_rows) or mode == "dos_mesh"
        src_rows = dos_rows if dos_rows else rows
        if not src_rows:
            src_rows = []
        dos_raw = [float(v) for r in src_rows for v in r[1:] if len(r) > 1]
        dos_ev = _to_ev(dos_raw)
        if fermi is not None:
            eigs_plot = [e - float(fermi) for e in dos_ev]
        else:
            eigs_plot = dos_ev
        dos_win = _near_fermi_window(eigs_plot) if fermi is not None else None
        xs, ys = _gaussian_dos(
            eigs_plot,
            sigma=0.12 if use_mesh_dos else 0.18,
            e_min=dos_win[0] if dos_win else None,
            e_max=dos_win[1] if dos_win else None,
        )
        if xs and ys:
            fig, ax = plt.subplots(figsize=(4.8, 3.4))
            ax.plot(xs, ys, color="#0F4D92", lw=1.3)
            ax.fill_between(xs, ys, color="#0F4D92", alpha=0.15)
            if fermi is not None:
                ax.axvline(0.0, color="#b42318", lw=0.9, ls="--", label="E$_F$")
                ax.legend(frameon=False, fontsize=8)
                ax.set_xlabel("E − E$_F$ (eV)")
                if dos_win:
                    ax.set_xlim(dos_win[0], dos_win[1])
            else:
                ax.set_xlabel("Energy (eV)")
            ax.set_ylabel("DOS (arb. units)")
            title = _sys_title("Density of states")
            if use_mesh_dos:
                title += " (uniform k-mesh)"
            else:
                title += " (path-approx, not full BZ)"
            note = str(meta.get("dos_note") or "").strip()
            if note and use_mesh_dos:
                pass  # 标题已标明网格
            ax.set_title(title)
            if ps and hasattr(ps, "force_axes_fonts"):
                try:
                    ps.force_axes_fonts(ax)
                except Exception:
                    pass
            p = out_dir / "dftb_dos.png"
            _save(fig, p, ps)
            plt.close(fig)
            paths.append(p)

    # 吸收光谱：仅激发态任务 + EXC.DAT
    exc = parse_exc_dat(artifacts.get("EXC.DAT") or "")
    if kp.want_plot_absorption(job_kind, has_exc=bool(exc)):
        fig, ax = plt.subplots(figsize=(4.5, 3.2))
        energies = [float(e["energy"]) for e in exc]
        osc = [max(float(e.get("osc") or 0.0), 0.0) for e in exc]
        ax.stem(energies, osc, basefmt=" ")
        ax.set_xlabel("Excitation energy (eV)")
        ax.set_ylabel("Oscillator strength")
        ax.set_title(_sys_title("Optical absorption (Casida)"))
        if ps and hasattr(ps, "force_axes_fonts"):
            try:
                ps.force_axes_fonts(ax)
            except Exception:
                pass
        p = out_dir / "dftb_absorption.png"
        _save(fig, p, ps)
        plt.close(fig)
        paths.append(p)

    # 振动频率：stem 谱（cm⁻¹），课堂一眼可见分布
    vib = parse_modes_log(artifacts.get("modes.log") or "")
    if not vib:
        vib = parse_vibrations_tag(artifacts.get("vibrations.tag") or "")
    if kp.want_plot_vibrations(job_kind, has_freqs=bool(vib)):
        freqs = [float(v.get("freq_cm1") or 0.0) for v in vib]
        # stem 谱：无 IR 强度时用频率幅值；负频用红色提示
        fig, ax = plt.subplots(figsize=(5.0, 3.2))
        xs = list(range(1, len(freqs) + 1))
        for x, f in zip(xs, freqs):
            c = "#b42318" if f < -1e-3 else "#0F6E6A"
            ax.vlines(x, 0.0, f, color=c, lw=1.4)
            ax.plot(x, f, "o", color=c, ms=3.2)
        ax.axhline(0.0, color="#9aa3ad", lw=0.7)
        ax.set_xlabel("Mode index")
        ax.set_ylabel("Frequency (cm$^{-1}$)")
        ax.set_title(_sys_title("Vibrational frequencies"))
        if ps and hasattr(ps, "force_axes_fonts"):
            try:
                ps.force_axes_fonts(ax)
            except Exception:
                pass
        p = out_dir / "dftb_vibrations.png"
        _save(fig, p, ps)
        plt.close(fig)
        paths.append(p)

    # MD：Total MD Energy（及温度）轨迹；md.out > dftb.log > detailed.out
    md_traj = {"energies_eV": [], "temps_K": []}
    for key in ("md.out", "dftb.log", "detailed.out"):
        md_traj = parse_md_trajectory(artifacts.get(key) or "")
        if len(md_traj.get("energies_eV") or []) >= 2:
            break
    md_e = md_traj.get("energies_eV") or []
    md_t = md_traj.get("temps_K") or []
    if kp.want_plot_md_energy(job_kind, has_trace=len(md_e) >= 2):
        xs = list(range(len(md_e)))
        if md_t and len(md_t) == len(md_e):
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(4.8, 4.4), sharex=True)
            ax1.plot(xs, md_e, color="#0F4D92", lw=1.3)
            ax1.set_ylabel("Total MD E (eV)")
            ax1.set_title(_sys_title("BOMD trajectory"))
            ax2.plot(xs, md_t, color="#B45309", lw=1.2)
            ax2.set_xlabel("MD step")
            ax2.set_ylabel("T (K)")
            axes = (ax1, ax2)
        else:
            fig, ax1 = plt.subplots(figsize=(4.6, 3.2))
            ax1.plot(xs, md_e, color="#0F4D92", lw=1.3)
            ax1.set_xlabel("MD step")
            ax1.set_ylabel("Total MD E (eV)")
            ax1.set_title(_sys_title("BOMD energy trajectory"))
            axes = (ax1,)
        if ps and hasattr(ps, "force_axes_fonts"):
            for ax in axes:
                try:
                    ps.force_axes_fonts(ax)
                except Exception:
                    pass
        p = out_dir / "dftb_md_energy.png"
        _save(fig, p, ps)
        plt.close(fig)
        paths.append(p)

    return paths
