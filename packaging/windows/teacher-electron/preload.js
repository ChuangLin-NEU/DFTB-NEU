const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dftbTeacher", {
  platform: process.platform,
  getConfig: () => ipcRenderer.invoke("teacher-config"),
  setTeacherPassword: (password) => ipcRenderer.invoke("teacher-set-password", password),
});
