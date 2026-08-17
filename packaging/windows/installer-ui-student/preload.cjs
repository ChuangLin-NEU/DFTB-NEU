const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("setupApi", {
  meta: () => ipcRenderer.invoke("setup:meta"),
  pickDir: (current) => ipcRenderer.invoke("setup:pickDir", current),
  install: (opts) => ipcRenderer.invoke("setup:install", opts),
  launch: (exePath) => ipcRenderer.invoke("setup:launch", exePath),
  onProgress: (cb) => {
    const handler = (_e, data) => cb(data);
    ipcRenderer.on("setup:progress", handler);
    return () => ipcRenderer.removeListener("setup:progress", handler);
  },
  window: (action) => ipcRenderer.send("setup:window", action),
});
