/**
 * DFTB 工作台 · 现代安装器（纸面无边框）
 * 在 Windows 上避免 Node fs.cpSync 的 ENOTDIR：清空目标后直接 PowerShell 解压。
 */
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const ROLE = "student"; // student | teacher
const IS_TEACHER = ROLE === "teacher";
const APP_NAME = IS_TEACHER ? "DFTB教师端" : "DFTB工作台";
const EXE_NAME = IS_TEACHER ? "DFTB教师端.exe" : "DFTB工作台.exe";
const DONE_NOTE = IS_TEACHER
  ? "安装完成。打开后即可发布本堂密码并监管在线用户。"
  : "安装完成。打开后请先「部署到本机」；教学场景再登录服务中心。";

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

/** 是否为盘符根（C:\ / E:\），不可对其 mkdir。 */
function isDriveRoot(p) {
  const s = path.resolve(String(p || "")).replace(/\//g, "\\");
  return /^[a-zA-Z]:\\$/.test(s);
}

/** 规范化安装目录：支持 D: / E:\ / 任意非 C 盘路径。 */
function normalizeInstallDir(raw) {
  let d = String(raw || "").trim().replace(/\//g, "\\");
  if (!d) d = defaultInstallDir();
  // E: 或 E:\ → E:\APP_NAME（避免 path.join('E:','x') 变成 E:x 相对路径）
  if (/^[a-zA-Z]:\\?$/.test(d)) {
    d = `${d[0]}:\\${APP_NAME}`;
  } else if (/^[a-zA-Z]:[^\\/]/.test(d)) {
    d = `${d[0]}:\\${d.slice(2)}`;
  }
  d = path.resolve(d);
  if (isDriveRoot(d)) d = path.join(d, APP_NAME);
  return d;
}

/** 确保父目录存在；盘符根已存在则跳过，避免 EPERM mkdir 'E:\'。 */
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
    show: false,
    backgroundColor: "#eef4f6",
    title: `${APP_NAME} 安装`,
    icon: path.join(__dirname, "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  win.setMenuBarVisibility(false);
  win.once("ready-to-show", () => {
    win.show();
    win.focus();
  });
  win.loadFile(path.join(__dirname, "index.html")).catch((err) => {
    dialog.showErrorBox("安装界面加载失败", String(err && err.message ? err.message : err));
    app.quit();
  });
}

// 尽早弹出可见反馈，避免「双击无反应」被误判
process.on("uncaughtException", (err) => {
  try {
    fs.appendFileSync(
      path.join(os.tmpdir(), `dftb-setup-${ROLE}-crash.log`),
      `${new Date().toISOString()} ${err && err.stack ? err.stack : err}\n`,
      "utf8",
    );
  } catch {
    /* ignore */
  }
  try {
    dialog.showErrorBox("安装程序异常", String(err && err.message ? err.message : err));
  } catch {
    /* ignore */
  }
});

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
      else reject(new Error((err || out).trim() || `${cmd} 退出码 ${code}`));
    });
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 结束占用安装目录的旧进程（工作台/教师端及其子进程）。 */
async function stopInstallTargets(installDir) {
  const dir = path.resolve(String(installDir || ""));
  // 历史/现用主程序名不一致：DFTB工作台.exe ↔ DFTB-NEU 工作台.exe
  const images = [
    EXE_NAME,
    "DFTB工作台.exe",
    "DFTB-NEU 工作台.exe",
    "DFTB-NEU工作台.exe",
    "DFTB教师端.exe",
    "DFTB-NEU 教师端.exe",
    "dftb-neu.exe",
  ];
  for (const img of [...new Set(images)]) {
    try {
      await run("taskkill.exe", ["/F", "/IM", img, "/T"], { acceptCodes: [0, 128, 255] });
    } catch {
      /* ignore */
    }
  }
  // 再按路径/进程名杀掉仍挂在安装目录下的进程（含嵌入 python、历史主程序名）
  const ps = [
    "$ErrorActionPreference='SilentlyContinue'",
    `$root = [IO.Path]::GetFullPath(${JSON.stringify(dir)})`,
    "Get-Process | Where-Object {",
    "  $_.ProcessName -match 'DFTB|dftb-neu' -and $_.ProcessName -notmatch 'Setup'",
    "} | Stop-Process -Force",
    "if (-not $root) { return }",
    "Get-CimInstance Win32_Process | ForEach-Object {",
    "  $exe = [string]($_.ExecutablePath)",
    "  $cmd = [string]($_.CommandLine)",
    "  $hit = $false",
    "  if ($exe -and $exe.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { $hit = $true }",
    "  if (-not $hit -and $cmd -and $cmd.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $hit = $true }",
    "  if ($hit -and $_.ProcessId -gt 0 -and $_.Name -notmatch 'Setup') { Stop-Process -Id $_.ProcessId -Force }",
    "}",
  ].join("; ");
  try {
    await run(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
      { acceptCodes: [0, 1] },
    );
  } catch {
    /* ignore */
  }
  await sleep(800);
}

/** 清空或移除路径；默认 soft：清不掉也不抛（覆盖安装靠就地写入）。 */
async function removePath(target, { retries = 8, soft = true } = {}) {
  const p = path.resolve(String(target || ""));
  if (!p || !fs.existsSync(p)) return true;
  let lastErr = null;
  for (let i = 0; i < retries; i++) {
    try {
      fs.rmSync(p, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
      if (!fs.existsSync(p)) return true;
    } catch (err) {
      lastErr = err;
    }
    try {
      await run("cmd.exe", ["/c", "rd", "/s", "/q", p], { acceptCodes: [0, 1, 2] });
      if (!fs.existsSync(p)) return true;
    } catch (err) {
      lastErr = err;
    }
    try {
      const tomb = `${p}.old-${Date.now()}-${i}`;
      if (fs.existsSync(p)) fs.renameSync(p, tomb);
      try {
        fs.rmSync(tomb, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
      } catch {
        try {
          await run("cmd.exe", ["/c", "rd", "/s", "/q", tomb], { acceptCodes: [0, 1, 2] });
        } catch {
          /* 改名成功即可 */
        }
      }
      if (!fs.existsSync(p)) return true;
    } catch (err) {
      lastErr = err;
    }
    await sleep(350 + i * 200);
  }
  if (soft) return false;
  const code = lastErr && lastErr.code ? lastErr.code : "EBUSY";
  throw new Error(
    `无法清理临时目录（${code}）。\n路径：${p}`,
  );
}

/** 把单个文件挪成 .old-*，便于写入同名新文件（应对 app.asar 被杀软/索引锁住）。 */
function tombstoneFile(filePath) {
  const p = path.resolve(String(filePath || ""));
  if (!p || !fs.existsSync(p)) return true;
  for (let i = 0; i < 4; i++) {
    const tomb = `${p}.old-${Date.now()}-${i}`;
    try {
      fs.renameSync(p, tomb);
      // 后台尽力删；删不掉也不影响安装
      setTimeout(() => {
        try {
          fs.rmSync(tomb, { force: true });
        } catch {
          /* ignore */
        }
      }, 0);
      return true;
    } catch {
      /* retry */
    }
  }
  return !fs.existsSync(p);
}

function canReplaceFile(filePath) {
  const p = path.resolve(String(filePath || ""));
  if (!fs.existsSync(p)) return true;
  try {
    const fd = fs.openSync(p, "r+");
    fs.closeSync(fd);
    return true;
  } catch {
    return tombstoneFile(p);
  }
}

/**
 * 准备安装目标：优先整目录改名挪走；失败则就地覆盖。
 * 返回 { ready: true } 或 { ready: false, reason }（关键文件仍被锁）。
 */
async function prepareInstallDir(installDir) {
  const p = path.resolve(String(installDir || ""));
  if (!p) return { ready: true };
  ensureParentDir(p);
  if (!fs.existsSync(p)) {
    fs.mkdirSync(p, { recursive: true });
    return { ready: true };
  }
  // 1) 整目录改名挪走（最干净）
  for (let i = 0; i < 3; i++) {
    const tomb = `${p}.old-${Date.now()}-${i}`;
    try {
      fs.renameSync(p, tomb);
      setTimeout(() => {
        removePath(tomb, { retries: 2, soft: true }).catch(() => {});
      }, 0);
      fs.mkdirSync(p, { recursive: true });
      return { ready: true };
    } catch {
      await sleep(200 + i * 150);
    }
  }
  // 2) 整目录删不掉：把常见锁文件先改名，再 soft 清理
  const lockCandidates = [
    path.join(p, "resources", "app.asar"),
    path.join(p, "resources", "app.asar.unpacked"),
    path.join(p, EXE_NAME),
    path.join(p, "DFTB工作台.exe"),
    path.join(p, "DFTB-NEU 工作台.exe"),
    path.join(p, "DFTB教师端.exe"),
    path.join(p, "DFTB-NEU 教师端.exe"),
  ];
  for (const f of lockCandidates) tombstoneFile(f);
  await removePath(p, { retries: 3, soft: true });
  if (!fs.existsSync(p)) {
    fs.mkdirSync(p, { recursive: true });
    return { ready: true };
  }
  const asar = path.join(p, "resources", "app.asar");
  if (fs.existsSync(asar) && !canReplaceFile(asar)) {
    return { ready: false, reason: "app.asar 被占用" };
  }
  return { ready: true };
}

function installLooksComplete(dir, extractedRoot) {
  const root = path.resolve(dir);
  if (!fs.existsSync(path.join(root, EXE_NAME))) {
    // 允许解压名与规范名不同，稍后会复制
    const names = fs.existsSync(root)
      ? fs.readdirSync(root).filter((n) => n.toLowerCase().endsWith(".exe"))
      : [];
    if (!names.some((n) => looksLikeMainExe(n))) return false;
  }
  const srcAsar = path.join(extractedRoot, "resources", "app.asar");
  const dstAsar = path.join(root, "resources", "app.asar");
  if (!fs.existsSync(srcAsar)) return true;
  if (!fs.existsSync(dstAsar)) return false;
  try {
    return fs.statSync(dstAsar).size === fs.statSync(srcAsar).size;
  } catch {
    return false;
  }
}

/** 写入安装文件；目标被锁时自动改用旁路干净目录。 */
async function deployAppTree(extractedRoot, preferredDir) {
  let prep = await prepareInstallDir(preferredDir);
  if (prep.ready) {
    await copyTreeInto(extractedRoot, preferredDir);
    if (installLooksComplete(preferredDir, extractedRoot)) return preferredDir;
  }

  // 旁路：旧目录关键文件锁死时，装到干净目录并改快捷方式指向这里
  const parent = path.dirname(path.resolve(preferredDir));
  const candidates = [
    path.join(parent, `${APP_NAME}-最新`),
    path.join(parent, `${APP_NAME}-${appVersion()}`),
    path.join(parent, `${APP_NAME}-${Date.now()}`),
  ];
  for (const alt of candidates) {
    if (path.resolve(alt) === path.resolve(preferredDir)) continue;
    await removePath(alt, { retries: 2, soft: true });
    if (fs.existsSync(alt)) {
      // 仍在则换下一个时间戳目录
      continue;
    }
    fs.mkdirSync(alt, { recursive: true });
    await copyTreeInto(extractedRoot, alt);
    if (installLooksComplete(alt, extractedRoot)) {
      // 尽力清旧目录；失败也无妨
      await removePath(preferredDir, { retries: 2, soft: true });
      return alt;
    }
  }
  throw new Error(
    `无法写入程序文件（旧目录可能被杀毒/索引锁定）。\n请关闭占用后重试，或手动删除：\n${preferredDir}`,
  );
}

/** 把解压结果写入安装目录；遇锁文件先改名再覆盖，不要求先清空目标。 */
async function copyTreeInto(srcDir, destDir) {
  const src = path.resolve(srcDir);
  const dest = path.resolve(destDir);
  if (!fs.existsSync(src)) throw new Error(`解压结果不存在：${src}`);
  fs.mkdirSync(dest, { recursive: true });

  // 优先 robocopy：可在目标非空时覆盖；退出码 < 8 视为成功
  try {
    const r = await run(
      "robocopy.exe",
      [src, dest, "/E", "/IS", "/IT", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
      { acceptCodes: [0, 1, 2, 3, 4, 5, 6, 7] },
    );
    if ((r.code || 0) < 8) {
      // 关键文件仍可能失败：对主程序 / asar 再补一轮
      await hardenOverwriteKeyFiles(src, dest);
      return;
    }
  } catch {
    /* fallback */
  }

  // PowerShell：逐文件；失败则 tombstone 后重试
  const ps = [
    "$ErrorActionPreference='Continue'",
    `$src = [IO.Path]::GetFullPath($env:QS_SRC)`,
    `$dest = [IO.Path]::GetFullPath($env:QS_DEST)`,
    "function Tomb([string]$p) {",
    "  if (-not (Test-Path -LiteralPath $p)) { return }",
    "  $t = \"$p.old-$(Get-Date -Format yyyyMMddHHmmssfff)\"",
    "  try { Rename-Item -LiteralPath $p -NewName (Split-Path $t -Leaf) -Force } catch {}",
    "}",
    "Get-ChildItem -LiteralPath $src -Recurse -Force | ForEach-Object {",
    "  $rel = $_.FullName.Substring($src.Length).TrimStart('\\')",
    "  $target = Join-Path $dest $rel",
    "  if ($_.PSIsContainer) {",
    "    New-Item -ItemType Directory -Force -Path $target | Out-Null",
    "  } else {",
    "    $parent = Split-Path $target -Parent",
    "    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }",
    "    try {",
    "      Copy-Item -LiteralPath $_.FullName -Destination $target -Force -ErrorAction Stop",
    "    } catch {",
    "      Tomb $target",
    "      Copy-Item -LiteralPath $_.FullName -Destination $target -Force",
    "    }",
    "  }",
    "}",
  ].join("; ");
  await run(
    "powershell.exe",
    ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
    { env: { ...process.env, QS_SRC: src, QS_DEST: dest } },
  );
  await hardenOverwriteKeyFiles(src, dest);
}

async function hardenOverwriteKeyFiles(srcDir, destDir) {
  const keys = [
    path.join("resources", "app.asar"),
    EXE_NAME,
    "DFTB工作台.exe",
    "DFTB教师端.exe",
    "chrome_100_percent.pak",
    "resources.pak",
  ];
  for (const rel of keys) {
    const from = path.join(srcDir, rel);
    const to = path.join(destDir, rel);
    if (!fs.existsSync(from) || !fs.statSync(from).isFile()) continue;
    fs.mkdirSync(path.dirname(to), { recursive: true });
    try {
      fs.copyFileSync(from, to);
    } catch {
      tombstoneFile(to);
      try {
        fs.copyFileSync(from, to);
      } catch {
        // 最后手段：写到旁路名再尝试替换
        const alt = `${to}.new`;
        try {
          fs.copyFileSync(from, alt);
          try {
            fs.renameSync(alt, to);
          } catch {
            /* 旁路文件也保留，至少有一份新内容 */
          }
        } catch {
          /* ignore */
        }
      }
    }
  }
}

async function extractZipTo(zipPath, destDir) {
  if (!fs.existsSync(zipPath) || !fs.statSync(zipPath).isFile()) {
    throw new Error(`安装包资源无效：${zipPath}`);
  }
  // 先删掉目标（可能是上次残留的文件/半截目录），再解压
  await removePath(destDir);
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
      "if (-not (Test-Path -LiteralPath $env:QS_ZIP -PathType Leaf)) { throw \"zip 不是文件: $env:QS_ZIP\" }",
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
    return /DFTB|课堂教师/i.test(name) && !/install|setup|uninstall/i.test(name);
  }
  return /DFTB|工作台/i.test(name) && !/install|setup|uninstall|教师/i.test(name);
}

function findAppRoot(extractRoot) {
  if (!fs.existsSync(extractRoot) || !fs.statSync(extractRoot).isDirectory()) {
    throw new Error(`解压目录无效：${extractRoot}`);
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
  throw new Error(`未找到 ${EXE_NAME}`);
}

function resolveMainExeName(appRoot) {
  const names = fs.readdirSync(appRoot).filter((n) => n.toLowerCase().endsWith(".exe"));
  if (names.includes(EXE_NAME)) return EXE_NAME;
  const hit = names.find((n) => looksLikeMainExe(n));
  if (hit) return hit;
  throw new Error(`安装目录中无主程序：${names.join(", ") || "(空)"}`);
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
  for (const name of ["Desktop", "桌面"]) {
    const p = path.join(home, name);
    if (fs.existsSync(p) && fs.statSync(p).isDirectory()) return p;
  }
  return path.join(home, "Desktop");
}

function uninstallRegKeyName() {
  return IS_TEACHER ? "DFTBNeuTeacher" : "DFTBNeuWorkbench";
}

function appVersion() {
  try {
    return require("./package.json").version || app.getVersion();
  } catch {
    return app.getVersion();
  }
}

/** 写入卸载脚本，并注册到「设置 → 应用」列表。 */
function registerUninstallEntry({ installDir, exePath, iconPath }) {
  const version = appVersion();
  const keyName = uninstallRegKeyName();
  const uninstCmd = path.join(installDir, `Uninstall ${APP_NAME}.cmd`);
  const uninstPs1 = path.join(installDir, "uninstall.ps1");

  const ps1 = `# DFTB-NEU uninstaller (auto-generated)
$ErrorActionPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppName = ${JSON.stringify(APP_NAME)}
$KeyName = ${JSON.stringify(keyName)}

$imgs = @(
  ${JSON.stringify(EXE_NAME)},
  'DFTB工作台.exe', 'DFTB-NEU 工作台.exe', 'DFTB-NEU工作台.exe',
  'DFTB教师端.exe', 'DFTB-NEU 教师端.exe', 'dftb-neu.exe'
) | Select-Object -Unique
foreach ($img in $imgs) {
  Start-Process -FilePath taskkill.exe -ArgumentList @('/F','/IM',$img,'/T') -WindowStyle Hidden -Wait -ErrorAction SilentlyContinue | Out-Null
}
Get-Process | Where-Object { $_.ProcessName -match 'DFTB|dftb-neu' -and $_.ProcessName -notmatch 'Setup' } | Stop-Process -Force
Get-CimInstance Win32_Process | ForEach-Object {
  $exe = [string]$_.ExecutablePath
  $cmd = [string]$_.CommandLine
  if (($exe -and $exe.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)) -or
      ($cmd -and $cmd.IndexOf($Root, [StringComparison]::OrdinalIgnoreCase) -ge 0)) {
    if ($_.ProcessId -gt 0 -and $_.Name -notmatch 'Setup') { Stop-Process -Id $_.ProcessId -Force }
  }
}
Start-Sleep -Milliseconds 600

$links = @(
  (Join-Path $env:APPDATA ('Microsoft\\Windows\\Start Menu\\Programs\\' + $AppName + '.lnk')),
  (Join-Path $env:USERPROFILE ('Desktop\\' + $AppName + '.lnk')),
  (Join-Path $env:USERPROFILE ('桌面\\' + $AppName + '.lnk')),
  (Join-Path $env:PUBLIC ('Desktop\\' + $AppName + '.lnk'))
)
foreach ($l in $links) { if (Test-Path -LiteralPath $l) { Remove-Item -LiteralPath $l -Force } }

$reg = Join-Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' $KeyName
if (Test-Path $reg) { Remove-Item -LiteralPath $reg -Recurse -Force }
Get-ChildItem 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall' -ErrorAction SilentlyContinue | ForEach-Object {
  try {
    $p = Get-ItemProperty $_.PSPath -ErrorAction Stop
    if ($p.DisplayName -and $p.DisplayName.Contains($AppName) -and ([string]$p.UninstallString).Contains('dftb-neu')) {
      Remove-Item -LiteralPath $_.PSPath -Recurse -Force
    }
  } catch {}
}

$tmpPs1 = Join-Path $env:TEMP ('dftb-uninst-' + [guid]::NewGuid().ToString('N') + '.ps1')
$lines = @(
  '$ErrorActionPreference = ''SilentlyContinue''',
  'Start-Sleep -Seconds 1',
  ('cmd /c rd /s /q "' + $Root + '"'),
  ('Remove-Item -LiteralPath "' + $tmpPs1 + '" -Force -ErrorAction SilentlyContinue')
)
Set-Content -LiteralPath $tmpPs1 -Value $lines -Encoding UTF8
Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$tmpPs1) -WindowStyle Hidden
`;

  const cmd = `@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
`;

  // PowerShell 5.x 读脚本建议带 UTF-8 BOM，避免中文应用名导致引号解析失败
  fs.writeFileSync(uninstPs1, "\ufeff" + ps1, "utf8");
  fs.writeFileSync(uninstCmd, cmd, "utf8");

  // 清理旧 NSIS / 失效卸载项
  try {
    const { execFileSync } = require("child_process");
    const cleanPs = `
$ErrorActionPreference='SilentlyContinue'
Get-ChildItem 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall' | ForEach-Object {
  $p = Get-ItemProperty $_.PSPath
  if ($p.DisplayName -match ${JSON.stringify(APP_NAME)} -or $p.DisplayName -match 'DFTB') {
    $u = [string]$p.UninstallString
    if ($u -match 'dftb-neu' -or ($u -match '\\.exe' -and -not (Test-Path -LiteralPath (($u -replace '^\"([^\"]+)\".*','$1'))))) {
      Remove-Item -LiteralPath $_.PSPath -Recurse -Force
    }
  }
}
`;
    execFileSync(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cleanPs],
      { windowsHide: true, stdio: "ignore" },
    );
  } catch {
    /* ignore */
  }

  const regPath = `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${keyName}`;
  const displayIcon = iconPath || exePath;
  const add = (name, value, type = "REG_SZ") => {
    try {
      require("child_process").execFileSync(
        "reg.exe",
        ["add", regPath, "/v", name, "/t", type, "/d", String(value), "/f"],
        { windowsHide: true, stdio: "ignore" },
      );
    } catch {
      /* ignore */
    }
  };
  try {
    require("child_process").execFileSync("reg.exe", ["add", regPath, "/f"], {
      windowsHide: true,
      stdio: "ignore",
    });
  } catch {
    /* ignore */
  }
  add("DisplayName", `${APP_NAME} ${version}`);
  add("DisplayVersion", version);
  add("Publisher", "dftb-neu");
  add("InstallLocation", installDir);
  add("DisplayIcon", displayIcon);
  add("UninstallString", `"${uninstCmd}"`);
  add("QuietUninstallString", `"${uninstCmd}"`);
  add("NoModify", "1", "REG_DWORD");
  add("NoRepair", "1", "REG_DWORD");
  try {
    const sizeKb = Math.max(1, Math.round(dirSizeBytes(installDir) / 1024));
    add("EstimatedSize", String(sizeKb), "REG_DWORD");
  } catch {
    /* ignore */
  }
  return uninstCmd;
}

function dirSizeBytes(root) {
  let total = 0;
  const walk = (p) => {
    for (const ent of fs.readdirSync(p, { withFileTypes: true })) {
      const full = path.join(p, ent.name);
      if (ent.isDirectory()) walk(full);
      else {
        try {
          total += fs.statSync(full).size;
        } catch {
          /* ignore */
        }
      }
    }
  };
  walk(root);
  return total;
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
    title: "选择安装路径",
    defaultPath: current || defaultInstallDir(),
    properties: ["openDirectory", "createDirectory"],
  });
  if (res.canceled || !res.filePaths[0]) return null;
  const picked = res.filePaths[0];
  const base = path.basename(String(picked).replace(/[\\/]+$/, ""));
  // 选中盘符根或普通文件夹时，自动套一层应用目录
  let target = picked;
  if (!(base === APP_NAME || /DFTB|课堂/i.test(base))) {
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
    throw new Error(`缺少安装包资源（期望 zip 文件）：${zip}`);
  }

  send({ pct: 6, message: "正在结束旧版本进程…" });
  await stopInstallTargets(installDir);
  // 旧版 dftb-neu 目录也可能占用资源，一并尝试结束
  const legacyDir = path.join(
    process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"),
    "Programs",
    "dftb-neu",
  );
  if (legacyDir !== installDir) await stopInstallTargets(legacyDir);

  send({ pct: 10, message: "准备安装目录…" });
  // 旧目录锁文件（EPERM）时：就地覆盖，或自动改用旁路干净目录

  const staging = path.join(os.tmpdir(), `dftb-setup-${ROLE}-${Date.now()}`);
  try {
    send({ pct: 18, message: "正在解压程序文件…" });
    await extractZipTo(zip, staging);

    send({ pct: 52, message: "正在写入安装目录…" });
    const extractedRoot = findAppRoot(staging);
    const mainExeName = resolveMainExeName(extractedRoot);

    await stopInstallTargets(installDir);
    const finalDir = await deployAppTree(extractedRoot, installDir);
    // 旁路安装时后续快捷方式/卸载项都指向实际目录
    const installedDir = finalDir;

    const exePath = path.join(installedDir, EXE_NAME);
    const actualExe = path.join(installedDir, mainExeName);
    if (!fs.existsSync(actualExe)) {
      throw new Error(`安装后未找到主程序：${mainExeName}（目录：${installedDir}）`);
    }
    if (mainExeName !== EXE_NAME) fs.copyFileSync(actualExe, exePath);
    if (!fs.existsSync(exePath)) throw new Error("安装后未找到主程序");

    const iconPath = ensureInstallIcon(installedDir) || exePath;
    send({ pct: 72, message: "创建快捷方式…" });
    const startMenu = path.join(
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"),
      "Microsoft",
      "Windows",
      "Start Menu",
      "Programs",
      `${APP_NAME}.lnk`,
    );
    await writeShortcut(startMenu, exePath, installedDir, iconPath);
    if (createDesktop) {
      await writeShortcut(path.join(desktopDir(), `${APP_NAME}.lnk`), exePath, installedDir, iconPath);
    }

    send({ pct: 88, message: "注册卸载程序…" });
    const uninstallPath = registerUninstallEntry({
      installDir: installedDir,
      exePath,
      iconPath,
    });

    const relocated =
      path.resolve(installedDir).toLowerCase() !== path.resolve(installDir).toLowerCase();
    send({ pct: 100, message: relocated ? `安装完成（已改用：${installedDir}）` : "安装完成" });
    return {
      ok: true,
      installDir: installedDir,
      exePath,
      uninstallPath,
      relocated,
      networkMessage: relocated
        ? `${DONE_NOTE}\n旧目录被占用，已安装到：${installedDir}`
        : DONE_NOTE,
    };
  } catch (err) {
    const msg = err && err.message ? err.message : String(err);
    const code = err && err.code ? ` [${err.code}]` : "";
    throw new Error(`${msg}${code}\n目标：${installDir}\n资源：${zip}`);
  } finally {
    try {
      await removePath(staging, { retries: 3 });
    } catch {
      /* ignore */
    }
  }
});

ipcMain.handle("setup:launch", async (_e, exePath) => {
  if (!exePath || !fs.existsSync(exePath)) throw new Error("主程序不存在");
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
