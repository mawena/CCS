// Sessions : « En cours » (chats et terminaux ouverts, avec leur état), projets et conversations
// à gauche, onglets de chat ou écran Projet à droite. Au téléphone, une colonne : la liste, puis
// le chat (ou le projet) en plein écran avec un bouton de retour.
import { ChatView } from "./chat.js";
import { clear, confirmSheet, el, emptyState, errorState, loading, toast } from "./dom.js";
import { baseName as base, ProjectScreen } from "./project.js";
import { convRow } from "./sessions-conv.js";
import { newSession } from "./sessions-new.js";
import { TerminalView } from "./terminal.js";

const STATES = {
  busy: ["Claude travaille", "busy"], permission: ["attend ta réponse", "permission"], idle: ["prêt", "idle"],
  starting: ["démarre", "busy"], suspended: ["en veille", "stopped"], stopped: ["arrêté", "stopped"],
};
const PROJECTS_STEP = 40;
const CONVS_STEP = 60;
const PROJECT_PREFIX = "projet/";

export function mountSessions(root, api, ctx = {}) {
  const tabs = new Map();         // chat_id (ou term-<n>) → { tab, view, holder, term, cwd, title, state, sessionId }
  let current = null;
  let project = null;             // { cwd, screen } : écran Projet ouvert (gardé pour le retrouver tel quel)
  let data = null;                // dernière réponse de projects.list
  let shownProjects = PROJECTS_STEP;
  let shownConvs = CONVS_STEP;
  const search = el("input", { type: "search", placeholder: "Rechercher une conversation", "aria-label": "Rechercher" });
  const running = el("div", { class: "running", hidden: true });
  const list = el("div", { class: "session-list" });
  const tabBar = el("div", { class: "tabs", role: "tablist" });
  const stage = el("div", { class: "stage" });
  // « ← Sessions » : comme le bouton Retour du téléphone quand on vient de la liste
  const back = el("button", { class: "flat back", onclick: () => (history.state?.fromList ? history.back() : show(null)) }, "← Sessions");
  const newBtn = el("button", { class: "primary new-session-btn", onclick: () => askNewSession() }, "Nouvelle session");
  const side = el("aside", { class: "side" }, newBtn, running, search, list);
  const main = el("div", { class: "main" }, el("div", { class: "tabs-row" }, back, tabBar), stage);
  const projectHost = el("div", { class: "project", hidden: true });
  const layout = el("div", { class: "sessions" }, side, main, projectHost);
  root.append(layout);

  // ---- navigation ------------------------------------------------------------------------------

  function hideProject() {
    projectHost.hidden = true;
    layout.classList.remove("project-open");
  }

  // push : nouvelle entrée d'historique (ouverture depuis la liste), sinon l'adresse est remplacée
  function show(chatId, { push = false } = {}) {
    hideProject();
    const want = chatId ? `#/sessions/${encodeURIComponent(chatId)}` : "#/sessions";
    if (location.hash !== want) history[push && !current ? "pushState" : "replaceState"]({ fromList: push && !current }, "", want);
    document.body.classList.toggle("chat-mode", Boolean(chatId));
    current = chatId;
    for (const [id, t] of tabs) {
      t.holder.hidden = id !== chatId;
      t.tab.classList.toggle("active", id === chatId);
      t.tab.setAttribute("aria-selected", String(id === chatId));
    }
    layout.classList.toggle("chat-open", Boolean(chatId));
    if (chatId) sessionStorage.setItem("ccs-chat", chatId); else sessionStorage.removeItem("ccs-chat");
    renderRunning();
    if (!tabs.size) clear(stage).append(emptyState("Aucun chat ouvert. Choisis un projet ou une conversation.",
      el("button", { class: "primary", onclick: () => askNewSession() }, "Nouvelle session")));
  }

  function showProject(cwd, { push = false } = {}) {
    document.body.classList.remove("chat-mode");
    current = null;
    for (const t of tabs.values()) t.holder.hidden = true;
    layout.classList.remove("chat-open");
    sessionStorage.removeItem("ccs-chat");
    const want = `#/sessions/${PROJECT_PREFIX}${encodeURIComponent(cwd)}`;
    if (location.hash !== want) history[push ? "pushState" : "replaceState"]({ fromList: push }, "", want);
    if (!project || project.cwd !== cwd) {
      project?.screen.destroy();
      clear(projectHost);
      project = { cwd, screen: new ProjectScreen(projectHost, api, cwd, {
        onBack: () => (history.state?.fromList ? history.back() : show(null)),
        resume: (c) => open(c.cwd, c),
        newChat: (dir, text) => open(dir, null, {}, text),
        openTerm: (dir) => openTerm(dir),
        opened: openedIds,
      }) };
    }
    projectHost.hidden = false;
    layout.classList.add("project-open");
  }

  const openedIds = () => new Set([...tabs.values()].map((t) => t.sessionId).filter(Boolean));

  // ---- onglets ---------------------------------------------------------------------------------

  async function closeTab(id) {
    const t = tabs.get(id);
    if (!t) return;
    const name = t.title || base(t.cwd);
    const ok = t.term
      ? await confirmSheet({ title: `Fermer le terminal « ${name} » ?`, body: "Ce qui y tourne est arrêté.", confirm: "Fermer", danger: true })
      : await confirmSheet({ title: `Fermer le chat « ${name} » ?`, body: "Claude s'arrête ; la conversation reste dans l'historique.", confirm: "Fermer", danger: true });
    if (!ok || !tabs.has(id)) return;
    if (t.term) t.view.destroy(true);
    else {
      try { await api.call("chat.close", { chat_id: id }); } catch { /* déjà fermé */ }
      t.view.destroy();
    }
    t.holder.remove();
    t.tab.remove();
    tabs.delete(id);
    renderRunning();
    if (current === id || !current) show(current === id ? (tabs.size ? [...tabs.keys()].pop() : null) : current);
  }

  function addTab(chatId, cwd, title, history, termOptions, meta = {}) {
    if (tabs.has(chatId)) { show(chatId); return tabs.get(chatId); }
    if (!tabs.size) clear(stage);
    const holder = el("div", { class: "holder" });
    stage.append(holder);
    const isTerm = Boolean(termOptions);
    const view = isTerm ? new TerminalView(holder, api, termOptions) : new ChatView(holder, api, { chatId, cwd, title, history });
    const close = el("button", { class: "flat tab-close", "aria-label": `Fermer ${title || base(cwd)}`, onclick: (e) => { e.stopPropagation(); closeTab(chatId); } }, "×");
    const tab = el("div", { class: `tab${isTerm ? " term-tab" : ""}`, role: "tab", tabindex: "0", onclick: () => { show(chatId); if (isTerm) view.resize(); } },
      el("span", {}, (isTerm ? "▸ " : "") + (title || base(cwd))), close);
    tabBar.append(tab);
    const rec = { tab, view, holder, term: isTerm, cwd, title: title || base(cwd), state: isTerm ? "term" : (meta.state || "starting"), sessionId: meta.session_id || null };
    tabs.set(chatId, rec);
    renderRunning();
    show(chatId, { push: true });
    return rec;
  }

  // chat.open ; options : { model, rights } ; text : premier message à envoyer. Lève en cas d'échec.
  async function openChat(cwd, conv, options, text) {
    const r = await api.call("chat.open", { cwd, session_id: conv?.session_id || null, ...(options ? { options } : {}) });
    const real = r.cwd || cwd;                  // chemin réel (~ développé par le pont)
    const rec = addTab(r.chat_id, real, conv?.title || base(real), r.seq ? null : conv?.path, null,
      { session_id: conv?.session_id, state: r.seq ? "idle" : "starting" });
    if (text && rec?.view?.sendText) rec.view.sendText(text);
    return true;
  }

  async function open(cwd, conv, options, text) {
    try { return await openChat(cwd, conv, options, text); } catch (e) {
      toast(e.message, { kind: "error", action: { label: "Réessayer", run: () => open(cwd, conv, options, text) } });
      return false;
    }
  }

  let termSeq = 0;
  function openTerm(cwd, extra = {}) {
    const key = `term-${++termSeq}`;
    addTab(key, cwd, extra.title || base(cwd), null, { cwd, ...extra });
  }

  function askNewSession(initial = "") {
    const known = ((data && data.entries) || []).filter((p) => p.cwd && p.exists).map((p) => ({ path: p.cwd, name: p.name }));
    newSession(api, {
      known, initial,
      onOpen: (cwd, options) => openChat(cwd, null, options),
      onTerm: (cwd) => openTerm(cwd),
    });
  }

  // ---- « En cours » ----------------------------------------------------------------------------

  function setState(chatId, state) {
    const t = tabs.get(chatId);
    if (!t || t.term || t.state === state) return;
    t.state = state;
    renderRunning();
  }

  function renderRunning() {
    clear(running);
    running.hidden = !tabs.size;
    if (!tabs.size) return;
    running.append(el("h3", {}, "En cours"));
    for (const [id, t] of tabs) {
      const [label, tone] = t.term ? ["terminal", "term"] : STATES[t.state] || ["", "stopped"];
      running.append(el("div", { class: `item run${id === current ? " active" : ""}` },
        el("button", { class: "run-main", onclick: () => { show(id, { push: true }); if (t.term) t.view.resize(); } },
          el("span", { class: `dot ${tone}`, "aria-hidden": "true" }),
          el("span", { class: "grow run-text" }, el("strong", {}, (t.term ? "▸ " : "") + t.title),
            el("span", { class: "subtle" }, `${label} · ${base(t.cwd) || ""}`))),
        el("button", { class: "flat run-close", "aria-label": `Fermer ${t.title}`, onclick: () => closeTab(id) }, "×")));
    }
  }

  // ---- liste des projets et des conversations --------------------------------------------------

  async function loadList({ quiet = false } = {}) {
    if (!quiet || !data) clear(list).append(loading());
    let r;
    try { r = await api.call("projects.list", { query: search.value }); } catch (e) {
      clear(list).append(errorState(e.message, () => loadList()));
      return;
    }
    data = r;
    renderList();
  }

  function renderList() {
    clear(list);
    const query = search.value.trim();
    const projects = (data.entries || []).filter((p) => p.cwd);
    const convs = data.conversations || [];
    if (!projects.length && !convs.length) {
      list.append(query ? emptyState(`Rien trouvé pour « ${query} ».`, el("button", { onclick: () => { search.value = ""; loadList(); } }, "Effacer la recherche"))
        : emptyState("Aucun projet ni conversation pour l'instant.", el("button", { class: "primary", onclick: () => askNewSession() }, "Nouvelle session")));
      return;
    }
    list.append(el("h3", {}, "Projets"));
    if (!projects.length) list.append(el("p", { class: "subtle" }, "Aucun projet ne correspond."));
    for (const p of projects.slice(0, shownProjects)) {
      list.append(el("div", { class: "item project-item" },
        el("button", { class: "project-open-btn grow", "aria-label": `Ouvrir le projet ${p.name}`, onclick: () => showProject(p.cwd, { push: true }) },
          el("strong", {}, p.name), el("span", { class: "subtle" }, `${p.total} conversation(s)${p.open ? ` · ${p.open} ouverte(s)` : ""}`)),
        p.exists ? el("button", { class: "small", onclick: () => open(p.cwd) }, "Nouveau chat") : null,
        p.exists ? el("button", { class: "small flat", title: "Terminal dans ce projet", "aria-label": `Terminal dans ${p.name}`, onclick: () => openTerm(p.cwd) }, "▸_") : null));
    }
    if (projects.length > shownProjects) list.append(el("button", { class: "flat more", onclick: () => { shownProjects += PROJECTS_STEP; renderList(); } },
      `Voir plus de projets (${projects.length - shownProjects})`));
    list.append(el("h3", {}, "Conversations récentes"));
    if (!convs.length) list.append(el("p", { class: "subtle" }, query ? "Aucune conversation ne correspond." : "Aucune conversation."));
    const cctx = { api, opened: openedIds(), resume: (c) => open(c.cwd, c) };
    for (const c of convs.slice(0, shownConvs)) list.append(convRow(c, cctx));
    if (convs.length > shownConvs) list.append(el("button", { class: "flat more", onclick: () => { shownConvs += CONVS_STEP; renderList(); } },
      `Voir plus de conversations (${convs.length - shownConvs})`));
  }

  async function restore() {
    let r;
    try { r = await api.call("chat.list"); } catch { r = { chats: [] }; }
    for (const c of r.chats || []) addTab(c.chat_id, c.cwd, base(c.cwd), null, null, { state: c.state, session_id: c.session_id });
    try {
      for (const t of (await api.call("term.list")).terms || []) addTab(`term-${t.term_id}`, t.cwd || "", t.name || "Terminal", null, { termId: t.term_id });
    } catch { /* pas de terminal */ }
    if (data) renderList();                                 // les conversations ouvertes reçoivent leur marque
    const asked = ctx.sub ? decodeURIComponent(ctx.sub) : null;
    if (asked && asked.startsWith(PROJECT_PREFIX)) { showProject(asked.slice(PROJECT_PREFIX.length)); return; }
    const keep = tabs.has(asked) ? asked : sessionStorage.getItem("ccs-chat");
    show(tabs.has(keep) ? keep : (matchMedia("(max-width: 719px)").matches ? null : [...tabs.keys()][0] || null));
  }

  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { shownProjects = PROJECTS_STEP; shownConvs = CONVS_STEP; loadList({ quiet: true }); }, 300); });
  const onNewChat = (e) => { if (e.detail?.cwd) open(e.detail.cwd, null, {}, e.detail.text); };
  document.addEventListener("ccs:new-chat", onNewChat);
  const offs = [
    api.on("reconnected", () => loadList({ quiet: true })),
    api.on("chat.event", (d) => { if (d.event?.type === "StateChanged") setState(d.chat_id, d.event.state); }),
  ];
  const first = ctx.sub ? decodeURIComponent(ctx.sub) : "";
  if (!first.startsWith(PROJECT_PREFIX)) show(null);
  loadList();
  restore();
  return {
    cleanup: () => {
      for (const off of offs) off();
      document.removeEventListener("ccs:new-chat", onNewChat);
      document.body.classList.remove("chat-mode");
      project?.screen.destroy();
      for (const t of tabs.values()) t.view.destroy();
    },
    // bouton Retour du téléphone, lien direct : la sous-adresse est un chat ou « projet/<chemin> »
    route: (sub) => {
      const id = sub ? decodeURIComponent(sub) : null;
      if (id && id.startsWith(PROJECT_PREFIX)) { showProject(id.slice(PROJECT_PREFIX.length)); return; }
      show(tabs.has(id) ? id : null);
    },
  };
}

