"""DFTB 方法段与课题成稿（无 VASP 依赖）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .. import db
from . import deepseek


DFTB_REFS = [
    {
        "cite_key": "Hourahine2020",
        "formatted": (
            "B. Hourahine et al., DFTB+, a software package for efficient approximate density "
            "functional theory based atomistic simulations, J. Chem. Phys. 152, 124101 (2020). "
            "https://doi.org/10.1063/1.5143190"
        ),
    },
    {
        "cite_key": "Elstner1998",
        "formatted": (
            "M. Elstner et al., Self-consistent-charge density-functional tight-binding method "
            "for simulations of biological molecules, Phys. Rev. B 58, 7260 (1998)."
        ),
    },
]


def methods_paragraph(*, sk_set: str = "3ob", family: str = "electronic", title: str = "") -> str:
    _ = title
    return (
        f"Atomistic calculations were carried out with DFTB+ "
        f"(Hourahine et al., J. Chem. Phys. 152, 124101, 2020) using the density-functional "
        f"tight-binding Hamiltonian. Slater–Koster parameters from the `{sk_set}` set "
        f"(dftb.org / dftbparams) were employed. The workflow family `{family}` follows the "
        f"official DFTB+ Recipes. Geometry and electronic options were specified in "
        f"`dftb_in.hsd` (HSD). Executables were isolated under the user `~/.dftb-neu` prefix. "
        f"Where applicable, self-consistent charge (SCC) DFTB and/or third-order corrections "
        f"consistent with the chosen SK set were enabled. Task-specific drivers were selected "
        f"according to the Recipes chapter for `{family}`."
    )


def build_manuscript(project_id: str, *, use_llm: bool = True) -> dict[str, Any]:
    proj = db.get_project(project_id)
    if not proj:
        raise ValueError("课题不存在")
    protocol = proj.get("protocol") or {}
    idea = proj.get("idea") or {}
    sk = protocol.get("sk_set") or "3ob"
    family = protocol.get("dftb_family") or protocol.get("family") or "electronic"
    analysis = protocol.get("analysis") or {}
    title = proj.get("title") or idea.get("title") or "DFTB+ classroom study"
    methods = methods_paragraph(sk_set=sk, family=family, title=title)
    results = _results_summary(analysis, protocol)
    captions = list(protocol.get("figure_captions") or [])
    ms = {
        "title": title,
        "abstract": "",
        "introduction": "",
        "methods": methods,
        "results": results,
        "discussion": "",
        "conclusion": "",
        "figure_captions": captions,
        "references": [r["formatted"] for r in DFTB_REFS],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if use_llm:
        try:
            prompt = (
                "你是计算材料学助教。根据下列 DFTB+ 课堂计算结果，用中文撰写简短摘要（≤120字）、"
                "结果段（≤200字）与一句结论。不要营销话术。输出 JSON："
                '{"abstract":"...","results":"...","conclusion":"..."}\n\n'
                f"标题：{title}\n族：{family}\nSK：{sk}\n分析：{analysis}\n方法段：{methods}"
            )
            raw = deepseek.chat(
                [
                    {"role": "system", "content": "只输出 JSON，不要 Markdown。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            import json
            import re

            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                data = json.loads(m.group(0))
                ms["abstract"] = str(data.get("abstract") or "")
                if data.get("results"):
                    ms["results"] = str(data["results"])
                ms["conclusion"] = str(data.get("conclusion") or "")
        except Exception:
            pass
    db.update_project(project_id, manuscript=ms, phase="manuscript")
    db.append_activity(project_id, "已生成方法段与结果摘要", "manuscript")
    # 导出
    md = to_markdown(ms)
    out = db.project_dir(project_id) / "artifacts" / "manuscript.md"
    out.write_text(md, encoding="utf-8")
    html = to_html(ms)
    (db.project_dir(project_id) / "artifacts" / "manuscript.html").write_text(html, encoding="utf-8")
    return ms


def _results_summary(analysis: dict, protocol: dict) -> str:
    parts = []
    detailed = analysis.get("detailed") or {}
    energy = analysis.get("total_energy")
    if energy is None:
        energy = detailed.get("total_energy_eV")
    fermi = analysis.get("fermi_energy")
    if fermi is None:
        fermi = detailed.get("fermi_eV")
    converged = analysis.get("converged")
    if converged is None:
        converged = bool(detailed.get("geo_converged") or detailed.get("scc_converged"))
    if converged:
        parts.append("计算已收敛。")
    if energy is not None:
        parts.append(f"总能量约为 {float(energy):.6f} eV。")
    if fermi is not None:
        parts.append(f"Fermi 能级约为 {float(fermi):.6f} eV。")
    if analysis.get("n_kpoints"):
        parts.append(f"能带采样 k 点数：{analysis.get('n_kpoints')}。")
    if analysis.get("n_excitations"):
        parts.append(f"激发态数目：{analysis.get('n_excitations')}。")
    if analysis.get("summary"):
        parts.append(str(analysis["summary"]))
    if protocol.get("job_id"):
        parts.append(f"作业编号：{protocol['job_id']}。")
    if protocol.get("plot_error"):
        parts.append(f"出图告警：{protocol.get('plot_error')}。")
    return " ".join(parts) or "计算结果见课题资产与 detailed.out。"


def to_markdown(ms: dict) -> str:
    lines = [
        f"# {ms.get('title') or 'DFTB+ 文稿'}",
        "",
        "## Abstract",
        ms.get("abstract") or "",
        "",
        "## Methods",
        ms.get("methods") or "",
        "",
        "## Results",
        ms.get("results") or "",
        "",
        "## Conclusion",
        ms.get("conclusion") or "",
        "",
        "## Figure captions",
    ]
    for i, c in enumerate(ms.get("figure_captions") or [], 1):
        lines.append(f"{i}. {c}")
    lines += ["", "## References"]
    for i, r in enumerate(ms.get("references") or [], 1):
        lines.append(f"[{i}] {r}")
    return "\n".join(lines)


def to_html(ms: dict) -> str:
    body = to_markdown(ms).replace("\n", "<br>\n")
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{ms.get('title')}</title></head><body>{body}</body></html>"
