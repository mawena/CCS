// Sessions : projets et conversations à gauche, onglets de chat à droite. Au téléphone, une
// colonne : la liste, puis le chat en plein écran avec un bouton de retour.
import { ChatView } from "./chat.js";
import { ago, clear, el } from "./dom.js";

const base = (p) => (p || "").split("/").filter(Boolean).pop() || p;

export function mountSessions(root, api) {
  const tabs = new Map();         // chat_id → { tab, view, holder }
  let current = null;
  const search = el("input", { type: "search", placeholder: "Rechercher une conversation", "aria-label": "Rechercher" });
  const list = el("div", { class: "session-list" });
  const tabBar = el("div", { class: "tabs", role: "tablist" });
  const stage = el("div", { class: "stage" });
  const back = el("button", { class: "flat back", onclick: () => show(null) }, "← Sessions");
  const side = el("aside", { class: "side" }, search, list);
  const main = el("div", { class: "main" }, el("div", { class: "tabs-row" }, back, tabBar), stage);
  const layout = el("div", { class: "sessions" }, side, main);
  root.append(layout);

  function show(chatId) {
    current = chatId;
    for (const [id, t] of tabs) {
      t.holder.hidden = id !== chatId;
      t.tab.classList.toggle("active", id === chatId);
      t.tab.setAttribute("aria-selected", String(id === chatId));
    }
    layout.classList.toggle("chat-open", Boolean(chatId));
    if (chatId) sessionStorage.setItem("ccs-chat", chatId); else sessionStorage.removeItem("ccs-chat");
    if (!tabs.size) clear(stage).append(el("div", { class: "card empty" }, el("h2", {}, "Aucun chat ouvert"),
      el("p", { class: "subtle" }, "Choisis un projet ou une conversation à gauche.")));
  }

  function addTab(chatId, cwd, title, history) {
    if (tabs.has(chatId)) { show(chatId); return; }
    if (!tabs.size) clear(stage);
    const holder = el("div", { class: "holder" });
    stage.append(holder);
    const view = new ChatView(holder, api, { chatId, cwd, title, history });
    const close = el("button", { class: "flat tab-close", "aria-label": "Fermer", onclick: async (e) => {
      e.stopPropagation();
      if (!confirm("Fermer ce chat ? Claude s'arrête ; la conversation reste dans l'historique.")) return;
      try { await api.call("chat.close", { chat_id: chatId }); } catch { /* déjà fermé */ }
      view.destroy();
      holder.remove();
      tab.remove();
      tabs.delete(chatId);
      show(tabs.size ? [...tabs.keys()].pop() : null);
    } }, "×");
    const tab = el("div", { class: "tab", role: "tab", tabindex: "0", onclick: () => show(chatId) },
      el("span", {}, title || base(cwd)), close);
    tabBar.append(tab);
    tabs.set(chatId, { tab, view, holder });
    show(chatId);
  }

  async function open(cwd, conv) {
    try {
      const r = await api.call("chat.open", { cwd, session_id: conv?.session_id || null });
      addTab(r.chat_id, cwd, conv?.title || base(cwd), r.seq ? null : conv?.path);
    } catch (e) { alert(e.message); }
  }

  async function loadList() {
    let r;
    try { r = await api.call("projects.list", { query: search.value }); } catch (e) {
      clear(list).append(el("p", { class: "message" }, e.message));
      return;
    }
    clear(list);
    const projects = (r.entries || []).filter((p) => p.cwd);
    list.append(el("h3", {}, "Projets"));
    for (const p of projects.slice(0, 40)) {
      list.append(el("div", { class: "item" },
        el("div", { class: "grow" }, el("strong", {}, p.name), el("div", { class: "subtle" },
          `${p.total} conversation(s)${p.open ? ` · ${p.open} ouverte(s)` : ""}`)),
        p.exists ? el("button", { class: "small", onclick: () => open(p.cwd) }, "Nouveau chat") : null));
    }
    list.append(el("h3", {}, "Conversations récentes"));
    for (const c of (r.conversations || []).slice(0, 60)) {
      list.append(el("button", { class: "item conv", onclick: () => open(c.cwd, c), disabled: !c.folder_exists },
        el("strong", {}, c.title || c.first_prompt || "(sans titre)"),
        el("span", { class: "subtle" }, `${base(c.cwd)} · ${ago(c.updated_at)}`)));
    }
  }

  async function restore() {
    let r;
    try { r = await api.call("chat.list"); } catch { return; }
    for (const c of r.chats || []) addTab(c.chat_id, c.cwd, base(c.cwd), null);
    const keep = sessionStorage.getItem("ccs-chat");
    show(tabs.has(keep) ? keep : (matchMedia("(max-width: 719px)").matches ? null : [...tabs.keys()][0] || null));
  }

  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(loadList, 300); });
  show(null);
  loadList();
  restore();
  const off = api.on("reconnected", loadList);
  return () => { off(); for (const t of tabs.values()) t.view.destroy(); };
}
