/**
 * DFTB-NEU 工作台 — macOS Electron 壳
 * 默认走课堂中心 DeepSeek（登录后无需自配 Key）；本机可用系统 Python / 内嵌 venv。
 */
const { app, BrowserWindow, dialog, shell, Menu, ipcMain } = require("electron");
const { spawn, spawnSync, execSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

const PORT = 8765;
const APP_DATA_NAME = "DFTB工作台";

let apiProc = null;
let mainWindow = null;
let logFd = null;

function configureUserData() {
  const preferred = path.join(app.getPath("appData"), APP_DATA_NAME);
  try {
    fs.mkdirSync(preferred, { recursive: true });
    app.setPath("userData", preferred);
  } catch {
    /* ignore */
  }
}
configureUserData();

function resourcesRoot() {
  if (app.isPackaged) return process.resourcesPath;
  return path.resolve(__dirname, "../../..");
}

function backendDir() {
  if (app.isPackaged) return path.join(resourcesRoot(), "backend");
  return path.join(__dirname, "..", "backend");
}

function apiDir() {
  if (app.isPackaged) return path.join(resourcesRoot(), "api");
  return path.join(resourcesRoot(), "apps", "api");
}

function enginesDir() {
  if (app.isPackaged) return path.join(resourcesRoot(), "engines", "dftb_agent");
  return path.join(resourcesRoot(), "engines", "dftb_agent");
}

function venvPython() {
  return path.join(app.getPath("userData"), "backend-venv", "bin", "python");
}

function findSystemPython() {
  for (const cmd of ["python3", "python"]) {
    try {
      const out = execSync(`command -v ${cmd}`, { encoding: "utf8" }).trim();
      if (out && fs.existsSync(out)) return out;
    } catch {
      /* ignore */
    }
  }
  return "";
}

function ensureVenv(logPath) {
  const py = venvPython();
  if (fs.existsSync(py)) return py;
  const base = findSystemPython();
  if (!base) {
    throw Object.assign(
      new Error("未找到 python3。请先安装：brew install python@3.12"),
      { logPath },
    );
  }
  const venvDir = path.join(app.getPath("userData"), "backend-venv");
  fs.mkdirSync(path.dirname(venvDir), { recursive: true });
  const mk = spawnSync(base, ["-m", "venv", venvDir], { encoding: "utf8" });
  if (mk.status !== 0) {
    throw Object.assign(new Error(`创建虚拟环境失败：${mk.stderr || mk.stdout}`), { logPath });
  }
  const req = path.join(apiDir(), "requirements.txt");
  const pipArgs = [
    "-m",
    "pip",
    "install",
    "-i",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "--trusted-host",
    "pypi.tuna.tsinghua.edu.cn",
    "-r",
    req,
  ];
  const pip = spawnSync(py, pipArgs, { encoding: "utf8", timeout: 600000 });
  if (pip.status !== 0) {
    throw Object.assign(new Error(`安装 Python 依赖失败：${(pip.stderr || pip.stdout || "").slice(-800)}`), {
      logPath,
    });
  }
  return py;
}

function findPython(logPath) {
  if (process.env.DFTB_NEU_PYTHON && fs.existsSync(process.env.DFTB_NEU_PYTHON)) {
    return process.env.DFTB_NEU_PYTHON;
  }
  const bundled = path.join(backendDir(), "python-mac", "bin", "python3");
  if (fs.existsSync(bundled)) return bundled;
  const venvPy = path.join(backendDir(), "venv", "bin", "python");
  if (fs.existsSync(venvPy)) return venvPy;
  return ensureVenv(logPath);
}

function freeLocalPort() {
  try {
    const out = execSync(`lsof -ti tcp:${PORT} -sTCP:LISTEN || true`, { encoding: "utf8" });
    for (const pid of out.split(/\s+/).filter(Boolean)) {
      try {
        process.kill(Number(pid), "SIGTERM");
      } catch {
        /* ignore */
      }
    }
  } catch {
    /* ignore */
  }
}

function startApi() {
  const root = resourcesRoot();
  const api = apiDir();
  const userData = app.getPath("userData");
  const logPath = path.join(userData, "backend.log");
  const dataDir = path.join(userData, "data");
  fs.mkdirSync(dataDir, { recursive: true });

  if (!fs.existsSync(path.join(api, "dftbneu", "main.py"))) {
    throw Object.assign(new Error(`缺少 API：${api}`), { logPath });
  }

  const py = findPython(logPath);
  const pydeps = path.join(backendDir(), "pydeps");
  const pyPath = [api, enginesDir(), fs.existsSync(pydeps) ? pydeps : "", process.env.PYTHONPATH || ""]
    .filter(Boolean)
    .join(path.delimiter);

  try {
    if (fs.existsSync(logPath) && fs.statSync(logPath).size > 2_000_000) {
      const buf = fs.readFileSync(logPath);
      fs.writeFileSync(logPath, buf.subarray(Math.max(0, buf.length - 200_000)));
    }
  } catch {
    /* ignore */
  }
  logFd = fs.openSync(logPath, "a");
  fs.writeSync(logFd, `\n==== launch ${new Date().toISOString()} ====\n`);
  fs.writeSync(logFd, `python=${py}\napi=${api}\n`);

  freeLocalPort();

  const env = {
    ...process.env,
    PYTHONPATH: pyPath,
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
    DFTB_NEU_HOST: "127.0.0.1",
    DFTB_NEU_PORT: String(PORT),
    DFTB_NEU_DATA_DIR: dataDir,
    DFTB_NEU_ROOT: root,
    DFTB_NEU_CLASSROOM_HUB_URL:
      process.env.DFTB_NEU_CLASSROOM_HUB_URL || "https://desktop-ibhgp7g.tailcc9705.ts.net",
    DFTB_NEU_LICENSE_REQUIRED: process.env.DFTB_NEU_LICENSE_REQUIRED || "true",
    // Mac 课堂版：登录后 LLM 走课堂中心 DeepSeek，无需学生自配 Key
    DFTB_NEU_HUB_LLM_PROXY: process.env.DFTB_NEU_HUB_LLM_PROXY || "1",
  };
  delete env.DFTB_NEU_DEEPSEEK_API_KEY;
  delete env.CMATS_DEEPSEEK_API_KEY;
  delete env.DFTB_NEU_LLM_API_KEY;
  delete env.CMATS_LLM_API_KEY;

  apiProc = spawn(
    py,
    ["-m", "uvicorn", "dftbneu.main:app", "--app-dir", api, "--host", "127.0.0.1", "--port", String(PORT)],
    {
      cwd: root,
      env,
      stdio: ["ignore", logFd, logFd],
    },
  );
  apiProc.on("exit", (code, signal) => {
    try {
      fs.writeSync(logFd, `\n==== backend exit code=${code} signal=${signal} ====\n`);
    } catch {
      /* ignore */
    }
    apiProc = null;
  });
  apiProc.on("error", (e) => {
    try {
      fs.writeSync(logFd, `\n==== spawn error: ${e && e.message ? e.message : e} ====\n`);
    } catch {
      /* ignore */
    }
  });
  return logPath;
}

function waitHealth(timeoutMs = 90000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      if (!apiProc) {
        reject(new Error("本地 API 进程已退出，请查看 backend.log"));
        return;
      }
      const req = http.get(`http://127.0.0.1:${PORT}/api/health`, (res) => {
        if (res.statusCode === 200) resolve(true);
        else if (Date.now() - start > timeoutMs) reject(new Error("health timeout"));
        else setTimeout(tick, 400);
      });
      req.on("error", () => {
        if (!apiProc) {
          reject(new Error("本地 API 进程已退出，请查看 backend.log"));
          return;
        }
        if (Date.now() - start > timeoutMs) reject(new Error("API 未启动"));
        else setTimeout(tick, 400);
      });
    };
    tick();
  });
}

ipcMain.handle("ensure-wsl", async () => ({
  ok: true,
  skipped: true,
  message: "macOS 无需 WSL。请在「部署」页按提示安装 DFTB+（Homebrew / 本机工具链）。",
}));

function resolveAppIcon() {
  const candidates = [
    path.join(resourcesRoot(), "icon.icns"),
    path.join(resourcesRoot(), "icon.png"),
    path.join(__dirname, "..", "build", "icon.png"),
    path.join(__dirname, "..", "build", "icon-512.png"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return undefined;
}

async function createWindow() {
  const icon = resolveAppIcon();
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    title: "DFTB-NEU 工作台",
    autoHideMenuBar: true,
    ...(icon ? { icon } : {}),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.setMenu(null);
  await mainWindow.loadURL(`http://127.0.0.1:${PORT}/`);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

async function showFirstRunHint() {
  const marker = path.join(app.getPath("userData"), ".first-run-done");
  if (fs.existsSync(marker)) return;
  await dialog.showMessageBox({
    type: "info",
    title: "首次使用",
    message: "登录课堂后即可使用中心 DeepSeek，无需自配 Key。",
    detail: "请用学号 + 本堂密码登录。计算环境请在「部署」页按 macOS 提示完成。",
    buttons: ["继续"],
    defaultId: 0,
  });
  try {
    fs.writeFileSync(marker, new Date().toISOString(), "utf8");
  } catch {
    /* ignore */
  }
}

async function showStartError(err) {
  const logPath = err && err.logPath;
  const detail = [
    String(err && err.message ? err.message : err),
    logPath ? `\n日志：${logPath}` : "",
    "",
    "请确认已安装 Python 3（brew install python@3.12），并允许首次联网安装依赖。",
  ].join("\n");
  const res = await dialog.showMessageBox({
    type: "error",
    title: "无法启动",
    message: "本地服务未能启动",
    detail,
    buttons: logPath ? ["打开日志所在文件夹", "确定"] : ["确定"],
    defaultId: logPath ? 1 : 0,
  });
  if (logPath && res.response === 0) {
    try {
      if (fs.existsSync(logPath)) shell.showItemInFolder(logPath);
      else shell.openPath(path.dirname(logPath));
    } catch {
      /* ignore */
    }
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

app.whenReady().then(async () => {
  if (!gotLock) return;
  Menu.setApplicationMenu(null);
  let logPath = "";
  try {
    logPath = startApi();
    await waitHealth();
  } catch (e) {
    e.logPath = e.logPath || logPath;
    await showStartError(e);
    app.quit();
    return;
  }
  await showFirstRunHint();
  await createWindow();
});

app.on("window-all-closed", () => {
  if (apiProc) {
    try {
      apiProc.kill();
    } catch {
      /* ignore */
    }
  }
  if (logFd != null) {
    try {
      fs.closeSync(logFd);
    } catch {
      /* ignore */
    }
  }
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
