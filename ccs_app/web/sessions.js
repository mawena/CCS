// Sessions : « En cours » (chats et terminaux ouverts, avec leur état), projets et conversations
// à gauche, onglets de chat ou écran Projet à droite. Au téléphone, une colonne : la liste, puis
// le chat (ou le projet) en plein écran avec un bouton de retour.
import { ChatView } from "./chat.js";
import { clear, confirmSheet, contextMenu, el, emptyState, errorState, loading, promptSheet, resizable, toast } from "./dom.js";
import { addProject, openTrash, removeProject, trashConversation } from "./sessions-manage.js";
import { baseName as base, ProjectScreen } from "./project.js";
import { convRow, copy, renameConversation } from "./sessions-conv.js";
import { rememberProject } from "./pages-machines.js";
import { newSession } from "./sessions-new.js";
import { getMode, MODES, move, setMode, sortEntries } from "./sessions-order.js";
import { TerminalView } from "./terminal.js";

const STATES = {
  busy: ["Claude travaille", "busy"], permission: ["attend ta réponse", "permission"], idle: ["prêt", "idle"],
  starting: ["démarre", "busy"], suspended: ["en veille", "stopped"], stopped: ["arrêté", "stopped"],
};
const PROJECTS_STEP = 40;
const CONVS_STEP = 60;
const PROJECT_PREFIX = "projet/";
const ACTIVE = new Set(["busy", "permission"]);   // états qui comptent comme activité (tri « Activité récente »)

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
  resizable(side, "sessions-side", { min: 220, max: 600 });
  // Grand écran : masquer / réafficher la liste des sessions (choix gardé).
  const sideToggle = el("button", { class: "flat side-toggle", "aria-label": "Masquer ou afficher la liste des sessions",
    title: "Masquer / afficher la liste", onclick: () => toggleSide() }, "☰");
  const main = el("div", { class: "main" }, el("div", { class: "tabs-row" }, sideToggle, back, tabBar), stage);
  const projectHost = el("div", { class: "project", hidden: true });
  const layout = el("div", { class: "sessions" }, side, main, projectHost);
  const toggleSide = (hide = !layout.classList.contains("side-hidden")) => {
    layout.classList.toggle("side-hidden", hide);
    localStorage.setItem("ccs-side-hidden", hide ? "1" : "");
  };
  toggleSide(localStorage.getItem("ccs-side-hidden") === "1");
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
    // téléphone : un chat (pas un terminal) n'a qu'une barre, la sienne, avec son bouton retour
    layout.classList.toggle("chat-tab", Boolean(chatId && !chatId.startsWith("term-")));
    if (chatId) sessionStorage.setItem("ccs-chat", chatId); else sessionStorage.removeItem("ccs-chat");
    renderRunning();
    if (!tabs.size) clear(stage).append(emptyState("Aucun chat ouvert. Choisis un projet ou une conversation.",
      el("button", { class: "primary", onclick: () => askNewSession() }, "Nouvelle session")));
  }

  function showProject(cwd, { push = false } = {}) {
    document.body.classList.remove("chat-mode");
    current = null;
    for (const t of tabs.values()) t.holder.hidden = true;
    layout.classList.remove("chat-open", "chat-tab");
    sessionStorage.removeItem("ccs-chat");
    const want = `#/sessions/${PROJECT_PREFIX}${encodeURIComponent(cwd)}`;
    if (location.hash !== want) history[push ? "pushState" : "replaceState"]({ fromList: push }, "", want);
    rememberProject(api, cwd);          // dossier proposé par la page Machines
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

  async function closeTab(id, { ask = true } = {}) {
    const t = tabs.get(id);
    if (!t) return;
    const name = t.title || base(t.cwd);
    const ok = !ask || (t.term
      ? await confirmSheet({ title: `Fermer le terminal « ${name} » ?`, body: "Ce qui y tourne est arrêté.", confirm: "Fermer", danger: true })
      : await confirmSheet({ title: `Fermer le chat « ${name} » ?`, body: "Claude s'arrête ; la conversation reste dans l'historique.", confirm: "Fermer", danger: true }));
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

  async function closeOthers(id) {
    const others = [...tabs.keys()].filter((k) => k !== id);
    if (!others.length) return;
    const ok = await confirmSheet({ title: `Fermer les ${others.length} autre(s) onglet(s) ?`,
      body: "Claude s'arrête dans ces chats (leurs conversations restent dans l'historique) ; ce qui tourne dans ces terminaux est arrêté.", confirm: "Fermer", danger: true });
    if (!ok) return;
    show(id);
    for (const k of others) await closeTab(k, { ask: false });
  }

  // Titre d'un onglet (et de son chat, de « En cours »).
  function setTitle(id, title) {
    const t = tabs.get(id);
    if (!t || !title || t.title === title) return;
    t.title = title;
    t.label.textContent = (t.term ? "▸ " : "") + title;
    t.closeBtn.setAttribute("aria-label", `Fermer ${title}`);
    t.view.setTitle?.(title);
    renderRunning();
  }

  // Renommer : la conversation elle-même pour un chat (comme `/rename`), le seul onglet pour un terminal.
  async function renameTab(id) {
    let t = tabs.get(id);
    if (!t) return;
    if (t.term) {
      const v = await promptSheet({ title: "Renommer le terminal", value: t.title, confirm: "Renommer", maxlength: 80 });
      if (v && v.trim()) setTitle(id, v.trim());
      return;
    }
    if (!t.sessionId || !t.path) { await sync(); t = tabs.get(id); }
    if (!t) return;
    if (!t.sessionId || !t.path) { toast("Cette conversation n'a pas encore commencé : envoie d'abord un message.", { kind: "error" }); return; }
    await renameConversation(api, { session_id: t.sessionId, path: t.path, title: t.title });
  }

  // Clic droit sur un onglet ou une ligne de « En cours ».
  function tabMenu(e, id) {
    const t = tabs.get(id);
    if (!t) return;
    const ok = Boolean(t.cwd);
    const order = ordered();
    const at = order.findIndex(([k]) => k === id);
    contextMenu(e, [
      { label: "Renommer…", run: () => renameTab(id) },
      null,
      { label: "Monter", disabled: at <= 0, run: () => { move(order, id, { delta: -1 }); renderRunning(); } },
      { label: "Descendre", disabled: at < 0 || at >= order.length - 1, run: () => { move(order, id, { delta: 1 }); renderRunning(); } },
      null,
      { label: "Nouveau chat dans ce projet", disabled: !ok, run: () => open(t.cwd) },
      { label: "Terminal dans ce projet", disabled: !ok, run: () => openTerm(t.cwd) },
      { label: "Ouvrir le projet", disabled: !ok, run: () => showProject(t.cwd, { push: true }) },
      { label: "Copier le chemin", disabled: !ok, run: () => copy(t.cwd) },
      null,
      { label: t.term ? "Fermer le terminal" : "Fermer le chat", danger: true, run: () => closeTab(id) },
      { label: "Fermer les autres onglets", danger: true, disabled: tabs.size < 2, run: () => closeOthers(id) },
    ]);
  }

  // meta : { state, session_id, options, silent } ; silent : ne change ni l'onglet courant ni l'historique
  // (restauration au chargement et à la reconnexion : Retour ne doit pas se presser deux fois).
  function addTab(chatId, cwd, title, history, termOptions, meta = {}) {
    if (tabs.has(chatId)) { if (!meta.silent) show(chatId); return tabs.get(chatId); }
    if (!tabs.size) clear(stage);
    const holder = el("div", { class: "holder" });
    stage.append(holder);
    const isTerm = Boolean(termOptions);
    const view = isTerm ? new TerminalView(holder, api, termOptions) : new ChatView(holder, api, { chatId, cwd, title, history, sessionId: meta.session_id || null, options: meta.options || null,
      host: { back: () => back.click(), resume: (v) => resumeStopped(chatId, v), stopped: () => { const t = tabs.get(chatId); if (t) { t.state = "stopped"; renderRunning(); } } } });
    const closeBtn = el("button", { class: "flat tab-close", "aria-label": `Fermer ${title || base(cwd)}`, onclick: (e) => { e.stopPropagation(); closeTab(chatId); } }, "×");
    const label = el("span", {}, (isTerm ? "▸ " : "") + (title || base(cwd)));
    const tab = el("div", { class: `tab${isTerm ? " term-tab" : ""}`, role: "tab", tabindex: "0", onclick: () => { show(chatId); if (isTerm) view.resize(); },
      oncontextmenu: (e) => tabMenu(e, chatId), ...dragProps(chatId, "x") }, label, closeBtn);
    tabBar.append(tab);
    const rec = { tab, label, closeBtn, view, holder, term: isTerm, cwd, title: title || base(cwd), state: isTerm ? "term" : (meta.state || "starting"), activeAt: Date.now(),
      sessionId: meta.session_id || null, path: typeof history === "string" ? history : null };
    tabs.set(chatId, rec);
    renderRunning();
    if (!meta.silent) show(chatId, { push: true });
    return rec;
  }

  // chat.open ; options : { model, rights } ; text : premier message à envoyer. Lève en cas d'échec.
  async function openChat(cwd, conv, options, text) {
    const r = await api.call("chat.open", { cwd, session_id: conv?.session_id || null, ...(options ? { options } : {}) });
    const real = r.cwd || cwd;                  // chemin réel (~ développé par le pont)
    const rec = addTab(r.chat_id, real, conv?.title || base(real), conv?.path || r.path, null,
      { session_id: conv?.session_id || r.session_id, options: r.options, state: r.seq ? "idle" : "starting" });
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
    if (ACTIVE.has(state)) t.activeAt = Date.now();
    renderRunning();
  }

  // Sessions ouvertes dans l'ordre choisi (tri ou ordre manuel, voir sessions-order.js).
  const ordered = () => sortEntries([...tabs]);

  // Glisser-déposer d'un onglet (axe "x") ou d'une ligne de « En cours » (axe "y") sur un autre.
  let dragId = null;
  const dropMarks = () => document.querySelectorAll(".drop-before, .drop-after")
    .forEach((n) => n.classList.remove("drop-before", "drop-after"));
  const afterHalf = (e, axis) => {
    const r = e.currentTarget.getBoundingClientRect();
    return axis === "x" ? e.clientX > r.left + r.width / 2 : e.clientY > r.top + r.height / 2;
  };
  function dragProps(id, axis) {
    return {
      draggable: "true",
      ondragstart: (e) => { dragId = id; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", id); e.currentTarget.classList.add("dragging"); },
      ondragend: (e) => { dragId = null; e.currentTarget.classList.remove("dragging"); dropMarks(); },
      ondragover: (e) => {
        if (!dragId || dragId === id) return;
        e.preventDefault();
        dropMarks();
        e.currentTarget.classList.add(afterHalf(e, axis) ? "drop-after" : "drop-before");
      },
      ondrop: (e) => {
        if (!dragId || dragId === id) return;
        e.preventDefault();
        move(ordered(), dragId, { target: id, after: afterHalf(e, axis) });
        dropMarks();
        renderRunning();
      },
    };
  }

  function renderRunning() {
    clear(running);
    running.hidden = !tabs.size;
    if (!tabs.size) return;
    const mode = getMode();
    const sort = el("select", { class: "run-sort", "aria-label": "Trier les sessions", title: "Trier les sessions",
      onchange: (e) => { setMode(e.target.value); renderRunning(); } },
      ...MODES.map(([k, label]) => el("option", { value: k, selected: k === mode }, label)));
    running.append(el("div", { class: "list-head" }, el("h3", {}, "En cours"), sort));
    const order = ordered();
    // la barre d'onglets suit le même ordre (et Ctrl+Page préc./suiv. aussi)
    if (order.some(([, t], i) => tabBar.children[i] !== t.tab)) for (const [, t] of order) tabBar.append(t.tab);
    for (const [id, t] of order) {
      const [label, tone] = t.term ? ["terminal", "term"] : STATES[t.state] || ["", "stopped"];
      running.append(el("div", { class: `item run${id === current ? " active" : ""}`, oncontextmenu: (e) => tabMenu(e, id), ...dragProps(id, "y") },
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
    list.append(el("div", { class: "list-head" }, el("h3", {}, "Projets"),
      el("button", { class: "small flat", "aria-label": "Ajouter un projet", title: "Ajouter un projet",
        onclick: () => addProject(api, { folders: projects.map((p) => p.cwd), onDone: () => loadList({ quiet: true }) }) }, "+ Ajouter")));
    if (!projects.length) list.append(el("p", { class: "subtle" }, "Aucun projet ne correspond."));
    for (const p of projects.slice(0, shownProjects)) {
      list.append(el("div", { class: "item project-item", oncontextmenu: (e) => contextMenu(e, [
        { label: "Ouvrir le projet", run: () => showProject(p.cwd, { push: true }) },
        { label: "Nouveau chat", disabled: !p.exists, run: () => open(p.cwd) },
        { label: "Terminal", disabled: !p.exists, run: () => openTerm(p.cwd) },
        { label: "Copier le chemin", run: () => copy(p.cwd) },
        null,
        { label: "Retirer de la liste…", danger: true, run: () => removeProject(api, p, { onDone: () => loadList({ quiet: true }) }) },
      ]) },
        el("button", { class: "project-open-btn grow", "aria-label": `Ouvrir le projet ${p.name}`, onclick: () => showProject(p.cwd, { push: true }) },
          el("strong", {}, p.name), el("span", { class: "subtle" }, `${p.total} conversation(s)${p.open ? ` · ${p.open} ouverte(s)` : ""}`)),
        p.exists ? el("button", { class: "small", onclick: () => open(p.cwd) }, "Nouveau chat") : null,
        p.exists ? el("button", { class: "small flat", title: "Terminal dans ce projet", "aria-label": `Terminal dans ${p.name}`, onclick: () => openTerm(p.cwd) }, "▸_") : null,
        el("button", { class: "small flat", title: "Retirer de la liste", "aria-label": `Retirer ${p.name} de la liste`,
          onclick: () => removeProject(api, p, { onDone: () => loadList({ quiet: true }) }) }, "✕")));
    }
    if (projects.length > shownProjects) list.append(el("button", { class: "flat more", onclick: () => { shownProjects += PROJECTS_STEP; renderList(); } },
      `Voir plus de projets (${projects.length - shownProjects})`));
    list.append(el("h3", {}, "Conversations récentes"));
    if (!convs.length) list.append(el("p", { class: "subtle" }, query ? "Aucune conversation ne correspond." : "Aucune conversation."));
    const cctx = { api, opened: openedIds(), resume: (c) => open(c.cwd, c), trash: trashOf };
    for (const c of convs.slice(0, shownConvs)) list.append(convRow(c, cctx));
    if (convs.length > shownConvs) list.append(el("button", { class: "flat more", onclick: () => { shownConvs += CONVS_STEP; renderList(); } },
      `Voir plus de conversations (${convs.length - shownConvs})`));
    list.append(el("button", { class: "flat more trash-open", onclick: () => openTrash(api, { onDone: () => loadList({ quiet: true }) }) }, "🗑 Corbeille"));
  }

  function trashOf(c) {
    trashConversation(api, c, { onDone: () => loadList({ quiet: true }) });
  }

  // Recale les onglets sur ce qui tourne vraiment dans le pont : ajoute ce qui manque, marque « arrêté »
  // ce qui n'y est plus (le pont a pu redémarrer après une mise à jour), remplace un onglet dont le
  // dossier ne correspond plus. Une liste qui n'arrive pas ne retire rien.
  async function sync() {
    let r = null;
    try { r = await api.call("chat.list"); } catch { /* on garde les onglets tels quels */ }
    if (r) {
      const alive = new Map((r.chats || []).map((c) => [c.chat_id, c]));
      for (const [id, t] of [...tabs]) {
        if (t.term) continue;
        const c = alive.get(id);
        if (c && c.cwd === t.cwd) continue;
        if (c) dropTab(id);                                  // même identifiant, autre dossier : ce n'est plus ce chat
        else { t.state = "stopped"; t.view.gone?.(); }
      }
      for (const c of r.chats || []) {
        const t = tabs.get(c.chat_id);
        if (t) { if (ACTIVE.has(c.state) && c.state !== t.state) t.activeAt = Date.now(); t.state = c.state || t.state; t.sessionId = c.session_id || t.sessionId; t.path = c.path || t.path; setTitle(c.chat_id, c.title); continue; }
        addTab(c.chat_id, c.cwd, c.title || base(c.cwd), c.path || null, null, { state: c.state, session_id: c.session_id, options: c.options, silent: true });
      }
    }
    try {
      const terms = (await api.call("term.list")).terms || [];
      const live = new Set(terms.map((t) => t.term_id));
      const known = new Set([...tabs.values()].filter((t) => t.term).map((t) => t.view.termId).filter(Boolean));
      for (const t of terms) {
        if (!known.has(t.term_id)) addTab(`term-${t.term_id}`, t.cwd || "", t.name || "Terminal", null, { termId: t.term_id }, { silent: true });
      }
      for (const t of tabs.values()) if (t.term && t.view.termId && !live.has(t.view.termId)) t.view.gone?.();
    } catch { /* pas de terminal */ }
    renderRunning();
    if (data) renderList();                                 // les conversations ouvertes reçoivent leur marque
  }

  // Retire un onglet sans rien demander au pont (il n'existe plus ou n'est plus le même).
  function dropTab(id) {
    const t = tabs.get(id);
    if (!t) return;
    t.view.destroy();
    t.holder.remove();
    t.tab.remove();
    tabs.delete(id);
    if (current === id) show(null);
  }

  // « Reprendre la conversation » d'un chat que le pont a perdu : nouveau chat sur la même conversation,
  // à la place de l'ancien onglet.
  async function resumeStopped(oldId, view) {
    const t = tabs.get(oldId);
    if (!t || !view.sessionId) return;
    const conv = { session_id: view.sessionId, title: t.title, path: view.history?.path || null };
    let r;
    try { r = await api.call("chat.open", { cwd: t.cwd, session_id: view.sessionId }); } catch (e) {
      toast(e.message, { kind: "error", action: { label: "Réessayer", run: () => resumeStopped(oldId, view) } });
      return;
    }
    addTab(r.chat_id, r.cwd || t.cwd, conv.title, conv.path || r.path, null,
      { session_id: conv.session_id, options: r.options, state: r.seq ? "idle" : "starting" });
    if (r.chat_id !== oldId) dropTab(oldId);              // le nouvel onglet est déjà devant : l'ancien disparaît
    renderRunning();
  }

  async function restore() {
    await sync();
    const asked = ctx.sub ? decodeURIComponent(ctx.sub) : null;
    if (asked && asked.startsWith(PROJECT_PREFIX)) { showProject(asked.slice(PROJECT_PREFIX.length)); return; }
    const keep = tabs.has(asked) ? asked : sessionStorage.getItem("ccs-chat");
    show(tabs.has(keep) ? keep : (matchMedia("(max-width: 719px)").matches ? null : [...tabs.keys()][0] || null));
  }

  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { shownProjects = PROJECTS_STEP; shownConvs = CONVS_STEP; loadList({ quiet: true }); }, 300); });
  const onNewChat = (e) => { if (e.detail?.cwd) open(e.detail.cwd, null, {}, e.detail.text); };
  document.addEventListener("ccs:new-chat", onNewChat);
  // conversation renommée (onglet, liste, écran Projet) : ses onglets et la liste suivent
  const onRenamed = (e) => {
    const { session_id: sid, title } = e.detail || {};
    for (const [id, t] of tabs) if (!t.term && sid && t.sessionId === sid) setTitle(id, title);
    if (data) loadList({ quiet: true });
  };
  document.addEventListener("ccs:conv-renamed", onRenamed);
  // Ctrl+Page préc. / Ctrl+Page suiv. : onglet précédent / suivant, dans l'ordre de la barre, en boucle.
  // Capturé avant le chat et le terminal. Dans un onglet du navigateur, celui-ci garde souvent ces
  // touches pour ses propres onglets : elles arrivent ici surtout dans CCS installé en application.
  const onTabKey = (e) => {
    if (!e.ctrlKey || e.altKey || e.metaKey || e.shiftKey || (e.key !== "PageUp" && e.key !== "PageDown")) return;
    if (!tabs.size || document.querySelector("dialog[open], .ctx-menu")) return;
    const order = [...tabBar.children].map((n) => [...tabs].find(([, t]) => t.tab === n)?.[0]).filter(Boolean);
    if (!order.length) return;
    e.preventDefault();
    e.stopPropagation();
    const i = order.indexOf(current);
    const next = order[(i < 0 ? 0 : i + (e.key === "PageDown" ? 1 : -1) + order.length) % order.length];
    show(next);
    const t = tabs.get(next);
    t.tab.scrollIntoView({ block: "nearest", inline: "nearest" });
    if (t.term) t.view.resize();
  };
  window.addEventListener("keydown", onTabKey, true);
  // titre automatique de Claude Code (après la première réponse) : relu quand un chat redevient prêt
  let titleTimer;
  const refreshTitles = () => { clearTimeout(titleTimer); titleTimer = setTimeout(async () => {
    let r;
    try { r = await api.call("chat.list"); } catch { return; }
    for (const c of r.chats || []) {
      const t = tabs.get(c.chat_id);
      if (!t || t.term) continue;
      t.sessionId = c.session_id || t.sessionId;
      t.path = c.path || t.path;
      setTitle(c.chat_id, c.title);
    }
  }, 1500); };
  const offs = [
    api.on("reconnected", () => { loadList({ quiet: true }); sync(); }),
    api.on("chat.event", (d) => {
      if (d.event?.type !== "StateChanged") return;
      setState(d.chat_id, d.event.state);
      if (d.event.state === "idle") refreshTitles();
    }),
  ];
  const first = ctx.sub ? decodeURIComponent(ctx.sub) : "";
  if (!first.startsWith(PROJECT_PREFIX)) show(null);
  loadList();
  restore();
  return {
    cleanup: () => {
      for (const off of offs) off();
      document.removeEventListener("ccs:new-chat", onNewChat);
      document.removeEventListener("ccs:conv-renamed", onRenamed);
      window.removeEventListener("keydown", onTabKey, true);
      clearTimeout(titleTimer);
      document.body.classList.remove("chat-mode");
      project?.screen.destroy();
      for (const t of tabs.values()) t.view.destroy();
    },
    // bouton Retour du téléphone, lien direct : la sous-adresse est un chat ou « projet/<chemin> »
    route: (sub) => {
      const id = sub ? decodeURIComponent(sub) : null;
      if (id && id.startsWith(PROJECT_PREFIX)) { showProject(id.slice(PROJECT_PREFIX.length)); return; }
      if (id && !tabs.has(id)) { sync().then(() => show(tabs.has(id) ? id : null)); return; }   // chat ouvert ailleurs (« Reprendre » une tâche) : on le rattrape
      show(tabs.has(id) ? id : null);
    },
  };
}

