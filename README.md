# DFTB-NEU 工作台

**版本 0.4.5**

[English](README.en.md)

东北大学 材料科学与工程学院  
林创 博士生  
张林 教授

面向科研与教学的 DFTB+ 本机计算工作台。学生端在本机完成结构、任务与结果查看；Windows 上的 DFTB+ 经 WSL2 部署。可选连接课堂中心，用于教学登录与密钥代理。教师端用于发布课堂并查看学习情况，不在教师机上跑计算。

密钥只放在本机 `.env`（可参考 `.env.example`），不要写入本文件或提交到仓库。

## 目录

```
apps/api/              FastAPI 服务（127.0.0.1:8765）
apps/web/              学生工作台界面
apps/teacher_web/      教师端界面
apps/classroom_hub/    课堂中心
engines/dftb_agent/    DFTB+ 任务与输入生成
packaging/windows/     Windows 学生端 / 教师端安装包
packaging/mac/         macOS 学生端
scripts/               部署与课堂辅助脚本
docs/                  学生手册、教师手册、课堂中心、DFTB 命令
templates/             能力矩阵、课程结构与 playbooks
```

`node_modules`、内置 Python、构建产物和超过 GitHub 体积限制的安装包不在本仓库中。

## 开发启动（macOS / Linux）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r apps/api/requirements.txt
export PYTHONPATH="apps/api:engines/dftb_agent"
uvicorn dftbneu.main:app --host 127.0.0.1 --port 8765 --app-dir apps/api
```

浏览器打开 http://127.0.0.1:8765/

## Windows

学生端安装后无需预装 Python。DFTB+ 仍在本机 WSL2 中运行，由应用内「部署」页引导。打包说明见 [packaging/windows/README.md](packaging/windows/README.md)。

## macOS

学生端打包与开发启动见 [packaging/mac/README.md](packaging/mac/README.md)。

## 文档

- [学生手册](docs/学生手册.md)
- [教师手册](docs/教师手册.md)
- [课堂中心](docs/课堂中心.md)
- [DFTB 命令](docs/DFTB命令.md)
