# DFTB 工作台（dftb-neu）

DFTB+ 本机计算客户端，面向科研与教学。Windows 上经 WSL2 隔离部署；可选接入服务中心做教学登录与密钥代理。

## 目录

```
apps/api/          # FastAPI（127.0.0.1）
apps/web/          # 工作台 UI
engines/dftb_agent/
packaging/windows/ # Electron + 现代纸面 Setup
scripts/wsl_deploy_dftb.sh
docs/              # 手册与命令说明
templates/         # 能力矩阵与 playbooks
```

## 开发启动（macOS / Linux）

```bash
cd /Users/mu/Projects/dftb-neu
python3 -m venv .venv && source .venv/bin/activate
pip install -r apps/api/requirements.txt
export PYTHONPATH="apps/api:engines/dftb_agent"
uvicorn dftbneu.main:app --host 127.0.0.1 --port 8765 --app-dir apps/api
```

浏览器打开 http://127.0.0.1:8765/

## Windows 安装包

见 [packaging/windows/README.md](packaging/windows/README.md)。
