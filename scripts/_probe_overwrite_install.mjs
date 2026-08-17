/**
 * 实测覆盖安装能力：旧版在跑 → 杀进程 → 清目录 → 写入新文件 → 注册卸载。
 * 不弹 GUI，复刻 Setup 核心步骤。
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const installDir = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"),
  "Programs",
  "DFTB工作台",
);
const legacyDir = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"),
  "Programs",
  "dftb-neu",
);
const sourceUnpacked = path.resolve(
  "C:/Users/13919/Projects/dftb-neu/packaging/windows/electron/dist/win-unpacked",
);

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    encoding: "utf8",
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    ...opts,
  });
  return r;
}

function sleep(ms) {
  spawnSync("powershell.exe", ["-NoProfile", "-Command", `Start-Sleep -Milliseconds ${ms}`], {
    windowsHide: true,
  });
}

function stopTargets(dir) {
  const images = [
    "DFTB工作台.exe",
    "DFTB-NEU 工作台.exe",
    "DFTB-NEU工作台.exe",
    "dftb-neu.exe",
  ];
  for (const img of images) {
    run("taskkill.exe", ["/F", "/IM", img, "/T"]);
  }
  const ps = [
    "$ErrorActionPreference='SilentlyContinue'",
    `$root = [IO.Path]::GetFullPath(${JSON.stringify(dir)})`,
    "Get-Process | Where-Object { $_.ProcessName -match 'DFTB|dftb-neu' -and $_.ProcessName -notmatch 'Setup' } | Stop-Process -Force",
    "Get-CimInstance Win32_Process | ForEach-Object {",
    "  $exe = [string]($_.ExecutablePath); $cmd = [string]($_.CommandLine); $hit=$false",
    "  if ($exe -and $exe.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { $hit=$true }",
    "  if (-not $hit -and $cmd -and $cmd.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $hit=$true }",
    "  if ($hit -and $_.ProcessId -gt 0 -and $_.Name -notmatch 'Setup') { Stop-Process -Id $_.ProcessId -Force }",
    "}",
  ].join("; ");
  run("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]);
  sleep(800);
}

function removePath(p, retries = 8) {
  if (!fs.existsSync(p)) return true;
  for (let i = 0; i < retries; i++) {
    try {
      fs.rmSync(p, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
      if (!fs.existsSync(p)) return true;
    } catch {
      /* continue */
    }
    run("cmd.exe", ["/c", "rd", "/s", "/q", p]);
    if (!fs.existsSync(p)) return true;
    try {
      const tomb = `${p}.old-${Date.now()}-${i}`;
      if (fs.existsSync(p)) fs.renameSync(p, tomb);
      run("cmd.exe", ["/c", "rd", "/s", "/q", tomb]);
      if (!fs.existsSync(p)) return true;
    } catch {
      /* continue */
    }
    sleep(350 + i * 200);
  }
  return !fs.existsSync(p);
}

function findMainExe(dir) {
  const names = fs.readdirSync(dir).filter((n) => n.toLowerCase().endsWith(".exe"));
  const hit = names.find((n) => /DFTB|工作台/i.test(n) && !/uninstall|setup/i.test(n));
  return hit || names[0] || "";
}

console.log("installDir=", installDir);
console.log("source=", sourceUnpacked, "exists=", fs.existsSync(sourceUnpacked));
if (!fs.existsSync(sourceUnpacked)) {
  console.error("FAIL: no win-unpacked source");
  process.exit(2);
}

const beforeExe = fs.existsSync(installDir) ? findMainExe(installDir) : "";
const beforeHasUninst = fs.existsSync(path.join(installDir, "uninstall.ps1"));
console.log("before exe=", beforeExe, "uninstall_ps1=", beforeHasUninst);

// Case A: start old app then overwrite
let started = false;
if (beforeExe) {
  const exePath = path.join(installDir, beforeExe);
  console.log("starting old app…", exePath);
  // detached：勿用 spawnSync+start（部分环境会一直挂起）
  const child = spawnSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-Command",
      `Start-Process -FilePath ${JSON.stringify(exePath)} -WorkingDirectory ${JSON.stringify(installDir)}`,
    ],
    { windowsHide: true, encoding: "utf8" },
  );
  if (child.status !== 0) console.log("start warn", (child.stderr || "").slice(0, 200));
  sleep(5000);
  const alive = run("powershell.exe", [
    "-NoProfile",
    "-Command",
    "(Get-Process | Where-Object { $_.ProcessName -match 'DFTB' -and $_.ProcessName -notmatch 'Setup' }).Count",
  ]);
  console.log("running DFTB processes=", (alive.stdout || "").trim());
  started = true;
}

console.log("stop + remove (with app potentially running)…");
stopTargets(installDir);
stopTargets(legacyDir);
const cleared = removePath(installDir);
console.log("cleared installDir=", cleared, "exists=", fs.existsSync(installDir));
if (!cleared) {
  console.error("FAIL: could not clear old install dir (overwrite blocked)");
  process.exit(1);
}

console.log("copy new files…");
const r = run(
  "powershell.exe",
  [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    "Copy-Item -LiteralPath $env:QS_SRC -Destination $env:QS_DEST -Recurse -Force",
  ],
  { env: { ...process.env, QS_SRC: sourceUnpacked, QS_DEST: installDir } },
);
if (r.status !== 0) {
  console.error("FAIL copy", r.stderr || r.stdout);
  process.exit(1);
}

// alias exe name expected by shortcuts
const mainName = findMainExe(installDir);
const alias = path.join(installDir, "DFTB工作台.exe");
const mainPath = path.join(installDir, mainName);
if (mainName && mainName !== "DFTB工作台.exe" && fs.existsSync(mainPath)) {
  fs.copyFileSync(mainPath, alias);
}

// write uninstall marker like installer
const uninstPs1 = path.join(installDir, "uninstall.ps1");
const uninstCmd = path.join(installDir, "Uninstall DFTB工作台.cmd");
fs.writeFileSync(uninstPs1, "\ufeff# probe uninstall marker\n", "utf8");
fs.writeFileSync(
  uninstCmd,
  '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"\r\n',
  "utf8",
);
run("reg.exe", [
  "add",
  "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DFTBNeuWorkbench",
  "/v",
  "DisplayName",
  "/t",
  "REG_SZ",
  "/d",
  "DFTB工作台 0.3.2-probe",
  "/f",
]);
run("reg.exe", [
  "add",
  "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DFTBNeuWorkbench",
  "/v",
  "UninstallString",
  "/t",
  "REG_SZ",
  "/d",
  `"${uninstCmd}"`,
  "/f",
]);
run("reg.exe", [
  "add",
  "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DFTBNeuWorkbench",
  "/v",
  "InstallLocation",
  "/t",
  "REG_SZ",
  "/d",
  installDir,
  "/f",
]);

const afterExe = findMainExe(installDir);
const ok =
  cleared &&
  fs.existsSync(path.join(installDir, afterExe)) &&
  fs.existsSync(uninstPs1) &&
  fs.existsSync(alias);
console.log("after exe=", afterExe);
console.log("has DFTB工作台.exe=", fs.existsSync(alias));
console.log("has uninstall=", fs.existsSync(uninstPs1));
console.log(started ? "CASE=running-old-then-overwrite" : "CASE=cold-overwrite");
console.log(ok ? "PASS overwrite install" : "FAIL overwrite install");
process.exit(ok ? 0 : 1);
