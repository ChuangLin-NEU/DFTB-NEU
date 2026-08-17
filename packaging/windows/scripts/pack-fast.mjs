/**
 * 快速封装：复用已有 win-unpacked，刷新资源后出安装包。
 *
 * 用法：
 *   node scripts/pack-fast.mjs
 *   MODE=modern|zip          默认 modern（Electron 现代 Setup，非 NSIS）
 *   TARGET=student|teacher|all
 *   COPY_DESKTOP=1
 *   SKIP_MODERN_SETUP=1      兼容旧写法，等价 MODE=zip
 *
 * 耗时大致：
 *   MODE=modern 刷新 + 压 zip + 现代 portable Setup
 *   MODE=zip    只出 zip
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolvePython } from "./resolve-python.mjs";

const winRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(winRoot, "..", "..");
const releaseDir = path.join(winRoot, "release");
const target = (process.env.TARGET || "all").toLowerCase();
const copyDesktop = process.env.COPY_DESKTOP === "1";
const pyExeHost = resolvePython();

function resolveMode() {
  if (process.env.SKIP_MODERN_SETUP === "1") return "zip";
  const m = (process.env.MODE || "modern").toLowerCase();
  if (m === "modern" || m === "portable" || m === "zip") return m === "portable" ? "modern" : m;
  if (m === "nsis") {
    throw new Error("已停用 NSIS。请用 MODE=modern（默认）或 MODE=zip。");
  }
  throw new Error(`未知 MODE=${m}，请用 modern|zip`);
}

const mode = resolveMode();

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    console.log(`\n$ ${cmd} ${args.join(" ")}`);
    // 仅 .cmd/.bat 需要 shell；对 node.exe 等带空格路径禁用 shell，避免被拆开
    const useShell = process.platform === "win32" && /\.(cmd|bat)$/i.test(cmd);
    const child = spawn(cmd, args, {
      cwd: opts.cwd || winRoot,
      stdio: "inherit",
      shell: useShell,
      env: { ...process.env, ...opts.env },
    });
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${cmd} 退出码 ${code}`));
    });
  });
}

function electronCacheDir() {
  if (process.env.ELECTRON_CACHE) return process.env.ELECTRON_CACHE;
  if (process.platform === "win32") {
    return path.join(osHomedir(), "AppData", "Local", "electron", "Cache");
  }
  return path.join(osHomedir(), "Library/Caches/electron");
}

function rmrf(p) {
  fs.rmSync(p, { recursive: true, force: true });
}

function step(msg) {
  console.log(`\n==> [${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${msg}`);
}

function osHomedir() {
  return process.env.HOME || process.env.USERPROFILE || "";
}

function syncDir(src, dest) {
  if (!fs.existsSync(src)) throw new Error(`缺少源目录：${src}`);
  rmrf(dest);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.cpSync(src, dest, {
    recursive: true,
    filter: (p) => {
      const base = path.basename(p);
      if (base === "__pycache__" || base.endsWith(".pyc") || base === ".DS_Store") return false;
      return true;
    },
  });
}

const ebEnv = {
  CSC_IDENTITY_AUTO_DISCOVERY: "false",
  ELECTRON_MIRROR: process.env.ELECTRON_MIRROR || "https://npmmirror.com/mirrors/electron/",
  ELECTRON_BUILDER_BINARIES_MIRROR:
    process.env.ELECTRON_BUILDER_BINARIES_MIRROR ||
    "https://npmmirror.com/mirrors/electron-builder-binaries/",
};

function ebBin() {
  const base = path.join(winRoot, "node_modules", ".bin", "electron-builder");
  const p =
    process.platform === "win32"
      ? [base + ".cmd", base + ".ps1", base].find((x) => fs.existsSync(x))
      : fs.existsSync(base)
        ? base
        : "";
  if (!p) throw new Error("缺少 electron-builder。请先完整打过一次包，或 npm install。");
  return p;
}

function asarBin() {
  const p = path.join(winRoot, "node_modules", "@electron", "asar", "bin", "asar.js");
  if (!fs.existsSync(p)) return "";
  return p;
}

/** 把最新 main.js / preload.js 打进 app.asar（改壳后必须） */
async function refreshAsar(appDir, unpacked) {
  const asarPath = path.join(unpacked, "resources", "app.asar");
  const bin = asarBin();
  if (!fs.existsSync(asarPath) || !bin) {
    console.log("  [提示] 无 app.asar 或 asar 工具，跳过壳刷新");
    return;
  }
  step(`刷新 Electron 壳 → ${path.relative(winRoot, asarPath)}`);
  const tmp = path.join(winRoot, "release", `.asar-tmp-${path.basename(appDir)}`);
  rmrf(tmp);
  await run(process.execPath, [bin, "extract", asarPath, tmp]);
  for (const f of ["main.js", "preload.js", "package.json"]) {
    const src = path.join(appDir, f);
    if (fs.existsSync(src)) fs.copyFileSync(src, path.join(tmp, f));
  }
  await run(process.execPath, [bin, "pack", tmp, asarPath]);
  rmrf(tmp);
}

async function refreshStudent(unpacked) {
  const res = path.join(unpacked, "resources");
  step("刷新学生端 resources（web/api/engines/templates/scripts）");
  syncDir(path.join(repoRoot, "apps/api"), path.join(res, "api"));
  syncDir(path.join(repoRoot, "apps/web"), path.join(res, "web"));
  syncDir(path.join(repoRoot, "engines"), path.join(res, "engines"));
  syncDir(path.join(repoRoot, "templates"), path.join(res, "templates"));
  syncDir(path.join(repoRoot, "scripts"), path.join(res, "scripts"));
  for (const must of [
    path.join(res, "backend", "python-win", "python.exe"),
    path.join(res, "backend", "pydeps", "fastapi"),
    path.join(res, "web", "index.html"),
    path.join(res, "api", "dftbneu", "main.py"),
  ]) {
    if (!fs.existsSync(must)) throw new Error(`快速封装校验失败：缺少 ${must}（请先全量打包一次）`);
  }
}

async function refreshTeacher(unpacked) {
  const res = path.join(unpacked, "resources");
  step("刷新教师端 resources（teacher_web）");
  syncDir(path.join(repoRoot, "apps/teacher_web"), path.join(res, "teacher_web"));
  if (!fs.existsSync(path.join(res, "teacher_web", "index.html"))) {
    throw new Error("教师端 web 刷新失败");
  }
  // 桌面快捷方式 / 旁路 icon.ico：用去白角后的教师图标
  const ico =
    [path.join(winRoot, "build", "icon-teacher.ico"), path.join(winRoot, "build", "icon.ico")].find(
      (p) => fs.existsSync(p),
    ) || "";
  if (ico) {
    fs.copyFileSync(ico, path.join(unpacked, "icon.ico"));
    fs.copyFileSync(ico, path.join(res, "icon.ico"));
  }
}

async function packModern({ label, appDir, payloadName, installerUiDir, setupPrefix, version, unpacked }) {
  const distZip = path.join(releaseDir, `${setupPrefix}-${version}-win-x64.zip`);
  step(`${label}：压缩 zip → ${path.basename(distZip)}`);
  await run(pyExeHost, [path.join(winRoot, "scripts", "zip-win-payload.py"), unpacked, distZip]);

  const uiPkgPath = path.join(installerUiDir, "package.json");
  const uiPkg = JSON.parse(fs.readFileSync(uiPkgPath, "utf8"));
  uiPkg.version = version;
  fs.writeFileSync(uiPkgPath, `${JSON.stringify(uiPkg, null, 2)}\n`);

  const payloadDir = path.join(releaseDir, payloadName);
  const payloadZip = path.join(payloadDir, "app.zip");
  rmrf(payloadDir);
  fs.mkdirSync(payloadDir, { recursive: true });
  step(`${label}：压缩 payload → ${payloadName}/app.zip`);
  await run(pyExeHost, [path.join(winRoot, "scripts", "zip-win-payload.py"), unpacked, payloadZip]);

  const installerOut = path.join(
    releaseDir,
    label.includes("教师") ? "installer-build-teacher" : "installer-build-student",
  );
  rmrf(installerOut);

  step(`${label}：重打现代 Setup（Electron portable，非 NSIS）`);
  await run(
    ebBin(),
    [
      "--project",
      installerUiDir,
      "--config",
      "electron-builder.json",
      "--win",
      "portable",
      "--x64",
    ],
    {
      cwd: installerUiDir,
      env: {
        ...ebEnv,
        ELECTRON_CACHE: electronCacheDir(),
      },
    },
  );

  const built = fs.existsSync(installerOut)
    ? fs.readdirSync(installerOut).filter((n) => /\.exe$/i.test(n))
    : [];
  if (!built.length) throw new Error(`${label} 未找到 Setup：${installerOut}`);
  const finalDest = path.join(releaseDir, `${setupPrefix}_Setup_${version}.exe`);
  fs.copyFileSync(path.join(installerOut, built[0]), finalDest);
  console.log(`  → ${finalDest} (${Math.round(fs.statSync(finalDest).size / 1024 / 1024)} MB)`);
  return { distZip, setup: finalDest };
}

async function packSide({
  label,
  appDir,
  payloadName,
  installerUiDir,
  setupPrefix,
  refresh,
}) {
  const unpacked = path.join(appDir, "dist", "win-unpacked");
  if (!fs.existsSync(unpacked)) {
    throw new Error(`${label} 无 win-unpacked，请先全量：node scripts/pack-win.mjs TARGET=...`);
  }
  await refresh(unpacked);
  await refreshAsar(appDir, unpacked);

  const version = JSON.parse(fs.readFileSync(path.join(appDir, "package.json"), "utf8")).version;
  fs.mkdirSync(releaseDir, { recursive: true });

  if (mode === "zip") {
    const distZip = path.join(releaseDir, `${setupPrefix}-${version}-win-x64.zip`);
    step(`${label}：仅 zip → ${path.basename(distZip)}`);
    await run(pyExeHost, [path.join(winRoot, "scripts", "zip-win-payload.py"), unpacked, distZip]);
    return { version, distZip };
  }

  // modern（默认）
  const out = await packModern({
    label,
    appDir,
    payloadName,
    installerUiDir,
    setupPrefix,
    version,
    unpacked,
  });
  return { version, ...out };
}

step(`DFTB Neu 快速封装 MODE=${mode}`);

const outs = [];
if (target === "all" || target === "student") {
  outs.push(
    await packSide({
      label: "学生端",
      appDir: path.join(winRoot, "electron"),
      payloadName: "payload-student",
      installerUiDir: path.join(winRoot, "installer-ui-student"),
      setupPrefix: "DFTB_Neu",
      refresh: refreshStudent,
    }),
  );
}
if (target === "all" || target === "teacher") {
  outs.push(
    await packSide({
      label: "教师端",
      appDir: path.join(winRoot, "teacher-electron"),
      payloadName: "payload-teacher",
      installerUiDir: path.join(winRoot, "installer-ui-teacher"),
      setupPrefix: "DFTB_Neu_Teacher",
      refresh: refreshTeacher,
    }),
  );
}

if (copyDesktop) {
  const desk = fs.existsSync(path.join(osHomedir(), "Desktop"))
    ? path.join(osHomedir(), "Desktop")
    : path.join(osHomedir(), "桌面");
  for (const o of outs) {
    if (!o.setup) continue;
    const dest = path.join(desk, path.basename(o.setup));
    fs.copyFileSync(o.setup, dest);
    console.log(`  已拷贝桌面：${dest}`);
  }
}

step(`完成：${releaseDir}`);
for (const name of fs.readdirSync(releaseDir)) {
  const full = path.join(releaseDir, name);
  const st = fs.statSync(full);
  if (st.isFile() && /\.(exe|zip)$/i.test(name) && /Setup|win-x64/.test(name)) {
    console.log(`  - ${name} (${Math.round(st.size / 1024 / 1024)} MB)`);
  }
}
