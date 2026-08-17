/**
 * 打 Windows 源码包（可重新打包 Setup，不含 node_modules / pydeps / release）。
 *   node scripts/pack-win-source.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const version =
  JSON.parse(
    fs.readFileSync(
      path.join(repoRoot, "packaging", "windows", "electron", "package.json"),
      "utf8",
    ),
  ).version || "dev";

const outName = `DFTB_Neu_Windows源码_${version}`;
const desktop = process.env.USERPROFILE
  ? path.join(process.env.USERPROFILE, "Desktop")
  : repoRoot;
const staging = path.join(repoRoot, "packaging", "windows", "release", `_src_${version}`);
const zipPath = path.join(desktop, `${outName}.zip`);
const releaseZip = path.join(repoRoot, "packaging", "windows", "release", `${outName}.zip`);

const SKIP_DIR_NAMES = new Set([
  ".git",
  ".venv",
  "venv",
  "node_modules",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".cache",
  "dist",
  "release",
  "python-win",
  "pydeps",
  "win-unpacked",
  "payload",
  "payload-student",
  "payload-teacher",
  "installer-build-student",
  "installer-build-teacher",
  "data",
  ".cursor",
  "agent-transcripts",
  "_src_0.3.1",
]);

const SKIP_FILE_GLOBS = [
  /\.pyc$/i,
  /\.log$/i,
  /^\.env$/i,
  /\.DS_Store$/i,
  /^DFTB_Neu_.*\.(exe|zip)$/i,
  /^app\.zip$/i,
  /^cloudflared\.exe$/i,
];

function shouldSkipDir(name) {
  return SKIP_DIR_NAMES.has(name);
}

function shouldSkipFile(name) {
  return SKIP_FILE_GLOBS.some((re) => re.test(name));
}

function rmrf(p) {
  fs.rmSync(p, { recursive: true, force: true });
}

function copyTree(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const ent of fs.readdirSync(src, { withFileTypes: true })) {
    if (ent.name === "." || ent.name === "..") continue;
    const from = path.join(src, ent.name);
    const to = path.join(dest, ent.name);
    if (ent.isDirectory()) {
      if (shouldSkipDir(ent.name)) continue;
      // packaging/windows/electron/dist 等已由 SKIP_DIR_NAMES 覆盖
      copyTree(from, to);
      continue;
    }
    if (ent.isSymbolicLink()) continue;
    if (shouldSkipFile(ent.name)) continue;
    fs.copyFileSync(from, to);
  }
}

function writeReadme(destRoot) {
  const text = `DFTB-NEU Windows 源码包 ${version}
================================

内容：仓库源码（apps / engines / templates / scripts / packaging 等），
不含 node_modules、内置 Python、pydeps、已打好的 Setup。

在 Windows 上重新打 Setup：
  1. 安装 Node.js LTS、Git（可选）
  2. cd packaging\\windows
  3. npm install --registry=https://registry.npmmirror.com
  4. 首次需准备内置 Python 与 pydeps（去掉 SKIP_*）：
       node scripts\\pack-win.mjs
     若本机已有 packaging\\windows\\backend\\python-win 与 pydeps，可：
       set SKIP_WIN_PYTHON=1
       set SKIP_PYDEPS=1
       node scripts\\pack-win.mjs
  5. 产物在 packaging\\windows\\release\\DFTB_Neu_Setup_${version}.exe

学生使用请发 Setup，不要发本源码包。
`;
  fs.writeFileSync(path.join(destRoot, "源码说明.txt"), text, "utf8");
}

console.log("staging →", staging);
rmrf(staging);
const rootOut = path.join(staging, outName);
fs.mkdirSync(rootOut, { recursive: true });

// 顶层选择性拷贝（避免把巨大无关目录带上）
const topKeep = [
  "apps",
  "engines",
  "templates",
  "scripts",
  "docs",
  "packaging",
  "README.md",
  "LICENSE",
  ".gitignore",
  "pyproject.toml",
  "requirements.txt",
  "requirements-dev.txt",
];
for (const name of topKeep) {
  const from = path.join(repoRoot, name);
  if (!fs.existsSync(from)) continue;
  const to = path.join(rootOut, name);
  const st = fs.statSync(from);
  if (st.isDirectory()) copyTree(from, to);
  else if (!shouldSkipFile(name)) fs.copyFileSync(from, to);
}
writeReadme(rootOut);

// 用内置 python 打 zip（路径友好）
const py =
  process.env.DFTB_NEU_PYTHON ||
  path.join(repoRoot, "packaging", "windows", "backend", "python-win", "python.exe");
// 源码 zip：保留顶层目录名；不要求根目录有 exe
const zipPy = `
import sys, zipfile
from pathlib import Path
src, out = Path(sys.argv[1]), Path(sys.argv[2])
if out.exists(): out.unlink()
root_name = src.name
n = 0
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for p in sorted(src.rglob("*")):
        if p.is_file():
            zf.write(p, arcname=(root_name + "/" + p.relative_to(src).as_posix()))
            n += 1
print(f"wrote {out} files={n} size_mb={out.stat().st_size/1024/1024:.1f}")
`;
const zipHelper = path.join(staging, "_zip_src.py");
fs.writeFileSync(zipHelper, zipPy, "utf8");
const pyBin = fs.existsSync(py) ? py : "python";
for (const dest of [zipPath, releaseZip]) {
  rmrf(dest);
  console.log("zip →", dest);
  const r = spawnSync(pyBin, [zipHelper, rootOut, dest], { stdio: "inherit" });
  if (r.status !== 0) process.exit(r.status || 1);
}

rmrf(staging);
console.log("DONE");
console.log("  Desktop:", zipPath);
console.log("  Release:", releaseZip);
