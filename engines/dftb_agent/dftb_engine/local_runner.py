"""DFTB+ 本地 / WSL 运行桥接（无 VASP / SSH 依赖）。"""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_DISTRO_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")


def edu_home() -> Path:
    """数据根：跨平台用户目录下的 .dftb-neu。"""
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "dftb-neu"
    return Path.home() / ".dftb-neu"


def jobs_dir() -> Path:
    d = edu_home() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def use_wsl() -> bool:
    if platform.system() != "Windows":
        return False
    return shutil.which("wsl.exe") is not None or shutil.which("wsl") is not None


def wsl_exe() -> str:
    return shutil.which("wsl.exe") or shutil.which("wsl") or "wsl.exe"


def _utf16_nul_ratio(raw: bytes) -> float:
    """奇数位大量 0x00 才像 UTF-16LE。偶数长度的 UTF-8 不能按 UTF-16 解。"""
    if len(raw) < 4:
        return 0.0
    sample = raw[: min(240, len(raw))]
    if len(sample) % 2:
        sample = sample[:-1]
    pairs = len(sample) // 2
    if pairs == 0:
        return 0.0
    nuls = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
    return nuls / pairs


def _decode_score(s: str) -> int:
    if not s:
        return -10
    bad = s.count("\ufffd")
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    ascii_ok = sum(1 for ch in s if ch.isascii() and ch.isprintable())
    latin = sum(1 for ch in s if "A" <= ch <= "Z" or "a" <= ch <= "z")
    repeat_pen = 0
    if len(s) >= 12:
        for n in (2, 3, 4):
            chunk = s[:n]
            if chunk.strip() and s.count(chunk) >= 4:
                repeat_pen = 80
                break
    marker = 0
    low = s.lower()
    for m in ("deploy_ok", "smoke_ok", "ubuntu", "name", "state", "wsl", "dftb", "geometry"):
        if m in low:
            marker += 40
    if len(s) > 24 and cjk > len(s) * 0.65 and latin < 4:
        return -80 - bad * 12 - repeat_pen
    return cjk * 2 + ascii_ok + marker - bad * 12 - repeat_pen


def decode_wsl_bytes(data: bytes | None) -> str:
    """wsl.exe 自身常用 UTF-16；发行版里 bash 输出是 UTF-8。只在像 UTF-16 时才按 UTF-16 解。"""
    if not data:
        return ""
    raw = bytes(data)
    cands: list[str] = []
    utf16_likely = (
        raw.startswith(b"\xff\xfe")
        or raw.startswith(b"\xfe\xff")
        or _utf16_nul_ratio(raw) >= 0.35
    )
    if raw.startswith(b"\xfe\xff"):
        cands.append(raw.decode("utf-16-be", errors="replace"))
    elif utf16_likely:
        cands.append(raw.decode("utf-16-le", errors="replace"))
    try:
        cands.append(raw.decode("utf-8"))
    except UnicodeDecodeError:
        cands.append(raw.decode("utf-8", errors="replace"))
    if not utf16_likely:
        for enc in ("gbk", "cp936"):
            try:
                cands.append(raw.decode(enc))
            except UnicodeDecodeError:
                continue
    best = max(cands, key=_decode_score)
    return best.replace("\x00", "").replace("\ufeff", "")


def looks_garbled_wsl_text(text: str) -> bool:
    """解错码后的重复生僻字，不能当安装日志展示。"""
    if not text:
        return False
    if "DEPLOY_OK" in text or "SMOKE_OK" in text:
        return False
    if _decode_score(text) < 0:
        return True
    if text.count("\ufffd") >= 2:
        return True
    return False


def _looks_mojibake(text: str) -> bool:
    if not text:
        return False
    if text.count("\ufffd") >= 2:
        return True
    low = text.lower()
    return "wsl.exe --install" in low or "aka.ms/wslinstall" in low


def is_wsl_distro_name(name: str) -> bool:
    n = (name or "").strip().lstrip("*")
    if not n or not _DISTRO_NAME_RE.match(n):
        return False
    return n.lower() not in {"name", "state", "version", "windows", "linux", "subsystem"}


_WSL_DISTRO_CACHE: Optional[str] = None


def list_wsl_distros() -> list[str]:
    """列出本机 WSL 发行版名称。"""
    if not use_wsl():
        return []
    exe = wsl_exe()
    names: list[str] = []
    try:
        r = subprocess.run([exe, "-l", "-v"], capture_output=True, timeout=20)
        text = decode_wsl_bytes(r.stdout) + decode_wsl_bytes(r.stderr)
        for line in text.splitlines():
            line = line.strip().replace("\x00", "")
            if not line or line.lower().startswith("windows subsystem"):
                continue
            parts = line.split()
            if parts and parts[0] in {"*", ">"}:
                parts = parts[1:]
            if not parts:
                continue
            name = parts[0].lstrip("*").strip()
            if name.upper() in {"NAME", "STATE", "VERSION"}:
                continue
            if is_wsl_distro_name(name) and name not in names:
                names.append(name)
    except Exception:
        return []
    preferred = [n for n in names if n.lower().startswith("ubuntu")]
    others = [n for n in names if n.lower() not in {"docker-desktop", "docker-desktop-data"} and n not in preferred]
    return preferred + others


def _distro_has_dftb(distro: str) -> bool:
    """探测指定发行版用户目录下是否已安装 dftb+。"""
    if not distro:
        return False
    script = 'test -x "$HOME/.dftb-neu/envs/dftbplus/bin/dftb+" && echo HAS_DFTB'
    try:
        r = run_wsl(script, timeout=12, distro=distro)
        return "HAS_DFTB" in ((r.stdout or "") + (r.stderr or ""))
    except Exception:
        return False


def resolve_wsl_distro(preferred: str = "") -> str:
    """选择可用的 WSL 发行版：优先已配置且含 DFTB+ 的；否则扫描含 DFTB+ 的发行版。"""
    global _WSL_DISTRO_CACHE
    preferred = (preferred or os.environ.get("DFTB_NEU_WSL_DISTRO") or "").strip()
    if preferred and not is_wsl_distro_name(preferred):
        preferred = ""
    if _WSL_DISTRO_CACHE and not is_wsl_distro_name(_WSL_DISTRO_CACHE):
        _WSL_DISTRO_CACHE = None
    if preferred and _distro_has_dftb(preferred):
        _WSL_DISTRO_CACHE = preferred
        return preferred
    if _WSL_DISTRO_CACHE and _distro_has_dftb(_WSL_DISTRO_CACHE):
        return _WSL_DISTRO_CACHE
    for name in list_wsl_distros():
        if preferred and name == preferred:
            continue
        if _distro_has_dftb(name):
            _WSL_DISTRO_CACHE = name
            return name
    known = list_wsl_distros()
    if preferred and preferred in known:
        _WSL_DISTRO_CACHE = preferred
        return preferred
    if known:
        _WSL_DISTRO_CACHE = known[0]
        return known[0]
    return ""


def run_local(cmd: str, *, cwd: Optional[Path] = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        shell=True,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ},
    )


def run_wsl(
    bash_cmd: str, *, timeout: int = 600, distro: str = "", user: str = ""
) -> subprocess.CompletedProcess:
    """在 WSL 默认（或指定）发行版执行 bash -lc。"""
    exe = wsl_exe()
    prefix = [exe]
    if distro:
        prefix += ["-d", distro]
    if user:
        prefix += ["-u", user]
    prefix += ["-e", "bash", "-lc", bash_cmd]
    flags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    r = subprocess.run(prefix, capture_output=True, timeout=timeout, creationflags=flags)
    return subprocess.CompletedProcess(
        r.args,
        r.returncode,
        decode_wsl_bytes(r.stdout),
        decode_wsl_bytes(r.stderr),
    )


def env_bin_prefix() -> str:
    """shell 内 PATH 前缀（Linux / WSL 路径）。"""
    return (
        'export PATH="$HOME/.dftb-neu/envs/dftbplus/bin:$HOME/.dftb-neu/bin:$PATH"; '
        'export DFTB_NEU_HOME="$HOME/.dftb-neu"; '
    )


class LocalDftbRunner:
    """本机（macOS/Linux）或 Windows+WSL 上提交 DFTB+ 作业。"""

    def __init__(self, wsl_distro: str = ""):
        self._wsl = use_wsl()
        raw = (wsl_distro or os.environ.get("DFTB_NEU_WSL_DISTRO") or "").strip()
        # Windows：自动落到已安装 DFTB+ 的发行版，避免默认发行版无引擎导致作业秒退
        self.wsl_distro = resolve_wsl_distro(raw) if self._wsl else raw

    def test(self) -> dict[str, Any]:
        script = env_bin_prefix() + 'command -v dftb+ && dftb+ --version 2>&1 | head -n 6; '
        script += 'find "$HOME/.dftb-neu/share/dftb/sk" -name "*.skf" 2>/dev/null | wc -l'
        try:
            if self._wsl:
                r = run_wsl(script, timeout=30, distro=self.wsl_distro)
            else:
                r = run_local(script, timeout=30)
            out = (r.stdout or "") + (r.stderr or "")
            ok = r.returncode == 0 and "dftb" in out.lower()
            if ok:
                first = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
                return {
                    "status": "ok",
                    "message": (first[:160] if first else "已安装并可探测"),
                    "wsl": self._wsl,
                    "detail": out[-800:],
                }
            return {
                "status": "error",
                "message": "尚未安装 DFTB+",
                "wsl": self._wsl,
                "detail": out[-800:],
            }
        except Exception as e:
            err = str(e)[:300]
            if _looks_mojibake(err):
                err = "未能探测 DFTB+"
            return {"status": "error", "message": err, "wsl": self._wsl}

    def submit_job(self, files: dict[str, str], *, job_id: str = "", np: int = 1) -> dict[str, Any]:
        job_id = job_id or f"edu_{uuid.uuid4().hex[:10]}"
        if not job_id.startswith(("edu_", "cmats_")):
            job_id = f"edu_{job_id}"

        if self._wsl:
            return self._submit_wsl(job_id, files, np=np)
        return self._submit_native(job_id, files, np=np)

    def _job_run_script(self) -> str:
        """写入作业目录的 run.sh：避免嵌套引号导致后台任务无法启动。"""
        return (
            "#!/usr/bin/env bash\n"
            "set +e\n"
            'cd "$(dirname "$0")" || exit 1\n'
            + env_bin_prefix()
            + "\n"
            "echo running > status\n"
            "date +%s > started_at\n"
            ": > dftb.log\n"
            "rc=0\n"
            "# 展开所有 HSD 中的 $HOME（含 opt/dos 附属输入；DFTB+ 不会自己展开）\n"
            "for _hsd in dftb_in.hsd dftb_in_opt.hsd dftb_in_dos.hsd modes_in.hsd; do\n"
            '  if [ -f "$_hsd" ]; then sed -i "s|\\$HOME|'"$HOME"'|g" "$_hsd" || true; fi\n'
            "done\n"
            "# 预优化：dftb_in_opt.hsd → 必须产出 geo_end.gen，否则不进入后续阶段\n"
            "if [ -f dftb_in_opt.hsd ]; then\n"
            "  cp -f dftb_in.hsd dftb_in_elec.hsd\n"
            "  cp -f dftb_in_opt.hsd dftb_in.hsd\n"
            '  sed -i "s|\\$HOME|'"$HOME"'|g" dftb_in.hsd || true\n'
            "  echo '==== stage1: geometry optimization ====' >> dftb.log\n"
            "  dftb+ >> dftb.log 2>&1 &\n"
            "  echo $! > dftb.pid\n"
            "  wait $(cat dftb.pid 2>/dev/null)\n"
            "  rc=$?\n"
            "  if [ $rc -ne 0 ]; then\n"
            "    echo '==== stage1 failed: geometry optimization error ====' >> dftb.log\n"
            "  elif [ ! -f geo_end.gen ]; then\n"
            "    echo '==== stage1 failed: missing geo_end.gen (refuse silent fallback) ====' >> dftb.log\n"
            "    rc=1\n"
            "  else\n"
            "    cp -f geo_end.gen geo.gen\n"
            "    echo '==== stage1 done: geo_end.gen -> geo.gen ====' >> dftb.log\n"
            "  fi\n"
            "  cp -f dftb_in_elec.hsd dftb_in.hsd\n"
            "fi\n"
            "if [ $rc -eq 0 ]; then\n"
            "  echo '==== stage2: electronic / main DFTB+ ====' >> dftb.log\n"
            "  dftb+ >> dftb.log 2>&1 &\n"
            "  echo $! > dftb.pid\n"
            "  wait $(cat dftb.pid 2>/dev/null)\n"
            "  rc=$?\n"
            "fi\n"
            "# 能带+DOS：另跑均匀 k 网格，避免路径 DOS 冒充态密度\n"
            "if [ $rc -eq 0 ] && [ -f dftb_in_dos.hsd ]; then\n"
            "  if [ -f band.out ]; then cp -f band.out band_path.out; fi\n"
            "  cp -f dftb_in.hsd dftb_in_band.hsd\n"
            "  cp -f dftb_in_dos.hsd dftb_in.hsd\n"
            '  sed -i "s|\\$HOME|'"$HOME"'|g" dftb_in.hsd || true\n'
            "  echo '==== stage3: uniform k-mesh DOS ====' >> dftb.log\n"
            "  dftb+ >> dftb.log 2>&1 &\n"
            "  echo $! > dftb.pid\n"
            "  wait $(cat dftb.pid 2>/dev/null)\n"
            "  rc=$?\n"
            "  if [ -f band.out ]; then cp -f band.out band_dos.out; fi\n"
            "  if [ -f band_path.out ]; then cp -f band_path.out band.out; fi\n"
            "  cp -f dftb_in_band.hsd dftb_in.hsd\n"
            "fi\n"
            "# 振动任务：hessian 完成后用 modes 求频率（cm-1）\n"
            'if [ $rc -eq 0 ] && [ -f modes_in.hsd ] && [ -f hessian.out ] && command -v modes >/dev/null 2>&1; then\n'
            "  if [ -f modes_in.hsd ]; then sed -i \"s|\\$HOME|$HOME|g\" modes_in.hsd || true; fi\n"
            "  modes > modes.log 2>&1 || true\n"
            "fi\n"
            "date +%s > finished_at\n"
            'if [ -f started_at ] && [ -f finished_at ]; then\n'
            '  echo $(( $(cat finished_at) - $(cat started_at) )) > wall_seconds\n'
            "else\n"
            "  echo -1 > wall_seconds\n"
            "fi\n"
            'cur=$(cat status 2>/dev/null || true)\n'
            'if [ "$cur" = "cancelled" ]; then\n'
            "  echo 130 > exit_code\n"
            "elif [ $rc -eq 0 ]; then\n"
            "  echo done > status\n"
            "  echo $rc > exit_code\n"
            "else\n"
            "  echo error > status\n"
            "  echo $rc > exit_code\n"
            "fi\n"
        )

    def _submit_native(self, job_id: str, files: dict[str, str], *, np: int) -> dict[str, Any]:
        jd = jobs_dir() / job_id
        jd.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            text = content.replace("$HOME/.dftb-neu", str(Path.home() / ".dftb-neu"))
            text = text.replace("$HOME", str(Path.home()))
            (jd / name).write_text(text, encoding="utf-8")
        run_sh = jd / "run.sh"
        run_sh.write_text(self._job_run_script(), encoding="utf-8")
        try:
            run_sh.chmod(0o755)
        except Exception:
            pass
        (jd / "status").write_text("pending", encoding="utf-8")
        subprocess.Popen(
            ["bash", str(run_sh)],
            cwd=str(jd),
            start_new_session=True,
            stdout=open(jd / "runner.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        time.sleep(0.3)
        return {"status": "ok", "job_id": job_id, "work_dir": str(jd), "backend": "native"}

    def _submit_wsl(self, job_id: str, files: dict[str, str], *, np: int) -> dict[str, Any]:
        # 在 WSL 家目录写作业；run.sh 单独落盘再 nohup，避免嵌套引号失败
        import base64

        b64_parts = []
        for name, content in files.items():
            text = content.replace("$HOME/.cmats", "$HOME/.dftb-neu")
            b64 = base64.b64encode(text.encode()).decode()
            b64_parts.append(f'echo {shlex.quote(b64)} | base64 -d > "$JD/{name}"')
        run_b64 = base64.b64encode(self._job_run_script().encode()).decode()
        writes = "\n".join(b64_parts)
        launch = f"""
{env_bin_prefix()}
JD="$HOME/.dftb-neu/jobs/{job_id}"
mkdir -p "$JD" "$HOME/.dftb-neu/jobs"
if ! command -v dftb+ >/dev/null 2>&1; then
  echo NO_DFTB_BIN
  echo "dftb+ not found in PATH (distro=$(uname -n) home=$HOME)" >&2
  exit 2
fi
{writes}
echo {shlex.quote(run_b64)} | base64 -d > "$JD/run.sh"
chmod +x "$JD/run.sh"
# 投递时即展开全部 HSD，避免 stage1 用 dftb_in_opt.hsd 覆盖后仍残留字面量 $HOME
for _hsd in dftb_in.hsd dftb_in_opt.hsd dftb_in_dos.hsd modes_in.hsd; do
  if [ -f "$JD/$_hsd" ]; then sed -i "s|\\$HOME|$HOME|g" "$JD/$_hsd" || true; fi
done
echo pending > "$JD/status"
nohup bash "$JD/run.sh" > "$JD/runner.log" 2>&1 &
echo $! > "$JD/runner.pid"
sleep 0.4
RPID=$(cat "$JD/runner.pid" 2>/dev/null || true)
ST=$(cat "$JD/status" 2>/dev/null || echo unknown)
# 小体系（如水分子优化）常在 0.4s 内算完，runner 已退出但 status=done/running/error，属正常启动
if [ -n "$RPID" ] && kill -0 "$RPID" 2>/dev/null; then
  echo SUBMIT_OK
elif [ "$ST" = "done" ] || [ "$ST" = "running" ] || [ "$ST" = "error" ]; then
  echo SUBMIT_OK
  echo FAST_FINISH:$ST
else
  echo RUNNER_DEAD
  echo STATUS:$ST
  tail -n 40 "$JD/runner.log" 2>/dev/null || true
  exit 3
fi
echo DISTRO_HOME:$HOME
"""
        r = run_wsl(launch, timeout=120, distro=self.wsl_distro)
        out = (r.stdout or "") + (r.stderr or "")
        if "NO_DFTB_BIN" in out:
            return {
                "status": "error",
                "job_id": job_id,
                "message": (
                    f"当前 WSL 发行版「{self.wsl_distro or '默认'}」未找到 dftb+。"
                    "请在「部署」页选择已安装环境的发行版并重新部署。"
                ),
                "backend": "wsl",
                "raw": out[-800:],
            }
        if "RUNNER_DEAD" in out or ("SUBMIT_OK" not in out and r.returncode != 0):
            return {
                "status": "error",
                "job_id": job_id,
                "message": "作业未能启动（后台进程已退出）。请查看日志后取消并重新确认计算。",
                "backend": "wsl",
                "raw": out[-800:],
            }
        return {
            "status": "ok",
            "job_id": job_id,
            "work_dir": f"~/.dftb-neu/jobs/{job_id}",
            "backend": "wsl",
            "wsl_distro": self.wsl_distro,
            "fast_finish": "FAST_FINISH:" in out,
        }

    def get_status(self, job_id: str) -> dict[str, Any]:
        timing: dict[str, Any] = {}
        if self._wsl:
            r = run_wsl(
                f'JD="$HOME/.dftb-neu/jobs/{job_id}"; '
                'if [ ! -d "$JD" ]; then echo NOT_FOUND; exit 0; fi; '
                'echo STATUS:$(cat "$JD/status" 2>/dev/null || echo unknown); '
                'echo STARTED:$(cat "$JD/started_at" 2>/dev/null || echo); '
                'echo FINISHED:$(cat "$JD/finished_at" 2>/dev/null || echo); '
                'echo WALL:$(cat "$JD/wall_seconds" 2>/dev/null || echo); '
                'echo HASLOG:$([ -s "$JD/dftb.log" ] && echo 1 || echo 0); '
                'echo HASRUN:$([ -f "$JD/run.sh" ] && echo 1 || echo 0); '
                'if [ -f "$JD/dftb.pid" ]; then echo DPID:$(cat "$JD/dftb.pid"); fi; '
                'if [ -f "$JD/runner.pid" ]; then echo RPID:$(cat "$JD/runner.pid"); '
                '  if kill -0 $(cat "$JD/runner.pid") 2>/dev/null; then echo RALIVE:1; else echo RALIVE:0; fi; '
                "fi; "
                'if [ -f "$JD/runner.log" ]; then echo RLOG:$(tail -n 8 "$JD/runner.log" | tr "\\n" " " | head -c 400); fi; '
                'if [ -f "$JD/dftb.log" ]; then echo DLOG:$(tail -n 8 "$JD/dftb.log" | tr "\\n" " " | head -c 400); fi',
                timeout=20,
                distro=self.wsl_distro,
            )
            raw_all = (r.stdout or "").strip()
            raw = "unknown"
            diag: dict[str, Any] = {}
            for line in raw_all.splitlines():
                if line.startswith("STATUS:"):
                    raw = line.split(":", 1)[1].strip()
                elif line.startswith("STARTED:") and line.split(":", 1)[1].strip().isdigit():
                    timing["started_at"] = int(line.split(":", 1)[1].strip())
                elif line.startswith("FINISHED:") and line.split(":", 1)[1].strip().isdigit():
                    timing["finished_at"] = int(line.split(":", 1)[1].strip())
                elif line.startswith("WALL:"):
                    try:
                        timing["wall_seconds"] = float(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif line.startswith("HASLOG:"):
                    diag["has_log"] = line.split(":", 1)[1].strip() == "1"
                elif line.startswith("HASRUN:"):
                    diag["has_run_script"] = line.split(":", 1)[1].strip() == "1"
                elif line.startswith("RALIVE:"):
                    diag["runner_alive"] = line.split(":", 1)[1].strip() == "1"
                elif line.startswith("DPID:"):
                    diag["dftb_pid"] = line.split(":", 1)[1].strip()
                elif line.startswith("RPID:"):
                    diag["runner_pid"] = line.split(":", 1)[1].strip()
                elif line.startswith("RLOG:"):
                    diag["runner_log_tail"] = line.split(":", 1)[1].strip()
                elif line.startswith("DLOG:"):
                    diag["dftb_log_tail"] = line.split(":", 1)[1].strip()
        else:
            diag = {}
            jd = jobs_dir() / job_id
            p = jd / "status"
            raw = p.read_text(encoding="utf-8").strip() if p.is_file() else "NOT_FOUND"
            for key, fname in (("started_at", "started_at"), ("finished_at", "finished_at")):
                fp = jd / fname
                if fp.is_file():
                    try:
                        timing[key] = int(fp.read_text(encoding="utf-8").strip())
                    except ValueError:
                        pass
            wp = jd / "wall_seconds"
            if wp.is_file():
                try:
                    timing["wall_seconds"] = float(wp.read_text(encoding="utf-8").strip())
                except ValueError:
                    pass
            if jd.is_dir():
                log_p = jd / "dftb.log"
                diag["has_log"] = log_p.is_file() and log_p.stat().st_size > 0
                diag["has_run_script"] = (jd / "run.sh").is_file()
                rpid_p = jd / "runner.pid"
                if rpid_p.is_file():
                    try:
                        rpid = int(rpid_p.read_text(encoding="utf-8").strip())
                        diag["runner_pid"] = str(rpid)
                        os.kill(rpid, 0)
                        diag["runner_alive"] = True
                    except Exception:
                        diag["runner_alive"] = False

        first = raw.splitlines()[0].strip().upper() if raw else "UNKNOWN"
        status = "unknown"
        if first.startswith("DONE"):
            status = "done"
        elif first.startswith("CANCEL"):
            status = "cancelled"
        elif first.startswith("ERROR"):
            status = "error"
        elif first.startswith("RUNNING"):
            status = "running"
        elif first.startswith("PENDING"):
            status = "pending"
        elif first.startswith("NOT_FOUND"):
            status = "not_found"
        if status in ("running", "pending") and timing.get("started_at") and "wall_seconds" not in timing:
            timing["elapsed_seconds"] = max(0, int(time.time()) - int(timing["started_at"]))
        elif timing.get("started_at") and timing.get("finished_at") and "wall_seconds" not in timing:
            timing["wall_seconds"] = max(0, int(timing["finished_at"]) - int(timing["started_at"]))
        out: dict[str, Any] = {"job_id": job_id, "status": status, "raw": raw}
        if timing:
            out["timing"] = timing
        if diag:
            out["diag"] = diag
        # 仍为 pending 但无法启动：视为失败，避免界面永久“排队中”
        # 注意：超快作业会先写 running/done，不应在此误杀；仅 status 仍为 pending 时判断
        if status == "pending":
            tip = diag.get("runner_log_tail") or diag.get("dftb_log_tail") or ""
            # 已有引擎日志说明 runner 曾启动（可能极快结束但 status 未刷新）——再读一次 status 文件由上层轮询即可
            if diag.get("runner_alive") is False and not diag.get("has_log"):
                out["status"] = "error"
                if "not found" in tip.lower() or "No such file" in tip or (
                    "dftb+" in tip.lower() and "command" in tip.lower()
                ):
                    out["message"] = (
                        f"作业未能启动：当前 WSL「{self.wsl_distro or '默认'}」找不到 dftb+。"
                        "请到「部署」页刷新并确认发行版，或重新部署后再次确认计算。"
                    )
                else:
                    out["message"] = "作业未能启动（后台进程已退出），请取消后重新确认计算。"
                if tip:
                    out["log_hint"] = tip
            elif diag.get("has_run_script") is False and diag.get("has_log") is False:
                out["status"] = "error"
                out["message"] = "旧作业未正确启动（缺少运行脚本），请取消或删除后重新确认计算。"
        return out

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """终止本机 / WSL 上的 DFTB+ 作业。"""
        if self._wsl:
            script = f"""
JD="$HOME/.dftb-neu/jobs/{job_id}"
if [ ! -d "$JD" ]; then echo NOT_FOUND; exit 0; fi
st=$(cat "$JD/status" 2>/dev/null || echo unknown)
if [ "$st" = "done" ] || [ "$st" = "cancelled" ]; then echo ALREADY:$st; exit 0; fi
if [ -f "$JD/dftb.pid" ]; then
  pid=$(cat "$JD/dftb.pid" 2>/dev/null || true)
  if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true; fi
fi
if [ -f "$JD/runner.pid" ]; then
  rpid=$(cat "$JD/runner.pid" 2>/dev/null || true)
  if [ -n "$rpid" ]; then kill "$rpid" 2>/dev/null || kill -9 "$rpid" 2>/dev/null || true; fi
fi
for pid in $(pgrep -f '[d]ftb\\+' 2>/dev/null || true); do
  cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
  case "$cwd" in *"/jobs/{job_id}"*) kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true;; esac
done
echo cancelled > "$JD/status"
date +%s > "$JD/finished_at"
echo CANCELLED
"""
            r = run_wsl(script, timeout=30, distro=self.wsl_distro)
            out = (r.stdout or "") + (r.stderr or "")
            if "NOT_FOUND" in out:
                return {"ok": False, "job_id": job_id, "status": "not_found", "message": "作业目录不存在"}
            return {"ok": True, "job_id": job_id, "status": "cancelled", "message": "已取消作业", "raw": out[-400:]}
        jd = jobs_dir() / job_id
        if not jd.is_dir():
            return {"ok": False, "job_id": job_id, "status": "not_found", "message": "作业目录不存在"}
        st_path = jd / "status"
        cur = st_path.read_text(encoding="utf-8").strip().lower() if st_path.is_file() else ""
        if cur in ("done", "cancelled"):
            return {"ok": True, "job_id": job_id, "status": cur, "message": "作业已结束"}
        pid_path = jd / "dftb.pid"
        if pid_path.is_file():
            try:
                pid = int(pid_path.read_text(encoding="utf-8").strip())
                os.kill(pid, 15)
                time.sleep(0.2)
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
            except (ValueError, ProcessLookupError, PermissionError):
                pass
        st_path.write_text("cancelled", encoding="utf-8")
        (jd / "finished_at").write_text(str(int(time.time())), encoding="utf-8")
        return {"ok": True, "job_id": job_id, "status": "cancelled", "message": "已取消作业"}

    def fetch_artifacts(self, job_id: str, names: Optional[list[str]] = None) -> dict[str, str]:
        names = names or [
            "dftb_in.hsd",
            "geo.gen",
            "POSCAR",
            "band_meta.json",
            "run.sh",
            "detailed.out",
            "dftb.log",
            "runner.log",
            "band.out",
            "band_dos.out",
            "band_path.out",
            "geo_end.gen",
            "EXC.DAT",
            "hessian.out",
            "modes.log",
            "vibrations.tag",
            "md.out",
            "status",
            "started_at",
            "finished_at",
            "wall_seconds",
            "exit_code",
        ]
        out: dict[str, str] = {}
        if self._wsl:
            for name in names:
                r = run_wsl(
                    f'F="$HOME/.dftb-neu/jobs/{job_id}/{name}"; '
                    'if [ -f "$F" ]; then head -c 400000 "$F"; else echo __MISSING__; fi',
                    timeout=60,
                    distro=self.wsl_distro,
                )
                text = r.stdout or ""
                if text.strip() == "__MISSING__":
                    continue
                out[name] = text
        else:
            jd = jobs_dir() / job_id
            for name in names:
                p = jd / name
                if p.is_file():
                    out[name] = p.read_text(encoding="utf-8", errors="replace")[:400000]
        return out
