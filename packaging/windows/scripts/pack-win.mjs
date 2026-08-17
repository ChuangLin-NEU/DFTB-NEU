/**
 * 打包 Windows x64 现代 Setup（学生端 + 教师端，Electron portable，非 NSIS）：
 *   packaging/windows/release/DFTB_Neu_Setup_<ver>.exe
 *   packaging/windows/release/DFTB_Neu_Teacher_Setup_<ver>.exe
 *
 * 用法：
 *   node packaging/windows/scripts/pack-win.mjs
 *   TARGET=student|teacher|all SKIP_MODERN_SETUP=1 SKIP_PYDEPS=1 SKIP_WIN_PYTHON=1
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolvePython } from "./resolve-python.mjs";

const winRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(winRoot, "..", "..");
const releaseDir = path.join(winRoot, "release");
const skipModern = process.env.SKIP_MODERN_SETUP === "1";
const target = (process.env.TARGET || "all").toLowerCase();
const pyExeHost = resolvePython();

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    console.log(`\n$ ${cmd} ${args.join(" ")}`);
    // 仅 .cmd/.bat 需要 shell；node.exe 等带空格路径禁用 shell
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

function rmrf(p) {
  fs.rmSync(p, { recursive: true, force: true });
}

function step(msg) {
  console.log(`\n==> [${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${msg}`);
}

function osHomedir() {
  return process.env.HOME || process.env.USERPROFILE || "";
}

function electronCacheDir() {
  if (process.env.ELECTRON_CACHE) return process.env.ELECTRON_CACHE;
  if (process.platform === "win32") {
    return path.join(osHomedir(), "AppData", "Local", "electron", "Cache");
  }
  return path.join(osHomedir(), "Library/Caches/electron");
}

const pyMirror = process.env.PIP_INDEX_URL || "https://pypi.tuna.tsinghua.edu.cn/simple";
const skipPydeps = process.env.SKIP_PYDEPS === "1";
const skipWinPython = process.env.SKIP_WIN_PYTHON === "1";

const ebEnv = {
  CSC_IDENTITY_AUTO_DISCOVERY: "false",
  ELECTRON_MIRROR: process.env.ELECTRON_MIRROR || "https://npmmirror.com/mirrors/electron/",
  ELECTRON_BUILDER_BINARIES_MIRROR:
    process.env.ELECTRON_BUILDER_BINARIES_MIRROR ||
    "https://npmmirror.com/mirrors/electron-builder-binaries/",
};

function assertWinPydeps(dir) {
  if (!fs.existsSync(dir)) throw new Error(`缺少 pydeps：${dir}`);
  const darwin = [];
  const walk = (p) => {
    for (const name of fs.readdirSync(p)) {
      const full = path.join(p, name);
      let st;
      try {
        st = fs.lstatSync(full);
      } catch {
        continue;
      }
      if (st.isDirectory()) {
        if (name === "__pycache__" || name.endsWith(".dist-info")) continue;
        walk(full);
      } else if (/\.(so|dylib)$/i.test(name) || /cpython-\d+-darwin/i.test(name)) {
        darwin.push(path.relative(dir, full));
      }
    }
  };
  walk(dir);
  if (darwin.length) {
    throw new Error(
      `pydeps 含 macOS 原生库（共 ${darwin.length} 个），不可用于 Windows。示例：${darwin.slice(0, 3).join(", ")}`,
    );
  }
  for (const n of ["uvicorn", "fastapi", "pydantic_core", "httpx"]) {
    if (!fs.existsSync(path.join(dir, n)) && !fs.existsSync(path.join(dir, `${n}.py`))) {
      throw new Error(`pydeps 缺少 ${n}`);
    }
  }
  const pc = path.join(dir, "pydantic_core");
  if (fs.existsSync(pc)) {
    const native = fs.readdirSync(pc).filter((n) => /pydantic_core/i.test(n) && !n.endsWith(".pyi") && n !== "__init__.py");
    if (!native.some((n) => /\.pyd$/i.test(n) || /win_amd64/i.test(n))) {
      throw new Error(`pydantic_core 未含 Windows 扩展：${native.join(", ") || "(空)"}`);
    }
  }
}

async function prepareStudentRuntime() {
  const { prepareWinPython } = await import("./prepare-win-python.mjs");
  if (!skipWinPython) {
    step("准备内置 Windows Python …");
    await prepareWinPython();
  } else {
    step("跳过 Windows Python（SKIP_WIN_PYTHON=1）");
  }
  const pyExe = path.join(winRoot, "backend", "python-win", "python.exe");
  if (!fs.existsSync(pyExe)) throw new Error("内置 Python 未就绪");

  const pydeps = path.join(winRoot, "backend", "pydeps");
  const reqWin = path.join(winRoot, "backend", "requirements-win.txt");
  // 本机已是 Windows：直接用内置 python-win 装依赖，无需交叉编译轮子
  const embedPy = path.join(winRoot, "backend", "python-win", "python.exe");
  const pyBin = fs.existsSync(embedPy) ? embedPy : pyExeHost;
  const onWindows = process.platform === "win32";

  if (skipPydeps && fs.existsSync(pydeps) && fs.readdirSync(pydeps).length > 5) {
    step("跳过 pip（复用 pydeps）");
    assertWinPydeps(pydeps);
  } else {
    step(`安装 Windows Python 依赖 → pydeps（解释器 ${pyBin}，镜像 ${pyMirror}）…`);
    rmrf(pydeps);
    fs.mkdirSync(pydeps, { recursive: true });
    const pipArgs = [
      "-m",
      "pip",
      "install",
      "--no-compile",
      "--default-timeout",
      "180",
      "-r",
      reqWin,
      "-t",
      pydeps,
      "-i",
      pyMirror,
      "--upgrade",
    ];
    if (!onWindows) {
      pipArgs.push(
        "--platform",
        "win_amd64",
        "--python-version",
        "312",
        "--implementation",
        "cp",
        "--abi",
        "cp312",
        "--only-binary=:all:",
        "--ignore-requires-python",
      );
    }
    await run(pyBin, pipArgs, { env: { PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" } });
    assertWinPydeps(pydeps);
  }
}

function resolveEbBin() {
  const base = path.join(winRoot, "node_modules", ".bin", "electron-builder");
  if (process.platform === "win32") {
    if (fs.existsSync(base + ".cmd")) return base + ".cmd";
    if (fs.existsSync(base + ".ps1")) return base + ".ps1";
  }
  if (fs.existsSync(base)) return base;
  return "";
}

async function ensureSharedBuilder() {
  let eb = resolveEbBin();
  if (eb) return eb;
  step("npm install（共用 electron-builder，仅一次）…");
  await run(
    process.platform === "win32" ? "npm.cmd" : "npm",
    [
      "install",
      "--no-fund",
      "--no-audit",
      "--registry=https://registry.npmmirror.com",
    ],
    {
      cwd: winRoot,
      env: {
        ELECTRON_MIRROR: ebEnv.ELECTRON_MIRROR,
        ELECTRON_BUILDER_BINARIES_MIRROR: ebEnv.ELECTRON_BUILDER_BINARIES_MIRROR,
        ELECTRON_CACHE: electronCacheDir(),
      },
    },
  );
  eb = resolveEbBin();
  if (!eb) throw new Error("electron-builder 安装失败");
  return eb;
}

function copyIconBeside(unpacked, iconSrc) {
  const src = iconSrc || path.join(winRoot, "build", "icon.ico");
  if (!fs.existsSync(src)) return;
  const dest = path.join(unpacked, "icon.ico");
  fs.copyFileSync(src, dest);
  const resIcon = path.join(unpacked, "resources", "icon.ico");
  try {
    fs.mkdirSync(path.dirname(resIcon), { recursive: true });
    fs.copyFileSync(src, resIcon);
  } catch {
    /* ignore */
  }
}

async function packApp({ label, appDir, productExeHint, payloadName, installerUiDir, setupPrefix, ebBin, iconFile }) {
  step(`${label}：electron-builder --win dir --x64`);
  await run(ebBin, ["--win", "dir", "--x64"], { cwd: appDir, env: ebEnv });

  const outDir = path.join(appDir, "dist");
  const unpacked = path.join(outDir, "win-unpacked");
  if (!fs.existsSync(unpacked)) throw new Error(`${label} 未生成 win-unpacked`);
  const exes = fs.readdirSync(unpacked).filter((n) => n.endsWith(".exe"));
  if (!exes.length) throw new Error(`${label} win-unpacked 无 exe`);
  console.log(`  ${label} exes:`, exes.join(", "));
  if (productExeHint && !exes.some((n) => n.includes(productExeHint) || n === productExeHint)) {
    console.warn(`  [warn] 未看到期望主程序名含「${productExeHint}」，现有：${exes.join(", ")}`);
  }
  copyIconBeside(unpacked, iconFile ? path.join(winRoot, "build", iconFile) : undefined);

  const version = JSON.parse(fs.readFileSync(path.join(appDir, "package.json"), "utf8")).version;
  const distZip = path.join(releaseDir, `${setupPrefix}-${version}-win-x64.zip`);
  fs.mkdirSync(releaseDir, { recursive: true });
  step(`${label}：压缩发行 zip → ${path.basename(distZip)}`);
  await run(pyExeHost, [path.join(winRoot, "scripts", "zip-win-payload.py"), unpacked, distZip]);

  if (skipModern) {
    step(`${label}：跳过现代 Setup（SKIP_MODERN_SETUP=1）`);
    return { version, distZip };
  }

  const uiPkgPath = path.join(installerUiDir, "package.json");
  const uiPkg = JSON.parse(fs.readFileSync(uiPkgPath, "utf8"));
  uiPkg.version = version;
  fs.writeFileSync(uiPkgPath, `${JSON.stringify(uiPkg, null, 2)}\n`);

  const payloadDir = path.join(releaseDir, payloadName);
  const payloadZip = path.join(payloadDir, "app.zip");
  rmrf(payloadDir);
  fs.mkdirSync(payloadDir, { recursive: true });
  step(`${label}：压缩 win-unpacked → ${payloadName}/app.zip`);
  await run(pyExeHost, [path.join(winRoot, "scripts", "zip-win-payload.py"), unpacked, payloadZip]);

  // 现代 Setup：Electron 无边框安装界面 + portable（非 NSIS）
  const installerOut = path.join(
    releaseDir,
    label.includes("教师") ? "installer-build-teacher" : "installer-build-student",
  );
  rmrf(installerOut);

  step(`${label}：打包现代 Setup（Electron portable，非 NSIS）`);
  await run(
    ebBin,
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
  if (!built.length) throw new Error(`${label} 未找到 Setup 产物：${installerOut}`);
  const finalDest = path.join(releaseDir, `${setupPrefix}_Setup_${version}.exe`);
  fs.copyFileSync(path.join(installerOut, built[0]), finalDest);
  console.log(`  → ${finalDest} (${Math.round(fs.statSync(finalDest).size / 1024 / 1024)} MB)`);
  return { version, distZip, setup: finalDest };
}

step("DFTB Neu Windows 现代 Setup 打包开始");
const ebBin = await ensureSharedBuilder();

if (target === "all" || target === "student") {
  await prepareStudentRuntime();
}

const results = [];
if (target === "all" || target === "student") {
  results.push(
    await packApp({
      label: "学生端",
      appDir: path.join(winRoot, "electron"),
      productExeHint: "DFTB",
      payloadName: "payload-student",
      installerUiDir: path.join(winRoot, "installer-ui-student"),
      setupPrefix: "DFTB_Neu",
      ebBin,
      iconFile: "icon-student.ico",
    }),
  );
  // 打包后硬校验：内置 Python / pydeps 必须在 win-unpacked
  const unpacked = path.join(winRoot, "electron", "dist", "win-unpacked");
  const must = [
    path.join(unpacked, "resources", "backend", "python-win", "python.exe"),
    path.join(unpacked, "resources", "backend", "pydeps", "fastapi"),
    path.join(unpacked, "resources", "api", "dftbneu", "main.py"),
    path.join(unpacked, "resources", "web", "index.html"),
  ];
  for (const p of must) {
    if (!fs.existsSync(p)) throw new Error(`学生端打包校验失败：缺少 ${p}`);
  }
  step("学生端产物校验通过（内置 Python + pydeps + API + Web）");
}
if (target === "all" || target === "teacher") {
  results.push(
    await packApp({
      label: "教师端",
      appDir: path.join(winRoot, "teacher-electron"),
      productExeHint: "教师",
      payloadName: "payload-teacher",
      installerUiDir: path.join(winRoot, "installer-ui-teacher"),
      setupPrefix: "DFTB_Neu_Teacher",
      ebBin,
      iconFile: "icon-teacher.ico",
    }),
  );
}

step(`完成：${releaseDir}`);
for (const name of fs.readdirSync(releaseDir)) {
  const full = path.join(releaseDir, name);
  const st = fs.statSync(full);
  if (st.isFile() && /\.(exe|zip)$/i.test(name)) {
    console.log(`  - ${name} (${Math.round(st.size / 1024 / 1024)} MB)`);
  }
}
