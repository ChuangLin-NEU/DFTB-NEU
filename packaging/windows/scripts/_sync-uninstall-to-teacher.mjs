import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const s = fs.readFileSync(path.join(root, "installer-ui-student", "main.cjs"), "utf8");
let t = fs.readFileSync(path.join(root, "installer-ui-teacher", "main.cjs"), "utf8");
const start = s.indexOf("function uninstallRegKeyName");
const end = s.indexOf('ipcMain.handle("setup:meta"');
if (start < 0 || end < 0) throw new Error("student markers missing");
const block = s.slice(start, end);
if (t.includes("function uninstallRegKeyName")) {
  const ts = t.indexOf("function uninstallRegKeyName");
  const te = t.indexOf('ipcMain.handle("setup:meta"');
  t = t.slice(0, ts) + block + t.slice(te);
} else {
  const te = t.indexOf('ipcMain.handle("setup:meta"');
  t = t.slice(0, te) + block + t.slice(te);
}
if (!t.includes("注册卸载程序")) {
  t = t.replace(
    'send({ pct: 100, message: "安装完成" });',
    `send({ pct: 88, message: "注册卸载程序…" });
    const uninstallPath = registerUninstallEntry({
      installDir,
      exePath,
      iconPath,
    });

    send({ pct: 100, message: "安装完成" });`,
  );
  t = t.replace(
    "networkMessage: DONE_NOTE,\n    };",
    "uninstallPath,\n      networkMessage: DONE_NOTE,\n    };",
  );
}
fs.writeFileSync(path.join(root, "installer-ui-teacher", "main.cjs"), t);
console.log("ok", t.includes("registerUninstallEntry"), t.includes("注册卸载程序"));
