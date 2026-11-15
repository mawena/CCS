// Un chat de la version web : fil (messages, Markdown rendu par le pont, cartes d'actions,
// sous-agents), autorisations et questions de Claude, liste de tâches épinglée, barre modèle /
// effort / droits, saisie avec images. Les événements arrivent numérotés : après une coupure, le
// chat redemande ce qu'il a manqué (`chat.attach` depuis son dernier numéro).
import { clear, el, setHtml, toast } from "./dom.js";
import { ChangesPanel } from "./chat-changes.js";
import { Completer } from "./chat-complete.js";
import { diffCard, editDiffs } from "./chat-diff.js";
import { linkify } from "./chat-links.js";
import { openSavedSheet } from "./chat-saved.js";
import { FindBar } from "./chat-search.js";
import { FilesPanel } from "./files.js";
import { GitPanel } from "./git.js";
import { RoadmapPanel } from "./roadmap.js";

const RIGHTS = [["manual", "Demander"], ["acceptEdits", "Modifications acceptées"], ["plan", "Plan"],
  ["bypassPermissions", "Tout autoriser"]];
const EFFORTS = [["", "Effort par défaut"], ["low", "Faible"], ["medium", "Moyen"], ["high", "Élevé"],
  ["xhigh", "Très élevé"], ["max", "Max"]];
const DRAWER_TITLES = { files: "Fichiers", roadmap: "Feuille de route", git: "Git", changes: "Changements de la session" };
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

export class ChatView {
  constructor(root, api, { chatId, cwd, title, history }) {
    this.api = api;
    this.chatId = chatId;
    this.cwd = cwd;
    this.seq = 0;
    this.texts = new Map();      // msg_id → { node, text, timer }
    this.tools = new Map();      // tool_id → carte
    this.perms = new Map();      // request_id → carte
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
    this.draftKey = `ccs-draft:${cwd}|${history || chatId}`;

    this.state = el("span", { class: "chat-state", hidden: true }, "");
    this.stopBtn = el("button", { type: "button", class: "danger stop", hidden: true, onclick: () => this.call("chat.interrupt") }, "Arrêter");
    this.thread = el("div", { class: "thread", role: "log", "aria-live": "polite", tabindex: "-1" });
    this.todos = el("div", { class: "todos", hidden: true });
    this.input = el("textarea", { rows: 1, placeholder: "Écris à Claude…", "aria-label": "Message", enterkeyhint: "send",
      autocapitalize: "sentences", autocomplete: "off" });
    this.thumbs = el("div", { class: "thumbs" });
    this.fileInput = el("input", { type: "file", accept: "image/*", multiple: true, hidden: true });
    this.rights = el("select", { "aria-label": "Droits" }, ...RIGHTS.map(([v, t]) => el("option", { value: v }, t)));
    this.effort = el("select", { "aria-label": "Effort" }, ...EFFORTS.map(([v, t]) => el("option", { value: v }, t)));
    this.model = el("select", { "aria-label": "Modèle" }, el("option", { value: "" }, "Modèle par défaut"));
    this.context = el("span", { class: "subtle context" }, "");
    this.summary = el("span", { class: "opt-summary subtle" }, "");
    this.bar = el("div", { class: "chat-bar", hidden: true }, this.model, this.effort, this.rights);
    this.optBtn = el("button", { type: "button", class: "small flat opt", "aria-expanded": "false", onclick: () => this.toggleOptions() },
      el("strong", {}, "Options"), this.summary);

    const send = el("button", { class: "primary send", type: "submit", "aria-label": "Envoyer" }, "Envoyer");
    const attach = el("button", { class: "flat icon", type: "button", "aria-label": "Joindre une image", title: "Joindre une image",
      onclick: () => this.fileInput.click() }, "📎");
    const saved = el("button", { class: "flat icon", type: "button", "aria-label": "Messages enregistrés", title: "Messages enregistrés",
      onclick: () => openSavedSheet({ api: this.api, cwd: this.cwd, currentText: () => this.input.value,
        onInsert: (t) => this.insert(t) }) }, "★");
    this.form = el("form", { class: "composer" },
      this.todos, this.thumbs,
      el("div", { class: "composer-row" }, attach, saved, this.input, this.stopBtn, send, this.fileInput),
      this.bar,
      el("div", { class: "composer-foot" }, this.optBtn, this.context));
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
      ensureAll: () => this.loadFullHistory(), onClose: () => this.input.focus() });
    this.drawer = el("aside", { class: "drawer", hidden: true });
    this.menu = el("div", { class: "chat-menu", hidden: true });
    const items = [
      { label: "Fichiers", run: () => this.openDrawer("files"), phone: true },
      { label: "Feuille de route", run: () => this.openDrawer("roadmap") },
      { label: "Git", run: () => this.openDrawer("git") },
      { label: "Changements", run: () => this.openDrawer("changes") },
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
        el("div", { class: "chat-title grow" }, el("strong", { class: "title" }, title || cwd),
          el("div", { class: "chat-sub" }, this.state, el("span", { class: "subtle cwd" }, cwd))),
        actions, this.menu),
      this.findbar.node,
      el("div", { class: "chat-body" }, this.drawer, el("div", { class: "chat-main" }, this.thread, this.form)));
    this.node.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "f") { e.preventDefault(); this.findbar.show(); }
    });
    const outside = (e) => { if (!this.menu.hidden && !this.menu.contains(e.target) && !e.target.closest?.(".chat-actions")) this.menu.hidden = true; };
    document.addEventListener("click", outside);
    this.offs.push(() => document.removeEventListener("click", outside));
    root.append(this.node);

    this.input.value = this.loadDraft();
    this.grow();
    this.updateSummary();
    this.offs.push(api.on("chat.event", (d) => { if (d.chat_id === this.chatId) this.receive(d); }));
    this.offs.push(api.on("work.shell", (d) => { if (d.chat_id === this.chatId) this.shellDone(d); }));
    this.offs.push(api.on("reconnected", () => { this.attach(); this.pollShells(); }));
    if (history) this.loadHistory(history);
    this.attach();
  }

  destroy() { for (const off of this.offs) off(); this.node.remove(); }

  // ---- saisie -----------------------------------------------------------------------------

  keydown(e) {
    if (this.completer.key(e)) return;
    const phone = matchMedia("(max-width: 719px)").matches;
    if (e.key === "Enter" && !e.shiftKey && !phone) { e.preventDefault(); this.send(); return; }
    if (e.key === "Tab" && e.shiftKey) {            // comme au bureau : Maj+Tab change les droits
      e.preventDefault();
      const order = RIGHTS.map(([v]) => v);
      this.rights.value = order[(order.indexOf(this.rights.value) + 1) % order.length];
      this.pushOptions();
      toast(`Droits : ${this.rights.selectedOptions[0].textContent}`);
      return;
    }
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

  pushOptions() {
    this.updateSummary();
    this.call("chat.options", { options: { model: this.model.value || null, effort: this.effort.value || null, rights: this.rights.value } });
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
  async deliver(text, images = [], retry = null) {
    let r = null;
    try { r = await this.api.call("chat.send", { chat_id: this.chatId, text: this.shellNotes.join("") + text, images }); } catch (e) {
      this.sendFailed(e.message, retry);
      return false;
    }
    if (!r || !r.ok) { this.sendFailed("Claude n'a pas pu démarrer.", retry); return false; }
    this.shellNotes = [];
    this.userBubble(text, images.length);
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
    this.sending = true;
    try {
      const images = [...this.images];
      if (await this.deliver(text, images, () => this.send())) {
        this.images = [];
        clear(this.thumbs);
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
    try { r = await this.api.call("work.shell.run", { chat_id: this.chatId, command }); } catch (e) {
      this.shellFinish({ card, command }, { code: 127, output: e.message, truncated: false });
      return;
    }
    const entry = { card, command };
    stop.addEventListener("click", () => this.api.call("work.shell.stop", { run_id: r.run_id }).catch(() => {}));
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
      try { const r = await this.api.call("work.shell.poll", { run_id }); if (r.done) this.shellDone(r); } catch { /* sera retenté */ }
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
    const cfg = (await this.workInfo()).context;
    const over = Boolean(cfg.enabled && cfg.threshold_tokens && ev.total >= cfg.threshold_tokens);
    if (over && !this.heavy) {           // franchissement du seuil vers le haut : une seule alerte
      const gain = ev.total - Math.floor(ev.total * 0.2);
      this.notice(`Contexte lourd : ${fr(ev.total)} jetons. Compacter libérerait environ ${fr(gain)} jetons (estimation).`, "warning",
        { label: "Compacter", run: () => this.sendText("/compact") });
    }
    this.heavy = over;
  }

  // ---- volets ------------------------------------------------------------------------------

  openDrawer(kind, { fresh = false } = {}) {
    if (!fresh && !this.drawer.hidden && this.drawer.dataset.kind === kind) { this.drawer.hidden = true; return; }
    clear(this.drawer);
    this.drawer.dataset.kind = kind;
    this.drawer.hidden = false;
    this.drawer.append(el("div", { class: "drawer-head" },
      el("strong", { class: "grow" }, DRAWER_TITLES[kind]),
      el("button", { type: "button", class: "small flat", "aria-label": "Fermer", onclick: () => { this.drawer.hidden = true; } }, "×")));
    const body = el("div", { class: "drawer-body" });
    this.drawer.append(body);
    this.panel = null;
    if (kind === "files") this.panel = new FilesPanel(body, this.api, this.cwd);
    else if (kind === "git") new GitPanel(body, this.api, this.cwd);
    else if (kind === "changes") new ChangesPanel(body, this.api, this.chatId, this.cwd, { openFile: (p) => this.openFile(p), changed: () => { this.filesP = null; } });
    else new RoadmapPanel(body, this.api, this.cwd, { send: (text) => this.sendText(text) });
  }

  // Fichier d'un projet cité dans le chat ou dans un diff : volet Fichiers, à la ligne `line`.
  openFile(path, { line = null } = {}) {
    this.openDrawer("files", { fresh: true });
    this.panel.openFile(path, { line });
  }

  async call(method, params = {}) {
    try { return await this.api.call(method, { chat_id: this.chatId, ...params }); } catch (e) {
      this.notice(e.message, "error");
      return null;
    }
  }

  async attach() {
    const r = await this.call("chat.attach", { since: this.seq });
    if (!r) return;
    for (const item of r.events) this.receive(item);
    this.setState(r.state);
  }

  // ---- fil ----------------------------------------------------------------------------

  stuck() { return this.thread.scrollHeight - this.thread.scrollTop - this.thread.clientHeight < 80; }

  append(node) {
    const stick = this.stuck();
    this.thread.append(node);
    if (stick) this.thread.scrollTop = this.thread.scrollHeight;
    return node;
  }

  userBubble(text, nImages = 0) {
    return this.append(el("div", { class: "msg user" }, el("div", { class: "bubble" }, text,
      nImages ? el("div", { class: "subtle" }, `${nImages} image(s) jointe(s)`) : null)));
  }

  // `action` : { label, run } ajoute un bouton à la note (« Compacter »…).
  notice(text, kind = "info", action = null) {
    return this.append(el("div", { class: `notice ${kind}` }, el("span", {}, text),
      action ? el("button", { type: "button", class: "small", onclick: action.run }, action.label) : null));
  }

  async render(node, markdown) {
    try {
      const r = await this.api.call("chat.render", { markdown });
      setHtml(node, r.html);
      linkify(node, this.cwd, (await this.fileIndex()).set, (p, o) => this.openFile(p, o));
    } catch { if (!node.firstChild) node.textContent = markdown; }
  }

  assistant(msgId, text, final) {
    let entry = this.texts.get(msgId);
    if (!entry) {
      entry = { node: this.append(el("div", { class: "msg claude" })), text: "", timer: null };
      this.texts.set(msgId, entry);
    }
    entry.text = text;
    clearTimeout(entry.timer);
    if (final) this.render(entry.node, text);
    else entry.timer = setTimeout(() => this.render(entry.node, entry.text), 250);
  }

  toolCard(ev) {
    const name = TOOL_LABELS[ev.name] || ev.name;
    const diffs = editDiffs(ev.name, ev.input);
    let card;
    if (diffs) card = diffCard({ label: name, diffs, nested: Boolean(ev.parent_id), onOpen: (p) => this.openFile(p) });
    else {
      const body = el("pre", { class: "tool-body" }, JSON.stringify(ev.input || {}, null, 2));
      const result = el("pre", { class: "tool-result", hidden: true });
      card = el("details", { class: `tool${ev.parent_id ? " nested" : ""}` },
        el("summary", {}, el("strong", {}, name), " ", el("span", { class: "subtle" }, target(ev.name, ev.input))),
        body, result);
      card.result = result;
    }
    this.tools.set(ev.tool_id, card);
    return this.append(card);
  }

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
  }

  permissionCard(ev) {
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
    switch (ev.type) {
      case "Init": this.sessionId = ev.session_id; break;
      case "Hello":
        clear(this.model).append(el("option", { value: "" }, "Modèle par défaut"),
          ...(ev.models || []).map((m) => (Array.isArray(m) ? el("option", { value: m[0] }, m[1] || m[0]) : el("option", { value: m }, m))));
        this.workP = null;
        this.updateSummary();
        break;
      case "Status":
        if (ev.permission_mode) { this.rights.value = ev.permission_mode === "default" ? "manual" : ev.permission_mode; this.updateSummary(); }
        break;
      case "LocalCommand": if (ev.text) this.notice(ev.text); break;
      case "TextDelta": {
        const e = this.texts.get(ev.msg_id);
        this.assistant(ev.msg_id, (e ? e.text : "") + ev.text, false);
        break;
      }
      case "AssistantText": this.assistant(ev.msg_id, ev.text, true); break;
      case "Thinking": this.state.textContent = "Claude réfléchit…"; break;
      case "ToolUse": this.toolCard(ev); break;
      case "ToolResult": {
        const card = this.tools.get(ev.tool_id);
        if (card) { card.result.hidden = false; card.result.textContent = ev.text; card.classList.toggle("error", ev.is_error); card.classList.add("done"); }
        break;
      }
      case "TaskNotice": {
        const card = this.tools.get(ev.tool_id);
        if (card) card.classList.add("done");
        if (ev.summary) this.notice(ev.summary);
        break;
      }
      case "Todos": this.setTodos(ev.items || []); break;
      case "PermissionRequest": this.permissionCard(ev); break;
      case "PermissionSettled": { const c = this.perms.get(ev.request_id); if (c) { c.remove(); this.perms.delete(ev.request_id); } break; }
      case "ControlReply": break;
      case "TurnResult":
        if (ev.interrupted) this.notice("Arrêté.");
        else if (ev.is_limit) this.notice(`Limite d'usage atteinte : ${ev.text || "attends la fin de la période ou change de compte."}`, "warning");
        else if (!ev.ok) this.notice(ev.text || "Claude n'a pas pu finir sa réponse.", "error");
        for (const c of this.perms.values()) c.remove();
        this.perms.clear();
        this.filesP = null;          // Claude a pu créer ou supprimer des fichiers
        break;
      case "Compacted": this.notice("Conversation compactée."); break;
      case "Retrying": this.notice(`Nouvel essai (${ev.attempt}) dans ${Math.round(ev.delay_s)} s…`, "warning"); break;
      case "Unknown": break;
      case "StateChanged": this.setState(ev.state); break;
      case "ContextUsage": this.context.textContent = `Contexte ${ev.percentage} %`; this.checkContext(ev); break;
      case "OptionRefused": this.notice(`Réglage refusé (${ev.what}) : ${ev.error}`, "warning"); break;
      case "UnhandledRequest": this.notice(`Demande non prise en charge : ${ev.subtype}`, "warning"); break;
      case "ProcessExited": if (!ev.requested && ev.code) this.notice(`Claude s'est arrêté (code ${ev.code}).`, "error"); break;
      default: break;
    }
  }

  // ---- historique d'une conversation reprise ----------------------------------------------

  historyNode(m) {
    if (m.role === "utilisateur") return el("div", { class: "msg user" }, el("div", { class: "bubble" }, m.text));
    if (m.role === "assistant") { const n = el("div", { class: "msg claude" }); this.render(n, m.text); return n; }
    if (m.role === "outil" && m.tool) {
      return el("details", { class: `tool done${m.tool.is_error ? " error" : ""}` },
        el("summary", {}, el("strong", {}, TOOL_LABELS[m.tool.name] || m.tool.name), " ", el("span", { class: "subtle" }, m.tool.target)),
        m.tool.result ? el("pre", { class: "tool-result" }, m.tool.result) : null);
    }
    return m.text ? el("div", { class: "notice info" }, el("span", {}, m.text)) : null;
  }

  async loadHistory(path) {
    let r;
    try { r = await this.api.call("conversation.messages", { path, limit: HISTORY_LIMIT }); } catch { return; }
    const msgs = r.messages || [];
    this.history.loaded = msgs.length;
    this.history.full = msgs.length < HISTORY_LIMIT;
    for (const m of msgs) { const n = this.historyNode(m); if (n) this.append(n); }
    this.thread.scrollTop = this.thread.scrollHeight;
  }

  // Pour la recherche : le fil ne montre que les derniers messages ; ajoute les plus anciens en haut.
  async loadFullHistory() {
    const h = this.history;
    if (!h || h.full) return;
    h.full = true;
    let r;
    try { r = await this.api.call("conversation.messages", { path: h.path, limit: 100000 }); } catch { h.full = false; return; }
    const older = (r.messages || []).slice(0, Math.max(0, (r.messages || []).length - h.loaded));
    const first = this.thread.firstChild;
    for (const m of older) { const n = this.historyNode(m); if (n) this.thread.insertBefore(n, first); }
  }
}
