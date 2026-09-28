/**
 * 打 Mac 学生端构建包（在 macOS 上 npm run dist 即可出 dmg）。
 *   node scripts/pack-mac-kit.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const version =
  JSON.parse(
    fs.readFileSync(path.join(repoRoot, "packaging", "mac", "electron", "package.json"), "utf8"),
  ).version || "dev";

const outName = `DFTB_Neu_Mac学生端构建包_${version}`;
const desktop = process.env.USERPROFILE
  ? path.join(process.env.USERPROFILE, "Desktop")
  : repoRoot;
const staging = path.join(repoRoot, "packaging", "mac", "release", `_kit_${version}`);
const zipPath = path.join(desktop, `${outName}.zip`);
const releaseZip = path.join(repoRoot, "packaging", "mac", "release", `${outName}.zip`);

const SKIP_DIR_NAMES = new Set([
  ".git",
  ".venv",
  "venv",
  "node_modules",
  "__pycache__",
  ".pytest_cache",
  "dist",
  "release",
  "win-unpacked",
  "python-win",
  "pydeps",
]);

function rmrf(p) {
  if (fs.existsSync(p)) fs.rmSync(p, { recursive: true, force: true, maxRetries: 3 });
}

function shouldSkipDir(name) {
  return SKIP_DIR_NAMES.has(name) || name.startsWith("_src_") || name.startsWith("_kit_");
}

function copyTree(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const ent of fs.readdirSync(src, { withFileTypes: true })) {
    const from = path.join(src, ent.name);
    const to = path.join(dest, ent.name);
    if (ent.isDirectory()) {
      if (shouldSkipDir(ent.name)) continue;
      copyTree(from, to);
    } else if (ent.isFile() && !ent.name.endsWith(".pyc")) {
      fs.copyFileSync(from, to);
    }
  }
}

rmrf(staging);
const destRoot = path.join(staging, outName);
fs.mkdirSync(destRoot, { recursive: true });

for (const rel of ["apps/api", "apps/web", "engines", "templates", "packaging/mac"]) {
  const src = path.join(repoRoot, ...rel.split("/"));
  if (!fs.existsSync(src)) throw new Error(`缺少 ${rel}`);
  copyTree(src, path.join(destRoot, ...rel.split("/")));
}

fs.writeFileSync(
  path.join(destRoot, "请先读我.txt"),
  `DFTB-NEU Mac 学生端构建包 ${version}
================================

特点：登录课堂中心后，DeepSeek / LLM 默认走中心代理，无需学生自配 Key。

在 macOS 上构建：
  1. brew install python@3.12
  2. cd packaging/mac/electron
  3. npm install --registry=https://registry.npmmirror.com
  4. npm run dist
  5. 产物在 packaging/mac/electron/dist/DFTB_Neu_Mac_${version}_*.dmg

开发运行：
  cd packaging/mac/electron && npm start

详见 packaging/mac/README.md
`,
  "utf8",
);

const py =
  process.env.DFTB_NEU_PYTHON ||
  path.join(repoRoot, "packaging", "windows", "backend", "python-win", "python.exe");
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
const zipHelper = path.join(staging, "_zip_kit.py");
fs.writeFileSync(zipHelper, zipPy, "utf8");
const pyBin = fs.existsSync(py) ? py : "python";
fs.mkdirSync(path.dirname(releaseZip), { recursive: true });

console.log("staging →", staging);
for (const dest of [zipPath, releaseZip]) {
  if (fs.existsSync(dest)) fs.unlinkSync(dest);
  console.log("zip →", dest);
  const r = spawnSync(pyBin, [zipHelper, destRoot, dest], { stdio: "inherit" });
  if (r.status !== 0) process.exit(r.status || 1);
}
try {
  rmrf(staging);
} catch (e) {
  console.warn("soft cleanup staging", e && e.message);
}
console.log("DONE");
console.log("  Desktop:", zipPath);
console.log("  Release:", releaseZip);
