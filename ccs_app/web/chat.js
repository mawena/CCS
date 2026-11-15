// Un chat de la version web : fil (messages, Markdown rendu par le pont, cartes d'actions,
// sous-agents), autorisations et questions de Claude, liste de tâches épinglée, barre modèle /
// effort / droits, saisie avec images. Les événements arrivent numérotés : après une coupure, le
// chat redemande ce qu'il a manqué (`chat.attach` depuis son dernier numéro).
import { clear, el, setHtml } from "./dom.js";
import { FilesPanel } from "./files.js";
import { RoadmapPanel } from "./roadmap.js";

const RIGHTS = [["manual", "Demander"], ["acceptEdits", "Modifications acceptées"], ["plan", "Plan"],
  ["bypassPermissions", "Tout autoriser"]];
const EFFORTS = [["", "Effort par défaut"], ["low", "Faible"], ["medium", "Moyen"], ["high", "Élevé"],
  ["xhigh", "Très élevé"], ["max", "Max"]];
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
    this.images = [];
    this.offs = [];

    this.state = el("span", { class: "chat-state subtle" }, "");
    this.stopBtn = el("button", { class: "small danger", hidden: true, onclick: () => this.call("chat.interrupt") }, "Arrêter");
    this.thread = el("div", { class: "thread", role: "log", "aria-live": "polite" });
    this.todos = el("div", { class: "todos", hidden: true });
    this.input = el("textarea", { rows: 1, placeholder: "Écris à Claude…", "aria-label": "Message" });
    this.thumbs = el("div", { class: "thumbs" });
    this.fileInput = el("input", { type: "file", accept: "image/*", multiple: true, hidden: true });
    this.rights = el("select", { "aria-label": "Droits" }, ...RIGHTS.map(([v, t]) => el("option", { value: v }, t)));
    this.effort = el("select", { "aria-label": "Effort" }, ...EFFORTS.map(([v, t]) => el("option", { value: v }, t)));
    this.model = el("select", { "aria-label": "Modèle" }, el("option", { value: "" }, "Modèle par défaut"));
    this.context = el("span", { class: "subtle context" }, "");

    const send = el("button", { class: "primary send", type: "submit", "aria-label": "Envoyer" }, "Envoyer");
    const attach = el("button", { class: "flat", type: "button", "aria-label": "Joindre une image", onclick: () => this.fileInput.click() }, "📎");
    const form = el("form", { class: "composer" },
      this.todos, this.thumbs,
      el("div", { class: "composer-row" }, attach, this.input, send, this.fileInput),
      el("div", { class: "chat-bar" }, this.model, this.effort, this.rights, this.context));
    form.addEventListener("submit", (e) => { e.preventDefault(); this.send(); });
    this.input.addEventListener("keydown", (e) => {
      const phone = matchMedia("(max-width: 719px)").matches;
      if (e.key === "Enter" && !e.shiftKey && !phone) { e.preventDefault(); this.send(); }
      if (e.key === "Escape") this.call("chat.interrupt");
    });
    this.input.addEventListener("input", () => this.grow());
    this.input.addEventListener("paste", (e) => {
      const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
      if (files.length) { e.preventDefault(); this.addImages(files); }
    });
    this.fileInput.addEventListener("change", () => { this.addImages([...this.fileInput.files]); this.fileInput.value = ""; });
    const options = () => this.call("chat.options", { options: {
      model: this.model.value || null, effort: this.effort.value || null, rights: this.rights.value } });
    for (const s of [this.rights, this.effort, this.model]) s.addEventListener("change", options);

    this.drawer = el("aside", { class: "drawer", hidden: true });
    const panel = (kind) => () => this.openDrawer(kind);
    this.node = el("section", { class: "chat" },
      el("header", { class: "chat-head" }, el("div", { class: "grow" }, el("strong", {}, title || cwd),
        el("div", { class: "subtle" }, cwd)), this.state, this.stopBtn,
        el("button", { class: "small flat", title: "Fichiers du projet", onclick: panel("files") }, "📁"),
        el("button", { class: "small flat", title: "Feuille de route", onclick: panel("roadmap") }, "☑")),
      el("div", { class: "chat-body" }, this.drawer, el("div", { class: "chat-main" }, this.thread, form)));
    root.append(this.node);

    this.offs.push(api.on("chat.event", (d) => { if (d.chat_id === this.chatId) this.receive(d); }));
    this.offs.push(api.on("reconnected", () => this.attach()));
    if (history) this.loadHistory(history);
    this.attach();
  }

  destroy() { for (const off of this.offs) off(); this.node.remove(); }

  openDrawer(kind) {
    if (!this.drawer.hidden && this.drawer.dataset.kind === kind) { this.drawer.hidden = true; return; }
    clear(this.drawer);
    this.drawer.dataset.kind = kind;
    this.drawer.hidden = false;
    this.drawer.append(el("div", { class: "drawer-head" },
      el("strong", { class: "grow" }, kind === "files" ? "Fichiers" : "Feuille de route"),
      el("button", { class: "small flat", "aria-label": "Fermer", onclick: () => { this.drawer.hidden = true; } }, "×")));
    const body = el("div", { class: "drawer-body" });
    this.drawer.append(body);
    if (kind === "files") new FilesPanel(body, this.api, this.cwd);
    else new RoadmapPanel(body, this.api, this.cwd, { send: (text) => this.sendText(text) });
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

  grow() {
    this.input.style.height = "auto";
    this.input.style.height = `${Math.min(this.input.scrollHeight, 220)}px`;
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

  // Texte préparé ailleurs (feuille de route, messages enregistrés…) : envoyé comme s'il était tapé.
  sendText(text) {
    this.input.value = text;
    return this.send();
  }

  async send() {
    const text = this.input.value.trim();
    if (!text && !this.images.length) return;
    const images = this.images.splice(0);
    clear(this.thumbs);
    this.input.value = "";
    this.grow();
    this.userBubble(text, images.length);
    const r = await this.call("chat.send", { text, images });
    if (!r || !r.ok) this.notice("Le message n'est pas parti : Claude n'a pas pu démarrer.", "error");
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

  notice(text, kind = "info") {
    return this.append(el("div", { class: `notice ${kind}` }, text));
  }

  async render(node, markdown) {
    try {
      const r = await this.api.call("chat.render", { markdown });
      setHtml(node, r.html);
    } catch { node.textContent = markdown; }
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
    const body = el("pre", { class: "tool-body" }, JSON.stringify(ev.input || {}, null, 2));
    const result = el("pre", { class: "tool-result", hidden: true });
    const card = el("details", { class: `tool${ev.parent_id ? " nested" : ""}` },
      el("summary", {}, el("strong", {}, name), " ", el("span", { class: "subtle" }, target(ev.name, ev.input))),
      body, result);
    card.result = result;
    this.tools.set(ev.tool_id, card);
    return this.append(card);
  }

  permissionCard(ev) {
    if (ev.tool_name === "AskUserQuestion") return this.questionCard(ev);
    const reason = el("input", { placeholder: "Motif du refus (facultatif)" });
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
      const other = el("input", { placeholder: "Autre réponse (facultatif)" });
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
    this.stopBtn.hidden = !["busy", "permission", "starting"].includes(state);
    this.node.classList.toggle("busy", state === "busy");
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
        break;
      case "Status": if (ev.permission_mode) this.rights.value = ev.permission_mode === "default" ? "manual" : ev.permission_mode; break;
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
        break;
      case "Compacted": this.notice("Conversation compactée."); break;
      case "Retrying": this.notice(`Nouvel essai (${ev.attempt}) dans ${Math.round(ev.delay_s)} s…`, "warning"); break;
      case "Unknown": break;
      case "StateChanged": this.setState(ev.state); break;
      case "ContextUsage": this.context.textContent = `Contexte ${ev.percentage} %`; break;
      case "OptionRefused": this.notice(`Réglage refusé (${ev.what}) : ${ev.error}`, "warning"); break;
      case "UnhandledRequest": this.notice(`Demande non prise en charge : ${ev.subtype}`, "warning"); break;
      case "ProcessExited": if (!ev.requested && ev.code) this.notice(`Claude s'est arrêté (code ${ev.code}).`, "error"); break;
      default: break;
    }
  }

  // ---- historique d'une conversation reprise ----------------------------------------------

  async loadHistory(path) {
    let r;
    try { r = await this.api.call("conversation.messages", { path, limit: 200 }); } catch { return; }
    for (const m of r.messages || []) {
      if (m.role === "utilisateur") this.userBubble(m.text);
      else if (m.role === "assistant") { const n = this.append(el("div", { class: "msg claude" })); this.render(n, m.text); } else if (m.role === "outil" && m.tool) {
        this.append(el("details", { class: `tool done${m.tool.is_error ? " error" : ""}` },
          el("summary", {}, el("strong", {}, TOOL_LABELS[m.tool.name] || m.tool.name), " ", el("span", { class: "subtle" }, m.tool.target)),
          m.tool.result ? el("pre", { class: "tool-result" }, m.tool.result) : null));
      } else if (m.text) this.notice(m.text);
    }
    this.thread.scrollTop = this.thread.scrollHeight;
  }
}
