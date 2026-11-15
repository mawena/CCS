// Terminal shell dans le navigateur (xterm.js, chargé par index.html) relié à un pseudo-terminal
// du pont. Après une coupure, il se rattache et réaffiche la fin de la sortie.
import { el } from "./dom.js";

export class TerminalView {
  constructor(container, api, { cwd, command, name, termId }) {
    this.api = api;
    this.termId = termId || null;
    this.box = el("div", { class: "term" });
    container.append(this.box);
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    this.term = new window.Terminal({
      fontFamily: '"JetBrains Mono", "DejaVu Sans Mono", monospace', fontSize: 13, cursorBlink: true,
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
    this.term.onData((data) => { if (this.termId && !this.exited) api.call("term.input", { term_id: this.termId, data }).catch(() => {}); });
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(this.box);
    if (this.termId) this.attach(false);
    else this.start(cwd, command, name);
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
    this.box.remove();
  }
}
