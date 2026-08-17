from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from dftb_engine import kind_profile as kp
from dftb_engine.service import DftbEngine

from .. import db
from ..config import load_user_config, settings

router = APIRouter(tags=["assets"])

_FIG_SKIP = {"dftb_total_energy.png", "dftb_performance.png"}

_INPUT_NAMES = {
    "dftb_in.hsd",
    "geo.gen",
    "POSCAR",
    "poscar",
    "band_meta.json",
    "run.sh",
}
# 仅保留 DFTB+ 产生的有意义输出（不含调度元数据 / runner 包装日志）
_OUTPUT_NAMES = {
    "detailed.out",
    "band.out",
    "geo_end.gen",
    "EXC.DAT",
    "dftb.log",
}
# 仅能带/DOS 类任务展示的输出
_BAND_ONLY_OUTPUTS = {"band.out", "band.dat", "band_meta.json"}


def _kind_for(name: str) -> str:
    if name in _INPUT_NAMES:
        return "input"
    if name in _OUTPUT_NAMES:
        return "output"
    low = name.lower()
    if low.endswith((".hsd", ".gen", ".poscar", ".vasp")) or low in ("poscar",):
        return "input"
    return "other"


@router.get("/projects/{project_id}/figures")
def list_figures(project_id: str):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(404, "课题不存在")
    fig_dir = db.project_dir(project_id) / "figures"
    files = []
    if fig_dir.is_dir():
        for f in sorted(fig_dir.iterdir()):
            if f.suffix.lower() == ".png" and f.name.lower() not in _FIG_SKIP:
                files.append(
                    {
                        "name": f.name,
                        "url": f"/api/projects/{project_id}/figures/{f.name}",
                        "download_url": f"/api/projects/{project_id}/figures/{f.name}?download=1",
                    }
                )
    return {"figures": files, "protocol_figures": (p.get("protocol") or {}).get("figures") or []}


@router.get("/projects/{project_id}/figures/{name}")
def get_figure(project_id: str, name: str, download: int = Query(0)):
    if "/" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    path = db.project_dir(project_id) / "figures" / name
    if not path.is_file():
        raise HTTPException(404, "图不存在")
    if download:
        return FileResponse(path, filename=name, media_type="image/png")
    return FileResponse(path)


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(project_id: str):
    if not db.get_project(project_id):
        raise HTTPException(404, "课题不存在")
    art = db.project_dir(project_id) / "artifacts"
    names = []
    if art.is_dir():
        names = sorted(f.name for f in art.iterdir() if f.is_file())
    return {"artifacts": names}


@router.get("/projects/{project_id}/artifacts/{name}")
def get_artifact(project_id: str, name: str):
    if "/" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    path = db.project_dir(project_id) / "artifacts" / name
    if not path.is_file():
        raise HTTPException(404, "资产不存在")
    return FileResponse(path)


def _project_kind(project_id: str = "", proj: dict | None = None) -> str:
    p = proj if proj is not None else (db.get_project(project_id) or {})
    return str((p.get("protocol") or {}).get("kind") or "")


def _io_name_allowed(name: str, kind: str = "") -> bool:
    """按任务类型过滤 IO 列表：优化等不展示 band.out。"""
    if name in _BAND_ONLY_OUTPUTS and not kp.shows_kpath(kind) and kind not in kp.BAND_KINDS:
        # band_meta 作输入时也仅能带任务保留
        return False
    return True


def _ensure_local_artifacts(project_id: str) -> Path:
    """若本机 artifacts 不足，从 WSL 作业目录补拉文本文件。"""
    art = db.project_dir(project_id) / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    proj = db.get_project(project_id) or {}
    job_id = (proj.get("job") or {}).get("job_id") or (proj.get("protocol") or {}).get("job_id") or ""
    existing = {p.name for p in art.iterdir() if p.is_file()} if art.is_dir() else set()
    # 补写方案中的结构 / HSD（未落盘时）
    protocol = proj.get("protocol") or {}
    structure = proj.get("structure") or {}
    kind = _project_kind(proj=proj)
    if "dftb_in.hsd" not in existing:
        hsd = (protocol.get("hsd_preview") or protocol.get("hsd_default") or "").strip()
        if hsd:
            (art / "dftb_in.hsd").write_text(hsd, encoding="utf-8")
            existing.add("dftb_in.hsd")
    if "POSCAR" not in existing and structure.get("poscar"):
        (art / "POSCAR").write_text(str(structure["poscar"]), encoding="utf-8")
        existing.add("POSCAR")
    if "geo.gen" not in existing and structure.get("gen"):
        (art / "geo.gen").write_text(str(structure["gen"]), encoding="utf-8")
        existing.add("geo.gen")
    need = [
        "dftb_in.hsd",
        "geo.gen",
        "POSCAR",
        "detailed.out",
        "dftb.log",
        "runner.log",
        "geo_end.gen",
        "EXC.DAT",
        "status",
        "exit_code",
    ]
    if kind in kp.BAND_KINDS or kp.shows_kpath(kind):
        need.extend(["band_meta.json", "band.out"])
    if kind in kp.MD_KINDS or kp.shows_md_metrics(kind):
        need.append("md.out")
    if kind in kp.VIB_KINDS or kp.shows_vibrations(kind):
        need.extend(["modes.log", "vibrations.tag", "hessian.out"])
    missing = [n for n in need if n not in existing]
    if job_id and missing:
        try:
            cfg = load_user_config()
            eng = DftbEngine(wsl_distro=str(cfg.get("wsl_distro") or settings.wsl_distro or ""))
            fetched = eng.fetch_artifacts(job_id, missing)
            for name, content in fetched.items():
                if content is None:
                    continue
                (art / name).write_text(content, encoding="utf-8", errors="replace")
        except Exception:
            pass
    return art


@router.get("/projects/{project_id}/io-files")
def list_io_files(project_id: str, sync: int = Query(1)):
    """列出本次计算的输入 / 输出文本文件，供逐个查看。"""
    proj = db.get_project(project_id)
    if not proj:
        raise HTTPException(404, "课题不存在")
    job_kind = _project_kind(proj=proj)
    art = _ensure_local_artifacts(project_id) if sync else db.project_dir(project_id) / "artifacts"
    files = []
    if art.is_dir():
        for f in sorted(art.iterdir(), key=lambda p: (_kind_for(p.name), p.name.lower())):
            if not f.is_file():
                continue
            # 跳过体积很大的二进制
            if f.suffix.lower() in {".bin", ".tag", ".npz"}:
                continue
            if not _io_name_allowed(f.name, job_kind):
                continue
            try:
                size = f.stat().st_size
            except OSError:
                size = 0
            if size > 2_000_000:
                continue
            kind = _kind_for(f.name)
            if kind == "other":
                continue
            if f.name not in _INPUT_NAMES and f.name not in _OUTPUT_NAMES:
                # 额外结构文件可作输入；其它杂项不列出
                if kind != "input":
                    continue
            files.append(
                {
                    "name": f.name,
                    "kind": kind,
                    "kind_zh": {"input": "输入文件", "output": "DFTB+ 输出", "other": "其它"}.get(
                        kind, "其它"
                    ),
                    "size": size,
                    "url": f"/api/projects/{project_id}/io-files/{f.name}",
                    "download_url": f"/api/projects/{project_id}/io-files/{f.name}?download=1",
                }
            )
    # 输入优先、再输出
    order = {"input": 0, "output": 1, "other": 2}
    files.sort(key=lambda x: (order.get(x["kind"], 9), x["name"].lower()))
    return {"files": files}


@router.get("/projects/{project_id}/io-files/{name}")
def get_io_file(project_id: str, name: str, download: int = Query(0)):
    if "/" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    if not db.get_project(project_id):
        raise HTTPException(404, "课题不存在")
    art = _ensure_local_artifacts(project_id)
    path = art / name
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    if download:
        return FileResponse(path, filename=name, media_type="text/plain; charset=utf-8")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(500, f"读取失败：{e}") from e
    # 预览截断，避免超大日志拖垮前端
    truncated = len(text) > 400_000
    if truncated:
        text = text[:400_000] + "\n\n…（内容过长，已截断；可点「下载」查看全文）"
    return {
        "name": name,
        "kind": _kind_for(name),
        "kind_zh": {"input": "输入文件", "output": "DFTB+ 输出", "other": "其它"}.get(
            _kind_for(name), "其它"
        ),
        "text": text,
        "truncated": truncated,
        "download_url": f"/api/projects/{project_id}/io-files/{name}?download=1",
    }


@router.get("/jobs/{job_id}/log")
def job_log(job_id: str, tail: int = 80):
    cfg = load_user_config()
    eng = DftbEngine(wsl_distro=str(cfg.get("wsl_distro") or settings.wsl_distro or ""))
    arts = eng.fetch_artifacts(job_id, ["dftb.log", "detailed.out", "status"])
    log = arts.get("dftb.log") or ""
    lines = log.splitlines()
    raw_status = (arts.get("status") or "").strip()
    st = raw_status.lower()
    zh = {
        "pending": "排队中",
        "running": "计算中",
        "done": "已完成",
        "error": "失败",
        "cancelled": "已取消",
    }.get(st, raw_status or "未知")
    return {
        "job_id": job_id,
        "status": raw_status,
        "status_zh": zh,
        "log_tail": "\n".join(lines[-max(tail, 10) :]),
        "has_detailed": "detailed.out" in arts,
    }
