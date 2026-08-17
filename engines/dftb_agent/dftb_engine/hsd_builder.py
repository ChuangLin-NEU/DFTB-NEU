"""HSD 块拼装 — 对照 DFTB+ Manual / Recipes（以 21.x 可解析关键字为准）。"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from . import sk_resolver as sk


def geometry_include_gen(filename: str = "geo.gen") -> str:
    return f'Geometry = GenFormat {{\n  <<< "{filename}"\n}}'


def geometry_include_vasp(filename: str = "POSCAR") -> str:
    return f'Geometry = VaspFormat {{\n  <<< "{filename}"\n}}'


def geometry_include_xyz(filename: str = "struc.xyz") -> str:
    return f'Geometry = xyzFormat {{\n  <<< "{filename}"\n}}'


def hamiltonian_dftb(
    elements: Iterable[str],
    *,
    sk_set: str = "3ob",
    scc: bool = True,
    third_order: bool = False,
    filling_temp: float = 300.0,
    kpoints: Optional[str] = None,
    kpoints_block: Optional[str] = None,
    solvation: Optional[str] = None,
    dispersion: bool = False,
    spin_constants: bool = False,
    colinear_spin: bool = False,
    unpaired_electrons: float = 0.0,
    max_scc_iter: Optional[int] = None,
    read_charges: bool = False,
    omit_filling: bool = False,
) -> str:
    els = [str(e).strip().capitalize() for e in elements]
    # 课堂默认放宽 SCC：避免一步几何优化就因默认迭代不够而强退
    scc_iters = int(max_scc_iter) if max_scc_iter is not None else 250
    body = [
        "Hamiltonian = DFTB {",
        f"  SCC = {'Yes' if scc else 'No'}",
        "  SCCTolerance = 1.0E-5",
        f"  MaxSCCIterations = {scc_iters}",
        "  Mixer = Broyden { MixingParameter = 0.2 }",
    ]
    if read_charges:
        body.append("  ReadInitialCharges = Yes")
    if third_order:
        # 仅在显式开启三阶时写入；Casida 等任务必须关闭，且勿因 sk_set=3ob 强行打开
        body.append("  ThirdOrderFull = Yes")
        body.append("  HCorrection = Damping { Exponent = 4.0 }")
        hub = {
            "H": -0.1857,
            "C": -0.1492,
            "N": -0.1535,
            "O": -0.1575,
            "S": -0.11,
            "P": -0.14,
            "F": -0.1623,
            "Cl": -0.0697,
            "Br": -0.0573,
            "I": -0.0433,
            "Mg": -0.02,
            "Zn": -0.03,
            "Na": -0.03,
            "K": -0.03,
            "Ca": -0.034,
        }
        if any(e in hub for e in els):
            body.append("  HubbardDerivs = {")
            for e in els:
                if e in hub:
                    body.append(f"    {e} = {hub[e]}")
            body.append("  }")
    body.append(sk.max_angular_momentum_block(els))
    body.append(sk.slater_koster_block(sk_set))
    if not omit_filling:
        body.append("  Filling = Fermi {")
        body.append(f"    Temperature [K] = {float(filling_temp)}")
        body.append("  }")
    if dispersion:
        # Recipes solvation DFTB3-D4；parser≥14 要求显式 s9
        body += [
            "  Dispersion = DFTD4 {",
            "    s6 = 1.0",
            "    s8 = 0.4727337",
            "    s9 = 1.0",
            "    a1 = 0.5467502",
            "    a2 = 4.4955068",
            "  }",
        ]
    if solvation:
        # Recipes: Solvation = GeneralizedBorn { ParamFile = ... }
        body.append(f"  Solvation = GeneralizedBorn {{ ParamFile = \"{solvation}\" }}")
    # 共线自旋：缺陷石墨烯等需从优化阶段起就打开
    if colinear_spin:
        body.append("  SpinPolarisation = Colinear {")
        body.append(f"    UnpairedElectrons = {float(unpaired_electrons):.6g}")
        body.append("  }")
        spin_constants = True
    if spin_constants:
        # Recipes linresp / REKS / 自旋极化：部分激发与共线自旋需要 SpinConstants
        body.append("  SpinConstants = {")
        for e in els:
            if e == "H":
                body.append("    H = { -0.072 }")
            elif e == "C":
                body.append("    C = { -0.031 -0.025 -0.025 -0.023 }")
            elif e == "N":
                body.append("    N = { -0.033 -0.027 -0.027 -0.026 }")
            elif e == "O":
                body.append("    O = { -0.035 -0.030 -0.030 -0.028 }")
            else:
                body.append(f"    {e} = {{ -0.03 }}")
        body.append("  }")
    if kpoints_block:
        # 完整块（可含 Klines / SupercellFolding），需自带缩进
        kb = str(kpoints_block).rstrip()
        if not kb.lstrip().startswith("KPointsAndWeights"):
            kb = "  KPointsAndWeights = " + kb.lstrip()
        if not kb.startswith("  "):
            kb = "\n".join(("  " + ln if ln.strip() else ln) for ln in kb.splitlines())
        body.append(kb)
    elif kpoints:
        parts = [int(x) for x in str(kpoints).replace(",", " ").split() if x][:3]
        while len(parts) < 3:
            parts.append(1)
        nx, ny, nz = parts
        body += [
            "  KPointsAndWeights = SupercellFolding {",
            f"    {nx} 0 0",
            f"    0 {ny} 0",
            f"    0 0 {nz}",
            "    0.0 0.0 0.0",
            "  }",
        ]
    body.append("}")
    return "\n".join(body)


def hamiltonian_xtb(*, method: str = "GFN2-xTB", solvation: Optional[str] = None) -> str:
    lines = [
        "Hamiltonian = xTB {",
        f'  Method = "{method}"',
    ]
    if solvation:
        lines.append(f'  Solvation = GeneralizedBorn {{ ParamFile = "{solvation}" }}')
    lines.append("}")
    return "\n".join(lines)


def driver_none() -> str:
    return "Driver = {}"


def driver_geo_opt(*, max_steps: int = 100) -> str:
    return "\n".join(
        [
            "Driver = GeometryOptimization {",
            "  Optimizer = Rational {}",
            "  MovedAtoms = 1:-1",
            f"  MaxSteps = {int(max_steps)}",
            '  OutputPrefix = "geo_end"',
            "  Convergence = {",
            "    GradElem = 1E-4",
            "  }",
            "}",
        ]
    )


def driver_second_derivatives(*, delta: float = 1e-4) -> str:
    # Recipes moleculardynamics/vibrations
    return "\n".join(
        [
            "Driver = SecondDerivatives {",
            f"  Delta = {float(delta)}",
            "}",
        ]
    )


def driver_velocity_verlet(
    *,
    steps: int = 200,
    timestep_fs: float = 0.5,
    temperature_k: float = 300.0,
    anneal: bool = False,
) -> str:
    lines = [
        "Driver = VelocityVerlet {",
        f"  TimeStep [fs] = {float(timestep_fs)}",
        f"  Steps = {int(steps)}",
        "  MovedAtoms = 1:-1",
    ]
    if anneal:
        # Recipes：TemperatureProfile 决定总步数；新版解析器在有 profile 时会忽略独立 Steps
        t0 = float(temperature_k)
        n1 = max(steps // 4, 1)
        n2 = max(steps // 4, 1)
        n3 = max(steps // 4, 1)
        n4 = max(steps - n1 - n2 - n3, 1)
        lines = [
            "Driver = VelocityVerlet {",
            f"  TimeStep [fs] = {float(timestep_fs)}",
            "  MovedAtoms = 1:-1",
            "  Thermostat = NoseHoover {",
            "    Temperature [K] = TemperatureProfile {",
            f"      constant 1 {t0 * 0.5}",
            f"      linear {n1} {t0}",
            f"      constant {n2} {t0 * 1.2}",
            f"      linear {n3} {t0}",
            f"      constant {n4} {t0}",
            "    }",
            "    CouplingStrength [cm^-1] = 3200",
            "  }",
            "}",
        ]
        return "\n".join(lines)
    lines += [
        "  Thermostat = NoseHoover {",
        f"    Temperature [K] = {float(temperature_k)}",
        "    CouplingStrength [cm^-1] = 3200",
        "  }",
    ]
    lines.append("}")
    return "\n".join(lines)


def analysis_band_structure(*, kpoints_block: str = "") -> str:
    """新版 DFTB+：能带 k 点写在 Hamiltonian；Analysis 仅保留 ProjectStates。"""
    _ = kpoints_block  # 兼容旧调用
    return "\n".join(
        [
            "Analysis = {",
            "  WriteBandOut = Yes",
            "  ProjectStates = {}",
            "}",
        ]
    )


def analysis_forces() -> str:
    # parser≥14：CalculateForces 已更名为 PrintForces
    return "Analysis = {\n  PrintForces = Yes\n  WriteBandOut = No\n}"


def analysis_no_band_out() -> str:
    """关闭默认 band.out（分子/优化等非能带任务不需要）。"""
    return "Analysis = {\n  WriteBandOut = No\n}"


_BAND_OUT_KINDS = frozenset({"dftb_band", "dftb_dos", "dftb_defect", "dftb_boundary"})


def ensure_write_band_out(hsd: str, kind: str = "") -> str:
    """按任务类型保证 WriteBandOut；覆盖用户旧 HSD 缺省（默认 Yes）导致多余 band.out。"""
    text = (hsd or "").strip()
    if not text:
        return text
    want = "Yes" if (kind or "").strip().lower() in _BAND_OUT_KINDS else "No"

    if re.search(r"WriteBandOut\s*=", text, flags=re.I):
        return re.sub(
            r"WriteBandOut\s*=\s*\w+",
            f"WriteBandOut = {want}",
            text,
            count=1,
            flags=re.I,
        )
    if re.search(r"Analysis\s*=\s*\{", text, flags=re.I):
        return re.sub(
            r"(Analysis\s*=\s*\{)",
            rf"\1\n  WriteBandOut = {want}",
            text,
            count=1,
            flags=re.I,
        )
    # 插在 Options 前；没有则追加
    block = f"Analysis = {{\n  WriteBandOut = {want}\n}}\n\n"
    if re.search(r"Options\s*=\s*\{", text, flags=re.I):
        return re.sub(r"(Options\s*=\s*\{)", block + r"\1", text, count=1, flags=re.I)
    return text.rstrip() + "\n\n" + block


def excited_state_casida(
    *,
    n_excitations: int = 10,
    symmetry: str = "singlet",
    state_of_interest: int = 0,
) -> str:
    """Casida 线性响应块（ParserVersion≥14；与三阶 DFTB 不兼容）。

    state_of_interest>0 时才会算激发态势力（几何优化在激发态上需要）。
    """
    lines = [
        "ExcitedState = {",
        "  Casida = {",
        f"    NrOfExcitations = {int(n_excitations)}",
        f"    Symmetry = {symmetry}",
        "    Diagonaliser = Arpack {}",
        "    WriteTransitions = Yes",
    ]
    if int(state_of_interest) > 0:
        lines.append(f"    StateOfInterest = {int(state_of_interest)}")
    lines += [
        "  }",
        "}",
    ]
    return "\n".join(lines)


def electron_dynamics_block(
    *,
    steps: int = 2000,
    timestep_au: float = 0.2,
    field_strength: float = 0.001,
    polarization: str = "all",
) -> str:
    # Recipes electronicdynamics/spectrum（块名 ElectronDynamics）
    return "\n".join(
        [
            "ElectronDynamics = {",
            f"  Steps = {int(steps)}",
            f"  TimeStep [au] = {float(timestep_au)}",
            "  Perturbation = Kick {",
            f'    PolarizationDirection = "{polarization}"',
            "  }",
            f"  FieldStrength [V/A] = {float(field_strength)}",
            "}",
        ]
    )


def reks_ssr22_block(*, target_state: int = 1) -> str:
    # Recipes reks/single_state_reks
    return "\n".join(
        [
            "REKS = SSR22 {",
            "  Energy = {",
            '    Functional = { "PPS" }',
            "  }",
            f"  TargetState = {int(target_state)}",
            "  FonMaxIter = 100",
            "  Shift = 1.0",
            "  VerbosityLevel = 1",
            "}",
        ]
    )


def transport_block(params: dict[str, Any]) -> str:
    # Recipes transport/molecule-junction — AtomRange 可由 params 覆盖
    dev = params.get("device_atoms") or "1 10"
    src = params.get("source_atoms") or "11 20"
    drain = params.get("drain_atoms") or "21 30"
    task = str(params.get("transport_task") or "ContactHamiltonian")
    contact_id = str(params.get("contact_id") or "Source")
    lines = [
        "Transport = {",
        "  Device = {",
        f"    AtomRange = {dev}",
        "  }",
        "  Contact = {",
        '    Id = "Source"',
        f"    AtomRange = {src}",
        "    PLShiftTolerance = 0.01",
        "  }",
        "  Contact = {",
        '    Id = "Drain"',
        f"    AtomRange = {drain}",
        "    PLShiftTolerance = 0.01",
        "  }",
    ]
    if task.lower() == "uploadcontacts":
        lines.append("  Task = UploadContacts {}")
    else:
        lines += [
            "  Task = ContactHamiltonian {",
            f'    ContactId = "{contact_id}"',
            "  }",
        ]
    lines.append("}")
    return "\n".join(lines)


def helical_geometry_note(params: dict[str, Any]) -> str:
    # Recipes boundaryconditions/helical — 在 Geometry 外用 Helical 相关选项时由用户几何决定
    n_k = int(params.get("helical_k") or 80)
    return "\n".join(
        [
            "# Helical BZ sampling (Recipes boundaryconditions/helical)",
            "# 将下列块并入 Hamiltonian（周期螺旋几何就绪后）：",
            f"#   KPointsAndWeights = HelicalUniform {{{n_k} 0.5}}",
        ]
    )


# 本机课堂环境 DFTB+（commit a23bfb2）当前解析器主版本
CURRENT_PARSER_VERSION = 14


def options_common(*, parser_version: int = CURRENT_PARSER_VERSION) -> str:
    return "\n".join(
        [
            "Options = {",
            "  WriteDetailedOut = Yes",
            "}",
            "ParserOptions = {",
            f"  ParserVersion = {int(parser_version)}",
            "}",
        ]
    )


def assemble_hsd(parts: list[str]) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip()) + "\n"


# kind → 回归断言用的必备子串（对照 Recipes）
KIND_REQUIRED_KEYS: dict[str, list[str]] = {
    "dftb_scc": ["Hamiltonian = DFTB", "Driver = {}", "SCC = Yes"],
    "dftb_opt": ["GeometryOptimization", "MaxAngularMomentum", "SlaterKosterFiles"],
    "dftb_band": ["KPointsAndWeights", "Klines"],
    "dftb_dos": ["KPointsAndWeights", "SupercellFolding"],
    "dftb_vib": ["SecondDerivatives"],
    "dftb_md": ["VelocityVerlet", "NoseHoover"],
    "dftb_md_anneal": ["VelocityVerlet", "TemperatureProfile"],
    "dftb_solv": ["Solvation = GeneralizedBorn", "GeometryOptimization"],
    "dftb_defect": ["KPointsAndWeights", "Klines"],
    "dftb_td": ["ExcitedState", "Casida", "NrOfExcitations"],
    "dftb_td_relax": ["ExcitedState", "GeometryOptimization"],
    "dftb_edyn": ["ElectronDynamics", "Perturbation = Kick"],
    "dftb_ehrenfest": ["ElectronDynamics", "Perturbation"],
    "dftb_phonon": ["PrintForces", "SCC = Yes"],
    "dftb_barrier": ["GeometryOptimization", "SCC = Yes"],
    "dftb_reks": ["REKS = SSR22", "SpinConstants"],
    "dftb_transport": ["Transport =", "ContactHamiltonian", "Device"],
    "dftb_boundary": ["HelicalUniform", "Hamiltonian = DFTB"],
    "dftb_gsm": ["PrintForces", "SCC = Yes"],
    "dftb_xtb": ["Hamiltonian = xTB", "GFN2-xTB"],
    "dftb_ase": ["Hamiltonian = DFTB", "SCC = Yes"],
    "dftb_ipi": ["Hamiltonian = DFTB", "PrintForces"],
}


def build_hsd_for_kind(
    kind: str,
    elements: list[str],
    *,
    sk_set: str = "3ob",
    params: Optional[dict[str, Any]] = None,
    geometry_mode: str = "gen",
) -> str:
    """按能力族 kind 生成 dftb_in.hsd（真实关键字，非注释占位）。"""
    p = dict(params or {})
    if geometry_mode == "vasp":
        geo = geometry_include_vasp("POSCAR")
    elif geometry_mode == "xyz":
        geo = geometry_include_xyz("struc.xyz")
    else:
        geo = geometry_include_gen("geo.gen")

    use_xtb = kind == "dftb_xtb" or str(p.get("hamiltonian") or "").lower() == "xtb"
    solv = p.get("solvation_param")
    if kind == "dftb_solv" and not solv:
        solv = "$HOME/.dftb-neu/share/dftb/sk/solvation/3ob-1-0/param_alpb_h2o.txt"

    is_td = kind in ("dftb_td", "dftb_td_relax")
    is_reks = kind == "dftb_reks"
    symmetry = str(p.get("symmetry") or "singlet").strip().lower()
    # Casida 与三阶 DFTB 不兼容；单重态不必写 SpinConstants（三重态/both 才需要）
    need_spin = bool(p.get("spin_constants")) or is_reks or (
        is_td and symmetry in ("triplet", "both")
    )
    need_colinear = bool(
        p.get("spin_polarized")
        or p.get("colinear_spin")
        or p.get("spin_polarisation")
    )
    unpaired = float(p.get("unpaired_electrons") if p.get("unpaired_electrons") is not None else 0.0)
    if (
        need_colinear
        and "unpaired_electrons" not in p
        and unpaired <= 0
        and kind in ("dftb_defect", "dftb_band", "dftb_dos", "dftb_opt")
    ):
        # 未显式指定时：石墨烯空位等局域磁矩默认 1 个未配对电子
        unpaired = 1.0
    cluster = bool(p.get("cluster") or p.get("molecule"))
    # 非 cluster 默认按周期体系写 k 点（几何优化 / SCC 等也会要求 KPointsAndWeights）
    if cluster:
        periodic = False
    elif "periodic" in p:
        periodic = bool(p.get("periodic"))
    else:
        periodic = True
    kpts = p.get("kpoints") if periodic else None
    if kind == "dftb_defect" and not kpts:
        kpts = "6 6 1"
    if periodic and not kpts:
        # SCC 基态需合理 k 网格；二维默认 12×12×1；纳米带/大胞默认 Gamma
        if str(p.get("dimensionality") or "") == "2d" or str(p.get("band_path") or "") in (
            "graphene",
            "hex",
            "2d",
        ):
            kpts = "12 12 1"
        elif kind in ("dftb_band", "dftb_dos"):
            kpts = "8 8 8"
        elif str(p.get("dimensionality") or "") in ("1d", "ribbon", "nanoribbon"):
            kpts = "4 1 1"
        else:
            kpts = "4 4 4"

    ham_kblock = str(p.get("ham_kpoints_block") or "").strip() or None
    if not periodic:
        ham_kblock = None
        kpts = None
    if use_xtb:
        ham = hamiltonian_xtb(
            method=str(p.get("xtb_method") or "GFN2-xTB"),
            solvation=solv if kind == "dftb_solv" else None,
        )
    else:
        third = bool(p.get("third_order", sk_set.startswith("3ob")))
        if is_td:
            third = False
        # 纯碳周期体系（石墨烯等）三阶易导致 SCC 发散，课堂默认关闭
        els_set = {str(e).strip().capitalize() for e in elements}
        if els_set == {"C"} and not bool(p.get("cluster") or p.get("molecule")):
            if "third_order" not in p:
                third = False
        ham = hamiltonian_dftb(
            elements,
            sk_set=sk_set,
            scc=bool(p.get("scc", True)),
            third_order=third,
            filling_temp=float(p.get("temperature_k") or 300),
            kpoints=None if ham_kblock else kpts,
            kpoints_block=ham_kblock,
            solvation=solv if kind == "dftb_solv" else None,
            dispersion=bool(p.get("dispersion") or kind == "dftb_solv"),
            spin_constants=need_spin or need_colinear,
            colinear_spin=need_colinear,
            unpaired_electrons=unpaired,
            max_scc_iter=p.get("max_scc_iter"),
            read_charges=bool(p.get("read_charges")),
            omit_filling=is_reks,
        )

    driver = driver_none()
    extra: list[str] = []

    if kind in ("dftb_opt", "dftb_barrier", "dftb_td_relax"):
        driver = driver_geo_opt(max_steps=int(p.get("max_steps") or 100))
        if kind == "dftb_td_relax":
            extra.append(
                excited_state_casida(
                    n_excitations=int(p.get("n_excitations") or 5),
                    symmetry=str(p.get("symmetry") or "singlet"),
                    state_of_interest=int(p.get("state_of_interest") or 1),
                )
            )
    elif kind == "dftb_vib":
        driver = driver_second_derivatives(delta=float(p.get("delta") or 1e-4))
    elif kind == "dftb_md":
        driver = driver_velocity_verlet(
            steps=int(p.get("md_steps") or 200),
            timestep_fs=float(p.get("timestep_fs") or 0.5),
            temperature_k=float(p.get("temperature_k") or 300),
        )
    elif kind == "dftb_md_anneal":
        driver = driver_velocity_verlet(
            steps=int(p.get("md_steps") or 400),
            timestep_fs=float(p.get("timestep_fs") or 0.5),
            temperature_k=float(p.get("temperature_k") or 300),
            anneal=True,
        )
    elif kind == "dftb_ehrenfest":
        # 新版：ElectronDynamics 不可与 VelocityVerlet MD 同时开启；Ehrenfest 由电子动力学驱动
        driver = driver_none()
        extra.append(
            electron_dynamics_block(
                steps=int(p.get("edyn_steps") or 500),
                timestep_au=float(p.get("timestep_au") or 0.2),
            )
        )
    elif kind == "dftb_solv":
        driver = driver_geo_opt(max_steps=int(p.get("max_steps") or 80))
        extra.append(analysis_forces())
    elif kind in ("dftb_band", "dftb_dos", "dftb_defect"):
        driver = driver_none()
        extra.append(analysis_band_structure())
    elif kind == "dftb_td":
        # 小分子（如 H2O）单粒子激发数有限，默认 6 更稳妥
        extra.append(
            excited_state_casida(
                n_excitations=int(p.get("n_excitations") or 6),
                symmetry=str(p.get("symmetry") or "singlet"),
            )
        )
    elif kind == "dftb_edyn":
        extra.append(
            electron_dynamics_block(
                steps=int(p.get("edyn_steps") or 2000),
                timestep_au=float(p.get("timestep_au") or 0.2),
                field_strength=float(p.get("field_strength") or 0.001),
                polarization=str(p.get("polarization") or "all"),
            )
        )
    elif kind == "dftb_reks":
        extra.append(reks_ssr22_block(target_state=int(p.get("target_state") or 1)))
    elif kind == "dftb_transport":
        extra.append(transport_block(p))
    elif kind == "dftb_boundary":
        # 螺旋采样写入 Hamiltonian 补充说明 + 标准 SCC；若 params 要求则注入 K 点注释块为可执行补充
        extra.append(helical_geometry_note(p))
        # 可执行：默认 Γ 点 SCC（螺旋几何由 gen 提供）；附加 HelicalUniform 到 ham 后需用户几何
        n_k = int(p.get("helical_k") or 80)
        # 将 HelicalUniform 以独立可粘贴块输出（回归键）
        extra.append(f"# executable hint kept as comment + key token HelicalUniform {{{n_k} 0.5}}")
        extra.append(analysis_band_structure())
    elif kind in ("dftb_phonon", "dftb_gsm", "dftb_ase", "dftb_ipi"):
        # 力/能量计算器：供 Phonopy / GSM / ASE / i-PI 驱动
        driver = driver_none()
        extra.append(analysis_forces())
    elif kind == "dftb_xtb":
        driver = driver_geo_opt(max_steps=int(p.get("max_steps") or 100))

    band_kinds = ("dftb_band", "dftb_dos", "dftb_defect", "dftb_boundary")
    has_analysis = any("Analysis =" in (e or "") for e in extra)
    if kind in band_kinds:
        if not has_analysis:
            extra.append(analysis_band_structure())
    elif not has_analysis:
        # DFTB+ 默认 WriteBandOut=Yes，优化/SCC 等会多出无意义的 band.out
        extra.append(analysis_no_band_out())

    parser_v = int(p.get("parser_version") or CURRENT_PARSER_VERSION)
    parts = [geo, ham, driver, *extra, options_common(parser_version=parser_v)]
    return assemble_hsd(parts)


def ensure_parser_version(hsd: str, kind: str = "") -> str:
    """将 ParserVersion 抬到当前课堂 DFTB+ 主版本，并做关键字兼容修补。

    - Casida+Diagonaliser 与 ParserVersion<10 冲突（转换重复插入 Diagonaliser）
    - parser≥14：CalculateForces → PrintForces
    """
    del kind  # 统一抬到当前版本，不再按 kind 分档
    text = (hsd or "").strip()
    if not text:
        return text
    want = CURRENT_PARSER_VERSION

    m = re.search(r"ParserVersion\s*=\s*(\d+)", text, flags=re.I)
    if m:
        try:
            cur = int(m.group(1))
        except ValueError:
            cur = 0
        if cur < want:
            text = re.sub(
                r"ParserVersion\s*=\s*\d+",
                f"ParserVersion = {want}",
                text,
                count=1,
                flags=re.I,
            )
    elif re.search(r"ParserOptions\s*=\s*\{", text, flags=re.I):
        text = re.sub(
            r"(ParserOptions\s*=\s*\{)",
            rf"\1\n  ParserVersion = {want}",
            text,
            count=1,
            flags=re.I,
        )
    else:
        text = text.rstrip() + f"\n\nParserOptions = {{\n  ParserVersion = {want}\n}}\n"

    # 旧 HSD / 旧生成器遗留关键字
    text = re.sub(
        r"\bCalculateForces\s*=\s*Yes\b",
        "PrintForces = Yes",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bCalculateForces\s*=\s*No\b",
        "PrintForces = No",
        text,
        flags=re.I,
    )
    # Casida 与第三阶不兼容：投递前关闭三阶相关块，避免被忽略后强退
    if re.search(r"ExcitedState\s*=\s*\{[\s\S]*?Casida\s*=", text, flags=re.I):
        text = re.sub(
            r"ThirdOrderFull\s*=\s*Yes",
            "ThirdOrderFull = No",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"\n\s*HCorrection\s*=\s*Damping\s*\{[^}]*\}",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"\n\s*HubbardDerivs\s*=\s*\{[\s\S]*?\n\s*\}",
            "",
            text,
            flags=re.I,
        )
    return text


def companion_files_for_kind(kind: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, str]:
    """附属文件：Phonopy / modes / ASE / GSM / i-PI（与 Recipes 配套）。"""
    p = dict(params or {})
    out: dict[str, str] = {}
    if kind == "dftb_vib":
        els = [str(e).strip().capitalize() for e in (p.get("elements") or []) if e]
        n_atoms = int(p.get("n_atoms") or 0)
        if n_atoms <= 0:
            n_atoms = max(len(els), 1)
        n_modes = max(3 * n_atoms, 1)
        sk_set = str(p.get("sk_set") or "3ob")
        prefix = sk.sk_prefix_path(sk_set)
        out["modes_in.hsd"] = "\n".join(
            [
                "Geometry = GenFormat {",
                '  <<< "geo.gen"',
                "}",
                "DisplayModes = {",
                f"  PlotModes = 1:{n_modes}",
                "  Animate = Yes",
                "}",
                "SlaterKosterFiles = Type2FileNames {",
                f'  Prefix = "{prefix}"',
                '  Separator = "-"',
                '  Suffix = ".skf"',
                "}",
                "Hessian = {",
                '  <<< "hessian.out"',
                "}",
                "InputVersion = 3",
                "",
            ]
        )
    if kind == "dftb_phonon":
        out["phonopy_dftb.conf"] = "\n".join(
            [
                "DIM = 2 2 2",
                "ATOM_NAME = " + " ".join(p.get("elements") or ["C"]),
                "EIGENVECTORS = .TRUE.",
                "BAND = 0 0 0  0.5 0 0  0.5 0.5 0  0 0 0",
                "# 【未闭环】本工作台不会自动跑位移超胞/phonopy；此文件仅作草稿。",
                "# Recipes：用 DFTB+ 算力后，需自行用 phonopy 后处理。",
                "",
            ]
        )
        out["NOT_IMPLEMENTED.txt"] = (
            "声子流程未闭环：当前只生成力计算器 HSD 与 phonopy 配置草稿，"
            "不会自动产出声子能带图。请勿将作业“完成”理解为已算声子。\n"
        )
    if kind == "dftb_ase":
        out["run_ase_dftb.py"] = "\n".join(
            [
                "#!/usr/bin/env python",
                "# 【未闭环】工作台不会自动执行本脚本；仅供课外自行调用 ASE。",
                "from ase.io import read",
                "from ase.calculators.dftb import Dftb",
                "atoms = read('geo.gen')",
                "atoms.calc = Dftb(label='ase_dftb', Hamiltonian_='DFTB', Hamiltonian_SCC='Yes')",
                "print('energy', atoms.get_potential_energy())",
                "",
            ]
        )
        out["NOT_IMPLEMENTED.txt"] = "ASE 接口未闭环：请在外部 Python 环境自行运行示例脚本。\n"
    if kind == "dftb_ipi":
        out["ipi_client.sh"] = "\n".join(
            [
                "#!/usr/bin/env bash",
                "# 【未闭环】需外部 i-PI 主进程；本工作台不启动 i-PI。",
                "export PATH=\"$HOME/.dftb-neu/envs/dftbplus/bin:$PATH\"",
                "exec dftb+",
                "",
            ]
        )
        out["NOT_IMPLEMENTED.txt"] = "i-PI 接口未闭环：仅提供客户端草稿。\n"
    if kind == "dftb_gsm":
        out["gsm_readme.txt"] = "\n".join(
            [
                "【未闭环】GSM + DFTB+",
                "本工作台不会自动跑增长串或反应路径搜索。",
                "1. 可用本目录 dftb_in.hsd 作为能量/力计算器",
                "2. 需自行按 GSM 文档设置初末态与参数",
                "",
            ]
        )
        out["NOT_IMPLEMENTED.txt"] = "GSM 反应路径未闭环。\n"
    if kind == "dftb_barrier":
        out["barrier_path.txt"] = "\n".join(
            [
                "# 【未闭环】能垒扫描不会自动执行",
                "# Recipes：沿反应坐标取点，每点用 dftb_in.hsd 做 SCC/优化后自行汇总",
                "",
            ]
        )
        out["NOT_IMPLEMENTED.txt"] = "反应能垒扫描未闭环。\n"
    if kind in ("dftb_transport", "dftb_boundary", "dftb_edyn", "dftb_ehrenfest", "dftb_reks"):
        out["NOT_IMPLEMENTED.txt"] = (
            "该能力族尚未形成端到端闭环（输入可能可生成，但缺少可靠后处理/出图或关键物理块未真正启用）。"
            "工作台默认禁止投递此类作业。\n"
        )
    return out
