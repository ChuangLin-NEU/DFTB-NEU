# DFTB 工作台 — Windows 打包说明

交付物为**现代 Setup**（Electron 无边框安装界面 + portable，**不用 NSIS**）。

安装后即可打开使用；学生端内嵌 Windows Python 与依赖，**无需预装 Python**。  
DFTB+ 计算仍在本机 WSL2 中完成（应用内「部署」页引导）。

## 正式打包（学生端 + 教师端）

```bat
cd packaging\windows
npm install --registry=https://registry.npmmirror.com

rem 复用已有内置 Python / pydeps 时：
set SKIP_WIN_PYTHON=1
set SKIP_PYDEPS=1
set COPY_DESKTOP=1
node scripts\pack-win.mjs
```

仅一端：`set TARGET=student` 或 `set TARGET=teacher`

## 快速迭代（已有 win-unpacked）

```bat
set MODE=modern
set COPY_DESKTOP=1
node scripts\pack-fast.mjs
```

| 模式 | 说明 |
|---|---|
| `MODE=modern`（默认） | 现代 UI Setup（非 NSIS） |
| `MODE=zip` | 只出 zip |

## 产物

`packaging/windows/release/`

| 文件 | 说明 |
|---|---|
| `DFTB_Neu_Setup_<ver>.exe` | 学生端：内嵌 Python + API + UI |
| `DFTB_Neu_Teacher_Setup_<ver>.exe` | 教师端：监管界面（无计算） |

## 新电脑预期

**学生端**：安装 → 打开 → 登录（学号 + 本堂密码）→「部署到本机」→ 开始计算。  
**教师端**：安装 → 发布本堂密码（课堂服务已预置）。
