// Git du projet au web (phase 14) : branche, avance / retard, fichiers modifiés, diff coloré,
// indexation par fichier et par bloc, commit (amend, message proposé), fetch / pull / push
// (push forcé gardé par une confirmation), derniers commits par pages de 50. Volet ouvert depuis
// le chat (bouton « Git ») et depuis l'écran Projet ; les méthodes `git.*` sont dans bridge_git.py.
import { ago, clear, confirmSheet, el, emptyState, loading, toast } from "./dom.js";

const MARKS = { M: "modifié", T: "type changé", A: "ajouté", D: "supprimé", R: "renommé", C: "copié", U: "en conflit", "?": "non suivi" };
const markClass = (c) => (c === "?" ? "q" : c);

export class GitPanel {
  constructor(container, api, cwd) {
    this.api = api;
    this.cwd = cwd;
    this.dead = false;
    this.view = "changes";
    this.status = null;
    this.open = new Map();          // « côté:chemin » → diff chargé (ou null pendant le chargement)
    this.log = { commits: [], more: false, loaded: false };
    this.working = false;
    this.errorBox = el("div", { "aria-live": "polite" });
    this.head = el("div", { class: "git-head" });
    this.tabs = el("div", { class: "git-tabs", role: "group", "aria-label": "Affichage Git" });
    this.files = el("div", { class: "stack" });
    this.logBox = el("div", { class: "git-commits" });
    this.message = el("textarea", { rows: "4", placeholder: "Message du commit", "aria-label": "Message du commit" });
    this.amend = el("input", { type: "checkbox" });
    this.commitBtn = el("button", { class: "primary", onclick: () => this.commit() }, "Commit");
    this.proposeBtn = el("button", { class: "small flat", onclick: () => this.propose() }, "Message proposé");
    this.amend.addEventListener("change", () => this.onAmend());
    this.commitBox = el("section", { class: "git-commit stack" }, this.message,
      el("label", { class: "check" }, this.amend, "Modifier le dernier commit (amend)"),
      el("div", { class: "row" }, this.commitBtn, this.proposeBtn));
    this.changesView = el("div", { class: "stack" }, this.files, this.commitBox);
    this.node = el("div", { class: "git" }, this.errorBox, this.head, this.tabs, this.changesView, this.logBox);
    container.append(this.node);
    this.drawTabs();
    clear(this.files).append(loading());
    this.refresh();
  }

  destroy() { this.dead = true; this.node.remove(); }

  call(method, params = {}) { return this.api.call(method, { cwd: this.cwd, ...params }); }

  // ---- erreurs et opérations -----------------------------------------------------------

  fail(e, retry = null) {
    if (this.dead) return;
    clear(this.errorBox).append(el("div", { class: "git-error", role: "alert" }, el("span", {}, e.message || String(e)),
      retry ? el("button", { class: "small flat", onclick: retry }, "Réessayer") : null,
      el("button", { class: "small flat", "aria-label": "Fermer l'erreur", onclick: () => clear(this.errorBox) }, "×")));
  }

  // Lance une opération d'écriture : boutons gelés, erreur dans le bandeau, puis rechargement.
  async run(action, done = "") {
    if (this.working) return false;
    this.working = true;
    this.render();
    clear(this.errorBox);
    let ok = false;
    try {
      await action();
      ok = true;
      if (done) toast(done, { kind: "success" });
    } catch (e) { this.fail(e); }
    this.working = false;
    await this.refresh();
    return ok;
  }

  // ---- lecture -------------------------------------------------------------------------

  async refresh() {
    try { this.status = await this.call("git.status"); } catch (e) {
      if (!this.status) clear(this.files).append(emptyState("Git est indisponible pour ce dossier."));
      this.fail(e, () => this.refresh());
      return;
    }
    if (this.dead) return;
    const keys = new Set(this.status.files.flatMap((f) => [f.staged !== "." && f.staged !== "?" ? `staged:${f.path}` : null,
      f.unstaged !== "." ? `work:${f.path}` : null].filter(Boolean)));
    for (const key of [...this.open.keys()]) if (!keys.has(key)) this.open.delete(key);
    await Promise.all([...this.open.keys()].map((key) => this.loadDiff(key, false)));
    this.render();
    if (this.view === "log") this.loadLog(true);
  }

  async loadDiff(key, draw = true) {
    const [side, ...rest] = key.split(":");
    try {
      this.open.set(key, (await this.call("git.diff", { path: rest.join(":"), staged: side === "staged" })).diff || { hunks: [], empty: true });
    } catch (e) { this.open.delete(key); this.fail(e); }
    if (draw && !this.dead) this.render();
  }

  async loadLog(reset) {
    const skip = reset ? 0 : this.log.commits.length;
    try {
      const r = await this.call("git.log", { skip });
      this.log = { commits: reset ? r.commits : [...this.log.commits, ...r.commits], more: r.more, loaded: true };
    } catch (e) { this.fail(e); }
    if (!this.dead) this.render();
  }

  // ---- affichage -----------------------------------------------------------------------

  drawTabs() {
    clear(this.tabs).append(...[["changes", "Changements"], ["log", "Historique"]].map(([v, label]) => el("button", {
      class: "small", "aria-pressed": String(this.view === v),
      onclick: () => { this.view = v; this.drawTabs(); this.render(); if (v === "log" && !this.log.loaded) this.loadLog(true); },
    }, label)));
  }

  render() {
    const st = this.status;
    this.changesView.hidden = this.view !== "changes" || !st?.repo;
    this.logBox.hidden = this.view !== "log" || !st?.repo;
    this.tabs.hidden = !st?.repo;
    if (!st) return;
    if (!st.repo) {
      clear(this.head);
      clear(this.files).append(emptyState("Ce dossier n'est pas un dépôt git."));
      this.changesView.hidden = false;
      this.commitBox.hidden = true;
      return;
    }
    this.commitBox.hidden = false;
    this.drawHead(st);
    this.drawFiles(st);
    this.drawLog();
    const staged = st.files.some((f) => f.staged !== "." && f.staged !== "?");
    this.commitBtn.disabled = this.working || (!staged && !this.amend.checked);
    this.proposeBtn.disabled = this.working || !st.proposed;
    this.proposeBtn.hidden = !st.proposed;
  }

  btn(label, onclick, opts = {}) {
    return el("button", { class: `small ${opts.cls || ""}`, disabled: this.working, "aria-label": opts.aria, onclick }, label);
  }

  drawHead(st) {
    const b = st.branch;
    const sync = [b.ahead ? `↑${b.ahead}` : "", b.behind ? `↓${b.behind}` : ""].filter(Boolean).join(" ");
    clear(this.head).append(
      el("span", { class: "branch" }, b.name || "HEAD détachée"),
      el("span", { class: "subtle" }, b.upstream ? `${b.upstream}${sync ? ` · ${sync}` : " · à jour"}` : "pas de suivi distant"),
      el("div", { class: "git-sync" },
        this.btn("Fetch", () => this.run(() => this.call("git.fetch"), "Fetch terminé.")),
        this.btn(b.behind ? `Pull ↓${b.behind}` : "Pull", () => this.run(() => this.call("git.pull"), "Pull terminé.")),
        this.btn(b.ahead ? `Push ↑${b.ahead}` : "Push", () => this.push(false)),
        this.btn("Push forcé…", () => this.push(true), { cls: "flat" })));
  }

  async push(force) {
    const b = this.status.branch;
    const ok = force
      ? await confirmSheet({ title: "Push forcé ?", confirm: "Pousser de force", danger: true,
        body: "Le dépôt distant sera écrasé par ta branche (avec garde-fou : refusé si quelqu'un a poussé entre-temps)." })
      : await confirmSheet({ title: b.name ? `Pousser « ${b.name} » ?` : "Pousser ?", confirm: "Pousser",
        body: b.upstream ? (b.ahead ? `${b.ahead} commit(s) partiront vers ${b.upstream}.` : "Rien de nouveau à pousser.")
          : "Le premier push crée la branche sur le dépôt distant." });
    if (ok) await this.run(() => this.call("git.push", { force }), force ? "Push forcé terminé." : "Push terminé.");
  }

  drawFiles(st) {
    const staged = st.files.filter((f) => f.staged !== "." && f.staged !== "?");
    const work = st.files.filter((f) => f.unstaged !== "." && f.unstaged !== "?");
    const untracked = st.files.filter((f) => f.staged === "?");
    clear(this.files);
    if (!st.files.length) { this.files.append(emptyState("Rien à valider : le dossier est propre.")); return; }
    this.group("Indexés", staged, "staged", (f) => f.staged, "Désindexer", "git.unstage", "Tout désindexer");
    this.group("Modifiés", work, "work", (f) => f.unstaged, "Indexer", "git.stage", "Tout indexer");
    this.group("Non suivis", untracked, "work", () => "?", "Indexer", "git.stage", "Tout indexer");
  }

  group(title, files, side, letter, verb, method, allLabel) {
    if (!files.length) return;
    const box = el("section", { class: "git-group" },
      el("div", { class: "row" }, el("h3", { class: "grow" }, `${title} (${files.length})`),
        this.btn(allLabel, () => this.run(() => this.call(method, { paths: files.map((f) => f.path) })), { cls: "flat" })));
    for (const f of files) {
      const key = `${side}:${f.path}`;
      const l = letter(f);
      const isOpen = this.open.has(key);
      box.append(el("div", { class: "git-file" },
        el("span", { class: `mark ${markClass(l)}`, title: MARKS[l] || "", "aria-label": MARKS[l] || l }, l),
        el("button", { class: "name", "aria-expanded": String(isOpen), title: f.path, onclick: () => this.toggle(key) }, f.path),
        this.btn(verb, () => this.run(() => this.call(method, { paths: [f.path] })), { aria: `${verb} ${f.path}` })));
      if (isOpen) box.append(this.diffNode(key, f, side, l));
    }
    this.files.append(box);
  }

  async toggle(key) {
    if (this.open.has(key)) { this.open.delete(key); this.render(); return; }
    this.open.set(key, null);
    this.render();
    await this.loadDiff(key);
  }

  diffNode(key, f, side, letter) {
    const d = this.open.get(key);
    if (d === null) return loading("Chargement du diff…");
    if (d.empty || (!d.hunks.length && !d.binary)) return el("p", { class: "subtle" }, "Pas de différence à montrer.");
    if (d.binary) return el("p", { class: "subtle" }, "Fichier binaire : pas de diff.");
    const canHunk = letter !== "?" && !d.new_file && !d.deleted;     // un fichier neuf ou supprimé s'indexe en entier
    const box = el("div", { class: "diff", role: "region", "aria-label": `Diff de ${f.path}` });
    d.hunks.forEach((h, i) => {
      box.append(el("div", { class: "diff-hunk" }, el("code", {}, h.header),
        canHunk ? this.btn(side === "staged" ? "Désindexer ce bloc" : "Indexer ce bloc",
          () => this.run(() => this.call("git.hunk", { path: f.path, index: i, action: side === "staged" ? "unstage" : "stage" }))) : null));
      for (const line of h.lines) {
        box.append(el("div", { class: `diff-line ${line.kind === "+" ? "add" : line.kind === "-" ? "del" : ""}` },
          el("span", {}, line.old_no ?? ""), el("span", {}, line.new_no ?? ""), el("span", {}, line.kind === " " ? "" : line.kind),
          el("span", {}, line.text)));
      }
    });
    if (d.truncated) box.append(el("p", { class: "subtle" }, "Diff tronqué : seules les premières lignes sont montrées."));
    return box;
  }

  // ---- commit --------------------------------------------------------------------------

  propose() {
    if (this.status?.proposed) { this.message.value = this.status.proposed; this.message.focus(); }
  }

  onAmend() {
    if (this.amend.checked && !this.message.value.trim() && this.status?.last_message) this.message.value = this.status.last_message;
    this.render();
  }

  async commit() {
    const message = this.message.value;
    if (!message.trim()) { this.fail(new Error("Écris le message du commit.")); this.message.focus(); return; }
    const amend = this.amend.checked;
    if (amend && !await confirmSheet({ title: "Modifier le dernier commit ?", confirm: "Modifier",
      body: "Son contenu et son message seront remplacés. Si tu l'as déjà poussé, il faudra un push forcé." })) return;
    const ok = await this.run(() => this.call("git.commit", { message, amend }), amend ? "Commit modifié." : "Commit créé.");
    if (ok) { this.message.value = ""; this.amend.checked = false; this.render(); this.log.loaded = false; }
  }

  // ---- historique ----------------------------------------------------------------------

  drawLog() {
    clear(this.logBox);
    if (this.view !== "log") return;
    if (!this.log.loaded) { this.logBox.append(loading()); return; }
    if (!this.log.commits.length) { this.logBox.append(emptyState("Aucun commit pour l'instant.")); return; }
    for (const c of this.log.commits) {
      this.logBox.append(el("div", { class: "commit" }, el("strong", {}, c.subject),
        el("span", { class: "subtle" }, `${c.short} · ${c.author} · ${ago(c.time)}`)));
    }
    if (this.log.more) this.logBox.append(el("button", { class: "small", onclick: (e) => { e.currentTarget.disabled = true; this.loadLog(false); } }, "Plus de commits"));
  }
}
