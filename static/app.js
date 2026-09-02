const thread = document.getElementById("thread");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");
const metaBox = document.getElementById("metaBox");
const authGate = document.getElementById("authGate");
const authForm = document.getElementById("authForm");
const authUser = document.getElementById("authUser");
const authPass = document.getElementById("authPass");
const authCaptcha = document.getElementById("authCaptcha");
const authSubmit = document.getElementById("authSubmit");
const authErr = document.getElementById("authErr");
const captchaBox = document.getElementById("captchaBox");
const whoEl = document.getElementById("who");
const logoutBtn = document.getElementById("logoutBtn");
const adminLink = document.getElementById("adminLink");
const histList = document.getElementById("histList");
const SUGGEST = [
  "公司口头把我辞退了，有没有经济补偿？",
  "租房到期房东不退押金，怎么办？",
  "网购的衣服不给七天无理由退货，合法吗？",
  "协议离婚后财产没分清，还能再要吗？",
];

let history = [];
let busy = false;
let currentUser = "";
let isAdmin = false;
let authMode = "login";
let captchaId = "";
let captchaReq = 0;
let conversationId = "";
let chats = [];
let sessionId = localStorage.getItem("law_sid");
if (!sessionId) {
  sessionId = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
  localStorage.setItem("law_sid", sessionId);
}

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

function setStatus(ok, text) {
  statusEl.className = "status " + (ok === true ? "ok" : ok === false ? "bad" : "");
  statusEl.innerHTML = `<i></i>${text}`;
}

function showUser(name, admin) {
  currentUser = name || "";
  isAdmin = !!admin;
  if (currentUser) {
    whoEl.hidden = false;
    whoEl.textContent = currentUser;
    logoutBtn.hidden = false;
    adminLink.hidden = !isAdmin;
    authGate.hidden = true;
  } else {
    whoEl.hidden = true;
    whoEl.textContent = "";
    logoutBtn.hidden = true;
    adminLink.hidden = true;
    authGate.hidden = false;
    histList.textContent = "登录后可查看保存的对话。";
  }
}

function renderEmpty() {
  thread.innerHTML = `
    <div class="empty">
      <h2>先说说你遇到的事</h2>
      <p>不必使用法律术语。点下面的问题试一下，也可以自己打字。对话会按账号保存。</p>
      <div class="chips">
        ${SUGGEST.map((q) => `<button type="button" class="chip">${q}</button>`).join("")}
      </div>
    </div>`;
  thread.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => ask(btn.textContent));
  });
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function formatAnswer(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^---+$/gm, "")
    .replace(/\n{3,}/g, "\n\n");
}

function renderCites(cites, parent) {
  if (!cites || !cites.length) return;
  const box = document.createElement("div");
  box.className = "cites";
  cites.forEach((c) => {
    if (!c.law_name) return;
    const tag = document.createElement("span");
    tag.className = "cite";
    tag.textContent = `《${c.law_name}》${c.article || ""}`.trim();
    box.appendChild(tag);
  });
  (parent || thread).appendChild(box);
}

function renderFeedback(messageId, rating) {
  if (!messageId) return;
  const box = document.createElement("div");
  box.className = "fb";
  box.dataset.mid = String(messageId);
  box.innerHTML = `
    <button type="button" data-r="1" class="${rating === 1 ? "on" : ""}">有用</button>
    <button type="button" data-r="-1" class="${rating === -1 ? "on" : ""}">不准</button>`;
  box.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => sendFeedback(messageId, Number(btn.dataset.r), box));
  });
  thread.appendChild(box);
}

async function sendFeedback(messageId, rating, box) {
  const r = await api("/api/feedback", {
    method: "POST",
    body: JSON.stringify({ message_id: messageId, rating }),
  });
  if (!r.ok) return;
  box.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("on", Number(b.dataset.r) === rating);
  });
}

function addMsg(role, text, cites, messageId, rating) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + (role === "user" ? "user" : "bot");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "bot") bubble.innerHTML = formatAnswer(text);
  else bubble.textContent = text;
  wrap.appendChild(bubble);
  thread.appendChild(wrap);
  if (cites && cites.length) renderCites(cites);
  if (role === "bot") renderFeedback(messageId, rating);
  thread.scrollTop = thread.scrollHeight;
}

function startBotBubble() {
  const wrap = document.createElement("div");
  wrap.className = "msg bot";
  const bubble = document.createElement("div");
  bubble.className = "bubble thinking";
  bubble.textContent = "正在对照现行规定…";
  wrap.appendChild(bubble);
  thread.appendChild(wrap);
  thread.scrollTop = thread.scrollHeight;
  return bubble;
}

async function readSse(response, onEvent) {
  const reader = response.body.getReader();
  const dec = new TextDecoder();
  let leftover = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    leftover += dec.decode(value, { stream: true });
    const parts = leftover.split("\n\n");
    leftover = parts.pop() || "";
    for (const block of parts) {
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .join("");
      if (!data) continue;
      onEvent(JSON.parse(data));
    }
  }
}

function renderHist() {
  if (!currentUser) {
    histList.textContent = "登录后可查看保存的对话。";
    return;
  }
  if (!chats.length) {
    histList.textContent = "还没有保存的对话。";
    return;
  }
  histList.innerHTML = chats
    .map(
      (c) => `
      <button type="button" class="hist-item ${c.id === conversationId ? "on" : ""}" data-id="${c.id}">
        <b>${escapeHtml(c.title || "新对话")}</b>
        <span>${escapeHtml(c.preview || "")}</span>
      </button>`
    )
    .join("");
  histList.querySelectorAll(".hist-item").forEach((btn) => {
    btn.addEventListener("click", () => openChat(btn.dataset.id));
  });
}

async function loadChats() {
  if (!currentUser) return;
  try {
    const d = await (await api("/api/chats")).json();
    chats = d.items || [];
    renderHist();
  } catch {
    histList.textContent = "历史加载失败";
  }
}

async function openChat(id) {
  const r = await api("/api/chats/" + id);
  if (!r.ok) return;
  const d = await r.json();
  conversationId = d.id;
  history = (d.messages || []).map((m) => ({ role: m.role, content: m.content })).slice(-12);
  thread.innerHTML = "";
  (d.messages || []).forEach((m) => {
    addMsg(m.role, m.content, m.citations, m.role === "assistant" ? m.id : null, m.feedback);
  });
  if (!d.messages || !d.messages.length) renderEmpty();
  renderHist();
  document.querySelector(".rail")?.classList.remove("show");
}

function startNewChat() {
  history = [];
  conversationId = "";
  sessionId = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
  localStorage.setItem("law_sid", sessionId);
  renderEmpty();
  renderHist();
  input.focus();
}

function setAuthErr(msg) {
  if (!msg) {
    authErr.hidden = true;
    authErr.textContent = "";
    return;
  }
  authErr.hidden = false;
  authErr.textContent = msg;
}

async function loadCaptcha() {
  const req = ++captchaReq;
  captchaBox.innerHTML = "刷新中";
  try {
    const r = await api("/api/auth/captcha");
    const d = await r.json();
    if (req !== captchaReq) return;
    captchaId = d.captcha_id || "";
    captchaBox.innerHTML = d.svg || "点击刷新";
    authCaptcha.value = "";
  } catch {
    if (req !== captchaReq) return;
    captchaBox.textContent = "加载失败，点击重试";
  }
}

function setAuthMode(mode) {
  authMode = mode;
  document.querySelectorAll(".auth-tab").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.mode === mode);
  });
  authPass.autocomplete = mode === "login" ? "current-password" : "new-password";
  authSubmit.textContent = mode === "login" ? "登录" : "注册并登录";
  setAuthErr("");
  loadCaptcha();
}

async function restoreLatest() {
  await loadChats();
  if (chats.length) await openChat(chats[0].id);
  else startNewChat();
}

async function checkMe() {
  try {
    const r = await api("/api/auth/me");
    const d = await r.json();
    if (d.ok && d.username) {
      showUser(d.username, d.is_admin);
      await restoreLatest();
      return true;
    }
  } catch {
    /* show login */
  }
  showUser("", false);
  await loadCaptcha();
  return false;
}

async function waitReady() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await api("/api/health");
      const d = await r.json();
      if (d.ok) {
        setStatus(true, "已就绪");
        return true;
      }
      setStatus(null, "知识库加载中");
    } catch {
      setStatus(false, "服务未连接");
    }
    await new Promise((res) => setTimeout(res, 1500));
  }
  setStatus(false, "加载超时");
  return false;
}

async function loadMeta() {
  try {
    const d = await (await api("/api/meta")).json();
    const s = d.stats || {};
    const types = s.doc_types
      ? Object.entries(s.doc_types).map(([k, v]) => `${k} ${v}`).join(" · ")
      : "";
    metaBox.textContent = `已入库 ${s.documents || "-"} 部法规，${s.chunks || "-"} 条检索块。${types}`;
  } catch {
    metaBox.textContent = "统计暂不可用";
  }
}

async function ask(text) {
  const q = (text || "").trim();
  if (!q || busy) return;
  if (!currentUser) {
    await checkMe();
    if (!currentUser) return;
  }
  if (thread.querySelector(".empty")) thread.innerHTML = "";
  addMsg("user", q);
  input.value = "";
  busy = true;
  sendBtn.disabled = true;
  const bubble = startBotBubble();
  let acc = "";
  let cites = [];
  let saved = null;
  try {
    const r = await api("/api/ask/stream", {
      method: "POST",
      body: JSON.stringify({
        question: q,
        history,
        session_id: sessionId,
        conversation_id: conversationId || null,
      }),
    });
    if (r.status === 401) {
      bubble.remove();
      showUser("", false);
      await loadCaptcha();
      return;
    }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      bubble.classList.remove("thinking");
      bubble.textContent = d.detail || "暂时无法回答，请稍后再试。";
      return;
    }
    await readSse(r, (ev) => {
      if (ev.event === "delta" && ev.text) {
        if (bubble.classList.contains("thinking")) {
          bubble.classList.remove("thinking");
          acc = "";
        }
        acc += ev.text;
        bubble.innerHTML = formatAnswer(acc);
        thread.scrollTop = thread.scrollHeight;
      }
      if (ev.event === "citations") cites = ev.citations || [];
      if (ev.event === "saved") saved = ev;
    });
    if (!acc) {
      bubble.classList.remove("thinking");
      bubble.textContent = "暂时没有生成回答，请再试一次。";
      return;
    }
    renderCites(cites);
    if (saved && saved.message_id) renderFeedback(saved.message_id, 0);
    if (saved && saved.conversation_id) conversationId = saved.conversation_id;
    history.push({ role: "user", content: q });
    history.push({ role: "assistant", content: acc });
    history = history.slice(-12);
    loadChats();
  } catch {
    bubble.classList.remove("thinking");
    bubble.textContent = "网络异常，请确认服务已启动后再试。";
  } finally {
    busy = false;
    sendBtn.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  ask(input.value);
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    ask(input.value);
  }
});
document.getElementById("newChat").addEventListener("click", startNewChat);
document.getElementById("histBtn")?.addEventListener("click", () => {
  document.querySelector(".rail")?.classList.toggle("show");
});

document.querySelectorAll(".auth-tab").forEach((btn) => {
  btn.addEventListener("click", () => setAuthMode(btn.dataset.mode));
});
captchaBox.addEventListener("click", loadCaptcha);
authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  setAuthErr("");
  authSubmit.disabled = true;
  try {
    const url = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const r = await api(url, {
      method: "POST",
      body: JSON.stringify({
        username: authUser.value.trim(),
        password: authPass.value,
        captcha_id: captchaId,
        captcha: authCaptcha.value.trim(),
      }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      setAuthErr(d.detail || "登录失败，请重试");
      await loadCaptcha();
      return;
    }
    authPass.value = "";
    authCaptcha.value = "";
    showUser(d.username, d.is_admin);
    await restoreLatest();
    input.focus();
  } catch {
    setAuthErr("网络异常，请确认服务已启动后再试。");
    await loadCaptcha();
  } finally {
    authSubmit.disabled = false;
  }
});
logoutBtn.addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  chats = [];
  startNewChat();
  showUser("", false);
  await loadCaptcha();
});

renderEmpty();
loadMeta();
waitReady();
checkMe();
