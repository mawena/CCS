// Fichiers d'un projet : arbre (chargé dossier par dossier, marques git), recherche par nom,
// fichier ouvert (lecture, image, ouverture à une ligne, retour à la ligne au choix, édition
// simple avec enregistrement et conflit signalé, aperçu Markdown rendu par le pont), gestion
// (créer, envoyer, renommer, supprimer, télécharger : files-manage.js).
import { clear, confirmSheet, el, errorState, loading, setHtml, toast } from "./dom.js";
import { clipboard, download, FileManager, icon, kindOf, label } from "./files-manage.js";

export { icon, kindOf, label };

const MARKS = { M: "modifié", A: "ajouté", "?": "nouveau", D: "supprimé" };
const WRAP_KEY = "ccs-file-wrap";
const CODE_LINES = 5000;        // au-delà, la lecture reste dans la zone de texte (pas de numéros)

const typeIcon = (name, dir = false) => { const k = kindOf(name, dir); return icon(k, `k-${k}`); };

export class FilesPanel {
  // opts.extra : actions en plus sur les dossiers (gestionnaire de fichiers), voir FileManager.
  constructor(container, api, root, opts = {}) {
    this.api = api;
    this.root = root;
    this.selected = null;
    this.node = el("div", { class: "files" });
    this.tree = el("ul", { class: "tree" });
    this.results = el("div", { class: "file-results", hidden: true });
    this.search = el("input", { type: "search", class: "file-search", placeholder: "Chercher un fichier par nom",
      "aria-label": "Chercher un fichier", autocapitalize: "off", autocomplete: "off", spellcheck: "false" });
    this.search.addEventListener("input", () => { clearTimeout(this.timer); this.timer = setTimeout(() => this.find(), 300); });
    this.manager = new FileManager(api, root, opts.extra || null);
    const top = (name, text, run) => el("button", { type: "button", class: "small file-tool", title: text,
      onclick: async () => { if (await run()) this.expand(this.tree, ""); } }, icon(name), label(text));
    this.tools = el("div", { class: "file-tools", role: "toolbar", "aria-label": "Actions sur ce dossier" },
      top("new-file", "+ Fichier", () => this.manager.create("", "file")),
      top("new-dir", "+ Dossier", () => this.manager.create("", "dir")),
      top("upload", "Envoyer", () => this.manager.upload("")));
    this.pasteBtn = top("paste", "Coller", () => this.manager.paste(""));
    this.pasteBtn.classList.add("paste");
    this.tools.append(this.pasteBtn);
    this.browser = el("div", { class: "file-browser" },
      el("div", { class: "file-search-box" }, icon("search"), this.search), this.tools, this.results, this.tree);
    this.node.append(this.browser);
    container.append(this.node);
    this.expand(this.tree, "");
  }

  // « Coller » n'apparaît que s'il y a quelque chose de copié ou de coupé.
  syncPaste() {
    const held = clipboard();
    const text = held ? `Coller « ${held.name} »` : "Coller";
    this.pasteBtn.hidden = !held;
    this.pasteBtn.querySelector(".btn-label").textContent = text;
    this.pasteBtn.title = text;
  }

  async expand(ul, rel) {
    this.syncPaste();
    clear(ul).append(el("li", {}, loading()));
    let r;
    try { r = await this.api.call("files.list", { root: this.root, rel }); } catch (e) {
      clear(ul).append(el("li", {}, errorState(e.message, () => this.expand(ul, rel))));
      return;
    }
    clear(ul);
    if (!r.entries.length) {
      ul.append(rel ? el("li", { class: "subtle file-empty" }, "Dossier vide.")
        : el("li", { class: "file-empty root" }, icon("dir", "big"), el("p", {}, "Ce dossier est vide."),
          el("p", { class: "subtle" }, "Crée un fichier ou envoies-en un avec les boutons ci-dessus.")));
    }
    for (const entry of r.entries) {
      const mark = entry.mark ? el("span", { class: `mark m-${entry.mark === "?" ? "n" : entry.mark}`, title: MARKS[entry.mark] || "" }, entry.mark) : null;
      const name = el("span", { class: "grow tree-name", title: entry.name }, entry.name);
      if (entry.dir) {
        const sub = el("ul", { class: "tree", hidden: true });
        const row = el("button", { class: "tree-row dir", "aria-expanded": "false", onclick: () => {
          sub.hidden = !sub.hidden;
          row.classList.toggle("open", !sub.hidden);
          row.setAttribute("aria-expanded", String(!sub.hidden));
          if (!sub.hidden && !sub.dataset.loaded) { sub.dataset.loaded = "1"; this.expand(sub, entry.path); }
        } }, el("span", { class: "twisty" }, icon("chevron")), typeIcon(entry.name, true), name, mark);
        const inside = () => {
          sub.dataset.loaded = "1"; sub.hidden = false;
          row.classList.add("open"); row.setAttribute("aria-expanded", "true");
          this.expand(sub, entry.path);
        };
        ul.append(el("li", {}, el("div", { class: "tree-line" }, row, this.more(entry, () => this.expand(ul, rel), inside)), sub));
      } else {
        ul.append(el("li", {}, el("div", { class: `tree-line${entry.path === this.selected ? " current" : ""}`, dataset: { path: entry.path } },
          el("button", { class: "tree-row", onclick: () => this.open(entry.path) },
            el("span", { class: "twisty" }), typeIcon(entry.name), name, mark),
          this.save(entry), this.more(entry, () => this.expand(ul, rel)))));
      }
    }
    if (r.truncated) ul.append(el("li", { class: "subtle file-empty" }, "(dossier trop long : liste coupée)"));
  }

  // Bouton « télécharger » d'un fichier : le télécharge tout de suite, sans passer par le menu.
  save(entry) {
    return el("button", { type: "button", class: "flat tree-save", "aria-label": `Télécharger ${entry.name}`, title: "Télécharger",
      onclick: () => download(this.api, this.manager.abs(entry.path)) }, icon("download"));
  }

  // Bouton « ⋯ » d'une entrée : ses actions de gestion ; recharge ensuite le dossier touché.
  more(entry, reload, inside = null) {
    return el("button", { type: "button", class: "flat tree-more", "aria-label": `Actions sur ${entry.name}`, title: "Actions",
      onclick: async () => {
        const r = await this.manager.menu(entry);
        this.syncPaste();
        if (r.all) this.expand(this.tree, "");        // déplacement : l'ancien dossier a changé aussi
        else if (r.changed) (r.inside && inside ? inside : reload)();
      } }, icon("more"));
  }

  // Recherche par nom dans tout l'arbre (méthode bornée du pont) ; champ vide : retour à l'arbre.
  async find() {
    const query = this.search.value.trim();
    this.results.hidden = !query;
    this.tree.hidden = this.tools.hidden = Boolean(query);
    if (!query) return;
    clear(this.results).append(loading("Recherche…"));
    let r;
    try { r = await this.api.call("files.search", { root: this.root, query }); } catch (e) {
      if (query === this.search.value.trim()) clear(this.results).append(errorState(e.message, () => this.find()));
      return;
    }
    if (query !== this.search.value.trim()) return;           // une frappe plus récente a pris le relais
    const files = r.entries.filter((e) => !e.dir);
    clear(this.results);
    if (!files.length) {
      this.results.append(el("div", { class: "file-empty root" }, icon("search", "big"), el("p", { class: "subtle" }, `Aucun fichier nommé « ${query} ».`)));
      return;
    }
    for (const f of files) {
      const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
      this.results.append(el("button", { class: "tree-row found", title: f.path, onclick: () => this.open(f.path) }, typeIcon(f.name),
        el("span", { class: "grow found-text" }, el("strong", {}, f.name), dir ? el("span", { class: "subtle" }, dir) : null)));
    }
    if (r.truncated) this.results.append(el("p", { class: "subtle file-empty" }, "Trop de résultats : précise ta recherche."));
  }

  // Un seul fichier ouvert à la fois : en ouvrir un autre remplace le premier (avec confirmation s'il
  // a des modifications non enregistrées). Renvoie false si l'utilisateur a gardé le premier.
  async open(relpath, opts = {}) {
    if (this.current && !await this.current.view.confirmLeave()) return false;
    this.current?.holder.remove();
    this.browser.hidden = true;
    this.selected = relpath;                       // au retour, la ligne du fichier reste en évidence
    for (const line of this.tree.querySelectorAll(".tree-line")) line.classList.toggle("current", line.dataset.path === relpath);
    const holder = el("div", { class: "file-holder" });
    this.node.append(holder);
    const view = new FileView(holder, this.api, `${this.root}/${relpath}`, () => {
      holder.remove();
      if (this.current && this.current.holder === holder) this.current = null;
      this.browser.hidden = false;
    }, opts);
    this.current = { holder, view };
    return true;
  }

  // Fichier cité dans le chat : chemin absolu dans le projet ou relatif ; `line` : ligne à montrer.
  openFile(path, { line = null } = {}) {
    const rel = path.startsWith(`${this.root}/`) ? path.slice(this.root.length + 1) : path.replace(/^\.?\/+/, "");
    return this.open(rel, { line });
  }

  // Modifications non enregistrées dans le fichier ouvert ?
  get dirty() { return Boolean(this.current?.view.dirty); }
}

export class FileView {
  constructor(container, api, path, onBack, opts = {}) {
    this.api = api;
    this.path = path;
    this.line = Number.isInteger(opts.line) && opts.line > 0 ? opts.line : null;
    this.stamp = null;
    this.dirty = false;
    this.wrap = localStorage.getItem(WRAP_KEY) === "1";
    this.text = el("textarea", { class: "file-text", spellcheck: "false", readonly: true, wrap: "off", hidden: true });
    this.text.addEventListener("input", () => { this.dirty = true; });
    this.code = el("div", { class: "file-code", hidden: true });
    this.image = el("div", { class: "file-image", hidden: true });
    this.preview = el("div", { class: "file-preview", hidden: true });
    this.state = el("div", { class: "file-state" });
    this.editBtn = el("button", { class: "small", hidden: true, title: "Modifier", onclick: () => this.edit() }, icon("edit"), label("Modifier"));
    this.saveBtn = el("button", { class: "small primary", hidden: true, title: "Enregistrer", onclick: () => this.save() }, icon("save"), label("Enregistrer"));
    this.wrapBtn = el("button", { class: "small flat icon-only", hidden: true, title: "Retour à la ligne", "aria-label": "Retour à la ligne",
      "aria-pressed": String(this.wrap), onclick: () => this.toggleWrap() }, icon("wrap"));
    const md = /\.(md|markdown)$/i.test(path);
    this.mdBtn = md ? el("button", { class: "small", hidden: true, title: "Aperçu", onclick: () => this.togglePreview() }, icon("eye"), label("Aperçu")) : null;
    const back = async () => { if (await this.confirmLeave()) onBack(); };
    const name = path.split("/").pop();
    const dir = path.slice(0, Math.max(0, path.length - name.length - 1));
    container.append(el("div", { class: "file-head" },
      el("button", { class: "small flat icon-only", "aria-label": "Retour", title: "Retour", onclick: back }, icon("back")),
      typeIcon(name),
      el("div", { class: "grow file-title" }, el("strong", { class: "file-name", title: path }, name),
        dir ? el("span", { class: "subtle file-dir", title: dir }, dir) : null),
      el("div", { class: "file-actions" },
        el("button", { class: "small flat icon-only", "aria-label": "Télécharger", title: "Télécharger", onclick: () => download(this.api, this.path) }, icon("download")),
        this.wrapBtn, this.mdBtn, this.editBtn, this.saveBtn)),
      this.state, this.text, this.code, this.image, this.preview);
    this.applyWrap();
    this.load();
  }

  // Vrai si l'on peut quitter ce fichier : rien de modifié, ou l'utilisateur abandonne ses changements.
  async confirmLeave() {
    if (!this.dirty) return true;
    return confirmSheet({ title: "Abandonner les modifications ?", body: "Elles ne sont pas enregistrées.",
      confirm: "Abandonner", danger: true });
  }

  fail(message) {
    clear(this.state).append(errorState(message, () => this.load()));
    for (const n of [this.text, this.code, this.image, this.editBtn, this.wrapBtn]) n.hidden = true;
  }

  async load() {
    clear(this.state).append(loading());
    let r;
    try { r = await this.api.call("files.read", { path: this.path }); } catch (e) { this.fail(e.message); return; }
    this.stamp = r.stamp;
    if (r.kind === "image") { await this.loadImage(); return; }
    if (r.kind !== "text") {
      clear(this.state).append(el("div", { class: "state empty file-unseen" }, icon(kindOf(this.path.split("/").pop()), "big"),
        el("p", {}, r.kind === "binary" ? "Fichier binaire : il n'est pas affiché." : "Fichier trop gros pour être affiché ici."),
        el("div", { class: "state-actions" },
          el("button", { class: "small", onclick: () => download(this.api, this.path) }, icon("download"), label("Télécharger")))));
      return;
    }
    clear(this.state);
    this.text.value = r.text;
    this.dirty = false;
    this.editBtn.hidden = false;
    this.wrapBtn.hidden = false;
    if (this.mdBtn) this.mdBtn.hidden = false;
    const lines = r.text.split("\n");
    if (this.line && lines.length <= CODE_LINES) this.showCode(lines);
    else this.text.hidden = false;
  }

  async loadImage() {
    let r;
    try { r = await this.api.call("files.image", { path: this.path }); } catch (e) { this.fail(e.message); return; }
    clear(this.state);
    clear(this.image).append(el("img", { src: `data:${r.mime};base64,${r.data}`, alt: this.path.split("/").pop(), class: "file-img" }));
    this.image.hidden = false;
  }

  // Lecture à une ligne donnée : numéros de ligne, la ligne cherchée marquée et amenée à l'écran.
  showCode(lines) {
    clear(this.code);
    const hit = this.line;
    const rows = lines.map((t, i) => el("div", { class: `code-line${i + 1 === hit ? " hit" : ""}`, id: `L${i + 1}` },
      el("span", { class: "code-no" }, String(i + 1)), el("span", { class: "code-text" }, t || " ")));
    this.code.append(...rows);
    this.code.hidden = false;
    this.text.hidden = true;
    const target = rows[Math.min(hit, rows.length) - 1];
    if (target) requestAnimationFrame(() => target.scrollIntoView({ block: "center" }));
  }

  applyWrap() {
    this.text.setAttribute("wrap", this.wrap ? "soft" : "off");
    this.text.classList.toggle("wrap", this.wrap);
    this.code.classList.toggle("wrap", this.wrap);
    this.preview.classList.toggle("wrap", this.wrap);
    this.wrapBtn.setAttribute("aria-pressed", String(this.wrap));
    this.wrapBtn.classList.toggle("on", this.wrap);
  }

  toggleWrap() {
    this.wrap = !this.wrap;
    localStorage.setItem(WRAP_KEY, this.wrap ? "1" : "0");
    this.applyWrap();
  }

  edit() {
    if (!this.code.hidden) {                       // de la vue à numéros à la zone de texte, à la même ligne
      this.code.hidden = true;
      this.text.hidden = false;
      const before = this.text.value.split("\n").slice(0, (this.line || 1) - 1).join("\n").length;
      this.text.setSelectionRange(before, before);
      const lh = parseFloat(getComputedStyle(this.text).lineHeight) || 18;
      this.text.scrollTop = Math.max(0, ((this.line || 1) - 3) * lh);
    }
    this.text.readOnly = false;
    this.text.classList.add("editing");
    this.text.focus();
    this.editBtn.hidden = true;
    this.saveBtn.hidden = false;
  }

  async save() {
    if (this.saving) return;
    this.saving = true;                          // un double appui enverrait deux écritures : faux conflit
    this.saveBtn.disabled = true;
    try {
      const r = await this.api.call("files.write", { path: this.path, text: this.text.value, stamp: this.stamp });
      this.stamp = r.stamp;
      this.dirty = false;
      this.text.readOnly = true;
      this.text.classList.remove("editing");
      this.saveBtn.hidden = true;
      this.editBtn.hidden = false;
      toast("Enregistré.", { kind: "success" });
    } catch (e) {
      toast(e.code === "conflit"
        ? "Le fichier a changé depuis son ouverture (Claude l'a peut-être modifié) : copie tes changements, puis rouvre-le."
        : e.message, { kind: "error", action: e.code === "conflit" ? null : { label: "Réessayer", run: () => this.save() } });
    } finally {
      this.saving = false;
      this.saveBtn.disabled = false;
    }
  }

  async togglePreview() {
    const show = this.preview.hidden;
    this.preview.hidden = !show;
    this.code.hidden = show || !this.code.children.length;
    this.text.hidden = show || Boolean(this.code.children.length);
    const text = show ? "Source" : "Aperçu";
    this.mdBtn.querySelector(".btn-label").textContent = text;
    this.mdBtn.title = text;
    this.mdBtn.firstChild.replaceWith(icon(show ? "code" : "eye"));
    if (show) {
      clear(this.preview).append(loading());
      try { setHtml(this.preview, (await this.api.call("chat.render", { markdown: this.text.value })).html); } catch (e) {
        clear(this.preview).append(errorState(e.message, () => { this.preview.hidden = true; this.togglePreview(); }));
      }
    }
  }
}
