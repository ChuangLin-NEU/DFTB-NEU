#!/usr/bin/env python3
"""在临时目录实测卸载脚本逻辑（不破坏真实安装）。"""

from __future__ import annotations

import os
import subprocess
import time
import winreg
from pathlib import Path

APP = "DFTBWorkbenchProbe"
KEY = "DFTBNeuWorkbenchProbe"
FAKE = Path(os.environ["TEMP"]) / "dftb-uninst-probe"


def main() -> int:
    subprocess.run(["cmd", "/c", "rd", "/s", "/q", str(FAKE)], check=False)
    FAKE.mkdir(parents=True)
    (FAKE / f"{APP}.exe").write_text("dummy", encoding="utf-8")

    lines = [
        "$ErrorActionPreference = 'SilentlyContinue'",
        "$Root = Split-Path -Parent $MyInvocation.MyCommand.Path",
        f"$AppName = '{APP}'",
        f"$KeyName = '{KEY}'",
        "$links = @(",
        "  (Join-Path $env:USERPROFILE ('Desktop\\' + $AppName + '.lnk'))",
        ")",
        "foreach ($l in $links) { if (Test-Path -LiteralPath $l) { Remove-Item -LiteralPath $l -Force } }",
        "$reg = Join-Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall' $KeyName",
        "if (Test-Path $reg) { Remove-Item -LiteralPath $reg -Recurse -Force }",
        "$tmpPs1 = Join-Path $env:TEMP ('dftb-uninst-' + [guid]::NewGuid().ToString('N') + '.ps1')",
        "$lines = @(",
        "  '$ErrorActionPreference = ''SilentlyContinue''',",
        "  'Start-Sleep -Seconds 1',",
        "  ('cmd /c rd /s /q \"' + $Root + '\"'),",
        "  ('Remove-Item -LiteralPath \"' + $tmpPs1 + '\" -Force -ErrorAction SilentlyContinue')",
        ")",
        "Set-Content -LiteralPath $tmpPs1 -Value $lines -Encoding UTF8",
        "Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$tmpPs1) -WindowStyle Hidden",
        "",
    ]
    ps1_path = FAKE / "uninstall.ps1"
    ps1_path.write_bytes("\ufeff".encode("utf-8") + "\n".join(lines).encode("utf-8"))
    uninst_cmd = FAKE / f"Uninstall {APP}.cmd"
    uninst_cmd.write_text(
        '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"\r\n',
        encoding="utf-8",
    )

    lnk = Path.home() / "Desktop" / f"{APP}.lnk"
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:QS_LNK); "
            "$s.TargetPath=$env:QS_EXE; $s.Save()",
        ],
        env={**os.environ, "QS_LNK": str(lnk), "QS_EXE": str(FAKE / f"{APP}.exe")},
        check=False,
    )

    reg_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{KEY}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, f"{APP}")
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, f'"{uninst_cmd}"')

    print("before:", FAKE.exists(), "lnk", lnk.exists())
    r = subprocess.run(["cmd", "/c", str(uninst_cmd)], check=False, capture_output=True, text=True)
    print("cmd exit", r.returncode, (r.stderr or r.stdout or "")[:200])
    time.sleep(3)
    reg_after = True
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path)
    except FileNotFoundError:
        reg_after = False
    print("after: fake=", FAKE.exists(), "lnk=", lnk.exists(), "reg=", reg_after)
    ok = (not FAKE.exists()) and (not lnk.exists()) and (not reg_after)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
