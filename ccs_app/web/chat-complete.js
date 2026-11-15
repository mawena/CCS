// Complétion dans la saisie du chat : `@` propose les fichiers du projet, `/` en début de message
// propose les commandes de Claude Code (comme au bureau).
import { clear, el } from "./dom.js";

const MAX_CHOICES = 8;

// Ce que le curseur est en train de taper : { kind, query, start, end } ou null.
export function detectToken(text, cursor) {
  const before = text.slice(0, cursor);
  let m = /^\/(\S*)$/.exec(before);
  if (m) return { kind: "/", query: m[1], start: 0, end: cursor };
  m = /(?:^|\s)@([^\s@]*)$/.exec(before);
  if (m) return { kind: "@", query: m[1], start: cursor - m[1].length - 1, end: cursor };
  return null;
}

const base = (f) => f.slice(f.lastIndexOf("/") + 1);

export function rankFiles(files, query) {
  const q = query.toLowerCase();
  return files.filter((f) => f.toLowerCase().includes(q))
    .sort((a, b) => (base(a).toLowerCase().startsWith(q) ? 0 : 1) - (base(b).toLowerCase().startsWith(q) ? 0 : 1) || a.length - b.length || a.localeCompare(b));
}

export function rankCommands(commands, query) {
  const q = query.toLowerCase();
  return commands.filter((c) => c.name.toLowerCase().includes(q))
    .sort((a, b) => (a.name.toLowerCase().startsWith(q) ? 0 : 1) - (b.name.toLowerCase().startsWith(q) ? 0 : 1) || a.name.localeCompare(b.name));
}

export class Completer {
  // sources : { commands(): Promise<[{name, description, hint}]>, files(): Promise<[chemin]> }
  constructor({ input, host, sources, onChange }) {
    this.input = input;
    this.sources = sources;
    this.onChange = onChange;
    this.token = null;
    this.items = [];
    this.at = 0;
    this.seq = 0;
    this.list = el("div", { class: "complete", role: "listbox", hidden: true, "aria-label": "Suggestions" });
    host.append(this.list);
    input.addEventListener("input", () => this.update());
    input.addEventListener("click", () => this.update());
    input.addEventListener("blur", () => setTimeout(() => this.close(), 150));
  }

  get open() { return !this.list.hidden; }

  async update() {
    const token = detectToken(this.input.value, this.input.selectionStart ?? this.input.value.length);
    const seq = ++this.seq;
    if (!token) { this.close(); return; }
    let items;
    try {
      if (token.kind === "/") {
        items = rankCommands(await this.sources.commands(), token.query).slice(0, MAX_CHOICES)
          .map((c) => ({ title: `/${c.name}`, sub: [c.hint, c.description].filter(Boolean).join(" · "), insert: `/${c.name} ` }));
      } else {
        items = rankFiles(await this.sources.files(), token.query).slice(0, MAX_CHOICES)
          .map((f) => ({ title: base(f), sub: f.includes("/") ? f.slice(0, f.lastIndexOf("/")) : "", insert: `@${f} ` }));
      }
    } catch { items = []; }
    if (seq !== this.seq) return;               // une frappe plus récente a pris le relais
    if (!items.length) { this.close(); return; }
    this.token = token;
    this.items = items;
    this.at = 0;
    this.draw();
  }

  draw() {
    clear(this.list).hidden = false;
    this.items.forEach((it, i) => {
      const row = el("button", { type: "button", class: `choice${i === this.at ? " current" : ""}`, role: "option",
        "aria-selected": i === this.at ? "true" : "false" }, el("strong", {}, it.title), el("span", { class: "subtle" }, it.sub));
      row.addEventListener("mousedown", (e) => e.preventDefault());
      row.addEventListener("click", () => this.pick(i));
      this.list.append(row);
    });
  }

  close() {
    this.seq++;
    this.list.hidden = true;
    this.items = [];
  }

  pick(i) {
    const it = this.items[i];
    if (!it || !this.token) return;
    const v = this.input.value;
    this.input.value = v.slice(0, this.token.start) + it.insert + v.slice(this.token.end);
    const pos = this.token.start + it.insert.length;
    this.input.setSelectionRange(pos, pos);
    this.close();
    this.input.focus();
    this.onChange();
  }

  // Touches clavier quand la liste est ouverte ; vrai si la touche a été prise.
  key(e) {
    if (!this.open) return false;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      this.at = (this.at + (e.key === "ArrowDown" ? 1 : this.items.length - 1)) % this.items.length;
      this.draw();
    } else if (e.key === "Enter" || e.key === "Tab") this.pick(this.at);
    else if (e.key === "Escape") this.close();
    else return false;
    e.preventDefault();
    return true;
  }
}
