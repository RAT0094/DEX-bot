const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

const initData = tg.initData || "";
let currentConversationId = null;
let isSending = false;

const messagesEl = document.getElementById("messages");
const welcomeEl = document.getElementById("welcome");
const inputEl = document.getElementById("input");
const historyEl = document.getElementById("history");
const typingEl = document.getElementById("typing");
const modelSelect = document.getElementById("modelSelect");
const sidebar = document.getElementById("sidebar");
const overlay = document.getElementById("overlay");

// تنظیمات marked
if (window.marked) {
  marked.setOptions({ breaks: true, gfm: true });
}

function toggleSidebar() {
  sidebar.classList.toggle("max-md:translate-x-full");
  overlay.classList.toggle("hidden");
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

function quickPrompt(text) {
  inputEl.value = text;
  send();
}

function newChat() {
  currentConversationId = null;
  messagesEl.innerHTML = welcomeEl.outerHTML;
  if (window.innerWidth < 768) toggleSidebar();
  inputEl.focus();
}

function clearCurrentChat() {
  if (!currentConversationId) {
    messagesEl.innerHTML = welcomeEl.outerHTML;
    return;
  }
  if (!confirm("این گفتگو پاک شود؟")) return;
  fetch(`/api/conversations/${currentConversationId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initData })
  }).finally(() => {
    newChat();
    loadConversations();
  });
}

function showTyping(show) {
  typingEl.classList.toggle("hidden", !show);
}

function hideWelcome() {
  const w = document.getElementById("welcome");
  if (w) w.style.display = "none";
}

function renderMessage(role, content, isHtml) {
  hideWelcome();
  const isUser = role === "user";
  const wrap = document.createElement("div");
  wrap.className = isUser ? "flex justify-end px-4 py-2" : "flex justify-start px-4 py-2";

  const bubble = document.createElement("div");
  bubble.className = isUser
    ? "bg-[#2f2f2f] text-white px-4 py-3 rounded-2xl max-w-[80%] text-sm leading-7 whitespace-pre-wrap"
    : "bg-transparent text-[#ececec] px-1 py-2 max-w-[90%] text-sm leading-7 prose prose-invert";

  if (isUser) {
    bubble.textContent = content;
  } else {
    if (isHtml) {
      bubble.innerHTML = content;
    } else {
      let html = "";
      try { html = marked.parse(content); } catch (e) { html = content; }
      bubble.innerHTML = html;
      bubble.querySelectorAll("pre code").forEach((block) => {
        try { hljs.highlightElement(block); } catch (e) {}
      });
      // لینک تصاویر را به عکس تبدیل کن
      const urls = content.match(/https?:\/\/\S+/g) || [];
      urls.forEach((u) => {
        const low = u.toLowerCase();
        if (low.endsWith(".png") || low.endsWith(".jpg") || low.endsWith(".jpeg") || low.endsWith(".webp") || low.includes("image")) {
          const img = document.createElement("img");
          img.src = u;
          img.className = "rounded-xl mt-3 max-w-full border border-[#333]";
          img.loading = "lazy";
          bubble.appendChild(img);
        }
      });
    }
  }

  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function isImagePrompt(text) {
  const low = text.toLowerCase();
  const triggers = ["عکس بساز", "تصویر بساز", "نقاشی بکش", "طراحی کن", "برام بکش", "برام بساز", "generate image", "create image"];
  return triggers.some((t) => low.includes(t));
}

async function send() {
  const text = inputEl.value.trim();
  if (!text || isSending) return;
  isSending = true;
  inputEl.value = "";
  autoResize(inputEl);

  renderMessage("user", text);
  showTyping(true);

  const model = modelSelect.value;
  const endpoint = isImagePrompt(text) ? "/api/image" : "/api/chat";
  const payload = endpoint === "/api/image"
    ? { initData, prompt: text, model }
    : { initData, message: text, model, conversation_id: currentConversationId };

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "خطا در ارتباط");

    if (endpoint === "/api/image") {
      let content = data.answer || "";
      if (data.urls && data.urls.length) {
        content += "\n\n" + data.urls.join("\n");
      }
      renderMessage("assistant", content);
    } else {
      currentConversationId = data.conversation_id;
      renderMessage("assistant", data.answer);
      loadConversations();
    }
  } catch (e) {
    renderMessage("assistant", "❌ خطا: " + e.message + " - لطفا دوباره تلاش کن");
  } finally {
    showTyping(false);
    isSending = false;
  }
}

async function loadConversations() {
  if (!initData) return;
  try {
    const res = await fetch(`/api/conversations?initData=${encodeURIComponent(initData)}`);
    const data = await res.json();
    const convs = data.conversations || [];
    if (!convs.length) {
      historyEl.innerHTML = \'<div class="text-xs text-[#666] text-center py-8">هنوز چتی نداری</div>\';
      return;
    }
    historyEl.innerHTML = "";
    convs.forEach((c) => {
      const btn = document.createElement("button");
      btn.className = `w-full text-right p-2.5 rounded-xl text-xs hover:bg-[#2f2f2f] flex justify-between items-center ${c.id === currentConversationId ? "bg-[#2f2f2f]" : ""}`;
      const title = document.createElement("span");
      title.textContent = c.title || "چت بدون عنوان";
      title.className = "truncate flex-1";
      btn.appendChild(title);
      btn.onclick = () => openConversation(c.id);
      historyEl.appendChild(btn);
    });
  } catch (e) {
    console.log("load convs failed", e);
  }
}

async function openConversation(id) {
  currentConversationId = id;
  messagesEl.innerHTML = "";
  showTyping(true);
  try {
    const res = await fetch(`/api/conversations/${id}?initData=${encodeURIComponent(initData)}`);
    const data = await res.json();
    const msgs = data.messages || [];
    msgs.forEach((m) => renderMessage(m.role, m.content));
    if (window.innerWidth < 768) toggleSidebar();
    loadConversations();
  } catch (e) {
    renderMessage("assistant", "خطا در بارگذاری گفتگو");
  } finally {
    showTyping(false);
  }
}

// لود اولیه
loadConversations();

// فوکوس
inputEl.focus();
