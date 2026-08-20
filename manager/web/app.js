/* ============================================================
   NIKKE 机器人管理客户端 · 前端逻辑
   ============================================================ */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

/* ---------- 基础工具 ---------- */
async function api(path, options = {}) {
  const opts = Object.assign({ headers: {} }, options);
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(path, opts);
  let data = {};
  try { data = await resp.json(); } catch (e) { /* ignore */ }
  if (!resp.ok) {
    throw new Error(data.message || ("请求失败 " + resp.status));
  }
  return data;
}

function toast(msg, type = "info", ms = 2600) {
  const box = $("#toast");
  const item = document.createElement("div");
  item.className = "item " + type;
  item.textContent = msg;
  box.appendChild(item);
  setTimeout(() => item.remove(), ms);
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const TAG_CLASS = {
  restart: "restart", alert: "alert", recover: "recover",
  start: "start", stop: "stop", skill: "skill", config: "config", error: "error",
};
const TAG_LABEL = {
  restart: "重启", alert: "告警", recover: "恢复",
  start: "启动", stop: "停止", skill: "技能", config: "配置", error: "错误",
};

/* ---------- 全局状态 ---------- */
let lastStatus = null;
let lastEvents = [];

/* ---------- 导航 ---------- */
const PAGES = {
  dashboard: { title: "总览", id: "page-dashboard" },
  services: { title: "服务管理", id: "page-services" },
  skills: { title: "技能管理", id: "page-skills" },
  ops: { title: "运维监控", id: "page-ops" },
  config: { title: "配置", id: "page-config" },
};

function switchPage(name) {
  if (!PAGES[name]) name = "dashboard";
  $$(".page").forEach((p) => p.classList.remove("active"));
  $("#" + PAGES[name].id).classList.add("active");
  $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.page === name));
  $("#pageTitle").textContent = PAGES[name].title;
  if (name === "dashboard") renderDashboard();
  if (name === "services") renderServices();
  if (name === "skills") renderSkills();
  if (name === "ops") renderOps();
}

/* ---------- 事件渲染 ---------- */
function renderEvents(listEl, events) {
  if (!events.length) {
    listEl.innerHTML = '<div class="empty">暂无记录</div>';
    return;
  }
  listEl.innerHTML = events.map((e) => `
    <div class="event-item">
      <span class="ts">${escapeHtml(e.ts)}</span>
      <span class="tag ${TAG_CLASS[e.type] || ""}">${TAG_LABEL[e.type] || e.type}</span>
      <span class="msg">${escapeHtml(e.service + "：" + e.message)}</span>
    </div>`).join("");
}

/* ---------- 服务状态 ---------- */
function lightClass(ok) { return ok === null || ok === undefined ? "warn" : (ok ? "ok" : "bad"); }

function statusText(ok) {
  return ok === null || ok === undefined ? "检测中" : (ok ? "在线" : "离线");
}

function serviceCardHtml(name, svc) {
  const light = lightClass(svc.ok);
  const since = svc.since ? new Date(svc.since * 1000).toLocaleString() : "-";
  return `
  <div class="svc-card">
    <div class="svc-head">
      <span class="svc-name">${escapeHtml(svc.label)}</span>
      <span class="light ${light}"></span>
    </div>
    <div class="svc-meta">状态：${statusText(svc.ok)} · ${svc.guarded ? "守护中" : "守护暂停"} · 连续失败 ${svc.fails} 次</div>
    <div class="svc-meta">${escapeHtml(svc.detail)}</div>
    <div class="svc-actions">
      ${svc.controllable ? `
      <button class="btn btn-primary" data-service-action="start" data-service="${name}">启动</button>
      <button class="btn btn-ghost" data-service-action="restart" data-service="${name}">重启</button>
      <button class="btn btn-danger" data-service-action="stop" data-service="${name}">停止</button>` : ""}
      ${svc.url ? `<button class="btn btn-ghost" data-open-service="${name}">打开后台</button>` : ""}
    </div>
  </div>`;
}

function renderDashboard() {
  const grid = $("#dashboardCards");
  if (!lastStatus || !lastStatus.services) {
    grid.innerHTML = '<div class="empty">加载中...</div>';
    return;
  }
  const svcs = lastStatus.services;
  // 总览只显示核心四服务 + 链路
  const order = ["astrbot", "napcat", "bridge", "admin", "onebot"];
  grid.innerHTML = order
    .filter((n) => svcs[n])
    .map((n) => serviceCardHtml(n, svcs[n]))
    .join("");
  $("#dashboardEvents").innerHTML = "";
  renderEvents($("#dashboardEvents"), lastEvents.slice(0, 8));
  renderDaemonState();
}

function renderServices() {
  if (!lastStatus || !lastStatus.services) return;
  const order = ["astrbot", "napcat", "bridge", "admin", "onebot"];
  const svcs = lastStatus.services;
  $("#serviceCards").innerHTML = order
    .filter((n) => svcs[n])
    .map((n) => serviceCardHtml(n, svcs[n]))
    .join("");
}

/* ---------- 技能 ---------- */
async function renderSkills() {
  let data;
  try { data = await api("/api/skills"); } catch (e) { toast(e.message, "error"); return; }
  const list = $("#skillList");
  if (!data.skills || !data.skills.length) {
    list.innerHTML = '<div class="empty">暂无技能，点击右上角添加</div>';
    return;
  }
  list.innerHTML = data.skills.map((s) => `
    <div class="skill-item" data-skill="${escapeHtml(s.name)}">
      <div class="skill-info">
        <div class="name">${escapeHtml(s.name)}</div>
        <div class="desc">${escapeHtml(s.desc || "")}</div>
        <div class="cmd">${escapeHtml(s.command || "")}</div>
      </div>
      <div class="skill-actions">
        <label class="switch">
          <input type="checkbox" data-skill-toggle ${s.enabled ? "checked" : ""}>
          <span class="track"></span><span class="thumb"></span>
        </label>
        <button class="btn btn-ghost" data-skill-del>删除</button>
      </div>
    </div>`).join("");
}

/* ---------- 运维 ---------- */
function renderOps() {
  renderOpsStatus();
  renderEvents($("#opsEvents"), lastEvents);
}

function renderDaemonState() {
  if (!lastStatus) return;
  $("#daemonPill").textContent = lastStatus.daemon ? "守护运行中" : "守护已暂停";
  $("#daemonPill").style.color = lastStatus.daemon ? "" : "var(--danger)";
}

function renderOpsStatus() {
  if (!lastStatus) return;
  const svcs = lastStatus.services;
  const rows = Object.keys(svcs).map((n) => {
    const s = svcs[n];
    return `<tr>
      <td>${escapeHtml(s.label)}</td>
      <td><span class="light ${lightClass(s.ok)}"></span> ${statusText(s.ok)}</td>
      <td>${s.fails}</td>
      <td>${escapeHtml(s.detail)}</td>
    </tr>`;
  }).join("");
  $("#opsStatus").innerHTML = `
    <table class="status-table">
      <thead><tr><th>服务</th><th>状态</th><th>连续失败</th><th>详情</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  renderDaemonState();
}

/* ---------- 服务动作 ---------- */
async function runServiceAction(service, action) {
  const actionZh = action === "start" ? "启动" : action === "stop" ? "停止" : "重启";
  const label = service === "all" ? "全部服务" : service;
  toast("正在" + actionZh + "：" + label, "info");
  try {
    const data = await api("/api/services/" + action, {
      method: "POST", body: { service },
    });
    if (data.task_id) {
      // 打开进度弹窗，轮询任务日志（类似思考过程的实时展示）
      openLoading(actionZh + label);
      pollTask(data.task_id);
    } else {
      toast("操作完成", data.ok ? "success" : "error");
      setTimeout(pollStatus, 800);
    }
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------- 操作进度弹窗（任务流式日志） ---------- */
let taskPollTimer = null;

function openLoading(title) {
  $("#loadingTitle").textContent = title;
  $("#loadingLog").innerHTML = "";
  $("#loadingModal").hidden = false;
}

function closeLoading() {
  $("#loadingModal").hidden = true;
  clearTimeout(taskPollTimer);
}

async function pollTask(taskId) {
  try {
    const d = await api("/api/tasks/" + taskId);
    const box = $("#loadingLog");
    const msgs = d.messages || [];
    const rendered = box.querySelectorAll(".item").length;
    for (let i = rendered; i < msgs.length; i++) {
      const div = document.createElement("div");
      div.className = "item";
      div.textContent = msgs[i];
      box.appendChild(div);
    }
    // 最新一条高亮为"当前进行中"
    box.querySelectorAll(".item").forEach((el) => el.classList.remove("current"));
    const last = box.lastElementChild;
    if (last) last.classList.add("current");
    box.scrollTop = box.scrollHeight;
    if (d.done) {
      closeLoading();
      toast("操作完成", d.ok ? "success" : "error");
      // 刷新状态（进程退出/启动需要时间，多刷几次让状态跟上）
      setTimeout(pollStatus, 800);
      for (let i = 1; i <= 4; i++) {
        setTimeout(pollStatus, 800 + i * 2000);
      }
      return;
    }
    taskPollTimer = setTimeout(() => pollTask(taskId), 500);
  } catch (e) {
    closeLoading();
    toast(e.message, "error");
  }
}

/* ---------- 设置表单 ---------- */
async function loadOpsForm() {
  try {
    const cfg = await api("/api/settings");
    const f = $("#opsForm");
    f.daemon_enabled.checked = cfg.daemon_enabled !== false;
    f.check_interval.value = cfg.check_interval;
    f.fail_threshold.value = cfg.fail_threshold;
    f.max_attempts.value = cfg.retry && cfg.retry.max_attempts;
    f.backoff_seconds.value = (cfg.retry && cfg.retry.backoff_seconds || []).join(",");
    f.dingtalk_webhook.value = cfg.alert && cfg.alert.dingtalk_webhook || "";
    f.dingtalk_secret.value = cfg.alert && cfg.alert.dingtalk_secret || "";
    f.cooldown_minutes.value = cfg.alert && cfg.alert.cooldown_minutes;
    f.notify_on_recover.checked = !!(cfg.alert && cfg.alert.notify_on_recover);
  } catch (e) { toast(e.message, "error"); }
}

/* ---------- 背景 ---------- */
function applyBackground(bg) {
  const layer = $("#bgLayer");
  if (!bg) { layer.style.background = ""; return; }
  if (bg.type === "image") {
    layer.style.backgroundImage = "url('/bg')";
    layer.style.background = "";
    layer.style.backgroundImage = "url('/bg')";
    layer.style.backgroundSize = "cover";
    layer.style.backgroundPosition = "center";
  } else if (bg.type === "url" && bg.data) {
    layer.style.backgroundImage = "url(" + JSON.stringify(bg.data) + ")";
    layer.style.backgroundSize = "cover";
    layer.style.backgroundPosition = "center";
  } else {
    layer.style.background = "linear-gradient(135deg, #1e293b 0%, #0f172a 60%, #111827 100%)";
  }
}

/* ---------- 事件绑定 ---------- */
function bindEvents() {
  // 导航
  $$(".nav-item").forEach((n) => n.addEventListener("click", (e) => {
    e.preventDefault();
    switchPage(n.dataset.page);
    history.replaceState(null, "", "#" + n.dataset.page);
  }));

  // 服务动作（事件委托）
  document.addEventListener("click", async (e) => {
    const actBtn = e.target.closest("[data-service-action]");
    if (actBtn) {
      runServiceAction(actBtn.dataset.service, actBtn.dataset.serviceAction);
      return;
    }
    const openBtn = e.target.closest("[data-open-service]");
    if (openBtn) {
      try {
        await api("/api/open_service", {
          method: "POST", body: { service: openBtn.dataset.openService },
        });
      } catch (err) { toast(err.message, "error"); }
      return;
    }
    const delBtn = e.target.closest("[data-skill-del]");
    if (delBtn) {
      const item = delBtn.closest(".skill-item");
      const name = item.dataset.skill;
      if (delBtn.textContent !== "确认删除") {
        delBtn.textContent = "确认删除";
        delBtn.classList.add("btn-danger");
        setTimeout(() => { delBtn.textContent = "删除"; delBtn.classList.remove("btn-danger"); }, 2200);
        return;
      }
      try {
        await api("/api/skills/" + encodeURIComponent(name), { method: "DELETE" });
        toast("已删除技能：" + name, "success");
        renderSkills();
      } catch (err) { toast(err.message, "error"); }
    }
  });

  // 技能开关
  document.addEventListener("change", async (e) => {
    const t = e.target.closest("[data-skill-toggle]");
    if (!t) return;
    const item = t.closest(".skill-item");
    try {
      await api("/api/skills/" + encodeURIComponent(item.dataset.skill), {
        method: "PUT", body: { enabled: t.checked },
      });
      toast("已更新（重启插件后生效）", "success");
    } catch (err) { toast(err.message, "error"); t.checked = !t.checked; }
  });

  // 添加技能弹窗
  $("#addSkillBtn").addEventListener("click", () => {
    $("#skillModal").hidden = false;
    $("#skillForm").name.focus();
  });
  $("#skillClose").addEventListener("click", () => { $("#skillModal").hidden = true; });
  $("#skillForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    try {
      await api("/api/skills", { method: "POST", body: {
        name: form.name.value.trim(),
        desc: form.desc.value.trim(),
        command: form.command.value.trim(),
        enabled: form.enabled.checked,
      }});
      toast("技能已添加", "success");
      form.reset();
      form.enabled.checked = true;
      $("#skillModal").hidden = true;
      renderSkills();
    } catch (err) { toast(err.message, "error"); }
  });

  // 设置表单
  $("#opsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    try {
      await api("/api/settings", { method: "PUT", body: {
        daemon_enabled: f.daemon_enabled.checked,
        check_interval: parseInt(f.check_interval.value, 10),
        fail_threshold: parseInt(f.fail_threshold.value, 10),
        retry: {
          max_attempts: parseInt(f.max_attempts.value, 10),
          backoff_seconds: f.backoff_seconds.value.split(",").map((s) => parseInt(s.trim(), 10)),
        },
        alert: {
          dingtalk_webhook: f.dingtalk_webhook.value.trim(),
          dingtalk_secret: f.dingtalk_secret.value.trim(),
          cooldown_minutes: parseInt(f.cooldown_minutes.value, 10),
          notify_on_recover: f.notify_on_recover.checked,
        },
      }});
      toast("设置已保存", "success");
      setTimeout(pollStatus, 500);
    } catch (err) { toast(err.message, "error"); }
  });

  // 背景弹窗
  $("#bgBtn").addEventListener("click", () => { $("#bgModal").hidden = false; });
  $("#bgClose").addEventListener("click", () => { $("#bgModal").hidden = true; });
  $("#bgReset").addEventListener("click", async () => {
    try {
      await api("/api/background", { method: "POST", body: { type: "gradient" } });
      applyBackground({ type: "gradient" });
      toast("已恢复渐变背景", "success");
      $("#bgModal").hidden = true;
    } catch (e) { toast(e.message, "error"); }
  });
  $("#bgApplyUrl").addEventListener("click", async () => {
    const url = $("#bgUrl").value.trim();
    if (!url) { toast("请输入 URL", "error"); return; }
    try {
      await api("/api/background", { method: "POST", body: { type: "url", url } });
      applyBackground({ type: "url", data: url });
      toast("背景已更新", "success");
      $("#bgModal").hidden = true;
    } catch (e) { toast(e.message, "error"); }
  });
  $("#bgFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        await api("/api/background", { method: "POST", body: { type: "upload", data: reader.result } });
        applyBackground({ type: "image" });
        toast("背景已上传", "success");
        $("#bgModal").hidden = true;
      } catch (err) { toast(err.message, "error"); }
    };
    reader.readAsDataURL(file);
  });

  // 配置导出 / 导入 / 重置
  $("#exportBtn").addEventListener("click", async () => {
    try {
      const data = await api("/api/export");
      const blob = new Blob([JSON.stringify(data.config, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "manager_config_export.json";
      a.click();
      toast("配置已导出", "success");
    } catch (e) { toast(e.message, "error"); }
  });
  $("#importBtn").addEventListener("click", () => $("#importFile").click());
  $("#importFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const cfg = JSON.parse(text);
      await api("/api/import", { method: "POST", body: { config: cfg } });
      toast("配置已导入", "success");
      e.target.value = "";
      loadOpsForm();
    } catch (err) { toast("导入失败：" + err.message, "error"); }
  });
  $("#resetBtn").addEventListener("click", async () => {
    if (!confirm("确认恢复默认配置？")) return;
    try {
      await api("/api/reset", { method: "POST" });
      toast("已恢复默认", "success");
      loadOpsForm();
    } catch (e) { toast(e.message, "error"); }
  });

  // 在浏览器打开
  $("#openBrowserBtn").addEventListener("click", async () => {
    try {
      await api("/api/open_browser", { method: "POST", body: {} });
    } catch (e) { /* ignore */ }
  });

  // 手动刷新状态
  $("#btnRefreshStatus").addEventListener("click", async () => {
    toast("正在刷新服务状态 ...", "info");
    await pollStatus();
    toast("状态已刷新", "success");
  });

  // ---- 系统工具 ----
  $("#btnInstallDeps").addEventListener("click", async () => {
    try {
      const data = await api("/api/system/install_deps", { method: "POST", body: {} });
      toast(data.message || "已启动", data.ok ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
  });

  $("#btnShowQrcode").addEventListener("click", () => showQrcodeModal());
  $("#btnShowLogs").addEventListener("click", () => showLogsModal());
  $("#toolModalClose").addEventListener("click", () => { $("#toolModal").hidden = true; $("#toolModalRefresh").hidden = true; });
  $("#toolModalRefresh").addEventListener("click", () => {
    const kind = $("#toolModalRefresh").dataset.kind;
    if (kind === "qrcode") showQrcodeModal();
    else if (kind === "logs") showLogsModal();
  });
}

/* ---------- 系统工具弹窗 ---------- */
function openToolModal(title, bodyHTML, refreshKind = null) {
  $("#toolModalTitle").textContent = title;
  $("#toolModalBody").innerHTML = bodyHTML;
  $("#toolModalRefresh").hidden = !refreshKind;
  if (refreshKind) $("#toolModalRefresh").dataset.kind = refreshKind;
  $("#toolModal").hidden = false;
}

async function showQrcodeModal() {
  try {
    const info = await api("/api/qrcode/status");
    if (!info.exists) {
      openToolModal("登录二维码",
        `<p class="tool-hint">NapCat 二维码尚未生成。请先启动 NapCat，扫码登录后刷新查看。</p>`,
        "qrcode");
      return;
    }
    openToolModal("登录二维码",
      `<p class="tool-hint">用手机 QQ 扫描下方二维码登录机器人账号（更新于 ${info.mtime_text || "?"}，如已失效点"刷新"）</p>
       <img class="qrcode-img" src="/api/qrcode/image?ts=${Date.now()}" alt="NapCat 登录二维码">`,
      "qrcode");
  } catch (e) { toast(e.message, "error"); }
}

async function showLogsModal() {
  try {
    const data = await api("/api/system/logs");
    const names = Object.keys(data.logs || {});
    if (!names.length) {
      openToolModal("查看日志", `<p class="tool-hint">暂无日志文件</p>`);
      return;
    }
    const tabs = names.map((n, i) =>
      `<button class="btn btn-ghost ${i === 0 ? "active" : ""}" data-log-tab="${n}">${n}</button>`).join("");
    const boxes = names.map((n, i) =>
      `<pre class="log-box" data-log-box="${n}" ${i === 0 ? "" : "hidden"}>${escapeHtml((data.logs[n] || []).join("\n"))}</pre>`).join("");
    openToolModal("查看日志", `<div class="log-tabs">${tabs}</div>${boxes}`, "logs");
    $$("[data-log-tab]").forEach((btn) => btn.addEventListener("click", () => {
      $$("[data-log-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const n = btn.dataset.logTab;
      $$("[data-log-box]").forEach((b) => { b.hidden = b.dataset.logBox !== n; });
    }));
  } catch (e) { toast(e.message, "error"); }
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

/* ---------- 轮询 ---------- */
async function pollStatus() {
  try {
    const data = await api("/api/status");
    lastStatus = data;
    const eventsData = await api("/api/events");
    lastEvents = eventsData.events || [];
  } catch (e) {
    // 后端可能刚重启，忽略本次
  }
  // 刷新当前页面视图
  const active = document.querySelector(".nav-item.active");
  if (active) {
    const page = active.dataset.page;
    if (page === "dashboard") renderDashboard();
    if (page === "services") renderServices();
    if (page === "ops") renderOps();
  }
}

/* ---------- 初始化 ---------- */
(async function init() {
  bindEvents();
  const route = (location.hash || "#dashboard").slice(1);
  switchPage(PAGES[route] ? route : "dashboard");
  await loadOpsForm();
  // 背景
  try {
    const cfg = await api("/api/settings");
    applyBackground(cfg.background);
  } catch (e) { /* ignore */ }
  pollStatus();
  setInterval(pollStatus, 5000);
})();
