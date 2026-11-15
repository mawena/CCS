// Feuille de route d'un projet : phases avec leur progression, cases à cocher (le pont ne change
// que le caractère entre crochets, et refuse si la ligne a changé entre-temps).
import { clear, el } from "./dom.js";

export class RoadmapPanel {
  constructor(container, api, cwd) {
    this.api = api;
    this.cwd = cwd;
    this.node = el("div", { class: "roadmap" });
    container.append(this.node);
    this.load();
  }

  async load(message = "") {
    let r;
    try { r = await this.api.call("roadmap.read", { cwd: this.cwd }); } catch (e) {
      clear(this.node).append(el("p", { class: "message" }, e.message));
      return;
    }
    clear(this.node);
    if (message) this.node.append(el("p", { class: "message" }, message));
    if (!r.path) { this.node.append(el("p", { class: "subtle" }, "Pas de ROADMAP.md dans ce projet.")); return; }
    if (r.title) this.node.append(el("h3", {}, r.title));
    const phases = [...r.phases].reverse();          // la phase en cours en haut, comme au bureau
    for (const phase of phases) {
      const done = phase.tasks.filter((t) => t.done).length;
      const fill = el("div", { class: "bar-fill" });
      fill.style.width = `${phase.tasks.length ? (100 * done) / phase.tasks.length : 0}%`;
      const box = el("details", { class: "phase", open: done < phase.tasks.length },
        el("summary", {}, el("span", { class: "grow" }, phase.title), el("span", { class: "subtle" }, `${done}/${phase.tasks.length}`)),
        el("div", { class: "bar-track" }, fill));
      for (const task of phase.tasks) {
        const box2 = el("input", { type: "checkbox" });
        box2.checked = task.done;
        box2.addEventListener("change", async () => {
          try { await this.api.call("roadmap.toggle", { path: r.path, line: task.line, text: task.text }); this.load(); } catch (e) {
            this.load(e.message);
          }
        });
        const label = el("label", { class: `check task depth-${Math.min(task.depth || 0, 3)}${task.done ? " done" : ""}` }, box2, el("span", {}, task.text));
        box.append(label);
      }
      this.node.append(box);
    }
  }
}
