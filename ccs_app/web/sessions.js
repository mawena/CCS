// Sessions : projets et conversations à gauche, onglets de chat à droite. Au téléphone, une
// colonne : la liste, puis le chat en plein écran avec un bouton de retour.
import { ChatView } from "./chat.js";
import { ago, clear, el } from "./dom.js";
import { TerminalView } from "./terminal.js";

const base = (p) => (p || "").split("/").filter(Boolean).pop() || p;

export function mountSessions(root, api) {
  const tabs = new Map();         // chat_id → { tab, view, holder }
  let current = null;
  const search = el("input", { type: "search", placeholder: "Rechercher une conversation", "aria-label": "Rechercher" });
  const list = el("div", { class: "session-list" });
  const tabBar = el("div", { class: "tabs", role: "tablist" });
  const stage = el("div", { class: "stage" });
  const back = el("button", { class: "flat back", onclick: () => show(null) }, "← Sessions");
  // comme « Nouvelle session… » du bureau : un dossier encore sans conversation (~ accepté)
  const folder = el("input", { type: "text", placeholder: "Dossier, par ex. ~/Repo/projet", "aria-label": "Dossier du projet",
    autocapitalize: "off", autocomplete: "off", spellcheck: "false", enterkeyhint: "go" });
  const typed = () => folder.value.trim();
  const newSession = el("form", { class: "new-session", onsubmit: (e) => { e.preventDefault(); if (typed()) open(typed()); } },
    folder,
    el("button", { type: "submit", class: "small" }, "Nouveau chat"),
    el("button", { type: "button", class: "small flat", title: "Terminal dans ce dossier",
      onclick: () => { if (typed()) openTerm(typed()); } }, "▸_"));
  const side = el("aside", { class: "side" }, el("h3", {}, "Nouvelle session"), newSession, search, list);
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

  function addTab(chatId, cwd, title, history, termOptions) {
    if (tabs.has(chatId)) { show(chatId); return; }
    if (!tabs.size) clear(stage);
    const holder = el("div", { class: "holder" });
    stage.append(holder);
    const isTerm = Boolean(termOptions);
    const view = isTerm ? new TerminalView(holder, api, termOptions) : new ChatView(holder, api, { chatId, cwd, title, history });
    const close = el("button", { class: "flat tab-close", "aria-label": "Fermer", onclick: async (e) => {
      e.stopPropagation();
      if (isTerm) {
        if (!confirm("Fermer ce terminal ? Ce qui y tourne est arrêté.")) return;
        view.destroy(true);
      } else {
        if (!confirm("Fermer ce chat ? Claude s'arrête ; la conversation reste dans l'historique.")) return;
        try { await api.call("chat.close", { chat_id: chatId }); } catch { /* déjà fermé */ }
        view.destroy();
      }
      holder.remove();
      tab.remove();
      tabs.delete(chatId);
      show(tabs.size ? [...tabs.keys()].pop() : null);
    } }, "×");
    const tab = el("div", { class: `tab${isTerm ? " term-tab" : ""}`, role: "tab", tabindex: "0", onclick: () => { show(chatId); if (isTerm) view.resize(); } },
      el("span", {}, (isTerm ? "▸ " : "") + (title || base(cwd))), close);
    tabBar.append(tab);
    tabs.set(chatId, { tab, view, holder });
    show(chatId);
  }

  async function open(cwd, conv) {
    try {
      const r = await api.call("chat.open", { cwd, session_id: conv?.session_id || null });
      const real = r.cwd || cwd;                  // chemin réel (~ développé par le pont)
      addTab(r.chat_id, real, conv?.title || base(real), r.seq ? null : conv?.path);
    } catch (e) { alert(e.message); }
  }

  let termSeq = 0;
  function openTerm(cwd, extra = {}) {
    const key = `term-${++termSeq}`;
    addTab(key, cwd, extra.title || base(cwd), null, { cwd, ...extra });
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
        p.exists ? el("button", { class: "small", onclick: () => open(p.cwd) }, "Nouveau chat") : null,
        p.exists ? el("button", { class: "small flat", title: "Terminal dans ce projet", onclick: () => openTerm(p.cwd) }, "▸_") : null));
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
    try {
      for (const t of (await api.call("term.list")).terms || []) addTab(`term-${t.term_id}`, "", "Terminal", null, { termId: t.term_id });
    } catch { /* pas de terminal */ }
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
