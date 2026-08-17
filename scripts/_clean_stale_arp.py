#!/usr/bin/env python3
import os
import re
import winreg

path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as root:
    i = 0
    to_del = []
    while True:
        try:
            name = winreg.EnumKey(root, i)
            i += 1
        except OSError:
            break
        try:
            with winreg.OpenKey(root, name) as k:
                disp, _ = winreg.QueryValueEx(k, "DisplayName")
                uni, _ = winreg.QueryValueEx(k, "UninstallString")
        except OSError:
            continue
        if "DFTB" not in str(disp):
            continue
        m = re.match(r'"([^"]+)"', str(uni)) or re.match(r"(\S+\.exe)", str(uni))
        exe = m.group(1) if m else ""
        ok = os.path.isfile(exe)
        print(disp, "exe_ok", ok, exe)
        if not ok:
            to_del.append(name)
    for name in to_del:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path + "\\" + name)
        print("deleted", name)
