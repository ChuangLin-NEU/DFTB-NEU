/**
 * DFTB-NEU 工作台 — Windows Electron 壳
 * 使用安装包内嵌的 Windows Python + pydeps 启动本机 API，目标机无需预装 Python。
 */
const { app, BrowserWindow, dialog, shell, Menu, ipcMain } = require("electron");
const { spawn } = require("child_process");
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

/** 打包后：resources/；开发：仓库根 */
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

function findPython() {
  if (process.env.DFTB_NEU_PYTHON && fs.existsSync(process.env.DFTB_NEU_PYTHON)) {
    return process.env.DFTB_NEU_PYTHON;
  }
  const bundled = path.join(backendDir(), "python-win", "python.exe");
  if (fs.existsSync(bundled)) return bundled;
  return "";
}

/** 清理占用 8765 的旧后端，避免「双击无窗口 / 连到僵尸进程」。 */
function freeLocalPort() {
  if (process.platform !== "win32") return;
  try {
    const out = require("child_process").execSync("netstat -ano", { encoding: "utf8" });
    const pids = new Set();
    for (const line of out.split(/\r?\n/)) {
      if (!/127\.0\.0\.1:8765/.test(line) || !/LISTENING/i.test(line)) continue;
      const m = line.trim().split(/\s+/).pop();
      if (m && /^\d+$/.test(m) && m !== "0") pids.add(m);
    }
    for (const pid of pids) {
      try {
        require("child_process").execSync(`taskkill /F /PID ${pid}`, { stdio: "ignore" });
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
  const py = findPython();
  const api = apiDir();
  const pydeps = path.join(backendDir(), "pydeps");
  const userData = app.getPath("userData");
  const logPath = path.join(userData, "backend.log");
  const dataDir = path.join(userData, "data");
  fs.mkdirSync(dataDir, { recursive: true });

  if (!py) {
    throw Object.assign(new Error("安装包缺少内置 Python（backend/python-win）。请重新安装 Setup。"), {
      logPath,
    });
  }
  if (!fs.existsSync(path.join(api, "dftbneu", "main.py"))) {
    throw Object.assign(new Error(`缺少 API：${api}`), { logPath });
  }
  if (!fs.existsSync(path.join(api, "dftbneu", "routers", "courses.py"))) {
    throw Object.assign(
      new Error("安装不完整：缺少 courses 路由。请用最新 Setup 覆盖安装。"),
      { logPath },
    );
  }
  if (!fs.existsSync(pydeps)) {
    throw Object.assign(new Error("安装包缺少 Python 依赖（backend/pydeps）。请重新安装 Setup。"), {
      logPath,
    });
  }

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
  fs.writeSync(logFd, `python=${py}\napi=${api}\npydeps=${pydeps}\n`);

  freeLocalPort();

  const env = {
    ...process.env,
    PYTHONPATH: [pydeps, api, enginesDir(), process.env.PYTHONPATH || ""].filter(Boolean).join(path.delimiter),
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
    DFTB_NEU_HOST: "127.0.0.1",
    DFTB_NEU_PORT: String(PORT),
    DFTB_NEU_DATA_DIR: dataDir,
    DFTB_NEU_ROOT: root,
    // 课堂服务（预置地址）；强制学号+本堂密码登录
    // 公网课堂中心（学生无需 Tailscale）；运维可用环境变量覆盖
    DFTB_NEU_CLASSROOM_HUB_URL: process.env.DFTB_NEU_CLASSROOM_HUB_URL || "https://desktop-ibhgp7g.tailcc9705.ts.net",
    DFTB_NEU_LICENSE_REQUIRED: process.env.DFTB_NEU_LICENSE_REQUIRED || "true",
    // 学生端默认不经课堂中心调用 DeepSeek；MP 结构仍可走中心代理
    DFTB_NEU_HUB_LLM_PROXY: process.env.DFTB_NEU_HUB_LLM_PROXY || "0",
  };
  // 避免把打包机/开发机残留的 DeepSeek Key 带进学生进程
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
      windowsHide: true,
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

function waitHealth(timeoutMs = 45000) {
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

/** 提权启动 WSL2 / Ubuntu 安装（弹出 UAC，不要求用户手敲命令） */
function ensureWslElevated() {
  return new Promise((resolve) => {
    if (process.platform !== "win32") {
      resolve({ ok: true, skipped: true, message: "非 Windows，无需启用 WSL。" });
      return;
    }
    // Start-Process -Verb RunAs：用户确认 UAC 后由系统执行 wsl --install
    const ps =
      "Start-Process -FilePath wsl.exe -ArgumentList '--install','-d','Ubuntu' -Verb RunAs";
    const child = spawn(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
      { windowsHide: true },
    );
    let stderr = "";
    child.stderr.on("data", (d) => {
      stderr += d.toString();
    });
    child.on("close", (code) => {
      if (code === 0) {
        resolve({
          ok: true,
          message:
            "已请求启用 WSL2。请在管理员确认框中允许；安装完成后若系统要求重启，重启后再点一次「部署到本机」。",
        });
      } else {
        resolve({
          ok: false,
          cancelled: true,
          message:
            "未能启动 WSL 安装（可能取消了管理员确认）。请再次点击「部署到本机」。",
          code,
          stderr: stderr.slice(-400),
        });
      }
    });
    child.on("error", (e) => {
      resolve({ ok: false, message: String(e && e.message ? e.message : e) });
    });
  });
}

ipcMain.handle("ensure-wsl", () => ensureWslElevated());

function resolveAppIcon() {
  const candidates = [
    path.join(resourcesRoot(), "icon.ico"),
    path.join(path.dirname(process.execPath), "icon.ico"),
    path.join(__dirname, "..", "build", "icon-student.ico"),
    path.join(__dirname, "..", "build", "icon.ico"),
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
    message: "打开「部署」页，点击「部署到本机」。",
    detail:
      "该按钮会自动启用 WSL2（需确认管理员权限），并在本机用户目录隔离安装 DFTB+。若系统提示重启，重启后再点一次即可。",
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
    "请确认使用官方 Setup 安装，且未删除安装目录中的 backend 文件夹。",
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

// 已有实例时聚焦，避免多次双击堆出无窗口僵尸进程
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
