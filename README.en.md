# DFTB-NEU

[中文](README.md)

Local DFTB+ client (Windows source, v0.3.5) for research and classroom use. On Windows, DFTB+ is deployed through WSL2. A teaching login service is optional.

This repository is private. Local settings and keys live in the corresponding files (`.env` and similar). Do not paste key material into this file. Software-copyright application files are under `软件著作权申请/`.

## Layout

```
apps/api/          FastAPI (127.0.0.1)
apps/web/          UI
engines/dftb_agent/
packaging/windows/ Electron and Setup
scripts/           WSL deploy and helpers
docs/              Teacher/student manuals, DFTB commands
templates/         Capabilities and playbooks
软件著作权申请/    Copyright filing text
```

`node_modules`, bundled Python, `pydeps`, and built Setup files are not in this repository.

## Development (macOS / Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r apps/api/requirements.txt
export PYTHONPATH="apps/api:engines/dftb_agent"
uvicorn dftbneu.main:app --host 127.0.0.1 --port 8765 --app-dir apps/api
```

Open http://127.0.0.1:8765/

## Windows Setup build

See `源码说明.txt` and `packaging/windows/README.md`. Mainland npm:

```bat
cd packaging\windows
npm install --registry=https://registry.npmmirror.com
node scripts\pack-win.mjs
```

Output: `packaging\windows\release\DFTB_Neu_Setup_0.3.5.exe`. Give students the Setup, not this source tree.
