// Fichiers d'un projet : arbre (chargé dossier par dossier, marques git), fichier ouvert (lecture,
// édition simple avec enregistrement et conflit signalé, aperçu Markdown rendu par le pont).
import { clear, el, setHtml } from "./dom.js";

const MARKS = { M: "modifié", A: "ajouté", "?": "nouveau", D: "supprimé" };

export class FilesPanel {
  constructor(container, api, root) {
    this.api = api;
    this.root = root;
    this.node = el("div", { class: "files" });
    this.tree = el("ul", { class: "tree" });
    this.node.append(this.tree);
    container.append(this.node);
    this.expand(this.tree, "");
  }

  async expand(ul, rel) {
    clear(ul).append(el("li", { class: "subtle" }, "…"));
    let r;
    try { r = await this.api.call("files.list", { root: this.root, rel }); } catch (e) {
      clear(ul).append(el("li", { class: "message" }, e.message));
      return;
    }
    clear(ul);
    for (const entry of r.entries) {
      const mark = entry.mark ? el("span", { class: `mark m-${entry.mark === "?" ? "n" : entry.mark}`, title: MARKS[entry.mark] || "" }, entry.mark) : null;
      if (entry.dir) {
        const sub = el("ul", { class: "tree", hidden: true });
        const row = el("button", { class: "tree-row dir", onclick: () => {
          sub.hidden = !sub.hidden;
          row.classList.toggle("open", !sub.hidden);
          if (!sub.hidden && !sub.dataset.loaded) { sub.dataset.loaded = "1"; this.expand(sub, entry.path); }
        } }, el("span", { class: "twisty" }, "▸"), el("span", { class: "grow" }, entry.name), mark);
        ul.append(el("li", {}, row, sub));
      } else {
        ul.append(el("li", {}, el("button", { class: "tree-row", onclick: () => this.open(entry.path) },
          el("span", { class: "twisty" }, " "), el("span", { class: "grow" }, entry.name), mark)));
      }
    }
    if (r.truncated) ul.append(el("li", { class: "subtle" }, "(dossier trop long : liste coupée)"));
  }

  open(relpath) {
    this.tree.hidden = true;
    const holder = el("div", { class: "file-holder" });
    this.node.append(holder);
    new FileView(holder, this.api, `${this.root}/${relpath}`, () => { holder.remove(); this.tree.hidden = false; });
  }
}

export class FileView {
  constructor(container, api, path, onBack) {
    this.api = api;
    this.path = path;
    this.stamp = null;
    this.text = el("textarea", { class: "file-text", spellcheck: "false", readonly: true });
    this.preview = el("div", { class: "file-preview", hidden: true });
    this.msg = el("p", { class: "message" });
    this.editBtn = el("button", { class: "small", onclick: () => this.edit() }, "Modifier");
    this.saveBtn = el("button", { class: "small primary", hidden: true, onclick: () => this.save() }, "Enregistrer");
    const md = /\.(md|markdown)$/i.test(path);
    const toggle = md ? el("button", { class: "small", onclick: () => this.togglePreview(toggle) }, "Aperçu") : null;
    container.append(el("div", { class: "file-head" },
      el("button", { class: "small flat", onclick: onBack }, "←"),
      el("strong", { class: "grow file-name", title: path }, path.split("/").pop()), toggle, this.editBtn, this.saveBtn),
      this.msg, this.text, this.preview);
    this.load();
  }

  async load() {
    let r;
    try { r = await this.api.call("files.read", { path: this.path }); } catch (e) { this.msg.textContent = e.message; return; }
    this.stamp = r.stamp;
    if (r.kind !== "text") {
      this.text.hidden = true;
      this.editBtn.hidden = true;
      this.msg.textContent = r.kind === "binary" ? "Fichier binaire : il n'est pas affiché." :
        r.kind === "image" ? "Image : ouvre-la depuis le bureau." : "Fichier trop gros pour être affiché ici.";
      return;
    }
    this.text.value = r.text;
  }

  edit() {
    this.text.readOnly = false;
    this.text.focus();
    this.editBtn.hidden = true;
    this.saveBtn.hidden = false;
  }

  async save() {
    try {
      const r = await this.api.call("files.write", { path: this.path, text: this.text.value, stamp: this.stamp });
      this.stamp = r.stamp;
      this.msg.textContent = "";
      this.text.readOnly = true;
      this.saveBtn.hidden = true;
      this.editBtn.hidden = false;
    } catch (e) {
      this.msg.textContent = e.code === "conflit"
        ? "Le fichier a changé depuis son ouverture (Claude l'a peut-être modifié) : copie tes changements, puis rouvre-le."
        : e.message;
    }
  }

  async togglePreview(btn) {
    const show = this.preview.hidden;
    this.preview.hidden = !show;
    this.text.hidden = show;
    btn.textContent = show ? "Source" : "Aperçu";
    if (show) {
      try { setHtml(this.preview, (await this.api.call("chat.render", { markdown: this.text.value })).html); } catch (e) { this.preview.textContent = e.message; }
    }
  }
}
