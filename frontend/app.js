const messages = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("question");
const sendButton = document.getElementById("send-button");
const sendIcon = document.getElementById("send-icon");
const characterCount = document.getElementById("character-count");
const clearChatButton = document.getElementById("clear-chat");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const historyList = document.getElementById("history-list");
const historyPanel = document.getElementById("history-panel");
const historyToggle = document.getElementById("history-toggle");
const historyBackdrop = document.getElementById("history-backdrop");
const agrobankAvatarUrl = "https://play-lh.googleusercontent.com/RHFefZVUG-N9L9_-PA3NwU9NkLlUgALApzlYpVKtdDhm5dno3FsKg-IdgS8vGL7IVsevMSr_4LDHTBF9eyZr2wA";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function generateUUID() {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    try {
      return crypto.randomUUID();
    } catch {
      // Continue to getRandomValues fallback.
    }
  }

  if (
    typeof crypto !== "undefined" &&
    typeof crypto.getRandomValues === "function"
  ) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));

    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;

    const hex = [...bytes].map((b) =>
      b.toString(16).padStart(2, "0")
    );

    return (
      hex.slice(0, 4).join("") +
      "-" +
      hex.slice(4, 6).join("") +
      "-" +
      hex.slice(6, 8).join("") +
      "-" +
      hex.slice(8, 10).join("") +
      "-" +
      hex.slice(10, 16).join("")
    );
  }

  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(
    /[xy]/g,
    (char) => {
      const r = (Math.random() * 16) | 0;
      const value = char === "x" ? r : (r & 0x3) | 0x8;
      return value.toString(16);
    }
  );
}

let sessionId = generateUUID();

const state = {
  loading: false,
};
let historyLoaded = false;

/* ==========================================================================
   SECURITY
   ========================================================================== */

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function showAgrobankAvatar(container) {
  const image = document.createElement("img");
  image.src = agrobankAvatarUrl;
  image.alt = "";
  image.decoding = "async";
  image.addEventListener("error", () => {
    container.textContent = "A";
  });
  container.replaceChildren(image);
}

function decodeHtmlEntities(value) {
  const namedEntities = {
    amp: "&",
    nbsp: " ",
    quot: '"',
    apos: "'",
    lt: "<",
    gt: ">",
  };

  return String(value ?? "")
    .replace(
      /&#(?:x([0-9a-f]+)|(\d+));/gi,
      (match, hexadecimal, decimal) => {
        const codePoint = Number.parseInt(
          hexadecimal || decimal,
          hexadecimal ? 16 : 10
        );

        if (
          !Number.isInteger(codePoint) ||
          codePoint < 0 ||
          codePoint > 0x10ffff ||
          (codePoint >= 0xd800 && codePoint <= 0xdfff)
        ) {
          return match;
        }

        return String.fromCodePoint(codePoint);
      }
    )
    .replace(
      /&(amp|nbsp|quot|apos|lt|gt);/gi,
      (match, name) => namedEntities[name.toLowerCase()]
    );
}

function findSourceIndexByUrl(sources, url) {
  const normalizedUrl = String(url ?? "")
    .trim()
    .replace(/\/+$/, "");

  return sources.findIndex(
    (source) =>
      typeof source?.page_url === "string" &&
      source.page_url
        .trim()
        .replace(/\/+$/, "") === normalizedUrl
  );
}

/* ==========================================================================
   MARKDOWN RENDERING
   ========================================================================== */

function renderAnswer(text, sources = []) {
  const raw = String(text ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");

  const lines = raw.split("\n");
  const html = [];

  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    // ------------------------------------------------------------
    // Code block
    // ------------------------------------------------------------
    if (line.trim().startsWith("```")) {
      const codeLines = [];

      i += 1;

      while (
        i < lines.length &&
        !lines[i].trim().startsWith("```")
      ) {
        codeLines.push(lines[i]);
        i += 1;
      }

      if (
        i < lines.length &&
        lines[i].trim().startsWith("```")
      ) {
        i += 1;
      }

      html.push(
        `<pre><code>${escapeHtml(
          codeLines.join("\n")
        )}</code></pre>`
      );

      continue;
    }

    // ------------------------------------------------------------
    // Markdown table
    // ------------------------------------------------------------
    if (
      isTableHeader(line) &&
      i + 1 < lines.length &&
      isTableSeparator(lines[i + 1])
    ) {
      const headers = normalizeTableHeaders(
        parseTableRow(line)
      );
      const rows = [];

      i += 2;

      while (
        i < lines.length &&
        lines[i].trim() &&
        lines[i].includes("|")
      ) {
        const row = parseTableRow(lines[i]);

        if (row.length > 0) {
          rows.push(row);
        }

        i += 1;
      }

      html.push(
        renderTable(headers, rows, sources)
      );

      continue;
    }

    // ------------------------------------------------------------
    // Heading
    // ------------------------------------------------------------
    const heading = line.match(
      /^(#{1,3})\s+(.+)$/
    );

    if (heading) {
      const level = Math.min(
        heading[1].length + 1,
        4
      );

      html.push(
        `<h${level}>${renderInlineMarkdown(
          heading[2],
          sources
        )}</h${level}>`
      );

      i += 1;
      continue;
    }

    // ------------------------------------------------------------
    // Unordered list
    // ------------------------------------------------------------
    if (/^\s*[-*+]\s+/.test(line)) {
      const items = [];

      while (
        i < lines.length &&
        /^\s*[-*+]\s+/.test(lines[i])
      ) {
        const item = lines[i]
          .replace(/^\s*[-*+]\s+/, "")
          .trim();

        items.push(
          `<li>${renderInlineMarkdown(
            item,
            sources
          )}</li>`
        );

        i += 1;
      }

      html.push(
        `<ul>${items.join("")}</ul>`
      );

      continue;
    }

    // ------------------------------------------------------------
    // Ordered list
    // ------------------------------------------------------------
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];

      while (
        i < lines.length &&
        /^\s*\d+[.)]\s+/.test(lines[i])
      ) {
        const item = lines[i]
          .replace(/^\s*\d+[.)]\s+/, "")
          .trim();

        items.push(
          `<li>${renderInlineMarkdown(
            item,
            sources
          )}</li>`
        );

        i += 1;
      }

      html.push(
        `<ol>${items.join("")}</ol>`
      );

      continue;
    }

    // ------------------------------------------------------------
    // Blockquote
    // ------------------------------------------------------------
    if (/^\s*>\s?/.test(line)) {
      const quoteLines = [];

      while (
        i < lines.length &&
        /^\s*>\s?/.test(lines[i])
      ) {
        quoteLines.push(
          lines[i]
            .replace(/^\s*>\s?/, "")
            .trim()
        );

        i += 1;
      }

      html.push(
        `<blockquote>${quoteLines
          .map(
            (quote) =>
              `<div>${renderInlineMarkdown(
                quote,
                sources
              )}</div>`
          )
          .join("")}</blockquote>`
      );

      continue;
    }

    // ------------------------------------------------------------
    // Horizontal rule
    // ------------------------------------------------------------
    if (
      /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)
    ) {
      html.push("<hr>");
      i += 1;
      continue;
    }

    // ------------------------------------------------------------
    // Normal paragraph
    // ------------------------------------------------------------
    const paragraphLines = [line];

    i += 1;

    while (
      i < lines.length &&
      lines[i].trim() &&
      !isBlockStart(lines, i)
    ) {
      paragraphLines.push(lines[i]);
      i += 1;
    }

    html.push(
      `<p>${renderInlineMarkdown(
        paragraphLines.join(" "),
        sources
      )}</p>`
    );
  }

  return html.join("");
}

function renderInlineMarkdown(
  text,
  sources = []
) {
  let value = decodeHtmlEntities(text);

  /*
   * Flatten a malformed nested citation such as:
   * [**\[Submit request**](https://...) ]\(source:15)
   * into one ordinary trusted Markdown link.
   */
  value = value.replace(
    /^\[\*\*(?:\\?\[)?(.+?)\*\*\]\(\s*(https?:\/\/[^\s)]+)(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)\s*\]\s*\\?\(source:\d+\)\s*([.!?]?)$/gi,
    (match, label, url, punctuation) =>
      `[**${label.trim()}**](${url})${punctuation}`
  );

  /*
   * ------------------------------------------------------------
   * Normalize model-generated internal citations BEFORE escaping.
   * ------------------------------------------------------------
   *
   * Supported accidental formats:
   *
   *   【source:2】
   *   【source 2】
   *   【2†source 2】
   *   [source:2]
   *   [2]
   *
   * Preferred format:
   *
   *   [relevant text](source:2)
   *
   * The model should ideally generate the preferred format,
   * but the frontend defensively handles the other formats too.
   */

  /*
   * Convert:
   *
   * text【source:2】
   *
   * into:
   *
   * [text](source:2)
   *
   * This links the text immediately before the marker.
   *
   * We stop at common sentence boundaries.
   */
  value = value.replace(
    /(^|[.!?]\s+|;\s+|,\s+|- )([^.!?\n]+?)\s*【source:(\d+)】/gi,
    (match, prefix, sentence, number) => {
      const cleanText = sentence.trim();

      if (!cleanText) {
        return `${prefix}【source:${number}】`;
      }

      return `${prefix}[${cleanText}](source:${number})`;
    }
  );

  /*
   * Handle marker at the end of a bullet/list item.
   *
   * Example:
   *
   * - Agrobank is a large bank【source:2】.
   *
   * becomes:
   *
   * - [Agrobank is a large bank](source:2).
   */
  value = value.replace(
    /^(\s*[-*+]\s+)(.+?)\s*【source:(\d+)】(?=\.|!|\?|$)/gim,
    (match, bullet, textPart, number) => {
      return `${bullet}[${textPart.trim()}](source:${number})`;
    }
  );

  /*
   * Generic fallback:
   *
   * anything【source:2】
   *
   * Link the text immediately before the marker.
   */
  value = value.replace(
    /([^【\n]{3,}?)\s*【source:(\d+)】/gi,
    (match, textPart, number) => {
      const cleanText = textPart.trim();

      if (!cleanText) {
        return "";
      }

      return `[${cleanText}](source:${number})`;
    }
  );

  /*
   * Other accidental source formats.
   */
  value = value.replace(
    /【source\s*(\d+)】/gi,
    "[source:$1]"
  );

  value = value.replace(
    /【(\d+)†source\s*\d+】/gi,
    "[source:$1]"
  );

  value = value.replace(
    /[ \t\u00a0\u202f]*\[\s*source\s*:?\s*(\d+)\s*\]/gi,
    (match, number) => {
      return `[](source:${number})`;
    }
  );

  /*
   * Plain [1] / [2] citation markers become icon-only links.
   *
   * The source number is used to resolve the URL but is never displayed.
   */
  value = value.replace(
    /[ \t\u00a0\u202f]*\[\s*(\d+)\s*\]/g,
    "[](source:$1)"
  );

  /*
   * A model may add one or more separate [**Source N**](URL) links.
   * Use the URL from the API's source list and show only an icon.
   */
  value = value.replace(
    /[ \t\u00a0\u202f]*\[\s*(?:\*\*\s*)?source\s*:?\s*\d+\s*(?:\*\*)?\s*\]\(\s*(https?:\/\/[^\s)]+)(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/gi,
    (match, url) => {
      const sourceIndex = findSourceIndexByUrl(
        sources,
        url
      );

      return sourceIndex === -1
        ? ""
        : `[](source:${sourceIndex + 1})`;
    }
  );

  // The API's compatibility answer uses a compact linked icon. Keep it
  // as an icon when structured parts are unavailable in an older client.
  value = value.replace(
    /\[↗\]\(\s*(https?:\/\/[^\s)]+)\s*\)/g,
    (match, url) => {
      const sourceIndex = findSourceIndexByUrl(sources, url);
      return sourceIndex === -1 ? "" : `[](source:${sourceIndex + 1})`;
    }
  );

  /*
   * Some models append a separate linked source quotation after the real
   * answer. Attach that trusted URL to the answer itself and discard the
   * repeated quotation.
   *
   * Example:
   *   **Legal name:** Agrobank [**Agrobank**](https://... "Source")
   * becomes:
   *   [**Legal name:** Agrobank](source:1)
   */
  value = value.replace(
    /^(.+?)\s+\[([^\]]+)\]\(\s*(https?:\/\/[^\s)]+)(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)\s*$/gi,
    (match, answerText, citationText, url) => {
      const sourceIndex = findSourceIndexByUrl(
        sources,
        url
      );
      const cleanAnswer = answerText.trim();

      if (sourceIndex === -1) {
        return cleanAnswer;
      }

      return `[${cleanAnswer}](source:${sourceIndex + 1})`;
    }
  );

  /*
   * Convert direct Markdown URLs to internal citations only when the URL
   * exactly matches a source returned by the API. Untrusted URLs are
   * reduced to their label instead of becoming clickable links.
   *
   * This also supports the optional Markdown link title emitted by some
   * models: [label](https://example.com "Page title").
   */
  value = value.replace(
    /\[([^\]]+)\]\(\s*(https?:\/\/[^\s)]+)(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/gi,
    (match, label, url) => {
      const sourceIndex = findSourceIndexByUrl(
        sources,
        url
      );

      if (sourceIndex === -1) {
        return label;
      }

      return `[${label}](source:${sourceIndex + 1})`;
    }
  );

  /*
   * Models sometimes make the entire citation label bold and also put
   * escaped <strong> tags inside it. Remove the redundant outer bold
   * markers, then convert the intended inner emphasis to Markdown.
   */
  value = value.replace(
    /\[\*\*(.*?)\*\*\]\((source:\d+|https?:\/\/[^)\n]+)\)/gi,
    (match, label, destination) =>
      `[${label}](${destination})`
  );

  value = value.replace(
    /\\?<\/?strong>/gi,
    "**"
  );

  // Keep final punctuation before a run of source icons.
  value = value.replace(
    /^(.*?)(\s*(?:\[\]\(source:\d+\)\s*)+)([.!?])\s*$/,
    (match, answer, citations, punctuation) =>
      `${answer.trimEnd()}${punctuation}${citations.trimEnd()}`
  );

  /*
   * Escape everything before generating HTML.
   */
  let safe = escapeHtml(value);

  // Inline code.
  safe = safe.replace(
    /`([^`]+)`/g,
    "<code>$1</code>"
  );

  // Bold.
  safe = safe.replace(
    /\*\*(.+?)\*\*/g,
    "<strong>$1</strong>"
  );

  // Italic.
  safe = safe.replace(
    /(^|[^\*])\*([^*\n]+)\*(?!\*)/g,
    "$1<em>$2</em>"
  );

  /*
   * ------------------------------------------------------------
   * TRUSTED SOURCE CITATIONS
   * ------------------------------------------------------------
   *
   * [Agrobank Mobile](source:1)
   *
   * -> sources[0].page_url
   */
  safe = safe.replace(
    /\[([^\]]*)\]\(source:(\d+)\)(\s*[.,!?;:])?(?=\s|\[|$)/g,
    (match, label, sourceNumber, trailingPunctuation = "") => {
      const index =
        Number(sourceNumber) - 1;

      const source =
        sources[index];

      if (
        !source ||
        typeof source.page_url !== "string" ||
        !source.page_url.trim()
      ) {
        return `${label}${trailingPunctuation}`;
      }

      const title = escapeHtml(
        source.title ||
        source.page_url ||
        `Source ${sourceNumber}`
      );

      const url = escapeHtml(
        source.page_url
      );

      const punctuation = trailingPunctuation.trim();

      return `${label}${punctuation}<a class="citation-link" href="${url}" target="_blank" rel="noopener noreferrer" title="${title}" aria-label="Open source: ${title}"><span aria-hidden="true">↗</span></a>`;
    }
  );

  /*
   * ------------------------------------------------------------
   * SECURITY
   * ------------------------------------------------------------
   *
   * The model is NOT allowed to create arbitrary URLs.
   *
   * Remove Markdown links containing direct URLs.
   */
  safe = safe.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    "$1"
  );

  /*
   * Remove any remaining internal source markers.
   */
  safe = safe.replace(
    /【[^】]*source[^】]*】/gi,
    ""
  );

  return safe;
}

function isTableHeader(line) {
  return (
    line.includes("|") &&
    line.trim().startsWith("|")
  );
}

function isTableSeparator(line) {
  const cells =
    parseTableRow(line);

  if (cells.length < 2) {
    return false;
  }

  return cells.every((cell) =>
    /^:?-{3,}:?$/.test(cell.trim())
  );
}

function parseTableRow(line) {
  let value = line.trim();

  if (value.startsWith("|")) {
    value = value.slice(1);
  }

  if (value.endsWith("|")) {
    value = value.slice(0, -1);
  }

  return value
    .split("|")
    .map((cell) => cell.trim());
}

function normalizeTableHeaders(headers) {
  // Recover the four-column card table when the model joins all headings
  // into its first cell and leaves the other header cells empty.
  if (
    headers.length === 4 &&
    headers.slice(1).every((header) => !header) &&
    /^Card type\s*How to obtain\s*Cost of issuance\s*Main notes$/i.test(
      headers[0]
    )
  ) {
    return [
      "Card type",
      "How to obtain",
      "Cost of issuance",
      "Main notes",
    ];
  }

  return headers;
}

function renderTable(
  headers,
  rows,
  sources
) {
  const headerHtml =
    headers
      .map(
        (header) =>
          `<th>${renderInlineMarkdown(
            header,
            sources
          )}</th>`
      )
      .join("");

  const bodyHtml =
    rows
      .map((row) => {
        const cells =
          headers.map((_, index) => {
            return `
              <td>
                ${renderInlineMarkdown(
                  row[index] ?? "",
                  sources
                )}
              </td>
            `;
          });

        return `<tr>${cells.join("")}</tr>`;
      })
      .join("");

  return `
    <div class="answer-table-wrapper">
      <table class="answer-table">
        <thead>
          <tr>
            ${headerHtml}
          </tr>
        </thead>

        <tbody>
          ${bodyHtml}
        </tbody>
      </table>
    </div>
  `;
}

function isBlockStart(lines, index) {
  const line = lines[index];

  if (!line || !line.trim()) {
    return true;
  }

  if (/^#{1,3}\s+/.test(line)) {
    return true;
  }

  if (/^\s*[-*+]\s+/.test(line)) {
    return true;
  }

  if (/^\s*\d+[.)]\s+/.test(line)) {
    return true;
  }

  if (/^\s*>\s?/.test(line)) {
    return true;
  }

  if (
    index + 1 < lines.length &&
    isTableHeader(line) &&
    isTableSeparator(lines[index + 1])
  ) {
    return true;
  }

  if (
    /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)
  ) {
    return true;
  }

  return false;
}

/* ==========================================================================
   BACKEND STATUS
   ========================================================================== */

function setBackendStatus(ok) {
  statusDot.classList.toggle(
    "online",
    ok
  );

  statusDot.classList.toggle(
    "error",
    !ok
  );

  statusText.textContent =
    ok
      ? "Online"
      : "Unavailable";
}

async function checkBackend() {
  try {
    const response =
      await fetch("/api/health", {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
      });

    if (!response.ok) {
      throw new Error(
        `Health check failed: HTTP ${response.status}`
      );
    }

    setBackendStatus(true);
    if (!historyLoaded) {
      refreshHistory();
    }
  } catch (error) {
    console.error(
      "Backend health check failed:",
      error
    );

    setBackendStatus(false);
  }
}

/* ==========================================================================
   INPUT
   ========================================================================== */

function autoResize() {
  input.style.height = "auto";

  input.style.height =
    `${Math.min(
      input.scrollHeight,
      180
    )}px`;

  characterCount.textContent =
    `${input.value.length} / 2000`;
}

function scrollToBottom() {
  messages.scrollTop =
    messages.scrollHeight;
}

function clearWelcome() {
  document
    .getElementById("welcome-view")
    ?.remove();
}

/* ==========================================================================
   MESSAGES
   ========================================================================== */

function renderStructuredAnswer(parts, sources) {
  const container = document.createElement("div");
  container.className = "structured-answer";
  let currentList = null;

  for (const part of parts) {
    if (!part || typeof part.text !== "string") {
      continue;
    }

    const kind = part.kind;
    const isListItem = kind === "bullet" || kind === "step";
    const listTag = kind === "step" ? "ol" : "ul";
    let element;

    if (isListItem) {
      if (!currentList || currentList.tagName.toLowerCase() !== listTag) {
        currentList = document.createElement(listTag);
        container.appendChild(currentList);
      }
      element = document.createElement("li");
      currentList.appendChild(element);
    } else {
      currentList = null;
      element = document.createElement(kind === "heading" ? "h3" : "p");
      if (kind === "notice") {
        element.className = "answer-notice";
      }
      container.appendChild(element);
    }

    element.textContent = part.text;

    if (!Array.isArray(part.source_ids)) {
      continue;
    }

    for (const sourceId of new Set(part.source_ids)) {
      const source = Number.isInteger(sourceId)
        ? sources[sourceId - 1]
        : null;
      if (!source || typeof source.page_url !== "string") {
        continue;
      }

      let url;
      try {
        url = new URL(source.page_url);
      } catch {
        continue;
      }

      if (
        url.protocol !== "https:" ||
        (url.hostname !== "agrobank.uz" &&
          !url.hostname.endsWith(".agrobank.uz"))
      ) {
        continue;
      }

      const link = document.createElement("a");
      link.className = "citation-link";
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.title = source.title || "Agrobank source";
      link.setAttribute("aria-label", `Open source: ${link.title}`);

      const icon = document.createElement("span");
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = "↗";
      link.appendChild(icon);

      const lastWord = part.text.match(/\S+$/u);
      if (lastWord && lastWord.index > 0) {
        element.textContent = part.text.slice(0, lastWord.index);
        const tail = document.createElement("span");
        tail.className = "citation-tail";
        tail.textContent = lastWord[0];
        tail.appendChild(link);
        element.appendChild(tail);
      } else {
        element.appendChild(link);
      }
      break;
    }
  }

  return container;
}

function addMessage(
  role,
  text,
  sources = [],
  parts = null
) {
  clearWelcome();

  let list =
    messages.querySelector(
      ".message-list"
    );

  if (!list) {
    list = document.createElement("div");
    list.className = "message-list";
    messages.appendChild(list);
  }

  const row =
    document.createElement("article");

  row.className =
    `message-row ${role}`;

  const avatar =
    document.createElement("div");

  avatar.className =
    `avatar ${
      role === "user"
        ? "user-avatar"
        : ""
    }`;

  if (role === "user") {
    avatar.textContent = "You";
  } else {
    showAgrobankAvatar(avatar);
  }

  avatar.setAttribute(
    "aria-hidden",
    "true"
  );

  const stack =
    document.createElement("div");

  stack.className =
    "message-stack";

  const bubble =
    document.createElement("div");

  bubble.className =
    "message-bubble";

  if (role === "assistant") {
    if (Array.isArray(parts) && parts.length > 0) {
      bubble.appendChild(renderStructuredAnswer(parts, sources));
    } else {
      bubble.innerHTML = renderAnswer(text, sources);
    }
  } else {
    bubble.textContent =
      text;
  }

  const meta =
    document.createElement("div");

  meta.className =
    "message-meta";

  meta.textContent =
    role === "user"
      ? "You"
      : "Agrobank AI";

  stack.appendChild(bubble);
  stack.appendChild(meta);

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

/* ==========================================================================
   TYPING INDICATOR
   ========================================================================== */

function addTypingIndicator() {
  clearWelcome();

  let list =
    messages.querySelector(
      ".message-list"
    );

  if (!list) {
    list = document.createElement("div");
    list.className = "message-list";
    messages.appendChild(list);
  }

  const row =
    document.createElement("article");

  row.id =
    "typing-row";

  row.className =
    "message-row assistant";

  const avatar =
    document.createElement("div");

  avatar.className =
    "avatar";

  showAgrobankAvatar(avatar);

  avatar.setAttribute(
    "aria-hidden",
    "true"
  );

  const typing =
    document.createElement("div");

  typing.className =
    "typing";
  typing.setAttribute("role", "status");
  typing.setAttribute("aria-live", "polite");

  const dots = document.createElement("div");
  dots.className = "typing-dots";

  for (let i = 0; i < 3; i += 1) {
    dots.appendChild(
      document.createElement("span")
    );
  }

  const label = document.createElement("span");
  label.className = "typing-label";
  label.textContent = "Analyzing your question…";
  typing.appendChild(dots);
  typing.appendChild(label);

  row.appendChild(avatar);
  row.appendChild(typing);

  list.appendChild(row);

  scrollToBottom();
}

function setTypingPhase(phase) {
  const labels = {
    analyzing: "Analyzing your question…",
    exchange_rates: "Getting current exchange rates…",
    retrieving: "Finding relevant bank information…",
    generating: "Generating the final answer…",
  };
  const label = document.querySelector("#typing-row .typing-label");
  if (label && labels[phase]) {
    label.textContent = labels[phase];
  }
}

function removeTypingIndicator() {
  document
    .getElementById(
      "typing-row"
    )
    ?.remove();
}

/* ==========================================================================
   LOADING
   ========================================================================== */

function setLoading(loading) {
  state.loading =
    loading;

  sendButton.disabled =
    loading ||
    input.value.trim().length < 2;

  input.disabled =
    loading;

  sendIcon.textContent =
    loading
      ? "…"
      : "↑";
}

/* ==========================================================================
   CHAT HISTORY
   ========================================================================== */

function renderHistory(sessions) {
  historyList.replaceChildren();
  if (!sessions.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "No recent chats yet.";
    historyList.appendChild(empty);
    return;
  }

  for (const chat of sessions.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "history-row";

    const button = document.createElement("button");
    button.type = "button";
    button.className = `history-item${chat.session_id === sessionId ? " active" : ""}`;
    button.textContent = chat.title || "Chat";
    button.title = chat.title || "Chat";
    button.setAttribute("aria-current", chat.session_id === sessionId ? "page" : "false");
    button.addEventListener("click", () => loadChatSession(chat.session_id));
    row.appendChild(button);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "history-delete";
    deleteButton.title = "Delete chat";
    deleteButton.setAttribute("aria-label", `Delete chat: ${chat.title || "Chat"}`);
    deleteButton.innerHTML = `<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m5 4v6m4-6v6" /></svg>`;
    deleteButton.addEventListener("click", () => deleteChatSession(chat.session_id));
    row.appendChild(deleteButton);
    historyList.appendChild(row);
  }
}

async function refreshHistory() {
  try {
    const response = await fetch("/api/chat/sessions", {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(`History request failed: HTTP ${response.status}`);
    }
    const sessions = await response.json();
    historyLoaded = true;
    renderHistory(Array.isArray(sessions) ? sessions : []);
  } catch (error) {
    historyLoaded = false;
    console.error("Could not load recent chats:", error);
    if (!historyList.querySelector(".history-row")) {
      historyList.innerHTML = '<p class="history-empty">History unavailable. Retrying when the server is ready…</p>';
    }
  }
}

async function deleteChatSession(id) {
  if (state.loading || !window.confirm("Delete this chat permanently?")) {
    return;
  }

  try {
    const response = await fetch("/api/chat/session", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ session_id: id }),
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(`Delete request failed: HTTP ${response.status}`);
    }

    if (sessionId === id) {
      startNewChat();
    } else {
      refreshHistory();
    }
  } catch (error) {
    console.error("Could not delete chat:", error);
    window.alert("Could not delete this chat. Please try again.");
  }
}

function setHistoryOpen(open) {
  historyPanel.classList.toggle("open", open);
  historyPanel.inert = !open;
  historyBackdrop.classList.toggle("open", open);
  historyToggle.setAttribute("aria-expanded", String(open));
  historyToggle.setAttribute("aria-label", open ? "Close recent chats" : "Recent chats");
  historyToggle.title = open ? "Close recent chats" : "Recent chats";
  if (open) {
    historyPanel.focus();
  }
}

function showWelcome() {
  messages.replaceChildren();
  const welcome = document.createElement("div");
  welcome.id = "welcome-view";
  welcome.className = "welcome-view";
  welcome.innerHTML = `
    <div class="welcome-icon" aria-hidden="true"><img src="/agrobank-chatbot.png" alt=""></div>
    <h2>How can I help you today?</h2>
    <p>Ask about Agrobank cards, tariffs, transfers, services, requirements,
    and other information available on the bank’s public website.</p>
  `;
  messages.appendChild(welcome);
}

function startNewChat() {
  if (state.loading) {
    return;
  }
  sessionId = generateUUID();
  showWelcome();
  setHistoryOpen(false);
  refreshHistory();
  input.focus();
}

async function loadChatSession(id) {
  if (state.loading || !uuidPattern.test(id)) {
    return;
  }

  setLoading(true);
  try {
    const response = await fetch("/api/chat/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ session_id: id }),
    });
    if (!response.ok) {
      throw new Error(`Conversation request failed: HTTP ${response.status}`);
    }
    const savedMessages = await response.json();
    if (!Array.isArray(savedMessages) || !savedMessages.length) {
      throw new Error("This conversation is no longer available.");
    }

    sessionId = id;
    messages.replaceChildren();
    for (const message of savedMessages) {
      if (message.role === "user" || message.role === "assistant") {
        addMessage(message.role, message.content);
      }
    }
    setHistoryOpen(false);
    refreshHistory();
  } catch (error) {
    console.error("Could not open conversation:", error);
    statusText.textContent = "Could not open chat";
  } finally {
    setLoading(false);
    input.focus();
  }
}

/* ==========================================================================
   CHAT
   ========================================================================== */

async function readChatStream(response) {
  if (!response.body) {
    throw new Error("This browser cannot read the chat response stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let result = null;

  function handleLine(line) {
    if (!line.trim()) {
      return;
    }
    const event = JSON.parse(line);
    if (event.type === "phase") {
      setTypingPhase(event.phase);
    } else if (event.type === "error") {
      throw new Error(event.detail || "The chat service could not complete this request.");
    } else if (event.type === "result") {
      result = event.data;
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value || new Uint8Array(), { stream: !done });
      let newline;
      while ((newline = pending.indexOf("\n")) !== -1) {
        handleLine(pending.slice(0, newline));
        pending = pending.slice(newline + 1);
      }
      if (done) {
        break;
      }
    }
    handleLine(pending);
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }

  if (!result) {
    throw new Error("The chat service ended without an answer.");
  }
  return result;
}

async function sendQuestion(question) {
  const text =
    question.trim();

  if (
    text.length < 2 ||
    state.loading
  ) {
    return;
  }

  addMessage(
    "user",
    text
  );

  input.value = "";

  autoResize();

  setLoading(true);
  addTypingIndicator();
  let backendResponded = false;

  try {
    const response =
      await fetch(
        "/api/chat/stream",
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          credentials:
            "same-origin",

          body: JSON.stringify({
            question: text,
            session_id:
              sessionId,
          }),
        }
      );
    backendResponded = response.ok;

    if (!response.ok) {
      const errorPayload = await response.json().catch(() => ({}));
      throw new Error(
        errorPayload?.detail ||
          `Chat request failed: HTTP ${response.status}`
      );
    }

    const payload = await readChatStream(response);

    removeTypingIndicator();

    sessionId =
      payload.session_id ||
      sessionId;

    const answer =
      typeof payload.answer ===
      "string"
        ? payload.answer.trim()
        : "";

    const sources =
      Array.isArray(
        payload.sources
      )
        ? payload.sources
        : [];

    if (!answer) {
      addMessage(
        "assistant",
        "I could not generate an answer. Please try again."
      );
    } else {
      addMessage(
        "assistant",
        answer,
        sources,
        payload.parts
      );
    }

    setBackendStatus(true);
    refreshHistory();
  } catch (error) {
    console.error(
      "Chat request failed:",
      error
    );

    removeTypingIndicator();

    addMessage(
      "assistant",
      `I couldn’t complete your request. ${
        error?.message ||
        "Please try again in a moment."
      }`
    );

    setBackendStatus(backendResponded);
  } finally {
    setLoading(false);
    input.focus();
  }
}

/* ==========================================================================
   EVENTS
   ========================================================================== */

form.addEventListener(
  "submit",
  (event) => {
    event.preventDefault();

    sendQuestion(
      input.value
    );
  }
);

input.addEventListener(
  "input",
  () => {
    autoResize();

    sendButton.disabled =
      state.loading ||
      input.value.trim().length < 2;
  }
);

input.addEventListener(
  "keydown",
  (event) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey
    ) {
      event.preventDefault();

      form.requestSubmit();
    }
  }
);

/* ==========================================================================
   CLEAR CHAT
   ========================================================================== */

clearChatButton.addEventListener("click", startNewChat);
historyToggle.addEventListener("click", () => {
  setHistoryOpen(!historyPanel.classList.contains("open"));
});
historyBackdrop.addEventListener("click", () => {
  setHistoryOpen(false);
  historyToggle.focus();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && historyPanel.classList.contains("open")) {
    setHistoryOpen(false);
    historyToggle.focus();
  }
});

/* ==========================================================================
   STARTUP
   ========================================================================== */

autoResize();
showAgrobankAvatar(document.querySelector(".brand-mark"));
setLoading(false);
checkBackend();
refreshHistory();

setInterval(
  checkBackend,
  30000
);
