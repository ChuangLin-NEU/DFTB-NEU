/**
 * DFTB 宸ヤ綔鍙?路 鐜颁唬瀹夎鍣紙绾搁潰鏃犺竟妗嗭級
 * 鍦?Windows 涓婇伩鍏?Node fs.cpSync 鐨?ENOTDIR锛氭竻绌虹洰鏍囧悗鐩存帴 PowerShell 瑙ｅ帇銆? */
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const ROLE = process.env.DFTB_SETUP_ROLE || "student"; // student | teacher
const IS_TEACHER = ROLE === "teacher";
const APP_NAME = IS_TEACHER ? "DFTB鏁欏笀绔? : "DFTB宸ヤ綔鍙?;
const EXE_NAME = IS_TEACHER ? "DFTB鏁欏笀绔?exe" : "DFTB宸ヤ綔鍙?exe";
const DONE_NOTE = IS_TEACHER
  ? "瀹夎瀹屾垚銆傛墦寮€鍚庡嵆鍙彂甯冩湰鍫傚瘑鐮佸苟鐩戠鍦ㄧ嚎鐢ㄦ埛銆?
  : "瀹夎瀹屾垚銆傛墦寮€鍚庤鍏堛€岄儴缃插埌鏈満銆嶏紱鏁欏鍦烘櫙鍐嶇櫥褰曟湇鍔′腑蹇冦€?;

function payloadZip() {
  const candidates = [
    path.join(process.resourcesPath, "payload", "app.zip"),
    path.join(path.dirname(process.execPath), "resources", "payload", "app.zip"),
    path.join(__dirname, "..", "resources", "payload", "app.zip"),
  ];
  for (const p of candidates) {
    try {
      if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
    } catch {
      /* ignore */
    }
  }
  return candidates[0];
}

function defaultInstallDir() {
  const local =
    process.env.LOCALAPPDATA ||
    path.join(os.homedir(), "AppData", "Local");
  return path.join(local, "Programs", APP_NAME);
}

/** 鏄惁涓虹洏绗︽牴锛圕:\ / E:\锛夛紝涓嶅彲瀵瑰叾 mkdir銆?*/
function isDriveRoot(p) {
  const s = path.resolve(String(p || "")).replace(/\//g, "\\");
  return /^[a-zA-Z]:\\$/.test(s);
}

/** 瑙勮寖鍖栧畨瑁呯洰褰曪細鏀寔 D: / E:\ / 浠绘剰闈?C 鐩樿矾寰勩€?*/
function normalizeInstallDir(raw) {
  let d = String(raw || "").trim().replace(/\//g, "\\");
  if (!d) d = defaultInstallDir();
  // E: 鎴?E:\ 鈫?E:\APP_NAME锛堥伩鍏?path.join('E:','x') 鍙樻垚 E:x 鐩稿璺緞锛?  if (/^[a-zA-Z]:\\?$/.test(d)) {
    d = `${d[0]}:\\${APP_NAME}`;
  } else if (/^[a-zA-Z]:[^\\/]/.test(d)) {
    d = `${d[0]}:\\${d.slice(2)}`;
  }
  d = path.resolve(d);
  if (isDriveRoot(d)) d = path.join(d, APP_NAME);
  return d;
}

/** 纭繚鐖剁洰褰曞瓨鍦紱鐩樼鏍瑰凡瀛樺湪鍒欒烦杩囷紝閬垮厤 EPERM mkdir 'E:\'銆?*/
function ensureParentDir(target) {
  const parent = path.dirname(path.resolve(target));
  if (!parent || parent === path.resolve(target) || isDriveRoot(parent)) return;
  fs.mkdirSync(parent, { recursive: true });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 440,
    height: 580,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    frame: false,
    backgroundColor: "#f7f5f1",
    title: `${APP_NAME} 瀹夎`,
    icon: path.join(__dirname, "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, "index.html"));
}

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      ...opts,
    });
    let err = "";
    let out = "";
    child.stderr.on("data", (d) => {
      err += d.toString();
    });
    child.stdout.on("data", (d) => {
      out += d.toString();
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0 || (opts.acceptCodes || []).includes(code)) resolve({ code, out, err });
      else reject(new Error((err || out).trim() || `${cmd} 閫€鍑虹爜 ${code}`));
    });
  });
}

/** 娓呯┖鎴栫Щ闄よ矾寰勶紙鏂囦欢鎴栫洰褰曞潎鍙級 */
function removePath(target) {
  if (!fs.existsSync(target)) return;
  fs.rmSync(target, { recursive: true, force: true });
}

async function extractZipTo(zipPath, destDir) {
  if (!fs.existsSync(zipPath) || !fs.statSync(zipPath).isFile()) {
    throw new Error(`瀹夎鍖呰祫婧愭棤鏁堬細${zipPath}`);
  }
  // 鍏堝垹鎺夌洰鏍囷紙鍙兘鏄笂娆℃畫鐣欑殑鏂囦欢/鍗婃埅鐩綍锛夛紝鍐嶈В鍘?  removePath(destDir);
  ensureParentDir(destDir);
  const ps = [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    [
      "Add-Type -AssemblyName System.IO.Compression.FileSystem",
      "if (Test-Path -LiteralPath $env:QS_DEST) { Remove-Item -LiteralPath $env:QS_DEST -Recurse -Force }",
      "New-Item -ItemType Directory -Path $env:QS_DEST -Force | Out-Null",
      "if (-not (Test-Path -LiteralPath $env:QS_ZIP -PathType Leaf)) { throw \"zip 涓嶆槸鏂囦欢: $env:QS_ZIP\" }",
      "[System.IO.Compression.ZipFile]::ExtractToDirectory($env:QS_ZIP, $env:QS_DEST)",
    ].join("; "),
  ];
  await run("powershell.exe", ps, {
    env: { ...process.env, QS_ZIP: zipPath, QS_DEST: destDir },
  });
}

function looksLikeMainExe(name) {
  if (!name.toLowerCase().endsWith(".exe")) return false;
  if (name === EXE_NAME) return true;
  if (IS_TEACHER) {
    return /DFTB|璇惧爞鏁欏笀/i.test(name) && !/install|setup|uninstall/i.test(name);
  }
  return /DFTB|宸ヤ綔鍙?i.test(name) && !/install|setup|uninstall|鏁欏笀/i.test(name);
}

function findAppRoot(extractRoot) {
  if (!fs.existsSync(extractRoot) || !fs.statSync(extractRoot).isDirectory()) {
    throw new Error(`瑙ｅ帇鐩綍鏃犳晥锛?{extractRoot}`);
  }
  const queue = [{ dir: extractRoot, depth: 0 }];
  while (queue.length) {
    const { dir, depth } = queue.shift();
    let entries = [];
    try {
      if (!fs.statSync(dir).isDirectory()) continue;
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (e) {
      if (e && e.code === "ENOTDIR") continue;
      continue;
    }
    for (const ent of entries) {
      const full = path.join(dir, ent.name);
      if (ent.isFile() && looksLikeMainExe(ent.name)) return dir;
      if (ent.isDirectory() && depth < 3 && ent.name !== "locales") {
        queue.push({ dir: full, depth: depth + 1 });
      }
    }
  }
  throw new Error(`鏈壘鍒?${EXE_NAME}`);
}

function resolveMainExeName(appRoot) {
  const names = fs.readdirSync(appRoot).filter((n) => n.toLowerCase().endsWith(".exe"));
  if (names.includes(EXE_NAME)) return EXE_NAME;
  const hit = names.find((n) => looksLikeMainExe(n));
  if (hit) return hit;
  throw new Error(`瀹夎鐩綍涓棤涓荤▼搴忥細${names.join(", ") || "(绌?"}`);
}

function writeShortcut(lnkPath, exePath, workDir, iconPath) {
  const ps = `
$WshShell = New-Object -ComObject WScript.Shell
$dir = Split-Path -Parent $env:QS_LNK
if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$s = $WshShell.CreateShortcut($env:QS_LNK)
$s.TargetPath = $env:QS_EXE
$s.WorkingDirectory = $env:QS_DIR
$s.IconLocation = "$env:QS_ICO,0"
$s.Description = $env:QS_NAME
$s.Save()
`;
  return run("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], {
    env: {
      ...process.env,
      QS_LNK: lnkPath,
      QS_EXE: exePath,
      QS_DIR: workDir,
      QS_ICO: iconPath || exePath,
      QS_NAME: APP_NAME,
    },
  });
}

function ensureInstallIcon(installDir) {
  const dest = path.join(installDir, "icon.ico");
  const candidates = [
    path.join(installDir, "icon.ico"),
    path.join(installDir, "resources", "icon.ico"),
    path.join(__dirname, "icon.ico"),
  ];
  for (const src of candidates) {
    try {
      if (fs.existsSync(src) && fs.statSync(src).isFile()) {
        if (path.resolve(src) !== path.resolve(dest)) fs.copyFileSync(src, dest);
        return dest;
      }
    } catch {
      /* ignore */
    }
  }
  return "";
}

function desktopDir() {
  const home = os.homedir();
  for (const name of ["Desktop", "妗岄潰"]) {
    const p = path.join(home, name);
    if (fs.existsSync(p) && fs.statSync(p).isDirectory()) return p;
  }
  return path.join(home, "Desktop");
}

ipcMain.handle("setup:meta", () => {
  let version = "0.1.0";
  try {
    version = require("./package.json").version;
  } catch {
    version = app.getVersion();
  }
  const zip = payloadZip();
  let hasPayload = false;
  try {
    hasPayload = fs.existsSync(zip) && fs.statSync(zip).isFile();
  } catch {
    hasPayload = false;
  }
  return {
    appName: APP_NAME,
    version,
    defaultDir: defaultInstallDir(),
    hasPayload,
  };
});

ipcMain.handle("setup:pickDir", async (e, current) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  const res = await dialog.showOpenDialog(win, {
    title: "閫夋嫨瀹夎璺緞",
    defaultPath: current || defaultInstallDir(),
    properties: ["openDirectory", "createDirectory"],
  });
  if (res.canceled || !res.filePaths[0]) return null;
  const picked = res.filePaths[0];
  const base = path.basename(String(picked).replace(/[\\/]+$/, ""));
  // 閫変腑鐩樼鏍规垨鏅€氭枃浠跺す鏃讹紝鑷姩濂椾竴灞傚簲鐢ㄧ洰褰?  let target = picked;
  if (!(base === APP_NAME || /DFTB|璇惧爞/i.test(base))) {
    target = path.join(picked, APP_NAME);
  }
  return normalizeInstallDir(target);
});

ipcMain.handle("setup:install", async (e, opts) => {
  const send = (payload) => {
    try {
      e.sender.send("setup:progress", payload);
    } catch {
      /* ignore */
    }
  };
  const installDir = normalizeInstallDir(opts?.installDir || defaultInstallDir());
  const createDesktop = opts?.desktop !== false;
  const zip = payloadZip();
  if (!fs.existsSync(zip) || !fs.statSync(zip).isFile()) {
    throw new Error(`缂哄皯瀹夎鍖呰祫婧愶紙鏈熸湜 zip 鏂囦欢锛夛細${zip}`);
  }

  send({ pct: 8, message: "鍑嗗瀹夎鐩綍鈥? });
  // 鍕垮鐩樼鏍?mkdir锛圗:\ 浼?EPERM锛夛紱鍙繚璇佺埗鐩綍瀛樺湪
  ensureParentDir(installDir);
  // 鑻ョ洰鏍囨槸鏂囦欢鎴栧崐鎴洰褰曪紝鏁存鍒犻櫎
  removePath(installDir);

  const staging = path.join(os.tmpdir(), `dftb-setup-${ROLE}-${Date.now()}`);
  try {
    send({ pct: 18, message: "姝ｅ湪瑙ｅ帇绋嬪簭鏂囦欢鈥? });
    await extractZipTo(zip, staging);

    send({ pct: 52, message: "姝ｅ湪鍐欏叆瀹夎鐩綍鈥? });
    const extractedRoot = findAppRoot(staging);
    const mainExeName = resolveMainExeName(extractedRoot);

    // 鐩存帴瑙ｅ帇缁撴灉鐩綍 鈫?瀹夎鐩綍锛圥owerShell 鎷疯礉锛岄伩鍏?Node cpSync ENOTDIR锛?    removePath(installDir);
    await run(
      "powershell.exe",
      [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Copy-Item -LiteralPath $env:QS_SRC -Destination $env:QS_DEST -Recurse -Force",
      ],
      { env: { ...process.env, QS_SRC: extractedRoot, QS_DEST: installDir } },
    );

    const exePath = path.join(installDir, EXE_NAME);
    const actualExe = path.join(installDir, mainExeName);
    if (!fs.existsSync(actualExe)) {
      throw new Error(`瀹夎鍚庢湭鎵惧埌涓荤▼搴忥細${mainExeName}锛堢洰褰曪細${installDir}锛塦);
    }
    if (mainExeName !== EXE_NAME) fs.copyFileSync(actualExe, exePath);
    if (!fs.existsSync(exePath)) throw new Error("瀹夎鍚庢湭鎵惧埌涓荤▼搴?);

    const iconPath = ensureInstallIcon(installDir) || exePath;
    send({ pct: 72, message: "鍒涘缓蹇嵎鏂瑰紡鈥? });
    const startMenu = path.join(
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"),
      "Microsoft",
      "Windows",
      "Start Menu",
      "Programs",
      `${APP_NAME}.lnk`,
    );
    await writeShortcut(startMenu, exePath, installDir, iconPath);
    if (createDesktop) {
      await writeShortcut(path.join(desktopDir(), `${APP_NAME}.lnk`), exePath, installDir, iconPath);
    }

    send({ pct: 100, message: "瀹夎瀹屾垚" });
    return {
      ok: true,
      installDir,
      exePath,
      networkMessage: DONE_NOTE,
    };
  } catch (err) {
    const msg = err && err.message ? err.message : String(err);
    const code = err && err.code ? ` [${err.code}]` : "";
    throw new Error(`${msg}${code}\n鐩爣锛?{installDir}\n璧勬簮锛?{zip}`);
  } finally {
    try {
      removePath(staging);
    } catch {
      /* ignore */
    }
  }
});

ipcMain.handle("setup:launch", async (_e, exePath) => {
  if (!exePath || !fs.existsSync(exePath)) throw new Error("涓荤▼搴忎笉瀛樺湪");
  await shell.openPath(exePath);
  return true;
});

ipcMain.on("setup:window", (_e, action) => {
  const win = BrowserWindow.getFocusedWindow() || BrowserWindow.getAllWindows()[0];
  if (!win) return;
  if (action === "minimize") win.minimize();
  if (action === "close") win.close();
});

app.whenReady().then(createWindow);
app.on("window-all-closed", () => app.quit());
