// Sessions : « En cours » (chats et terminaux ouverts, avec leur état), projets et conversations
// à gauche, onglets de chat ou écran Projet à droite. Au téléphone, une colonne : la liste, puis
// le chat (ou le projet) en plein écran avec un bouton de retour. Quand d'autres machines sont
// connues, la liste devient un arbre (machines à la racine, dépliées : leurs projets et
// conversations) et les onglets de plusieurs machines restent ouverts côte à côte, chacun sur sa
// propre connexion, sans changer la machine pilotée.
import { Api } from "./api.js";
import { ChatView, savedOptions } from "./chat.js";
import { clear, confirmSheet, contextMenu, el, emptyState, errorState, loading, promptSheet, resizable, toast } from "./dom.js";
import { addProject, openTrash, removeProject, trashConversation } from "./sessions-manage.js";
import { baseName as base, ProjectScreen } from "./project.js";
import { convRow, copy, renameConversation } from "./sessions-conv.js";
import { rememberProject } from "./calcul.js";
import { describe, knownMachines, machineName, otherMachines } from "./machines.js";
import { RootWatch } from "./root.js";
import { newSession } from "./sessions-new.js";
import { getMode, MODES, move, setMode, sortEntries } from "./sessions-order.js";
import { isOpen, loadTree, parseProject, projectSub, roots, saveTree, splitKey, tabKey } from "./sessions-tree.js";
import { TerminalView } from "./terminal.js";

const STATES = {
  busy: ["Claude travaille", "busy"], permission: ["attend ta réponse", "permission"], idle: ["prêt", "idle"],
  starting: ["démarre", "busy"], suspended: ["en veille", "stopped"], stopped: ["arrêté", "stopped"],
};
const PROJECTS_STEP = 40;
const CONVS_STEP = 60;
const PROJECT_PREFIX = "projet/";   // « projet~<machine>/<chemin> » sur une autre machine (sessions-tree.js)
const REMOTE_MS = 20_000;           // une autre machine qui ne répond pas : erreur plutôt qu'attente sans fin
const ACTIVE = new Set(["busy", "permission"]);   // états qui comptent comme activité (tri « Activité récente »)

export function mountSessions(root, api, ctx = {}) {
  // clé (voir tabKey) → { tab, view, holder, term, cwd, title, state, sessionId, m, rid, conn }
  const tabs = new Map();
  let current = null;
  let pair = null;                // vue partagée : [gauche, droite], deux clés d'onglets ; l'onglet courant est l'un des deux
  let project = null;             // { m, cwd, screen } : écran Projet ouvert (gardé pour le retrouver tel quel)
  const P = api.machine || "";    // machine pilotée (fixe pendant la vie de la page : la changer la remonte)
  const tree = loadTree();
  const conns = new Map();        // machine → { id, api, own, data, shownProjects, shownConvs, status, body, offs, root }
  let machines = roots(P, knownMachines(), machineName(api));
  const search = el("input", { type: "search", placeholder: "Rechercher une conversation", "aria-label": "Rechercher" });
  const running = el("div", { class: "running", hidden: true });
  const list = el("div", { class: "session-list" });
  const tree_ = () => machines.length > 1;   // arbre seulement s'il y a d'autres machines
  const tabBar = el("div", { class: "tabs", role: "tablist" });
  const stage = el("div", { class: "stage" });
  // « ← Sessions » : comme le bouton Retour du téléphone quand on vient de la liste
  const back = el("button", { class: "flat back", onclick: () => (history.state?.fromList ? history.back() : show(null)) }, "← Sessions");
  const newBtn = el("button", { class: "primary new-session-btn", onclick: () => askNewSession() }, "Nouvelle session");
  // Le cadre ne défile pas : la poignée de redimensionnement reste visible pendant le défilement.
  const side = el("aside", { class: "side" }, el("div", { class: "side-body" }, newBtn, running, search, list));
  resizable(side, "sessions-side", { min: 220, max: 600 });
  // Grand écran : masquer / réafficher la liste des sessions (choix gardé).
  const sideToggle = el("button", { class: "flat side-toggle", "aria-label": "Masquer ou afficher la liste des sessions",
    title: "Masquer / afficher la liste", onclick: () => toggleSide() }, "☰");
  // Vue partagée : deux onglets côte à côte (en colonne sur téléphone), séparés par une poignée.
  const splitBtn = el("button", { class: "flat split-toggle", "aria-label": "Vue partagée : deux onglets côte à côte",
    title: "Vue partagée (deux onglets côte à côte)", onclick: () => toggleSplit() }, "◫");
  const divider = el("div", { class: "split-handle", role: "separator", title: "Glisser pour régler le partage (double-clic : moitié-moitié)" });
  const main = el("div", { class: "main" }, el("div", { class: "tabs-row" }, sideToggle, back, tabBar, splitBtn), stage);
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
    // un onglet hors de la vue partagée prend la place du volet courant
    if (pair && chatId && !pair.includes(chatId)) pair[Math.max(0, pair.indexOf(current))] = chatId;
    if (pair && (!tabs.has(pair[0]) || !tabs.has(pair[1]) || pair[0] === pair[1])) pair = null;
    current = chatId;
    if (tabs.has(chatId)) tabs.get(chatId).shownAt = Date.now();
    const both = Boolean(pair && chatId);
    for (const [id, t] of tabs) {
      const side = both ? pair.indexOf(id) : -1;
      t.holder.hidden = side < 0 && id !== chatId;
      t.holder.style.order = side < 0 ? "" : String(side * 2);
      t.holder.classList.toggle("focused", both && id === chatId);
      t.holder.classList.toggle("split-right", side === 1);
      t.tab.classList.toggle("active", id === chatId);
      t.tab.classList.toggle("split-tab", both && side >= 0 && id !== chatId);
      t.tab.setAttribute("aria-selected", String(id === chatId));
    }
    stage.classList.toggle("split", both);
    if (both) { if (divider.parentNode !== stage) stage.append(divider); } else divider.remove();
    splitBtn.classList.toggle("active", Boolean(pair));
    splitBtn.disabled = !pair && tabs.size < 2;
    if (both) requestAnimationFrame(() => { for (const id of pair) { const t = tabs.get(id); if (t?.term) t.view.resize(); } });
    layout.classList.toggle("chat-open", Boolean(chatId));
    // téléphone : un chat (pas un terminal) n'a qu'une barre, la sienne, avec son bouton retour
    layout.classList.toggle("chat-tab", Boolean(chatId && tabs.has(chatId) && !tabs.get(chatId).term));
    if (chatId) sessionStorage.setItem("ccs-chat", chatId); else sessionStorage.removeItem("ccs-chat");
    renderRunning();
    if (!tabs.size) clear(stage).append(emptyState("Aucun chat ouvert. Choisis un projet ou une conversation.",
      el("button", { class: "primary", onclick: () => askNewSession() }, "Nouvelle session")));
  }

  function showProject(m, cwd, { push = false } = {}) {
    const c = ensureConn(m);
    document.body.classList.remove("chat-mode");
    current = null;
    for (const t of tabs.values()) t.holder.hidden = true;
    layout.classList.remove("chat-open", "chat-tab");
    sessionStorage.removeItem("ccs-chat");
    const want = `#/sessions/${encodeURIComponent(projectSub(P, m, cwd))}`;
    if (location.hash !== want) history[push ? "pushState" : "replaceState"]({ fromList: push }, "", want);
    rememberProject(c.api, cwd);        // dossier proposé pour lancer une commande (onglet Réseau)
    if (!project || project.cwd !== cwd || project.m !== m) {
      project?.screen.destroy();
      clear(projectHost);
      project = { m, cwd, screen: new ProjectScreen(projectHost, c.api, cwd, {
        onBack: () => (history.state?.fromList ? history.back() : show(null)),
        resume: (conv) => open(c, conv.cwd, conv),
        newChat: (dir, text) => askNewSession(m, dir, text),
        openTerm: (dir) => openTerm(c, dir),
        opened: () => openedIds(c),
      }) };
    }
    projectHost.hidden = false;
    layout.classList.add("project-open");
  }

  // ---- vue partagée --------------------------------------------------------------------------

  // id ouvert à côté de l'onglet courant ; sans id : le dernier onglet actif autre que le courant
  function openBeside(id) {
    if (!current || !tabs.has(current)) return;
    if (!id) {
      const others = [...tabs].filter(([k]) => k !== current).sort(([, a], [, b]) => (b.shownAt || 0) - (a.shownAt || 0));
      id = others[0]?.[0];
    }
    if (!id || id === current || !tabs.has(id)) return;
    pair = [current, id];
    show(current);
  }

  function closeSplit() {
    pair = null;
    show(current);
    const t = tabs.get(current);
    if (t?.term) t.view.resize();
  }

  const toggleSplit = () => (pair ? closeSplit() : openBeside());

  // Proportion du volet gauche (ou du haut), gardée.
  const setRatio = (r) => { stage.style.setProperty("--split", `${Math.min(Math.max(r, 20), 80)}%`); };
  setRatio(Number(localStorage.getItem("ccs-split-ratio")) || 50);
  divider.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    divider.setPointerCapture(e.pointerId);
    const box = stage.getBoundingClientRect();
    const col = getComputedStyle(stage).flexDirection === "column";
    let ratio = 50;
    const move = (ev) => {
      ratio = col ? ((ev.clientY - box.top) / box.height) * 100 : ((ev.clientX - box.left) / box.width) * 100;
      setRatio(ratio);
    };
    const up = () => {
      divider.removeEventListener("pointermove", move);
      divider.removeEventListener("pointerup", up);
      document.body.classList.remove("resizing");
      localStorage.setItem("ccs-split-ratio", String(Math.round(Math.min(Math.max(ratio, 20), 80))));
      for (const id of pair || []) { const t = tabs.get(id); if (t?.term) t.view.resize(); }
    };
    document.body.classList.add("resizing");
    divider.addEventListener("pointermove", move);
    divider.addEventListener("pointerup", up);
  });
  divider.addEventListener("dblclick", () => { setRatio(50); localStorage.removeItem("ccs-split-ratio"); });

  const openedIds = (c) => new Set([...tabs.values()].filter((t) => t.conn === c).map((t) => t.sessionId).filter(Boolean));
  const machineLabel = (m) => machines.find((x) => x.id === m)?.name || m || "Ce serveur";

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
      try { await t.conn.api.call("chat.close", { chat_id: t.rid }); } catch { /* déjà fermé */ }
      t.view.destroy();
    }
    t.holder.remove();
    t.tab.remove();
    tabs.delete(id);
    detach(t.m);
    renderRunning();
    // dans la vue partagée : l'autre volet reste seul et devient l'onglet courant
    const mate = pair?.includes(id) ? pair.find((k) => k !== id) : null;
    if (mate) pair = null;
    if (mate && current === id) show(mate);
    else if (current === id || !current || mate) show(current === id ? (tabs.size ? [...tabs.keys()].pop() : null) : current);
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
    if (!t.sessionId || !t.path) { await sync(t.conn); t = tabs.get(id); }
    if (!t) return;
    if (!t.sessionId || !t.path) { toast("Cette conversation n'a pas encore commencé : envoie d'abord un message.", { kind: "error" }); return; }
    await renameConversation(t.conn.api, { session_id: t.sessionId, path: t.path, title: t.title });
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
      { label: "Ouvrir à côté", disabled: !current || id === current || Boolean(pair?.includes(id) && pair.includes(current)), run: () => openBeside(id) },
      { label: "Fermer la vue partagée", disabled: !pair, run: () => closeSplit() },
      null,
      { label: "Monter", disabled: at <= 0, run: () => { move(order, id, { delta: -1 }); renderRunning(); } },
      { label: "Descendre", disabled: at < 0 || at >= order.length - 1, run: () => { move(order, id, { delta: 1 }); renderRunning(); } },
      null,
      { label: "Nouveau chat dans ce projet", disabled: !ok, run: () => askNewSession(t.m, t.cwd) },
      { label: "Terminal dans ce projet", disabled: !ok, run: () => openTerm(t.conn, t.cwd) },
      { label: "Ouvrir le projet", disabled: !ok, run: () => showProject(t.m, t.cwd, { push: true }) },
      { label: "Copier le chemin", disabled: !ok, run: () => copy(t.cwd) },
      null,
      { label: t.term ? "Fermer le terminal" : "Fermer le chat", danger: true, run: () => closeTab(id) },
      { label: "Fermer les autres onglets", danger: true, disabled: tabs.size < 2, run: () => closeOthers(id) },
    ]);
  }

  // meta : { state, session_id, options, silent } ; silent : ne change ni l'onglet courant ni l'historique
  // (restauration au chargement et à la reconnexion : Retour ne doit pas se presser deux fois).
  function addTab(c, rid, cwd, title, history, termOptions, meta = {}) {
    const chatId = tabKey(P, c.id, rid);
    if (tabs.has(chatId)) { if (!meta.silent) show(chatId); return tabs.get(chatId); }
    if (!tabs.size) clear(stage);
    const holder = el("div", { class: "holder" });
    // vue partagée : un clic dans un volet en fait l'onglet courant
    holder.addEventListener("pointerdown", () => { if (pair?.includes(chatId) && current !== chatId) show(chatId); }, true);
    stage.append(holder);
    const isTerm = Boolean(termOptions);
    const view = isTerm ? new TerminalView(holder, c.api, termOptions) : new ChatView(holder, c.api, { chatId: rid, cwd, title, history, sessionId: meta.session_id || null, options: meta.options || null,
      host: { back: () => back.click(), resume: (v) => resumeStopped(chatId, v), stopped: () => { const t = tabs.get(chatId); if (t) { t.state = "stopped"; renderRunning(); } } } });
    const closeBtn = el("button", { class: "flat tab-close", "aria-label": `Fermer ${title || base(cwd)}`, onclick: (e) => { e.stopPropagation(); closeTab(chatId); } }, "×");
    const label = el("span", {}, (isTerm ? "▸ " : "") + (title || base(cwd)));
    // badge de la machine quand ce n'est pas la machine pilotée
    const badge = c.id !== P ? el("span", { class: "tab-machine", title: machineLabel(c.id) }, machineLabel(c.id)) : null;
    const tab = el("div", { class: `tab${isTerm ? " term-tab" : ""}`, role: "tab", tabindex: "0", onclick: () => { show(chatId); if (isTerm) view.resize(); },
      oncontextmenu: (e) => tabMenu(e, chatId), ...dragProps(chatId, "x") }, badge, label, closeBtn);
    tabBar.append(tab);
    const rec = { tab, label, closeBtn, view, holder, term: isTerm, cwd, title: title || base(cwd), state: isTerm ? "term" : (meta.state || "starting"), activeAt: Date.now(),
      sessionId: meta.session_id || null, path: typeof history === "string" ? history : null, m: c.id, rid, conn: c };
    tabs.set(chatId, rec);
    splitBtn.disabled = !pair && tabs.size < 2;
    attach(c.id);
    renderRunning();
    if (!meta.silent) show(chatId, { push: true });
    return rec;
  }

  // chat.open ; options : { model, rights } ; text : premier message à envoyer. Lève en cas d'échec.
  async function openChat(c, cwd, conv, options, text) {
    options = options || savedOptions(conv?.session_id);   // conversation reprise : ses derniers paramètres
    const r = await c.api.call("chat.open", { cwd, session_id: conv?.session_id || null, ...(options ? { options } : {}) });
    const real = r.cwd || cwd;                  // chemin réel (~ développé par le pont)
    const rec = addTab(c, r.chat_id, real, conv?.title || base(real), conv?.path || r.path, null,
      { session_id: conv?.session_id || r.session_id, options: r.options, state: r.seq ? "idle" : "starting" });
    if (text && rec?.view?.sendText) rec.view.sendText(text);
    return true;
  }

  async function open(c, cwd, conv, options, text) {
    try { return await openChat(c, cwd, conv, options, text); } catch (e) {
      toast(e.message, { kind: "error", action: { label: "Réessayer", run: () => open(c, cwd, conv, options, text) } });
      return false;
    }
  }

  let termSeq = 0;
  function openTerm(c, cwd, extra = {}) {
    const key = `term-${++termSeq}`;
    addTab(c, key, cwd, extra.title || base(cwd), null, { cwd, ...extra });
  }

  // Tout nouveau chat passe par cette feuille (modèle, droits, compte) ; initial : dossier déjà choisi,
  // text : premier message à envoyer une fois le chat ouvert.
  // m : machine où ouvrir (la machine pilotée par défaut).
  function askNewSession(m = P, initial = "", text) {
    const c = ensureConn(m);
    if (!c.data) loadList(c, { quiet: true });              // dossiers connus de cette machine
    const known = ((c.data && c.data.entries) || []).filter((p) => p.cwd && p.exists).map((p) => ({ path: p.cwd, name: p.name }));
    newSession(c.api, {
      known, initial,
      onOpen: (cwd, options) => openChat(c, cwd, null, options, text),
      onTerm: (cwd) => openTerm(c, cwd),
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
            el("span", { class: "subtle" }, t.m !== P ? el("span", { class: "run-machine" }, machineLabel(t.m)) : null,
              `${label} · ${base(t.cwd) || ""}`))),
        el("button", { class: "flat run-close", "aria-label": `Fermer ${t.title}`, onclick: () => closeTab(id) }, "×")));
    }
  }

  // ---- connexions par machine ------------------------------------------------------------------

  // Connexion d'une machine : celle de la page pour la machine pilotée, une connexion à part sinon
  // (ouverte au premier besoin, fermée avec la page).
  function ensureConn(m) {
    if (conns.has(m)) return conns.get(m);
    const own = m !== P;
    const capi = own ? new Api({ machine: m }) : api;
    const c = { id: m, api: capi, own, data: null, shownProjects: PROJECTS_STEP, shownConvs: CONVS_STEP,
      status: own ? "connecting" : "online", body: el("div", { class: "machine-body" }), offs: [], root: null, titleTimer: null };
    conns.set(m, c);
    const status = (st) => { if (c.status !== st) { c.status = st; renderTree(); } };
    c.offs.push(
      capi.on("reconnected", () => { if (c.data) loadList(c, { quiet: true }); sync(c); }),
      capi.on("chat.event", (d) => {
        if (d.event?.type !== "StateChanged") return;
        setState(tabKey(P, m, d.chat_id), d.event.state);
        if (d.event.state === "idle") refreshTitles(c);
      }),
    );
    if (own) {
      c.offs.push(capi.on("online", () => status("online")), capi.on("offline", () => status("offline")),
        capi.on("machine-down", () => status("down")));
      c.root = new RootWatch(capi).start();          // mot de passe administrateur demandé par cette machine
      capi.connect();
    }
    return c;
  }

  // Appel avec délai pour une autre machine (un appel mis en file n'échoue jamais tout seul).
  function call(c, method, params) {
    const p = c.api.call(method, params);
    if (!c.own) return p;
    return Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error(`${machineLabel(c.id)} ne répond pas.`)), REMOTE_MS))]);
  }

  // Machines dont des onglets sont ouverts : reconnectées au prochain chargement.
  function attach(m) {
    if (tree.attached.includes(m)) return;
    tree.attached.push(m);
    saveTree(tree);
    renderTree();
  }
  function detach(m) {
    if ([...tabs.values()].some((t) => t.m === m) || !tree.attached.includes(m)) { renderTree(); return; }
    tree.attached = tree.attached.filter((x) => x !== m);
    saveTree(tree);
    renderTree();
  }

  // ---- arbre des machines ----------------------------------------------------------------------

  function toggleNode(m) {
    tree.open[m] = !isOpen(tree, m, P);
    saveTree(tree);
    if (tree.open[m]) {
      const c = ensureConn(m);
      if (!c.data) loadList(c);
      sync(c);
    }
    renderTree();
  }

  function renderTree() {
    clear(list);
    if (!tree_()) { list.append(ensureConn(P).body); return; }
    for (const m of machines) {
      const c = conns.get(m.id);
      const openN = isOpen(tree, m.id, P);
      const count = [...tabs.values()].filter((t) => t.m === m.id).length;
      const live = m.id === P || (m.online !== false && m.tunnel !== false && (!c || c.status === "online" || c.status === "connecting"));
      const state = c?.own && c.status === "offline" ? "connexion coupée" : c?.own && c.status === "down" ? "injoignable"
        : m.server ? (m.id === P ? "machine pilotée" : "le serveur") : m.id === P ? "machine pilotée" : describe(m);
      const node = el("div", { class: `machine-node${live ? "" : " offline"}` },
        el("div", { class: "machine-head" },
          el("button", { class: "machine-toggle", "aria-expanded": openN ? "true" : "false", onclick: () => toggleNode(m.id) },
            el("span", { class: "caret", "aria-hidden": "true" }, openN ? "▾" : "▸"),
            el("span", { "aria-hidden": "true" }, m.server ? "☁ " : "🖥 "),
            el("span", { class: "grow machine-label" }, el("strong", {}, m.name || m.id),
              el("span", { class: "subtle machine-status" }, `${state}${count ? ` · ${count} ouvert${count > 1 ? "s" : ""}` : ""}`))),
          el("button", { class: "small flat machine-add", disabled: !live, "aria-label": `Nouvelle session sur ${m.name || m.id}`,
            title: `Nouvelle session sur ${m.name || m.id}`, onclick: () => askNewSession(m.id) }, "+")));
      if (openN) node.append(ensureConn(m.id).body);
      list.append(node);
    }
  }

  async function refreshMachines() {
    const r = await otherMachines(api);
    const next = roots(P, r.machines, machineName(api));
    if (JSON.stringify(next) === JSON.stringify(machines)) return;
    machines = next;
    renderTree();
  }

  // ---- liste des projets et des conversations --------------------------------------------------

  async function loadList(c = ensureConn(P), { quiet = false } = {}) {
    if (!quiet || !c.data) clear(c.body).append(loading());
    let r;
    try { r = await call(c, "projects.list", { query: search.value }); } catch (e) {
      clear(c.body).append(errorState(e.message, () => loadList(c)));
      return;
    }
    c.data = r;
    renderList(c);
  }

  function renderList(c) {
    const body = c.body;
    clear(body);
    const query = search.value.trim();
    const capi = c.api;
    const m = c.id;
    const projects = (c.data.entries || []).filter((p) => p.cwd);
    const convs = c.data.conversations || [];
    const reload = () => loadList(c, { quiet: true });
    if (!projects.length && !convs.length) {
      body.append(query ? emptyState(`Rien trouvé pour « ${query} ».`, el("button", { onclick: () => { search.value = ""; reloadAll(); } }, "Effacer la recherche"))
        : emptyState("Aucun projet ni conversation pour l'instant.", el("button", { class: "primary", onclick: () => askNewSession(m) }, "Nouvelle session")));
      return;
    }
    body.append(el("div", { class: "list-head" }, el("h3", {}, "Projets"),
      el("button", { class: "small flat", "aria-label": "Ajouter un projet", title: "Ajouter un projet",
        onclick: () => addProject(capi, { folders: projects.map((p) => p.cwd), onDone: reload }) }, "+ Ajouter")));
    if (!projects.length) body.append(el("p", { class: "subtle" }, "Aucun projet ne correspond."));
    for (const p of projects.slice(0, c.shownProjects)) {
      body.append(el("div", { class: "item project-item", oncontextmenu: (e) => contextMenu(e, [
        { label: "Ouvrir le projet", run: () => showProject(m, p.cwd, { push: true }) },
        { label: "Nouveau chat", disabled: !p.exists, run: () => askNewSession(m, p.cwd) },
        { label: "Terminal", disabled: !p.exists, run: () => openTerm(c, p.cwd) },
        { label: "Copier le chemin", run: () => copy(p.cwd) },
        null,
        { label: "Retirer de la liste…", danger: true, run: () => removeProject(capi, p, { onDone: reload }) },
      ]) },
        el("button", { class: "project-open-btn grow", "aria-label": `Ouvrir le projet ${p.name}`, onclick: () => showProject(m, p.cwd, { push: true }) },
          el("strong", {}, p.name), el("span", { class: "subtle" }, `${p.total} conversation(s)${p.open ? ` · ${p.open} ouverte(s)` : ""}`)),
        p.exists ? el("button", { class: "small flat icon-btn", title: "Nouveau chat", "aria-label": `Nouveau chat dans ${p.name}`, onclick: () => askNewSession(m, p.cwd) }, "+") : null,
        p.exists ? el("button", { class: "small flat icon-btn", title: "Terminal dans ce projet", "aria-label": `Terminal dans ${p.name}`, onclick: () => openTerm(c, p.cwd) }, "▸_") : null,
        el("button", { class: "small flat icon-btn", title: "Retirer de la liste", "aria-label": `Retirer ${p.name} de la liste`,
          onclick: () => removeProject(capi, p, { onDone: reload }) }, "✕")));
    }
    if (projects.length > c.shownProjects) body.append(el("button", { class: "flat more", onclick: () => { c.shownProjects += PROJECTS_STEP; renderList(c); } },
      `Voir plus de projets (${projects.length - c.shownProjects})`));
    body.append(el("h3", {}, "Conversations récentes"));
    if (!convs.length) body.append(el("p", { class: "subtle" }, query ? "Aucune conversation ne correspond." : "Aucune conversation."));
    const cctx = { api: capi, opened: openedIds(c), resume: (conv) => open(c, conv.cwd, conv), trash: (conv) => trashOf(c, conv) };
    for (const conv of convs.slice(0, c.shownConvs)) body.append(convRow(conv, cctx));
    if (convs.length > c.shownConvs) body.append(el("button", { class: "flat more", onclick: () => { c.shownConvs += CONVS_STEP; renderList(c); } },
      `Voir plus de conversations (${convs.length - c.shownConvs})`));
    body.append(el("button", { class: "flat more trash-open", onclick: () => openTrash(capi, { onDone: reload }) }, "🗑 Corbeille"));
  }

  function trashOf(c, conv) {
    trashConversation(c.api, conv, { onDone: () => loadList(c, { quiet: true }) });
  }

  // listes affichées (machine pilotée, nœuds dépliés) relues, par exemple après une recherche
  function reloadAll() {
    for (const c of conns.values()) {
      c.shownProjects = PROJECTS_STEP; c.shownConvs = CONVS_STEP;
      if (c.id === P && !tree_() || isOpen(tree, c.id, P)) loadList(c, { quiet: true });
    }
  }

  // Recale les onglets d'une machine sur ce qui tourne vraiment dans son pont : ajoute ce qui manque,
  // marque « arrêté » ce qui n'y est plus (le pont a pu redémarrer après une mise à jour), remplace un
  // onglet dont le dossier ne correspond plus. Une liste qui n'arrive pas ne retire rien.
  async function sync(c = ensureConn(P)) {
    let r = null;
    try { r = await call(c, "chat.list"); } catch { /* on garde les onglets tels quels */ }
    if (r) {
      const alive = new Map((r.chats || []).map((x) => [x.chat_id, x]));
      for (const [id, t] of [...tabs]) {
        if (t.term || t.conn !== c) continue;
        const x = alive.get(t.rid);
        if (x && x.cwd === t.cwd) continue;
        if (x) dropTab(id);                                  // même identifiant, autre dossier : ce n'est plus ce chat
        else { t.state = "stopped"; t.view.gone?.(); }
      }
      for (const x of r.chats || []) {
        const key = tabKey(P, c.id, x.chat_id);
        const t = tabs.get(key);
        if (t) { if (ACTIVE.has(x.state) && x.state !== t.state) t.activeAt = Date.now(); t.state = x.state || t.state; t.sessionId = x.session_id || t.sessionId; t.path = x.path || t.path; setTitle(key, x.title); continue; }
        addTab(c, x.chat_id, x.cwd, x.title || base(x.cwd), x.path || null, null, { state: x.state, session_id: x.session_id, options: x.options, silent: true });
      }
    }
    try {
      const terms = (await call(c, "term.list")).terms || [];
      const live = new Set(terms.map((t) => t.term_id));
      const mine = [...tabs.values()].filter((t) => t.term && t.conn === c);
      const known = new Set(mine.map((t) => t.view.termId).filter(Boolean));
      for (const t of terms) {
        if (!known.has(t.term_id)) addTab(c, `term-${t.term_id}`, t.cwd || "", t.name || "Terminal", null, { termId: t.term_id }, { silent: true });
      }
      for (const t of mine) if (t.view.termId && !live.has(t.view.termId)) t.view.gone?.();
    } catch { /* pas de terminal */ }
    renderRunning();
    if (c.data) renderList(c);                              // les conversations ouvertes reçoivent leur marque
  }

  // Retire un onglet sans rien demander au pont (il n'existe plus ou n'est plus le même).
  function dropTab(id) {
    const t = tabs.get(id);
    if (!t) return;
    t.view.destroy();
    t.holder.remove();
    t.tab.remove();
    tabs.delete(id);
    detach(t.m);
    const mate = pair?.includes(id) ? pair.find((k) => k !== id) : null;
    if (mate) pair = null;
    if (current === id) show(mate);
    else if (mate) show(current);
  }

  // « Reprendre la conversation » d'un chat que le pont a perdu : nouveau chat sur la même conversation,
  // à la place de l'ancien onglet.
  async function resumeStopped(oldId, view) {
    const t = tabs.get(oldId);
    if (!t || !view.sessionId) return;
    const c = t.conn;
    const conv = { session_id: view.sessionId, title: t.title, path: view.history?.path || null };
    let r;
    const options = view.opts || savedOptions(view.sessionId);   // mêmes paramètres qu'avant l'arrêt
    try { r = await call(c, "chat.open", { cwd: t.cwd, session_id: view.sessionId, ...(options ? { options } : {}) }); } catch (e) {
      toast(e.message, { kind: "error", action: { label: "Réessayer", run: () => resumeStopped(oldId, view) } });
      return;
    }
    const rec = addTab(c, r.chat_id, r.cwd || t.cwd, conv.title, conv.path || r.path, null,
      { session_id: conv.session_id, options: r.options, state: r.seq ? "idle" : "starting" });
    if (tabs.get(oldId) !== rec) dropTab(oldId);           // le nouvel onglet est déjà devant : l'ancien disparaît
    renderRunning();
  }

  // Ouvre l'adresse demandée : écran Projet (« projet/… », « projet~<machine>/… ») ou onglet.
  async function goTo(id) {
    const proj = parseProject(P, id);
    if (proj) { showProject(proj.machine, proj.cwd); return true; }
    if (id && !tabs.has(id)) {                             // chat ouvert ailleurs ou d'une autre machine : on le rattrape
      const { machine } = splitKey(P, id);
      await sync(ensureConn(machine));
    }
    return false;
  }

  async function restore() {
    await sync();
    // machines dont des onglets étaient ouverts, ou dépliées : rattachées sans les attendre
    const asked = ctx.sub ? decodeURIComponent(ctx.sub) : null;
    const want = asked ? (parseProject(P, asked)?.machine ?? splitKey(P, asked).machine) : P;
    for (const m of new Set([...tree.attached, ...Object.keys(tree.open).filter((k) => tree.open[k])])) {
      if (m === P || m === want) continue;
      const c = ensureConn(m);
      sync(c);
      if (tree_() && isOpen(tree, m, P)) loadList(c);
    }
    if (await goTo(asked)) return;
    const keep = tabs.has(asked) ? asked : sessionStorage.getItem("ccs-chat");
    show(tabs.has(keep) ? keep : (matchMedia("(max-width: 719px)").matches ? null : [...tabs.keys()][0] || null));
  }

  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(reloadAll, 300); });
  const onNewChat = (e) => { if (e.detail?.cwd) askNewSession(e.detail.machine ?? P, e.detail.cwd, e.detail.text); };
  document.addEventListener("ccs:new-chat", onNewChat);
  // conversation renommée (onglet, liste, écran Projet) : ses onglets et la liste suivent
  const onRenamed = (e) => {
    const { session_id: sid, title } = e.detail || {};
    for (const [id, t] of tabs) if (!t.term && sid && t.sessionId === sid) setTitle(id, title);
    for (const c of conns.values()) if (c.data) loadList(c, { quiet: true });
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
  const refreshTitles = (c) => { clearTimeout(c.titleTimer); c.titleTimer = setTimeout(async () => {
    let r;
    try { r = await call(c, "chat.list"); } catch { return; }
    for (const x of r.chats || []) {
      const key = tabKey(P, c.id, x.chat_id);
      const t = tabs.get(key);
      if (!t || t.term) continue;
      t.sessionId = x.session_id || t.sessionId;
      t.path = x.path || t.path;
      setTitle(key, x.title);
    }
  }, 1500); };
  ensureConn(P);
  const first = ctx.sub ? decodeURIComponent(ctx.sub) : "";
  if (!parseProject(P, first)) show(null);
  renderTree();
  loadList();
  refreshMachines();
  restore();
  return {
    cleanup: () => {
      for (const c of conns.values()) {
        for (const off of c.offs) off();
        clearTimeout(c.titleTimer);
        c.root?.stop();
        if (c.own) c.api.close();
      }
      document.removeEventListener("ccs:new-chat", onNewChat);
      document.removeEventListener("ccs:conv-renamed", onRenamed);
      window.removeEventListener("keydown", onTabKey, true);
      document.body.classList.remove("chat-mode");
      project?.screen.destroy();
      for (const t of tabs.values()) t.view.destroy();
    },
    // bouton Retour du téléphone, lien direct : la sous-adresse est un chat, « projet/<chemin> »
    // ou « projet~<machine>/<chemin> »
    route: (sub) => {
      const id = sub ? decodeURIComponent(sub) : null;
      if (id && (parseProject(P, id) || !tabs.has(id))) {
        goTo(id).then((done) => { if (!done) show(tabs.has(id) ? id : null); });
        return;
      }
      show(tabs.has(id) ? id : null);
    },
  };
}
