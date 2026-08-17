const { app, BrowserWindow, Menu, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");

function webRoot() {
  if (app.isPackaged) return path.join(process.resourcesPath, "teacher_web");
  return path.resolve(__dirname, "../../../apps/teacher_web");
}

function readTeacherConfig() {
  const cfgPath = path.join(webRoot(), "config.json");
  let hubUrl = "";
  let teacherPassword = "";
  try {
    if (fs.existsSync(cfgPath)) {
      const raw = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
      hubUrl = String((raw && raw.hubUrl) || "").trim();
      teacherPassword = String((raw && raw.teacherPassword) || "").trim();
    }
  } catch {
    /* ignore */
  }
  // 打包/运维：环境变量优先
  if (process.env.DFTB_CLASS_HUB_URL) {
    hubUrl = String(process.env.DFTB_CLASS_HUB_URL).trim();
  }
  if (process.env.DFTB_CLASS_TEACHER_PASSWORD) {
    teacherPassword = String(process.env.DFTB_CLASS_TEACHER_PASSWORD).trim();
  }
  // 与课堂中心默认永久密码一致；可在教师端界面修改并写回 config.json
  if (!teacherPassword) teacherPassword = "zl303@";
  return {
    hubUrl: hubUrl.replace(/\/$/, ""),
    teacherPassword,
  };
}

ipcMain.handle("teacher-config", () => readTeacherConfig());

ipcMain.handle("teacher-set-password", (_evt, password) => {
  const pwd = String(password || "").trim();
  if (!pwd) return { ok: false, message: "密码为空" };
  const cfgPath = path.join(webRoot(), "config.json");
  let cfg = {};
  try {
    if (fs.existsSync(cfgPath)) {
      cfg = JSON.parse(fs.readFileSync(cfgPath, "utf8") || "{}") || {};
    }
  } catch {
    cfg = {};
  }
  cfg.teacherPassword = pwd;
  if (!cfg.hubUrl) {
    const cur = readTeacherConfig();
    if (cur.hubUrl) cfg.hubUrl = cur.hubUrl;
  }
  fs.mkdirSync(path.dirname(cfgPath), { recursive: true });
  fs.writeFileSync(cfgPath, `${JSON.stringify(cfg, null, 2)}\n`, "utf8");
  return { ok: true, teacherPassword: pwd };
});

function createWindow() {
  const win = new BrowserWindow({
    width: 1000,
    height: 720,
    title: "DFTB-NEU 教师端",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });
  win.setMenuBarVisibility(false);
  win.setMenu(null);
  win.loadFile(path.join(webRoot(), "index.html"));
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
