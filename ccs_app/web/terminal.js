// Terminal shell dans le navigateur (xterm.js, chargé par index.html) relié à un pseudo-terminal
// du pont. Après une coupure, il se rattache et réaffiche la fin de la sortie. Sur écran tactile
// ou étroit, une barre de touches complète le clavier du téléphone (Échap, Tab, Ctrl collant,
// flèches, symboles difficiles à taper), avec Coller, Copier et la taille du texte.
import { el, toast } from "./dom.js";

const KEYS = [
  ["Échap", "\x1b"], ["Tab", "\t"], ["ctrl"], ["←", "\x1b[D"], ["↓", "\x1b[B"], ["↑", "\x1b[A"], ["→", "\x1b[C"],
  ["|", "|"], ["~", "~"], ["/", "/"], ["-", "-"],
];
const FONT = { key: "ccs-term-font", min: 9, max: 24, normal: 13 };

// Ctrl + lettre (ou @ [ \ ] ^ _) devient le caractère de contrôle correspondant.
export function controlChar(data) {
  if (typeof data !== "string" || data.length !== 1) return data;
  const code = data.toUpperCase().charCodeAt(0);
  if (code >= 64 && code <= 95) return String.fromCharCode(code - 64);
  if (data === "?") return "\x7f";
  return data;
}

const wantsBar = () => matchMedia("(pointer: coarse), (max-width: 719px)").matches;

export class TerminalView {
  constructor(container, api, { cwd, command, name, termId }) {
    this.api = api;
    this.termId = termId || null;
    this.ctrl = false;
    this.lastWarn = 0;
    this.box = el("div", { class: "term" });
    this.root = el("div", { class: "term-wrap" }, this.box);
    container.append(this.root);
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    const saved = Number(localStorage.getItem(FONT.key)) || FONT.normal;
    this.term = new window.Terminal({
      fontFamily: '"JetBrains Mono", "DejaVu Sans Mono", monospace', fontSize: Math.min(FONT.max, Math.max(FONT.min, saved)),
      cursorBlink: true,
      theme: dark ? { background: "#1e1e22", foreground: "#f2f2f5" } : { background: "#ffffff", foreground: "#1e1e22", cursor: "#1e1e22" },
    });
    this.fit = new window.FitAddon.FitAddon();
    this.term.loadAddon(this.fit);
    this.term.open(this.box);
    this.fit.fit();
    this.offs = [
      api.on("term.output", (d) => { if (d.term_id === this.termId) this.term.write(d.data); }),
      api.on("term.exit", (d) => { if (d.term_id === this.termId) { this.term.write(`\r\n[terminé, code ${d.code}]\r\n`); this.exited = true; } }),
      api.on("reconnected", () => this.attach(true)),
    ];
    this.term.onData((data) => this.type(data));
    if (wantsBar()) this.root.append(this.keyBar());
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(this.box);
    if (this.termId) this.attach(false);
    else this.start(cwd, command, name);
  }

  // Envoie la saisie ; une coupure donne un toast (une fois toutes les 4 s), jamais un silence.
  send(data) {
    if (!this.termId || this.exited) return;
    this.api.call("term.input", { term_id: this.termId, data }).catch((e) => {
      const now = Date.now();
      if (now - this.lastWarn < 4000) return;
      this.lastWarn = now;
      toast(`La saisie n'est pas partie${e?.message ? ` : ${e.message}` : ""}.`, { kind: "error" });
    });
  }

  // Saisie du clavier : Ctrl collant armé, la touche suivante devient un caractère de contrôle.
  type(data) {
    if (this.ctrl) { data = controlChar(data); this.setCtrl(false); }
    this.send(data);
  }

  setCtrl(on) {
    this.ctrl = on;
    this.ctrlBtn?.classList.toggle("on", on);
    this.ctrlBtn?.setAttribute("aria-pressed", String(on));
  }

  keyBar() {
    // pointerdown + preventDefault : le bouton ne prend pas le focus, le clavier reste ouvert
    const keep = (e) => e.preventDefault();
    const btn = (label, run, extra = {}) => el("button", { type: "button", class: "small key", onpointerdown: keep, onclick: run, ...extra }, label);
    this.ctrlBtn = btn("Ctrl", () => { this.setCtrl(!this.ctrl); this.term.focus(); }, { "aria-pressed": "false", title: "Ctrl collant : la touche suivante devient Ctrl + touche" });
    const keys = KEYS.map(([label, data]) => (label === "ctrl" ? this.ctrlBtn : btn(label, () => { this.setCtrl(false); this.send(data); this.term.focus(); })));
    const tools = [
      btn("Coller", () => this.paste()),
      btn("Copier", () => this.copy()),
      btn("A−", () => this.zoom(-1), { "aria-label": "Texte plus petit" }),
      btn("A+", () => this.zoom(1), { "aria-label": "Texte plus grand" }),
    ];
    return el("div", { class: "term-keys", role: "toolbar", "aria-label": "Touches du terminal" },
      el("div", { class: "keys-row" }, ...keys), el("div", { class: "keys-row" }, ...tools));
  }

  async paste() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) this.send(text);
      else toast("Le presse-papiers est vide.");
    } catch { toast("Le navigateur refuse l'accès au presse-papiers : colle avec un appui long dans le terminal.", { kind: "error" }); }
    this.term.focus();
  }

  async copy() {
    const text = this.term.getSelection();
    if (!text) { toast("Sélectionne d'abord du texte dans le terminal."); return; }
    try { await navigator.clipboard.writeText(text); toast("Copié.", { kind: "success" }); } catch {
      toast("Le navigateur refuse l'accès au presse-papiers.", { kind: "error" });
    }
  }

  zoom(step) {
    const size = Math.min(FONT.max, Math.max(FONT.min, this.term.options.fontSize + step));
    this.term.options.fontSize = size;
    localStorage.setItem(FONT.key, String(size));
    this.resize();
  }

  async start(cwd, command, name) {
    try {
      const r = await this.api.call("term.open", { cwd, cols: this.term.cols, rows: this.term.rows,
        ...(command ? { command, name } : {}) });
      this.termId = r.term_id;
      this.term.focus();
    } catch (e) { this.term.write(`Terminal impossible : ${e.message}\r\n`); }
  }

  async attach(again) {
    if (!this.termId) return;
    try {
      const r = await this.api.call("term.attach", { term_id: this.termId });
      if (again) this.term.reset();
      this.term.write(r.output || "");
      this.resize();
    } catch { this.term.write("\r\n[terminal fermé]\r\n"); this.exited = true; }
  }

  resize() {
    if (!this.box.offsetWidth) return;
    this.fit.fit();
    if (this.termId) this.api.call("term.resize", { term_id: this.termId, cols: this.term.cols, rows: this.term.rows }).catch(() => {});
  }

  destroy(close = false) {
    for (const off of this.offs) off();
    this.observer.disconnect();
    if (close && this.termId && !this.exited) this.api.call("term.close", { term_id: this.termId }).catch(() => {});
    this.term.dispose();
    this.root.remove();
  }
}
