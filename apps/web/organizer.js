(() => {
  const dialog = document.getElementById("organizer-dialog");
  const tree = document.getElementById("organizer-groups");
  const view = document.getElementById("organizer-view");
  const groupForm = document.getElementById("organizer-new-group");
  let groups = [];
  let selected = "";

  const request = async (path, options = {}) => {
    const response = await fetch(`/v1${path}`, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    if (!response.ok) throw new Error(`Organizer error (${response.status})`);
    return response.json();
  };
  const esc = (value = "") => { const element = document.createElement("span"); element.textContent = value; return element.innerHTML; };
  const icon = (name) => `<i data-lucide="${name}"></i>`;
  const icons = () => { try { window.lucide?.createIcons(); } catch {} };
  const when = (value) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
  const markdown = (value) => {
    const raw = window.marked?.parse(value || "") || esc(value);
    return window.DOMPurify?.sanitize(raw) || raw;
  };

  const trashButton = document.createElement("button");
  trashButton.type = "button";
  trashButton.className = "organizer-trash-button";
  trashButton.innerHTML = `${icon("trash-2")} Trash`;
  trashButton.style.cssText = "display:flex;align-items:center;gap:8px;width:calc(100% - 16px);margin:12px 8px 0;padding:8px 10px;border:0;border-top:1px solid var(--line);background:transparent;color:var(--muted);font:12px Manrope,Arial,sans-serif;cursor:pointer;text-align:left";
  tree.after(trashButton);

  function groupSection(title, items, symbol) {
    if (!items.length) return "";
    return `<section class="organizer-tree-section"><p>${esc(title)}</p>${items.map((group) => `<button type="button" class="organizer-group ${group.id === selected ? "active" : ""}" data-group="${group.id}">${icon(symbol)}<span>${esc(group.name)}</span><small>${group.count}</small></button>`).join("")}</section>`;
  }

  function renderTree() {
    const tasks = groups.filter((group) => group.kind === "task");
    const shopping = groups.filter((group) => group.kind === "shopping");
    const notes = groups.filter((group) => group.kind !== "task" && group.kind !== "shopping");
    tree.innerHTML = groups.length
      ? `${groupSection("To-dos", tasks, "check-square")}${groupSection("Shopping", shopping, "shopping-bag")}${groupSection("Notes & saved", notes, "file-text")}`
      : '<p class="sidebar-empty">No collections yet.</p>';
    tree.querySelectorAll("[data-group]").forEach((button) => button.addEventListener("click", () => select(button.dataset.group)));
    icons();
  }

  function emptyView() {
    view.innerHTML = `<div class="organizer-empty">${icon("bookmark-plus")}<h3>Keep useful things together.</h3><p>Create a collection for notes, links, shopping, or tasks.</p><button type="button" id="empty-new-group">Create collection</button></div>`;
    view.querySelector("#empty-new-group").addEventListener("click", openGroupForm);
    icons();
  }

  function itemCard(item) {
    const check = item.kind === "task"
      ? `<button class="task-toggle" data-check-item="${item.id}" data-next-check="${!item.checked}" aria-label="${item.checked ? "Mark incomplete" : "Mark complete"}">${icon(item.checked ? "check-circle-2" : "circle")}</button>`
      : icon(item.kind === "bookmark" ? "link" : "file-text");
    const tags = Array.isArray(item.metadata?.tags) ? item.metadata.tags : [];
    return `<article class="organizer-saved-item ${item.checked ? "is-checked" : ""}">${check}<div class="saved-item-body"><div class="item-title-row"><strong>${esc(item.title)}</strong><span class="item-kind">${esc(item.kind)}</span><button type="button" class="item-delete" data-delete-item="${item.id}" aria-label="Move ${esc(item.title)} to Trash" title="Move to Trash">${icon("trash-2")}</button></div>${item.summary ? `<p class="item-summary">${esc(item.summary)}</p>` : ""}${tags.length ? `<div class="item-tags">${tags.map((tag) => `<span>#${esc(tag)}</span>`).join("")}</div>` : ""}${item.content ? `<details class="item-details"><summary>Open full note</summary><div class="organizer-markdown">${markdown(item.content)}</div></details>` : ""}${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">Open link</a>` : ""}<small class="item-meta">Saved ${when(item.created_at)}${item.updated_at !== item.created_at ? ` · Updated ${when(item.updated_at)}` : ""}</small></div></article>`;
  }

  function addForm(group) {
    return `<section class="organizer-add"><button type="button" class="save-button" id="show-add-form">${icon("plus")} Add item</button><form id="organizer-item-form" hidden><h4>Add to ${esc(group.name)}</h4><label>Type<select id="organizer-item-kind"><option value="note">Note</option><option value="task">Task with checkbox</option><option value="bookmark">Bookmark</option></select></label><label>Title<input id="organizer-title-input" required maxlength="160" placeholder="What do you want to save?" /></label><label>Details <span>Markdown supported: bullets, headings, checkboxes</span><textarea id="organizer-content" rows="5" placeholder="- First point\n- Second point"></textarea></label><label>Link <span>optional</span><input id="organizer-url" type="url" placeholder="https://example.com" /></label><div><button type="submit" class="save-button">Save item</button><button type="button" class="text-button" id="cancel-add-item">Cancel</button></div></form></section>`;
  }

  function renderView(group, items) {
    view.innerHTML = `<header class="collection-header"><div><p class="eyebrow">${esc(group.kind || "collection")}</p><h3>${esc(group.name)}</h3><p>${items.length} saved item${items.length === 1 ? "" : "s"} · created ${when(group.created_at)}</p></div><button type="button" id="delete-organizer-group" class="danger-button">${icon("archive")} Archive collection</button></header><div class="organizer-items">${items.length ? items.map(itemCard).join("") : '<p class="organizer-empty-items">Nothing saved here yet.</p>'}</div>${addForm(group)}`;
    view.querySelector("#show-add-form").addEventListener("click", () => { view.querySelector("#show-add-form").hidden = true; const form = view.querySelector("#organizer-item-form"); form.hidden = false; form.querySelector("#organizer-title-input").focus(); });
    view.querySelector("#cancel-add-item").addEventListener("click", () => { view.querySelector("#organizer-item-form").hidden = true; view.querySelector("#show-add-form").hidden = false; });
    view.querySelectorAll("[data-check-item]").forEach((button) => button.addEventListener("click", async () => { await request(`/organizer/items/${button.dataset.checkItem}/checked`, { method: "POST", body: JSON.stringify({ approved: button.dataset.nextCheck === "true" }) }); await select(selected); }));
    view.querySelectorAll("[data-delete-item]").forEach((button) => button.addEventListener("click", async () => { if (!confirm("Move this item to Trash? You can restore it later.")) return; await request(`/organizer/items/${button.dataset.deleteItem}`, { method: "DELETE" }); await select(selected); }));
    view.querySelector("#delete-organizer-group").addEventListener("click", async () => { if (!confirm(`Archive “${group.name}” and its saved items? You can restore it from Trash.`)) return; await request(`/organizer/groups/${group.id}`, { method: "DELETE" }); selected = ""; await load(); });
    view.querySelector("#organizer-item-form").addEventListener("submit", async (event) => { event.preventDefault(); const kind = view.querySelector("#organizer-item-kind"); const title = view.querySelector("#organizer-title-input"); const content = view.querySelector("#organizer-content"); const url = view.querySelector("#organizer-url"); await request("/organizer/items", { method: "POST", body: JSON.stringify({ group_id: group.id, kind: kind.value, title: title.value, content: content.value, url: url.value.trim() || null }) }); await select(group.id); });
    icons();
  }

  async function select(id) {
    selected = id;
    const group = groups.find((item) => item.id === id);
    renderTree();
    if (!group) return emptyView();
    view.innerHTML = '<p class="organizer-empty-items">Loading collection…</p>';
    try { renderView(group, (await request(`/organizer/groups/${id}/items`)).items); }
    catch (error) { view.innerHTML = `<p class="organizer-empty-items">${esc(error.message)}</p>`; }
  }

  async function showTrash() {
    const archived = (await request("/organizer/groups/trash")).groups;
    selected = "";
    renderTree();
    view.innerHTML = `<header class="collection-header"><div><p class="eyebrow">recoverable</p><h3>Trash</h3><p>Nothing here is permanently deleted.</p></div></header><div class="organizer-items">${archived.length ? archived.map((group) => `<article class="organizer-saved-item"><div>${icon("folder")} <strong>${esc(group.name)}</strong><p>${group.count} item${group.count === 1 ? "" : "s"} · Archived ${when(group.deleted_at)}</p><button type="button" class="small-save" data-restore-group="${group.id}">Restore collection</button></div></article>`).join("") : '<p class="organizer-empty-items">Trash is empty.</p>'}</div>`;
    view.querySelectorAll("[data-restore-group]").forEach((button) => button.addEventListener("click", async () => { await request(`/organizer/groups/${button.dataset.restoreGroup}/restore`, { method: "POST" }); await load(); }));
    icons();
  }

  async function load() { groups = (await request("/organizer/groups")).groups; if (!groups.some((group) => group.id === selected)) selected = groups[0]?.id || ""; renderTree(); if (selected) await select(selected); else emptyView(); }
  function openGroupForm() { groupForm.hidden = false; document.getElementById("organizer-group-name").focus(); }

  document.getElementById("organizer-button").addEventListener("click", async () => { dialog.showModal(); await load(); });
  dialog.querySelector(".dialog-close").addEventListener("click", () => dialog.close());
  document.getElementById("new-organizer-group").addEventListener("click", openGroupForm);
  trashButton.addEventListener("click", showTrash);
  document.getElementById("cancel-organizer-group").addEventListener("click", () => { groupForm.hidden = true; groupForm.reset(); });
  groupForm.addEventListener("submit", async (event) => { event.preventDefault(); const input = document.getElementById("organizer-group-name"); if (!input.value.trim()) return; const group = await request("/organizer/groups", { method: "POST", body: JSON.stringify({ name: input.value, kind: "custom", parent_id: null }) }); selected = group.id; groupForm.hidden = true; groupForm.reset(); await load(); });
  document.getElementById("save-clarification").addEventListener("click", async () => { const button = document.getElementById("save-clarification"); const style = document.getElementById("clarification-style").value; await request("/memories", { method: "POST", body: JSON.stringify({ category: "preference", content: `Clarification preference: ${style}` }) }); button.textContent = "Saved"; setTimeout(() => { button.textContent = "Save preference"; }, 1300); });
})();
