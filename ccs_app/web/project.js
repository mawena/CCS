// Écran Projet : nom et chemin, « Nouveau chat » et « Terminal », puis quatre onglets
// (conversations, fichiers, feuille de route, Git). Chaque onglet n'est construit qu'à sa première
// ouverture et garde son état quand on change d'onglet.
import { clear, el, emptyState, errorState, loading } from "./dom.js";
import { FilesPanel } from "./files.js";
import { GitPanel } from "./git.js";
import { RoadmapPanel } from "./roadmap.js";
import { convRow } from "./sessions-conv.js";

const STEP = 30;
const TABS = [["conversations", "Conversations"], ["files", "Fichiers"], ["roadmap", "Feuille de route"], ["git", "Git"]];

export const baseName = (p) => (p || "").split("/").filter(Boolean).pop() || p;

// host : { onBack, resume(conv), newChat(cwd, text?), openTerm(cwd), opened() → Set de session_id }
export class ProjectScreen {
  constructor(container, api, cwd, host) {
    this.api = api;
    this.cwd = cwd;
    this.host = host;
    this.panels = new Map();
    this.buttons = new Map();
    this.body = el("div", { class: "project-body" });
    const tabs = el("div", { class: "project-tabs", role: "tablist" });
    for (const [id, label] of TABS) {
      const b = el("button", { class: "tab-btn", role: "tab", "aria-selected": "false", onclick: () => this.select(id) }, label);
      this.buttons.set(id, b);
      tabs.append(b);
    }
    this.node = el("section", { class: "project-screen" },
      el("header", { class: "project-head" },
        el("button", { class: "flat back-project", "aria-label": "Retour à la liste", onclick: () => host.onBack() }, "← Sessions"),
        el("div", { class: "grow project-title" }, el("h2", {}, baseName(cwd)), el("div", { class: "subtle project-path", title: cwd }, cwd)),
        el("div", { class: "project-actions" },
          el("button", { class: "primary", onclick: () => host.newChat(cwd) }, "Nouveau chat"),
          el("button", { onclick: () => host.openTerm(cwd) }, "Terminal"))),
      tabs, this.body);
    container.append(this.node);
    this.offs = [api.on("reconnected", () => this.reload())];
    this.select("conversations");
  }

  // Feuille de route et Git changent hors de cet écran (Claude, un terminal) : on les relit.
  reload() {
    this.roadmap?.load();
    this.git?.refresh();
    if (this.convBox && !this.panels.get("conversations")?.hidden) this.loadConversations();
  }

  select(id) {
    for (const [k, b] of this.buttons) { b.classList.toggle("active", k === id); b.setAttribute("aria-selected", String(k === id)); }
    for (const [k, p] of this.panels) p.hidden = k !== id;
    if (this.panels.has(id)) {
      if (id === "conversations") this.loadConversations();
      else if (id === "roadmap") this.roadmap?.load();
      else if (id === "git") this.git?.refresh();
      return;
    }
    const holder = el("div", { class: `project-panel panel-${id}` });
    this.panels.set(id, holder);
    this.body.append(holder);
    if (id === "conversations") { this.convBox = holder; this.loadConversations(); }
    else if (id === "files") this.files = new FilesPanel(holder, this.api, this.cwd);
    else if (id === "roadmap") {
      this.roadmap = new RoadmapPanel(holder, this.api, this.cwd, { standalone: true, send: (text) => this.host.newChat(this.cwd, text) });
    } else this.git = new GitPanel(holder, this.api, this.cwd);
  }

  async loadConversations() {
    const box = this.convBox;
    if (!box.children.length) box.append(loading());
    let r;
    try { r = await this.api.call("projects.list", { cwd: this.cwd }); } catch (e) {
      clear(box).append(errorState(e.message, () => { clear(box); this.loadConversations(); }));
      return;
    }
    const convs = r.conversations || [];
    let shown = STEP;
    const draw = () => {
      clear(box);
      if (!convs.length) {
        box.append(emptyState("Pas encore de conversation dans ce projet.", el("button", { class: "primary", onclick: () => this.host.newChat(this.cwd) }, "Nouveau chat")));
        return;
      }
      const ctx = { api: this.api, opened: this.host.opened(), resume: (c) => this.host.resume(c) };
      for (const c of convs.slice(0, shown)) box.append(convRow(c, ctx, { showProject: false }));
      if (convs.length > shown) box.append(el("button", { class: "flat more", onclick: () => { shown += STEP; draw(); } }, `Voir plus (${convs.length - shown})`));
    };
    draw();
  }

  destroy() { for (const off of this.offs) off(); this.git?.destroy?.(); this.node.remove(); }
}
