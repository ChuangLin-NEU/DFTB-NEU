# DFTB 工作台 — macOS 学生端

课堂版：登录服务中心后 **LLM 默认走课堂中心 DeepSeek**，学生无需自配 Key。  
（Windows 学生端仍为本地 Key；本 Mac 壳通过 `DFTB_NEU_HUB_LLM_PROXY=1` 打开中心代理。）

## 在 Mac 上打包（需本机 macOS）

```bash
cd packaging/mac/electron
npm install --registry=https://registry.npmmirror.com
npm run dist
```

产物：`packaging/mac/electron/dist/DFTB_Neu_Mac_0.3.5_*.dmg`（及 zip）

首次运行会用系统 `python3` 在用户目录创建 venv，并从清华源安装依赖（需联网一次）。

前置：`brew install python@3.12`（或系统已有 Python 3.10+）

## 开发启动

```bash
cd packaging/mac/electron
npm install --registry=https://registry.npmmirror.com
npm start
```

## 说明

- 课堂中心地址预置为 Funnel 公网地址，可用环境变量 `DFTB_NEU_CLASSROOM_HUB_URL` 覆盖。
- 关闭中心 LLM：启动前 `export DFTB_NEU_HUB_LLM_PROXY=0`。
- 未签名：首次打开若被拦截，请在「系统设置 → 隐私与安全性」允许，或执行  
  `xattr -cr "/Applications/DFTB-NEU 工作台.app"`。
