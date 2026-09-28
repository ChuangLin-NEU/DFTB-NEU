"""按 kind 生成 DFTB+ 输入文件集合。"""

from __future__ import annotations

from typing import Any, Optional

from . import band_paths
from . import geometry as geo
from . import hsd_builder as hsd
from . import sk_resolver as sk


KIND_FAMILY = {
    "dftb_scc": "electronic",
    "dftb_opt": "geometry_vib",
    "dftb_band": "electronic",
    "dftb_dos": "electronic",
    "dftb_vib": "geometry_vib",
    "dftb_md": "md",
    "dftb_md_anneal": "md",
    "dftb_solv": "solvation",
    "dftb_defect": "defect_2d",
    "dftb_td": "linresp",
    "dftb_td_relax": "linresp",
    "dftb_edyn": "electronic_dynamics",
    "dftb_ehrenfest": "electronic_dynamics",
    "dftb_phonon": "properties",
    "dftb_barrier": "properties",
    "dftb_reks": "reks",
    "dftb_transport": "transport",
    "dftb_boundary": "boundary",
    "dftb_gsm": "gsm",
    "dftb_xtb": "xtb_in_dftb",
    "dftb_ase": "interfaces",
    "dftb_ipi": "interfaces",
}


def prefer_env_for_kind(kind: str, params: Optional[dict] = None) -> str:
    """返回 nompi | mpi。激发态优先 nompi（Recipes）。"""
    p = params or {}
    if p.get("force_mpi"):
        return "mpi"
    if p.get("force_nompi"):
        return "nompi"
    excited = {
        "dftb_td",
        "dftb_td_relax",
        "dftb_edyn",
        "dftb_ehrenfest",
        "dftb_reks",
    }
    if kind in excited:
        return "nompi"
    if kind in ("dftb_md", "dftb_md_anneal", "dftb_phonon", "dftb_defect") and p.get("large_cell"):
        return "mpi"
    return "nompi"


def build_inputs_for_kind(
    kind: str,
    *,
    poscar: str = "",
    gen: str = "",
    elements: Optional[list[str]] = None,
    sk_set: str = "",
    params: Optional[dict[str, Any]] = None,
    use_recipes_water: bool = False,
) -> dict[str, Any]:
    p = dict(params or {})
    kind = (kind or "dftb_scc").strip()
    if use_recipes_water or (not poscar and not gen):
        gen_text = geo.water_gen_from_recipes()
        els = geo.elements_from_gen(gen_text)
        cluster = True
    elif poscar:
        # POSCAR 优先于残留 GEN，避免上一分子任务的 geo 与本任务 HSD 元素不一致
        cluster = bool(p.get("cluster") or p.get("molecule"))
        gen_text = geo.poscar_to_gen(poscar, cluster=cluster)
        els = elements or geo.elements_from_poscar(poscar)
        if poscar and not cluster:
            p.setdefault("periodic", True)
    else:
        gen_text = gen
        els = elements or geo.elements_from_gen(gen_text)
        cluster = bool(p.get("cluster") or p.get("molecule")) or geo.gen_is_cluster(gen_text)
        if not cluster:
            p.setdefault("periodic", True)

    # 分子/cluster 不得附带周期 k 网格（否则新版解析器忽略 KPoints 并报错退出）
    p["cluster"] = cluster
    if cluster:
        p["periodic"] = False
        p.pop("ham_kpoints_block", None)
        p.pop("kpoints", None)
    else:
        p.setdefault("periodic", True)

    sk_name = sk_set or sk.choose_sk_set(els, p.get("sk_set"))
    p["sk_set"] = sk_name
    sk_report = sk.sk_coverage_report(els, sk_name)
    p["_sk_coverage"] = sk_report
    prompt = str(p.get("prompt") or "")
    want_dos = bool(p.get("want_dos")) or kind == "dftb_dos"
    prompt_l = prompt.lower()
    gap_in_prompt = any(k in prompt for k in ("能带", "带隙", "能隙", "禁带")) or any(
        k in prompt_l for k in ("band", "bandgap", "band-gap", "band gap")
    )
    want_band = kind in ("dftb_band", "dftb_defect") or (want_dos and gap_in_prompt)
    # 缺陷超胞：SCC/优化用适中网格（超胞已放大，不必 12×12）
    if kind == "dftb_defect" and not cluster:
        p.setdefault("dimensionality", "2d")
        p.setdefault("kpoints", "6 6 1")
    # 周期结构默认补 k 点；纳米带用准一维网格
    if not cluster:
        pl = prompt.lower()
        if "纳米带" in prompt or "nanoribbon" in pl or "nano-ribbon" in pl:
            p.setdefault("dimensionality", "1d")
            p.setdefault("kpoints", "4 1 1")
        elif any(k in prompt for k in ("石墨烯", "石墨炔")) or "graphene" in pl:
            p.setdefault("dimensionality", "2d")
            if kind != "dftb_defect":
                p.setdefault("kpoints", "12 12 1")
    path = []
    path_name = ""
    mode = ""
    if kind in ("dftb_band", "dftb_dos", "dftb_defect") and not cluster:
        path, path_name = band_paths.infer_path(
            elements=els, poscar=poscar, prompt=prompt, params=p
        )
        if path_name == "graphene":
            p["dimensionality"] = "2d"
            if kind != "dftb_defect":
                p.setdefault("kpoints", "12 12 1")
        # 纯 DOS：均匀网格；能带（可附 DOS）：主输入用 Klines，DOS 另写 dftb_in_dos.hsd
        if kind == "dftb_dos" and not want_band:
            nz = 1 if p.get("dimensionality") == "2d" else 12
            p["ham_kpoints_block"] = band_paths.dos_mesh_hsd_block(
                nx=12, ny=12, nz=nz, indent="  "
            )
            mode = "dos_mesh"
        else:
            p["ham_kpoints_block"] = band_paths.klines_hsd_block(path, indent="  ")
            mode = "klines+dos_mesh" if want_dos else "klines"
        p["_band_meta"] = {
            "path": path,
            "path_name": path_name,
            "want_dos": want_dos or kind == "dftb_dos",
            "mode": mode,
        }

    hsd_text = hsd.build_hsd_for_kind(
        kind,
        els,
        sk_set=sk_name,
        params=p,
        geometry_mode="gen",
    )
    files = {
        "dftb_in.hsd": hsd_text,
        "geo.gen": gen_text,
    }
    if poscar and not use_recipes_water:
        files["POSCAR"] = poscar

    # 能带附带 DOS：第二阶段后另跑均匀网格，避免路径 DOS 冒充态密度
    if (
        kind in ("dftb_band", "dftb_defect")
        and want_dos
        and not cluster
        and path
    ):
        p_dos = dict(p)
        nz = 1 if p_dos.get("dimensionality") == "2d" else 12
        # 超胞缺陷：网格可略稀
        nx = 8 if kind == "dftb_defect" else 12
        ny = nx
        p_dos["ham_kpoints_block"] = band_paths.dos_mesh_hsd_block(
            nx=nx, ny=ny, nz=nz, indent="  "
        )
        files["dftb_in_dos.hsd"] = hsd.build_hsd_for_kind(
            "dftb_dos",
            els,
            sk_set=sk_name,
            params=p_dos,
            geometry_mode="gen",
        )
        if p.get("_band_meta"):
            p["_band_meta"]["mode"] = "klines+dos_mesh"
            p["_band_meta"]["want_dos"] = True
            p["_band_meta"]["dos_note"] = "DOS 来自均匀 k 网格（非能带路径近似）"

    # 预优化：主 HSD 本身已是优化的 kind 不再套一层
    pre_relax_kinds = (
        "dftb_band",
        "dftb_dos",
        "dftb_defect",
        "dftb_vib",
        "dftb_td",
        "dftb_md",
        "dftb_md_anneal",
        "dftb_edyn",
        "dftb_ehrenfest",
        "dftb_phonon",
        "dftb_transport",
        "dftb_reks",
    )
    already_opt = ("dftb_opt", "dftb_xtb", "dftb_solv", "dftb_td_relax", "dftb_barrier")
    want_pre = bool(p.get("pre_relax"))
    if kind in pre_relax_kinds and "pre_relax" not in p:
        want_pre = True
    if kind in ("dftb_band", "dftb_dos", "dftb_defect") and cluster and "pre_relax" not in p:
        want_pre = False
    if kind in already_opt:
        want_pre = False
    if want_pre and kind in pre_relax_kinds:
        p_opt = dict(p)
        p_opt.pop("ham_kpoints_block", None)  # 优化用均匀 k 网格，不用 Klines
        if kind in ("dftb_vib", "dftb_td"):
            p_opt.setdefault("max_steps", int(p.get("max_steps") or 50))
        else:
            p_opt.setdefault("max_steps", int(p.get("max_steps") or 80))
        files["dftb_in_opt.hsd"] = hsd.build_hsd_for_kind(
            "dftb_opt",
            els,
            sk_set=sk_name,
            params=p_opt,
            geometry_mode="gen",
        )
        p["_pre_relax"] = True

    meta = p.get("_band_meta")
    if meta:
        formula = str(p.get("formula") or "").strip()
        if not formula:
            formula = geo.formula_from_gen(gen_text)
        if not formula and els:
            formula = "".join(els)
        files["band_meta.json"] = band_paths.band_meta_json(
            meta["path"],
            path_name=meta["path_name"],
            want_dos=bool(meta.get("want_dos")),
            mode=str(meta.get("mode") or "klines"),
            formula=formula,
            title_hint=str(p.get("title_hint") or p.get("prompt") or "")[:80],
            dos_note=str(meta.get("dos_note") or ""),
        )
    from .hsd_builder import companion_files_for_kind

    companions = companion_files_for_kind(
        kind,
        params={
            **p,
            "elements": els,
            "sk_set": sk_name,
            "n_atoms": geo.natoms_from_gen(gen_text) or len(els),
        },
    )
    files.update(companions)
    return {
        "kind": kind,
        "family": KIND_FAMILY.get(kind, "electronic"),
        "elements": els,
        "sk_set": sk_name,
        "env": prefer_env_for_kind(kind, p),
        "files": files,
        "params": p,
        "sk_coverage": sk_report,
    }
