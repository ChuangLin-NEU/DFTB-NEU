/** 教师端：服务中心地址与教师凭证由安装包预置；本堂密码明文展示。 */

let hubUrl = "";
let teacherPassword = "";
let ready = false;
let lastPublishedPassword = "";
let activePasswords = [];

function $(id) {
  return document.getElementById(id);
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

function teacherHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Teacher-Password": teacherPassword,
  };
}

function setConn(ok, label) {
  const el = $("conn");
  if (!el) return;
  // 仅在已尝试连接后显示；不展示「未配置」
  el.hidden = false;
  el.className = "status-pill " + (ok ? "ok" : "warn");
  el.innerHTML =
    '<span class="status-dot ' +
    (ok ? "ok" : "warn") +
    '"></span><span class="status-label">' +
    (label || (ok ? "已连接" : "未连接")) +
    "</span>";
  const metric = $("metric-conn");
  if (metric) metric.textContent = label || (ok ? "已连接" : "未连接");
}

function setMsg(id, text, kind) {
  const el = $(id);
  if (!el) return;
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    el.className = "msg";
    return;
  }
  el.hidden = false;
  el.textContent = text;
  el.className = "msg" + (kind ? " " + kind : "");
}

async function hubFetch(path, opts = {}) {
  const base = (hubUrl || "").replace(/\/$/, "");
  if (!base) throw new Error("暂时无法连接课堂服务，请稍后重试或刷新。");
  if (!teacherPassword) throw new Error("教师凭证缺失，请重新安装或联系维护人员。");
  const r = await fetch(base + path, {
    ...opts,
    headers: { ...teacherHeaders(), ...(opts.headers || {}) },
  });
  const text = await r.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_) {
    data = { detail: text };
  }
  if (!r.ok) throw new Error(data.detail || text || r.statusText);
  return data;
}

/** 本堂会话默认不过期：数据库里用远期时间占位，界面显示「吊销前有效」。 */
function sessionValidityLabel(s) {
  if (s && s.is_master) return "长期";
  const exp = Number(s && s.expires_at);
  if (!exp || !Number.isFinite(exp)) return "吊销前有效";
  const years = (exp * 1000 - Date.now()) / (365.25 * 86400000);
  if (years > 5) return "吊销前有效";
  return fmt(s.expires_at_iso);
}

function fmt(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch (_) {
    return iso;
  }
}

function loadCachedClassPasswords() {
  try {
    const raw = localStorage.getItem("dftb-teacher-class-pwds");
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) {
        return arr
          .map((x) => String((x && (x.student_password || x)) || "").trim())
          .filter(Boolean);
      }
    }
    const legacy = String(localStorage.getItem("dftb-teacher-class-pwd") || "").trim();
    return legacy ? [legacy] : [];
  } catch (_) {
    return [];
  }
}

function saveCachedClassPasswords(list) {
  try {
    const arr = (list || [])
      .map((x) => ({
        id: x.id || "",
        student_password: String(x.student_password || "").trim(),
      }))
      .filter((x) => x.student_password);
    if (arr.length) {
      localStorage.setItem("dftb-teacher-class-pwds", JSON.stringify(arr));
      localStorage.setItem("dftb-teacher-class-pwd", arr[0].student_password);
    } else {
      localStorage.removeItem("dftb-teacher-class-pwds");
      localStorage.removeItem("dftb-teacher-class-pwd");
    }
  } catch (_) {
    /* ignore */
  }
}

function normalizePasswordList(gate) {
  const fromApi = Array.isArray(gate && gate.passwords) ? gate.passwords : [];
  const list = fromApi
    .map((p) => ({
      id: String((p && p.id) || "").trim(),
      student_password: String((p && (p.student_password || p.code_hint)) || "").trim(),
    }))
    .filter((p) => p.student_password || p.id);
  if (list.length) return list;
  const single = String((gate && (gate.student_password || gate.code_hint)) || "").trim();
  if (single && !single.includes("***")) {
    return [{ id: "", student_password: single }];
  }
  if (gate && gate.has_password) {
    return loadCachedClassPasswords().map((pwd) => ({ id: "", student_password: pwd }));
  }
  return [];
}

function renderPasswordList(list) {
  activePasswords = Array.isArray(list) ? list.slice() : [];
  saveCachedClassPasswords(activePasswords);
  lastPublishedPassword = activePasswords.length
    ? activePasswords[0].student_password || ""
    : "";
  const ul = $("pwd-list");
  const empty = $("pwd-empty");
  const countEl = $("pwd-count");
  const metric = $("metric-pwd");
  if (countEl) {
    countEl.textContent = activePasswords.length ? "(" + activePasswords.length + ")" : "";
  }
  if (metric) {
    if (!activePasswords.length) metric.textContent = "未设置";
    else if (activePasswords.length === 1) {
      metric.textContent = activePasswords[0].student_password || "已设置";
    } else {
      const first = activePasswords[0].student_password || "";
      metric.textContent = first ? first + " 等 " + activePasswords.length + " 个" : activePasswords.length + " 个";
    }
  }
  if (!ul) return;
  ul.innerHTML = "";
  if (!activePasswords.length) {
    ul.hidden = true;
    if (empty) empty.hidden = false;
    return;
  }
  ul.hidden = false;
  if (empty) empty.hidden = true;
  activePasswords.forEach((p) => {
    const li = document.createElement("li");
    li.className = "pwd-item";
    const text = document.createElement("span");
    text.className = "pwd-item-text";
    text.textContent = p.student_password || "（无明文）";
    const actions = document.createElement("div");
    actions.className = "pwd-item-actions";
    if (p.student_password) {
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "btn btn-ghost";
      copyBtn.textContent = "复制";
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(p.student_password);
          setMsg("msg", "已复制：" + p.student_password, "ok");
        } catch (_) {
          setMsg("msg", "复制失败，请手动选择口令。", "err");
        }
      });
      actions.appendChild(copyBtn);
    }
    const revokeBtn = document.createElement("button");
    revokeBtn.type = "button";
    revokeBtn.className = "btn danger";
    revokeBtn.textContent = "吊销";
    revokeBtn.addEventListener("click", async () => {
      const ok = await showConfirmDialog({
        title: "吊销本堂密码",
        message: "确定吊销口令 " + (p.student_password || p.id) + "？",
        hint: "仅注销使用该口令登录的学生；其他口令与会话不受影响。",
        danger: true,
        okText: "吊销",
        cancelText: "取消",
      });
      if (!ok) return;
      try {
        const body = p.id
          ? { password_id: p.id }
          : { student_password: p.student_password };
        const data = await hubFetch("/teacher/gate/revoke", {
          method: "POST",
          body: JSON.stringify(body),
        });
        renderPasswordList(normalizePasswordList(data));
        setMsg("msg", data.message || "已吊销该本堂密码。", "ok");
        await refreshStudents({ quiet: true });
      } catch (e) {
        setMsg("msg", e.message || String(e), "err");
      }
    });
    actions.appendChild(revokeBtn);
    li.appendChild(text);
    li.appendChild(actions);
    ul.appendChild(li);
  });
}

function showTeacherPassword() {
  const text = teacherPassword || "—";
  const el = $("teacher-pwd-current");
  if (el) el.textContent = text;
  const metric = $("metric-teacher-pwd");
  if (metric) metric.textContent = text;
  // 输入栏保持空白，不预填
}

async function loadConfigFromFile() {
  try {
    const r = await fetch("config.json", { cache: "no-store" });
    if (!r.ok) return;
    const cfg = await r.json();
    if (!hubUrl) hubUrl = String((cfg && cfg.hubUrl) || "").trim();
    if (!teacherPassword) teacherPassword = String((cfg && cfg.teacherPassword) || "").trim();
  } catch (_) {
    /* ignore */
  }
}

async function loadConfig() {
  // Electron 预置优先；若 hubUrl 为空再回退读本地 config.json（安装包应写入）
  if (window.dftbTeacher && typeof window.dftbTeacher.getConfig === "function") {
    try {
      const cfg = await window.dftbTeacher.getConfig();
      hubUrl = String((cfg && cfg.hubUrl) || "").trim();
      teacherPassword = String((cfg && cfg.teacherPassword) || "").trim();
    } catch (_) {
      /* ignore */
    }
  }
  if (!hubUrl || !teacherPassword) {
    await loadConfigFromFile();
  }
  hubUrl = (hubUrl || "").replace(/\/$/, "");
}

async function persistTeacherPassword(pwd) {
  teacherPassword = pwd;
  showTeacherPassword();
  if (window.dftbTeacher && typeof window.dftbTeacher.setTeacherPassword === "function") {
    await window.dftbTeacher.setTeacherPassword(pwd);
  }
}

async function refreshStudents(opts) {
  if (!ready || !hubUrl) return;
  const quiet = !!(opts && opts.quiet);
  if (!quiet) setMsg("msg", "刷新中…");
  try {
    const gate = await hubFetch("/teacher/gate");
    const data = await hubFetch("/teacher/sessions");
    const n = data.count || 0;
    setConn(true, "已连接 · 在线 " + n);
    if ($("count")) $("count").textContent = n ? "(" + n + ")" : "";
    const tb = $("students");
    const empty = $("students-empty");
    tb.innerHTML = "";
    const list = data.students || [];
    if (empty) empty.hidden = list.length > 0;
    list.forEach((s) => {
      const tr = document.createElement("tr");
      const device = (s.device_id || "").slice(0, 10);
      const kind = s.is_master
        ? '<span class="tag master">长期</span>'
        : '<span class="tag">本堂</span>';
      tr.innerHTML =
        "<td><strong>" +
        (s.student_id || "") +
        "</strong></td><td>" +
        (s.online_hint || "") +
        "</td><td>" +
        fmt(s.last_seen_iso) +
        "</td><td>" +
        fmt(s.issued_at_iso) +
        "</td><td>" +
        sessionValidityLabel(s) +
        "</td><td>" +
        (s.llm_calls_today || 0) +
        "</td><td title=\"" +
        (s.device_id || "") +
        "\">" +
        (device || "—") +
        "</td><td title=\"" +
        (s.is_master ? "教师永久凭证会话" : "本堂密码会话（不过期，吊销后失效）") +
        "\">" +
        kind +
        "</td><td></td>";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn danger";
      btn.textContent = "注销";
      btn.addEventListener("click", async () => {
        const ok = await showConfirmDialog({
          title: "注销学生会话",
          message: "确定注销学号 " + s.student_id + " 的会话？",
          hint: "注销后该学生需重新输入本堂密码登录。",
          danger: true,
          okText: "注销",
          cancelText: "取消",
        });
        if (!ok) return;
        await hubFetch("/teacher/sessions/revoke", {
          method: "POST",
          body: JSON.stringify({ token_id: s.token_id }),
        });
        await refreshStudents();
      });
      tr.lastChild.appendChild(btn);
      tb.appendChild(tr);
    });
    const pwds = normalizePasswordList(gate);
    renderPasswordList(pwds);
    if (!quiet) {
      if (pwds.length === 1) {
        setMsg("msg", "本堂密码：" + pwds[0].student_password + " · 列表已更新", "ok");
      } else if (pwds.length > 1) {
        setMsg("msg", "已发布 " + pwds.length + " 个本堂密码 · 列表已更新", "ok");
      } else if (gate.has_password) {
        setMsg(
          "msg",
          "本堂密码已在服务端设置，但未返回明文。请重新填写并点「发布本堂密码」。",
          "warn"
        );
      } else {
        setMsg("msg", "尚未设置本堂密码 · 列表已更新");
      }
    }
  } catch (e) {
    setConn(false, "连接失败");
    if (!quiet) setMsg("msg", e.message || String(e), "err");
  }
}

$("btn-set").addEventListener("click", async () => {
  const pwd = ($("student-password").value || "").trim();
  if (!pwd) {
    setMsg("msg", "请填写本堂密码", "err");
    return;
  }
  try {
    const data = await hubFetch("/teacher/gate", {
      method: "POST",
      // 本堂密码不设过期：有效至教师吊销/清空；不向中心写入 session_days
      body: JSON.stringify({ student_password: pwd, session_days: 0 }),
    });
    renderPasswordList(normalizePasswordList(data));
    setMsg("msg", data.message || ("已发布本堂密码：" + pwd), "ok");
    $("student-password").value = "";
    await refreshStudents({ quiet: true });
  } catch (e) {
    setMsg("msg", e.message || String(e), "err");
  }
});

function clearStudentsTable() {
  const tb = $("students");
  const empty = $("students-empty");
  if (tb) tb.innerHTML = "";
  if (empty) empty.hidden = false;
  if ($("count")) $("count").textContent = "";
  setConn(true, "已连接 · 在线 0");
}

$("btn-clear").addEventListener("click", async () => {
  const ok = await showConfirmDialog({
    title: "清空全部",
    message: "确定清空全部本堂口令，并注销本堂短密码会话？",
    hint: "使用永久凭证登录的「长期」会话不会被注销。",
    danger: true,
    okText: "清空全部",
    cancelText: "取消",
  });
  if (!ok) return;
  try {
    const data = await hubFetch("/teacher/gate/clear", {
      method: "POST",
      body: "{}",
    });
    renderPasswordList([]);
    setMsg(
      "msg",
      data.message || "已清空全部本堂口令；短密码会话已注销。",
      "ok"
    );
    await refreshStudents({ quiet: true });
  } catch (e) {
    setMsg("msg", e.message || String(e), "err");
  }
});

$("btn-change-teacher-pwd").addEventListener("click", async () => {
  const cur = ($("teacher-pwd-old").value || "").trim();
  const n1 = ($("teacher-pwd-new").value || "").trim();
  const n2 = ($("teacher-pwd-new2").value || "").trim();
  if (!cur || !n1 || !n2) {
    setMsg("teacher-pwd-msg", "请填写当前密码与新密码。", "err");
    return;
  }
  if (n1 !== n2) {
    setMsg("teacher-pwd-msg", "两次输入的新永久密码不一致。", "err");
    return;
  }
  if (n1.length < 4) {
    setMsg("teacher-pwd-msg", "新永久密码至少 4 位。", "err");
    return;
  }
  try {
    const data = await hubFetch("/teacher/password", {
      method: "POST",
      body: JSON.stringify({ current_password: cur, new_password: n1 }),
    });
    await persistTeacherPassword(data.teacher_password || n1);
    $("teacher-pwd-new").value = "";
    $("teacher-pwd-new2").value = "";
    $("teacher-pwd-old").value = "";
    setMsg("teacher-pwd-msg", data.message || "永久密码已更新。", "ok");
  } catch (e) {
    setMsg("teacher-pwd-msg", e.message || String(e), "err");
  }
});

(async function init() {
  initAppModal();
  await loadConfig();
  ready = true;
  showTeacherPassword();
  if (!hubUrl) {
    // 不在界面暴露「未预置」文案；安装包应写入 config.json 的 hubUrl
    if ($("conn")) $("conn").hidden = true;
    if ($("metric-conn")) $("metric-conn").textContent = "—";
    return;
  }
  await refreshStudents();
  setInterval(() => refreshStudents({ quiet: true }), 15000);
})();
