"""WSL / 本机 DFTB+ 隔离部署与状态探测。"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from ..config import load_user_config, save_user_config, settings
from dftb_engine.local_runner import (
    LocalDftbRunner,
    decode_wsl_bytes,
    is_wsl_distro_name,
    list_wsl_distros,
    looks_garbled_wsl_text,
    resolve_wsl_distro,
    run_local,
    run_wsl,
    use_wsl,
    wsl_exe,
)

_UBUNTU_NAME = "Ubuntu-22.04"
_UBUNTU_USER = "neu123"
_ROOTFS_URLS = (
    "https://mirrors.tuna.tsinghua.edu.cn/ubuntu-cloud-images/wsl/jammy/current/ubuntu-jammy-wsl-amd64-ubuntu22.04lts.rootfs.tar.gz",
    "https://mirrors.ustc.edu.cn/ubuntu-cloud-images/wsl/jammy/current/ubuntu-jammy-wsl-amd64-ubuntu22.04lts.rootfs.tar.gz",
)
_deploy_lock = threading.Lock()


def _repo_script() -> Path:
    return settings.root / "scripts" / "wsl_deploy_dftb.sh"


def _distro_enterable(name: str) -> bool:
    """发行版是否已经能执行命令。列表解析失败时用这条判断，避免空转。"""
    if not name or not is_wsl_distro_name(name):
        return False
    try:
        r = run_wsl("whoami", timeout=25, distro=name)
        text = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode != 0 or not text:
            return False
        low = text.lower()
        if "wsl.exe --install" in low or "aka.ms/wslinstall" in low:
            return False
        return True
    except Exception:
        return False


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
    has_exe = shutil.which("wsl.exe") is not None or shutil.which("wsl") is not None
    distros: list[str] = []
    default = ""
    version_ok = False
    msg = ""
    status_out = ""
    wsl2_ok = True
    if has_exe:
        try:
            distros = [n for n in list_wsl_distros() if is_wsl_distro_name(n)]
            if not distros and _distro_enterable(_UBUNTU_NAME):
                distros = [_UBUNTU_NAME]
            default = distros[0] if distros else ""
            version_ok = bool(distros)
            msg = "已检测到 WSL。" if distros else "尚未安装 Ubuntu。点「部署到本机」将从国内镜像安装。"
        except Exception as e:
            msg = f"WSL 探测失败：{e}"
    else:
        msg = "尚未启用 WSL。点「部署到本机」将自动启用（需确认管理员权限）。"
    needs_reboot = False
    if has_exe and not distros:
        wsl2_ok, status_out = _wsl2_ready()
        if not wsl2_ok:
            needs_reboot = _pending_reboot()
            if _looks_wsl_not_installed(status_out):
                msg = "尚未装好 WSL。点「部署到本机」；若弹出管理员确认请点「是」。"
            else:
                msg = "需先重启电脑。" if needs_reboot else "WSL2 未就绪。点「部署到本机」；若弹出管理员确认请点「是」。"
        else:
            _set_pending_reboot(False)
    # wsl.exe 在不等于子系统已装；空壳会报「未安装适用于 Linux 的 Windows 子系统」
    has_wsl = bool(has_exe) and not _looks_wsl_not_installed(status_out)
    ready = bool(has_wsl and distros)
    return {
        "platform": system,
        "wsl_required": True,
        "wsl_available": has_wsl,
        "wsl_distros": distros,
        "default_distro": default,
        "wsl2_likely": version_ok,
        "ready_for_deploy": ready,
        "wsl2_ready": wsl2_ok,
        "needs_reboot": needs_reboot,
        "message": msg,
        "admin_commands": [],
        "docs_url": "https://learn.microsoft.com/windows/wsl/install",
    }


def _progress_path() -> Path:
    return settings.store / "deploy-progress.json"


def _clear_stale_fail_progress() -> None:
    """三项已通过时，清掉误报的「安装失败」，避免和卡片打架。"""
    path = _progress_path()
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "失败" in str(raw.get("message") or ""):
                path.write_text(
                    json.dumps(
                        {
                            "phase": "done",
                            "message": "部署完成，测试校验通过",
                            "log": "",
                            "updated_at": int(time.time()),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
    except Exception:
        pass
    with _job_guard:
        res = _job_state.get("result")
        if isinstance(res, dict) and "失败" in str(res.get("message") or ""):
            _job_state["result"] = {
                **res,
                "ok": True,
                "message": "部署完成，测试校验通过",
                "log_tail": "",
            }


def set_deploy_progress(phase: str, message: str, log: str = "") -> None:
    payload = {
        "phase": phase,
        "message": message,
        "log": (log or "")[-4000:],
        "updated_at": int(time.time()),
    }
    path = _progress_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class _ProgressBeat:
    """导入 / 安装期间没有字节进度，用已用时间避免界面像卡住。"""

    def __init__(self, phase: str, message: str):
        self.phase = phase
        self.message = message
        self.stop = threading.Event()
        self.t0 = time.time()
        self.th = threading.Thread(target=self._run, daemon=True)

    def _line(self) -> str:
        sec = max(0, int(time.time() - self.t0))
        return f"{self.message}（已用 {sec // 60} 分 {sec % 60} 秒，请勿关闭软件）"

    def _run(self) -> None:
        while not self.stop.wait(1):
            set_deploy_progress(self.phase, self._line())

    def __enter__(self) -> "_ProgressBeat":
        set_deploy_progress(self.phase, self._line())
        self.th.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop.set()
        self.th.join(timeout=2)


_job_guard = threading.Lock()
_job_state: dict[str, Any] = {"running": False, "result": None, "started_at": 0}


def read_deploy_progress() -> dict[str, Any]:
    path = _progress_path()
    data: dict[str, Any] = {"phase": "", "message": "", "log": ""}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except Exception:
            pass
    with _job_guard:
        data["running"] = bool(_job_state["running"])
        data["result"] = _job_state["result"]
        data["started_at"] = int(_job_state.get("started_at") or 0)
    return data


def _wsl_flags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def _wsl_run(args: list[str], *, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(
        [wsl_exe(), *args],
        capture_output=True,
        timeout=timeout,
        creationflags=_wsl_flags(),
    )
    return r.returncode, (decode_wsl_bytes(r.stdout) + decode_wsl_bytes(r.stderr)).strip()


def _strip_wsl1_status_lines(text: str) -> str:
    """Win11 新版 WSL 即使 WSL2 可用，也会提示「若要使用 WSL1，请启用可选组件」。"""
    kept: list[str] = []
    for ln in (text or "").splitlines():
        low = ln.lower()
        if "wsl1" in low:
            continue
        if "不支持 wsl1" in low:
            continue
        kept.append(ln)
    return "\n".join(kept)


def _status_says_wsl2_default(text: str) -> bool:
    t = text or ""
    low = t.lower()
    return (
        "默认版本: 2" in t
        or "默认版本：2" in t
        or "default version: 2" in low
        or "default version : 2" in low
    )


def _looks_wsl_not_installed(text: str) -> bool:
    """有 wsl.exe 空壳，但 Windows 子系统还没装上。"""
    raw = text or ""
    compact = raw.lower().replace(" ", "").replace("\r", "").replace("\n", "")
    if "未安装适用于" in raw and "子系统" in raw:
        return True
    if "aka.ms/wslinstall" in compact:
        return True
    if "windowssubsystemforlinuxisnotinstalled" in compact:
        return True
    if "wsl.exe--install" in compact:
        if "没有已安装的分发" in raw or "hasnoinstalleddistributions" in compact:
            return False
        return True
    return False


def _looks_feature_error(text: str) -> bool:
    raw = _strip_wsl1_status_lines(text or "")
    low = raw.lower()
    keys = (
        "virtual machine platform",
        "enablevirtualization",
        "0x80370102",
        "0x80040326",
        "wsl/service/createinstance",
        "请启用虚拟机平台",
        "未启用虚拟机平台",
        "尚未启用虚拟机平台",
        "虚拟机平台未",
        "没有安装内核",
        "wsl2 无法",
        "update the wsl",
        "hcs_e_service_not_available",
        "createvm",
        "hypervisor is not running",
        "virtualization support not detected",
        "未检测到虚拟化",
        "未开启虚拟化",
    )
    return any(k in low or k in raw for k in keys)


_REBOOT_MSG = "请先重启电脑。重启后再打开本软件，点「部署到本机」。"


def _wsl2_ready() -> tuple[bool, str]:
    """wsl.exe 在并不等于 WSL2 能用；空壳或虚拟机平台未开时不能当成就绪。"""
    try:
        code, out = _wsl_run(["--status"], timeout=20)
    except Exception as e:
        return False, str(e)
    if _looks_wsl_not_installed(out):
        return False, out
    if _looks_feature_error(out):
        return False, out
    if _status_says_wsl2_default(out):
        return True, out
    if code != 0:
        return False, out
    return True, out


def _boot_stamp() -> str:
    """当前这次开机的时间戳；重启后会变，用来清掉过期的「请先重启」。"""
    try:
        r = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('s')",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_wsl_flags(),
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _pending_reboot() -> bool:
    cfg = load_user_config()
    if not cfg.get("wsl_pending_reboot"):
        return False
    saved = str(cfg.get("wsl_pending_reboot_boot") or "")
    now = _boot_stamp()
    if saved and now and saved != now:
        _set_pending_reboot(False)
        return False
    return True


def _set_pending_reboot(on: bool) -> None:
    cfg = load_user_config()
    if on:
        cfg["wsl_pending_reboot"] = True
        stamp = _boot_stamp()
        if stamp:
            cfg["wsl_pending_reboot_boot"] = stamp
    else:
        cfg.pop("wsl_pending_reboot", None)
        cfg.pop("wsl_pending_reboot_boot", None)
    save_user_config(cfg)


def _deploy_fail(phase: str, message: str, **extra: Any) -> dict[str, Any]:
    set_deploy_progress(phase, message)
    payload = {"ok": False, "phase": phase, "message": message, "wsl": detect_wsl()}
    payload.update(extra)
    return payload


def _download_rootfs(dest: Path) -> None:
    if dest.is_file() and dest.stat().st_size > 80 * 1024 * 1024:
        head = dest.read_bytes()[:2]
        if head == b"\x1f\x8b":
            set_deploy_progress("ubuntu", "已有 Ubuntu 镜像，正在导入…")
            return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err = ""
    for url in _ROOTFS_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DFTB-Neu-Setup"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                last = 0
                with tmp.open("wb") as f:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if got - last >= 2 * 1024 * 1024:
                            last = got
                            mb = got / (1024 * 1024)
                            if total:
                                set_deploy_progress(
                                    "ubuntu",
                                    f"正在从国内镜像下载 Ubuntu（{mb:.0f} / {total / (1024 * 1024):.0f} MB）",
                                )
                            else:
                                set_deploy_progress(
                                    "ubuntu", f"正在从国内镜像下载 Ubuntu（已下 {mb:.0f} MB）"
                                )
            if tmp.stat().st_size < 10 * 1024 * 1024:
                last_err = "镜像文件过小"
                tmp.unlink(missing_ok=True)
                continue
            tmp.replace(dest)
            return
        except Exception as e:
            last_err = str(e)[:240]
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    raise RuntimeError(last_err or "国内镜像下载失败")


def _setup_ubuntu_user(distro: str) -> None:
    script = (
        f"id -u {_UBUNTU_USER} >/dev/null 2>&1 || useradd -m -s /bin/bash {_UBUNTU_USER}; "
        f"echo '{_UBUNTU_USER}:{_UBUNTU_USER}' | chpasswd; "
        f"usermod -aG sudo {_UBUNTU_USER}; "
        f"printf '[user]\\ndefault={_UBUNTU_USER}\\n' > /etc/wsl.conf"
    )
    run_wsl(script, timeout=60, distro=distro, user="root")
    _wsl_run(["--terminate", distro], timeout=30)


def ensure_ubuntu_from_mirror() -> dict[str, Any]:
    """有 wsl.exe 时从国内镜像导入 Ubuntu，不走微软商店。"""
    info = detect_wsl()
    if not info.get("wsl_required"):
        return {"ok": True, "skipped": True, "wsl": info}
    if info.get("ready_for_deploy"):
        return {"ok": True, "already_ready": True, "wsl": info, "distro": info.get("default_distro") or _UBUNTU_NAME}
    if _distro_enterable(_UBUNTU_NAME):
        cfg = load_user_config()
        cfg["wsl_distro"] = _UBUNTU_NAME
        save_user_config(cfg)
        ready = detect_wsl()
        return {"ok": True, "already_ready": True, "wsl": ready, "distro": _UBUNTU_NAME}
    if not info.get("wsl_available"):
        return _deploy_fail(
            "wsl",
            "需要先启用 WSL。将弹出管理员确认，请点「是」。启用后若提示重启，重启后再点「部署到本机」。",
            needs_wsl_feature=True,
        )

    wsl2_ok, status_text = _wsl2_ready()
    if not wsl2_ok:
        if _pending_reboot():
            return _deploy_fail(
                "wsl",
                _REBOOT_MSG,
                needs_reboot=True,
                log_tail=(status_text or "")[-600:],
            )
        if _looks_wsl_not_installed(status_text):
            return _deploy_fail(
                "wsl",
                "本机尚未装好 WSL。将弹出管理员确认，请点「是」。装完后若提示重启，重启后再点「部署到本机」。",
                needs_wsl_feature=True,
                log_tail=(status_text or "")[-600:],
            )
        return _deploy_fail(
            "wsl",
            "本机尚未启用 WSL2（虚拟机平台）。将弹出管理员确认，请点「是」。点完后若提示重启，重启后再点「部署到本机」。",
            needs_wsl_feature=True,
            log_tail=(status_text or "")[-600:],
        )

    set_deploy_progress("ubuntu", "正在从国内镜像准备 Ubuntu…")
    cache = settings.store / "cache" / "ubuntu-jammy-wsl.rootfs.tar.gz"
    install_dir = Path(os.environ.get("LOCALAPPDATA") or settings.store) / "WSL" / _UBUNTU_NAME
    try:
        _download_rootfs(cache)
    except Exception as e:
        return _deploy_fail("ubuntu", f"从国内镜像下载 Ubuntu 失败：{e}。请检查网络后再次点「部署到本机」。")

    if not cache.is_file() or cache.stat().st_size < 80 * 1024 * 1024:
        return _deploy_fail("ubuntu", "Ubuntu 镜像未下载完整。请再点「部署到本机」。")

    install_dir.mkdir(parents=True, exist_ok=True)
    try:
        _wsl_run(["--set-default-version", "2"], timeout=30)
    except Exception:
        pass
    try:
        with _ProgressBeat("ubuntu", "正在导入 Ubuntu 发行版，解压大约需要几分钟"):
            code, out = _wsl_run(
                ["--import", _UBUNTU_NAME, str(install_dir), str(cache), "--version", "2"],
                timeout=900,
            )
    except subprocess.TimeoutExpired:
        return _deploy_fail("ubuntu", "导入 Ubuntu 超时。请再点一次「部署到本机」。")
    except Exception as e:
        return _deploy_fail("ubuntu", f"导入 Ubuntu 失败：{e}")

    already = "already exists" in (out or "").lower() or "已存在" in (out or "")
    if code != 0 and not already:
        if _looks_wsl_not_installed(out):
            return _deploy_fail(
                "wsl",
                "本机尚未装好 WSL。将弹出管理员确认，请点「是」。装完后若提示重启，重启后再点「部署到本机」。",
                needs_wsl_feature=True,
                log_tail=(out or "")[-600:],
            )
        if _looks_feature_error(out) or "hcs_e_service_not_available" in (out or "").lower():
            _set_pending_reboot(True)
            return _deploy_fail(
                "wsl",
                _REBOOT_MSG,
                needs_reboot=True,
                log_tail=(out or "")[-600:],
            )
        if "file_not_found" in (out or "").lower() or "找不到指定的文件" in (out or ""):
            try:
                cache.unlink(missing_ok=True)
            except Exception:
                pass
            return _deploy_fail("ubuntu", "Ubuntu 镜像不完整，将重新下载。请再点「部署到本机」。")
        detail = (out or "").replace("\r", " ").strip()
        return _deploy_fail(
            "ubuntu",
            f"导入 Ubuntu 失败。{detail[:180] or '请再点一次「部署到本机」。'}",
            log_tail=(out or "")[-600:],
        )

    set_deploy_progress("ubuntu", "正在创建日常用户…")
    try:
        _setup_ubuntu_user(_UBUNTU_NAME)
    except Exception:
        pass
    try:
        _wsl_run(["--set-default", _UBUNTU_NAME], timeout=30)
    except Exception:
        pass

    if not _distro_enterable(_UBUNTU_NAME):
        return {
            "ok": False,
            "phase": "ubuntu",
            "message": "Ubuntu 已导入，但现在还进不去。请过一两分钟再点「部署到本机」。",
            "wsl": detect_wsl(),
        }
    info = detect_wsl()
    cfg = load_user_config()
    cfg["wsl_distro"] = _UBUNTU_NAME
    save_user_config(cfg)
    set_deploy_progress("ubuntu", "Ubuntu 已就绪，继续安装 DFTB+…")
    return {"ok": True, "imported": True, "wsl": info, "distro": _UBUNTU_NAME}


def _enable_wsl_feature() -> dict[str, Any]:
    launched = False
    launch_error = ""
    try:
        import ctypes

        rc = int(
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "wsl.exe",
                "--install --no-distribution",
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
        try:
            ps = (
                "Start-Process -FilePath wsl.exe "
                "-ArgumentList '--install','--no-distribution' -Verb RunAs"
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
                creationflags=_wsl_flags(),
            )
            if r.returncode == 0:
                launched = True
            else:
                launch_error = (r.stderr or r.stdout or launch_error or f"exit {r.returncode}")[:400]
        except Exception as e:
            launch_error = launch_error or str(e)[:300]
    if not launched:
        return {
            "ok": False,
            "phase": "wsl",
            "needs_wsl_feature": True,
            "message": "未能启用 WSL"
            + (f"：{launch_error}" if launch_error else "。")
            + "请再点「部署到本机」，并在管理员确认框中允许。",
            "wsl": detect_wsl(),
        }
    deadline = time.time() + 25
    while time.time() < deadline:
        ok, _status = _wsl2_ready()
        if ok:
            _set_pending_reboot(False)
            return {"ok": True, "enabled": True, "wsl": detect_wsl()}
        time.sleep(3)
    ok, status_text = _wsl2_ready()
    if ok:
        _set_pending_reboot(False)
        return {"ok": True, "enabled": True, "wsl": detect_wsl()}
    _set_pending_reboot(True)
    return {
        "ok": False,
        "phase": "wsl",
        "needs_reboot": True,
        "needs_reboot_or_wait": True,
        "message": "已请求启用 WSL2。" + _REBOOT_MSG,
        "wsl": detect_wsl(),
        "log_tail": (status_text or "")[-400:],
    }


def ensure_wsl(*, poll_seconds: int = 90) -> dict[str, Any]:
    """就绪则直接返回；否则从国内镜像导入 Ubuntu。仅在缺 WSL 功能时提权。"""
    info = detect_wsl()
    if not info.get("wsl_required"):
        return {"ok": True, "skipped": True, "wsl": info}
    if info.get("ready_for_deploy"):
        return {"ok": True, "already_ready": True, "wsl": info}
    if info.get("wsl_available"):
        imported = ensure_ubuntu_from_mirror()
        if imported.get("ok"):
            return imported
        if imported.get("needs_wsl_feature"):
            return _enable_wsl_feature()
        return imported
    return _enable_wsl_feature()


def deploy_status() -> dict[str, Any]:
    cfg = load_user_config()
    preferred = cfg.get("wsl_distro") or settings.wsl_distro or ""
    distro = resolve_wsl_distro(str(preferred or ""))
    if distro and is_wsl_distro_name(distro) and distro != cfg.get("wsl_distro"):
        cfg["wsl_distro"] = distro
        save_user_config(cfg)
    wsl_info = detect_wsl()
    runner = LocalDftbRunner(wsl_distro=distro)
    probe = runner.test()
    smoke = _read_smoke(distro)
    wsl_ok = bool(wsl_info.get("ready_for_deploy")) or not wsl_info.get("wsl_required")
    dftb_ok = (probe or {}).get("status") == "ok"
    smoke_ok = bool((smoke or {}).get("ok"))
    progress = read_deploy_progress()
    deploying = bool(progress.get("running"))
    deploy_phase = str(progress.get("phase") or "")
    deploy_message = str(progress.get("message") or "").strip()
    # 盘里已有的 DFTB+ 不能当成「这一轮已经完成」
    environment_ready = bool(dftb_ok and smoke_ok and not deploying)
    if deploying:
        summary = deploy_message or "正在部署，请勿关闭软件。"
    elif environment_ready:
        summary = "环境已就绪：WSL、DFTB+ 与测试校验均通过。"
        _clear_stale_fail_progress()
    elif dftb_ok and not smoke_ok:
        summary = "DFTB+ 已安装，但测试校验未通过；请重新部署或查看日志。"
    elif wsl_ok and not dftb_ok:
        summary = "WSL 就绪，尚未完成 DFTB+ 隔离安装。"
    elif wsl_info.get("needs_reboot") or _pending_reboot():
        summary = _REBOOT_MSG
    elif wsl_info.get("wsl2_ready") is False:
        summary = "本机 WSL2 未就绪。点「部署到本机」；若弹出管理员确认请点「是」。点完后必须重启电脑，再打开软件继续。"
    else:
        summary = "尚未就绪。点「部署到本机」将从国内镜像安装 Ubuntu，再安装 DFTB+。"
    return {
        "wsl": wsl_info,
        "dftb": probe,
        "smoke": smoke,
        "readiness": {
            "wsl_ok": wsl_ok,
            "dftb_ok": dftb_ok,
            "smoke_ok": smoke_ok,
            "environment_ready": environment_ready,
            "deploying": deploying,
            "deploy_phase": deploy_phase,
            "deploy_message": deploy_message,
            "needs_reboot": bool(wsl_info.get("needs_reboot") or _pending_reboot()),
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
    """立即返回，实际部署在后台线程，避免把进度查询堵住。"""
    with _job_guard:
        if _job_state["running"]:
            return {
                "ok": True,
                "started": True,
                "running": True,
                "message": "部署正在进行，请看下方进度。",
            }
        _job_state["running"] = True
        _job_state["result"] = None
        _job_state["started_at"] = int(time.time())

    def worker() -> None:
        try:
            result = _run_deploy_locked(
                distro=distro, ensure_wsl_first=ensure_wsl_first, retried=False
            )
            with _job_guard:
                _job_state["result"] = result
        except Exception as e:
            with _job_guard:
                _job_state["result"] = {"ok": False, "phase": "dftb", "message": str(e)[:400]}
        finally:
            with _job_guard:
                _job_state["running"] = False

    set_deploy_progress("ubuntu", "正在部署…")
    threading.Thread(target=worker, daemon=True, name="dftb-deploy").start()
    return {
        "ok": True,
        "started": True,
        "running": True,
        "message": "已开始部署。",
    }


def _run_deploy_locked(*, distro: str, ensure_wsl_first: bool, retried: bool = False) -> dict[str, Any]:
    wsl_info = detect_wsl()
    if wsl_info.get("wsl_required") and not wsl_info.get("ready_for_deploy"):
        if not ensure_wsl_first:
            return {
                "ok": False,
                "phase": "wsl",
                "message": "WSL 尚未就绪。请点击「部署到本机」。",
                "wsl": wsl_info,
            }
        if not wsl_info.get("wsl_available"):
            return _enable_wsl_feature()
        ensured = ensure_ubuntu_from_mirror()
        wsl_info = ensured.get("wsl") or detect_wsl()
        distro_name = str(ensured.get("distro") or _UBUNTU_NAME)
        if not ensured.get("ok"):
            return {
                "ok": False,
                "phase": ensured.get("phase") or "wsl",
                "needs_wsl_feature": bool(ensured.get("needs_wsl_feature")),
                "needs_reboot_or_wait": bool(ensured.get("needs_reboot_or_wait")),
                "message": ensured.get("message") or "Ubuntu 尚未就绪。请再点「部署到本机」。",
                "wsl": wsl_info,
            }
        if not wsl_info.get("ready_for_deploy") and not _distro_enterable(distro_name):
            return {
                "ok": False,
                "phase": ensured.get("phase") or "wsl",
                "needs_wsl_feature": bool(ensured.get("needs_wsl_feature")),
                "needs_reboot_or_wait": bool(ensured.get("needs_reboot_or_wait")),
                "message": ensured.get("message") or "Ubuntu 尚未就绪。请再点「部署到本机」。",
                "wsl": wsl_info,
            }
        if ensured.get("distro"):
            distro = str(ensured["distro"])

    cfg = load_user_config()
    raw = distro or cfg.get("wsl_distro") or settings.wsl_distro or ""
    distro = resolve_wsl_distro(str(raw or "")) or wsl_info.get("default_distro") or ""
    if distro and not is_wsl_distro_name(distro):
        distro = _UBUNTU_NAME if _distro_enterable(_UBUNTU_NAME) else ""
    if distro and is_wsl_distro_name(distro):
        cfg["wsl_distro"] = distro
        save_user_config(cfg)

    script_path = _repo_script()
    if not script_path.is_file():
        return {"ok": False, "phase": "dftb", "message": f"缺少部署脚本：{script_path}"}

    try:
        with _ProgressBeat("dftb", "Ubuntu 已就绪，正在安装 DFTB+"):
            if use_wsl():
                import base64

                body = script_path.read_text(encoding="utf-8")
                b64 = base64.b64encode(body.encode()).decode()
                bash = (
                    f"echo {b64} | base64 -d > /tmp/dftb_edu_deploy.sh && "
                    "chmod +x /tmp/dftb_edu_deploy.sh && bash /tmp/dftb_edu_deploy.sh"
                )
                r = run_wsl(bash, timeout=1800, distro=distro)
            else:
                r = run_local(f"bash {script_path}", timeout=1800)
        full = (r.stdout or "") + (r.stderr or "")
        marked_ok = "DEPLOY_OK" in full and "SMOKE_OK" in full
        marked_dftb = "DEPLOY_OK" in full
        out = "\n".join(
            ln
            for ln in full.splitlines()
            if ln.strip()
            and "localhost 代理" not in ln
            and "不支持 localhost 代理" not in ln
        )[-4000:]
        if looks_garbled_wsl_text(out) and not marked_ok:
            out = ""
        ok = marked_ok
        low = full.lower()
        no_distro = (
            "wsl.exe --install" in low
            or "aka.ms/wslinstall" in low
            or "没有已安装的分发" in full
            or "不存在具有所提供名称的分发" in full
            or "wsl_e_distro_not_found" in low
        ) and not marked_ok
        if no_distro and not ok:
            if retried:
                return {
                    "ok": False,
                    "phase": "wsl",
                    "message": "本机还没有可用的 Ubuntu。请再点「部署到本机」。",
                    "log_tail": "",
                    "status": deploy_status(),
                }
            set_deploy_progress("ubuntu", "未找到可用的 Ubuntu，将重新从国内镜像安装。")
            retry = ensure_ubuntu_from_mirror()
            if retry.get("ok"):
                return _run_deploy_locked(
                    distro=str(retry.get("distro") or distro),
                    ensure_wsl_first=False,
                    retried=True,
                )
            return {
                "ok": False,
                "phase": retry.get("phase") or "wsl",
                "needs_wsl_feature": bool(retry.get("needs_wsl_feature")),
                "message": retry.get("message") or "本机还没有可用的 Ubuntu。请再点「部署到本机」。",
                "log_tail": "",
                "status": deploy_status(),
            }
        if looks_garbled_wsl_text(out):
            out = ""
        st_now = deploy_status()
        ready = bool((st_now.get("readiness") or {}).get("environment_ready"))
        if marked_ok or ready:
            ok = True
            message = "部署完成，测试校验通过"
        elif marked_dftb:
            message = "DFTB+ 已安装，但测试校验未通过"
        else:
            message = "DFTB+ 安装失败"
        set_deploy_progress("done" if ok else "dftb", message, out)
        return {
            "ok": ok,
            "phase": "dftb",
            "message": message,
            "log_tail": out,
            "status": deploy_status(),
        }
    except subprocess.TimeoutExpired:
        set_deploy_progress("dftb", "部署超时（已中止）。请再点「部署到本机」。")
        return {"ok": False, "phase": "dftb", "message": "部署超时（已中止）。请再点「部署到本机」。"}
    except Exception as e:
        set_deploy_progress("dftb", str(e)[:400])
        return {"ok": False, "phase": "dftb", "message": str(e)[:400]}
