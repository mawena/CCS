// Recherche dans le fil : sans accents ni majuscules, suivant / précédent, boucle aux extrémités.
import { el } from "./dom.js";

export function fold(s) {
  return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function findIndexes(texts, query) {
  const needle = fold(query).trim();
  if (!needle) return [];
  const out = [];
  texts.forEach((t, i) => { if (fold(t).includes(needle)) out.push(i); });
  return out;
}

export function step(at, count, dir) {
  if (!count) return -1;
  return (at + dir + count) % count;
}

// Barre de recherche posée au-dessus du fil. `blocks()` renvoie les éléments du fil (messages,
// cartes) ; `ensureAll()` charge, si besoin, tout l'historique avant de chercher.
export class FindBar {
  constructor({ blocks, ensureAll, onClose }) {
    this.blocks = blocks;
    this.ensureAll = ensureAll;
    this.onClose = onClose;
    this.hits = [];
    this.at = -1;
    this.input = el("input", { type: "search", placeholder: "Chercher dans le fil", "aria-label": "Chercher dans le fil",
      enterkeyhint: "search", autocapitalize: "none", autocomplete: "off" });
    this.count = el("span", { class: "subtle find-count", "aria-live": "polite" }, "");
    this.node = el("div", { class: "findbar", hidden: true },
      this.input, this.count,
      el("button", { type: "button", class: "small flat", "aria-label": "Précédent", onclick: () => this.go(-1) }, "▲"),
      el("button", { type: "button", class: "small flat", "aria-label": "Suivant", onclick: () => this.go(1) }, "▼"),
      el("button", { type: "button", class: "small flat", "aria-label": "Fermer la recherche", onclick: () => this.close() }, "×"));
    this.input.addEventListener("input", () => { clearTimeout(this.timer); this.timer = setTimeout(() => this.run(), 200); });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this.go(e.shiftKey ? -1 : 1); }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.close(); }
    });
  }

  get open() { return !this.node.hidden; }

  show() {
    this.node.hidden = false;
    this.input.focus();
    this.input.select();
  }

  close() {
    this.node.hidden = true;
    this.mark(null);
    this.hits = [];
    this.at = -1;
    this.onClose();
  }

  mark(current) {
    for (const b of this.blocks()) b.classList.remove("hit", "hit-current");
    for (const b of this.hits) b.classList.add("hit");
    if (current) { current.classList.add("hit-current"); current.scrollIntoView({ block: "center" }); }
  }

  async run() {
    if (!this.input.value.trim()) { this.hits = []; this.at = -1; this.count.textContent = ""; this.mark(null); return; }
    this.count.textContent = "Recherche…";
    await this.ensureAll();
    const blocks = this.blocks();
    this.hits = findIndexes(blocks.map((b) => b.textContent), this.input.value).map((i) => blocks[i]);
    this.at = this.hits.length ? this.hits.length - 1 : -1;       // on part du plus récent
    this.show_();
  }

  show_() {
    this.count.textContent = this.hits.length ? `${this.at + 1} / ${this.hits.length}` : "Rien trouvé";
    this.mark(this.hits[this.at] || null);
  }

  go(dir) {
    if (!this.hits.length) { this.run(); return; }
    this.at = step(this.at, this.hits.length, dir);
    this.show_();
  }
}
