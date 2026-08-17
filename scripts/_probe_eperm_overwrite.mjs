/**
 * 模拟「旧目录 app.asar 被锁删不掉」→ 旁路干净目录安装应成功。
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const parent = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"),
  "Programs",
);
const preferred = path.join(parent, "_dftb_eperm_probe");
const fallback = path.join(parent, "_dftb_eperm_probe-最新");
const sourceUnpacked = path.resolve(
  "C:/Users/13919/Projects/dftb-neu/packaging/windows/electron/dist/win-unpacked",
);

function sleep(ms) {
  spawnSync("powershell.exe", ["-NoProfile", "-Command", `Start-Sleep -Milliseconds ${ms}`], {
    windowsHide: true,
  });
}

function cleanup() {
  for (const name of fs.readdirSync(parent)) {
    if (name.startsWith("_dftb_eperm_probe")) {
      try {
        fs.rmSync(path.join(parent, name), { recursive: true, force: true });
      } catch {
        /* ignore */
      }
    }
  }
}

function copyTreeInto(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  const r = spawnSync(
    "robocopy.exe",
    [src, dest, "/E", "/IS", "/IT", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
    { encoding: "utf8", windowsHide: true },
  );
  if ((r.status || 0) >= 8) throw new Error(`robocopy ${r.status}`);
}

cleanup();
fs.mkdirSync(path.join(preferred, "resources"), { recursive: true });
const fakeAsar = path.join(preferred, "resources", "app.asar");
fs.writeFileSync(fakeAsar, "OLD_LOCKED_ASAR");

const locker = spawn(
  "powershell.exe",
  [
    "-NoProfile",
    "-Command",
    `$fs=[IO.File]::Open(${JSON.stringify(fakeAsar)},'Open','Read','None'); Start-Sleep -Seconds 40; $fs.Close()`,
  ],
  { windowsHide: true, stdio: "ignore" },
);
sleep(600);

// 模拟 deploy：首选目录写不进 → 旁路
let used = preferred;
try {
  copyTreeInto(sourceUnpacked, preferred);
  const asar = path.join(preferred, "resources", "app.asar");
  const srcSize = fs.statSync(path.join(sourceUnpacked, "resources", "app.asar")).size;
  if (!fs.existsSync(asar) || fs.statSync(asar).size !== srcSize) throw new Error("incomplete");
} catch {
  fs.mkdirSync(fallback, { recursive: true });
  copyTreeInto(sourceUnpacked, fallback);
  used = fallback;
}

const exes = fs.readdirSync(used).filter((n) => /\.exe$/i.test(n) && /DFTB/i.test(n));
const asar = path.join(used, "resources", "app.asar");
const srcSize = fs.statSync(path.join(sourceUnpacked, "resources", "app.asar")).size;
const ok =
  used === fallback &&
  exes.length > 0 &&
  fs.existsSync(asar) &&
  fs.statSync(asar).size === srcSize;

console.log("used=", used);
console.log("exes=", exes.join(","), "asar_size=", fs.existsSync(asar) ? fs.statSync(asar).size : 0);
console.log(ok ? "PASS" : "FAIL");

try {
  locker.kill();
} catch {
  /* ignore */
}
sleep(400);
cleanup();
process.exit(ok ? 0 : 1);
