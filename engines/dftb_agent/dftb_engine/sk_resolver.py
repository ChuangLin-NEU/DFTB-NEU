"""Slater-Koster 路径与 MaxAngularMomentum（对照 DFTB+ Recipes / 3ob 惯例）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

# 3ob / 常见有机与固体 SK 的角动量上限（Recipes 与参数集文档）
MAX_ANG: dict[str, str] = {
    "H": "s",
    "C": "p",
    "N": "p",
    "O": "p",
    "F": "p",
    "S": "d",
    "P": "d",
    "Cl": "d",
    "Br": "d",
    "I": "d",
    "Na": "p",
    "Mg": "p",
    "K": "p",
    "Ca": "p",
    "Zn": "d",
    "Si": "p",
    "Ge": "p",
    "Al": "p",
    "Ti": "d",
    "Fe": "d",
    "Ni": "d",
    "Cu": "d",
    "Ag": "d",
    "Au": "d",
    "Li": "s",
    "B": "p",
    "Mo": "d",
    "W": "d",
}

# 元素 → 优先参数集（可被 protocol 覆盖）
ELEMENT_SK_PREF: dict[str, str] = {
    "H": "3ob",
    "C": "3ob",
    "N": "3ob",
    "O": "3ob",
    "F": "3ob",
    "S": "3ob",
    "P": "3ob",
    "B": "3ob",
    "Si": "pbc",
    "Ge": "pbc",
    "Ti": "matsci",
    "Fe": "matsci",
    "Mo": "matsci",
    "W": "matsci",
}

# 课堂未承诺可靠覆盖的元素（缺专用 SK 时必须提示，勿 silently 用 3ob）
HARD_ELEMENTS = frozenset({"Mo", "W", "Ti", "Fe", "Ni", "Cu", "Ag", "Au"})


def choose_sk_set(elements: Iterable[str], preferred: str | None = None) -> str:
    els = [str(e).strip().capitalize() for e in elements if e]
    if not els:
        return (preferred or "3ob").strip() or "3ob"
    # 过渡金属/TMDC：只要含困难元素，优先 matsci，避免被 S/C 的 3ob 票数淹没
    if any(e in HARD_ELEMENTS for e in els):
        auto = "matsci"
    else:
        votes: dict[str, int] = {}
        for e in els:
            s = ELEMENT_SK_PREF.get(e, "3ob")
            votes[s] = votes.get(s, 0) + 1
        auto = max(votes, key=votes.get)  # type: ignore[arg-type]
    pref = (preferred or "").strip()
    if not pref:
        return auto
    # 显式 preferred 与元素偏好冲突时（如电子结构 playbook 默认 3ob 但体系是 Si），
    # 以元素投票为准，避免找不到 Si-Si.skf / SCC 异常。
    if pref != auto and any(ELEMENT_SK_PREF.get(e, "3ob") != pref for e in els):
        return auto
    return pref


def max_angular_momentum_block(elements: Iterable[str]) -> str:
    lines = ["  MaxAngularMomentum = {"]
    for e in sorted({str(x).strip().capitalize() for x in elements if x}):
        ang = MAX_ANG.get(e, "p")
        lines.append(f'    {e} = "{ang}"')
    lines.append("  }")
    return "\n".join(lines)


def sk_prefix_path(sk_set: str, remote_sk_root: str = "$HOME/.dftb-neu/share/dftb/sk") -> str:
    """HSD 中 Type2FileNames Prefix。"""
    root = remote_sk_root.rstrip("/")
    return f"{root}/{sk_set}/"


def slater_koster_block(sk_set: str, remote_sk_root: str = "$HOME/.dftb-neu/share/dftb/sk") -> str:
    prefix = sk_prefix_path(sk_set, remote_sk_root)
    # Recipes：SlaterKosterFiles = Type2FileNames { Prefix = ... Separator = "-" Suffix = ".skf" }
    return "\n".join(
        [
            "  SlaterKosterFiles = Type2FileNames {",
            f'    Prefix = "{prefix}"',
            '    Separator = "-"',
            '    Suffix = ".skf"',
            "  }",
        ]
    )


def _local_sk_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        from dftbneu.config import settings

        roots.append(Path(settings.root) / "share" / "dftb" / "sk")
    except Exception:
        pass
    home = Path.home()
    roots.extend(
        [
            home / ".dftb-neu" / "share" / "dftb" / "sk",
            Path("/home") / home.name / ".dftb-neu" / "share" / "dftb" / "sk",
        ]
    )
    # WSL 常见挂载（Windows 宿主调用时）
    try:
        import os

        local = os.environ.get("LOCALAPPDATA") or ""
        if local:
            roots.append(Path(local) / "dftb-neu" / "share" / "dftb" / "sk")
    except Exception:
        pass
    return roots


def sk_coverage_report(
    elements: Iterable[str],
    sk_set: str,
    *,
    sk_root: Optional[Path] = None,
) -> dict[str, Any]:
    """检查元素对在选定 SK 集中是否存在 .skf；实事求是返回缺失列表。"""
    els = sorted({str(e).strip().capitalize() for e in elements if e})
    set_name = (sk_set or "3ob").strip() or "3ob"
    roots = [sk_root] if sk_root else _local_sk_roots()
    found_root: Optional[Path] = None
    for r in roots:
        if r and (r / set_name).is_dir():
            found_root = r / set_name
            break
    hard = [e for e in els if e in HARD_ELEMENTS]
    if found_root is None:
        # 本机未部署时不硬失败（作业在 WSL 内跑）；但对困难元素给出警告
        return {
            "ok": True,
            "sk_set": set_name,
            "root": "",
            "missing_pairs": [],
            "hard_elements": hard,
            "checked": False,
            "message": (
                (
                    f"体系含 {', '.join(hard)}，已优先选用「{set_name}」。"
                    "过渡金属/TMDC 参数需本机已安装对应 .skf；缺失时作业会失败。"
                )
                if hard
                else ""
            ),
        }
    missing: list[str] = []
    for i, a in enumerate(els):
        for b in els[i:]:
            if not (found_root / f"{a}-{b}.skf").is_file() and not (
                found_root / f"{b}-{a}.skf"
            ).is_file():
                missing.append(f"{a}-{b}")
    ok = not missing
    msg = ""
    if missing:
        msg = (
            f"SK 集「{set_name}」缺少参数对：{', '.join(missing)}。"
            "该体系暂不可靠计算，请更换材料或安装对应 Slater–Koster 文件。"
        )
    elif hard:
        msg = (
            f"体系含 {', '.join(hard)}，已优先选用「{set_name}」。"
            "过渡金属 DFTB 参数质量差异大，结果仅供课堂定性参考。"
        )
    return {
        "ok": ok,
        "sk_set": set_name,
        "root": str(found_root),
        "missing_pairs": missing,
        "hard_elements": hard,
        "checked": True,
        "message": msg,
    }
