/**
 * 下载并配置 Windows embeddable Python → backend/python-win/
 * 供学生端安装包内嵌，目标机无需预装 Python。
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import https from "node:https";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PY_VER = process.env.WIN_PYTHON_VERSION || "3.12.10";
const PY_TAG = PY_VER.replace(/\./g, "").slice(0, 3); // 312
const destDir = path.join(root, "backend", "python-win");
const zipName = `python-${PY_VER}-embed-amd64.zip`;
const mirrors = [
  `https://mirrors.huaweicloud.com/python/${PY_VER}/${zipName}`,
  `https://npmmirror.com/mirrors/python/${PY_VER}/${zipName}`,
  `https://www.python.org/ftp/python/${PY_VER}/${zipName}`,
];

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { cwd: root, stdio: "inherit", shell: false });
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} 退出码 ${code}`))));
  });
}

function download(url, outFile) {
  return new Promise((resolve, reject) => {
    console.log(`  下载 ${url}`);
    const file = fs.createWriteStream(outFile);
    const lib = url.startsWith("https") ? https : http;
    const req = lib.get(url, { timeout: 180000 }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        file.close();
        fs.unlinkSync(outFile);
        download(res.headers.location, outFile).then(resolve, reject);
        return;
      }
      if (res.statusCode !== 200) {
        file.close();
        try {
          fs.unlinkSync(outFile);
        } catch {
          /* */
        }
        reject(new Error(`HTTP ${res.statusCode}`));
        return;
      }
      res.pipe(file);
      file.on("finish", () => file.close(() => resolve()));
    });
    req.on("error", (e) => {
      try {
        file.close();
        fs.unlinkSync(outFile);
      } catch {
        /* */
      }
      reject(e);
    });
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("下载超时"));
    });
  });
}

function rmrf(p) {
  fs.rmSync(p, { recursive: true, force: true });
}

/** 安装后 resources 布局：backend/python-win、backend/pydeps、api、engines */
function writePth() {
  const pth = path.join(destDir, `python${PY_TAG}._pth`);
  const body = [
    `python${PY_TAG}.zip`,
    ".",
    "..\\pydeps",
    "..\\..\\api",
    "..\\..\\engines\\dftb_agent",
    "import site",
    "",
  ].join("\n");
  fs.writeFileSync(pth, body, "utf8");
  console.log(`  已写入 ${path.basename(pth)}`);
}

export async function prepareWinPython() {
  const exe = path.join(destDir, "python.exe");
  if (process.env.SKIP_WIN_PYTHON === "1" && fs.existsSync(exe)) {
    console.log("==> 跳过 embed Python（已有）");
    writePth();
    return destDir;
  }

  // 优先复用同机 CMATS 已解压的 embed（版本一致时）
  const sibling = path.resolve(root, "../../../cmats-lab/packaging/windows/backend/python-win");
  const siblingExe = path.join(sibling, "python.exe");
  if (fs.existsSync(siblingExe) && !process.env.FORCE_WIN_PYTHON) {
    console.log(`==> 复用 CMATS python-win → ${destDir}`);
    rmrf(destDir);
    fs.mkdirSync(path.dirname(destDir), { recursive: true });
    fs.cpSync(sibling, destDir, { recursive: true });
    writePth();
    return destDir;
  }

  console.log(`==> 准备 Windows 内置 Python ${PY_VER}`);
  const cacheDir = path.join(root, ".cache");
  fs.mkdirSync(cacheDir, { recursive: true });
  let zipPath = path.join(cacheDir, zipName);
  const siblingZip = path.resolve(root, "../../../cmats-lab/packaging/windows/.cache", zipName);
  if (fs.existsSync(siblingZip) && fs.statSync(siblingZip).size > 1_000_000) {
    zipPath = siblingZip;
    console.log(`  复用缓存 ${zipPath}`);
  } else if (!fs.existsSync(zipPath) || fs.statSync(zipPath).size < 1_000_000) {
    let ok = false;
    let lastErr;
    for (const url of mirrors) {
      try {
        await download(url, zipPath);
        ok = true;
        break;
      } catch (e) {
        lastErr = e;
        console.warn(`  [warn] ${url} 失败：${e.message || e}`);
      }
    }
    if (!ok) throw lastErr || new Error("无法下载 embeddable Python");
  } else {
    console.log(`  复用缓存 ${zipPath}`);
  }

  rmrf(destDir);
  fs.mkdirSync(destDir, { recursive: true });
  await run("ditto", ["-x", "-k", zipPath, destDir]);
  if (!fs.existsSync(exe)) throw new Error("解压后未找到 python.exe");
  writePth();
  console.log(`==> 内置 Python 就绪：${exe}`);
  return destDir;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  prepareWinPython().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
