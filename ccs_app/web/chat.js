// Un chat de la version web : fil (messages, Markdown rendu par le pont, cartes d'actions,
// sous-agents), autorisations et questions de Claude, liste de tâches épinglée, barre modèle /
// effort / droits, saisie avec images. Les événements arrivent numérotés : après une coupure, le
// chat redemande ce qu'il a manqué (`chat.attach` depuis son dernier numéro).
import { choiceSheet, clear, el, resizable, setHtml, toast } from "./dom.js";
import { ChangesPanel } from "./chat-changes.js";
import { Completer } from "./chat-complete.js";
import { contextAlert, contextLevel, fmtTokens, usageSummary } from "./chat-context.js";
import { diffCard, editDiffs } from "./chat-diff.js";
import { linkify } from "./chat-links.js";
import { claudeNode, icon, quoteOf, REPLY_ICON, selectionIn, userNode } from "./chat-message.js";
import { CLAUDE, ME, compose, oneLine, sourceText } from "./chat-quote.js";
import { openTagSheet, TAG_ICON, TagsPanel, tagChips } from "./chat-tags.js";
import { openSavedSheet } from "./chat-saved.js";
import { FindBar } from "./chat-search.js";
import { FilesPanel } from "./files.js";
import { GitPanel } from "./git.js";
import { RoadmapPanel } from "./roadmap.js";

const RIGHTS = [["manual", "Demander"], ["acceptEdits", "Modifications acceptées"], ["plan", "Plan"],
  ["bypassPermissions", "Tout autoriser"]];
// Maj+Tab : « Tout autoriser » n'en fait pas partie (comme au bureau, il demande une confirmation)
const CYCLE_RIGHTS = ["manual", "acceptEdits", "plan"];
const EFFORTS = [["", "Effort par défaut"], ["low", "Faible"], ["medium", "Moyen"], ["high", "Élevé"],
  ["xhigh", "Très élevé"], ["max", "Max"]];
const DRAWER_TITLES = { files: "Fichiers", roadmap: "Feuille de route", git: "Git", changes: "Changements de la session", tags: "Étiquettes" };
const HISTORY_LIMIT = 200;
const fr = (n) => Number(n).toLocaleString("fr-FR");
const TOOL_LABELS = { Read: "Lecture", Edit: "Modification", MultiEdit: "Modification", Write: "Écriture",
  Bash: "Commande", Grep: "Recherche", Glob: "Fichiers", WebFetch: "Page web", WebSearch: "Recherche web",
  Task: "Sous-agent", Agent: "Sous-agent", TodoWrite: "Tâches", Skill: "Skill", AskUserQuestion: "Question" };

function target(name, input) {
  const i = input || {};
  const first = (s) => (typeof s === "string" ? s.split("\n")[0] : "");
  if (name === "Bash") return first(i.command);
  if (["Read", "Write", "Edit", "MultiEdit", "NotebookEdit"].includes(name)) return i.file_path || i.notebook_path || "";
  if (name === "Grep" || name === "Glob") return `${i.pattern || ""}${i.path ? ` dans ${i.path}` : ""}`;
  if (name === "WebFetch") return i.url || "";
  if (name === "WebSearch") return i.query || "";
  if (name === "Task" || name === "Agent") return i.description || first(i.prompt);
  if (name === "Skill") return i.skill || "";
  const s = Object.values(i).find((v) => typeof v === "string" && v.trim());
  return first(s || "");
}

function readImage(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve({ media_type: file.type || "image/png", data: String(r.result).split(",")[1] });
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

const DOWN_ICON = [["path", { d: "M12 5v14" }], ["path", { d: "m6 13 6 6 6-6" }]];

export class ChatView {
  // sessionId, options ({ model, effort, ultracode, rights }) : connus à l'ouverture ou au rattachement ;
  // host : { resume(view) } appelé par « Reprendre la conversation » quand le pont a perdu ce chat.
  constructor(root, api, { chatId, cwd, title, history, sessionId = null, options = null, host = null }) {
    this.api = api;
    this.chatId = chatId;
    this.cwd = cwd;
    this.host = host;
    this.sessionId = sessionId;
    this.opts = null;            // dernières options connues du moteur (tout est renvoyé à chaque changement)
    this.optionsReady = false;   // les listes sont remplies avec les vraies options : on peut envoyer
    this.panels = new Map();     // volets : un panneau par type, gardé d'une ouverture à l'autre
    this.seq = 0;
    this.texts = new Map();      // msg_id → { node, text, timer }
    this.tools = new Map();      // tool_id → carte
    this.perms = new Map();      // request_id → carte
    this.agents = new Map();     // tool_id → sous-agent : { name, view, pill, mark, card, done, background }
    this.shownAgent = null;      // sous-agent dont on regarde la vue (null : la conversation)
    this.shells = new Map();     // run_id → { card, command } (commandes `!` en cours)
    this.shellEarly = new Map(); // fins de commande arrivées avant la réponse du pont
    this.shellNotes = [];        // sorties des commandes `!`, ajoutées en tête du prochain message
    this.images = [];
    this.offs = [];
    this.history = history ? { path: history, loaded: 0, full: false } : null;
    this.workP = null;           // commandes `/` et réglage du contexte (work.commands)
    this.filesP = null;          // fichiers du projet (work.files)
    this.heavy = false;
    this.sending = false;
    this.draftKey = `ccs-draft:${cwd}|${chatId}`;      // identifiant du chat : unique d'un démarrage du pont à l'autre
    this.quote = null;           // message cité par la prochaine réponse : { author, text }
    this.quoteKey = `ccs-quote:${cwd}|${chatId}`;
    this.msgActions = [{ key: "reply", label: "Répondre", icon: REPLY_ICON, run: (msg) => this.replyTo(msg) },
      { key: "tag", label: "Étiqueter", icon: TAG_ICON, run: (msg) => this.tagMessage(msg) }];
    this.tagMap = {};            // identifiant d'un message → { tags, role, excerpt, ts } (conversation en cours)
    this.knownTags = [];         // étiquettes déjà utilisées (suggestions)
    this.tagsSession = null;     // conversation dont les étiquettes sont chargées
    this.renderQuote = (node, markdown) => this.quoteHtml(node, markdown);

    this.state = el("span", { class: "chat-state", hidden: true }, "");
    this.stopBtn = el("button", { type: "button", class: "small danger stop", hidden: true, onclick: () => this.call("chat.interrupt") }, "Arrêter");
    this.thread = el("div", { class: "thread", role: "log", "aria-live": "polite", tabindex: "-1" });
    // Suivre le bas du fil tant que l'utilisateur n'est pas remonté lire plus haut : le texte
    // rendu après coup (Markdown) agrandit le fil sans passer par append().
    this.follow = true;
    this.lastTop = 0;
    this.touching = false;
    // Bouton flottant : revient en bas du fil, visible seulement quand on en est loin.
    this.downBtn = el("button", { type: "button", class: "to-bottom", hidden: true, "aria-label": "Aller en bas",
      title: "Aller en bas", onclick: () => this.toBottom() }, icon(DOWN_ICON));
    this.watchThread();
    // Sous-agents : une pastille par sous-agent au-dessus du fil, chacun sa vue (comme sur le bureau).
    this.mainPill = el("button", { type: "button", class: "agent-pill active", onclick: () => this.showAgent(null) }, "Conversation");
    // Sous-agents finis : hors de la barre, mais dans « Terminés (n) », leur historique.
    this.historyBtn = el("button", { type: "button", class: "agent-pill agent-history-btn", hidden: true,
      "aria-expanded": "false", onclick: () => this.toggleAgentHistory() }, "Terminés");
    this.agentBar = el("div", { class: "agent-bar", hidden: true, role: "tablist", "aria-label": "Sous-agents" }, this.mainPill, this.historyBtn);
    this.agentHistory = el("div", { class: "agent-history", hidden: true, role: "list", "aria-label": "Sous-agents terminés" });
    this.thread.addEventListener("click", (e) => this.pick(e));
    this.working = el("div", { class: "working", hidden: true, role: "status" }, el("span", { class: "spinner" }), el("span", {}, "Claude travaille…"));
    this.todos = el("div", { class: "todos", hidden: true });
    this.input = el("textarea", { rows: 1, placeholder: "Écris à Claude…", "aria-label": "Message", enterkeyhint: "send",
      autocapitalize: "sentences", autocomplete: "off" });
    this.thumbs = el("div", { class: "thumbs" });
    this.quoteBar = el("div", { class: "quote-bar", hidden: true });
    this.fileInput = el("input", { type: "file", accept: "image/*", multiple: true, hidden: true });
    this.rights = el("select", { "aria-label": "Droits" }, ...RIGHTS.map(([v, t]) => el("option", { value: v }, t)));
    this.effort = el("select", { "aria-label": "Effort" }, ...EFFORTS.map(([v, t]) => el("option", { value: v }, t)));
    this.model = el("select", { "aria-label": "Modèle" }, el("option", { value: "" }, "Modèle par défaut"));
    this.context = el("span", { class: "subtle context" }, "");
    this.summary = el("span", { class: "opt-summary subtle" }, "");
    for (const sel of [this.model, this.effort, this.rights]) sel.disabled = true;     // jusqu'aux vraies options
    this.bar = el("div", { class: "chat-bar", hidden: true }, this.model, this.effort, this.rights);
    this.optBtn = el("button", { type: "button", class: "small flat opt", "aria-expanded": "false", onclick: () => this.toggleOptions() },
      el("strong", {}, "Options"), this.summary);

    const send = el("button", { class: "primary send", type: "submit", "aria-label": "Envoyer" },
      el("span", { class: "send-icon", "aria-hidden": "true" }, "➤"), el("span", { class: "send-label" }, "Envoyer"));
    const attach = el("button", { class: "flat icon", type: "button", "aria-label": "Joindre une image", title: "Joindre une image",
      onclick: () => this.fileInput.click() }, "📎");
    const saved = el("button", { class: "flat icon", type: "button", "aria-label": "Messages enregistrés", title: "Messages enregistrés",
      onclick: () => openSavedSheet({ api: this.api, cwd: this.cwd, currentText: () => this.input.value,
        onInsert: (t) => this.insert(t) }) }, "★");
    this.form = el("form", { class: "composer" },
      this.working, this.todos, this.thumbs, this.quoteBar,
      el("div", { class: "composer-row" }, attach, saved, this.input, send, this.fileInput),
      this.bar,
      el("div", { class: "composer-foot" }, this.optBtn, this.context, this.stopBtn));
    this.form.addEventListener("submit", (e) => { e.preventDefault(); this.send(); });
    this.completer = new Completer({ input: this.input, host: this.form, onChange: () => this.edited(),
      sources: { commands: async () => (await this.workInfo()).commands, files: async () => (await this.fileIndex()).list } });
    this.input.addEventListener("keydown", (e) => this.keydown(e));
    this.input.addEventListener("input", () => this.edited());
    this.input.addEventListener("paste", (e) => {
      const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
      if (files.length) { e.preventDefault(); this.addImages(files); }
    });
    this.fileInput.addEventListener("change", () => { this.addImages([...this.fileInput.files]); this.fileInput.value = ""; });
    for (const s of [this.rights, this.effort, this.model]) s.addEventListener("change", () => this.pushOptions());

    this.findbar = new FindBar({ blocks: () => [...this.thread.querySelectorAll(".msg, .tool")],
      ensureAll: () => this.loadFullHistory(), onClose: () => this.input.focus(),
      onJump: () => { this.follow = false; } });   // on lit un résultat : ne pas repartir en bas
    this.drawer = el("aside", { class: "drawer", hidden: true });
    resizable(this.drawer, "drawer", { min: 240, max: 1000 });
    this.menu = el("div", { class: "chat-menu", hidden: true });
    const items = [
      { label: "Fichiers", run: () => this.openDrawer("files"), phone: true },
      { label: "Feuille de route", run: () => this.openDrawer("roadmap") },
      { label: "Git", run: () => this.openDrawer("git") },
      { label: "Changements", run: () => this.openDrawer("changes") },
      { label: "Étiquettes", run: () => this.openDrawer("tags") },
      { label: "Chercher", run: () => this.findbar.show() },
    ];
    const actions = el("div", { class: "chat-actions" });
    for (const it of items) {
      actions.append(el("button", { type: "button", class: `small flat act${it.phone ? "" : " desk-only"}`, onclick: it.run }, it.label));
      if (!it.phone) this.menu.append(el("button", { type: "button", class: "menu-item", onclick: () => { this.menu.hidden = true; it.run(); } }, it.label));
    }
    actions.append(el("button", { type: "button", class: "small flat act phone-only", "aria-haspopup": "true",
      onclick: () => { this.menu.hidden = !this.menu.hidden; } }, "Plus"));
    this.node = el("section", { class: "chat" },
      el("header", { class: "chat-head" },
        el("button", { type: "button", class: "flat back-chat phone-only", "aria-label": "Retour aux sessions",
          onclick: () => this.host?.back?.() }, "←"),
        el("div", { class: "chat-title grow" }, el("strong", { class: "title" }, title || cwd),
          el("div", { class: "chat-sub" }, this.state, el("span", { class: "subtle cwd" }, cwd))),
        actions, this.menu),
      this.findbar.node,
      el("div", { class: "chat-body" }, this.drawer, el("div", { class: "chat-main" }, this.agentBar, this.agentHistory, el("div", { class: "thread-wrap" }, this.thread, this.downBtn), this.form)));
    this.node.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "f") { e.preventDefault(); this.findbar.show(); }
    });
    const outside = (e) => { if (!this.menu.hidden && !this.menu.contains(e.target) && !e.target.closest?.(".chat-actions")) this.menu.hidden = true; };
    document.addEventListener("click", outside);
    this.offs.push(() => document.removeEventListener("click", outside));
    const selected = () => this.selectionChanged();
    document.addEventListener("selectionchange", selected);
    this.offs.push(() => document.removeEventListener("selectionchange", selected));
    root.append(this.node);

    this.input.value = this.loadDraft();
    this.loadQuote();
    this.grow();
    this.updateSummary();
    if (options) this.applyOptions(options);
    this.offs.push(api.on("chat.event", (d) => { if (d.chat_id === this.chatId) this.receive(d); }));
    this.offs.push(api.on("chat.tags", (d) => { if (d.session_id && d.session_id === this.sessionId) this.applyTag(d.msg_id, d.entry); }));
    this.loadTags();
    this.offs.push(api.on("shell.done", (d) => { if (d.chat_id === this.chatId) this.shellDone(d); }));
    this.offs.push(api.on("reconnected", () => { this.attach(); this.pollShells(); }));
    this.attach();                                   // l'historique suit le premier rattachement
  }

  setTitle(title) { const n = this.node.querySelector(".chat-title .title"); if (n) n.textContent = title; }

  destroy() { this.dead = true; clearTimeout(this.ctxTimer); for (const off of this.offs) off(); for (const { panel } of this.panels.values()) panel.destroy?.(); this.node.remove(); }

  // ---- saisie -----------------------------------------------------------------------------

  keydown(e) {
    if (this.completer.key(e)) return;
    const phone = matchMedia("(max-width: 719px)").matches;
    if (e.key === "Enter" && !e.shiftKey && !phone) { e.preventDefault(); this.send(); return; }
    if (e.key === "Tab" && e.shiftKey) {            // comme au bureau : Maj+Tab change les droits
      e.preventDefault();
      if (!this.optionsReady) return;
      this.rights.value = CYCLE_RIGHTS[(CYCLE_RIGHTS.indexOf(this.rights.value) + 1) % CYCLE_RIGHTS.length];   // « Tout autoriser » (hors liste) repart de « Demander »
      this.pushOptions();
      toast(`Droits : ${this.rights.selectedOptions[0].textContent}`);
      return;
    }
    if (e.key === "Escape" && this.quote) { e.preventDefault(); this.clearQuote(); return; }
    if (e.key === "Escape" && !this.input.value && !this.stopBtn.hidden) this.call("chat.interrupt");
  }

  edited() {
    this.grow();
    clearTimeout(this.draftTimer);
    this.draftTimer = setTimeout(() => this.saveDraft(), 300);
  }

  loadDraft() {
    try { return localStorage.getItem(this.draftKey) || ""; } catch { return ""; }
  }

  saveDraft() {
    try {
      if (this.input.value) localStorage.setItem(this.draftKey, this.input.value);
      else localStorage.removeItem(this.draftKey);
    } catch { /* stockage plein ou refusé : le brouillon est un confort */ }
  }

  // ---- répondre en citant un message -------------------------------------------------------

  // Clic dans le fil : déplie une citation, ou montre les actions du message touché (écran
  // tactile ; à la souris elles apparaissent au survol, un clic ne change rien).
  pick(e) {
    const t = e.target;
    const quoted = t.closest?.(".quoted");
    if (quoted) { if (!t.closest?.("a")) quoted.classList.toggle("open"); return; }   // un lien s'ouvre, sans déplier
    if (!matchMedia("(hover: none)").matches) return;
    if (t.closest?.("a, button, summary, input, select, textarea, label, .msg-actions")) return;
    const msg = t.closest?.(".msg");
    if (msg && selectionIn(msg)) return;             // une sélection de texte en cours n'est pas un choix
    this.showActions(msg, !msg?.classList.contains("picked"));
  }

  // Ouvre la rangée d'actions de `msg` (et ferme celle des autres) ; `on` faux : la referme.
  showActions(msg, on = true) {
    for (const m of this.thread.querySelectorAll(".msg.picked")) if (m !== msg || !on) m.classList.remove("picked");
    if (!msg || !on || msg.classList.contains("picked")) return;
    msg.classList.add("picked");
    // la rangée s'ouvre sous le message : sous le dernier, elle serait hors de l'écran
    msg.querySelector(".msg-actions")?.scrollIntoView({ block: "nearest" });
  }

  // Écran tactile : du texte sélectionné dans un message ouvre sa rangée d'actions, pour pouvoir
  // répondre en ne citant que ce passage (toucher le message déferait la sélection).
  selectionChanged() {
    if (!matchMedia("(hover: none)").matches) return;
    const sel = window.getSelection?.();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const where = sel.getRangeAt(0).commonAncestorContainer;
    const msg = (where?.nodeType === 1 ? where : where?.parentElement)?.closest?.(".msg");
    if (msg && this.thread.contains(msg)) this.showActions(msg);
  }

  replyTo(msg) {
    const q = quoteOf(msg);
    if (!q) return;
    msg.classList.remove("picked");
    this.setQuote(q);
    this.input.focus();
  }

  setQuote(quote, save = true) {
    this.quote = quote;
    clear(this.quoteBar).append(
      el("div", { class: "quote-bar-text", dataset: { author: quote.author === CLAUDE ? "Réponse à Claude" : "Réponse à ton message" } },
        oneLine(quote.text, 200)),
      el("button", { type: "button", class: "flat icon", "aria-label": "Annuler la citation", title: "Annuler la citation",
        onclick: () => { this.clearQuote(); this.input.focus(); } }, "×"));
    this.quoteBar.hidden = false;
    if (save) this.saveQuote();
  }

  clearQuote() {
    this.quote = null;
    clear(this.quoteBar);
    this.quoteBar.hidden = true;
    this.saveQuote();
  }

  // Comme le brouillon : la citation en cours survit à un rechargement de la page.
  saveQuote() {
    try {
      if (this.quote) localStorage.setItem(this.quoteKey, JSON.stringify(this.quote));
      else localStorage.removeItem(this.quoteKey);
    } catch { /* stockage plein ou refusé : un confort */ }
  }

  loadQuote() {
    try {
      const q = JSON.parse(localStorage.getItem(this.quoteKey) || "null");
      if (q && typeof q.text === "string" && q.text && [CLAUDE, ME].includes(q.author)) this.setQuote({ author: q.author, text: q.text }, false);
    } catch { /* citation illisible : ignorée */ }
  }

  insert(text) {
    const at = this.input.selectionStart ?? this.input.value.length;
    this.input.value = this.input.value.slice(0, at) + text + this.input.value.slice(this.input.selectionEnd ?? at);
    this.input.focus();
    this.edited();
  }

  grow() {
    this.input.style.height = "auto";
    this.input.style.height = `${Math.min(this.input.scrollHeight, 220)}px`;
  }

  toggleOptions() {
    this.bar.hidden = !this.bar.hidden;
    this.optBtn.setAttribute("aria-expanded", String(!this.bar.hidden));
  }

  updateSummary() {
    const label = (sel) => sel.selectedOptions[0]?.textContent || "";
    const parts = [this.model.value ? label(this.model) : "", this.effort.value ? label(this.effort) : "", label(this.rights)];
    this.summary.textContent = parts.filter(Boolean).join(" · ");
  }

  // Remplit les trois listes avec les options réelles du chat (C2) ; n'écrase rien tant qu'elles manquent.
  applyOptions(o) {
    if (!o || typeof o !== "object") return;
    this.opts = { ...(this.opts || {}), ...o };
    const set = (sel, value) => {
      const v = value || "";
      if (v && ![...sel.options].some((op) => op.value === v)) sel.append(el("option", { value: v }, v));
      sel.value = v;
    };
    if ("model" in o) set(this.model, o.model);
    if ("effort" in o) set(this.effort, o.effort);
    if ("rights" in o) set(this.rights, o.rights === "default" ? "manual" : o.rights || "manual");
    this.markReady();
  }

  markReady() {
    this.optionsReady = true;
    for (const sel of [this.model, this.effort, this.rights]) sel.disabled = false;
    this.updateSummary();
  }

  pushOptions() {
    this.updateSummary();
    if (!this.optionsReady) return;
    this.opts = { ...(this.opts || {}), model: this.model.value || null, effort: this.effort.value || null, rights: this.rights.value };
    this.call("chat.options", { options: this.opts });
  }

  async addImages(files) {
    for (const f of files.slice(0, 5)) {
      if (f.size > 5 * 1024 * 1024) { this.notice(`${f.name} : image trop lourde (5 Mo au plus).`, "warning"); continue; }
      const img = await readImage(f);
      this.images.push(img);
      const thumb = el("img", { alt: f.name, class: "thumb", src: `data:${img.media_type};base64,${img.data}` });
      thumb.addEventListener("click", () => { this.images.splice(this.images.indexOf(img), 1); thumb.remove(); });
      this.thumbs.append(thumb);
    }
  }

  // Texte préparé ailleurs (feuille de route, bouton « Compacter »…) : envoyé sans toucher à la saisie.
  sendText(text) {
    return this.deliver(text, [], () => this.sendText(text));
  }

  // Envoie au pont ; le texte et les images ne sont retirés de la saisie qu'après sa réponse.
  // `quote` ({ author, text }) : message cité, placé en tête du texte envoyé (chat-quote.js).
  async deliver(text, images = [], retry = null, quote = null) {
    let r = null;
    const nonce = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    const uuid = newUuid();                          // identifiant du message dans le journal (étiquettes)
    (this.ownSent ||= new Set()).add(nonce);        // l'écho du pont n'est pas affiché deux fois
    // `/clear`, `/compact`… : la CLI ne les reconnaît qu'en tête du message, seuls ; sorties `!`
    // et citation attendent le prochain message.
    const command = isSlashCommand(text) && !images.length;
    if (command) { text = text.trim(); quote = null; }
    const notes = command ? "" : this.shellNotes.join("");
    const shown = quote ? compose(quote.author, quote.text, text) : text;
    const sent = quote ? compose(quote.author, quote.text, notes + text) : notes + text;
    try { r = await this.api.call("chat.send", { chat_id: this.chatId, text: sent, images, shown, nonce, uuid }); } catch (e) {
      this.ownSent.delete(nonce);
      this.sendFailed(e.message, retry);
      return false;
    }
    if (!r || !r.ok) { this.sendFailed("Claude n'a pas pu démarrer.", retry); return false; }
    if (!command) this.shellNotes = [];
    this.userBubble(shown, images.length, r.uuid || "");      // ancien pont : pas d'identifiant
    return true;
  }

  sendFailed(message, retry) {
    toast(`Le message n'est pas parti : ${message}`, { kind: "error", action: retry ? { label: "Réessayer", run: retry } : null });
  }

  async send() {
    const text = this.input.value.trim();
    if ((!text && !this.images.length) || this.sending) return;
    if (text.startsWith("!") && text.length > 1 && !this.images.length) {      // commande du shell, pas pour Claude
      this.input.value = "";
      this.edited();
      this.runShell(text.slice(1).trim());
      return;
    }
    if (this.cacheExpired && !(isSlashCommand(text) && !this.images.length)) {
      // cache expiré : ce message relira tout le contexte au prix fort
      const choice = await choiceSheet({ title: "Cache expiré",
        body: `Ce message relira ${fmtTokens(this.cacheExpired.context)} tokens au prix fort.`,
        choices: [{ value: "compact", label: "Compacter d'abord", primary: true }, { value: "send", label: "Envoyer quand même" }] });
      if (choice === "compact") { this.sendText("/compact"); return; }   // le message reste dans la saisie
      if (choice !== "send") return;
      this.cacheExpired = null;
    }
    this.sending = true;
    try {
      const images = [...this.images];
      const quote = this.quote;
      if (await this.deliver(text, images, () => this.send(), quote)) {
        this.images = [];
        clear(this.thumbs);
        if (this.quote === quote && !(isSlashCommand(text) && !images.length)) this.clearQuote();   // la citation attend
        if (this.input.value.trim() === text) {
          this.input.value = "";
          this.grow();
          this.saveDraft();
        }
      }
    } finally { this.sending = false; }
  }

  // ---- commande `!` --------------------------------------------------------------------

  async runShell(command) {
    if (!command) return;
    const out = el("pre", { class: "tool-result", hidden: true });
    const status = el("span", { class: "subtle" }, "en cours…");
    const stop = el("button", { type: "button", class: "small danger" }, "Arrêter");
    const card = el("details", { class: "tool shell", open: true },
      el("summary", {}, el("strong", {}, "Commande"), " ", el("span", { class: "subtle path" }, `$ ${command}`), status), out,
      el("div", { class: "tool-actions" }, stop));
    Object.assign(card, { out, status, stop });
    this.append(card);
    let r;
    try { r = await this.api.call("shell.run", { chat_id: this.chatId, command }); } catch (e) {
      this.shellFinish({ card, command }, { code: 127, output: e.message, truncated: false });
      return;
    }
    const entry = { card, command };
    stop.addEventListener("click", () => this.api.call("shell.stop", { run_id: r.run_id }).catch(() => {}));
    this.shells.set(r.run_id, entry);
    const early = this.shellEarly.get(r.run_id);
    if (early) this.shellDone(early);
  }

  shellDone(d) {
    const entry = this.shells.get(d.run_id);
    if (!entry) { this.shellEarly.set(d.run_id, d); return; }
    this.shells.delete(d.run_id);
    this.shellEarly.delete(d.run_id);
    this.shellFinish(entry, d);
  }

  shellFinish({ card, command }, d) {
    card.stop.remove();
    card.out.hidden = false;
    card.out.textContent = d.output + (d.truncated ? "\n[sortie tronquée]" : "") || "(aucune sortie)";
    card.status.textContent = d.code === 0 ? "terminé" : `code ${d.code}`;
    card.classList.add(d.code === 0 ? "done" : "error");
    const shown = d.output + (d.truncated ? "\n[sortie tronquée]" : "");
    this.shellNotes.push(`J'ai lancé \`${command}\` dans le dossier du projet (code ${d.code}) :\n\`\`\`\n${shown}\n\`\`\`\n\n`);
  }

  async pollShells() {                       // après une coupure, une fin de commande a pu être manquée
    for (const run_id of [...this.shells.keys()]) {
      try { const r = await this.api.call("shell.poll", { run_id }); if (r.done) this.shellDone(r); } catch { /* sera retenté */ }
    }
  }

  // ---- commandes, fichiers, contexte -----------------------------------------------------

  workInfo() {
    if (!this.workP) {
      this.workP = this.api.call("work.commands", { chat_id: this.chatId }).then((r) => {
        if (!r.commands.length) this.workP = null;       // Hello pas encore reçu : on redemandera
        return r;
      }).catch(() => { this.workP = null; return { commands: [], context: { enabled: false, threshold_tokens: 0 } }; });
    }
    return this.workP;
  }

  fileIndex() {
    if (!this.filesP) {
      this.filesP = this.api.call("work.files", { chat_id: this.chatId }).then((r) => ({ list: r.files, set: new Set(r.files) }))
        .catch(() => { this.filesP = null; return { list: [], set: new Set() }; });
    }
    return this.filesP;
  }

  async checkContext(ev) {
    const { heavy, gain } = contextAlert(ev, (await this.workInfo()).context, this.heavy);
    if (gain !== null) {                 // franchissement du seuil vers le haut : une seule alerte
      this.notice(`Contexte lourd : ${fr(ev.total)} jetons. Compacter libérerait environ ${fr(gain)} jetons (estimation).`, "warning",
        { label: "Compacter", run: () => this.sendText("/compact") });
    }
    this.heavy = heavy;
  }

  // « Contexte N % » n'arrive qu'en réponse à chat.context : on le demande après chaque tour.
  requestContext() {
    clearTimeout(this.ctxTimer);
    this.ctxTimer = setTimeout(() => {
      if (!this.dead && !this.stoppedCard) this.api.call("chat.context", { chat_id: this.chatId }).catch(() => {});
    }, 400);
  }

  // ---- étiquettes ---------------------------------------------------------------------------

  // Conversation connue (ouverture, Init, rattachement) : une reprise peut en changer, ses
  // étiquettes sont alors relues.
  setSession(id) {
    this.sessionId = this.seenSession = id;
    if (id && id !== this.tagsSession) this.loadTags();
  }

  async loadTags() {
    const sid = this.sessionId;
    if (!sid || this.dead) return;
    this.tagsSession = sid;
    let r;
    try { r = await this.api.call("chat.tags", { session_id: sid }); } catch { return; }    // ancien pont : pas d'étiquettes
    if (this.sessionId !== sid || this.dead) return;
    this.tagMap = r.messages || {};
    this.knownTags = r.known || [];
    for (const n of this.thread.querySelectorAll(".msg")) this.paintTags(n);
    this.panels.get("tags")?.panel.refresh();
  }

  // Pastilles des étiquettes du message, entre son contenu et ses actions ; rend le nœud.
  paintTags(node) {
    node.tagsNode?.remove();
    node.tagsNode = tagChips(this.tagMap[node.msgId]?.tags, (tag) => this.showTag(tag));
    if (node.tagsNode) node.insertBefore(node.tagsNode, [...node.children].find((c) => c.classList.contains("msg-actions")) || null);
    return node;
  }

  applyTag(msgId, entry) {
    if (entry) {
      this.tagMap[msgId] = entry;
      const have = new Set(this.knownTags.map((t) => t.toLocaleLowerCase("fr")));
      this.knownTags.push(...entry.tags.filter((t) => !have.has(t.toLocaleLowerCase("fr"))));
    } else delete this.tagMap[msgId];
    for (const n of this.thread.querySelectorAll(".msg")) if (n.msgId === msgId) this.paintTags(n);
    this.panels.get("tags")?.panel.refresh();
  }

  async tagMessage(msg) {
    msg.classList.remove("picked");
    if (!this.sessionId || !msg.msgId) {
      toast("Ce message ne peut pas encore être étiqueté : attends que Claude ait commencé la conversation.", { kind: "error" });
      return;
    }
    const text = msg.author === ME ? sourceText(msg.raw) : msg.raw;
    const tags = await openTagSheet({ current: this.tagMap[msg.msgId]?.tags || [], known: this.knownTags, excerpt: oneLine(text, 160) });
    if (tags === null || this.dead) return;
    const sid = this.sessionId;
    try {
      const r = await this.api.call("chat.tag", { session_id: sid, msg_id: msg.msgId, tags, text,
        role: msg.author === ME ? "user" : "assistant" });
      if (this.sessionId === sid) this.applyTag(msg.msgId, r.entry);
    } catch (e) { toast(`Étiquettes non enregistrées : ${e.message}`, { kind: "error" }); }
  }

  showTag(tag) {
    if (this.drawer.hidden || this.drawer.dataset.kind !== "tags") { this.drawer.hidden = true; this.openDrawer("tags"); }
    this.panels.get("tags")?.panel.show(tag);
  }

  // Ramène au message étiqueté ; s'il n'est pas dans le fil (seuls les derniers messages y sont),
  // charge d'abord tout le journal.
  async jumpTo(msgId) {
    const find = () => [...this.thread.querySelectorAll(".msg")].find((n) => n.msgId === msgId);
    let node = find();
    if (!node) { await this.loadFullHistory(); node = find(); }
    if (!node) { toast("Ce message n'est plus dans le fil (conversation compactée ou reprise ailleurs).", { kind: "error" }); return; }
    if (window.matchMedia?.("(max-width: 719px)").matches) this.drawer.hidden = true;   // téléphone : le volet couvre le fil
    this.follow = false;
    node.scrollIntoView?.({ block: "center", behavior: "smooth" });
    node.classList.remove("flash");
    void node.offsetWidth;
    node.classList.add("flash");
    setTimeout(() => node.classList.remove("flash"), 1600);
  }

  // ---- volets ------------------------------------------------------------------------------

  // Un panneau par type, gardé d'une ouverture à l'autre : un fichier en cours d'édition ou un message de
  // commit tapé survivent à la fermeture du volet. Les données (Git, feuille de route, changements) sont relues.
  openDrawer(kind) {
    if (!this.drawer.hidden && this.drawer.dataset.kind === kind) { this.drawer.hidden = true; return null; }
    if (!this.drawerBody) {
      this.drawerTitle = el("strong", { class: "grow" }, "");
      this.drawerBody = el("div", { class: "drawer-body" });
      this.drawer.append(el("div", { class: "drawer-head" }, this.drawerTitle,
        el("button", { type: "button", class: "small flat", "aria-label": "Fermer", onclick: () => { this.drawer.hidden = true; } }, "×")),
        this.drawerBody);
    }
    this.drawer.dataset.kind = kind;
    this.drawer.hidden = false;
    this.drawerTitle.textContent = DRAWER_TITLES[kind];
    for (const [k, p] of this.panels) p.holder.hidden = k !== kind;
    const known = this.panels.get(kind);
    if (known) {
      known.panel.refresh?.();
      if (kind === "roadmap" || kind === "changes") known.panel.load();
      return known.panel;
    }
    const holder = el("div", { class: `drawer-panel drawer-${kind}` });
    this.drawerBody.append(holder);
    let panel;
    if (kind === "files") panel = new FilesPanel(holder, this.api, this.cwd);
    else if (kind === "git") panel = new GitPanel(holder, this.api, this.cwd);
    else if (kind === "changes") panel = new ChangesPanel(holder, this.api, this.chatId, this.cwd, { openFile: (p) => this.openFile(p), changed: () => { this.filesP = null; } });
    else if (kind === "tags") panel = new TagsPanel(holder, { messages: () => this.tagMap, jump: (id) => this.jumpTo(id) });
    else panel = new RoadmapPanel(holder, this.api, this.cwd, { send: (text) => this.sendText(text) });
    this.panels.set(kind, { holder, panel });
    return panel;
  }

  // Fichier d'un projet cité dans le chat ou dans un diff : volet Fichiers, à la ligne `line`.
  async openFile(path, { line = null } = {}) {
    let known = this.panels.get("files");
    if (this.drawer.hidden || this.drawer.dataset.kind !== "files") { this.drawer.hidden = true; this.openDrawer("files"); known = this.panels.get("files"); }
    return known.panel.openFile(path, { line });
  }

  async call(method, params = {}) {
    try { return await this.api.call(method, { chat_id: this.chatId, ...params }); } catch (e) {
      this.notice(e.message, "error");
      return null;
    }
  }

  // Les rattachements se font l'un après l'autre (ouverture puis « reconnected » rapprochés).
  attach() {
    this.attachP = (this.attachP || Promise.resolve()).then(() => this.doAttach(), () => this.doAttach());
    return this.attachP;
  }

  async fetchAttach(since) {
    try { return await this.api.call("chat.attach", { chat_id: this.chatId, since }); } catch (e) {
      if (e.code === "introuvable") this.gone();
      else if (e.code !== "hors_ligne") this.notice(e.message, "error");
      return null;
    }
  }

  async doAttach() {
    if (this.dead) return;
    let r = await this.fetchAttach(this.seq);
    if (!r) return;
    // Le pont a redémarré (ou ce numéro ne lui dit rien) : on repart de zéro au lieu de jeter ses réponses.
    const behind = typeof r.seq === "number" && r.seq < this.seq;
    const other = Boolean(r.session_id && this.seenSession && r.session_id !== this.seenSession);   // vu par le pont, pas celui d'ouverture (une reprise peut en changer)
    if (behind || other) {
      this.resetThread(other);
      r = await this.fetchAttach(0);
      if (!r) return;
    }
    if (r.session_id) this.setSession(r.session_id);
    if (r.options) this.applyOptions(r.options); else if (!this.optionsReady) this.markReady();   // ancien pont : comme avant
    this.stoppedCard?.remove();
    this.stoppedCard = null;
    for (const item of r.events || []) this.receive(item);
    this.setState(r.state);
    this.startHistory(r.history_before);
  }

  // Journal de la conversation jusqu'à `before` (heure depuis laquelle le tampon du pont a tout), une
  // fois : ce qui suit est déjà arrivé par chat.attach. Sans `before` (chat perdu) : tout le journal.
  startHistory(before) {
    const h = this.history;
    if (!h || h.started) return;
    h.started = true;
    h.before = typeof before === "number" ? before : undefined;
    this.loadHistory();
  }

  resetThread(newSession) {
    this.seq = 0;
    this.seenSession = null;
    for (const e of this.texts.values()) clearTimeout(e.timer);
    for (const m of [this.texts, this.tools, this.perms, this.shells, this.shellEarly]) m.clear();
    this.showAgent(null);
    for (const a of this.agents.values()) { a.view.remove(); a.pill.remove(); }
    this.agents.clear();
    this.agentBar.hidden = true;
    this.agentHistory.hidden = true;
    clear(this.agentHistory);
    clear(this.thread);
    this.setTodos([]);
    this.heavy = false;
    this.context.textContent = "";
    this.contextPct = undefined;
    this.cacheExpired = null;
    if (newSession) this.history = null;
    else if (this.history) this.history = { path: this.history.path, loaded: 0, full: false };   // relu après chat.attach
  }

  // Le pont ne connaît plus ce chat (redémarrage après une mise à jour) : on le dit, et on propose de
  // reprendre la conversation si on connaît son identifiant.
  gone() {
    this.startHistory();                             // plus de tampon : tout le journal
    if (this.stoppedCard) return;
    this.setState("stopped");
    const resume = this.sessionId && this.host?.resume
      ? el("button", { type: "button", class: "primary", onclick: () => this.host.resume(this) }, "Reprendre la conversation") : null;
    this.stoppedCard = this.append(el("div", { class: "notice warning stopped-card", role: "alert" },
      el("strong", {}, "Ce chat s'est arrêté"),
      el("span", {}, resume ? "Le pont a redémarré : Claude n'est plus lancé pour cette conversation." : "Le pont a redémarré et on ne retrouve pas sa conversation : ferme cet onglet."),
      resume));
    this.host?.stopped?.(this);
  }

  // ---- fil ----------------------------------------------------------------------------

  toBottom() {
    this.follow = true;
    this.thread.scrollTop = this.thread.scrollHeight;
    this.lastTop = this.thread.scrollTop;
    this.downBtn.hidden = true;
  }

  // Seul un geste vers le haut détache du bas. « scroll » arrive aussi quand le fil grandit ou
  // que sa zone rétrécit (clavier du téléphone, liste des tâches) sans que personne ait bougé :
  // s'y fier décrochait le suivi en pleine réponse.
  scrolled() {
    const top = this.thread.scrollTop;
    if (this.stuck()) this.follow = true;
    else if (top < this.lastTop) this.follow = false;
    this.lastTop = top;
    this.offerDown();
  }

  offerDown() { this.downBtn.hidden = this.stuck(); }

  // Tout ce qui change la hauteur sans passer par append() (texte rendu après coup, résultat
  // d'un outil, image chargée, zone de saisie qui grandit) ramène en bas tant qu'on suit.
  restick() { if (this.follow && !this.touching) this.toBottom(); else this.offerDown(); }

  watchThread() {
    const t = this.thread;
    const again = () => this.restick();
    t.addEventListener("scroll", () => this.scrolled(), { passive: true });
    t.addEventListener("wheel", (e) => { if (e.deltaY < 0) this.follow = false; }, { passive: true });
    t.addEventListener("touchstart", () => { this.touching = true; }, { passive: true });
    for (const end of ["touchend", "touchcancel"]) t.addEventListener(end, () => { this.touching = false; }, { passive: true });
    t.addEventListener("load", again, true);
    if (typeof MutationObserver === "function") {
      const mo = new MutationObserver(again);
      mo.observe(t, { childList: true, subtree: true, characterData: true });
      this.offs.push(() => mo.disconnect());
    }
    if (typeof ResizeObserver === "function") {
      const ro = new ResizeObserver(again);
      ro.observe(t);
      this.offs.push(() => ro.disconnect());
    }
  }

  stuck() { return this.thread.scrollHeight - this.thread.scrollTop - this.thread.clientHeight < 80; }

  // `into` : la vue d'un sous-agent ; sans lui, le fil de la conversation.
  append(node, into = null) {
    const box = into || this.thread;
    const stick = into ? box.scrollHeight - box.scrollTop - box.clientHeight < 80 : this.follow || this.stuck();
    const last = box.lastElementChild;
    if (isToolNode(node) && last?.classList.contains("tool-group")) { last.body.append(node); refreshGroup(last); }
    else if (isToolNode(node) && isToolNode(last)) { const g = toolGroup(); last.replaceWith(g); g.body.append(last, node); refreshGroup(g); }
    else box.append(node);
    if (!stick) return node;
    if (into) box.scrollTop = box.scrollHeight; else this.toBottom();
    return node;
  }

  // Actions qui se suivent (commandes, lectures, modifications) : une ligne repliable.
  regroup() {
    let run = [];
    const flush = () => {
      if (run.length >= 2) { const g = toolGroup(); run[0].before(g); g.body.append(...run); refreshGroup(g); }
      run = [];
    };
    for (const n of [...this.thread.children]) { if (isToolNode(n)) run.push(n); else flush(); }
    flush();
  }

  userBubble(text, nImages = 0, msgId = "") {
    this.showAgent(null);                            // on écrit à Claude, pas au sous-agent
    this.follow = true;                              // nouveau message : on revient en bas
    return this.append(this.paintTags(userNode(text, nImages, this.msgActions, this.renderQuote, msgId)));
  }

  // Après `/clear` : les messages d'avant restent lisibles (et citables) mais grisés, sous un
  // séparateur ; Claude ne les voit plus.
  // `auto` : effacée par Claude en fin de sujet (`ccs chat effacer`).
  newConversation(auto = false) {
    for (const node of this.thread.children) node.classList.add("before-reset");
    this.append(el("div", { class: "reset-sep", role: "separator" },
      el("span", {}, auto ? "Sujet terminé : Claude a effacé la conversation — il ne voit plus les messages au-dessus"
        : "Nouvelle conversation — Claude ne voit plus les messages au-dessus")));
  }

  // `action` : { label, run } (ou une liste) ajoute des boutons à la note (« Compacter »…).
  notice(text, kind = "info", action = null) {
    const actions = Array.isArray(action) ? action : action ? [action] : [];
    return this.append(el("div", { class: `notice ${kind}` }, el("span", {}, text),
      ...actions.map((a) => el("button", { type: "button", class: "small", onclick: a.run }, a.label))));
  }

  // « Contexte N % · 120 k », coloré selon le seuil du contexte lourd (réglage du pont).
  async showContext(percentage, total) {
    if (percentage !== null && percentage !== undefined) this.contextPct = percentage;
    const tokens = total ? fmtTokens(total) : "";
    this.context.textContent = this.contextPct !== undefined
      ? `Contexte ${this.contextPct} %${tokens ? ` · ${tokens}` : ""}` : `Contexte ${tokens}`;
    const cfg = (await this.workInfo().catch(() => ({})))?.context || {};
    this.context.classList.remove("ctx-ok", "ctx-warn", "ctx-crit");
    if (total) this.context.classList.add(`ctx-${contextLevel(total, cfg.threshold_tokens)}`);
  }

  async render(node, markdown) {
    try {
      const r = await this.api.call("chat.render", { markdown });
      const follow = this.follow;
      setHtml(node, r.html);
      addCopyButtons(node);
      linkify(node, this.cwd, (await this.fileIndex()).set, (p, o) => this.openFile(p, o));
      if (follow) this.toBottom();
    } catch { if (!node.firstChild) node.textContent = markdown; }
  }

  // Passage cité dans une bulle : rendu comme une réponse (Markdown), sans boutons ni liens de
  // fichiers ; si le pont ne répond pas, le texte tel quel reste affiché.
  async quoteHtml(node, markdown) {
    try {
      const r = await this.api.call("chat.render", { markdown });
      const follow = this.follow;
      setHtml(node, r.html);
      node.classList.add("rendered");
      if (follow) this.toBottom();
    } catch { /* texte brut gardé */ }
  }

  assistant(msgId, text, final) {
    let entry = this.texts.get(msgId);
    if (!entry) {
      entry = { node: this.append(this.paintTags(claudeNode(this.msgActions, msgId))), text: "", timer: null };
      this.texts.set(msgId, entry);
    }
    entry.text = entry.node.raw = text;
    clearTimeout(entry.timer);
    if (final) this.render(entry.node.content, text);
    else entry.timer = setTimeout(() => this.render(entry.node.content, entry.text), 250);
  }

  // `into` : la vue du sous-agent qui a lancé l'outil (ses cartes ne sont pas décalées).
  toolCard(ev, into = null) {
    if (!into && AGENT_TOOLS.includes(ev.name)) return this.agentCard(ev);
    const name = TOOL_LABELS[ev.name] || ev.name;
    const nested = Boolean(ev.parent_id) && !into;
    const diffs = editDiffs(ev.name, ev.input);
    let card;
    if (diffs) card = diffCard({ label: name, diffs, nested, onOpen: (p) => this.openFile(p) });
    else {
      const body = el("pre", { class: "tool-body" }, JSON.stringify(ev.input || {}, null, 2));
      const result = el("pre", { class: "tool-result", hidden: true });
      card = el("details", { class: `tool${nested ? " nested" : ""}` },
        el("summary", {}, el("strong", {}, name), " ", el("span", { class: "subtle" }, target(ev.name, ev.input))),
        body, result);
      card.result = result;
    }
    this.tools.set(ev.tool_id, card);
    return this.append(card, into);
  }

  toolResult(ev) {
    const card = this.tools.get(ev.tool_id);
    if (!card) return;
    if (card.result) { card.result.hidden = false; card.result.textContent = ev.text; }
    card.classList.toggle("error", ev.is_error);
    card.classList.add("done");
  }

  // ---- sous-agents ------------------------------------------------------------------------
  // Comme sur le bureau : la carte du sous-agent reste dans le fil avec « Voir », son travail
  // (textes, outils) va dans sa vue en lecture seule, et sa pastille reste au-dessus du fil
  // tant qu'il travaille ou qu'on le regarde.

  agentCard(ev) {
    const id = ev.tool_id;
    const name = String(ev.input?.description || ev.input?.subagent_type || "Sous-agent").slice(0, 60);
    const background = Boolean(ev.input?.run_in_background);
    const status = el("span", { class: "subtle agent-status" }, background ? "en arrière-plan…" : "au travail…");
    const result = el("pre", { class: "tool-result", hidden: true });
    const card = el("div", { class: "agent-card" },
      el("div", { class: "agent-card-head" },
        el("span", { class: "agent-card-title" }, el("strong", {}, "Sous-agent"), " ", name), status,
        el("button", { type: "button", class: "small see-agent", onclick: () => this.showAgent(id) }, "Voir")),
      el("details", { class: "agent-detail" }, el("summary", { class: "subtle" }, "Consigne et résultat"),
        el("pre", { class: "tool-body" }, String(ev.input?.prompt || JSON.stringify(ev.input || {}, null, 2))), result));
    Object.assign(card, { result, status });
    const view = el("div", { class: "thread agent-view", role: "log", hidden: true });
    const mark = el("span", { class: "spinner" });
    const pill = el("button", { type: "button", class: "agent-pill", title: `Sous-agent : ${name}`,
      onclick: () => this.showAgent(id) }, mark, el("span", { class: "agent-name" }, name));
    this.agents.set(id, { name, view, pill, mark, card, done: false, background });
    this.thread.after(view);
    this.historyBtn.before(pill);               // « Terminés » reste au bout de la barre
    this.tools.set(id, card);
    this.tidyPills();
    return this.append(card);
  }

  // Affiche la vue d'un sous-agent, ou la conversation (`null`).
  showAgent(id) {
    const next = id && this.agents.has(id) ? id : null;
    if (next === this.shownAgent) return;
    if (!this.shownAgent) this.mainTop = this.thread.scrollTop;     // un fil caché perd sa position
    this.shownAgent = next;
    this.thread.hidden = Boolean(next);
    if (next) this.downBtn.hidden = true;
    this.mainPill.classList.toggle("active", !next);
    for (const [tid, a] of this.agents) {
      a.view.hidden = tid !== next;
      a.pill.classList.toggle("active", tid === next);
    }
    if (next) { const v = this.agents.get(next).view; v.scrollTop = v.scrollHeight; }
    else if (this.follow) this.toBottom();
    else this.thread.scrollTop = this.mainTop || 0;
    this.tidyPills();
  }

  // Un sous-agent qui travaille a sa pastille ; fini, il quitte la barre (sauf si on le regarde)
  // et passe dans « Terminés (n) ». La barre reste tant qu'il y a eu un sous-agent.
  tidyPills() {
    let done = 0;
    for (const [id, a] of this.agents) {
      a.pill.hidden = a.done && id !== this.shownAgent;
      if (a.done) done += 1;
    }
    this.historyBtn.hidden = done === 0;
    this.historyBtn.textContent = `Terminés (${done})`;
    if (!done) this.agentHistory.hidden = true;
    this.historyBtn.setAttribute("aria-expanded", String(!this.agentHistory.hidden));
    this.agentBar.hidden = this.agents.size === 0;
  }

  // Historique des sous-agents finis : le plus récent en tête ; un clic ouvre sa vue.
  toggleAgentHistory(force) {
    const show = force ?? this.agentHistory.hidden;
    clear(this.agentHistory);
    if (show) {
      const done = [...this.agents].filter(([, a]) => a.done).reverse();
      for (const [id, a] of done) {
        this.agentHistory.append(el("button", { type: "button", class: "agent-history-item", role: "listitem",
          onclick: () => { this.toggleAgentHistory(false); this.showAgent(id); } },
          el("span", { class: "agent-mark" }, a.mark.textContent), el("span", { class: "agent-name" }, a.name),
          el("span", { class: "subtle" }, a.card.status.textContent)));
      }
    }
    this.agentHistory.hidden = !show;
    this.tidyPills();
  }

  // Événement émis par un sous-agent : dans sa vue, pas dans le fil.
  agentEvent(agent, ev) {
    if (ev.type === "ToolUse") { if (ev.name !== "TodoWrite") this.toolCard(ev, agent.view); }
    else if (ev.type === "ToolResult") this.toolResult(ev);
    else if (ev.type === "AssistantText" && ev.text) {
      const node = claudeNode([], ev.msg_id);
      node.raw = ev.text;
      node.content.textContent = ev.text;
      this.append(node, agent.view);
      this.render(node.content, ev.text);
    }
  }

  // Fin d'un sous-agent : son résultat (premier plan) ou son avis de fin (arrière-plan : il rend
  // la main tout de suite, son résultat immédiat ne compte pas).
  agentDone(id, { notice = false, stopped = false } = {}) {
    const a = this.agents.get(id);
    if (!a || a.done || (a.background && !notice && !stopped)) return;
    a.done = true;
    a.mark.className = "agent-mark";
    a.mark.textContent = stopped ? "■" : "✓";
    a.card.status.textContent = stopped ? "arrêté" : "✓ terminé";
    a.card.classList.add("done");
    this.tidyPills();
  }

  stopAgents() { for (const id of this.agents.keys()) this.agentDone(id, { stopped: true }); }

  setTodos(items) {
    clear(this.todos);
    this.todos.hidden = !items.length;
    for (const t of items) {
      const mark = t.status === "completed" ? "✓" : t.status === "in_progress" ? "▸" : "○";
      this.todos.append(el("div", { class: `todo ${t.status}` }, `${mark} ${t.activeForm && t.status === "in_progress" ? t.activeForm : t.content}`));
    }
  }

  setState(state) {
    const labels = { busy: "Claude travaille…", starting: "Démarrage…", permission: "Attend ta réponse",
      idle: "", stopped: "", suspended: "En veille" };
    this.state.textContent = labels[state] ?? "";
    this.state.hidden = !this.state.textContent;
    this.state.dataset.state = state;
    this.stopBtn.hidden = !["busy", "permission", "starting"].includes(state);
    this.node.classList.toggle("busy", state === "busy");
    this.working.hidden = !["busy", "starting"].includes(state);
    this.working.lastChild.textContent = state === "starting" ? "Démarrage…" : "Claude travaille…";
  }

  permissionCard(ev) {
    this.showAgent(null);        // la demande est dans le fil : on y revient pour la voir
    if (ev.tool_name === "AskUserQuestion") return this.questionCard(ev);
    const reason = el("input", { placeholder: "Motif du refus (facultatif)", "aria-label": "Motif du refus", enterkeyhint: "done", autocapitalize: "sentences" });
    const answer = (decision) => this.call("chat.answer", { request_id: ev.request_id, decision, message: reason.value });
    const card = el("div", { class: "permission card" },
      el("strong", {}, `Claude demande : ${ev.display_name || ev.tool_name}`),
      el("pre", {}, target(ev.tool_name, ev.input) || JSON.stringify(ev.input, null, 2)),
      ev.description ? el("p", { class: "subtle" }, ev.description) : null,
      el("div", { class: "row" },
        el("button", { class: "primary", onclick: () => answer("allow") }, "Autoriser"),
        el("button", { onclick: () => answer("always") }, "Toujours"),
        el("button", { class: "danger", onclick: () => answer("deny") }, "Refuser")),
      reason);
    this.perms.set(ev.request_id, card);
    return this.append(card);
  }

  questionCard(ev) {
    const questions = (ev.input && ev.input.questions) || [];
    const fields = questions.map((q, qi) => {
      const multi = Boolean(q.multiSelect);
      const opts = (q.options || []).map((o) => {
        const input = el("input", { type: multi ? "checkbox" : "radio", name: `q${ev.request_id}-${qi}`, value: o.label });
        return el("label", { class: "check" }, input, el("span", {}, el("strong", {}, o.label),
          o.description ? el("span", { class: "subtle" }, ` — ${o.description}`) : null));
      });
      const other = el("input", { placeholder: "Autre réponse (facultatif)", "aria-label": "Autre réponse", enterkeyhint: "done", autocapitalize: "sentences" });
      return { q, multi, opts, other, node: el("fieldset", {}, el("legend", {}, q.question), ...opts, other) };
    });
    const submit = () => {
      const answers = {};
      for (const f of fields) {
        const picked = f.opts.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
        const free = f.other.value.trim();
        answers[f.q.question] = free || (f.multi ? picked : picked[0] || "");
      }
      this.call("chat.questions", { request_id: ev.request_id, answers });
    };
    const card = el("div", { class: "permission card" }, el("strong", {}, "Claude te pose une question"),
      ...fields.map((f) => f.node), el("button", { class: "primary", onclick: submit }, "Répondre"));
    this.perms.set(ev.request_id, card);
    return this.append(card);
  }

  // ---- événements du pont --------------------------------------------------------------

  receive(item) {
    if (item.seq) {
      if (item.seq <= this.seq) return;
      this.seq = item.seq;
    }
    const ev = item.event;
    const agent = ev.parent_id ? this.agents.get(ev.parent_id) : null;
    if (agent) { this.agentEvent(agent, ev); return; }
    switch (ev.type) {
      case "Init": this.setSession(ev.session_id); break;
      case "Hello": {
        const keep = this.model.value;
        clear(this.model).append(el("option", { value: "" }, "Modèle par défaut"),
          ...(ev.models || []).map((m) => (Array.isArray(m) ? el("option", { value: m[0] }, m[1] || m[0]) : el("option", { value: m }, m))));
        if (keep && ![...this.model.options].some((o) => o.value === keep)) this.model.append(el("option", { value: keep }, keep));
        this.model.value = keep;
        this.workP = null;
        this.updateSummary();
        break;
      }
      case "Status":
        if (ev.permission_mode) { this.rights.value = ev.permission_mode === "default" ? "manual" : ev.permission_mode; this.updateSummary(); }
        break;
      case "LocalCommand":
        if (ev.text) this.notice(ev.text);
        this.requestContext();       // `/compact`, `/clear` : le contexte a changé
        break;
      case "TextDelta": {
        const e = this.texts.get(ev.msg_id);
        this.assistant(ev.msg_id, (e ? e.text : "") + ev.text, false);
        break;
      }
      case "AssistantText": this.assistant(ev.msg_id, ev.text, true); break;
      case "Thinking": this.state.textContent = "Claude réfléchit…"; break;
      case "ToolUse": this.toolCard(ev); break;
      case "ToolResult": this.toolResult(ev); this.agentDone(ev.tool_id); break;
      case "TaskNotice": {
        const card = this.tools.get(ev.tool_id);
        if (card) card.classList.add("done");
        this.agentDone(ev.tool_id, { notice: true });
        if (ev.summary) this.notice(ev.summary);
        break;
      }
      case "Todos": this.setTodos(ev.items || []); break;
      case "PermissionRequest": this.permissionCard(ev); break;
      case "UserSent": if (!this.ownSent?.delete(ev.nonce)) this.userBubble(ev.text, ev.images || 0, ev.uuid || ""); break;
      case "TagsChanged": if (ev.session_id === this.sessionId) this.applyTag(ev.msg_id, ev.entry); break;
      case "PermissionSettled": { const c = this.perms.get(ev.request_id); if (c) { c.remove(); this.perms.delete(ev.request_id); } break; }
      case "ControlReply": break;
      case "TurnResult":
        this.cacheExpired = null;
        if (ev.ok && !ev.interrupted && usageSummary(ev.usage)) this.append(el("div", { class: "turn-usage subtle" }, usageSummary(ev.usage)));
        if (ev.usage?.context) this.showContext(null, ev.usage.context);
        if (ev.interrupted) { this.notice("Arrêté."); this.stopAgents(); }
        else if (ev.is_limit) this.notice(`Limite d'usage atteinte : ${ev.text || "attends la fin de la période ou change de compte."}`, "warning");
        else if (!ev.ok) this.notice(ev.text || "Claude n'a pas pu finir sa réponse.", "error");
        for (const c of this.perms.values()) c.remove();
        this.perms.clear();
        this.filesP = null;          // Claude a pu créer ou supprimer des fichiers
        this.requestContext();
        break;
      case "Compacted": this.notice("Conversation compactée."); break;
      case "ConversationReset": this.newConversation(ev.trigger === "ccs_auto"); break;
      case "Compacting": break;      // lu par le moteur (état du compactage), jamais envoyé
      case "Notice": this.notice(ev.text, ["warning", "error"].includes(ev.kind) ? ev.kind : "info"); break;
      case "Retrying": this.notice(`Nouvel essai (${ev.attempt}) dans ${Math.round(ev.delay_s)} s…`, "warning"); break;
      case "Unknown": break;
      case "StateChanged": this.setState(ev.state); break;
      case "ContextUsage": this.showContext(ev.percentage, ev.total); this.checkContext(ev); break;
      case "CacheExpired":
        this.cacheExpired = ev;
        this.notice(ev.text, "warning", [{ label: "Compacter", run: () => this.sendText("/compact") },
          { label: "Nouvelle session", run: () => document.dispatchEvent(new CustomEvent("ccs:new-chat", { detail: { cwd: this.cwd } })) }]);
        break;
      case "OptionRefused": this.notice(`Réglage refusé (${ev.what}) : ${ev.error}`, "warning"); break;
      case "UnhandledRequest": this.notice(`Demande non prise en charge : ${ev.subtype}`, "warning"); break;
      case "ProcessExited": this.stopAgents(); if (!ev.requested && ev.code) this.notice(`Claude s'est arrêté (code ${ev.code}).`, "error"); break;
      default: break;
    }
  }

  // ---- historique d'une conversation reprise ----------------------------------------------

  historyNode(m) {
    if (m.role === "user") return this.paintTags(userNode(m.text, 0, this.msgActions, this.renderQuote, m.uuid || ""));
    if (m.role === "assistant") { const n = this.paintTags(claudeNode(this.msgActions, m.msg_id || "")); n.raw = m.text; this.render(n.content, m.text); return n; }
    if (m.role === "tool" && m.tool) {
      return el("details", { class: `tool done${m.tool.is_error ? " error" : ""}` },
        el("summary", {}, el("strong", {}, TOOL_LABELS[m.tool.name] || m.tool.name), " ", el("span", { class: "subtle" }, m.tool.target)),
        m.tool.result ? el("pre", { class: "tool-result" }, m.tool.result) : null);
    }
    return m.text ? el("div", { class: "notice info" }, el("span", {}, m.text)) : null;
  }

  historyParams(h, limit) {
    return { path: h.path, limit, ...(h.before !== undefined ? { before: h.before } : {}) };
  }

  // Au-dessus du fil : les événements du tampon sont peut-être déjà affichés.
  async loadHistory() {
    const h = this.history;
    let r;
    try { r = await this.api.call("conversations.messages", this.historyParams(h, HISTORY_LIMIT)); } catch { return; }
    if (this.history !== h) return;                  // fil remis à zéro entre-temps
    const msgs = r.messages || [];
    h.loaded = msgs.length;
    h.full = msgs.length < HISTORY_LIMIT;
    const first = this.thread.firstChild;
    for (const m of msgs) { const n = this.historyNode(m); if (n) this.thread.insertBefore(n, first); }
    this.regroup();
    this.toBottom();
  }

  // Pour la recherche : le fil ne montre que les derniers messages ; ajoute les plus anciens en haut.
  async loadFullHistory() {
    const h = this.history;
    if (!h || h.full) return;
    h.full = true;
    let r;
    try { r = await this.api.call("conversations.messages", this.historyParams(h, 100000)); } catch { h.full = false; return; }
    const older = (r.messages || []).slice(0, Math.max(0, (r.messages || []).length - h.loaded));
    const first = this.thread.firstChild;
    for (const m of older) { const n = this.historyNode(m); if (n) this.thread.insertBefore(n, first); }
    this.regroup();
  }
}

// uuid v4 du message envoyé ; crypto.randomUUID n'existe qu'en contexte sûr (https, localhost).
// Commande de Claude Code (`/clear`, `/compact`…) : un `/` suivi d'une lettre, en tête.
export function isSlashCommand(text) {
  return /^\s*\/[A-Za-z]/.test(text || "");
}

function newUuid() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const b = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) crypto.getRandomValues(b); else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const AGENT_TOOLS = ["Task", "Agent"];   // outils qui lancent un sous-agent

function isToolNode(n) {
  return Boolean(n) && n.matches?.("details.tool") && !n.classList.contains("shell");
}

function toolGroup() {
  const count = el("strong", {});
  const last = el("span", { class: "subtle" });
  const body = el("div", { class: "tool-group-body" });
  const g = el("details", { class: "tool-group" }, el("summary", {}, count, " ", last), body);
  Object.assign(g, { body, count, last });
  return g;
}

function refreshGroup(g) {
  const tools = [...g.body.children];
  g.count.textContent = `${tools.length} actions`;
  const sum = tools[tools.length - 1]?.querySelector("summary");
  g.last.textContent = sum ? `· ${sum.textContent.trim()}` : "";
}

// Bloc de code d'une réponse : barre du haut avec la langue et un bouton « Copier », le code dessous
// (le bouton ne recouvre jamais une longue commande).
const COPY_ICON = [["rect", { x: 9, y: 9, width: 12, height: 12, rx: 2 }], ["path", { d: "M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" }]];
const DONE_ICON = [["path", { d: "M20 6 9 17l-5-5" }]];

function addCopyButtons(node) {
  for (const pre of node.querySelectorAll("pre")) {
    const code = pre.querySelector("code");
    const lang = [...(code?.classList || [])].find((c) => c.startsWith("language-"))?.slice(9) || "code";
    const btn = el("button", { type: "button", class: "copy-code", "aria-label": "Copier le code" });
    const label = (shapes, text) => { clear(btn).append(icon(shapes), el("span", {}, text)); };
    label(COPY_ICON, "Copier");
    btn.addEventListener("click", async () => {
      const text = (code || pre).textContent;
      try { await navigator.clipboard.writeText(text); }
      catch {
        const ta = el("textarea", { style: "position:fixed;opacity:0" }); ta.value = text;
        document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
      }
      btn.classList.add("done"); label(DONE_ICON, "Copié");
      setTimeout(() => { btn.classList.remove("done"); label(COPY_ICON, "Copier"); }, 1500);
    });
    const wrap = el("div", { class: "code-wrap" }, el("div", { class: "code-head" }, el("span", { class: "code-lang" }, lang), btn));
    pre.replaceWith(wrap); wrap.append(pre);
  }
}
