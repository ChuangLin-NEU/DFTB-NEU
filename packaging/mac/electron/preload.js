const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dftbNeu", {
  platform: process.platform,
  /** 提权启动 wsl --install（弹出 UAC）；部署按钮会先调用再安装 DFTB+ */
  ensureWsl: () => ipcRenderer.invoke("ensure-wsl"),
});
