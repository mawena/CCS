// Feuille de route d'un projet : phases avec leur progression, cases à cocher (le pont ne change
// que le caractère entre crochets, et refuse si la ligne a changé entre-temps). Cocher met la
// ligne à jour sur place : le défilement et les phases ouvertes restent comme ils sont.
// « Faire une tâche » : dans ce chat, dans un nouveau chat, ou cette nuit (file de tâches).
import { clear, el, emptyState, errorState, loading, toast } from "./dom.js";

export class RoadmapPanel {
  // actions : { send(text) } quand le volet vit dans un chat ; { send, standalone: true } hors d'un
  // chat (l'écran Projet : send ouvre un nouveau chat) ; newChat(text) facultatif, sinon l'événement
  // « ccs:new-chat » (écouté par Sessions) porte la demande.
  constructor(container, api, cwd, actions = {}) {
    this.api = api;
    this.cwd = cwd;
    this.actions = actions;
    this.node = el("div", { class: "roadmap" });
    container.append(this.node);
    this.load();
  }

  async load() {
    clear(this.node).append(loading());
    let r;
    try { r = await this.api.call("roadmap.read", { cwd: this.cwd }); } catch (e) {
      clear(this.node).append(errorState(e.message, () => this.load()));
      return;
    }
    clear(this.node);
    this.path = r.path;
    if (!r.path) { this.node.append(emptyState("Pas de ROADMAP.md dans ce projet.")); return; }
    if (r.title) this.node.append(el("h3", {}, r.title));
    for (const phase of r.phases) this.node.append(this.phaseBox(phase));   // ordre du fichier, comme au bureau
    // la phase en cours (première non finie) à l'écran
    this.node.querySelector("details.phase[open]")?.scrollIntoView({ block: "start" });
  }

  phaseBox(phase) {
    const count = el("span", { class: "subtle" }, "");
    const fill = el("div", { class: "bar-fill" });
    const update = () => {
      const done = phase.tasks.filter((t) => t.done).length;
      count.textContent = `${done}/${phase.tasks.length}`;
      fill.style.width = `${phase.tasks.length ? (100 * done) / phase.tasks.length : 0}%`;
    };
    const first = phase.tasks.some((t) => !t.done);
    const box = el("details", { class: "phase", open: first },
      el("summary", {}, el("span", { class: "grow" }, phase.title), count),
      el("div", { class: "bar-track" }, fill));
    for (const task of phase.tasks) box.append(this.taskRow(phase, task, update));
    update();
    return box;
  }

  taskRow(phase, task, update) {
    const check = el("input", { type: "checkbox", "aria-label": task.text });
    check.checked = task.done;
    const label = el("label", { class: `check task depth-${Math.min(task.depth || 0, 3)}${task.done ? " done" : ""}` }, check, el("span", {}, task.text));
    check.addEventListener("change", async () => {
      const want = check.checked;
      try {
        const r = await this.api.call("roadmap.toggle", { path: this.path, line: task.line, text: task.text, done: want });
        if (r && r.changed === false) {           // la case était déjà dans cet état : la page n'est plus à jour
          toast("La feuille de route avait déjà changé : elle est rechargée.");
          this.load();
          return;
        }
        task.done = want;
        label.classList.toggle("done", want);
        update();
        this.syncDo(row, task, phase);
      } catch (e) {
        check.checked = !want;                               // la ligne a changé ailleurs : on ne touche à rien d'autre
        toast(e.message, { kind: "error", action: { label: "Recharger", run: () => this.load() } });
      }
    });
    const row = el("div", { class: "task-row" }, label);
    this.syncDo(row, task, phase);
    return row;
  }

  // Le bouton « Faire » n'existe que sur une tâche non cochée.
  syncDo(row, task, phase) {
    row.querySelector(".task-do")?.remove();
    if (!task.done) row.append(el("button", { class: "small flat task-do", "aria-label": `Faire la tâche : ${task.text}`,
      onclick: () => this.doTask(task, phase) }, "Faire…"));
  }

  doTask(task, phase) {
    const info = { path: this.path, text: task.text, phase: phase.title };
    const dlg = el("dialog", { class: "sheet", "aria-label": "Faire une tâche" });
    const close = () => { if (dlg.open) dlg.close(); dlg.remove(); };
    const choose = (run) => async () => {
      close();
      let prompt;
      try { prompt = (await this.api.call("roadmap.prompt", info)).prompt; } catch (e) { toast(e.message, { kind: "error" }); return; }
      try { await run(prompt); } catch (e) { toast(e.message, { kind: "error" }); }
    };
    const inChat = this.actions.send && !this.actions.standalone;
    dlg.append(el("h2", {}, "Faire cette tâche"), el("p", { class: "subtle" }, task.text),
      el("div", { class: "sheet-choices" },
        inChat ? el("button", { type: "button", class: "primary", onclick: choose((p) => this.actions.send(p)) }, "Dans ce chat") : null,
        el("button", { type: "button", class: inChat ? "" : "primary", onclick: choose((p) => this.newChat(p)) }, "Nouveau chat"),
        el("button", { type: "button", onclick: choose(async (p) => {
          await this.api.call("tasks.add", { message: p, cwd: this.cwd, when: "nuit", roadmap: info });
          toast("Tâche ajoutée pour cette nuit.", { kind: "success" });
        }) }, "Cette nuit"),
        el("button", { type: "button", class: "flat", onclick: close }, "Annuler")));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
    document.body.append(dlg);
    dlg.showModal();
  }

  newChat(text) {
    if (this.actions.newChat) return this.actions.newChat(text);
    if (this.actions.standalone && this.actions.send) return this.actions.send(text);
    document.dispatchEvent(new CustomEvent("ccs:new-chat", { detail: { cwd: this.cwd, text } }));
    return null;
  }
}
