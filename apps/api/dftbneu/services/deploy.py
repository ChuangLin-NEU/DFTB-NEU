"""WSL / 本机 DFTB+ 隔离部署与状态探测。"""

from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..config import load_user_config, save_user_config, settings
from dftb_engine.local_runner import (
    LocalDftbRunner,
    resolve_wsl_distro,
    run_local,
    run_wsl,
    use_wsl,
    wsl_exe,
)


def _repo_script() -> Path:
    return settings.root / "scripts" / "wsl_deploy_dftb.sh"


def detect_wsl() -> dict[str, Any]:
    """Windows 上检测 WSL2；其它平台视为本机 Linux/macOS。"""
    system = platform.system()
    if system != "Windows":
        return {
            "platform": system,
            "wsl_required": False,
            "wsl_available": False,
            "ready_for_deploy": True,
            "message": "当前为非 Windows 环境，可直接在本机用户目录隔离部署。",
            "admin_commands": [],
            "docs_url": "https://learn.microsoft.com/windows/wsl/install",
        }
    exe = wsl_exe()
    has_wsl = shutil.which("wsl.exe") is not None or shutil.which("wsl") is not None
    distros: list[str] = []
    default = ""
    version_ok = False
    msg = ""
    if has_wsl:
        try:
            r = subprocess.run([exe, "-l", "-v"], capture_output=True, text=True, timeout=20)
            text = (r.stdout or "") + (r.stderr or "")
            # wsl -l -v 常为 UTF-16；再试 --list --verbose
            if not text.strip():
                r2 = subprocess.run([exe, "--list", "--verbose"], capture_output=True, timeout=20)
                text = (r2.stdout or b"").decode("utf-16-le", errors="replace") + (
                    r2.stderr or b""
                ).decode("utf-16-le", errors="replace")
            for line in text.splitlines():
                line = line.strip().replace("\x00", "")
                if not line or line.lower().startswith("windows subsystem") or "NAME" in line.upper():
                    continue
                parts = line.split()
                if not parts:
                    continue
                name = parts[0].lstrip("*").strip()
                if name:
                    distros.append(name)
                    if line.startswith("*") or "*" in parts[0]:
                        default = name
                if "2" in parts[-1:] or "VERSION" not in line.upper() and len(parts) >= 3 and parts[-1] == "2":
                    version_ok = True
            if not default and distros:
                default = distros[0]
            if any("2" in ln.replace("\x00", "") for ln in text.splitlines()):
                version_ok = True
            version_ok = version_ok or bool(distros)
            msg = "已检测到 WSL。" if distros else "已安装 wsl.exe，但未找到发行版。"
        except Exception as e:
            msg = f"WSL 探测失败：{e}"
    else:
        msg = "未检测到 WSL。点击「部署到本机」将自动启用（需确认管理员权限）。"
    ready = bool(has_wsl and distros)
    return {
        "platform": system,
        "wsl_required": True,
        "wsl_available": has_wsl,
        "wsl_distros": distros,
        "default_distro": default,
        "wsl2_likely": version_ok,
        "ready_for_deploy": ready,
        "message": msg,
        "admin_commands": [],
        "docs_url": "https://learn.microsoft.com/windows/wsl/install",
    }


def ensure_wsl(*, poll_seconds: int = 90) -> dict[str, Any]:
    """若 WSL/发行版未就绪，提权启动 ``wsl --install -d Ubuntu``，并短时轮询。"""
    info = detect_wsl()
    if not info.get("wsl_required"):
        return {"ok": True, "skipped": True, "wsl": info}
    if info.get("ready_for_deploy"):
        return {"ok": True, "already_ready": True, "wsl": info}

    launched = False
    launch_error = ""
    try:
        import ctypes

        # ShellExecuteW runas：弹出 UAC，由系统执行安装（用户无需手敲命令）
        rc = int(
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "wsl.exe",
                "--install -d Ubuntu",
                None,
                1,
            )
        )
        if rc > 32:
            launched = True
        else:
            launch_error = f"ShellExecute 返回 {rc}（可能取消了管理员确认）"
    except Exception as e:
        launch_error = str(e)[:300]

    if not launched:
        # 备用：PowerShell Start-Process -Verb RunAs
        try:
            ps = (
                "Start-Process -FilePath wsl.exe "
                "-ArgumentList '--install','-d','Ubuntu' -Verb RunAs"
            )
            r = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode == 0:
                launched = True
            else:
                launch_error = (r.stderr or r.stdout or launch_error or f"exit {r.returncode}")[
                    :400
                ]
        except Exception as e:
            launch_error = launch_error or str(e)[:300]

    if not launched:
        return {
            "ok": False,
            "phase": "wsl",
            "message": "未能启动 WSL 安装"
            + (f"：{launch_error}" if launch_error else "。")
            + "请再次点击「部署到本机」，并在管理员确认框中允许。",
            "wsl": detect_wsl(),
        }

    deadline = time.time() + max(10, poll_seconds)
    while time.time() < deadline:
        info = detect_wsl()
        if info.get("ready_for_deploy"):
            return {"ok": True, "installed": True, "wsl": info}
        time.sleep(5)

    info = detect_wsl()
    if info.get("ready_for_deploy"):
        return {"ok": True, "installed": True, "wsl": info}
    return {
        "ok": False,
        "phase": "wsl",
        "needs_reboot_or_wait": True,
        "message": (
            "已启动 WSL2 / Ubuntu 安装。若系统提示重启，请重启后再次点击「部署到本机」；"
            "否则稍候再点一次即可继续安装 DFTB+。"
        ),
        "wsl": info,
    }


def deploy_status() -> dict[str, Any]:
    cfg = load_user_config()
    preferred = cfg.get("wsl_distro") or settings.wsl_distro or ""
    distro = resolve_wsl_distro(str(preferred or ""))
    if distro and distro != cfg.get("wsl_distro"):
        cfg["wsl_distro"] = distro
        save_user_config(cfg)
    wsl_info = detect_wsl()
    runner = LocalDftbRunner(wsl_distro=distro)
    probe = runner.test()
    smoke = _read_smoke(distro)
    wsl_ok = bool(wsl_info.get("ready_for_deploy")) or not wsl_info.get("wsl_required")
    dftb_ok = (probe or {}).get("status") == "ok"
    smoke_ok = bool((smoke or {}).get("ok"))
    environment_ready = bool(dftb_ok and smoke_ok)
    if environment_ready:
        summary = "环境已就绪：WSL、DFTB+ 与测试校验均通过。"
    elif dftb_ok and not smoke_ok:
        summary = "DFTB+ 已安装，但测试校验未通过；请重新部署或查看日志。"
    elif wsl_ok and not dftb_ok:
        summary = "WSL 就绪，尚未完成 DFTB+ 隔离安装。"
    else:
        summary = "请先启用 WSL2，再执行隔离部署。"
    return {
        "wsl": wsl_info,
        "dftb": probe,
        "smoke": smoke,
        "readiness": {
            "wsl_ok": wsl_ok,
            "dftb_ok": dftb_ok,
            "smoke_ok": smoke_ok,
            "environment_ready": environment_ready,
            "summary": summary,
        },
        "home_hint": "~/.dftb-neu（Windows 作业目录可映射到 %LOCALAPPDATA%\\dftb-neu）",
        "settings": {
            "wsl_distro": distro or wsl_info.get("default_distro") or "",
        },
    }


def _read_smoke(distro: str) -> dict[str, Any]:
    script = (
        'F="$HOME/.dftb-neu/jobs/smoke_h2o/detailed.out"; '
        'L="$HOME/.dftb-neu/jobs/smoke_h2o/dftb.log"; '
        'if [ -f "$F" ] && grep -q "Geometry converged" "$F"; then echo SMOKE_OK; '
        'elif [ -f "$L" ]; then echo SMOKE_FAIL; tail -20 "$L"; else echo SMOKE_NONE; fi'
    )
    try:
        if use_wsl():
            r = run_wsl(script, timeout=30, distro=distro)
        else:
            r = run_local(script, timeout=30)
        out = (r.stdout or "") + (r.stderr or "")
        if "SMOKE_OK" in out:
            return {"ok": True, "message": "测试校验通过：H₂O 几何优化已收敛"}
        if "SMOKE_NONE" in out:
            return {"ok": False, "message": "尚未执行测试校验"}
        return {"ok": False, "message": "测试校验未通过", "log_tail": out[-600:]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


def run_deploy(*, distro: str = "", ensure_wsl_first: bool = True) -> dict[str, Any]:
    """启用 WSL（如需要）后执行隔离部署脚本。"""
    wsl_info = detect_wsl()
    if wsl_info.get("wsl_required") and not wsl_info.get("ready_for_deploy"):
        if not ensure_wsl_first:
            return {
                "ok": False,
                "phase": "wsl",
                "message": "WSL 尚未就绪。请点击「部署到本机」自动启用。",
                "wsl": wsl_info,
            }
        ensured = ensure_wsl()
        wsl_info = ensured.get("wsl") or detect_wsl()
        if not wsl_info.get("ready_for_deploy"):
            return {
                "ok": False,
                "phase": "wsl",
                "needs_reboot_or_wait": ensured.get("needs_reboot_or_wait", True),
                "message": ensured.get("message")
                or "WSL 尚未就绪。请确认管理员权限或重启后再点「部署到本机」。",
                "wsl": wsl_info,
            }

    cfg = load_user_config()
    distro = distro or cfg.get("wsl_distro") or settings.wsl_distro or ""
    distro = resolve_wsl_distro(str(distro or "")) or distro or wsl_info.get("default_distro") or ""
    if distro:
        cfg["wsl_distro"] = distro
        save_user_config(cfg)

    script_path = _repo_script()
    if not script_path.is_file():
        return {"ok": False, "phase": "dftb", "message": f"缺少部署脚本：{script_path}"}

    try:
        if use_wsl():
            # 将脚本经 stdin 喂给 bash
            body = script_path.read_text(encoding="utf-8")
            import base64

            b64 = base64.b64encode(body.encode()).decode()
            bash = (
                f"echo {b64} | base64 -d > /tmp/dftb_edu_deploy.sh && "
                "chmod +x /tmp/dftb_edu_deploy.sh && bash /tmp/dftb_edu_deploy.sh"
            )
            r = run_wsl(bash, timeout=1800, distro=distro)
        else:
            r = run_local(f"bash {script_path}", timeout=1800)
        out = ((r.stdout or "") + (r.stderr or ""))[-4000:]
        ok = "DEPLOY_OK" in out and "SMOKE_OK" in out
        return {
            "ok": ok,
            "phase": "dftb",
            "message": (
                "隔离部署完成，测试校验通过"
                if "SMOKE_OK" in out
                else ("部署结束但测试校验未通过" if "DEPLOY_OK" in out else "部署失败")
            ),
            "log_tail": out,
            "status": deploy_status(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "phase": "dftb", "message": "部署超时（已中止）。请查看日志后重新部署。"}
    except Exception as e:
        return {"ok": False, "phase": "dftb", "message": str(e)[:400]}
