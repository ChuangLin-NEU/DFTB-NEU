"""dftb-neu FastAPI 应用。"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

def _detect_root() -> Path:
    here = Path(__file__).resolve()
    packaged = here.parents[2]
    if (packaged / "api").is_dir() and (packaged / "engines").is_dir():
        return packaged
    return here.parents[3]


# engines on path
_ROOT = _detect_root()
_ENG = _ROOT / "engines" / "dftb_agent"
if str(_ENG) not in sys.path:
    sys.path.insert(0, str(_ENG))
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dftbneu.routers import (
    assets,
    chat,
    courses,
    deploy,
    jobs,
    license as license_router,
    projects,
    settings as settings_router,
    status,
    structure,
)

app = FastAPI(title="DFTB Neu", version="0.2.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(settings_router.router, prefix="/api")
app.include_router(deploy.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(courses.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(structure.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(license_router.router, prefix="/api")


@app.middleware("http")
async def classroom_license_gate(request, call_next):
    path = request.url.path or ""
    if not path.startswith("/api/"):
        return await call_next(request)
    open_prefixes = (
        "/api/health",
        "/api/license",
        "/api/settings",
        "/api/status",
    )
    if any(path == p or path.startswith(p + "/") for p in open_prefixes):
        return await call_next(request)
    import time

    from fastapi.responses import JSONResponse

    from dftbneu.services import license as lic

    if not lic.license_required():
        return await call_next(request)
    st = lic.public_license_status()
    if not st.get("activated"):
        return JSONResponse(
            {"detail": "尚未登录或会话已失效", "license": st},
            status_code=401,
        )
    # 本地过期立即拒绝；超过 15 秒未在线校验则向中心重验（教师清密码后尽快失效）
    cfg_last = float(st.get("last_ok_at") or 0)
    if not cfg_last or (time.time() - cfg_last) > 15:
        check = await lic.check_session(allow_offline_grace=True)
        if not check.get("ok"):
            return JSONResponse(
                {
                    "detail": check.get("message") or "课堂许可无效，请重新登录",
                    "license": lic.public_license_status(),
                },
                status_code=401,
            )
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "dftb-neu"}


# 打包：resources/web；开发：apps/web[/dist]
_web_candidates = [
    _ROOT / "web",
    _ROOT / "apps" / "web" / "dist",
    _ROOT / "apps" / "web",
]
_web_dir = next((p for p in _web_candidates if (p / "index.html").is_file()), None)
if _web_dir is not None:
    _NO_CACHE = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    if (_web_dir / "app.js").is_file() and not (_web_dir / "assets").is_dir():
        # 源码静态页（无 vite dist）
        @app.get("/")
        def index():
            return FileResponse(_web_dir / "index.html", headers=_NO_CACHE)

        @app.get("/static/{file_path:path}")
        def static_file(file_path: str):
            target = (_web_dir / file_path).resolve()
            if not str(target).startswith(str(_web_dir.resolve())) or not target.is_file():
                from fastapi import HTTPException

                raise HTTPException(404)
            return FileResponse(target, headers=_NO_CACHE)

    else:
        app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")


def main():
    import uvicorn
    from dftbneu.config import settings

    uvicorn.run("dftbneu.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
