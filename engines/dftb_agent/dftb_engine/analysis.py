"""解析 DFTB+ detailed.out / band.out / EXC.DAT 等产物。"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def parse_detailed_out(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {"raw_lines": len((text or "").splitlines())}
    if not text:
        return out
    m = re.search(r"(?i)Total energy:\s+([-\d.Ee+]+)\s+H(?:\s+([-\d.Ee+]+)\s+eV)?", text)
    if m:
        out["total_energy_H"] = float(m.group(1))
        if m.group(2) is not None:
            out["total_energy_eV"] = float(m.group(2))
        else:
            out["total_energy_eV"] = float(m.group(1)) * 27.211386245988
    m = re.search(r"Fermi level:\s+([-\d.Ee+]+)\s+H", text)
    if m:
        out["fermi_H"] = float(m.group(1))
        out["fermi_eV"] = float(m.group(1)) * 27.211386245988
    if re.search(r"Geometry optimization completed|Geometry converged", text, re.I):
        out["geo_converged"] = True
    if re.search(r"SCC converged", text, re.I):
        out["scc_converged"] = True

    scc_iters = [
        int(m.group(1))
        for m in re.finditer(r"(?i)(?:iSCC|SCC\s*iteration|Iteration)\s*[:=]?\s*(\d+)", text)
    ]
    if scc_iters:
        out["scc_iterations"] = max(scc_iters)
        out["scc_iter_trace"] = scc_iters[-80:]

    opt_energies = parse_opt_energies(text)
    if opt_energies:
        out["opt_energies_eV"] = opt_energies
    return out


def parse_opt_energies(text: str) -> list[float]:
    """几何优化逐步能量（eV）。dftb.log 常用 'Total Energy:'（E 大写）。"""
    energies: list[float] = []
    if not text:
        return energies
    # 优先：Geometry step 块内的 Total Energy ... eV
    for m in re.finditer(
        r"(?i)(?:\*\*\*\s*)?Geometry\s+step:\s*(\d+)[\s\S]{0,1200}?"
        r"Total\s+Energy:\s+([-\d.Ee+]+)\s+H(?:\s+([-\d.Ee+]+)\s+eV)?",
        text,
    ):
        try:
            if m.group(3) is not None:
                energies.append(float(m.group(3)))
            else:
                energies.append(float(m.group(2)) * 27.211386245988)
        except ValueError:
            pass
    if len(energies) >= 2:
        return energies[:500]
    # 退化：多条「Total Energy:」（不含 Total Electronic / Total MD）
    energies = []
    for m in re.finditer(
        r"(?i)Total\s+Energy:\s+([-\d.Ee+]+)\s+H(?:\s+([-\d.Ee+]+)\s+eV)?",
        text,
    ):
        try:
            if m.group(2) is not None:
                energies.append(float(m.group(2)))
            else:
                energies.append(float(m.group(1)) * 27.211386245988)
        except ValueError:
            pass
    if len(energies) < 2:
        return []
    return energies[:500]


_HA_TO_CM1 = 219474.6313705


def parse_modes_log(text: str) -> list[dict[str, Any]]:
    """解析 modes 日志中的振动频率表（Mode / cm-1）。"""
    out: list[dict[str, Any]] = []
    if not text:
        return out
    in_table = False
    for line in text.splitlines():
        s = line.strip()
        if re.search(r"(?i)Mode\s+cm-1", s):
            in_table = True
            continue
        if not in_table:
            continue
        if not s or s.startswith("|") or s.startswith("-"):
            if out:
                break
            continue
        m = re.match(r"^(\d+)\s+([-\d.Ee+]+)\s*$", s)
        if not m:
            if out and not re.match(r"^\d+", s):
                break
            continue
        try:
            out.append({"mode": int(m.group(1)), "freq_cm1": float(m.group(2))})
        except ValueError:
            continue
    return out


def parse_vibrations_tag(text: str) -> list[dict[str, Any]]:
    """解析 vibrations.tag 中的 frequencies（Hartree → cm⁻¹）。"""
    if not text:
        return []
    m = re.search(
        r"frequencies\s*:real:1:(\d+)\s*((?:[-\d.Ee+]+\s*)+)",
        text,
        flags=re.I,
    )
    if not m:
        return []
    vals = [float(x) for x in m.group(2).split()]
    return [
        {"mode": i + 1, "freq_cm1": float(v) * _HA_TO_CM1, "freq_Ha": float(v)}
        for i, v in enumerate(vals)
    ]


def parse_md_trajectory(text: str) -> dict[str, list[float]]:
    """解析 MD 轨迹：优先 Total MD Energy / MD Temperature（md.out、dftb.log）。"""
    energies: list[float] = []
    temps: list[float] = []
    if not text:
        return {"energies_eV": [], "temps_K": []}

    # 首选：Total MD Energy ... eV（或仅 Hartree）
    for m in re.finditer(
        r"(?i)Total\s+MD\s+Energy:\s+([-\d.Ee+]+)\s+H(?:\s+([-\d.Ee+]+)\s+eV)?",
        text,
    ):
        try:
            if m.group(2) is not None:
                energies.append(float(m.group(2)))
            else:
                energies.append(float(m.group(1)) * 27.211386245988)
        except ValueError:
            pass
    for m in re.finditer(
        r"(?i)MD\s+Temperature:\s+[-\d.Ee+]+\s+(?:H|au)\s+([-\d.Ee+]+)\s+K",
        text,
    ):
        try:
            temps.append(float(m.group(1)))
        except ValueError:
            pass

    # 退化：仅 MD step + Total energy（勿用 Geometry step，以免与几何优化混淆）
    if len(energies) < 2:
        fallback: list[float] = []
        for m in re.finditer(
            r"(?i)MD\s*step\s*[:=]?\s*(\d+)[\s\S]{0,800}?"
            r"Total\s+Energy:\s+([-\d.Ee+]+)\s+H(?:\s+([-\d.Ee+]+)\s+eV)?",
            text,
        ):
            try:
                if m.group(3) is not None:
                    fallback.append(float(m.group(3)))
                else:
                    fallback.append(float(m.group(2)) * 27.211386245988)
            except ValueError:
                pass
        if len(fallback) >= 2:
            energies = fallback

    return {
        "energies_eV": energies[:2000],
        "temps_K": temps[:2000],
    }


def parse_md_energies(text: str) -> list[float]:
    """兼容旧接口：仅返回 MD 总能量轨迹（eV）。"""
    return parse_md_trajectory(text).get("energies_eV") or []


def parse_exc_dat(text: str) -> list[dict[str, Any]]:
    """解析 Casida EXC.DAT（能量 / 振子强度）。"""
    out: list[dict[str, Any]] = []
    if not text:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("!"):
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        try:
            # 常见：index energy osc ... 或 energy osc
            if len(parts) >= 3:
                i = int(float(parts[0]))
                energy = float(parts[1])
                osc = float(parts[2])
            else:
                i = len(out) + 1
                energy = float(parts[0])
                osc = float(parts[1])
            out.append({"i": i, "energy": energy, "osc": osc})
        except ValueError:
            continue
    return out[:80]


def parse_band_out(text: str) -> dict[str, Any]:
    """解析 DFTB+ band.out（KPT 块 + 能级/占据）。

    返回 rows：每行为 [k_index, e1, e2, ...]（能量单位 Hartree）。
    """
    rows: list[list[float]] = []
    cur_k = 0
    cur_eigs: list[float] = []

    def flush() -> None:
        nonlocal cur_eigs
        if cur_k > 0 and cur_eigs:
            rows.append([float(cur_k), *cur_eigs])
        cur_eigs = []

    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.upper().startswith("KPT"):
            flush()
            parts = s.split()
            try:
                # KPT <idx> SPIN ...
                cur_k = int(parts[1])
            except Exception:
                cur_k += 1
            continue
        parts = s.split()
        if len(parts) >= 2:
            try:
                # "<band_index> <energy> [occupancy]"
                _bi = int(float(parts[0]))
                e = float(parts[1])
                cur_eigs.append(e)
            except ValueError:
                # 兼容旧扁平格式：整行数值
                try:
                    vals = [float(x) for x in parts]
                    if len(vals) >= 2:
                        rows.append(vals)
                except ValueError:
                    continue
    flush()
    return {"nk": len(rows), "rows": rows[:8000]}


def parse_band_meta(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _energies_to_ev(values: list[float]) -> list[float]:
    """band.out 能级：数值尺度 <4 时按 Hartree，否则按 eV。"""
    if not values:
        return []
    if max(abs(v) for v in values) < 4.0:
        return [v * 27.211386245988 for v in values]
    return list(values)


def estimate_band_gap(band: dict[str, Any], fermi_eV: Optional[float]) -> dict[str, Any]:
    """由 band.out + Fermi 估算带隙（课堂演示用，定性）。"""
    rows = band.get("rows") or []
    if not rows or fermi_eV is None:
        return {}
    eigs: list[float] = []
    for r in rows:
        for v in r[1:]:
            try:
                eigs.append(float(v))
            except (TypeError, ValueError):
                continue
    eigs_ev = _energies_to_ev(eigs)
    if not eigs_ev:
        return {}
    tol = 1e-4
    below = [e for e in eigs_ev if e <= float(fermi_eV) + tol]
    above = [e for e in eigs_ev if e > float(fermi_eV) + tol]
    out: dict[str, Any] = {"fermi_eV": float(fermi_eV)}
    if below:
        out["vbm_eV"] = max(below)
    if above:
        out["cbm_eV"] = min(above)
    if below and above:
        gap = float(out["cbm_eV"]) - float(out["vbm_eV"])
        out["gap_eV"] = max(0.0, gap)
        out["gap_type"] = "metallic_or_zero" if gap <= 0.05 else "gapped"
    return out


def flatten_analysis(res: dict[str, Any]) -> dict[str, Any]:
    """供前端/成稿使用的扁平字段。"""
    detailed = res.get("detailed") or {}
    flat = dict(res)
    if detailed.get("total_energy_eV") is not None:
        flat["total_energy"] = detailed["total_energy_eV"]
        flat["total_energy_eV"] = detailed["total_energy_eV"]
    if detailed.get("fermi_eV") is not None:
        flat["fermi_energy"] = detailed["fermi_eV"]
        flat["fermi_eV"] = detailed["fermi_eV"]
    conv = bool(detailed.get("geo_converged") or detailed.get("scc_converged"))
    flat["converged"] = conv
    flat["geometry_converged"] = bool(detailed.get("geo_converged"))
    flat["scc_converged"] = bool(detailed.get("scc_converged"))
    if res.get("ok") is not None:
        flat["ok"] = res["ok"]
    exc = detailed.get("excitations") or res.get("excitations") or []
    if exc:
        flat["n_excitations"] = len(exc)
    band = res.get("band") or {}
    if band.get("nk"):
        flat["n_kpoints"] = band["nk"]
    meta = res.get("band_meta") or {}
    if meta.get("path_name"):
        flat["band_path"] = meta.get("path_name")
    if meta.get("mode"):
        flat["band_mode"] = meta.get("mode")
    gap = res.get("band_gap") or {}
    if gap.get("gap_eV") is not None:
        flat["band_gap_eV"] = gap["gap_eV"]
        flat["vbm_eV"] = gap.get("vbm_eV")
        flat["cbm_eV"] = gap.get("cbm_eV")
        flat["gap_type"] = gap.get("gap_type")
    detailed = res.get("detailed") or {}
    if detailed.get("scc_iterations") is not None:
        flat["scc_iterations"] = detailed["scc_iterations"]
    if detailed.get("opt_energies_eV"):
        flat["opt_energies_eV"] = detailed["opt_energies_eV"]
    vib = res.get("vibrations") or []
    if vib:
        flat["vibrations"] = vib
        flat["n_vibrations"] = len(vib)
        real = [float(v.get("freq_cm1") or 0.0) for v in vib if float(v.get("freq_cm1") or 0.0) > 50]
        if real:
            flat["vib_freq_min_cm1"] = min(real)
            flat["vib_freq_max_cm1"] = max(real)
    md_e = res.get("md_energies_eV") or detailed.get("md_energies_eV") or []
    if md_e:
        flat["md_energies_eV"] = md_e
        flat["md_steps"] = len(md_e)
    md_t = res.get("md_temps_K") or detailed.get("md_temps_K") or []
    if md_t:
        flat["md_temps_K"] = md_t
        try:
            flat["md_temp_mean_K"] = sum(float(x) for x in md_t) / len(md_t)
            flat["md_temp_min_K"] = min(float(x) for x in md_t)
            flat["md_temp_max_K"] = max(float(x) for x in md_t)
        except (TypeError, ValueError):
            pass
    perf = res.get("performance") or {}
    if perf:
        flat["performance"] = perf
        if perf.get("wall_seconds") is not None:
            flat["wall_seconds"] = perf["wall_seconds"]
    return flat


def parse_performance(artifacts: dict[str, str]) -> dict[str, Any]:
    """从作业墙钟文件与日志提取本地性能指标。"""
    perf: dict[str, Any] = {}
    try:
        started = int((artifacts.get("started_at") or "").strip())
        finished = int((artifacts.get("finished_at") or "").strip())
        if finished >= started > 0:
            perf["started_at"] = started
            perf["finished_at"] = finished
            perf["wall_seconds"] = finished - started
    except ValueError:
        pass
    try:
        ws = float((artifacts.get("wall_seconds") or "").strip())
        if ws >= 0:
            perf["wall_seconds"] = ws
    except ValueError:
        pass
    exit_raw = (artifacts.get("exit_code") or "").strip()
    if exit_raw.isdigit():
        perf["exit_code"] = int(exit_raw)
    log = artifacts.get("dftb.log") or ""
    m = re.search(r"(?i)(?:Total\s+time|CPU\s+time|Wall\s*clock)\s*[:=]?\s*([-\d.Ee+]+)\s*(s|sec|seconds)?", log)
    if m:
        try:
            perf["engine_reported_seconds"] = float(m.group(1))
        except ValueError:
            pass
    detailed = parse_detailed_out(artifacts.get("detailed.out") or "")
    if detailed.get("scc_iterations") is not None:
        perf["scc_iterations"] = detailed["scc_iterations"]
    if detailed.get("scc_iter_trace"):
        perf["scc_iter_trace"] = detailed["scc_iter_trace"]
    if detailed.get("opt_energies_eV"):
        perf["energy_trace_eV"] = detailed["opt_energies_eV"]
    return perf


def analyze_artifacts(artifacts: dict[str, str]) -> dict[str, Any]:
    res: dict[str, Any] = {"ok": True, "files": list(artifacts.keys())}
    if "detailed.out" in artifacts:
        res["detailed"] = parse_detailed_out(artifacts["detailed.out"])
    if "band.out" in artifacts:
        res["band"] = parse_band_out(artifacts["band.out"])
    if "band_meta.json" in artifacts:
        res["band_meta"] = parse_band_meta(artifacts["band_meta.json"])
    # 激发态只认 EXC.DAT，避免 detailed.out 轨道布居行误判
    exc = parse_exc_dat(artifacts.get("EXC.DAT") or "")
    if exc:
        res["excitations"] = exc
        detailed = res.setdefault("detailed", {})
        detailed["excitations"] = exc
    detailed = res.setdefault("detailed", {})
    log_txt = artifacts.get("dftb.log") or ""
    det_txt = artifacts.get("detailed.out") or ""
    blob_txt = log_txt + "\n" + det_txt
    is_md_job = bool(
        re.search(r"(?i)Total\s+MD\s+Energy|Molecular dynamics completed|\bMD step:", blob_txt)
    )
    is_opt_job = (not is_md_job) and bool(
        re.search(r"(?i)Geometry converged|Geometry optimization", blob_txt)
    )
    # 优化轨迹：仅几何优化任务；detailed.out 常只有末步，dftb.log 含逐步 Total Energy
    opt_e = detailed.get("opt_energies_eV") or []
    if is_opt_job:
        if len(opt_e) < 2:
            opt_e = parse_opt_energies(log_txt)
        if len(opt_e) >= 2:
            detailed["opt_energies_eV"] = opt_e
        else:
            detailed.pop("opt_energies_eV", None)
    else:
        detailed.pop("opt_energies_eV", None)
        opt_e = []
    vib = parse_modes_log(artifacts.get("modes.log") or "")
    if not vib:
        vib = parse_vibrations_tag(artifacts.get("vibrations.tag") or "")
    if vib:
        res["vibrations"] = vib
    # MD：仅 Total MD Energy / MD step；勿把几何优化 Geometry step 当成 MD
    md_traj = {"energies_eV": [], "temps_K": []}
    if is_md_job:
        for key in ("md.out", "dftb.log", "detailed.out"):
            md_traj = parse_md_trajectory(artifacts.get(key) or "")
            if len(md_traj.get("energies_eV") or []) >= 2:
                break
    md_e = md_traj.get("energies_eV") or []
    md_t = md_traj.get("temps_K") or []
    if md_e:
        res["md_energies_eV"] = md_e
        detailed["md_energies_eV"] = md_e
    if md_t:
        res["md_temps_K"] = md_t
        detailed["md_temps_K"] = md_t
    perf = parse_performance(artifacts)
    if perf:
        res["performance"] = perf
    log = artifacts.get("dftb.log") or ""
    status = (artifacts.get("status") or "").strip().lower()
    detailed = res.get("detailed") or {}
    fermi = detailed.get("fermi_eV")
    if res.get("band") and fermi is not None:
        gap = estimate_band_gap(res["band"], float(fermi))
        if gap:
            res["band_gap"] = gap
    fatal = bool(re.search(r"(?i)\b(fatal|aborted|segmentation)\b", log))
    if status == "error" or fatal:
        res["ok"] = False
        res["log_tail"] = log[-800:]
    elif (
        detailed.get("geo_converged")
        or detailed.get("scc_converged")
        or detailed.get("total_energy_H") is not None
        or (res.get("band") or {}).get("nk")
        or exc
        or vib
        or md_e
    ):
        res["ok"] = True
    res.update(flatten_analysis(res))
    return res
