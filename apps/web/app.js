const state = { sessionId: localStorage.getItem("neo-session-id") || `web-${crypto.randomUUID()}`, key: "", busy: false, deliveredIds: new Set(), remindersLoaded: false, voiceReply: false, recognition: null, voiceStream: null, expandedPanels: new Set(), previewCache: new Map() };
localStorage.setItem("neo-session-id", state.sessionId);
const $ = (id) => document.getElementById(id);
const conversation = $("conversation");

function headers() { return { "Content-Type": "application/json", ...(state.key ? { "X-Neo-Owner-Key": state.key } : {}) }; }
async function api(path, options = {}) {
  const response = await fetch(`/v1${path}`, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(response.status === 401 ? "Owner access key required." : (payload.detail || `Gateway error (${response.status})`)); error.diagnostic = payload.diagnostic || { source: "http", status: response.status, message: error.message }; throw error; }
  return payload;
}
function escapeHtml(text) { const div = document.createElement("div"); div.textContent = text; return div.innerHTML; }
function compactPanel(items, empty, panelName, limit = 4) {
  if (!items.length) return '<p class="empty">' + empty + "</p>";
  const expanded = state.expandedPanels.has(panelName);
  const shown = expanded ? items : items.slice(0, limit);
  const more = items.length - limit;
  const toggle = more > 0 ? '<button type="button" class="panel-toggle" data-panel-toggle="' + panelName + '">' + (expanded ? "Show less" : "Show " + more + " more") + "</button>" : "";
  return shown.join("") + toggle;
}
function bindPanelToggles() {
  document.querySelectorAll("[data-panel-toggle]").forEach((button) => button.addEventListener("click", () => {
    const name = button.dataset.panelToggle;
    if (state.expandedPanels.has(name)) state.expandedPanels.delete(name);
    else state.expandedPanels.add(name);
    recall();
  }));
}
function renderMarkdown(text) {
  if (!window.marked || !window.DOMPurify) return escapeHtml(text).replaceAll("\n", "<br>");
  return DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));
}
function mediaKind(value) {
  try {
    const path = new URL(value).pathname.toLowerCase();
    if (/\.(jpe?g|png|webp|gif|avif)(?:$|\/)/.test(path)) return "image";
    if (/\.(mp4|webm|ogv|ogg|mov)(?:$|\/)/.test(path)) return "video";
    if (/\.(mp3|wav|m4a|aac|oga)(?:$|\/)/.test(path)) return "audio";
  } catch { /* Not a URL we can embed. */ }
  return null;
}
function externalLink(url, label) {
  const link = document.createElement("a");
  link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = label; return link;
}
function attachmentFallback(card, url, label) {
  card.replaceChildren(externalLink(url, "Open " + label));
  card.classList.add("attachment-fallback");
}
function makeMediaAttachment(url, kind, label) {
  const card = document.createElement("figure"); card.className = "attachment-card attachment-" + kind;
  if (kind === "image") {
    const image = document.createElement("img"); image.src = url; image.alt = label; image.loading = "lazy"; image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => attachmentFallback(card, url, "image"));
    card.append(image);
  } else if (kind === "video") {
    const video = document.createElement("video"); video.controls = true; video.preload = "metadata"; video.playsInline = true; video.src = url;
    video.addEventListener("error", () => attachmentFallback(card, url, "video"));
    card.append(video);
  } else {
    const audio = document.createElement("audio"); audio.controls = true; audio.preload = "metadata"; audio.src = url;
    audio.addEventListener("error", () => attachmentFallback(card, url, "audio"));
    card.append(audio);
  }
  const caption = document.createElement("figcaption"); caption.append(externalLink(url, label)); card.append(caption);
  return card;
}
function makeSitePreview(data) {
  const card = document.createElement("a"); card.className = "site-preview"; card.href = data.url; card.target = "_blank"; card.rel = "noopener noreferrer";
  if (data.image_url) {
    const image = document.createElement("img"); image.className = "site-preview-image"; image.src = data.image_url; image.alt = ""; image.loading = "lazy"; image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => image.remove()); card.append(image);
  }
  const body = document.createElement("span"); body.className = "site-preview-body";
  const host = document.createElement("small"); host.textContent = data.host;
  const title = document.createElement("strong"); title.textContent = data.title || data.host;
  body.append(host, title);
  if (data.description) { const description = document.createElement("span"); description.textContent = data.description; body.append(description); }
  card.append(body); return card;
}
async function hydrateEmbeds(content) {
  if (!content || content.dataset.embedsHydrated === "true") return;
  content.dataset.embedsHydrated = "true";
  const links = [...content.querySelectorAll("a[href]")];
  const previewed = new Set(); let previewCount = 0;
  for (const link of links) {
    const url = link.href; const kind = mediaKind(url);
    if (kind) {
      const media = makeMediaAttachment(url, kind, link.textContent.trim() || kind);
      link.after(media); link.classList.add("attachment-source"); continue;
    }
    if (!/^https?:/i.test(url) || previewed.has(url) || previewCount >= 3) continue;
    previewed.add(url); previewCount += 1;
    try {
      let data = state.previewCache.get(url);
      if (!data) { data = await api("/previews?url=" + encodeURIComponent(url)); state.previewCache.set(url, data); }
      if (!data.ok) continue;
      const preview = makeSitePreview(data); link.after(preview);
      if (data.video_url && mediaKind(data.video_url) === "video") preview.after(makeMediaAttachment(data.video_url, "video", "Preview video"));
    } catch { /* A link remains usable when its preview cannot load. */ }
  }
}
function speakerName() { return "Neo"; }
function updateGreeting() {
  const hour = new Date().getHours();
  const greeting = hour < 5 ? "Good night." : hour < 12 ? "Good morning." : hour < 18 ? "Good afternoon." : "Good evening.";
  $("workspace-greeting").textContent = greeting;
  $("message-input").placeholder = "Message Neo";
}
async function announceReminder(item) { const payload = item.payload || {}; const labels = { notification: "Reminder", task: "Task", content: "Scheduled content", link: "Scheduled link" }; const label = labels[item.kind] || "Scheduled item"; const parts = [`${label}: **${item.title}**`]; if (payload.body) parts.push(payload.body); if (payload.url) parts.push(`[Open link](${payload.url})`); addMessage("neo", parts.join("\n\n")); if (window.Notification && Notification.permission === "granted") new Notification(`Neo · ${label}`, { body: payload.body || item.title }); try { await api(`/reminders/${item.id}/acknowledge`, { method: "POST" }); } catch { /* It remains ready and will be retried on the next refresh. */ } }
function activityStages(text) {
  if (/https?:\/\//i.test(text)) return ["Opening page", "Reading the page", "Gathering useful context"];
  if (/\b(search|look up|research|find out|latest)\b/i.test(text)) return ["Searching for info", "Gathering sources", "Putting it together"];
  return ["Thinking through that", "Working on it", "Putting it together"];
}
function showActivity(stages) {
  const node = document.createElement("article"); node.className = "activity"; node.setAttribute("aria-live", "polite");
  node.innerHTML = `<span class="activity-icon"><i data-lucide="sparkles"></i></span><span class="activity-copy"><span class="activity-text"></span><span class="activity-elapsed"></span></span><span class="activity-shimmer" aria-hidden="true"></span>`;
  const text = node.querySelector(".activity-text"); const elapsed = node.querySelector(".activity-elapsed"); const started = Date.now(); let index = 0;
  const update = () => { const seconds = Math.floor((Date.now() - started) / 1000); text.textContent = stages[index]; elapsed.textContent = seconds ? ` · ${seconds}s` : ""; };
  update(); const timer = setInterval(() => { index = Math.min(index + 1, stages.length - 1); update(); }, 1450);
  node.stopActivity = () => clearInterval(timer);
  conversation.append(node); conversation.scrollTop = conversation.scrollHeight; lucide.createIcons(); return node;
}
function attachDiagnostic(container, diagnostic) {
  if (!diagnostic) return;
  const details = document.createElement("details"); details.className = "diagnostic";
  const summary = document.createElement("summary"); summary.textContent = "Technical details";
  const copy = document.createElement("button"); copy.type = "button"; copy.className = "diagnostic-copy"; copy.textContent = "Copy error";
  const pre = document.createElement("pre"); const output = typeof diagnostic === "string" ? diagnostic : JSON.stringify(diagnostic, null, 2); pre.textContent = output;
  copy.addEventListener("click", async (event) => { event.preventDefault(); event.stopPropagation(); try { await navigator.clipboard.writeText(output); copy.textContent = "Copied"; } catch { copy.textContent = "Copy failed"; } setTimeout(() => { copy.textContent = "Copy error"; }, 1400); });
  const toolbar = document.createElement("div"); toolbar.className = "diagnostic-toolbar"; toolbar.append(copy); details.append(summary, toolbar, pre); container.append(details);
}
function addMessage(role, text, diagnostic = null) {
  const node = document.createElement("article"); node.className = `message ${role}-message`;
  const avatar = role === "neo" ? speakerName().slice(0, 1) : "You";
  node.innerHTML = `<div class="avatar">${avatar}</div><div class="message-content"></div>`;
  const content = node.querySelector(".message-content"); if (role === "neo") { content.innerHTML = renderMarkdown(text); if (text.trim()) void hydrateEmbeds(content); } else content.textContent = text; attachDiagnostic(content, diagnostic); conversation.append(node); conversation.scrollTop = conversation.scrollHeight; return content;
}
function speak(text) { if (!state.voiceReply || !window.speechSynthesis) return; window.speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(text.replace(/[`*_>#]/g, " ").replace(/\s+/g, " ").trim()); utterance.rate = 1.08; utterance.pitch = 1; window.speechSynthesis.speak(utterance); }
async function typeReply(text, diagnostic = null) { const target = addMessage("neo", ""); for (let i = 0; i < text.length; i += 12) { target.textContent += text.slice(i, i + 12); conversation.scrollTop = conversation.scrollHeight; await new Promise((resolve) => setTimeout(resolve, 5)); } target.innerHTML = renderMarkdown(text); attachDiagnostic(target, diagnostic); void hydrateEmbeds(target); lucide.createIcons(); speak(text); }
async function send(text) {
  if (state.busy || !text.trim()) return;
  state.busy = true; $("send-button").disabled = true; addMessage("user", text); const activity = showActivity(activityStages(text));
  try { const data = await api("/chat", { method: "POST", body: JSON.stringify({ session_id: state.sessionId, text }) }); activity.stopActivity(); activity.remove(); await typeReply(data.response, data.diagnostic); await Promise.all([renderSessions(), recall()]); }
  catch (error) { activity.stopActivity(); activity.remove(); addMessage("neo", error.message, error.diagnostic); }
  finally { state.busy = false; $("send-button").disabled = false; $("message-input").focus(); }
}
async function refreshStatus() {
  try { const data = await api("/status"); $("connection-dot").classList.add("online"); $("connection-label").textContent = "Gateway connected"; $("connection-detail").textContent = "Local workspace"; $("model-name").textContent = data.model || "Provider ready"; $("model-detail").textContent = `${data.provider} · ${Array.isArray(data.tools) ? data.tools.length : 0} tools enabled`; document.querySelector(".pulse").classList.add("online"); }
  catch (error) { $("connection-label").textContent = "Gateway offline"; $("connection-detail").textContent = error.message; $("model-name").textContent = "Unavailable"; $("model-detail").textContent = "Start the Neo gateway"; }
}
async function recall() {
  try {
    const [identity, birthdays, preferences, reminders, approvals] = await Promise.all([api("/memories?category=identity"), api("/memories?category=birthday"), api("/memories?category=preference"), api("/reminders"), api("/approvals")]);
    const personalFacts = [...identity.memories, ...birthdays.memories];
    $("memory-list").innerHTML = compactPanel(personalFacts.map((item) => `<div class="memory-item">${escapeHtml(item)}</div>`), "No saved personal facts.", "memory");
    $("preferences-list").innerHTML = compactPanel(preferences.memories.map((item) => `<div class="memory-item">${escapeHtml(item)}</div>`), "No saved preferences.", "preferences");
    $("preference-count").textContent = preferences.memories.length;
    const actions = $("actions-list"); const active = reminders.reminders.filter((item) => item.status === "scheduled");
    const ready = reminders.reminders.filter((item) => item.status === "ready");
    ready.filter((item) => !state.deliveredIds.has(item.id)).forEach((item) => { state.deliveredIds.add(item.id); announceReminder(item); });
    state.remindersLoaded = true;
    const scheduled = active.map((item) => `<div class="memory-item"><strong>${escapeHtml(item.title)}</strong><br><small>${escapeHtml(item.kind || "notification")} · ${new Date(item.due_at).toLocaleString()}</small></div>`);
    const failed = reminders.reminders.filter((item) => item.status === "failed").map((item) => `<div class="memory-item"><strong>${escapeHtml(item.title)}</strong><br><small>Failed · ${escapeHtml(item.last_error || "Unknown delivery error")}</small></div>`);
    const pending = approvals.approvals.map((item) => `<div class="memory-item approval-item"><strong>${escapeHtml(item.tool_name)}</strong><br><small>Approval needed</small><div class="approval-buttons"><button data-approval="${item.id}" data-approved="true">Approve</button><button data-approval="${item.id}" data-approved="false">Decline</button></div></div>`);
    const actionItems = [...pending, ...scheduled, ...failed];
    actions.innerHTML = compactPanel(actionItems, "No approval requests or scheduled jobs.", "actions");
    $("action-count").textContent = actionItems.length;
    actions.querySelectorAll("[data-approval]").forEach((button) => button.addEventListener("click", () => resolveApproval(button.dataset.approval, button.dataset.approved === "true")));
    bindPanelToggles();
  } catch { /* Gateway status communicates errors. */ }
}
async function resolveApproval(approvalId, approved) {
  try { const result = await api(`/approvals/${approvalId}`, { method: "POST", body: JSON.stringify({ approved }) }); addMessage("neo", result.ok ? (approved ? (result.message || "Approved and completed.") : "Action declined.") : (result.error || "The action could not be completed."), result.diagnostic); await recall(); } catch (error) { addMessage("neo", error.message, error.diagnostic); }
}
async function loadSession(sessionId = state.sessionId) {
  state.sessionId = sessionId; localStorage.setItem("neo-session-id", sessionId); closeMobilePanels();
  try { const data = await api(`/sessions/${state.sessionId}`); if (!data.messages.length) { renderSessions(); return; } conversation.innerHTML = ""; data.messages.filter((message) => (message.role === "user" || (message.role === "assistant" && message.content?.trim())) && !message.content?.startsWith("[Owner requested") && !message.content?.startsWith("[Owner attempted")).forEach((message) => addMessage(message.role === "assistant" ? "neo" : "user", message.content, message.diagnostic)); renderSessions(); } catch { /* A new local session is expected on first load. */ }
}
async function renderSessions() {
  try { const data = await api("/sessions"); const list = $("conversation-list"); list.innerHTML = data.sessions.length ? data.sessions.map((session) => `<div class="conversation-item ${session.id === state.sessionId ? "active" : ""}"><button class="conversation-open" data-session="${session.id}" title="${escapeHtml(session.title)}">${escapeHtml(session.title)}</button><button class="conversation-delete" data-delete-session="${session.id}" aria-label="Delete ${escapeHtml(session.title)}"><i data-lucide="trash-2"></i></button></div>`).join("") : '<p class="sidebar-empty">No saved conversations yet.</p>'; list.querySelectorAll("[data-session]").forEach((button) => button.addEventListener("click", () => loadSession(button.dataset.session))); list.querySelectorAll("[data-delete-session]").forEach((button) => button.addEventListener("click", () => deleteSession(button.dataset.deleteSession))); lucide.createIcons(); } catch { /* Connection panel shows status. */ }
}
async function deleteSession(sessionId) {
  if (!confirm("Delete this conversation? This cannot be undone.")) return;
  try { await api(`/sessions/${sessionId}`, { method: "DELETE" }); if (state.sessionId === sessionId) { state.sessionId = `web-${crypto.randomUUID()}`; localStorage.setItem("neo-session-id", state.sessionId); conversation.innerHTML = ""; addMessage("neo", "New conversation started. What would you like to do?"); } await renderSessions(); } catch (error) { addMessage("neo", error.message); }
}

function closeConversationMenu() {
  document.querySelector(".conversation-menu-popover")?.remove();
}

function showConversationMenu(session, anchor) {
  closeConversationMenu();
  const menu = document.createElement("div");
  menu.className = "conversation-menu-popover";
  menu.setAttribute("role", "menu");
  const rename = document.createElement("button");
  rename.type = "button";
  rename.textContent = "Rename";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "danger";
  remove.textContent = "Delete";
  rename.addEventListener("click", () => renameSession(session.id, session.title));
  remove.addEventListener("click", () => deleteSession(session.id));
  menu.append(rename, remove);
  document.body.append(menu);
  const bounds = anchor.getBoundingClientRect();
  menu.style.top = Math.min(bounds.bottom + 6, window.innerHeight - 90) + "px";
  menu.style.left = Math.max(8, bounds.right - menu.offsetWidth) + "px";
  setTimeout(() => document.addEventListener("click", closeConversationMenu, { once: true }), 0);
}

async function renameSession(sessionId, currentTitle) {
  closeConversationMenu();
  const title = window.prompt("Rename conversation", currentTitle || "");
  if (title === null) return;
  const clean = title.trim();
  if (!clean) return;
  try {
    await api("/sessions/" + encodeURIComponent(sessionId), {
      method: "PATCH",
      body: JSON.stringify({ title: clean }),
    });
    await renderSessions();
  } catch (error) {
    addMessage("neo", error.message, error.diagnostic);
  }
}

async function renderSessions() {
  try {
    const data = await api("/sessions");
    const list = $("conversation-list");
    list.replaceChildren();
    if (!data.sessions.length) {
      const empty = document.createElement("p");
      empty.className = "sidebar-empty";
      empty.textContent = "No saved conversations yet.";
      list.append(empty);
      return;
    }
    data.sessions.forEach((session) => {
      const row = document.createElement("div");
      row.className = "conversation-item" + (session.id === state.sessionId ? " active" : "");
      const open = document.createElement("button");
      open.type = "button";
      open.className = "conversation-open";
      open.textContent = session.title || "New conversation";
      open.title = "Open " + open.textContent;
      open.addEventListener("click", () => loadSession(session.id));
      open.addEventListener("dblclick", (event) => {
        event.preventDefault();
        renameSession(session.id, session.title);
      });
      row.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        showConversationMenu(session, row);
      });
      const menu = document.createElement("button");
      menu.type = "button";
      menu.className = "conversation-menu";
      menu.setAttribute("aria-label", "Conversation options");
      menu.title = "Conversation options";
      menu.innerHTML = '<i data-lucide="more-horizontal"></i>';
      menu.addEventListener("click", (event) => {
        event.stopPropagation();
        showConversationMenu(session, menu);
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "conversation-delete";
      remove.setAttribute("aria-label", "Delete " + open.textContent);
      remove.innerHTML = '<i data-lucide="trash-2"></i>';
      remove.addEventListener("click", () => deleteSession(session.id));
      row.append(open, menu, remove);
      list.append(row);
    });
    lucide.createIcons();
  } catch { /* Connection panel shows status. */ }
}
function closeMobilePanels() { document.body.classList.remove("mobile-sidebar-open", "mobile-context-open"); }
function toggleMobilePanel(kind) { const className = kind === "sidebar" ? "mobile-sidebar-open" : "mobile-context-open"; const opposite = kind === "sidebar" ? "mobile-context-open" : "mobile-sidebar-open"; document.body.classList.remove(opposite); document.body.classList.toggle(className); }
function submitInput() { const input = $("message-input"); const text = input.value; input.value = ""; input.style.height = "auto"; send(text); }

$("chat-form").addEventListener("submit", (event) => { event.preventDefault(); submitInput(); });
$("message-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submitInput(); } });
$("message-input").addEventListener("input", (event) => { event.target.style.height = "auto"; event.target.style.height = `${Math.min(event.target.scrollHeight, 120)}px`; });
function setVoiceState(listening, hint) { $("voice-button").classList.toggle("listening", listening); $("voice-button").setAttribute("aria-label", listening ? "Stop voice input" : "Start voice input"); $("voice-hint").textContent = hint; }
function stopVoiceStream() { state.voiceStream?.getTracks().forEach((track) => track.stop()); state.voiceStream = null; }
function initVoice() { const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition; if (!Recognition || !navigator.mediaDevices?.getUserMedia) { $("voice-button").disabled = true; $("voice-hint").textContent = "Voice input needs Chrome or Edge with microphone support."; return; } const recognition = new Recognition(); recognition.lang = navigator.language || "en-US"; recognition.continuous = false; recognition.interimResults = true; recognition.onresult = (event) => { let text = ""; for (let index = event.resultIndex; index < event.results.length; index += 1) text += event.results[index][0].transcript; $("message-input").value = text.trim(); }; recognition.onspeechstart = () => setVoiceState(true, "Listening… speak naturally"); recognition.onnomatch = () => setVoiceState(false, "I did not catch that — try again."); recognition.onend = () => { stopVoiceStream(); setVoiceState(false, "Tap the mic to talk · Neo will answer aloud"); const text = $("message-input").value.trim(); if (text && !state.busy) submitInput(); }; recognition.onerror = (event) => { stopVoiceStream(); const message = event.error === "not-allowed" || event.error === "service-not-allowed" ? "Microphone blocked — allow it in the browser address bar." : `Voice error: ${event.error}. Tap the mic to retry.`; setVoiceState(false, message); }; state.recognition = recognition; $("voice-button").addEventListener("click", async () => { if ($("voice-button").classList.contains("listening")) { recognition.stop(); return; } try { setVoiceState(true, "Requesting microphone permission…"); state.voiceStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }); state.voiceReply = true; recognition.start(); setVoiceState(true, "Listening… tap the mic again to stop"); } catch (error) { stopVoiceStream(); setVoiceState(false, "Microphone permission is required — allow it and try again."); } }); setVoiceState(false, "Tap the mic to talk · Neo will answer aloud"); }
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => send(button.dataset.prompt)));
initVoice();
$("new-chat").addEventListener("click", () => { state.sessionId = `web-${crypto.randomUUID()}`; localStorage.setItem("neo-session-id", state.sessionId); conversation.innerHTML = ""; addMessage("neo", "New conversation started. What would you like to do?"); renderSessions(); });
$("clear-chat").addEventListener("click", () => { conversation.innerHTML = ""; addMessage("neo", "Conversation cleared."); });
$("settings-button").addEventListener("click", () => $("settings-dialog").showModal());
$("sidebar-toggle").addEventListener("click", () => toggleMobilePanel("sidebar"));
$("context-toggle").addEventListener("click", () => toggleMobilePanel("context"));
$("mobile-backdrop").addEventListener("click", closeMobilePanels);
$("save-settings").addEventListener("click", () => { state.key = $("owner-key").value; setTimeout(() => { refreshStatus(); recall(); }, 0); });
$("add-memory").addEventListener("click", () => $("memory-dialog").showModal());
$("save-memory").addEventListener("click", async () => { const input = $("memory-input"); if (input.value.trim()) { try { await api("/memories", { method: "POST", body: JSON.stringify({ content: input.value, category: "preference" }) }); input.value = ""; recall(); } catch (error) { alert(error.message); } } });
$("refresh-status").addEventListener("click", refreshStatus);
lucide.createIcons(); updateGreeting(); refreshStatus(); recall(); loadSession(); renderSessions(); setInterval(recall, 10000); if (window.Notification && Notification.permission === "default") Notification.requestPermission();
