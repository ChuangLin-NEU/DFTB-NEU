const API = "";
let currentProjectId = "";
let structureKind = "poscar";
/** 结构是否来自用户上传（上传后生成时保留，不被内置模板清掉）。 */
let structureUserOwned = false;
/** 输入文件是否来自用户上传（确认计算时原样投递，不被自动生成覆盖）。 */
let hsdUserOwned = false;
let hsdUploadName = "";
let courseHints = { family: "", kind: "" };
let hintPrompt = "";
let hsdDefaultText = "";
let lastDeployDiag = "";
let autoPreviewTimer = null;
let autoPreviewBusy = false;
let lastAutoPreviewKey = "";
let structViewers = { calc: null, task: null };
/** 各任务详情快照：切换/收起后再打开时复用，避免整页重载闪烁。 */
const taskDetailCache = new Map();
/** 当前面板上的结构对比原文（供快照缓存）。 */
let taskStructTexts = { before: "", after: "" };

/** 将接口/异常里的任意值收成可读文案，避免出现 [object Object]。 */
function asDisplayText(value, fallback) {
  if (value == null || value === "") return fallback || "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const parts = value.map((x) => asDisplayText(x, "")).filter(Boolean);
    return parts.length ? parts.join("；") : fallback || "";
  }
  if (typeof value === "object") {
    if (typeof value.message === "string" && value.message.trim()) return value.message;
    if (typeof value.msg === "string" && value.msg.trim()) return value.msg;
    if (typeof value.detail === "string" && value.detail.trim()) return value.detail;
    if (value.detail != null && value.detail !== value) {
      const nested = asDisplayText(value.detail, "");
      if (nested) return nested;
    }
    try {
      return JSON.stringify(value);
    } catch (_) {
      return fallback || "发生错误";
    }
  }
  return String(value);
}

function formatApiError(raw) {
  let msg = asDisplayText(raw, "").trim();
  if (!msg) return "请求失败";
  for (let i = 0; i < 4; i++) {
    try {
      const data = JSON.parse(msg);
      if (data && typeof data === "object" && data.detail != null) {
        const next = asDisplayText(data.detail, "").trim();
        if (next && next !== msg) {
          msg = next;
          continue;
        }
      }
    } catch (_) {
      /* not pure JSON — try nested {"detail":...} inside text */
    }
    const m = msg.match(/\{\s*"detail"\s*:\s*"((?:\\.|[^"\\])*)"\s*\}/);
    if (m) {
      try {
        msg = JSON.parse('"' + m[1] + '"');
      } catch (_) {
        msg = m[1].replace(/\\"/g, '"');
      }
      continue;
    }
    break;
  }
  msg = asDisplayText(msg, "").trim();
  if (/本堂密码/.test(msg) && !/^登录失败/.test(msg)) {
    msg = "登录失败：" + msg;
  }
  if (/^Internal Server Error$/i.test(msg) || /^500\b/.test(msg)) {
    msg =
      "登录失败：本地服务异常或无法连接课堂中心。请确认课堂服务在线后重试";
  }
  return msg || "请求失败";
}

let _sessionWatchTimer = null;
let _forcingLogout = false;
let _sessionGraceUntil = 0;

async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!r.ok) {
    const t = await r.text();
    if (
      r.status === 401 &&
      !String(path || "").startsWith("/api/license") &&
      Date.now() >= _sessionGraceUntil
    ) {
      forceLogoutToGate(
        formatApiError(t || "课堂会话已失效，请重新登录") ||
          "课堂会话已失效，请重新登录"
      );
    }
    throw new Error(formatApiError(t || r.statusText));
  }
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) return r.json();
  return r.text();
}

function stopSessionWatch() {
  if (_sessionWatchTimer) {
    clearInterval(_sessionWatchTimer);
    _sessionWatchTimer = null;
  }
}

function startSessionWatch() {
  stopSessionWatch();
  // 登录后短暂宽限，避免刚激活时误判踢回登录页
  _sessionGraceUntil = Date.now() + 8000;
  _sessionWatchTimer = setInterval(() => {
    watchClassroomSession();
  }, 10000);
  setTimeout(() => {
    watchClassroomSession();
  }, 8000);
}

async function watchClassroomSession() {
  if (_forcingLogout) return;
  if (Date.now() < _sessionGraceUntil) return;
  const app = $("app");
  if (!app || app.hidden) return;
  try {
    const data = await api("/api/license");
    const lic = data.license || {};
    const check = data.check || {};
    // 仅在会话已被中心吊销/本地清空时退出；短暂网络错误不踢出
    if (!lic.activated || check.mode === "locked") {
      forceLogoutToGate(
        (check && check.message) || "本堂密码已失效，请重新登录"
      );
    }
  } catch (_) {
    /* api() 已处理 401；其它错误（如短暂断网）不强制退出 */
  }
}

async function forceLogoutToGate(message) {
  if (_forcingLogout) return;
  _forcingLogout = true;
  stopSessionWatch();
  try {
    await fetch(API + "/api/license/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (_) {
    /* ignore */
  }
  showGate();
  setEnterMessage(
    message || "本堂密码已清除或会话已注销，请重新登录",
    "err"
  );
  _forcingLogout = false;
}

let _modalResolver = null;

function closeAppModal(result) {
  const modal = $("app-modal");
  if (modal) modal.hidden = true;
  document.removeEventListener("keydown", onModalKeydown);
  const resolve = _modalResolver;
  _modalResolver = null;
  if (resolve) resolve(!!result);
}

function onModalKeydown(ev) {
  if (ev.key === "Escape") {
    ev.preventDefault();
    closeAppModal(false);
  } else if (ev.key === "Enter") {
    ev.preventDefault();
    closeAppModal(true);
  }
}

function showConfirmDialog(opts) {
  const o = opts || {};
  const modal = $("app-modal");
  if (!modal) {
    return Promise.resolve(window.confirm(o.message || "确认？"));
  }
  const title = $("app-modal-title");
  const message = $("app-modal-message");
  const hint = $("app-modal-hint");
  const icon = $("app-modal-icon");
  const okBtn = $("app-modal-ok");
  const cancelBtn = $("app-modal-cancel");
  const card = modal.querySelector(".app-modal-card");
  if (title) title.textContent = o.title || "确认操作";
  if (message) message.textContent = o.message || "";
  if (hint) {
    hint.textContent = o.hint || "";
    hint.hidden = !o.hint;
  }
  if (icon) icon.textContent = o.icon || (o.danger ? "!" : "?");
  if (card) card.classList.toggle("is-danger", !!o.danger);
  if (okBtn) {
    okBtn.textContent = o.okText || "确定";
    okBtn.className = "btn " + (o.danger ? "danger" : "btn-primary");
  }
  if (cancelBtn) cancelBtn.textContent = o.cancelText || "取消";
  modal.hidden = false;
  document.addEventListener("keydown", onModalKeydown);
  setTimeout(() => {
    if (o.danger && cancelBtn) cancelBtn.focus();
    else if (okBtn) okBtn.focus();
  }, 0);
  return new Promise((resolve) => {
    _modalResolver = resolve;
  });
}

function initAppModal() {
  const modal = $("app-modal");
  if (!modal || modal.dataset.bound) return;
  modal.dataset.bound = "1";
  modal.querySelectorAll("[data-modal-dismiss]").forEach((el) => {
    el.addEventListener("click", () => closeAppModal(false));
  });
  const okBtn = $("app-modal-ok");
  if (okBtn) okBtn.addEventListener("click", () => closeAppModal(true));
}

function setEnterMessage(text, kind) {
  const el = $("enter-msg");
  if (!el) return;
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    el.className = "enter-alert";
    return;
  }
  const clean = formatApiError(text);
  el.hidden = !clean;
  el.textContent = clean;
  el.className = "enter-alert" + (kind ? " " + kind : "");
}

function $(id) {
  return document.getElementById(id);
}

function structPayload() {
  const text = ($("struct-text").value || "").trim();
  if (!text) return { poscar: "", gen: "" };
  const first = (text.split("\n")[0] || "").trim();
  if (structureKind === "gen" || /^\d+\s+[CcFfSs]/.test(first)) {
    return { poscar: "", gen: text };
  }
  return { poscar: text, gen: "" };
}

function showGate() {
  stopSessionWatch();
  const gate = $("gate");
  const app = $("app");
  if (gate) gate.hidden = false;
  if (app) app.hidden = true;
  document.body.classList.add("is-gate");
  document.body.classList.remove("is-app");
  window.scrollTo(0, 0);
}

function showApp() {
  const gate = $("gate");
  const app = $("app");
  if (gate) gate.hidden = true;
  if (app) app.hidden = false;
  document.body.classList.add("is-app");
  document.body.classList.remove("is-gate");
  window.scrollTo(0, 0);
}

function switchTab(name, opts) {
  if (name === "enter") {
    showGate();
    return;
  }
  const options = opts || {};
  document.querySelectorAll("#app nav button").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === name);
  });
  document.querySelectorAll("#app .panel").forEach((p) => {
    p.classList.toggle("active", p.id === "tab-" + name);
  });
  // skipLoad：调用方会自己 loadProjects（避免与投递后展开详情抢跑）
  if (name === "projects" && !options.skipLoad) loadProjects().catch(() => {});
  if (name === "deploy") {
    refreshDeploy().catch(() => {});
    resumeDeployIfRunning().catch(() => {});
  }
  if (name === "settings") loadSettings().catch(() => {});
  if (name === "courses") loadCourses().catch(() => {});
  if (name === "chat" || name === "home") loadExamples().catch(() => {});
}

document.querySelectorAll("#app nav button").forEach((b) => {
  b.addEventListener("click", () => switchTab(b.dataset.tab));
});

function revealChatLog() {
  const welcome = $("chat-welcome");
  const log = $("chat-log");
  if (welcome) welcome.hidden = true;
  if (log) log.hidden = false;
}

function showHsdPreview(text, meta, opts) {
  const panel = $("hsd-panel");
  const ta = $("hsd-preview");
  const metaEl = $("hsd-meta");
  const body = (text || "").trim();
  const options = opts || {};
  if (options.defaultText != null) hsdDefaultText = String(options.defaultText || "");
  else if (body && !hsdDefaultText) hsdDefaultText = body;
  if (ta) ta.value = body;
  if (metaEl) metaEl.textContent = meta || (body ? "可编辑后确认计算" : "可编辑后确认计算");
  if (panel) panel.hidden = !body;
  const restoreBtn = $("btn-restore-hsd");
  if (restoreBtn) {
    restoreBtn.hidden = !hsdDefaultText;
    restoreBtn.textContent = hsdUserOwned ? "恢复上传原文" : "恢复推荐默认";
  }
  if (options.tips) renderHsdTips(options.tips);
  else if (!body) renderHsdTips([]);
  if (body) $("btn-submit").disabled = false;
}

function renderHsdTips(tips) {
  const box = $("hsd-tips");
  if (!box) return;
  const list = tips || [];
  if (!list.length) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = list
    .map(
      (t) =>
        "<div class='hsd-tip'><strong>" +
        (t.title || t.key || "") +
        "</strong><span>" +
        (t.text || "") +
        "</span></div>"
    )
    .join("");
}

function getEditedHsd() {
  const ta = $("hsd-preview");
  return ta ? (ta.value || "").trim() : "";
}

let genProgressTicker = null;

function stopGenProgressTicker() {
  if (genProgressTicker) {
    clearInterval(genProgressTicker);
    genProgressTicker = null;
  }
}

function setCalcProgress(stage, text) {
  const box = $("calc-progress");
  const fill = $("calc-progress-fill");
  const note = $("calc-progress-text");
  if (!box) return;
  box.hidden = false;
  // 进度条仅覆盖「输入文件生成」阶段
  const order = ["parse", "prepare", "generate", "ready"];
  let mapped = stage;
  if (stage === "preview" || stage === "done") mapped = "ready";
  if (stage === "submit" || stage === "run") mapped = "ready";
  const isError = stage === "error" || mapped === "error";
  const idx = order.indexOf(mapped);
  const widths = { parse: 22, prepare: 48, generate: 76, ready: 100, error: 100 };
  if (fill) fill.style.width = (widths[mapped] || widths.error || 12) + "%";
  const busy = !isError && mapped !== "ready";
  box.classList.toggle("is-busy", busy);
  // 失败时默认标在「生成输入」；若调用方传入具体阶段（少见）则用该阶段
  const errAt = isError ? (idx >= 0 ? idx : order.indexOf("generate")) : -1;
  document.querySelectorAll("#calc-progress-steps li").forEach((li) => {
    const step = li.dataset.step;
    const si = order.indexOf(step);
    li.classList.remove("active", "done", "error");
    if (isError) {
      if (si === errAt) li.classList.add("error");
      else if (si < errAt) li.classList.add("done");
    } else if (si < idx || mapped === "ready") li.classList.add("done");
    else if (si === idx) li.classList.add("active");
  });
  if (note) note.textContent = asDisplayText(text, isError ? "生成输入失败" : "");
}

function hideCalcProgress() {
  stopGenProgressTicker();
  const box = $("calc-progress");
  if (box) box.hidden = true;
}

/** 生成输入期间动态推进进度条，完成后停在「已就绪」。 */
async function withGenerateProgress(workFn) {
  const stages = [
    ["parse", "正在解析计算意图…"],
    ["prepare", "正在准备结构与参数…"],
    ["generate", "正在生成输入文件…"],
  ];
  let i = 0;
  stopGenProgressTicker();
  setCalcProgress(stages[0][0], stages[0][1]);
  genProgressTicker = setInterval(() => {
    if (i < stages.length - 1) {
      i += 1;
      setCalcProgress(stages[i][0], stages[i][1]);
    }
  }, 420);
  try {
    const result = await workFn();
    stopGenProgressTicker();
    return result;
  } catch (e) {
    stopGenProgressTicker();
    throw e;
  }
}

function showJobProgress(status, note, logText) {
  const box = $("job-progress");
  if (!box) return;
  box.hidden = false;
  const label = $("job-status-label");
  const noteEl = $("job-progress-note");
  const logEl = $("job-log");
  const chips = $("job-status-chips");
  const st = (status || "unknown").toLowerCase();
  const map = {
    pending: "排队中",
    running: "计算中",
    done: "已完成",
    error: "失败",
    cancelled: "已取消",
    not_found: "未找到作业",
    unknown: "未知",
  };
  if (label) label.textContent = map[st] || st || "—";
  if (noteEl) noteEl.textContent = asDisplayText(note, "");
  if (logEl) logEl.textContent = asDisplayText(logText, "");
  if (chips) {
    const stages = [
      ["pending", "排队"],
      ["running", "运行"],
      ["done", "完成"],
    ];
    chips.innerHTML = "";
    stages.forEach(([key, name]) => {
      const span = document.createElement("span");
      span.className = "job-chip";
      span.textContent = name;
      if (st === "error" && key === "running") span.classList.add("err");
      else if (st === "done") span.classList.add("done");
      else if (st === key) span.classList.add("on");
      else if (
        (st === "running" && key === "pending") ||
        (st === "done" && (key === "pending" || key === "running"))
      ) {
        span.classList.add("done");
      }
      chips.appendChild(span);
    });
  }
}

function hideJobProgress() {
  const box = $("job-progress");
  if (box) box.hidden = true;
  const logEl = $("job-log");
  if (logEl) logEl.textContent = "";
}

function clearChatLog() {
  const log = $("chat-log");
  const welcome = $("chat-welcome");
  if (log) {
    log.innerHTML = "";
    log.hidden = true;
  }
  if (welcome) welcome.hidden = false;
}

function clearStructurePanel() {
  if ($("struct-text")) $("struct-text").value = "";
  structureKind = "poscar";
  structureUserOwned = false;
  renderStructureViewer("calc");
}

/** 新指令是否点名了内置/示例材料——若是则勿再提交上一任务残留结构。 */
function promptRequestsKnownMaterial(msg) {
  const t = msg || "";
  return /硅|石墨烯|石墨|水分子|\bH2O\b|\bh2o\b|苯|C6H6|c6h6|甲烷|CH4|氨|NH3|甲醛|H2CO|graphene|silicon|benzene|空位|缺陷|二硫化钼|MoS2|纳米带|nanoribbon|钝化/i.test(
    t
  );
}

function applyPreviewStructure(preview) {
  if (!preview || !$("struct-text")) return false;
  const files = preview.files || {};
  const poscar = preview.poscar || files.POSCAR || files.poscar || "";
  const gen = preview.gen || files["geo.gen"] || "";
  if (poscar) {
    $("struct-text").value = poscar;
    structureKind = "poscar";
    renderStructureViewer("calc");
    return true;
  }
  if (gen) {
    $("struct-text").value = gen;
    structureKind = "gen";
    renderStructureViewer("calc");
    return true;
  }
  if (preview.used_default_water) {
    // 后端应带回 geo.gen；若无则至少清掉旧晶体残留
    clearStructurePanel();
    return true;
  }
  return false;
}

function clearCalcPage() {
  stopGenProgressTicker();
  if (autoPreviewTimer) {
    clearTimeout(autoPreviewTimer);
    autoPreviewTimer = null;
  }
  autoPreviewBusy = false;
  lastAutoPreviewKey = "";
  hsdDefaultText = "";
  hsdUserOwned = false;
  hsdUploadName = "";
  clearChatLog();
  if ($("chat-input")) $("chat-input").value = "";
  showHsdPreview("");
  renderHsdTips([]);
  if ($("btn-submit")) $("btn-submit").disabled = true;
  clearStructurePanel();
  hideCalcProgress();
  hideJobProgress();
  courseHints = { family: "", kind: "" };
  hintPrompt = "";
  currentProjectId = "";
}

function addBubble(text, who) {
  text = asDisplayText(text, "");
  revealChatLog();
  const el = document.createElement("div");
  el.className = "bubble " + who;
  el.textContent = text;
  $("chat-log").appendChild(el);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
}

function setBusyButton(btn, busy, busyText, idleText) {
  if (!btn) return;
  btn.disabled = !!busy;
  if (busyText || idleText) btn.textContent = busy ? busyText : idleText;
}

function applyPalette(name) {
  const palette = name || localStorage.getItem("dftb-neu-palette") || "teal";
  document.documentElement.setAttribute("data-palette", palette);
  localStorage.setItem("dftb-neu-palette", palette);
  document.querySelectorAll(".theme-card").forEach((btn) => {
    const on = btn.dataset.palette === palette;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function envCardText(raw, fallback) {
  const t = String(raw || "").replace(/\u0000/g, "").trim();
  if (!t) return fallback;
  const bad = (t.match(/\uFFFD/g) || []).length;
  if (bad >= 2 || /wsl\.exe --install|aka\.ms\/wslinstall/i.test(t)) return fallback;
  return t.length > 80 ? t.slice(0, 80) + "…" : t;
}

function envLogLooksGarbled(raw) {
  const t = String(raw || "");
  if (!t.trim()) return false;
  if ((t.match(/\uFFFD/g) || []).length >= 2) return true;
  if (/([\u4e00-\u9fff]{2,4})\1{3,}/.test(t)) return true;
  if (/瀹夎|澶辫触|å®è£|å¤±è´¥/.test(t)) return true;
  const cjk = (t.match(/[\u4e00-\u9fff]/g) || []).length;
  const latin = (t.match(/[A-Za-z]/g) || []).length;
  return t.length > 40 && cjk > t.length * 0.65 && latin < 8;
}

function envLogText(message, tail) {
  const msg = String(message || "").replace(/\u0000/g, "").trim();
  const raw = String(tail || "").replace(/\u0000/g, "");
  const junk =
    envLogLooksGarbled(raw) || /wsl\.exe --install|aka\.ms\/wslinstall/i.test(raw);
  const clean = junk ? "" : raw.trim();
  if (msg && clean) return msg + "\n\n" + clean;
  if (msg && junk) return msg + "\n\n（安装日志编码无法显示，请看上方三项状态。）";
  return msg || clean || "部署未完成。请再点「部署到本机」。";
}

function setCheckItem(id, ok, text, pending) {
  const el = $(id);
  if (!el) return;
  const state = pending ? "pending" : ok ? "ok" : "bad";
  el.className = "check-item " + state;
  el.querySelector(".dot").textContent = pending ? "…" : ok ? "✓" : "·";
  const p = el.querySelector("p");
  if (p) p.textContent = text;
}

function setStatusItem(id, { ok, warn, label }) {
  const el = $(id);
  if (!el) return;
  const dot = el.querySelector(".status-dot");
  const lab = el.querySelector(".status-label");
  if (lab && label != null) lab.textContent = label;
  if (dot) {
    dot.classList.toggle("ok", !!ok);
    dot.classList.toggle("warn", !ok && !!warn);
  }
}

function paintEnvPill(readiness) {
  const r = readiness || {};
  const ready = !!r.environment_ready && !r.deploying;
  setStatusItem("status-soft", { ok: ready, warn: !ready, label: "环境" });
}

async function refreshStatusPill() {
  const pill = $("status-pill");
  if (!pill) return;
  try {
    const st = await api("/api/status");
    const settings = st.settings || {};
    const llmOk = !!(st.llm && st.llm.ok) || !!settings.api_key_set || !!settings.llm_api_key_set;
    const lic = st.license || {};
    const licOk = !!lic.activated;
    setStatusItem("status-login", { ok: licOk, warn: !licOk, label: licOk ? "已登录" : "未登录" });
    setStatusItem("status-llm", { ok: llmOk, warn: !llmOk, label: "AI" });
    paintEnvPill((st.deploy && st.deploy.readiness) || {});
    pill.className = "status-pill " + (licOk ? "ok" : "warn");
  } catch (e) {
    setStatusItem("status-login", { ok: false, warn: true, label: "未连接" });
    setStatusItem("status-llm", { ok: false, warn: true, label: "AI" });
    setStatusItem("status-soft", { ok: false, warn: true, label: "环境" });
    pill.className = "status-pill warn";
  }
}

function flashSection(id) {
  const el = $(id);
  if (!el) return;
  el.classList.remove("flash-target");
  void el.offsetWidth;
  el.classList.add("flash-target");
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  setTimeout(() => el.classList.remove("flash-target"), 1800);
}

function jumpStatus(target) {
  if (target === "llm") {
    switchTab("settings");
    setTimeout(() => {
      flashSection("settings-llm");
      const key = $("deepseek-key");
      if (key) key.focus();
    }, 40);
    return;
  }
  if (target === "soft") {
    switchTab("deploy");
    setTimeout(() => flashSection("deploy-checks"), 40);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function enterWorkspace(preferredTab) {
  showApp();
  startSessionWatch();
  try {
    await refreshStatusPill();
  } catch (_) {
    /* ignore */
  }
  try {
    await loadExamples();
  } catch (_) {
    /* ignore */
  }
  // 默认留在主页，不主动跳到环境页
  switchTab(preferredTab || "home");
}

async function launchFromHome(sendNow) {
  const homeInput = $("home-nl-input");
  const message = homeInput ? homeInput.value.trim() : "";
  switchTab("chat");
  const chat = $("chat-input");
  if (message && chat) {
    chat.value = message;
    // 避免随后自动预览用旧 key 跳过，或清空输入
    lastAutoPreviewKey = "";
    if (sendNow) {
      await previewOnly({ quiet: false, fresh: true });
      // 再次确保首页文案仍在输入框
      if (chat && !chat.value.trim()) chat.value = message;
    } else {
      chat.focus();
    }
  } else if (chat) {
    chat.focus();
  }
}

async function bootstrapSession() {
  let unlocked = false;
  try {
    const data = await api("/api/license");
    const lic = data.license || {};
    const check = data.check || {};
    unlocked = !!(lic.activated && check.ok);
  } catch (_) {
    unlocked = false;
  }
  if (unlocked) {
    await enterWorkspace();
    return;
  }
  showGate();
  setEnterMessage("", "");
}

async function doLogin(ev) {
  if (ev) ev.preventDefault();
  const btn = $("btn-enter");
  if (btn && btn.disabled) return;
  const sid = ($("student-id").value || "").trim();
  const code = ($("class-code").value || "").trim();
  if (!sid) {
    setEnterMessage("请填写学号", "err");
    return;
  }
  if (!code) {
    setEnterMessage("请填写本堂密码", "err");
    return;
  }
  if (btn) btn.disabled = true;
  setEnterMessage("正在验证…", "pending");
  try {
    await api("/api/license/activate", {
      method: "POST",
      body: JSON.stringify({ code, student_id: sid }),
    });
    setEnterMessage("登录成功，正在进入工作台…", "ok");
    await enterWorkspace("home");
    // 进入工作台后再清空，避免登录成功瞬间密码栏闪成空白
    if ($("class-code")) $("class-code").value = "";
  } catch (e) {
    setEnterMessage(e.message || "登录失败", "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

$("enter-form").addEventListener("submit", doLogin);
$("btn-logout").addEventListener("click", async () => {
  stopSessionWatch();
  try {
    await api("/api/license/clear", { method: "POST", body: "{}" });
  } catch (_) {
    /* ignore */
  }
  showGate();
  setEnterMessage("", "");
});

async function loadCourses() {
  const box = $("course-list");
  if (!box) return;
  box.innerHTML = "<p class='muted-block'>加载课次…</p>";
  try {
    const data = await api("/api/courses");
    const course = (data.courses || [])[0];
    if (!course) {
      box.innerHTML = "<p class='muted-block'>暂无课程数据。</p>";
      return;
    }
    box.innerHTML = "";
    const head = document.createElement("div");
    head.className = "section course-intro";
    head.innerHTML =
      "<div class='section-head'><div><h2>" +
      (course.title || "固体物理课堂演示") +
      "</h2><p>" +
      (course.description || "") +
      "</p>" +
      (course.curriculum_note
        ? "<p class='course-curriculum'>" + course.curriculum_note + "</p>"
        : "") +
      "</div></div>";
    box.appendChild(head);
    (course.lessons || []).forEach((L) => {
      const card = document.createElement("article");
      card.className = "course-card";
      const objs = (L.objectives || []).slice(0, 3);
      const objHtml = objs.length
        ? "<ul class='course-objectives'>" +
          objs.map((o) => "<li>" + o + "</li>").join("") +
          "</ul>"
        : "";
      card.innerHTML =
        "<div class='course-card-top'>" +
        "<div class='course-index'>第 " +
        (L.index || "") +
        " 课</div>" +
        (L.chapter ? "<div class='course-chapter'>" + L.chapter + "</div>" : "") +
        "</div>" +
        "<h3>" +
        (L.title || "") +
        "</h3>" +
        "<p class='course-topic'>" +
        (L.topic || "") +
        "</p>" +
        (L.knowledge ? "<p class='course-knowledge'>" + L.knowledge + "</p>" : "") +
        objHtml +
        (L.quiz ? "<p class='course-quiz'>思考：" + L.quiz + "</p>" : "");
      const actions = document.createElement("div");
      actions.className = "course-actions";
      const btnGen = document.createElement("button");
      btnGen.type = "button";
      btnGen.className = "btn btn-primary";
      btnGen.textContent = "一键复现";
      btnGen.title = "载入课例结构并生成 HSD，核对后确认计算";
      btnGen.addEventListener("click", () => runLessonRecipe(L.id));
      const genDesc = document.createElement("p");
      genDesc.className = "course-action-desc";
      genDesc.textContent = "载入结构、生成输入文件，核对后即可确认计算";
      actions.appendChild(btnGen);
      actions.appendChild(genDesc);
      card.appendChild(actions);
      box.appendChild(card);
    });
  } catch (e) {
    box.innerHTML = "<p class='msg err'>" + e.message + "</p>";
  }
}

function applyLessonContext(data) {
    if (data.poscar) {
      $("struct-text").value = data.poscar;
      structureKind = "poscar";
      renderStructureViewer("calc");
    }
    courseHints = { family: data.family || "", kind: data.kind || "" };
    hintPrompt = data.prompt || "";
    $("chat-input").value = hintPrompt;
  if (data.lesson) {
    const L = data.lesson;
    const lines = [];
    if (L.chapter) lines.push(L.chapter);
    if (L.topic) lines.push("主题：" + L.topic);
    if (L.knowledge) lines.push(L.knowledge);
    if ((L.expected_observables || []).length) {
      lines.push("课堂观察：" + L.expected_observables.join("、"));
    }
    if (L.quiz) lines.push("思考：" + L.quiz);
    if (lines.length) addBubble(lines.join("\n"), "bot");
  }
}

function beginFreshCalcSession() {
  /** 课程一键复现 / 新课例：清空计算页旧对话、HSD、进度与结构残留。 */
  stopGenProgressTicker();
  if (autoPreviewTimer) {
    clearTimeout(autoPreviewTimer);
    autoPreviewTimer = null;
  }
  autoPreviewBusy = false;
  lastAutoPreviewKey = "";
  currentProjectId = "";
  courseHints = { family: "", kind: "" };
  hintPrompt = "";
  resetPreviewOutputs();
  clearStructurePanel();
  hideCalcProgress();
  if ($("chat-input")) $("chat-input").value = "";
}

async function startLesson(lessonId) {
  try {
    beginFreshCalcSession();
    switchTab("chat");
    const data = await api("/api/courses/lessons/" + lessonId + "/start", { method: "POST", body: "{}" });
    addBubble(data.message || "已载入课次。", "bot");
    applyLessonContext(data);
    if (!data.structure_ready && data.needs_structure) {
      addBubble("本课次需要结构：请上传 POSCAR / GEN，或在自然语言中说明由 Materials Project 获取后再预览/计算。", "bot");
    }
  } catch (e) {
    addBubble("载入课次失败：" + e.message, "bot");
    switchTab("chat");
  }
}

async function runLessonRecipe(lessonId) {
  try {
    beginFreshCalcSession();
    switchTab("chat");
    const data = await withGenerateProgress(() =>
      api("/api/courses/lessons/" + lessonId + "/recipe", {
        method: "POST",
        body: "{}",
      })
    );
    addBubble(data.message || "已生成课例输入文件。", "bot");
    applyLessonContext(data);
    if (data.project_id) currentProjectId = data.project_id;
    if (data.preview && data.preview.hsd_preview) {
      hsdUserOwned = false;
      hsdUploadName = "";
      const mp = data.preview.mp || {};
      const mat = data.preview.maturity || {};
      const allowSubmit = data.preview.allow_submit !== false;
      const metaBits = [];
      if (data.preview.sk_set) metaBits.push("SK：" + data.preview.sk_set);
      if (mat.label) metaBits.push("状态：" + mat.label);
      const srcLabel = structureSourceLabel(mp);
      if (srcLabel) metaBits.push(srcLabel);
      metaBits.push(allowSubmit ? "课例输入已生成" : "仅预览（未闭环）");
      showHsdPreview(data.preview.hsd_preview, metaBits.join(" · "), {
        defaultText: data.preview.hsd_default || data.preview.hsd_preview,
        tips: data.preview.param_tips || [],
      });
      $("btn-submit").disabled = !allowSubmit;
      if (allowSubmit) {
        setCalcProgress("ready", "输入文件已就绪，可编辑后确认计算。");
      } else {
        setCalcProgress(
          "error",
          asDisplayText(data.preview.message || mat.note, "该功能尚未闭环")
        );
      }
    } else {
      setCalcProgress("error", data.message || "未能生成课例输入");
    }
  } catch (e) {
    addBubble("生成输入文件失败：" + e.message, "bot");
    setCalcProgress("error", e.message || "生成输入文件失败");
    switchTab("chat");
  }
}

async function loadExamples() {
  try {
    const data = await api("/api/examples");
    const solid = $("examples-solid");
    const research = $("examples-research");
    if (!solid || !research) return;
    solid.innerHTML = "";
    research.innerHTML = "";
    (data.examples || []).forEach((ex) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = ex.title;
      btn.title = ex.prompt;
      btn.addEventListener("click", () => {
        courseHints = {
          family: ex.family || "",
          kind: ex.kind || "",
        };
        hintPrompt = ex.prompt || "";
        $("chat-input").value = hintPrompt;
        previewOnly({ quiet: false, fresh: true }).catch(() => {});
      });
      (ex.group === "research" ? research : solid).appendChild(btn);
    });
  } catch (e) {
    /* ignore */
  }
}

async function sendChat(confirm) {
  const message = $("chat-input").value.trim();
  const hsd = getEditedHsd();
  if (!message && !confirm) return;
  if (confirm && !hsd) {
    addBubble("请先点「生成输入」，或上传自己的 HSD 输入文件。", "bot");
    return;
  }
  // 非确认：走生成进度条；确认投递后用作业进度区，不再推进生成进度条
  if (!confirm) {
    await previewOnly({ quiet: false });
    return;
  }
  const st = structPayload();
  const submitBtn = $("btn-submit");
  setBusyButton(submitBtn, true, "投递中…", "确认计算");
  showJobProgress("pending", "正在投递本机作业…", "");
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message: message || (hsdUserOwned ? "使用自写输入文件" : "确认计算"),
        project_id: currentProjectId || "",
        confirm_submit: true,
        poscar: st.poscar || "",
        gen: st.gen || "",
        hsd: hsd || "",
        user_hsd: !!hsdUserOwned,
        family: courseHints.family || "",
        kind: courseHints.kind || "",
      }),
    });
    if (data.project_id) currentProjectId = data.project_id;
    addBubble(data.reply || JSON.stringify(data), "bot");
    if (data.ok && data.job_id) {
      $("btn-submit").disabled = true;
      // 生成进度条保持「已就绪」，作业进度看下方作业区
      setCalcProgress("ready", "输入文件已就绪；作业已投递，请到「任务」页查看进度。");
      showJobProgress("pending", "作业已提交，等待 DFTB+ 启动…", "");
      addBubble("作业已提交，正在跳转到任务页跟踪进度。", "bot");
      const pid = currentProjectId;
      const jid = data.job_id;
      // 投递成功即进任务页并展开详情（计算中即可看日志/进度，不必等完成）
      switchTab("projects", { skipLoad: true });
      try {
        if (pid) taskDetailCache.delete(pid);
        await loadProjects();
        if (pid) {
          await ensureListedProject(pid);
          await showProject(pid, { force: true });
          startTaskWatch(pid);
        }
      } catch (_) {
        try {
          if (pid) {
            await ensureListedProject(pid);
            await showProject(pid, { force: true });
            startTaskWatch(pid);
          }
        } catch (__) {
          /* 列表失败时仍尽量把当前作业挂上 */
        }
      }
      pollProject(pid, jid);
    } else if (data.ok === false) {
      showJobProgress("error", asDisplayText(data.reply, "投递失败"), "");
    }
  } catch (e) {
    const errText = asDisplayText(e && e.message, "投递失败");
    addBubble("错误：" + errText, "bot");
    showJobProgress("error", errText, "");
  } finally {
    if (submitBtn && !$("btn-submit").disabled) setBusyButton(submitBtn, false, null, "确认计算");
    else if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "确认计算";
    }
  }
}

function resetPreviewOutputs() {
  clearChatLog();
  showHsdPreview("");
  renderHsdTips([]);
  hideJobProgress();
  if ($("btn-submit")) $("btn-submit").disabled = true;
  hsdDefaultText = "";
  hsdUserOwned = false;
  hsdUploadName = "";
}

async function previewOnly(opts) {
  const options = opts || {};
  const quiet = !!options.quiet;
  const fresh = !!options.fresh;
  const message = ($("chat-input").value || "").trim();
  if (!message) return;
  if (autoPreviewBusy) return;
  // 主动发起的新计算：新开任务，避免沿用上一作业的 project / 结构残留
  const startNew = !quiet || fresh;
  let st = structPayload();
  if (startNew) {
    currentProjectId = "";
    resetPreviewOutputs();
    // 合理流程：自然语言先生成结构；用户上传覆盖后再次生成时保留上传结构
    if (structureUserOwned && (st.poscar || st.gen)) {
      st = structPayload();
    } else if (fresh || promptRequestsKnownMaterial(message)) {
      clearStructurePanel();
      st = { poscar: "", gen: "" };
    } else {
      st = structPayload();
    }
  }
  const key = message + "||" + (st.poscar || st.gen || "") + "||" + (courseHints.kind || "");
  if (quiet && key === lastAutoPreviewKey) return;
  autoPreviewBusy = true;
  if (!quiet) addBubble(message, "user");
  try {
    const data = await withGenerateProgress(() =>
      api("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          message,
          project_id: currentProjectId || "",
          confirm_submit: false,
          poscar: st.poscar || "",
          gen: st.gen || "",
          family: courseHints.family || "",
          kind: courseHints.kind || "",
        }),
      })
    );
    if (data.project_id) currentProjectId = data.project_id;
    if (!quiet) addBubble(data.reply || "已生成输入文件", "bot");
    // 用户已上传覆盖时，勿再用后端近似模板冲掉面板
    if (data.preview && !structureUserOwned) applyPreviewStructure(data.preview);
    if (
      !quiet &&
      data.preview &&
      (data.preview.structure_approximate || (data.preview.mp && data.preview.mp.approximate))
    ) {
      const note =
        (data.preview.message ||
          (data.preview.mp && data.preview.mp.approx_note) ||
          "当前为系统近似结构；若不满意请上传 GEN/POSCAR 覆盖。").trim();
      addBubble(note, "bot");
    }
    if (data.preview && data.preview.needs_structure && !data.preview.ok) {
      showHsdPreview("");
      if ($("btn-submit")) $("btn-submit").disabled = true;
      setCalcProgress(
        "error",
        asDisplayText(data.preview.message || data.reply, "需要结构文件")
      );
      return;
    }
    if (data.preview && data.preview.hsd_preview) {
      hsdUserOwned = false;
      hsdUploadName = "";
      const mp = data.preview.mp || {};
      const mat = data.preview.maturity || {};
      const allowSubmit = data.preview.allow_submit !== false;
      const metaBits = [];
      if (data.preview.sk_set) metaBits.push("SK：" + data.preview.sk_set);
      if (mat.label) metaBits.push("状态：" + mat.label);
      const srcLabel = structureSourceLabel(mp);
      if (srcLabel) metaBits.push(srcLabel);
      metaBits.push(allowSubmit ? "可编辑" : "仅预览");
      showHsdPreview(data.preview.hsd_preview, metaBits.join(" · "), {
        defaultText: data.preview.hsd_default || data.preview.hsd_preview,
        tips: data.preview.param_tips || [],
      });
      if ($("btn-submit")) $("btn-submit").disabled = !allowSubmit;
      if (allowSubmit) {
        setCalcProgress("ready", "输入文件已生成，可编辑后点击下方「确认计算」。");
        if (!quiet) addBubble("已生成 DFTB+ 输入文件（HSD）。可编辑后确认计算。", "bot");
      } else {
        const why =
          (data.preview.message || mat.note || data.reply || "该功能尚未闭环，暂不可投递。").trim();
        setCalcProgress("error", asDisplayText(why, "该功能尚未闭环"));
        if (!quiet) addBubble(why, "bot");
      }
      lastAutoPreviewKey =
        message +
        "||" +
        (structPayload().poscar || structPayload().gen || "") +
        "||" +
        (courseHints.kind || "");
    } else {
      setCalcProgress("error", asDisplayText(data.reply, "未能生成输入文件"));
    }
    // 保留自然语言输入，不在生成后清空
    if ($("chat-input") && message) $("chat-input").value = message;
  } catch (e) {
    const errText = asDisplayText(e && e.message, "生成输入失败");
    if (!quiet) addBubble("生成输入失败：" + errText, "bot");
    setCalcProgress("error", errText);
  } finally {
    autoPreviewBusy = false;
  }
}

function scheduleAutoPreview() {
  if (hsdUserOwned) return;
  if (autoPreviewTimer) clearTimeout(autoPreviewTimer);
  autoPreviewTimer = setTimeout(() => {
    const msg = ($("chat-input").value || "").trim();
    if (msg.length < 4) return;
    previewOnly({ quiet: true }).catch(() => {});
  }, 700);
}

const btnSubmit = $("btn-submit");
if (btnSubmit) btnSubmit.addEventListener("click", () => sendChat(true));
const btnNlSubmit = $("btn-nl-submit");
if (btnNlSubmit) {
  btnNlSubmit.addEventListener("click", async () => {
    const msg = ($("chat-input").value || "").trim();
    if (!msg) {
      addBubble("请先输入自然语言任务描述。", "bot");
      return;
    }
    setBusyButton(btnNlSubmit, true, "生成中…", "生成输入");
    try {
      await previewOnly({ quiet: false, fresh: true });
    } finally {
      setBusyButton(btnNlSubmit, false, null, "生成输入");
    }
  });
}
$("chat-input").addEventListener("input", () => {
  if (!courseHints.family && !courseHints.kind) {
    /* keep */
  } else {
    const v = ($("chat-input").value || "").trim();
    if (v !== (hintPrompt || "").trim()) {
      courseHints = { family: "", kind: "" };
      hintPrompt = "";
    }
  }
});
$("chat-input").addEventListener("keydown", (ev) => {
  if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
    ev.preventDefault();
    if (btnNlSubmit) btnNlSubmit.click();
  }
});

const btnRestoreHsd = $("btn-restore-hsd");
if (btnRestoreHsd) {
  btnRestoreHsd.addEventListener("click", () => {
    if (!hsdDefaultText) return;
    showHsdPreview(hsdDefaultText, "已恢复推荐默认 · 可继续编辑");
    if ($("btn-submit")) $("btn-submit").disabled = false;
    addBubble(
      hsdUserOwned ? "已恢复你上传的输入文件原文。" : "已恢复本次预览生成的推荐 HSD。",
      "bot"
    );
  });
}

function looksLikePoscar(text) {
  const lines = (text || "").split(/\r?\n/).filter((l) => l.trim().length);
  if (lines.length < 8) return false;
  if (!/^\s*[-+]?\d/.test(lines[1] || "")) return false;
  return true;
}

function looksLikeGen(text) {
  const t = (text || "").replace(/^\uFEFF/, "").trim();
  if (!t) return false;
  const first = t.split(/\r?\n/)[0] || "";
  return /^\s*\d+\s+[CSFcfs]\b/.test(first);
}

function looksLikeHsd(text) {
  const t = (text || "").trim();
  if (!t) return false;
  return /Hamiltonian\s*=|Geometry\s*=|Driver\s*=|ParserOptions|MaxAngularMomentum|SlaterKosterFiles/i.test(
    t
  );
}

function hsdReferencesStructureFile(text) {
  return /Geometry\s*=\s*\w+\s*\{[^}]*<<</i.test(text || "");
}

/** 轻微后略转视角，避免平面分子沿默认 z 向投影重叠（如旧版 H2O）。 */
function applyMolViewerCamera(viewer) {
  if (!viewer) return;
  try {
    viewer.zoomTo();
    viewer.rotate(28, "x");
    viewer.rotate(18, "y");
    viewer.render();
    viewer.zoom(1.05, 200);
  } catch (_) {
    try {
      viewer.zoomTo();
      viewer.render();
    } catch (__) {
      /* ignore */
    }
  }
}

function parseGen(text) {
  // DFTB+ GenFormat：N C|S|F → 元素 → N 行原子 →（S/F）原点 + 3 晶格向量
  const lines = (text || "")
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines.length < 2) return null;
  const head = lines[0].split(/\s+/).filter(Boolean);
  const n = parseInt(head[0], 10);
  if (!n || n < 1) return null;
  const mode = (head[1] || "C").toUpperCase().slice(0, 1);
  let idx = 1;
  const species = (lines[idx++] || "").split(/\s+/).filter(Boolean);
  const coords = [];
  for (let i = 0; i < n && idx < lines.length; i++, idx++) {
    const parts = lines[idx].split(/\s+/).filter(Boolean);
    let sp = "X";
    let x = NaN;
    let y = NaN;
    let z = NaN;
    if (parts.length >= 5) {
      sp = species[(parseInt(parts[1], 10) || 1) - 1] || "X";
      x = parseFloat(parts[2]);
      y = parseFloat(parts[3]);
      z = parseFloat(parts[4]);
    } else if (parts.length >= 4) {
      sp = species[(parseInt(parts[0], 10) || 1) - 1] || parts[0];
      x = parseFloat(parts[1]);
      y = parseFloat(parts[2]);
      z = parseFloat(parts[3]);
    } else {
      continue;
    }
    if ([x, y, z].some((v) => Number.isNaN(v))) continue;
    coords.push({ sp, x, y, z, fx: x, fy: y, fz: z });
  }
  if (!coords.length) return null;
  let lattice = null;
  let origin = [0, 0, 0];
  if ((mode === "S" || mode === "F") && lines.length - idx >= 4) {
    origin = lines[idx++]
      .split(/\s+/)
      .map(Number)
      .slice(0, 3);
    lattice = [0, 1, 2].map(() =>
      lines[idx++]
        .split(/\s+/)
        .map(Number)
        .slice(0, 3)
    );
    if (lattice.some((row) => row.length < 3 || row.some((v) => Number.isNaN(v)))) {
      lattice = null;
    }
  }
  if (lattice && mode === "F") {
    for (const c of coords) {
      const x = c.fx;
      const y = c.fy;
      const z = c.fz;
      c.x = origin[0] + x * lattice[0][0] + y * lattice[1][0] + z * lattice[2][0];
      c.y = origin[1] + x * lattice[0][1] + y * lattice[1][1] + z * lattice[2][1];
      c.z = origin[2] + x * lattice[0][2] + y * lattice[1][2] + z * lattice[2][2];
    }
  } else if (lattice && mode === "S") {
    for (const c of coords) {
      c.x += origin[0] || 0;
      c.y += origin[1] || 0;
      c.z += origin[2] || 0;
    }
  }
  return { n: coords.length, mode, species, coords, lattice, origin };
}

function genFormula(parsed) {
  if (!parsed || !parsed.coords) return "";
  const counts = {};
  parsed.coords.forEach((c) => {
    counts[c.sp] = (counts[c.sp] || 0) + 1;
  });
  const keys = Object.keys(counts);
  let g = 0;
  keys.forEach((s) => {
    g = g ? gcdInt(g, counts[s]) : counts[s];
  });
  if (g < 1) g = 1;
  return keys
    .map((s) => {
      const n = counts[s] / g;
      return n > 1 ? s + n : s;
    })
    .join("");
}

function gcdInt(a, b) {
  a = Math.abs(a);
  b = Math.abs(b);
  while (b) {
    const t = b;
    b = a % b;
    a = t;
  }
  return a || 1;
}

function latticeConstant(row) {
  if (!row || row.length < 3) return 0;
  return Math.sqrt(row[0] * row[0] + row[1] * row[1] + row[2] * row[2]);
}

function genToXyz(text) {
  const parsed = typeof text === "object" && text && text.coords ? text : parseGen(text);
  if (!parsed) return "";
  let out = parsed.coords.length + "\nDFTB-NEU\n";
  parsed.coords.forEach((c) => {
    out += c.sp + " " + c.x + " " + c.y + " " + c.z + "\n";
  });
  return out;
}

function genToPoscar(text) {
  const parsed = typeof text === "object" && text && text.coords ? text : parseGen(text);
  if (!parsed || !parsed.lattice) return "";
  const order = [];
  const counts = {};
  parsed.coords.forEach((c) => {
    if (!counts[c.sp]) {
      counts[c.sp] = 0;
      order.push(c.sp);
    }
    counts[c.sp] += 1;
  });
  const formula = genFormula(parsed) || "GEN";
  let out = formula + "\n1.0\n";
  parsed.lattice.forEach((row) => {
    out += row.map((x) => Number(x).toPrecision(12)).join("  ") + "\n";
  });
  out += order.join(" ") + "\n";
  out += order.map((s) => counts[s]).join(" ") + "\n";
  if (parsed.mode === "F") {
    out += "Direct\n";
    parsed.coords.forEach((c) => {
      out += c.fx + " " + c.fy + " " + c.fz + "\n";
    });
  } else {
    out += "Cartesian\n";
    parsed.coords.forEach((c) => {
      out += c.x + " " + c.y + " " + c.z + "\n";
    });
  }
  return out;
}

function prepareStructureModel(text, kindHint) {
  const raw = (text || "").trim();
  if (!raw) return null;
  if (looksLikeGen(raw) || kindHint === "gen") {
    const parsed = parseGen(raw);
    if (!parsed) return { error: "无法解析 GEN 结构" };
    if (parsed.lattice) {
      const poscar = genToPoscar(parsed);
      if (!poscar) return { error: "无法解析 GEN 晶格" };
      const a = latticeConstant(parsed.lattice[0]);
      const replicate = parsed.coords.length <= 32 ? 2 : 0;
      const bits = [genFormula(parsed) || "GEN", parsed.coords.length + " 原子"];
      if (parsed.mode === "F") bits.push("分数坐标");
      if (a > 0.2) bits.push("a=" + a.toFixed(2) + " Å");
      if (replicate) bits.push("显示 " + replicate + "×" + replicate + "×" + replicate);
      bits.push("可拖拽旋转");
      return { data: poscar, format: "vasp", parsed, replicate, caption: bits.join(" · ") };
    }
    return {
      data: genToXyz(parsed),
      format: "xyz",
      parsed,
      replicate: 0,
      caption: (genFormula(parsed) || "结构") + " · 分子 · 可拖拽旋转",
    };
  }
  if (looksLikePoscar(raw) || kindHint === "poscar") {
    return { data: raw, format: "vasp", replicate: 0, caption: "POSCAR · 球棍模型 · 可拖拽旋转" };
  }
  return { data: raw, format: "xyz", replicate: 0, caption: "结构 · 球棍模型 · 可拖拽旋转" };
}

function molViewerStyle() {
  return {
    stick: { radius: 0.12, colorscheme: "Jmol" },
    sphere: { scale: 0.22, colorscheme: "Jmol" },
  };
}

function renderStructureViewer(which, textOverride, kindOverride) {
  const isTask = which === "task";
  const wrap = $(isTask ? "task-struct-viewer-wrap" : "struct-viewer-wrap");
  const el = $(isTask ? "task-struct-viewer" : "struct-viewer");
  const caption = isTask ? null : $("struct-viewer-caption");
  if (!wrap || !el) return;
  const text = (textOverride != null ? textOverride : ($("struct-text") && $("struct-text").value) || "").trim();
  if (!text) {
    wrap.hidden = true;
    if (caption) caption.textContent = "";
    return;
  }
  if (typeof $3Dmol === "undefined") {
    wrap.hidden = false;
    el.innerHTML = "<p class='muted-inline'>结构可视化库未加载</p>";
    return;
  }
  wrap.hidden = false;
  const prepared = prepareStructureModel(text, kindOverride || structureKind);
  if (!prepared || prepared.error) {
    el.innerHTML = "<p class='muted-inline'>" + ((prepared && prepared.error) || "无法解析结构") + "</p>";
    if (caption) caption.textContent = "";
    return;
  }
  const format = prepared.format;
  const data = prepared.data;
  try {
    el.innerHTML = "";
    const viewer = $3Dmol.createViewer(el, {
      backgroundColor: "#f4f7f8",
      antialias: true,
    });
    viewer.addModel(data, format);
    if (prepared.replicate && format === "vasp") {
      try {
        viewer.replicateUnitCell(prepared.replicate, prepared.replicate, prepared.replicate);
      } catch (_) {
        /* optional */
      }
    }
    viewer.setStyle({}, molViewerStyle());
    try {
      if (format === "vasp") viewer.addUnitCell({ box: { color: "0x6a7d89" } });
    } catch (_) {
      /* unit cell optional */
    }
    applyMolViewerCamera(viewer);
    structViewers[isTask ? "task" : "calc"] = viewer;
    if (caption) caption.textContent = prepared.caption || "结构 · 球棍模型 · 可拖拽旋转";
    setTimeout(() => {
      try {
        viewer.resize();
        viewer.render();
      } catch (_) {
        /* ignore */
      }
    }, 80);
  } catch (e) {
    el.innerHTML = "<p class='muted-inline'>结构预览失败：" + (e.message || e) + "</p>";
  }
}

const structTextEl = $("struct-text");
if (structTextEl) {
  structTextEl.addEventListener("input", () => {
    const t = structTextEl.value || "";
    if (looksLikeGen(t)) structureKind = "gen";
    else if (looksLikePoscar(t)) structureKind = "poscar";
    renderStructureViewer("calc");
    scheduleAutoPreview();
  });
}
const btnClearAll = $("btn-clear-all");
if (btnClearAll) btnClearAll.addEventListener("click", clearCalcPage);

async function pollProject(pid, jobId) {
  if (!pid) return;
  const started = Date.now();
  let lastStatus = "";
  for (let i = 0; i < 180; i++) {
    let data;
    try {
      data = await api("/api/projects/" + pid + "/poll", { method: "POST", body: "{}" });
    } catch (e) {
      addBubble("轮询失败：" + e.message, "bot");
      showJobProgress("error", e.message, "");
      return;
    }
    const jid = jobId || data.job_id;
    const st = (data.status || "unknown").toLowerCase();
    const timing = data.timing || {};
    const elapsed =
      timing.elapsed_seconds != null
        ? Number(timing.elapsed_seconds)
        : timing.wall_seconds != null
          ? Number(timing.wall_seconds)
          : Math.round((Date.now() - started) / 1000);
    let logTail = "";
    if (jid) {
      try {
        const log = await api("/api/jobs/" + jid + "/log?tail=50");
        logTail = log.log_tail || "";
        if (log.status) {
          /* prefer poll status */
        }
      } catch (_) {
        /* ignore */
      }
    }
    // 任务页已展开该任务时，同步刷新详情（计算中即可看进度/日志）
    const onTasks =
      !!$("tab-projects") && $("tab-projects").classList.contains("active");
    if (onTasks && currentProjectId === pid) {
      refreshTaskLive(pid, st === "done" || st === "error", {
        forceReplot: st === "done",
      }).catch(() => {});
    }
    if (st === "pending") {
      showJobProgress(
        "pending",
        "状态：排队中。引擎尚未开始写日志，通常数秒内会进入运行。已等待 " + elapsed + " s。",
        logTail || "（尚无运行日志）"
      );
    } else if (st === "running") {
      showJobProgress(
        "running",
        "状态：计算中。下方为实时日志尾部。已运行 " + elapsed + " s。",
        logTail || "（日志读取中…）"
      );
    }
    if (st !== lastStatus) {
      if (st === "pending") addBubble("进度：作业排队中，等待引擎启动…", "bot");
      if (st === "running") addBubble("进度：本机 DFTB+ 已开始运行。", "bot");
      lastStatus = st;
    }
    if (st === "done") {
      const doneMsg = "作业完成，已解析结果。";
      addBubble(doneMsg, "bot");
      if (data.figures && data.figures.length) {
        addBubble(
          "出图：" + data.figures.map((f) => String(f).split(/[/\\]/).pop()).join(", "),
          "bot"
        );
      }
      setCalcProgress("ready", "输入文件已就绪；作业已完成，可在「任务」页查看结果。");
      showJobProgress("done", doneMsg + " 可前往「任务」页查看详细结果。", logTail);
      if (onTasks && currentProjectId === pid) {
        refreshTaskLive(pid, true, { forceReplot: true }).catch(() => {});
      }
      return;
    }
    if (st === "error") {
      addBubble("作业失败，请查看日志。", "bot");
      showJobProgress("error", "计算失败。请根据日志排查后重新确认计算。", logTail);
      if (onTasks && currentProjectId === pid) {
        refreshTaskLive(pid, true).catch(() => {});
      }
      return;
    }
    if (st === "cancelled") {
      addBubble("作业已取消。", "bot");
      showJobProgress("cancelled", "任务已取消，可重新确认计算。", logTail);
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  addBubble("跟踪超时：请到「任务」页手动刷新作业状态。", "bot");
  showJobProgress("error", "跟踪超时，请到「任务」页刷新。", "");
}

function fillMetricGrid(box, items) {
  if (!box) return;
  box.innerHTML = "";
  items.forEach(([k, v]) => {
    const card = document.createElement("div");
    card.className = "metric-card";
    card.innerHTML = "<div class='metric-k'>" + k + "</div><div class='metric-v'>" + v + "</div>";
    box.appendChild(card);
  });
}

const PHASE_ZH = {
  draft: "草稿",
  protocol: "方案就绪",
  running: "计算中",
  analyzed: "已完成",
  manuscript: "文稿",
  cancelled: "已取消",
  error: "失败",
};
const STATUS_ZH = {
  pending: "排队中",
  running: "计算中",
  done: "已完成",
  error: "失败",
  cancelled: "已取消",
  not_found: "未找到",
  unknown: "未知",
  none: "未投递",
};

function phaseZh(phase) {
  return PHASE_ZH[(phase || "").toLowerCase()] || phase || "—";
}
function statusZh(status) {
  return STATUS_ZH[(status || "").toLowerCase()] || status || "—";
}

/** 单一状态文案：避免「计算中 · 计算中」「已分析 · 已完成」等重复。 */
function unifiedStatus(phase, jobStatus, pollStatus) {
  const st = String(pollStatus || jobStatus || "").toLowerCase();
  const ph = String(phase || "").toLowerCase();
  if (st === "done" || ph === "analyzed") return "已完成";
  if (st === "cancelled" || ph === "cancelled") return "已取消";
  if (st === "error" || ph === "error") return "失败";
  if (st === "running") return "计算中";
  if (st === "pending") return "排队中";
  if (ph === "running") return "计算中";
  if (ph === "protocol") return "方案就绪";
  if (ph === "draft") return "草稿";
  if (st === "none") return "未投递";
  return statusZh(st) !== "—" ? statusZh(st) : phaseZh(ph);
}

const SKIP_FIG_NAMES = {
  "dftb_total_energy.png": true,
  "dftb_performance.png": true,
};

function onlyPngFigures(list) {
  return (list || []).filter((f) => {
    const name = String((f && f.name) || f || "").toLowerCase();
    return name.endsWith(".png") && !SKIP_FIG_NAMES[name];
  });
}

let currentFigures = [];
let figLightboxIndex = 0;
let ioFiles = [];
let ioFileIndex = 0;

function triggerDownload(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  if (filename) a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function openFigureLightbox(index) {
  const list = currentFigures || [];
  if (!list.length) return;
  const i = Math.max(0, Math.min(list.length - 1, Number(index) || 0));
  figLightboxIndex = i;
  const f = list[i];
  const box = $("fig-lightbox");
  const img = $("fig-lightbox-img");
  const cap = $("fig-lightbox-cap");
  if (!box || !img) return;
  img.src = f.url || "";
  img.alt = f.name || "";
  if (cap) {
    cap.textContent =
      (f.name || "结果图") + (list.length > 1 ? "  （" + (i + 1) + " / " + list.length + "）" : "");
  }
  const prev = $("fig-lightbox-prev");
  const next = $("fig-lightbox-next");
  if (prev) prev.disabled = list.length < 2;
  if (next) next.disabled = list.length < 2;
  box.hidden = false;
}

function closeFigureLightbox() {
  const box = $("fig-lightbox");
  const img = $("fig-lightbox-img");
  if (box) box.hidden = true;
  if (img) img.removeAttribute("src");
}

function exportCurrentFigure() {
  const f = currentFigures[figLightboxIndex];
  if (!f) return;
  triggerDownload(f.download_url || f.url + (String(f.url).includes("?") ? "&" : "?") + "download=1", f.name);
}

async function exportAllFigures() {
  const list = currentFigures || [];
  if (!list.length) {
    addBubble("当前没有可导出的结果图。", "bot");
    return;
  }
  for (let i = 0; i < list.length; i++) {
    const f = list[i];
    triggerDownload(
      f.download_url || f.url + (String(f.url).includes("?") ? "&" : "?") + "download=1",
      f.name
    );
    if (i < list.length - 1) await new Promise((r) => setTimeout(r, 280));
  }
  addBubble("已开始导出 " + list.length + " 张结果图。", "bot");
}

function fillFigureGallery(figures) {
  const gal = $("fig-gallery");
  const btnExport = $("btn-export-figs");
  const figsBlock = $("figs-block");
  if (!gal) return;
  currentFigures = onlyPngFigures(figures).map((f) => ({
    name: f.name,
    url: f.url,
    download_url: f.download_url || f.url + "?download=1",
  }));
  gal.innerHTML = "";
  if (figsBlock) figsBlock.hidden = false;
  if (btnExport) btnExport.hidden = !currentFigures.length;
  if (!currentFigures.length) {
    gal.innerHTML = "<p class='muted-inline task-panel-placeholder'>暂无结果图</p>";
    return;
  }
  currentFigures.forEach((f, idx) => {
    const fig = document.createElement("figure");
    fig.className = "gallery-item";
    fig.tabIndex = 0;
    fig.setAttribute("role", "button");
    fig.setAttribute("aria-label", "查看 " + (f.name || "结果图"));
    const img = document.createElement("img");
    img.src = f.url;
    img.alt = f.name;
    img.title = "点击查看大图";
    const cap = document.createElement("figcaption");
    cap.textContent = f.name || "";
    const exp = document.createElement("button");
    exp.type = "button";
    exp.className = "btn btn-ghost btn-mini gallery-export";
    exp.textContent = "导出";
    exp.addEventListener("click", (ev) => {
      ev.stopPropagation();
      triggerDownload(f.download_url, f.name);
    });
    fig.appendChild(img);
    fig.appendChild(cap);
    fig.appendChild(exp);
    const open = () => openFigureLightbox(idx);
    fig.addEventListener("click", open);
    fig.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        open();
      }
    });
    gal.appendChild(fig);
  });
}

function primeTaskDetailShell() {
  const io = $("task-io");
  if (io) {
    io.hidden = false;
    const list = $("io-file-list");
    if (list) list.innerHTML = "<p class='muted-inline task-panel-placeholder'>加载文件列表…</p>";
    const text = $("io-file-text");
    if (text) text.textContent = "";
    const meta = $("io-browser-meta");
    if (meta) meta.textContent = "加载中…";
    const nameEl = $("io-file-name");
    if (nameEl) nameEl.textContent = "—";
  }
  const live = $("task-live");
  if (live) {
    live.hidden = false;
    const note = $("task-live-note");
    if (note) note.textContent = "加载计算进度…";
    const log = $("task-live-log");
    if (log) log.textContent = "加载中…";
    const statusBtn = $("task-live-status-btn");
    if (statusBtn) {
      statusBtn.textContent = "…";
      statusBtn.className = "job-status-btn is-pending";
    }
    const steps = $("task-pipeline-steps");
    if (steps) {
      steps.hidden = true;
      steps.innerHTML = "";
    }
    const bar = $("task-progress-bar");
    if (bar) bar.hidden = true;
    const diag = $("task-diag");
    if (diag) diag.hidden = true;
  }
  const struct = $("task-struct-compare");
  if (struct) {
    // 结构对比仅几何优化类任务显示；骨架阶段先隐藏
    struct.hidden = true;
  }
  const figs = $("figs-block");
  if (figs) {
    figs.hidden = false;
    const gal = $("fig-gallery");
    if (gal) gal.innerHTML = "<p class='muted-inline task-panel-placeholder'>加载结果图…</p>";
    const btnExport = $("btn-export-figs");
    if (btnExport) btnExport.hidden = true;
  }
  const analysis = $("analysis-cards");
  if (analysis) {
    analysis.innerHTML =
      "<div class='metric-card'><div class='metric-k'>状态</div><div class='metric-v'>加载中…</div></div>" +
      "<div class='metric-card'><div class='metric-k'>任务类型</div><div class='metric-v'>—</div></div>" +
      "<div class='metric-card'><div class='metric-k'>摘要</div><div class='metric-v'>加载中…</div></div>";
  }
  const cancelBtn = $("btn-cancel-job");
  if (cancelBtn) cancelBtn.hidden = true;
}

async function loadTaskIoPanel(opts) {
  if (!currentProjectId) return;
  const soft = !!(opts && opts.soft);
  const box = $("task-io");
  const listEl = $("io-file-list");
  const meta = $("io-browser-meta");
  const textEl = $("io-file-text");
  if (!box || !listEl) return;
  box.hidden = false;
  // 轮询刷新时保留当前选中的文件与滚动位置，避免被顶回列表第一项
  const keepName =
    (ioFiles[ioFileIndex] && ioFiles[ioFileIndex].name) ||
    (($("io-file-name") && $("io-file-name").textContent) || "").trim();
  const keepScroll = textEl ? textEl.scrollTop : 0;
  try {
    const data = await api("/api/projects/" + currentProjectId + "/io-files?sync=1");
    ioFiles = data.files || [];
    if (meta) {
      const nIn = ioFiles.filter((f) => f.kind === "input").length;
      const nOut = ioFiles.filter((f) => f.kind === "output").length;
      meta.textContent = ioFiles.length
        ? "输入 " + nIn + " · DFTB+ 输出 " + nOut
        : "暂无已落盘文件（计算开始后出现）";
    }
    if (!ioFiles.length) {
      listEl.innerHTML = "<p class='muted-inline'>暂无文件。计算进行中或完成后会显示。</p>";
      return;
    }
    let idx = 0;
    if (keepName && keepName !== "—") {
      const found = ioFiles.findIndex((f) => f.name === keepName);
      if (found >= 0) idx = found;
    } else if (ioFileIndex > 0 && ioFileIndex < ioFiles.length) {
      idx = ioFileIndex;
    }
    renderIoFileList();
    await showIoFile(idx, { soft: soft, restoreScroll: keepScroll });
  } catch (e) {
    listEl.innerHTML = "<p class='muted-inline'>加载失败：" + (e.message || e) + "</p>";
  }
}

function renderIoFileList() {
  const listEl = $("io-file-list");
  if (!listEl) return;
  listEl.innerHTML = "";
  const groups = [
    { kind: "input", title: "输入文件" },
    { kind: "output", title: "DFTB+ 输出" },
    { kind: "other", title: "其它" },
  ];
  groups.forEach((g) => {
    const items = ioFiles
      .map((f, idx) => ({ f, idx }))
      .filter((x) => x.f.kind === g.kind);
    if (!items.length) return;
    const lab = document.createElement("div");
    lab.className = "io-file-group-label";
    lab.textContent = g.title;
    listEl.appendChild(lab);
    items.forEach(({ f, idx }) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "io-file-item" + (idx === ioFileIndex ? " active" : "");
      btn.innerHTML =
        "<span class='io-kind io-kind-" +
        f.kind +
        "'>" +
        (f.kind === "input" ? "输入" : f.kind === "output" ? "输出" : "其它") +
        "</span><span class='io-name'></span>";
      btn.querySelector(".io-name").textContent = f.name;
      btn.addEventListener("click", () => showIoFile(idx));
      listEl.appendChild(btn);
    });
  });
}

async function showIoFile(index, opts) {
  if (!ioFiles.length || !currentProjectId) return;
  const options = opts || {};
  const soft = !!options.soft;
  const restoreScroll =
    typeof options.restoreScroll === "number" ? options.restoreScroll : null;
  const i = Math.max(0, Math.min(ioFiles.length - 1, Number(index) || 0));
  ioFileIndex = i;
  const f = ioFiles[i];
  renderIoFileList();
  const nameEl = $("io-file-name");
  const kindEl = $("io-file-kind");
  const textEl = $("io-file-text");
  const prev = $("io-file-prev");
  const next = $("io-file-next");
  if (nameEl) nameEl.textContent = f.name;
  if (kindEl) {
    kindEl.textContent = f.kind_zh || f.kind || "—";
    kindEl.className =
      "io-kind-badge is-" + (f.kind === "input" ? "input" : f.kind === "output" ? "output" : "other");
  }
  if (prev) prev.disabled = ioFiles.length < 2;
  if (next) next.disabled = ioFiles.length < 2;
  // 软刷新（轮询）不闪「加载中」，避免打断阅读；手动切换文件时再显示
  if (textEl && !soft) textEl.textContent = "加载中…";
  try {
    const data = await api(
      "/api/projects/" + currentProjectId + "/io-files/" + encodeURIComponent(f.name)
    );
    if (textEl) {
      textEl.textContent = data.text || "（空文件）";
      if (restoreScroll != null) textEl.scrollTop = restoreScroll;
    }
    f.download_url = data.download_url || f.download_url;
  } catch (e) {
    if (textEl && !soft) textEl.textContent = "读取失败：" + (e.message || e);
  }
}

function renderPipelineSteps(steps) {
  const ol = $("task-pipeline-steps");
  const bar = $("task-progress-bar");
  const fill = $("task-progress-fill");
  if (!ol) return;
  const list = Array.isArray(steps) ? steps : [];
  if (!list.length) {
    ol.hidden = true;
    ol.innerHTML = "";
    if (bar) bar.hidden = true;
    return;
  }
  ol.hidden = false;
  ol.innerHTML = "";
  let doneN = 0;
  let activeN = 0;
  list.forEach((s) => {
    const li = document.createElement("li");
    const st = String(s.state || "idle");
    li.className = "is-" + st;
    li.textContent = s.label || s.id || "";
    ol.appendChild(li);
    if (st === "done") doneN += 1;
    if (st === "active") activeN += 1;
  });
  if (bar && fill) {
    bar.hidden = false;
    const pct = Math.round(((doneN + activeN * 0.45) / list.length) * 100);
    fill.style.width = Math.max(8, Math.min(100, pct)) + "%";
  }
}

let taskWatchTimer = null;

function stopTaskWatch() {
  if (taskWatchTimer) {
    clearInterval(taskWatchTimer);
    taskWatchTimer = null;
  }
}

function startTaskWatch(projectId) {
  stopTaskWatch();
  if (!projectId) return;
  taskWatchTimer = setInterval(() => {
    if (currentProjectId !== projectId) {
      stopTaskWatch();
      return;
    }
    // 计算中持续刷新进度/日志；结束后再拉一次出图
    refreshTaskLive(projectId, false)
      .then((poll) => {
        const st = String((poll && poll.status) || "").toLowerCase();
        if (["done", "error", "cancelled"].includes(st)) {
          refreshTaskLive(projectId, true, { forceReplot: st === "done" }).catch(() => {});
          stopTaskWatch();
        }
      })
      .catch(() => {});
  }, 2000);
}

function renderDiagPanel(poll) {
  const box = $("task-diag");
  if (!box) return;
  const diag = (poll && poll.diag) || {};
  const st = String((poll && poll.status) || "").toLowerCase();
  const show =
    !!poll &&
    (st === "error" || st === "cancelled") &&
    Object.keys(diag).length > 0;
  if (!show) {
    box.hidden = true;
    return;
  }
  const bits = [];
  if (diag.has_run_script === false) bits.push("缺少 run.sh");
  if (diag.has_log === false) bits.push("尚无引擎日志");
  if (diag.runner_alive === false) bits.push("后台进程已退出");
  box.hidden = !bits.length;
  if (!bits.length) return;
  box.innerHTML = "<strong>运行诊断</strong><span>" + bits.join(" · ") + "</span>";
}

function structureSourceLabel(mp) {
  if (!mp) return "";
  const mid = String(mp.material_id || "");
  const formula = String(mp.formula || "").trim();
  const source = String(mp.source || "");
  const approx = mp.approximate ? "近似 · " : "";
  if (source === "pristine+vacancy" || mid.startsWith("derived:vacancy")) {
    const vac = mp.vacancy || {};
    const sc = (vac.nx || "?") + "×" + (vac.ny || "?") + "×" + (vac.nz || "?");
    return "完美晶体→挖空 · " + sc + (formula ? "（" + formula + "）" : "");
  }
  const isLocal = source === "local-template" || source === "local" || mid.startsWith("local:");
  if (isLocal) {
    const name = mid.startsWith("local:") ? mid.slice(6) : mid || "内置";
    return approx + "内置模板 · " + name + (formula ? "（" + formula + "）" : "");
  }
  if (mid || formula) {
    return (
      approx +
      "Materials Project · " +
      (mid || formula) +
      (mid && formula ? "（" + formula + "）" : "")
    );
  }
  return approx ? "近似结构（可上传覆盖）" : "";
}

function summarizeStructure(poscar, gen, mp) {
  const meta = [];
  const src = structureSourceLabel(mp);
  if (src) meta.push(src);
  const text = (poscar || gen || "").trim();
  if (!text) return { meta: meta.join(" · ") || "无结构", preview: "" };
  const lines = text.split(/\r?\n/);
  if (poscar) {
    const comment = (lines[0] || "").trim();
    const scale = (lines[1] || "").trim();
    const species = (lines[5] || "").trim();
    const counts = (lines[6] || "").trim();
    if (comment) meta.push(comment.slice(0, 60));
    if (species) meta.push("元素 " + species);
    if (counts) meta.push("原子数 " + counts);
    if (scale) meta.push("缩放 " + scale);
    const lattice = lines.slice(2, 5).join("\n");
    const head = lines.slice(0, Math.min(lines.length, 18)).join("\n");
    return {
      meta: meta.filter(Boolean).join(" · ") || "POSCAR",
      preview: (lattice ? "晶格矢量：\n" + lattice + "\n\n" : "") + head,
    };
  }
  return {
    meta: meta.join(" · ") || "GEN 结构",
    preview: lines.slice(0, 24).join("\n"),
  };
}

function renderLecture(_lecture) {
  // 结果说明与下方摘要卡片重复，已移除展示
}

function renderLiveMonitor(poll, job, phase) {
  const box = $("task-live");
  const cancelBtn = $("btn-cancel-job");
  if (!box) return;
  const st = (poll && poll.status) || (job && job.status) || "";
  const stNorm = String(st).toLowerCase();
  const ph = String(phase || "").toLowerCase();
  const done = stNorm === "done" || ph === "analyzed";
  const active = !done && ["pending", "running"].includes(stNorm);
  const hasJob = !!(poll && poll.job_id) || !!(job && job.job_id);
  box.hidden = false;
  if (cancelBtn) cancelBtn.hidden = !(poll && poll.cancellable) && !active;

  renderDiagPanel(hasJob ? poll : null);
  if (!hasJob) {
    stopTaskWatch();
    renderPipelineSteps([]);
    const statusBtn = $("task-live-status-btn");
    if (statusBtn) {
      statusBtn.textContent = "未投递";
      statusBtn.className = "job-status-btn is-pending";
    }
    const noteEl = $("task-live-note");
    if (noteEl) noteEl.textContent = "尚未投递本机作业。";
    const logEl = $("task-live-log");
    if (logEl) logEl.textContent = "（暂无日志）";
    return;
  }

  const titleEl = $("task-live-title");
  if (titleEl) titleEl.textContent = done ? "计算进度" : "计算进度";

  let stZh = unifiedStatus(phase, job && job.status, poll && poll.status);
  if (
    stZh === "计算中" &&
    poll &&
    (poll.analysis || poll.partial_analysis) &&
    String(poll.status || "").toLowerCase() === "done"
  ) {
    stZh = "已完成";
  }
  const statusBtn = $("task-live-status-btn");
  if (statusBtn) {
    let label = "完成";
    let kind = "done";
    if (stNorm === "pending") {
      label = "排队";
      kind = "pending";
    } else if (stNorm === "running" && !done) {
      label = "运行";
      kind = "running";
    } else if (stNorm === "error" || ph === "error") {
      label = "失败";
      kind = "err";
    } else if (stNorm === "cancelled" || ph === "cancelled") {
      label = "已取消";
      kind = "err";
    } else if (done || stZh === "已完成") {
      label = "完成";
      kind = "done";
    }
    statusBtn.textContent = label;
    statusBtn.className = "job-status-btn is-" + kind;
  }

  renderPipelineSteps((poll && poll.pipeline_steps) || []);

  const noteEl = $("task-live-note");
  if (noteEl) {
    const msg = (poll && poll.message) || "";
    const note = (poll && poll.note) || "";
    const next = (poll && poll.next_action) || "";
    if (done) noteEl.textContent = note || "作业已完成，结果见下方出图与摘要。";
    else if (active)
      noteEl.textContent =
        next || note || msg || "正在运行 DFTB+，下方实时显示计算步骤与日志…";
    else if (msg && note && msg !== note) noteEl.textContent = note + " " + msg;
    else noteEl.textContent = note || msg || "状态：" + stZh;
  }

  const logEl = $("task-live-log");
  if (logEl) {
    const tail = (poll && poll.log_tail) || "";
    logEl.textContent = tail || (active ? "（等待引擎日志…）" : "（暂无日志）");
  }

  if (active) startTaskWatch(currentProjectId);
  else stopTaskWatch();
}

const KIND_BAND = new Set(["dftb_band", "dftb_dos", "dftb_defect", "dftb_boundary"]);
const KIND_ELECTRONIC = new Set([
  "dftb_scc",
  "dftb_band",
  "dftb_dos",
  "dftb_defect",
  "dftb_boundary",
]);
const KIND_OPT = new Set(["dftb_opt", "dftb_xtb", "dftb_solv", "dftb_barrier", "dftb_td_relax"]);
const KIND_TD = new Set(["dftb_td", "dftb_td_relax"]);
const KIND_VIB = new Set(["dftb_vib"]);
const KIND_MD = new Set(["dftb_md", "dftb_md_anneal", "dftb_ehrenfest"]);

function kindFlags(kind, protocol) {
  const k = String(kind || "").toLowerCase();
  const stages = (protocol && (protocol.stages || (protocol.params && protocol.params.stages))) || [];
  const pre = !!(
    (protocol && protocol.params && protocol.params.pre_relax) ||
    (Array.isArray(stages) && stages.indexOf("opt") >= 0)
  );
  return {
    kind: k,
    fermi: KIND_ELECTRONIC.has(k),
    band: KIND_BAND.has(k),
    opt: KIND_OPT.has(k) || pre,
    td: KIND_TD.has(k),
    vib: KIND_VIB.has(k),
    md: KIND_MD.has(k),
    structCompare: KIND_OPT.has(k) || pre,
    stages: Array.isArray(stages) ? stages : [],
  };
}

function renderIntoMolViewer(el, text, kindHint) {
  if (!el) return;
  const raw = (text || "").trim();
  if (!raw) {
    el.innerHTML = "<p class='muted-inline'>暂无结构</p>";
    return;
  }
  if (typeof $3Dmol === "undefined") {
    el.innerHTML = "<p class='muted-inline'>结构可视化库未加载</p>";
    return;
  }
  const prepared = prepareStructureModel(raw, kindHint);
  if (!prepared || prepared.error) {
    el.innerHTML = "<p class='muted-inline'>" + ((prepared && prepared.error) || "无法解析 GEN") + "</p>";
    return;
  }
  try {
    el.innerHTML = "";
    const viewer = $3Dmol.createViewer(el, {
      backgroundColor: "#f4f7f8",
      antialias: true,
    });
    viewer.addModel(prepared.data, prepared.format);
    if (prepared.replicate && prepared.format === "vasp") {
      try {
        viewer.replicateUnitCell(prepared.replicate, prepared.replicate, prepared.replicate);
      } catch (_) {
        /* optional */
      }
    }
    viewer.setStyle({}, molViewerStyle());
    try {
      if (prepared.format === "vasp") viewer.addUnitCell({ box: { color: "0x6a7d89" } });
    } catch (_) {
      /* optional */
    }
    applyMolViewerCamera(viewer);
    setTimeout(() => {
      try {
        viewer.resize();
        viewer.render();
      } catch (_) {
        /* ignore */
      }
    }, 80);
  } catch (e) {
    el.innerHTML = "<p class='muted-inline'>预览失败：" + (e.message || e) + "</p>";
  }
}

async function renderTaskStructureCompare(protocol, lecture) {
  const box = $("task-struct-compare");
  if (!box) return;
  const flags = kindFlags(protocol && protocol.kind, protocol);
  const want =
    flags.structCompare ||
    !!(lecture && lecture.show_structure_compare);
  const note = $("task-struct-compare-note");
  const beforeEl = $("task-struct-before");
  const afterEl = $("task-struct-after");
  if (!want || !currentProjectId) {
    box.hidden = true;
    rememberStructTexts("", "");
    if (beforeEl) beforeEl.innerHTML = "";
    if (afterEl) afterEl.innerHTML = "";
    return;
  }
  box.hidden = false;
  let before = "";
  let after = "";
  try {
    const beforeRes = await api(
      "/api/projects/" + currentProjectId + "/io-files/" + encodeURIComponent("geo.gen")
    ).catch(() => null);
    const afterRes = await api(
      "/api/projects/" + currentProjectId + "/io-files/" + encodeURIComponent("geo_end.gen")
    ).catch(() => null);
    before = (beforeRes && beforeRes.text) || "";
    after = (afterRes && afterRes.text) || "";
    if (!before) {
      const pos = await api(
        "/api/projects/" + currentProjectId + "/io-files/" + encodeURIComponent("POSCAR")
      ).catch(() => null);
      before = (pos && pos.text) || "";
    }
  } catch (_) {
    /* ignore */
  }
  rememberStructTexts(before, after);
  if (!after) {
    if (note) note.textContent = "尚无优化后结构（计算完成后显示）";
    if (beforeEl)
      beforeEl.innerHTML = before
        ? ""
        : "<p class='muted-inline task-panel-placeholder'>暂无输入结构</p>";
    if (before) {
      renderIntoMolViewer(beforeEl, before, looksLikePoscar(before) ? "poscar" : "gen");
    }
    if (afterEl)
      afterEl.innerHTML = "<p class='muted-inline task-panel-placeholder'>等待 geo_end.gen</p>";
    return;
  }
  if (note) note.textContent = before ? "优化前（输入） / 优化后（geo_end.gen）" : "优化后结构";
  renderIntoMolViewer(beforeEl, before, before && looksLikePoscar(before) ? "poscar" : "gen");
  renderIntoMolViewer(afterEl, after, "gen");
}

function renderAnalysis(full, poll) {
  const box = $("analysis-cards");
  const proj = full.project || full;
  const protocol = proj.protocol || full.protocol || {};
  const analysis =
    (poll && poll.analysis) ||
    protocol.analysis ||
    full.analysis ||
    (poll && poll.partial_analysis) ||
    {};
  const detailed = analysis.detailed || {};
  const job = proj.job || full.job || {};
  const lecture = (poll && poll.lecture) || null;
  const phase = proj.phase || full.phase || "";
  const flags = kindFlags(protocol.kind, protocol);
  renderLecture(lecture);
  renderTaskStructureCompare(protocol, lecture).catch(() => {});

  const perf = protocol.performance || analysis.performance || {};
  const energy =
    analysis.total_energy != null
      ? analysis.total_energy
      : detailed.total_energy_eV != null
        ? detailed.total_energy_eV
        : analysis.energy;
  const fermi =
    analysis.fermi_energy != null
      ? analysis.fermi_energy
      : detailed.fermi_eV != null
        ? detailed.fermi_eV
        : analysis.fermi;
  let converged = analysis.converged;
  if (converged == null) {
    if (detailed.geo_converged || detailed.scc_converged) converged = true;
    else if (analysis.geometry_converged != null) converged = analysis.geometry_converged;
  }
  const gap =
    analysis.band_gap_eV != null
      ? analysis.band_gap_eV
      : (analysis.band_gap || {}).gap_eV;
  const pathName =
    analysis.band_path ||
    (analysis.band_meta || {}).path_name ||
    "";
  const stLabel = unifiedStatus(phase, job.status, poll && poll.status);
  const items = [
    ["状态", stLabel],
    ["任务类型", protocol.kind || "—"],
    ["SK 参数集", protocol.sk_set || "—"],
  ];
  const stageZh = {
    opt: "几何优化",
    band: "能带与带隙",
    dos: "态密度",
    defect: "缺陷电子结构",
    vib: "振动频率",
    td: "吸收光谱",
    md: "分子动力学",
    md_anneal: "退火 MD",
    scc: "SCC 单点",
  };
  const stages = flags.stages || protocol.stages || [];
  if (stages.length) {
    items.push(["计算阶段", stages.map((s) => stageZh[s] || s).join(" → ")]);
  }
  if (energy != null && energy !== "") {
    items.push([
      "总能量 (eV)",
      String(Number(energy).toFixed ? Number(energy).toFixed(6) : energy),
    ]);
  }
  if (flags.fermi && fermi != null && fermi !== "") {
    items.push([
      "Fermi (eV)",
      String(Number(fermi).toFixed ? Number(fermi).toFixed(6) : fermi),
    ]);
  }
  if (converged === true || converged === false) {
    items.push(["收敛", converged === true ? "是" : "否"]);
  }
  if (flags.band && gap != null && gap !== "") {
    items.push(["带隙 (eV)", Number(gap).toFixed(3) + "（定性）"]);
  }
  if (flags.band && pathName) items.push(["k 路径", String(pathName)]);
  if (flags.band && analysis.n_kpoints) items.push(["k 点数", String(analysis.n_kpoints)]);
  if (flags.opt) {
    const optE = detailed.opt_energies_eV || analysis.opt_energies_eV || [];
    if (Array.isArray(optE) && optE.length >= 2) {
      items.push(["优化步数", String(optE.length)]);
      const dE = Number(optE[optE.length - 1]) - Number(optE[0]);
      if (!Number.isNaN(dE)) items.push(["ΔE (eV)", dE.toFixed(6)]);
    }
  }
  if (flags.td) {
    const exc = analysis.excitations || detailed.excitations || [];
    if (exc.length) {
      items.push(["激发态数", String(exc.length)]);
      const e0 = Number(exc[0].energy);
      if (!Number.isNaN(e0)) items.push(["最低激发 (eV)", e0.toFixed(3)]);
    }
  }
  if (flags.vib) {
    const vib = analysis.vibrations || [];
    if (vib.length) {
      items.push(["振动模数", String(vib.length)]);
      const real = vib
        .map((v) => Number(v.freq_cm1))
        .filter((f) => !Number.isNaN(f) && f > 50);
      if (real.length) {
        items.push([
          "频率范围 (cm⁻¹)",
          Math.min(...real).toFixed(1) + " – " + Math.max(...real).toFixed(1),
        ]);
        const top = [...real].sort((a, b) => b - a).slice(0, 6);
        items.push(["主要频率 (cm⁻¹)", top.map((x) => x.toFixed(1)).join("、")]);
      }
      const nImag = vib.filter((v) => Number(v.freq_cm1) < -1).length;
      if (nImag) items.push(["虚频模数", String(nImag)]);
    }
  }
  if (flags.md) {
    const mdE = analysis.md_energies_eV || detailed.md_energies_eV || [];
    if (Array.isArray(mdE) && mdE.length >= 2) {
      items.push(["MD 步数", String(mdE.length)]);
      const dE = Number(mdE[mdE.length - 1]) - Number(mdE[0]);
      if (!Number.isNaN(dE)) items.push(["ΔE (eV)", dE.toFixed(6)]);
    }
    const mdT = analysis.md_temps_K || detailed.md_temps_K || [];
    let tMean = analysis.md_temp_mean_K;
    if (tMean == null && Array.isArray(mdT) && mdT.length) {
      tMean = mdT.reduce((a, b) => a + Number(b), 0) / mdT.length;
    }
    if (tMean != null && !Number.isNaN(Number(tMean))) {
      items.push(["平均温度 (K)", Number(tMean).toFixed(1)]);
      if (Array.isArray(mdT) && mdT.length) {
        const nums = mdT.map(Number).filter((x) => !Number.isNaN(x));
        if (nums.length) {
          items.push([
            "温度范围 (K)",
            Math.min(...nums).toFixed(1) + " – " + Math.max(...nums).toFixed(1),
          ]);
        }
      }
    }
  }
  if (
    (flags.fermi || flags.opt || !flags.kind) &&
    (analysis.scc_iterations != null || detailed.scc_iterations != null || perf.scc_iterations != null)
  ) {
    items.push([
      "SCC 迭代",
      String(
        analysis.scc_iterations != null
          ? analysis.scc_iterations
          : detailed.scc_iterations != null
            ? detailed.scc_iterations
            : perf.scc_iterations
      ),
    ]);
  }
  if (protocol.plot_error) {
    items.push(["出图", "失败：" + String(protocol.plot_error).slice(0, 80)]);
  }
  if (lecture && lecture.items && lecture.items.length) {
    const skip = new Set(["title", "phase", "mp", "wall"]);
    const lecItems = lecture.items
      .filter((it) => {
        const key = String(it.key || "").toLowerCase();
        const label = String(it.label || "");
        if (skip.has(key)) return false;
        if (/墙钟/.test(label)) return false;
        return true;
      })
      .map((it) => [it.label || it.key, it.value != null ? String(it.value) : "—"]);
    fillMetricGrid(box, lecItems.length ? lecItems : items);
  } else {
    fillMetricGrid(box, items);
  }
  renderLiveMonitor(poll, job, phase);
}

function parkProjectDetail() {
  const detail = $("project-detail");
  const host = $("project-detail-host");
  if (detail && host && detail.parentElement !== host) {
    host.appendChild(detail);
  }
  if (detail) detail.hidden = true;
  document.querySelectorAll("#project-list .project-item.is-open").forEach((el) => {
    el.classList.remove("is-open");
    const slot = el.querySelector(".project-expand");
    if (slot) slot.hidden = true;
  });
}

function stashCurrentTaskDetail() {
  const id = currentProjectId;
  if (!id || !$("project-detail") || $("project-detail").hidden) return;
  try {
    taskDetailCache.set(id, captureTaskDetailSnapshot());
  } catch (_) {
    /* ignore */
  }
}

function captureTaskDetailSnapshot() {
  const statusBtn = $("task-live-status-btn");
  const bar = $("task-progress-bar");
  const fill = $("task-progress-fill");
  const steps = $("task-pipeline-steps");
  const diag = $("task-diag");
  const cancelBtn = $("btn-cancel-job");
  const ioText = $("io-file-text");
  return {
    analysisHtml: ($("analysis-cards") && $("analysis-cards").innerHTML) || "",
    figures: (currentFigures || []).map((f) => ({ ...f })),
    ioFiles: (ioFiles || []).map((f) => ({ ...f })),
    ioFileIndex: ioFileIndex || 0,
    ioText: (ioText && ioText.textContent) || "",
    ioName: ($("io-file-name") && $("io-file-name").textContent) || "—",
    ioKind: ($("io-file-kind") && $("io-file-kind").textContent) || "—",
    ioKindClass: ($("io-file-kind") && $("io-file-kind").className) || "io-kind-badge",
    ioMeta: ($("io-browser-meta") && $("io-browser-meta").textContent) || "",
    ioHidden: !!($("task-io") && $("task-io").hidden),
    liveHidden: !!($("task-live") && $("task-live").hidden),
    liveNote: ($("task-live-note") && $("task-live-note").textContent) || "",
    liveLog: ($("task-live-log") && $("task-live-log").textContent) || "",
    liveStatus: (statusBtn && statusBtn.textContent) || "—",
    liveStatusClass: (statusBtn && statusBtn.className) || "job-status-btn",
    stepsHtml: (steps && steps.innerHTML) || "",
    stepsHidden: !!(steps && steps.hidden),
    barHidden: !!(bar && bar.hidden),
    fillWidth: (fill && fill.style.width) || "",
    diagHtml: (diag && diag.innerHTML) || "",
    diagHidden: !!(diag && diag.hidden),
    cancelHidden: !!(cancelBtn && cancelBtn.hidden),
    figsHidden: !!($("figs-block") && $("figs-block").hidden),
    structHidden: !!($("task-struct-compare") && $("task-struct-compare").hidden),
    structNote:
      ($("task-struct-compare-note") && $("task-struct-compare-note").textContent) || "",
    structBefore: taskStructTexts.before || "",
    structAfter: taskStructTexts.after || "",
    jobStatus: String((statusBtn && statusBtn.className) || "").includes("is-running")
      ? "running"
      : String((statusBtn && statusBtn.className) || "").includes("is-pending")
        ? "pending"
        : "done",
  };
}

function rememberStructTexts(before, after) {
  taskStructTexts = { before: before || "", after: after || "" };
}

function restoreTaskDetailSnapshot(snap) {
  if (!snap) return;
  const analysis = $("analysis-cards");
  if (analysis) analysis.innerHTML = snap.analysisHtml || "";

  currentFigures = (snap.figures || []).slice();
  fillFigureGallery(currentFigures);
  const figsBlock = $("figs-block");
  if (figsBlock) figsBlock.hidden = !!snap.figsHidden;

  ioFiles = (snap.ioFiles || []).map((f) => ({ ...f }));
  ioFileIndex = snap.ioFileIndex || 0;
  const ioBox = $("task-io");
  if (ioBox) ioBox.hidden = !!snap.ioHidden;
  const meta = $("io-browser-meta");
  if (meta) meta.textContent = snap.ioMeta || "";
  const nameEl = $("io-file-name");
  if (nameEl) nameEl.textContent = snap.ioName || "—";
  const kindEl = $("io-file-kind");
  if (kindEl) {
    kindEl.textContent = snap.ioKind || "—";
    kindEl.className = snap.ioKindClass || "io-kind-badge";
  }
  const textEl = $("io-file-text");
  if (textEl) textEl.textContent = snap.ioText || "";
  if (ioFiles.length) renderIoFileList();
  else {
    const listEl = $("io-file-list");
    if (listEl)
      listEl.innerHTML = "<p class='muted-inline'>暂无文件。计算进行中或完成后会显示。</p>";
  }
  const prev = $("io-file-prev");
  const next = $("io-file-next");
  if (prev) prev.disabled = ioFiles.length < 2;
  if (next) next.disabled = ioFiles.length < 2;

  const live = $("task-live");
  if (live) live.hidden = !!snap.liveHidden;
  const statusBtn = $("task-live-status-btn");
  if (statusBtn) {
    statusBtn.textContent = snap.liveStatus || "—";
    statusBtn.className = snap.liveStatusClass || "job-status-btn";
  }
  const noteEl = $("task-live-note");
  if (noteEl) noteEl.textContent = snap.liveNote || "";
  const logEl = $("task-live-log");
  if (logEl) logEl.textContent = snap.liveLog || "";
  const steps = $("task-pipeline-steps");
  if (steps) {
    steps.innerHTML = snap.stepsHtml || "";
    steps.hidden = !!snap.stepsHidden;
  }
  const bar = $("task-progress-bar");
  if (bar) bar.hidden = !!snap.barHidden;
  const fill = $("task-progress-fill");
  if (fill) fill.style.width = snap.fillWidth || "";
  const diag = $("task-diag");
  if (diag) {
    diag.innerHTML = snap.diagHtml || "";
    diag.hidden = !!snap.diagHidden;
  }
  const cancelBtn = $("btn-cancel-job");
  if (cancelBtn) cancelBtn.hidden = !!snap.cancelHidden;

  const struct = $("task-struct-compare");
  if (struct) {
    struct.hidden = !!snap.structHidden;
    const snote = $("task-struct-compare-note");
    if (snote) snote.textContent = snap.structNote || "";
    rememberStructTexts(snap.structBefore, snap.structAfter);
    const beforeEl = $("task-struct-before");
    const afterEl = $("task-struct-after");
    if (!struct.hidden) {
      if (snap.structBefore && beforeEl) {
        renderIntoMolViewer(
          beforeEl,
          snap.structBefore,
          looksLikePoscar(snap.structBefore) ? "poscar" : "gen"
        );
      }
      if (snap.structAfter && afterEl) {
        renderIntoMolViewer(afterEl, snap.structAfter, "gen");
      } else if (afterEl && !snap.structHidden) {
        afterEl.innerHTML =
          "<p class='muted-inline task-panel-placeholder'>等待 geo_end.gen</p>";
      }
    }
  }
}

function appendProjectListItem(p) {
  const ul = $("project-list");
  if (!ul) return null;
  const li = document.createElement("li");
  li.className = "project-item";
  li.dataset.id = p.id;
  const title = p.title || "未命名任务";
  const hasResult = !!(p.protocol && p.protocol.analysis);
  let right = unifiedStatus(p.phase || "", (p.job || {}).status || "");
  if (hasResult && right === "计算中") right = "已完成";
  li.innerHTML =
    "<div class='project-row'>" +
    "<div class='project-row-main'><strong></strong><span class='project-phase'></span></div>" +
    "<div class='project-row-actions'>" +
    "<button type='button' class='btn btn-ghost btn-mini-refresh' data-refresh>刷新</button>" +
    "<button type='button' class='btn btn-ghost danger-ghost btn-mini-del' data-del>删除</button>" +
    "</div></div>" +
    "<div class='project-expand' hidden></div>";
  li.querySelector("strong").textContent = title;
  li.querySelector(".project-phase").textContent = right;
  const row = li.querySelector(".project-row");
  row.addEventListener("click", () => toggleProject(p.id));
  const refreshBtn = li.querySelector("[data-refresh]");
  refreshBtn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    refreshProjectRow(p.id, refreshBtn);
  });
  const delBtn = li.querySelector("[data-del]");
  delBtn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    deleteProject(p.id, title);
  });
  ul.appendChild(li);
  return li;
}

function projectJobId(p) {
  if (!p) return "";
  const job = p.job || {};
  return String(
    job.job_id || (p.protocol && p.protocol.job_id) || p.protocol_job_id || ""
  ).trim();
}

function isSubmittedProject(p) {
  // 任务页：已投递的都显示（含排队/计算中）；未点「确认计算」的「方案就绪」不进列表
  if (!p) return false;
  if (projectJobId(p)) return true;
  const job = p.job || {};
  const ph = String(p.phase || "").toLowerCase();
  const st = String(job.status || "").toLowerCase();
  if (["pending", "running", "done", "error", "cancelled"].includes(st)) return true;
  return ["running", "analyzed", "manuscript", "error", "cancelled"].includes(ph);
}

function setProjectListHint(kind, text) {
  const emptyEl = $("project-list-empty");
  const errEl = $("project-list-error");
  if (emptyEl) emptyEl.hidden = kind !== "empty";
  if (errEl) {
    errEl.hidden = kind !== "error";
    errEl.textContent = text || "";
  }
}

async function ensureListedProject(id) {
  if (!id) return null;
  const ul = $("project-list");
  if (ul && ul.querySelector('.project-item[data-id="' + id + '"]')) return id;
  try {
    const full = await api("/api/projects/" + id);
    const proj = full.project || full;
    if (!proj || !proj.id) return null;
    const proto = proj.protocol || {};
    const summary = {
      id: proj.id,
      title: proj.title,
      phase: proj.phase,
      job: proj.job || null,
      protocol: { job_id: proto.job_id, kind: proto.kind },
      protocol_job_id: proto.job_id || "",
    };
    if (!isSubmittedProject(summary) && !projectJobId(summary)) return null;
    if (ul && !ul.querySelector('.project-item[data-id="' + proj.id + '"]')) {
      appendProjectListItem(summary);
    }
    setProjectListHint("", "");
    return proj.id;
  } catch (_) {
    return null;
  }
}

async function loadProjects() {
  const ul = $("project-list");
  if (!ul) return;
  const keepId = currentProjectId;
  stashCurrentTaskDetail();
  parkProjectDetail();
  setProjectListHint("", "");
  let listed = [];
  try {
    const data = await api("/api/projects");
    listed = (data.projects || []).filter(isSubmittedProject);
  } catch (e) {
    ul.innerHTML = "";
    setProjectListHint("error", asDisplayText(e && e.message, "无法加载任务列表，请点刷新或重新打开「任务」。"));
    if (keepId) await ensureListedProject(keepId);
    if (keepId && ul.querySelector('.project-item[data-id="' + keepId + '"]')) {
      await showProject(keepId, { silent: true });
    }
    return;
  }
  ul.innerHTML = "";
  listed.forEach((p) => appendProjectListItem(p));
  if (keepId && !ul.querySelector('.project-item[data-id="' + keepId + '"]')) {
    await ensureListedProject(keepId);
  }
  const alive = new Set(
    Array.from(ul.querySelectorAll(".project-item")).map((el) => el.dataset.id)
  );
  Array.from(taskDetailCache.keys()).forEach((k) => {
    if (typeof k === "string" && !alive.has(k)) taskDetailCache.delete(k);
  });
  if (keepId && ul.querySelector('.project-item[data-id="' + keepId + '"]')) {
    await showProject(keepId, { silent: true });
  } else if (keepId && !alive.has(keepId)) {
    stopTaskWatch();
  }
  if (!ul.querySelector(".project-item")) {
    setProjectListHint("empty");
  }
}

async function deleteProject(id, title) {
  const label = title || "该方案";
  const ok = await showConfirmDialog({
    title: "删除方案",
    message: "确定删除「" + label + "」吗？",
    hint: "将取消进行中的计算，并删除本地方案与相关记录，且不可恢复。",
    okText: "删除",
    cancelText: "保留",
    danger: true,
    icon: "⌫",
  });
  if (!ok) return;
  try {
    await api("/api/projects/" + id, { method: "DELETE" });
    taskDetailCache.delete(id);
    const wasOpen = currentProjectId === id;
    if (wasOpen) {
      currentProjectId = "";
      stopTaskWatch();
      parkProjectDetail();
    }
    // 只移除该项，不重建列表，其它任务详情保持不动
    const li = document.querySelector('#project-list .project-item[data-id="' + id + '"]');
    if (li) li.remove();
  } catch (e) {
    await showConfirmDialog({
      title: "删除失败",
      message: e.message || "删除失败",
      okText: "知道了",
      cancelText: "关闭",
      danger: true,
      icon: "!",
    });
  }
}

async function toggleProject(id) {
  if (currentProjectId === id) {
    // 收起：缓存当前详情，再次展开时直接恢复
    stashCurrentTaskDetail();
    currentProjectId = "";
    stopTaskWatch();
    parkProjectDetail();
    return;
  }
  await showProject(id);
}

async function refreshTaskLive(id, updateFigures, opts) {
  const options = opts || {};
  const forceReplot = !!options.forceReplot;
  let poll = null;
  try {
    poll = await api("/api/projects/" + id + "/poll", {
      method: "POST",
      body: JSON.stringify({ force_replot: forceReplot }),
    });
  } catch (_) {
    poll = null;
  }
  const full = await api("/api/projects/" + id);
  const proj = full.project || full;
  let stLabel = unifiedStatus(proj.phase || "", (proj.job || {}).status || "", poll && poll.status);
  if (stLabel === "计算中" && !!(proj.protocol && proj.protocol.analysis)) stLabel = "已完成";
  const phaseEl = document.querySelector(
    '#project-list .project-item[data-id="' + id + '"] .project-phase'
  );
  if (phaseEl) phaseEl.textContent = stLabel;
  renderAnalysis(full.project ? full : { project: proj }, poll);
  if (updateFigures !== false) {
    try {
      const figs = await api("/api/projects/" + id + "/figures");
      fillFigureGallery(figs.figures || []);
    } catch (_) {
      /* ignore */
    }
  }
  if (currentProjectId === id) {
    // soft：保留当前打开的文件与滚动位置，不被进度轮询顶回去
    loadTaskIoPanel({ soft: true }).catch(() => {});
  }
  return poll;
}

async function refreshProjectRow(id, btn) {
  if (btn) btn.disabled = true;
  try {
    const open = currentProjectId === id;
    taskDetailCache.delete(id);
    if (open) {
      await showProject(id, { force: true, silent: true });
      addBubble("已刷新任务详情", "bot");
    } else {
      await api("/api/projects/" + id + "/poll", {
        method: "POST",
        body: JSON.stringify({ force_replot: true }),
      });
      // 只更新该行状态，不整表重建，避免其它任务详情被冲掉
      try {
        const full = await api("/api/projects/" + id);
        const proj = full.project || full;
        const hasResult = !!(proj.protocol && proj.protocol.analysis);
        let st = unifiedStatus(proj.phase || "", (proj.job || {}).status || "");
        if (hasResult && st === "计算中") st = "已完成";
        const phaseEl = document.querySelector(
          '#project-list .project-item[data-id="' + id + '"] .project-phase'
        );
        if (phaseEl) phaseEl.textContent = st;
      } catch (_) {
        /* ignore */
      }
    }
  } catch (e) {
    addBubble("刷新失败：" + (e.message || e), "bot");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function showProject(id, opts) {
  const silent = !!(opts && opts.silent);
  const force = !!(opts && opts.force);
  const li = document.querySelector('#project-list .project-item[data-id="' + id + '"]');
  const slot = li && li.querySelector(".project-expand");
  const detail = $("project-detail");
  if (!li || !slot || !detail) return;

  const prevId = currentProjectId;
  if (prevId && prevId !== id) {
    stashCurrentTaskDetail();
  }

  document.querySelectorAll("#project-list .project-item.is-open").forEach((el) => {
    if (el !== li) {
      el.classList.remove("is-open");
      const other = el.querySelector(".project-expand");
      if (other) other.hidden = true;
    }
  });

  currentProjectId = id;
  stopTaskWatch();
  slot.appendChild(detail);
  detail.hidden = false;
  slot.hidden = false;
  li.classList.add("is-open");
  li.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const cached = !force ? taskDetailCache.get(id) : null;
  if (cached) {
    restoreTaskDetailSnapshot(cached);
    // 进行中的作业后台轻量刷新；已完成则完全复用缓存
    const st = String(cached.jobStatus || "").toLowerCase();
    if (st === "running" || st === "pending") {
      await refreshTaskLive(id, true, { forceReplot: false }).catch(() => {});
      stashCurrentTaskDetail();
    }
    if (!silent) {
      /* quiet */
    }
    return;
  }

  primeTaskDetailShell();
  await refreshTaskLive(id, true, { forceReplot: false }).catch(() => {});
  stashCurrentTaskDetail();
  if (!silent) {
    /* keep bubble quiet when restoring after list refresh */
  }
}

const btnCancelJob = $("btn-cancel-job");
if (btnCancelJob) {
  btnCancelJob.addEventListener("click", async () => {
    if (!currentProjectId) return;
    const ok = await showConfirmDialog({
      title: "取消计算",
      message: "确定取消当前任务的本机计算吗？",
      hint: "已投递的 DFTB+ 作业将被终止；方案本身仍会保留，可重新确认计算。",
      okText: "取消计算",
      cancelText: "继续计算",
      danger: true,
      icon: "⏹",
    });
    if (!ok) return;
    btnCancelJob.disabled = true;
    try {
      const data = await api("/api/projects/" + currentProjectId + "/cancel", {
        method: "POST",
        body: "{}",
      });
      addBubble(data.message || "已取消任务", "bot");
      stopTaskWatch();
      await refreshTaskLive(currentProjectId, true);
      await loadProjects();
    } catch (e) {
      addBubble("取消失败：" + e.message, "bot");
    } finally {
      btnCancelJob.disabled = false;
    }
  });
}

function deployActionLabel(readiness) {
  const r = readiness || {};
  if (!r.wsl_ok) return "部署到本机";
  if (!r.dftb_ok) return "安装 DFTB+";
  if (!r.smoke_ok) return "测试校验";
  return "重新部署";
}

let deployBusy = false;
let deployClockTimer = null;
let deployStartedAt = 0;
let deployLastBase = "";

function lockDeployUi(label) {
  deployBusy = true;
  const btn = $("btn-deploy");
  if (!btn) return;
  btn.disabled = true;
  btn.classList.add("is-busy");
  btn.textContent = label || "正在部署…";
  btn.setAttribute("aria-busy", "true");
}

function unlockDeployUi(readiness) {
  deployBusy = false;
  if (deployClockTimer) {
    clearInterval(deployClockTimer);
    deployClockTimer = null;
  }
  const btn = $("btn-deploy");
  if (!btn) return;
  btn.disabled = false;
  btn.classList.remove("is-busy");
  btn.removeAttribute("aria-busy");
  btn.textContent = deployActionLabel(readiness);
}

function updateDeployButton(readiness) {
  if (deployBusy) return;
  const btn = $("btn-deploy");
  if (!btn || btn.disabled) return;
  btn.textContent = deployActionLabel(readiness);
}

function stripDeployClock(s) {
  return String(s || "").replace(/（已用 \d+ 分 \d+ 秒[^）]*）/g, "").trim();
}

function paintDeployClock() {
  const log = $("deploy-log");
  if (!log) return;
  const started = deployStartedAt || Date.now();
  const sec = Math.max(0, Math.floor((Date.now() - started) / 1000));
  const base = stripDeployClock(deployLastBase) || "正在部署";
  log.textContent = `${base}（已用 ${Math.floor(sec / 60)} 分 ${sec % 60} 秒，请勿关闭软件）`;
}

function syncDeployLog(readiness) {
  if (deployBusy) return;
  const log = $("deploy-log");
  if (!log) return;
  const r = readiness || {};
  if (r.environment_ready) {
    log.textContent = "";
    return;
  }
  if (/部署完成|安装失败|瀹夎|澶辫触|å®è£|å¤±è´¥/.test(log.textContent || "")) {
    log.textContent = "";
  }
}

function startDeployClock(base, startedAt) {
  deployLastBase = stripDeployClock(base) || "正在部署";
  deployStartedAt = startedAt || Date.now();
  if (deployClockTimer) clearInterval(deployClockTimer);
  paintDeployClock();
  deployClockTimer = setInterval(paintDeployClock, 1000);
}

async function refreshDeploy() {
  const st = await api("/api/deploy/status");
  const w = st.wsl || {};
  const r = st.readiness || {};
  const deploying = !!r.deploying;
  const phase = String(r.deploy_phase || "");
  const wslOk = !!r.wsl_ok;
  const dftbOk = !!r.dftb_ok && !deploying;
  const smokeOk = !!r.smoke_ok && !deploying;
  const wslPending = deploying && (phase === "wsl" || phase === "ubuntu") && !wslOk;
  const dftbPending = deploying && (phase === "ubuntu" || phase === "dftb" || phase === "wsl");
  const smokePending = deploying;
  setCheckItem(
    "chk-wsl",
    wslOk && !wslPending,
    wslPending
      ? "正在准备"
      : wslOk
        ? envCardText(w.message || "", "已检测到 WSL")
        : envCardText(w.message || "", r.needs_reboot ? "需先重启电脑" : "未就绪"),
    wslPending
  );
  setCheckItem(
    "chk-dftb",
    dftbOk,
    dftbPending
      ? phase === "dftb"
        ? "正在安装"
        : "等待安装"
      : dftbOk
        ? "已安装并可探测"
        : envCardText((st.dftb && st.dftb.message) || "", "尚未安装"),
    dftbPending
  );
  setCheckItem(
    "chk-smoke",
    smokeOk,
    smokePending
      ? "等待测试校验"
      : (st.smoke && st.smoke.message) || (smokeOk ? "通过" : "未通过"),
    smokePending
  );
  const summary = $("deploy-summary");
  if (summary) {
    if (deploying) {
      summary.hidden = true;
    } else {
      summary.hidden = false;
      summary.textContent = r.summary || "—";
      summary.className =
        "callout" + (r.environment_ready ? " ok-callout" : r.needs_reboot ? " warn-callout" : "");
    }
  }
  updateDeployButton(r);
  syncDeployLog(r);
  paintEnvPill(r);
  const diagEl = $("deploy-diag");
  const diagObj = {
    readiness: r,
    wsl: w,
    dftb: st.dftb || {},
    smoke: st.smoke || {},
  };
  lastDeployDiag = JSON.stringify(diagObj, null, 2);
  if (diagEl) diagEl.textContent = lastDeployDiag;
  return st;
}

const btnRefreshDeploy = $("btn-refresh-deploy");
if (btnRefreshDeploy) {
  btnRefreshDeploy.addEventListener("click", async () => {
    if (deployBusy) return;
    const idle = "刷新";
    setBusyButton(btnRefreshDeploy, true, "刷新中…", idle);
    try {
      const st = await refreshDeploy();
      const r = (st && st.readiness) || {};
      const summary = $("deploy-summary");
      if (summary && r.summary && !r.deploying) {
        summary.hidden = false;
        summary.textContent = r.summary + "（已刷新）";
      }
    } catch (e) {
      const summary = $("deploy-summary");
      if (summary) {
        summary.textContent = "刷新失败：" + (e.message || e);
        summary.className = "callout";
      }
    } finally {
      setBusyButton(btnRefreshDeploy, false, null, idle);
    }
  });
}
async function fetchDeployProgress() {
  const r = await fetch(API + "/api/deploy/progress", {
    headers: { "Content-Type": "application/json" },
  });
  if (!r.ok) return null;
  return r.json();
}

async function resumeDeployIfRunning() {
  if (deployBusy) return;
  let p = null;
  try {
    p = await fetchDeployProgress();
  } catch (_) {
    return;
  }
  if (!p || !p.running) return;
  lockDeployUi("正在部署…");
  deployLastBase = stripDeployClock(p.message) || "正在部署";
  deployStartedAt = p.started_at ? p.started_at * 1000 : Date.now();
  startDeployClock(deployLastBase, deployStartedAt);
  try {
    const data = await waitDeployJob();
    const log = $("deploy-log");
    if (log) log.textContent = envLogText(data && data.message, data && data.log_tail);
    const st = await refreshDeploy().catch(() => null);
    unlockDeployUi((st && st.readiness) || {});
  } catch (_) {
    unlockDeployUi({});
  }
}

async function waitDeployJob() {
  const deadline = Date.now() + 40 * 60 * 1000;
  let data = null;
  let ticks = 0;
  while (Date.now() < deadline) {
    await sleep(1000);
    ticks += 1;
    let p = null;
    try {
      p = await fetchDeployProgress();
    } catch (_) {
      paintDeployClock();
      continue;
    }
    if (p && (p.message || p.log)) {
      deployLastBase = envLogText(stripDeployClock(p.message), p.log);
      if (p.started_at) deployStartedAt = p.started_at * 1000;
    }
    paintDeployClock();
    if (ticks % 5 === 0) {
      refreshDeploy().catch(() => {});
    }
    if (p && p.running === false) {
      data = p.result || { ok: false, message: stripDeployClock(p.message) || "部署未完成" };
      break;
    }
  }
  return data;
}

$("btn-deploy").addEventListener("click", async () => {
  if (deployBusy) return;
    const log = $("deploy-log");
  if (log) log.textContent = "";
  lockDeployUi("正在部署…");
  startDeployClock("正在检查环境…");
  try {
    let st = null;
    try {
      st = await refreshDeploy();
    } catch (_) {
      /* 探测失败不挡部署 */
    }
    let w = (st && st.wsl) || {};
    let r = (st && st.readiness) || {};
    const action = deployActionLabel(r);

    if (w.wsl_required && w.wsl_available === false) {
      deployLastBase = "正在启用 WSL（请在弹出的管理员确认框中允许）";
      paintDeployClock();
      if (window.dftbNeu && typeof window.dftbNeu.ensureWsl === "function") {
        const elev = await window.dftbNeu.ensureWsl();
        if (!elev || !elev.ok) {
          log.textContent = (elev && elev.message) || "未能启用 WSL。请再点「部署到本机」，并允许管理员确认。";
          return;
        }
      }
      const deadline = Date.now() + 90000;
      while (Date.now() < deadline) {
        await sleep(5000);
        st = await refreshDeploy();
        w = (st && st.wsl) || {};
        if (w.wsl_available) break;
        deployLastBase = "已请求启用 WSL。若系统提示重启，请重启后再点「部署到本机」";
        paintDeployClock();
      }
      if (!w.wsl_available) {
        log.textContent = "WSL 功能尚未就绪。若系统提示重启，请重启后再点「部署到本机」。";
        return;
      }
    }

    if (action === "测试校验") deployLastBase = "正在运行测试校验";
    else if (action === "安装 DFTB+") deployLastBase = "正在安装 DFTB+，大约需要几分钟";
    else deployLastBase = "正在部署：从国内镜像安装 Ubuntu，再安装 DFTB+";
    paintDeployClock();

    const start = await api("/api/deploy/run", {
      method: "POST",
      body: JSON.stringify({ ensure_wsl: true }),
    });

    let data = start;
    if (start && (start.started || start.running) && start.running !== false) {
      data = (await waitDeployJob()) || start;
    }

    if (data && data.needs_wsl_feature && window.dftbNeu && typeof window.dftbNeu.ensureWsl === "function") {
      log.textContent = data.message || "需要先启用 WSL。请在管理员确认框中点「是」。";
      const elev = await window.dftbNeu.ensureWsl();
      if (!elev || !elev.ok) {
        if (deployClockTimer) {
          clearInterval(deployClockTimer);
          deployClockTimer = null;
        }
        log.textContent =
          (elev && elev.message) || "未能启用 WSL。请再点「部署到本机」，并允许管理员确认。";
        return;
      }
      await sleep(3000);
      st = await refreshDeploy().catch(() => null);
      w = (st && st.wsl) || {};
      r = (st && st.readiness) || {};
      if (w.wsl2_ready === false && r.needs_reboot) {
        if (deployClockTimer) {
          clearInterval(deployClockTimer);
          deployClockTimer = null;
        }
        log.textContent =
          (elev && elev.message) ||
          "已请求启用 WSL2。请先重启电脑。重启后再打开本软件，点「部署到本机」。";
        return;
      }
      deployLastBase = "WSL 已就绪，继续安装 Ubuntu 与 DFTB+";
      paintDeployClock();
      const start2 = await api("/api/deploy/run", {
        method: "POST",
        body: JSON.stringify({ ensure_wsl: true }),
      });
      data = start2;
      if (start2 && (start2.started || start2.running) && start2.running !== false) {
        data = (await waitDeployJob()) || start2;
      }
    }

    if (deployClockTimer) {
      clearInterval(deployClockTimer);
      deployClockTimer = null;
    }
    const stAfter = await refreshDeploy().catch(() => null);
    const readyAfter = !!(stAfter && stAfter.readiness && stAfter.readiness.environment_ready);
    if (readyAfter) {
      log.textContent = "";
    } else {
      log.textContent = envLogText(data && data.message, data && data.log_tail);
    }
    await refreshStatusPill();
  } catch (e) {
    try {
      const p = await fetchDeployProgress();
      if (p && p.running) {
        deployLastBase = stripDeployClock(p.message) || "正在部署";
        if (p.started_at) deployStartedAt = p.started_at * 1000;
        const data = await waitDeployJob();
        log.textContent = envLogText(data && data.message, data && data.log_tail);
        return;
      }
    } catch (_) {
      /* 进度读不到再报原错误 */
    }
    log.textContent = e.message || String(e);
  } finally {
    let still = false;
    try {
      const p = await fetchDeployProgress();
      still = !!(p && p.running);
    } catch (_) {
      still = false;
    }
    if (!still) {
      let readiness = {};
      try {
        const st = await refreshDeploy();
        readiness = (st && st.readiness) || {};
      } catch (_) {
        /* ignore */
      }
      unlockDeployUi(readiness);
    }
  }
});

async function loadSettings() {
  const s = await api("/api/settings");
  const base = $("deepseek-base");
  const model = $("deepseek-model");
  const dsHint = $("deepseek-hint");
  if (base && !base.dataset.touched) base.value = s.deepseek_base_url || "https://api.deepseek.com";
  if (model && !model.dataset.touched) model.value = s.deepseek_model || "deepseek-v4-flash";
  if (dsHint) {
    dsHint.textContent = s.api_key_set
      ? "当前 Key：" + (s.api_key_hint || "已设置") + "（留空保存则不改动）"
      : "尚未配置本地 DeepSeek Key";
  }
  const key = $("deepseek-key");
  if (key && !key.dataset.touched) key.placeholder = s.api_key_set ? "已设置，输入新 Key 可覆盖" : "sk-…";
}

["deepseek-key", "deepseek-base", "deepseek-model"].forEach((id) => {
  const el = $(id);
  if (!el) return;
  el.addEventListener("input", () => {
    el.dataset.touched = "1";
  });
});

$("btn-save-llm").addEventListener("click", async () => {
  const btn = $("btn-save-llm");
  const msg = $("settings-msg");
  if (btn) btn.disabled = true;
  try {
    const body = {
      llm_provider: "deepseek",
      api_key: ($("deepseek-key").value || "").trim(),
      base_url: ($("deepseek-base").value || "").trim(),
      model: ($("deepseek-model").value || "").trim(),
    };
    const data = await api("/api/settings", { method: "POST", body: JSON.stringify(body) });
    if (msg) {
      msg.hidden = false;
      msg.textContent = JSON.stringify(data.probe || data, null, 2);
    }
    $("deepseek-key").value = "";
    delete $("deepseek-key").dataset.touched;
    await loadSettings();
    await refreshStatusPill();
  } catch (e) {
    if (msg) {
      msg.hidden = false;
      msg.textContent = e.message || String(e);
    }
  } finally {
    if (btn) btn.disabled = false;
  }
});

$("status-llm").addEventListener("click", () => jumpStatus("llm"));
$("status-soft").addEventListener("click", () => jumpStatus("soft"));

const homeNlForm = $("home-nl-form");
if (homeNlForm) {
  homeNlForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = $("btn-home-nl");
    const idle = "开始计算";
    setBusyButton(btn, true, "生成中…", idle);
    try {
      await launchFromHome(true);
    } finally {
      setBusyButton(btn, false, null, idle);
    }
  });
}
const btnHomeToChat = $("btn-home-to-chat");
if (btnHomeToChat) {
  btnHomeToChat.addEventListener("click", () => {
    launchFromHome(false).catch(() => {});
  });
}
document.querySelectorAll(".home-demo").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = $("home-nl-input");
    if (!input) return;
    input.value = btn.dataset.prompt || btn.textContent || "";
    input.focus();
  });
});

const btnHomeGuide = $("btn-home-guide");
const homeGuide = $("home-guide");
const btnHomeGuideClose = $("btn-home-guide-close");
if (btnHomeGuide && homeGuide) {
  btnHomeGuide.addEventListener("click", () => {
    homeGuide.hidden = false;
    homeGuide.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}
if (btnHomeGuideClose && homeGuide) {
  btnHomeGuideClose.addEventListener("click", () => {
    homeGuide.hidden = true;
  });
}

const structFile = $("struct-file");
if (structFile) {
  structFile.addEventListener("change", async (ev) => {
    const f = ev.target.files && ev.target.files[0];
    if (!f) return;
    const text = await f.text();
    $("struct-text").value = text;
    const lower = (f.name || "").toLowerCase();
    if (lower.endsWith(".gen") || looksLikeGen(text)) structureKind = "gen";
    else if (looksLikePoscar(text) || lower.endsWith(".vasp") || lower.endsWith(".poscar")) {
      structureKind = "poscar";
    } else {
      structureKind = "poscar";
    }
    structureUserOwned = true;
    renderStructureViewer("calc");
    if (hsdUserOwned) {
      addBubble("已上传结构。当前使用你上传的输入文件，不会重新生成。", "bot");
    } else {
      scheduleAutoPreview();
      addBubble("已用上传结构覆盖；将按该结构重新生成输入文件。", "bot");
    }
  });
}

const hsdFile = $("hsd-file");
if (hsdFile) {
  hsdFile.addEventListener("change", async (ev) => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!f) return;
    if (f.size > 2 * 1024 * 1024) {
      addBubble("输入文件过大（超过 2 MB），请检查是否选错文件。", "bot");
      return;
    }
    let text = "";
    try {
      text = await f.text();
    } catch (e) {
      addBubble("无法读取该文件。", "bot");
      return;
    }
    if (!text || !text.trim()) {
      addBubble("这个文件是空的。", "bot");
      return;
    }
    if (text.indexOf("\x00") >= 0) {
      addBubble("这不像文本输入文件（HSD）。请上传 dftb_in.hsd 或 .txt。", "bot");
      return;
    }
    const body = text.trim();
    hsdUserOwned = true;
    hsdUploadName = f.name || "dftb_in.hsd";
    currentProjectId = "";
    showHsdPreview(body, "来自上传 · " + hsdUploadName + " · 可编辑", {
      defaultText: body,
      tips: [
        {
          title: "自写输入",
          text: "将按这份 HSD 原样投递。若其中引用了 geo.gen / POSCAR，请同时在下方上传结构。",
        },
      ],
    });
    setCalcProgress("ready", "已载入你上传的输入文件，可编辑后点击下方「确认计算」。");
    let note = "已载入输入文件「" + hsdUploadName + "」。核对后可直接确认计算。";
    if (!looksLikeHsd(body)) {
      note += " 内容不太像标准 HSD，请再看一眼。";
    }
    if (hsdReferencesStructureFile(body) && !structPayload().poscar && !structPayload().gen) {
      note += " 这份输入引用了结构文件，请在下方「结构」上传 POSCAR 或 GEN。";
    }
    addBubble(note, "bot");
  });
}

applyPalette(localStorage.getItem("dftb-neu-palette") || "teal");
document.querySelectorAll(".theme-card").forEach((btn) => {
  btn.addEventListener("click", () => applyPalette(btn.dataset.palette));
});

const figLightbox = $("fig-lightbox");
if (figLightbox) {
  figLightbox.querySelectorAll("[data-fig-dismiss]").forEach((el) => {
    el.addEventListener("click", () => closeFigureLightbox());
  });
}
const figPrev = $("fig-lightbox-prev");
const figNext = $("fig-lightbox-next");
const figExport = $("fig-lightbox-export");
if (figPrev) {
  figPrev.addEventListener("click", () => {
    if (!currentFigures.length) return;
    openFigureLightbox((figLightboxIndex - 1 + currentFigures.length) % currentFigures.length);
  });
}
if (figNext) {
  figNext.addEventListener("click", () => {
    if (!currentFigures.length) return;
    openFigureLightbox((figLightboxIndex + 1) % currentFigures.length);
  });
}
if (figExport) figExport.addEventListener("click", () => exportCurrentFigure());

const btnExportFigs = $("btn-export-figs");
if (btnExportFigs) btnExportFigs.addEventListener("click", () => exportAllFigures());

const ioPrev = $("io-file-prev");
const ioNext = $("io-file-next");
const ioDl = $("io-file-download");
if (ioPrev) {
  ioPrev.addEventListener("click", () => {
    if (!ioFiles.length) return;
    showIoFile((ioFileIndex - 1 + ioFiles.length) % ioFiles.length);
  });
}
if (ioNext) {
  ioNext.addEventListener("click", () => {
    if (!ioFiles.length) return;
    showIoFile((ioFileIndex + 1) % ioFiles.length);
  });
}
if (ioDl) {
  ioDl.addEventListener("click", () => {
    const f = ioFiles[ioFileIndex];
    if (!f) return;
    triggerDownload(f.download_url || f.url + "?download=1", f.name);
  });
}

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") {
    if (figLightbox && !figLightbox.hidden) closeFigureLightbox();
    return;
  }
  if (figLightbox && !figLightbox.hidden) {
    if (ev.key === "ArrowLeft") figPrev && figPrev.click();
    if (ev.key === "ArrowRight") figNext && figNext.click();
  }
});

initAppModal();
bootstrapSession();
