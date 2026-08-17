# DFTB-NEU

[English](README.en.md)

DFTB+ 本机计算客户端（Windows 源码，v0.3.5），用于科研与课堂教学。Windows 上经 WSL2 部署 DFTB+；可选接入服务中心做教学登录。

本仓库仅自己可见。本机配置与密钥在对应文件里（`.env` 等），不要把密钥抄进说明。软著申请材料在 `软件著作权申请/`。

## 目录

```
apps/api/          FastAPI（127.0.0.1）
apps/web/          页面
engines/dftb_agent/
packaging/windows/ Electron 与 Setup
scripts/           WSL 部署等
docs/              教师手册、学生手册、DFTB 命令
templates/         能力与 playbook
软件著作权申请/    软著文本
```

`node_modules`、内置 Python、`pydeps`、已打好的 Setup 不在本库。

## 开发启动（macOS / Linux）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r apps/api/requirements.txt
export PYTHONPATH="apps/api:engines/dftb_agent"
uvicorn dftbneu.main:app --host 127.0.0.1 --port 8765 --app-dir apps/api
```

浏览器打开 http://127.0.0.1:8765/

## Windows 上打 Setup

见 `源码说明.txt` 与 `packaging/windows/README.md`。国内 npm：

```bat
cd packaging\windows
npm install --registry=https://registry.npmmirror.com
node scripts\pack-win.mjs
```

产物：`packaging\windows\release\DFTB_Neu_Setup_0.3.5.exe`。发给学生用 Setup，不要发本源码库。
