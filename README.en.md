# DFTB-NEU Workbench

**Version 0.4.5**

[中文](README.md)

Northeastern University, Shenyang  
School of Materials Science and Engineering  
Chuang Lin, PhD student  
Professor Lin Zhang

A local DFTB+ workbench for research and teaching. The student app prepares structures, runs tasks, and views results on the machine itself. On Windows, DFTB+ runs through WSL2. An optional classroom hub provides teaching login and key proxying. The teacher app publishes a class session and reviews student work; it does not run calculations.

Keep keys in a local `.env` file (see `.env.example`). Do not put them in this file or commit them.

## Layout

```
apps/api/              FastAPI server (127.0.0.1:8765)
apps/web/              Student workbench UI
apps/teacher_web/      Teacher UI
apps/classroom_hub/    Classroom hub
engines/dftb_agent/    DFTB+ tasks and input generation
packaging/windows/     Windows student and teacher installers
packaging/mac/         macOS student app
scripts/               Deploy and classroom helper scripts
docs/                  Student and teacher manuals, classroom hub, DFTB commands
templates/             Capability matrix, course structures, and playbooks
```

`node_modules`, the bundled Python runtime, build output, and installers that exceed GitHub’s file size limit are not in this repository.

## Development (macOS / Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r apps/api/requirements.txt
export PYTHONPATH="apps/api:engines/dftb_agent"
uvicorn dftbneu.main:app --host 127.0.0.1 --port 8765 --app-dir apps/api
```

Open http://127.0.0.1:8765/

## Windows

The student installer does not require a preinstalled Python. DFTB+ still runs in local WSL2, guided by the in-app Deploy page. See [packaging/windows/README.md](packaging/windows/README.md).

## macOS

See [packaging/mac/README.md](packaging/mac/README.md) for the student app build and development start.

## Documentation

- [Student manual](docs/学生手册.md)
- [Teacher manual](docs/教师手册.md)
- [Classroom hub](docs/课堂中心.md)
- [DFTB commands](docs/DFTB命令.md)
