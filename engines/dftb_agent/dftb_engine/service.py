"""DftbEngine：本机 / WSL 课堂版入口。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from . import analysis as dftb_analysis
from . import plot_bands_dos
from .hsd_builder import ensure_parser_version, ensure_write_band_out
from .inputs import build_inputs_for_kind
from .local_runner import LocalDftbRunner


class DftbEngine:
    def __init__(self, wsl_distro: str = ""):
        self.runner = LocalDftbRunner(wsl_distro=wsl_distro)

    def test(self) -> dict[str, Any]:
        return self.runner.test()

    def submit_job(
        self,
        *,
        kind: str,
        poscar: str = "",
        gen: str = "",
        job_id: str | None = None,
        np: int = 1,
        params: dict | None = None,
        use_recipes_water: bool = False,
        sk_set: str = "",
        hsd_override: str = "",
        user_hsd: bool = False,
    ) -> dict[str, Any]:
        job_id = job_id or f"edu_{uuid.uuid4().hex[:10]}"
        built = build_inputs_for_kind(
            kind,
            poscar=poscar,
            gen=gen,
            sk_set=sk_set,
            params=params,
            use_recipes_water=use_recipes_water,
        )
        # 自写输入：只跑用户的 dftb_in.hsd，不要再套预优化 / DOS 附属阶段
        if user_hsd:
            for extra in ("dftb_in_opt.hsd", "dftb_in_dos.hsd", "modes_in.hsd"):
                built["files"].pop(extra, None)
        # SK 路径改为课堂根；前端编辑只覆盖电子结构主输入 dftb_in.hsd（勿覆盖预优化 dftb_in_opt.hsd）
        override = (hsd_override or "").strip()
        for name, content in list(built["files"].items()):
            if name.endswith(".hsd"):
                text = override if (override and name == "dftb_in.hsd") else content
                text = ensure_write_band_out(text, kind if name == "dftb_in.hsd" else "dftb_opt")
                text = ensure_parser_version(text, kind if name == "dftb_in.hsd" else "dftb_opt")
                built["files"][name] = text.replace(
                    "$HOME/.cmats/share/dftb/sk",
                    "$HOME/.dftb-neu/share/dftb/sk",
                )
        result = self.runner.submit_job(built["files"], job_id=job_id, np=np)
        result["kind"] = kind
        result["family"] = built.get("family")
        result["elements"] = built.get("elements")
        result["sk_set"] = built.get("sk_set")
        return result

    def get_status(self, job_id: str) -> dict:
        return self.runner.get_status(job_id)

    def cancel_job(self, job_id: str) -> dict:
        return self.runner.cancel_job(job_id)

    def fetch_artifacts(self, job_id: str, names: Optional[list[str]] = None) -> dict[str, str]:
        return self.runner.fetch_artifacts(job_id, names)

    def analyze(self, artifacts: dict[str, str]) -> dict[str, Any]:
        return dftb_analysis.analyze_artifacts(artifacts)

    def plot(self, artifacts: dict[str, str], out_dir: Path, *, kind: str = "") -> list[Path]:
        return plot_bands_dos.plot_from_artifacts(artifacts, out_dir, kind=kind)
