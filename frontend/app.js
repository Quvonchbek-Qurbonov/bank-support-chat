const messages = document.getElementById("messages");
const welcomeView = document.getElementById("welcome-view");
const form = document.getElementById("chat-form");
const input = document.getElementById("question");
const sendButton = document.getElementById("send-button");
const sendIcon = document.getElementById("send-icon");
const characterCount = document.getElementById("character-count");
const languageSelect = document.getElementById("language-select");
const clearChatButton = document.getElementById("clear-chat");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");

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
    const response = await fetch("/api/health", { cache: "no-store" });
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
  if (welcomeView) {
    welcomeView.remove();
  }
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
  languageSelect.disabled = loading;
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
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        question: text,
        language: languageSelect.value,
      }),
    });

    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      const detail = payload?.detail || "The chatbot service returned an error.";
      throw new Error(detail);
    }

    removeTypingIndicator();
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
  document.querySelector(".message-list")?.remove();

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
