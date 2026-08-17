/** 解析本机 Python，供 zip / pip 调用（Windows / macOS 通用）。 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const winRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(winRoot, "..", "..");

export function resolvePython() {
  const candidates = [
    process.env.DFTB_PACK_PYTHON,
    path.join(winRoot, "backend", "python-win", "python.exe"),
    path.join(repoRoot, ".venv", "Scripts", "python.exe"),
    path.join(repoRoot, ".venv", "bin", "python"),
    process.env.LOCALAPPDATA
      ? path.join(process.env.LOCALAPPDATA, "Programs", "dftb-neu", "resources", "backend", "python-win", "python.exe")
      : "",
    "python",
    "python3",
    "py",
  ].filter(Boolean);

  for (const c of candidates) {
    if (c.includes(path.sep) || c.includes("/") || /^[A-Za-z]:\\/.test(c)) {
      if (!fs.existsSync(c)) continue;
      return c;
    }
    const r = spawnSync(c, ["-c", "import sys; print(sys.executable)"], {
      encoding: "utf8",
      shell: process.platform === "win32",
    });
    if (r.status === 0 && (r.stdout || "").trim()) {
      return (r.stdout || "").trim().split(/\r?\n/)[0];
    }
  }
  throw new Error("未找到可用 Python。请设置 DFTB_PACK_PYTHON 或先准备 backend/python-win。");
}
