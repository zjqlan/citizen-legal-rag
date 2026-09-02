const gate = document.getElementById("gate");
const shell = document.getElementById("shell");
let chunkPage = 1;

function api(url, options = {}) {
  return fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function fmtTime(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  return d.toLocaleString("zh-CN", { hour12: false });
}

function pct(n) {
  return `${Math.round((n || 0) * 1000) / 10}%`;
}

function kpis(el, items) {
  el.innerHTML = items
    .map((it) => `<div class="kpi"><b>${escapeHtml(String(it.value))}</b><span>${escapeHtml(it.label)}</span></div>`)
    .join("");
}

function bars(el, obj) {
  const entries = Object.entries(obj || {});
  const max = Math.max(1, ...entries.map(([, v]) => v));
  el.innerHTML = entries
    .map(
      ([k, v]) =>
        `<div class="bar"><span>${escapeHtml(k || "空")}</span><i style="width:${(v / max) * 100}%"></i><span>${v}</span></div>`
    )
    .join("") || "<p class='muted'>暂无数据</p>";
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((el) => {
    el.hidden = el.id !== "tab-" + name;
  });
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.tab === name);
  });
  if (name === "chunks") loadChunks();
  if (name === "users") loadUsers();
  if (name === "eval") loadEval();
  if (name === "feedback") loadFeedback();
}

async function loadOverview() {
  const r = await api("/api/admin/overview");
  if (r.status === 401 || r.status === 403) {
    return false;
  }
  const d = await r.json();
  kpis(document.getElementById("kpis"), [
    { value: d.users, label: "注册用户" },
    { value: d.conversations, label: "保存对话" },
    { value: d.questions, label: "用户提问" },
    { value: d.legal_answers, label: "法律回答" },
    { value: d.feedback_good, label: "有用反馈" },
    { value: d.feedback_bad, label: "不准反馈" },
    { value: d.kb.documents || "-", label: "法规部数" },
    { value: d.kb.chunks || "-", label: "检索块" },
  ]);
  const online = (d.pipeline && d.pipeline.online) || [];
  document.getElementById("flow").innerHTML = online
    .map((s) => `<span class="step">${escapeHtml(s)}</span>`)
    .join("");
  bars(document.getElementById("intentBars"), d.intents);
  document.getElementById("recent").innerHTML = (d.recent_questions || [])
    .map(
      (q) =>
        `<p><b>${escapeHtml(q.username)}</b> · ${escapeHtml(q.intent || "")}<br>${escapeHtml(
          (q.content || "").slice(0, 80)
        )}</p>`
    )
    .join("") || "<p class='muted'>暂无提问</p>";
  gate.hidden = true;
  shell.hidden = false;
  return true;
}

async function loadChunks(page) {
  chunkPage = page || chunkPage || 1;
  const q = document.getElementById("chunkQ").value.trim();
  const doc = document.getElementById("chunkDoc").value;
  const typ = document.getElementById("chunkType").value;
  const params = new URLSearchParams({ q, doc_type: doc, chunk_type: typ, page: String(chunkPage) });
  const d = await (await api("/api/admin/chunks?" + params)).json();
  const s = d.stats || {};
  const p = s.processed || {};
  document.getElementById("chunkHint").textContent =
    (s.strategy || "") + ` 已索引 ${s.indexed || 0} 块，覆盖 ${s.laws || 0} 部法规。`;
  kpis(document.getElementById("chunkKpis"), [
    { value: p.chunks || s.indexed || 0, label: "总块数" },
    { value: (s.chunk_types || {}).article || 0, label: "按条" },
    { value: (s.chunk_types || {}).child || 0, label: "按款(子块)" },
    { value: (s.chunk_types || {}).parent || 0, label: "父块" },
    { value: (s.chunk_types || {}).window || 0, label: "窗口块" },
  ]);
  const rows = (d.items || [])
    .map(
      (it) => `<tr>
        <td><button class="link" data-id="${escapeHtml(it.chunk_id)}">查看</button></td>
        <td>${escapeHtml(it.law_name)}</td>
        <td>${escapeHtml(it.article)}</td>
        <td>${escapeHtml(it.chunk_type)}</td>
        <td>${escapeHtml(it.doc_type)}</td>
        <td>${escapeHtml(it.preview || "")}</td>
      </tr>`
    )
    .join("");
  document.getElementById("chunkTable").innerHTML = `
    <table>
      <thead><tr><th></th><th>法律</th><th>条</th><th>切法</th><th>类型</th><th>摘要</th></tr></thead>
      <tbody>${rows || "<tr><td colspan='6'>没有匹配的块</td></tr>"}</tbody>
    </table>`;
  document.querySelectorAll("#chunkTable .link").forEach((btn) => {
    btn.style.cssText = "border:0;background:none;color:#b23a2f;cursor:pointer;";
    btn.addEventListener("click", () => openChunk(btn.dataset.id));
  });
  const pages = Math.max(1, Math.ceil((d.total || 0) / (d.page_size || 20)));
  document.getElementById("chunkPager").innerHTML = `
    <button type="button" ${chunkPage <= 1 ? "disabled" : ""} data-p="${chunkPage - 1}">上一页</button>
    <span>${chunkPage} / ${pages} · 共 ${d.total || 0}</span>
    <button type="button" ${chunkPage >= pages ? "disabled" : ""} data-p="${chunkPage + 1}">下一页</button>`;
  document.querySelectorAll("#chunkPager button").forEach((b) => {
    b.addEventListener("click", () => loadChunks(Number(b.dataset.p)));
  });
}

async function openChunk(id) {
  const d = await (await api("/api/admin/chunks/" + id)).json();
  const view = document.getElementById("chunkView");
  view.hidden = false;
  view.textContent = `《${d.law_name}》${d.article}  [${d.chunk_type}/${d.doc_type}]\n\n${d.text || ""}`;
  view.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function loadUsers() {
  const d = await (await api("/api/admin/users")).json();
  document.getElementById("userTable").innerHTML = `
    <table>
      <thead><tr><th>用户</th><th>角色</th><th>对话</th><th>提问</th><th>最近活跃</th><th>注册</th></tr></thead>
      <tbody>
        ${(d.items || [])
          .map(
            (u) => `<tr>
              <td>${escapeHtml(u.username)}</td>
              <td>${u.is_admin ? "管理员" : "用户"}</td>
              <td>${u.conversations || 0}</td>
              <td>${u.questions || 0}</td>
              <td>${fmtTime(u.last_at)}</td>
              <td>${fmtTime(u.created_at)}</td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

function renderEval(latest) {
  if (!latest) {
    document.getElementById("evalMeta").textContent = "尚未运行评估。";
    document.getElementById("evalKpis").innerHTML = "";
    document.getElementById("evalTable").innerHTML = "";
    return;
  }
  document.getElementById("evalMeta").textContent =
    `最近一次：${fmtTime(latest.finished_at)} · ${latest.n} 道测试题`;
  kpis(document.getElementById("evalKpis"), [
    { value: pct(latest.recall_at_k), label: "测试召回率 Recall@K" },
    { value: (latest.mrr || 0).toFixed(3), label: "MRR" },
    { value: pct(latest.citation_hit), label: "命中标准法条" },
  ]);
  const rows = (latest.detail || [])
    .map((it) => {
      const fb = it.user_feedback || {};
      const rate = fb.good_rate == null ? "暂无真实反馈" : pct(fb.good_rate) + `（${fb.n} 条）`;
      const gold = (it.gold || []).map((g) => `《${g.law_name}》${g.article}`).join("；");
      const got = (it.retrieved || [])
        .slice(0, 3)
        .map((g) => `《${g.law_name}》${g.article}`)
        .join("；");
      return `<tr>
        <td>${escapeHtml(it.topic)}<br><b>${escapeHtml(it.question)}</b></td>
        <td class="${it.hit ? "hit" : "miss"}">${it.hit ? "命中 #" + it.rank : "未命中"}</td>
        <td>${escapeHtml(gold)}</td>
        <td>${escapeHtml(got)}</td>
        <td>${escapeHtml(rate)}</td>
      </tr>`;
    })
    .join("");
  document.getElementById("evalTable").innerHTML = `
    <table>
      <thead><tr><th>测试题</th><th>检索评估</th><th>标准法条</th><th>实际召回 Top3</th><th>用户反馈</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function loadEval() {
  const d = await (await api("/api/admin/eval")).json();
  renderEval(d.latest);
}

async function runEval() {
  const btn = document.getElementById("runEval");
  btn.disabled = true;
  btn.textContent = "评估中，约需半分钟…";
  try {
    const r = await api("/api/admin/eval/run", { method: "POST" });
    const d = await r.json();
    if (!r.ok) {
      document.getElementById("evalMeta").textContent = d.detail || "评估失败";
      return;
    }
    renderEval(d);
  } finally {
    btn.disabled = false;
    btn.textContent = "运行检索评估";
  }
}

async function loadFeedback() {
  const d = await (await api("/api/admin/feedback")).json();
  document.getElementById("fbList").innerHTML =
    (d.items || [])
      .map(
        (it) => `<div class="fb-card">
          <div class="muted">${escapeHtml(it.username)} · ${it.rating === 1 ? "有用" : "不准"} · ${fmtTime(
            it.created_at
          )}</div>
          <p><b>问：</b>${escapeHtml(it.question || "")}</p>
          <p>${escapeHtml(it.answer || "")}</p>
          ${it.comment ? `<p class="muted">补充：${escapeHtml(it.comment)}</p>` : ""}
        </div>`
      )
      .join("") || "<p class='muted'>还没有用户反馈。问答页每条回答下可点「有用 / 不准」。</p>";
}

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});
document.getElementById("chunkForm").addEventListener("submit", (e) => {
  e.preventDefault();
  loadChunks(1);
});
document.getElementById("runEval").addEventListener("click", runEval);

let captchaId = "";
let captchaReq = 0;

async function loadCaptcha() {
  const box = document.getElementById("adminCaptchaBox");
  const req = ++captchaReq;
  box.innerHTML = "刷新中";
  try {
    const r = await api("/api/auth/captcha");
    const d = await r.json();
    if (req !== captchaReq) return;
    captchaId = d.captcha_id || "";
    box.innerHTML = d.svg || "点击刷新";
    document.getElementById("adminCaptcha").value = "";
  } catch {
    if (req !== captchaReq) return;
    box.textContent = "加载失败，点击重试";
  }
}

function setGateErr(msg) {
  const el = document.getElementById("gateErr");
  el.hidden = !msg;
  el.textContent = msg || "";
}

function showGate(hint) {
  gate.hidden = false;
  shell.hidden = true;
  document.getElementById("gateHint").textContent = hint || "";
  loadCaptcha();
}

async function enterAdmin() {
  const ok = await loadOverview();
  if (!ok) showGate("当前登录账号没有管理员权限，请改用 admin 登录。");
}

document.getElementById("adminCaptchaBox").addEventListener("click", loadCaptcha);
document.getElementById("adminLogin").addEventListener("submit", async (e) => {
  e.preventDefault();
  setGateErr("");
  const btn = document.getElementById("adminSubmit");
  btn.disabled = true;
  try {
    const r = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("adminUser").value.trim(),
        password: document.getElementById("adminPass").value,
        captcha_id: captchaId,
        captcha: document.getElementById("adminCaptcha").value.trim(),
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setGateErr(d.detail || "登录失败");
      await loadCaptcha();
      return;
    }
    if (!d.is_admin) {
      setGateErr("这个账号不是管理员。请使用 .env 里配置的管理员账号。");
      await loadCaptcha();
      return;
    }
    document.getElementById("adminPass").value = "";
    await enterAdmin();
  } catch {
    setGateErr("网络异常，请确认服务已启动。");
    await loadCaptcha();
  } finally {
    btn.disabled = false;
  }
});

(async () => {
  try {
    const me = await (await api("/api/auth/me")).json();
    if (me.ok && me.is_admin) {
      await enterAdmin();
      return;
    }
    showGate(me.ok ? `当前登录的是「${me.username}」，不是管理员。` : "请先登录管理员账号。");
  } catch {
    showGate("服务未连接，请先启动问答服务。");
  }
})();
