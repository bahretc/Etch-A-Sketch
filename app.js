// ===== NotePad Texts =====
// Compose handwritten-style notes and "send" them to phone numbers.
// Conversations are stored per-number in localStorage; the "Open in
// Messages" link uses an sms: URI so a note can be delivered as a real
// text from a phone.

const STORAGE_KEY = "notepad-texts-conversations";

const padEl = document.getElementById("pad");
const messageInput = document.getElementById("message-input");
const charCount = document.getElementById("char-count");
const fontSelect = document.getElementById("font-select");
const sendForm = document.getElementById("send-form");
const phoneInput = document.getElementById("phone-input");
const formError = document.getElementById("form-error");
const conversationList = document.getElementById("conversation-list");
const noConversations = document.getElementById("no-conversations");
const threadPanel = document.getElementById("thread-panel");
const threadTitle = document.getElementById("thread-title");
const threadMessages = document.getElementById("thread-messages");
const smsLink = document.getElementById("sms-link");
const deleteThreadBtn = document.getElementById("delete-thread-btn");
const newNoteBtn = document.getElementById("new-note-btn");
const toast = document.getElementById("toast");

const PAD_STYLES = ["lined", "blank", "sticky", "grid"];
const FONT_CLASSES = { caveat: "font-caveat", shadows: "font-shadows", patrick: "font-patrick" };

let currentPad = "lined";
let activeNumber = null;
let toastTimer = null;

// ---------- Storage ----------

function loadConversations() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function saveConversations(conversations) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
}

// ---------- Phone helpers ----------

function normalizeNumber(raw) {
  const digits = raw.replace(/\D/g, "");
  if (digits.length < 7 || digits.length > 15) return null;
  return raw.trim().startsWith("+") ? "+" + digits : digits;
}

function formatNumber(number) {
  const digits = number.replace(/\D/g, "");
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  if (digits.length === 11 && digits.startsWith("1")) {
    return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  }
  return number;
}

// ---------- Pad / font pickers ----------

document.querySelectorAll(".pad-choice").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".pad-choice").forEach((b) => {
      b.classList.remove("selected");
      b.setAttribute("aria-pressed", "false");
    });
    btn.classList.add("selected");
    btn.setAttribute("aria-pressed", "true");
    currentPad = btn.dataset.pad;
    PAD_STYLES.forEach((p) => padEl.classList.remove(`pad-${p}`));
    padEl.classList.add(`pad-${currentPad}`);
  });
});

fontSelect.addEventListener("change", () => {
  Object.values(FONT_CLASSES).forEach((c) => padEl.classList.remove(c));
  padEl.classList.add(FONT_CLASSES[fontSelect.value]);
});

messageInput.addEventListener("input", () => {
  charCount.textContent = `${messageInput.value.length} / 500`;
});

// ---------- Sending ----------

sendForm.addEventListener("submit", (event) => {
  event.preventDefault();
  formError.hidden = true;

  const text = messageInput.value.trim();
  const number = normalizeNumber(phoneInput.value);

  if (!text) {
    showError("Write something on the pad first!");
    messageInput.focus();
    return;
  }
  if (!number) {
    showError("That doesn't look like a valid phone number (7–15 digits).");
    phoneInput.focus();
    return;
  }

  const conversations = loadConversations();
  if (!conversations[number]) conversations[number] = [];
  conversations[number].push({
    text,
    pad: currentPad,
    font: fontSelect.value,
    sentAt: Date.now(),
  });
  saveConversations(conversations);

  // Tear-off animation, then reset the pad.
  padEl.classList.add("tear-away");
  setTimeout(() => {
    padEl.classList.remove("tear-away");
    messageInput.value = "";
    charCount.textContent = "0 / 500";
  }, 380);

  renderConversationList();
  openThread(number);
  showToast(`Note sent to ${formatNumber(number)} 📨`);
});

function showError(message) {
  formError.textContent = message;
  formError.hidden = false;
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 2600);
}

// ---------- Conversations ----------

function renderConversationList() {
  const conversations = loadConversations();
  const numbers = Object.keys(conversations).sort((a, b) => {
    const lastA = conversations[a][conversations[a].length - 1]?.sentAt || 0;
    const lastB = conversations[b][conversations[b].length - 1]?.sentAt || 0;
    return lastB - lastA;
  });

  conversationList.innerHTML = "";
  noConversations.hidden = numbers.length > 0;

  numbers.forEach((number) => {
    const messages = conversations[number];
    const last = messages[messages.length - 1];

    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "conversation-item" + (number === activeNumber ? " active" : "");

    const numberSpan = document.createElement("span");
    numberSpan.className = "conversation-number";
    numberSpan.textContent = formatNumber(number);

    const previewSpan = document.createElement("span");
    previewSpan.className = "conversation-preview";
    previewSpan.textContent = last ? last.text : "";

    btn.append(numberSpan, previewSpan);
    btn.addEventListener("click", () => openThread(number));
    li.appendChild(btn);
    conversationList.appendChild(li);
  });
}

function openThread(number) {
  const conversations = loadConversations();
  const messages = conversations[number];
  if (!messages) return;

  activeNumber = number;
  threadPanel.hidden = false;
  threadTitle.textContent = formatNumber(number);

  const lastText = messages[messages.length - 1]?.text || "";
  smsLink.href = `sms:${number}?&body=${encodeURIComponent(lastText)}`;

  threadMessages.innerHTML = "";
  messages.forEach((msg) => {
    const card = document.createElement("div");
    card.className = `note-card pad-${msg.pad} ${FONT_CLASSES[msg.font] || "font-caveat"}`;

    const text = document.createElement("p");
    text.className = "note-text";
    text.textContent = msg.text;

    const meta = document.createElement("span");
    meta.className = "note-meta";
    meta.textContent = new Date(msg.sentAt).toLocaleString([], {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });

    card.append(text, meta);
    threadMessages.appendChild(card);
  });
  threadMessages.scrollTop = threadMessages.scrollHeight;

  renderConversationList();
}

deleteThreadBtn.addEventListener("click", () => {
  if (!activeNumber) return;
  if (!confirm(`Delete the conversation with ${formatNumber(activeNumber)}?`)) return;

  const conversations = loadConversations();
  delete conversations[activeNumber];
  saveConversations(conversations);
  activeNumber = null;
  threadPanel.hidden = true;
  renderConversationList();
});

newNoteBtn.addEventListener("click", () => {
  activeNumber = null;
  threadPanel.hidden = true;
  phoneInput.value = "";
  messageInput.value = "";
  charCount.textContent = "0 / 500";
  renderConversationList();
  messageInput.focus();
});

// ---------- Init ----------

renderConversationList();
