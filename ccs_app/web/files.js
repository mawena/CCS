// Fichiers d'un projet : arbre (chargé dossier par dossier, marques git), recherche par nom,
// fichier ouvert (lecture, image, ouverture à une ligne, retour à la ligne au choix, édition
// simple avec enregistrement et conflit signalé, aperçu Markdown rendu par le pont), gestion
// (créer, envoyer, renommer, supprimer, télécharger : files-manage.js).
import { clear, confirmSheet, el, errorState, loading, setHtml, toast } from "./dom.js";
import { download, FileManager } from "./files-manage.js";

const MARKS = { M: "modifié", A: "ajouté", "?": "nouveau", D: "supprimé" };
const WRAP_KEY = "ccs-file-wrap";
const CODE_LINES = 5000;        // au-delà, la lecture reste dans la zone de texte (pas de numéros)

export class FilesPanel {
  constructor(container, api, root) {
    this.api = api;
    this.root = root;
    this.node = el("div", { class: "files" });
    this.tree = el("ul", { class: "tree" });
    this.results = el("div", { class: "file-results", hidden: true });
    this.search = el("input", { type: "search", class: "file-search", placeholder: "Chercher un fichier par nom",
      "aria-label": "Chercher un fichier", autocapitalize: "off", autocomplete: "off", spellcheck: "false" });
    this.search.addEventListener("input", () => { clearTimeout(this.timer); this.timer = setTimeout(() => this.find(), 300); });
    this.manager = new FileManager(api, root);
    const top = (label, run) => el("button", { type: "button", class: "small flat", onclick: async () => { if (await run()) this.expand(this.tree, ""); } }, label);
    this.tools = el("div", { class: "file-tools" },
      top("+ Fichier", () => this.manager.create("", "file")), top("+ Dossier", () => this.manager.create("", "dir")),
      top("Envoyer", () => this.manager.upload("")));
    this.browser = el("div", { class: "file-browser" }, this.search, this.tools, this.results, this.tree);
    this.node.append(this.browser);
    container.append(this.node);
    this.expand(this.tree, "");
  }

  async expand(ul, rel) {
    clear(ul).append(el("li", {}, loading()));
    let r;
    try { r = await this.api.call("files.list", { root: this.root, rel }); } catch (e) {
      clear(ul).append(el("li", {}, errorState(e.message, () => this.expand(ul, rel))));
      return;
    }
    clear(ul);
    if (!r.entries.length) ul.append(el("li", { class: "subtle file-empty" }, rel ? "Dossier vide." : "Ce dossier est vide."));
    for (const entry of r.entries) {
      const mark = entry.mark ? el("span", { class: `mark m-${entry.mark === "?" ? "n" : entry.mark}`, title: MARKS[entry.mark] || "" }, entry.mark) : null;
      if (entry.dir) {
        const sub = el("ul", { class: "tree", hidden: true });
        const row = el("button", { class: "tree-row dir", onclick: () => {
          sub.hidden = !sub.hidden;
          row.classList.toggle("open", !sub.hidden);
          if (!sub.hidden && !sub.dataset.loaded) { sub.dataset.loaded = "1"; this.expand(sub, entry.path); }
        } }, el("span", { class: "twisty" }, "▸"), el("span", { class: "grow" }, entry.name), mark);
        const inside = () => { sub.dataset.loaded = "1"; sub.hidden = false; row.classList.add("open"); this.expand(sub, entry.path); };
        ul.append(el("li", {}, el("div", { class: "tree-line" }, row, this.more(entry, () => this.expand(ul, rel), inside)), sub));
      } else {
        ul.append(el("li", {}, el("div", { class: "tree-line" },
          el("button", { class: "tree-row", onclick: () => this.open(entry.path) },
            el("span", { class: "twisty" }, " "), el("span", { class: "grow" }, entry.name), mark),
          this.save(entry), this.more(entry, () => this.expand(ul, rel)))));
      }
    }
    if (r.truncated) ul.append(el("li", { class: "subtle" }, "(dossier trop long : liste coupée)"));
  }

  // Bouton « ⤓ » d'un fichier : le télécharge tout de suite, sans passer par le menu.
  save(entry) {
    return el("button", { type: "button", class: "flat tree-save", "aria-label": `Télécharger ${entry.name}`, title: "Télécharger",
      onclick: () => download(this.api, this.manager.abs(entry.path)) }, "⤓");
  }

  // Bouton « ⋯ » d'une entrée : ses actions de gestion ; recharge ensuite le dossier touché.
  more(entry, reload, inside = null) {
    return el("button", { type: "button", class: "flat tree-more", "aria-label": `Actions sur ${entry.name}`, title: "Actions",
      onclick: async () => {
        const r = await this.manager.menu(entry);
        if (r.changed) (r.inside && inside ? inside : reload)();
      } }, "⋯");
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
    if (!files.length) { this.results.append(el("p", { class: "subtle file-empty" }, `Aucun fichier nommé « ${query} ».`)); return; }
    for (const f of files) {
      const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
      this.results.append(el("button", { class: "tree-row found", onclick: () => this.open(f.path) },
        el("span", { class: "grow" }, el("strong", {}, f.name), dir ? el("span", { class: "subtle" }, ` ${dir}`) : null)));
    }
    if (r.truncated) this.results.append(el("p", { class: "subtle" }, "Trop de résultats : précise ta recherche."));
  }

  // Un seul fichier ouvert à la fois : en ouvrir un autre remplace le premier (avec confirmation s'il
  // a des modifications non enregistrées). Renvoie false si l'utilisateur a gardé le premier.
  async open(relpath, opts = {}) {
    if (this.current && !await this.current.view.confirmLeave()) return false;
    this.current?.holder.remove();
    this.browser.hidden = true;
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
    this.editBtn = el("button", { class: "small", hidden: true, onclick: () => this.edit() }, "Modifier");
    this.saveBtn = el("button", { class: "small primary", hidden: true, onclick: () => this.save() }, "Enregistrer");
    this.wrapBtn = el("button", { class: "small flat", hidden: true, title: "Retour à la ligne", "aria-pressed": String(this.wrap),
      onclick: () => this.toggleWrap() }, "↩");
    const md = /\.(md|markdown)$/i.test(path);
    this.mdBtn = md ? el("button", { class: "small", hidden: true, onclick: () => this.togglePreview() }, "Aperçu") : null;
    const back = async () => { if (await this.confirmLeave()) onBack(); };
    container.append(el("div", { class: "file-head" },
      el("button", { class: "small flat", "aria-label": "Retour", onclick: back }, "←"),
      el("strong", { class: "grow file-name", title: path }, path.split("/").pop()),
      el("button", { class: "small flat", "aria-label": "Télécharger", title: "Télécharger", onclick: () => download(this.api, this.path) }, "⤓"),
      this.wrapBtn, this.mdBtn, this.editBtn, this.saveBtn),
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
      clear(this.state).append(el("p", { class: "subtle" }, r.kind === "binary" ? "Fichier binaire : il n'est pas affiché." : "Fichier trop gros pour être affiché ici."));
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
    this.mdBtn.textContent = show ? "Source" : "Aperçu";
    if (show) {
      clear(this.preview).append(loading());
      try { setHtml(this.preview, (await this.api.call("chat.render", { markdown: this.text.value })).html); } catch (e) {
        clear(this.preview).append(errorState(e.message, () => { this.preview.hidden = true; this.togglePreview(); }));
      }
    }
  }
}
