"""基础测试：能力矩阵、HSD 预览、设置存储。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "engines" / "dftb_agent"))


def test_matrix_loads():
    from dftb_engine.capability import load_matrix, match_family_from_text

    m = load_matrix()
    assert m.get("families")
    assert match_family_from_text("用 DFTB+ 对水分子做几何优化") == "geometry_vib"
    assert match_family_from_text("对该结构进行几何优化并计算其带隙值") == "electronic"
    assert match_family_from_text("几何优化并计算振动频率") == "geometry_vib"


def test_preview_hsd():
    from dftbneu.services.pipeline import preview_hsd

    prev = preview_hsd("用 DFTB+ 对水分子做几何优化")
    assert "dftb_in.hsd" in prev["files"]
    assert "Hamiltonian" in prev["hsd_preview"]
    assert ".dftb-neu" in prev["hsd_preview"] or "SlaterKoster" in prev["hsd_preview"]


def test_methods_paragraph():
    from dftbneu.services.manuscript import methods_paragraph

    t = methods_paragraph(sk_set="3ob", family="geometry_vib")
    assert "DFTB+" in t
    assert "~/.dftb-neu" in t


def test_protect_key_roundtrip(tmp_path, monkeypatch):
    from dftbneu import config
    from dftbneu.services import secrets

    monkeypatch.setattr(config.settings, "data_dir", str(tmp_path))
    secrets.save_llm_settings(api_key="sk-test-key-12345678", base_url="https://api.deepseek.com", model="deepseek-chat")
    pub = secrets.public_settings()
    assert pub["api_key_set"] is True
    assert secrets.reveal_api_key() == "sk-test-key-12345678"


def test_teaching_examples():
    from dftbneu.services.pipeline import teaching_examples

    ex = teaching_examples()
    assert len(ex) >= 4
    assert any(e["id"] == "h2o_opt" for e in ex)


def test_user_hsd_geometry_helpers():
    from dftbneu.services.pipeline import (
        ensure_hsd_geometry,
        hsd_geometry_mode,
        infer_kind_from_hsd,
    )

    inline = "Geometry = GenFormat {\n  3 C\n  O H\n}\nHamiltonian = DFTB {}\n"
    include = 'Geometry = GenFormat {\n  <<< "geo.gen"\n}\nHamiltonian = DFTB {}\n'
    missing = "Hamiltonian = DFTB {\n  SCC = Yes\n}\n"
    assert hsd_geometry_mode(inline) == "inline"
    assert hsd_geometry_mode(include) == "include"
    assert hsd_geometry_mode(missing) == "missing"
    patched = ensure_hsd_geometry(missing, gen="3 C\n O H\n")
    assert "<<< \"geo.gen\"" in patched
    assert infer_kind_from_hsd("Driver = GeometryOptimization {}\n") == "dftb_opt"
    assert infer_kind_from_hsd("Hamiltonian = DFTB { Klines = {\n}\n}\n") == "dftb_band"


def test_user_hsd_chat_without_nl():
    import asyncio

    from dftbneu.services.pipeline import handle_chat

    inline = (
        "Geometry = GenFormat {\n"
        "  3 C\n"
        "}\n"
        "Hamiltonian = DFTB {\n"
        "  SCC = Yes\n"
        "}\n"
    )
    data = asyncio.run(
        handle_chat("", hsd=inline, user_hsd=True, confirm_submit=False)
    )
    assert data.get("ok") is True
    assert data["preview"]["hsd_preview"]
    assert data["preview"].get("allow_submit") is True

    include = 'Geometry = GenFormat {\n  <<< "geo.gen"\n}\nHamiltonian = DFTB {}\n'
    need = asyncio.run(
        handle_chat("", hsd=include, user_hsd=True, confirm_submit=False)
    )
    assert need.get("ok") is False
    assert "结构" in (need.get("reply") or "")

    with_gen = asyncio.run(
        handle_chat(
            "",
            hsd=include,
            gen="3 C\n O H\n    1 1 0 0 0\n    2 2 0.7 0 0\n    3 2 -0.7 0 0\n",
            user_hsd=True,
            confirm_submit=False,
        )
    )
    assert with_gen.get("ok") is True


def test_llm_resolve_without_crash():
    from dftbneu.services import llm

    key, base, model, label = llm.resolve_endpoint()
    assert base
    assert model
    assert label in {"deepseek", "qwen"}


def test_public_settings_has_providers():
    from dftbneu.services.secrets import public_settings

    s = public_settings()
    assert "llm_provider" in s
    assert "mp_api_key_set" in s
    assert "env_bootstrap" in s


def test_opt_then_gap_compound_intent():
    from dftb_engine.capability import resolve_nl_intent
    from dftbneu.services.pipeline import (
        _hsd_should_drop_on_kind_upgrade,
        _refine_kind,
        preview_hsd,
    )

    cases = [
        ("对该结构进行几何优化并计算其带隙值", "dftb_band", ["opt", "band"], True),
        ("几何优化并计算能带", "dftb_band", ["opt", "band"], True),
        ("先优化再算带隙", "dftb_band", ["opt", "band"], True),
        ("optimize the geometry and calculate the band gap", "dftb_band", ["opt", "band"], True),
        ("几何优化并计算能带和态密度", "dftb_band", ["opt", "band", "dos"], True),
        ("能带和 DOS", "dftb_band", ["opt", "band", "dos"], True),
        ("对该结构进行几何优化并计算态密度", "dftb_dos", ["opt", "dos"], True),
        ("几何优化并计算振动频率", "dftb_vib", ["opt", "vib"], True),
        ("先短优化再算吸收光谱", "dftb_td", ["opt", "td"], True),
        ("先优化再跑分子动力学", "dftb_md", ["opt", "md"], True),
        ("用 DFTB+ 对水分子做几何优化", "dftb_opt", ["opt"], False),
        ("用 DFTB+ 算水分子单点 SCC 能量", "dftb_scc", ["scc"], False),
        ("不优化直接计算能带", "dftb_band", ["band"], False),
        ("石墨烯空位并计算带隙", "dftb_defect", ["opt", "defect"], True),
        ("DFTB+ 算石墨烯缺陷电子结构", "dftb_defect", ["opt", "defect"], True),
    ]
    for prompt, kind, stages, pre in cases:
        got = resolve_nl_intent(prompt)
        assert got.get("kind") == kind, (prompt, got)
        assert got.get("stages") == stages, (prompt, got.get("stages"), stages)
        assert bool(got.get("params", {}).get("pre_relax")) is pre, (prompt, got.get("params"))

    kind, params = _refine_kind("对该结构进行几何优化并计算其带隙值", "geometry_vib", "dftb_opt")
    assert kind == "dftb_band"
    assert params.get("pre_relax") is True

    poscar = (ROOT / "templates" / "courses" / "structures" / "si_diamond.poscar").read_text(
        encoding="utf-8"
    )
    prev = preview_hsd("对该结构进行几何优化并计算其带隙值", poscar=poscar)
    assert prev.get("ok") is True
    assert prev["kind"] == "dftb_band"
    assert prev["family"] == "electronic"
    assert prev.get("stages") == ["opt", "band"]
    files = prev["files"] or {}
    assert "dftb_in_opt.hsd" in files
    assert "GeometryOptimization" in files["dftb_in_opt.hsd"]
    assert "Klines" in files.get("dftb_in.hsd", "")
    assert _hsd_should_drop_on_kind_upgrade(
        "Driver = GeometryOptimization {}\nHamiltonian = DFTB {}\n", "dftb_band"
    )
    assert _hsd_should_drop_on_kind_upgrade(
        "Driver = GeometryOptimization {}\nHamiltonian = DFTB {}\n", "dftb_vib"
    )
    assert not _hsd_should_drop_on_kind_upgrade(
        "Hamiltonian = DFTB { Klines = {\n}\n}\n", "dftb_band"
    )

    locked = preview_hsd(
        "对该结构进行几何优化并计算其带隙值",
        poscar=poscar,
        kind_hint="dftb_opt",
        family_hint="geometry_vib",
    )
    assert locked["kind"] == "dftb_band"
    assert "dftb_in_opt.hsd" in (locked.get("files") or {})
