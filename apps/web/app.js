const state = { sessionId: localStorage.getItem("neo-session-id") || `web-${crypto.randomUUID()}`, key: "", busy: false, deliveredIds: new Set(), remindersLoaded: false, voiceReply: false, recognition: null, voiceStream: null };
localStorage.setItem("neo-session-id", state.sessionId);
const $ = (id) => document.getElementById(id);
const conversation = $("conversation");

function headers() { return { "Content-Type": "application/json", ...(state.key ? { "X-Neo-Owner-Key": state.key } : {}) }; }
async function api(path, options = {}) {
  const response = await fetch(`/v1${path}`, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  if (!response.ok) throw new Error(response.status === 401 ? "Owner access key required." : `Gateway error (${response.status})`);
  return response.json();
}
function escapeHtml(text) { const div = document.createElement("div"); div.textContent = text; return div.innerHTML; }
function renderMarkdown(text) {
  if (!window.marked || !window.DOMPurify) return escapeHtml(text).replaceAll("\n", "<br>");
  return DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));
}
function speakerName() { return "Neo"; }
function updateGreeting() {
  const hour = new Date().getHours();
  const greeting = hour < 5 ? "Good night." : hour < 12 ? "Good morning." : hour < 18 ? "Good afternoon." : "Good evening.";
  $("workspace-greeting").textContent = greeting;
  $("message-input").placeholder = "Message Neo";
}
function announceReminder(item) { const text = `Reminder: **${item.title}**`; addMessage("neo", text); if (window.Notification && Notification.permission === "granted") new Notification("Neo reminder", { body: item.title }); }
function showActivity(text) { const node = document.createElement("article"); node.className = "activity"; node.innerHTML = `<span class="activity-icon"><i data-lucide="sparkles"></i></span><span class="activity-text">${escapeHtml(text)}</span><span class="activity-dots"><b></b><b></b><b></b></span>`; conversation.append(node); conversation.scrollTop = conversation.scrollHeight; lucide.createIcons(); return node; }
function addMessage(role, text) {
  const node = document.createElement("article"); node.className = `message ${role}-message`;
  const avatar = role === "neo" ? speakerName().slice(0, 1) : "You";
  node.innerHTML = `<div class="avatar">${avatar}</div><div class="message-content"></div>`;
  const content = node.querySelector(".message-content"); if (role === "neo") content.innerHTML = renderMarkdown(text); else content.textContent = text; conversation.append(node); conversation.scrollTop = conversation.scrollHeight; return content;
}
function speak(text) { if (!state.voiceReply || !window.speechSynthesis) return; window.speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(text.replace(/[`*_>#]/g, " ").replace(/\s+/g, " ").trim()); utterance.rate = 1.08; utterance.pitch = 1; window.speechSynthesis.speak(utterance); }
async function typeReply(text) { const target = addMessage("neo", ""); for (let i = 0; i < text.length; i += 2) { target.textContent += text.slice(i, i + 2); conversation.scrollTop = conversation.scrollHeight; await new Promise((resolve) => setTimeout(resolve, 9)); } target.innerHTML = renderMarkdown(text); lucide.createIcons(); speak(text); }
async function send(text) {
  if (state.busy || !text.trim()) return;
  state.busy = true; $("send-button").disabled = true; addMessage("user", text); const researching = /https?:\/\/|\b(search|look up|research|find out|latest)\b/i.test(text); const activity = showActivity(researching ? "Searching and gathering sources" : "Thinking through that");
  try { const data = await api("/chat", { method: "POST", body: JSON.stringify({ session_id: state.sessionId, text }) }); activity.remove(); await typeReply(data.response); await Promise.all([renderSessions(), recall()]); }
  catch (error) { activity.remove(); addMessage("neo", error.message); }
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
    $("memory-list").innerHTML = personalFacts.length ? personalFacts.map((item) => `<div class="memory-item">${escapeHtml(item)}</div>`).join("") : '<p class="empty">No saved personal facts.</p>';
    $("preferences-list").innerHTML = preferences.memories.length ? preferences.memories.map((item) => `<div class="memory-item">${escapeHtml(item)}</div>`).join("") : '<p class="empty">No saved preferences.</p>';
    $("preference-count").textContent = preferences.memories.length;
    const actions = $("actions-list"); const active = reminders.reminders.filter((item) => item.status === "scheduled");
    const delivered = reminders.reminders.filter((item) => item.status === "delivered");
    if (state.remindersLoaded) delivered.filter((item) => !state.deliveredIds.has(item.id)).forEach(announceReminder);
    delivered.forEach((item) => state.deliveredIds.add(item.id)); state.remindersLoaded = true;
    const scheduled = active.map((item) => `<div class="memory-item"><strong>${escapeHtml(item.title)}</strong><br><small>${new Date(item.due_at).toLocaleString()}</small></div>`);
    const pending = approvals.approvals.map((item) => `<div class="memory-item approval-item"><strong>${escapeHtml(item.tool_name)}</strong><br><small>Approval needed</small><div class="approval-buttons"><button data-approval="${item.id}" data-approved="true">Approve</button><button data-approval="${item.id}" data-approved="false">Decline</button></div></div>`);
    actions.innerHTML = [...pending, ...scheduled].length ? [...pending, ...scheduled].join("") : '<p class="empty">No approval requests or scheduled reminders.</p>';
    $("action-count").textContent = pending.length + scheduled.length;
    actions.querySelectorAll("[data-approval]").forEach((button) => button.addEventListener("click", () => resolveApproval(button.dataset.approval, button.dataset.approved === "true")));
  } catch { /* Gateway status communicates errors. */ }
}
async function resolveApproval(approvalId, approved) {
  try { const result = await api(`/approvals/${approvalId}`, { method: "POST", body: JSON.stringify({ approved }) }); addMessage("neo", result.ok ? (approved ? (result.message || "Approved and completed.") : "Action declined.") : (result.error || "The action could not be completed.")); await recall(); } catch (error) { addMessage("neo", error.message); }
}
async function loadSession(sessionId = state.sessionId) {
  state.sessionId = sessionId; localStorage.setItem("neo-session-id", sessionId); closeMobilePanels();
  try { const data = await api(`/sessions/${state.sessionId}`); if (!data.messages.length) { renderSessions(); return; } conversation.innerHTML = ""; data.messages.filter((message) => (message.role === "user" || (message.role === "assistant" && message.content?.trim())) && !message.content?.startsWith("[Owner requested") && !message.content?.startsWith("[Owner attempted")).forEach((message) => addMessage(message.role === "assistant" ? "neo" : "user", message.content)); renderSessions(); } catch { /* A new local session is expected on first load. */ }
}
async function renderSessions() {
  try { const data = await api("/sessions"); const list = $("conversation-list"); list.innerHTML = data.sessions.length ? data.sessions.map((session) => `<div class="conversation-item ${session.id === state.sessionId ? "active" : ""}"><button class="conversation-open" data-session="${session.id}" title="${escapeHtml(session.title)}">${escapeHtml(session.title)}</button><button class="conversation-delete" data-delete-session="${session.id}" aria-label="Delete ${escapeHtml(session.title)}"><i data-lucide="trash-2"></i></button></div>`).join("") : '<p class="sidebar-empty">No saved conversations yet.</p>'; list.querySelectorAll("[data-session]").forEach((button) => button.addEventListener("click", () => loadSession(button.dataset.session))); list.querySelectorAll("[data-delete-session]").forEach((button) => button.addEventListener("click", () => deleteSession(button.dataset.deleteSession))); lucide.createIcons(); } catch { /* Connection panel shows status. */ }
}
async function deleteSession(sessionId) {
  if (!confirm("Delete this conversation? This cannot be undone.")) return;
  try { await api(`/sessions/${sessionId}`, { method: "DELETE" }); if (state.sessionId === sessionId) { state.sessionId = `web-${crypto.randomUUID()}`; localStorage.setItem("neo-session-id", state.sessionId); conversation.innerHTML = ""; addMessage("neo", "New conversation started. What would you like to do?"); } await renderSessions(); } catch (error) { addMessage("neo", error.message); }
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
