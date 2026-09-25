const messages = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("question");
const sendButton = document.getElementById("send-button");
const sendIcon = document.getElementById("send-icon");
const characterCount = document.getElementById("character-count");
const clearChatButton = document.getElementById("clear-chat");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");

function generateUUID() {
  // crypto.randomUUID() requires a secure context (HTTPS or localhost) and
  // throws in insecure contexts, which breaks this whole script if called
  // directly at module scope. crypto.getRandomValues() has no such
  // restriction, so build a UUIDv4 from it instead.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID();
    } catch {
      // fall through to manual generation
    }
  }

  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0"));
    return (
      hex.slice(0, 4).join("") + "-" +
      hex.slice(4, 6).join("") + "-" +
      hex.slice(6, 8).join("") + "-" +
      hex.slice(8, 10).join("") + "-" +
      hex.slice(10, 16).join("")
    );
  }

  // Last-resort fallback (not cryptographically strong, but functional).
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

let sessionId = generateUUID();

const state = {
  loading: false,
};

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function renderAnswer(text) {
  let safe = escapeHtml(String(text ?? ""));
  safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");
  return safe;
}

function setBackendStatus(ok) {
  statusDot.classList.toggle("online", ok);
  statusDot.classList.toggle("error", !ok);
  statusText.textContent = ok ? "Online" : "Unavailable";
}

async function checkBackend() {
  try {
    const response = await fetch("health", { cache: "no-store" });
    setBackendStatus(response.ok);
  } catch {
    setBackendStatus(false);
  }
}

function autoResize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  characterCount.textContent = `${input.value.length} / 2000`;
}

function scrollToBottom() {
  messages.scrollTop = messages.scrollHeight;
}

function clearWelcome() {
  document.getElementById("welcome-view")?.remove();
}

function addMessage(role, text, sources = []) {
  clearWelcome();

  let list = messages.querySelector(".message-list");
  if (!list) {
    list = document.createElement("div");
    list.className = "message-list";
    messages.appendChild(list);
  }

  const row = document.createElement("article");
  row.className = `message-row ${role}`;

  const avatar = document.createElement("div");
  avatar.className = `avatar ${role === "user" ? "user-avatar" : ""}`;
  avatar.textContent = role === "user" ? "You" : "A";
  avatar.setAttribute("aria-hidden", "true");

  const stack = document.createElement("div");
  stack.className = "message-stack";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.innerHTML = renderAnswer(text);

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = role === "user" ? "You" : "Agrobank AI";

  stack.appendChild(bubble);
  stack.appendChild(meta);

  if (sources.length && role === "assistant") {
    const source = sources[0];

    const sourcesWrap = document.createElement("div");
    sourcesWrap.className = "sources";

    const card = document.createElement("div");
    card.className = "source-card";

    const icon = document.createElement("span");
    icon.className = "source-icon";
    icon.textContent = "↗";

    const content = document.createElement("div");
    content.className = "source-content";

    const link = document.createElement("a");
    link.href = source.page_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = source.title || source.page_url;

    const score = document.createElement("div");
    score.className = "source-score";
    score.textContent = `Retrieved source · ${(Number(source.score) || 0).toFixed(2)}`;

    content.appendChild(link);
    content.appendChild(score);

    card.appendChild(icon);
    card.appendChild(content);

    sourcesWrap.appendChild(card);
    stack.appendChild(sourcesWrap);
  }


  if (role === "user") {
    row.appendChild(stack);
    row.appendChild(avatar);
  } else {
    row.appendChild(avatar);
    row.appendChild(stack);
  }

  list.appendChild(row);
  scrollToBottom();
}

function addTypingIndicator() {
  clearWelcome();

  let list = messages.querySelector(".message-list");
  if (!list) {
    list = document.createElement("div");
    list.className = "message-list";
    messages.appendChild(list);
  }

  const row = document.createElement("article");
  row.id = "typing-row";
  row.className = "message-row assistant";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "A";
  avatar.setAttribute("aria-hidden", "true");

  const typing = document.createElement("div");
  typing.className = "typing";
  typing.setAttribute("aria-label", "Agrobank AI is thinking");

  for (let i = 0; i < 3; i += 1) {
    typing.appendChild(document.createElement("span"));
  }

  row.appendChild(avatar);
  row.appendChild(typing);
  list.appendChild(row);
  scrollToBottom();
}

function removeTypingIndicator() {
  document.getElementById("typing-row")?.remove();
}

function setLoading(loading) {
  state.loading = loading;
  sendButton.disabled = loading || input.value.trim().length < 2;
  input.disabled = loading;
  sendIcon.textContent = loading ? "…" : "↑";
}

async function sendQuestion(question) {
  const text = question.trim();
  if (text.length < 2 || state.loading) return;

  addMessage("user", text);
  input.value = "";
  autoResize();
  setLoading(true);
  addTypingIndicator();

  try {
    const response = await fetch("chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        question: text,
        session_id: sessionId,
      }),
    });

    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      const detail = payload?.detail || "The chatbot service returned an error.";
      throw new Error(detail);
    }

    removeTypingIndicator();
    sessionId = payload.session_id || sessionId;
    addMessage("assistant", payload.answer || "I could not generate an answer.", payload.sources || []);
    setBackendStatus(true);
  } catch (error) {
    removeTypingIndicator();
    addMessage(
      "assistant",
      `I couldn’t reach the Agrobank AI service. ${error.message || "Please try again in a moment."}`
    );
    setBackendStatus(false);
  } finally {
    setLoading(false);
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendQuestion(input.value);
});

input.addEventListener("input", () => {
  autoResize();
  sendButton.disabled = state.loading || input.value.trim().length < 2;
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll(".prompt-card").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.prompt || "";
    autoResize();
    input.focus();
  });
});

clearChatButton.addEventListener("click", () => {
  sessionId = generateUUID();

  document.querySelector(".message-list")?.remove();
  document.getElementById("welcome-view")?.remove();

  const empty = document.createElement("div");
  empty.id = "welcome-view";
  empty.className = "welcome-view";
  empty.innerHTML = `
    <div class="welcome-icon" aria-hidden="true">✦</div>
    <h2>How can I help you today?</h2>
    <p>Ask about Agrobank cards, tariffs, transfers, services, requirements, and other information available on the bank’s public website.</p>
    <div class="prompt-grid">
      <button class="prompt-card" type="button" data-prompt="Humo kartani chiqarish narxi qancha?"><span class="prompt-icon">💳</span><span>Humo card fees</span></button>
      <button class="prompt-card" type="button" data-prompt="Agrobank biznes tariflari qanday?"><span class="prompt-icon">📊</span><span>Business tariffs</span></button>
      <button class="prompt-card" type="button" data-prompt="What cards can Agrobank customers use?"><span class="prompt-icon">🏦</span><span>Available cards</span></button>
      <button class="prompt-card" type="button" data-prompt="Какие комиссии есть у Agrobank?"><span class="prompt-icon">ℹ️</span><span>Service fees</span></button>
    </div>
  `;
  messages.appendChild(empty);

  empty.querySelectorAll(".prompt-card").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.prompt || "";
      autoResize();
      input.focus();
    });
  });
});

autoResize();
setLoading(false);
checkBackend();
setInterval(checkBackend, 30000);