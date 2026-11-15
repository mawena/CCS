// Volet « Changements de la session » : fichiers changés par Claude avec leur diff, annulation d'un
// fichier, retour à l'état d'avant un message. Toute écriture passe par une carte de confirmation.
import { clear, confirmSheet, el, emptyState, errorState, loading, toast } from "./dom.js";
import { diffBlock, parseUnified, statBadges } from "./chat-diff.js";

const KINDS = { created: "créé", deleted: "supprimé", modified: "modifié" };

export class ChangesPanel {
  // actions : { openFile(chemin absolu), changed() } ; chatId : le chat dont on lit la session.
  constructor(container, api, chatId, cwd, actions = {}) {
    this.api = api;
    this.chatId = chatId;
    this.cwd = cwd;
    this.actions = actions;
    this.node = el("div", { class: "changes" });
    container.append(this.node);
    this.load();
  }

  async load() {
    clear(this.node).append(loading());
    let r;
    try { r = await this.api.call("work.changes", { chat_id: this.chatId }); } catch (e) {
      clear(this.node).append(errorState(e.message, () => this.load()));
      return;
    }
    clear(this.node);
    this.node.append(el("div", { class: "row" }, el("strong", { class: "grow" }, "Fichiers changés"),
      el("button", { type: "button", class: "small", onclick: () => this.load() }, "Actualiser")));
    if (r.unknown) {
      this.node.append(emptyState("Le format de l'historique des fichiers de Claude Code n'est pas reconnu : rien ne peut être annulé d'ici."));
      return;
    }
    if (!r.files.length) this.node.append(emptyState("Aucun fichier n'a changé depuis le début de la session."));
    for (const f of r.files) this.node.append(this.fileCard(f));
    if (r.points.length) {
      this.node.append(el("h3", {}, "Revenir avant un message"),
        el("p", { class: "subtle" }, "Remet les fichiers dans l'état où ils étaient avant ce message."));
      for (const p of [...r.points].reverse()) {
        this.node.append(el("div", { class: "point" },
          el("span", { class: "grow point-text" }, p.text.replace(/\s+/g, " ")),
          el("button", { type: "button", class: "small", onclick: () => this.rewind(p) }, "Revenir ici")));
      }
    }
  }

  fileCard(f) {
    const name = f.path.split("/").pop();
    const lines = f.too_big || f.binary ? [] : parseUnified(f.diff || "");
    const card = el("details", { class: "change" },
      el("summary", {}, el("strong", {}, name), el("span", { class: `kind k-${f.kind}` }, KINDS[f.kind]),
        ...(f.binary || f.too_big ? [] : statBadges(lines)), el("span", { class: "subtle path" }, f.path)),
      f.too_big ? el("p", { class: "subtle" }, "Fichier trop gros pour être montré")
        : f.binary ? el("p", { class: "subtle" }, "Fichier binaire : pas de diff.") : diffBlock(lines),
      el("div", { class: "tool-actions" },
        f.kind === "deleted" ? null : el("button", { type: "button", class: "small", onclick: () => this.actions.openFile?.(f.path) }, "Ouvrir le fichier"),
        el("button", { type: "button", class: "small danger", onclick: () => this.undo(f) }, "Annuler ce fichier")));
    return card;
  }

  async undo(f) {
    const ok = await confirmSheet({ title: `Annuler les changements de ${f.path.split("/").pop()} ?`,
      body: `${f.kind === "created" ? "Le fichier sera supprimé (Claude l'a créé)." : "Le fichier reviendra à son état d'avant la session."} C'est définitif.`,
      confirm: "Annuler ce fichier", danger: true });
    if (!ok) return;
    try {
      await this.api.call("work.undo_file", { chat_id: this.chatId, path: f.path, ...(f.sha256 !== undefined ? { expected: f.sha256 } : {}) });
      toast("Fichier remis comme avant la session.", { kind: "success" });
      this.actions.changed?.();
    } catch (e) { toast(e.message, { kind: "error" }); }      // « conflit » ou « occupé » : le message du pont, puis on actualise
    this.load();
  }

  async rewind(p) {
    let plan;
    try { plan = await this.api.call("work.rewind_plan", { chat_id: this.chatId, message_id: p.message_id }); } catch (e) {
      toast(e.message, { kind: "error" });
      return;
    }
    if (!plan.steps.length) { toast("Tout est déjà comme avant ce message."); return; }
    const shown = plan.steps.every((s) => s.sha256 !== undefined);      // champ absent : ancien pont, pas de garde
    const expected = shown ? { expected: plan.steps.map((s) => ({ path: s.path, sha256: s.sha256 })) } : {};
    const list = plan.steps.map((s) => `${s.path.startsWith(`${this.cwd}/`) ? s.path.slice(this.cwd.length + 1) : s.path}${s.deleted ? " (supprimé)" : ""}${s.user_edited ? " (modifié depuis par toi ?)" : ""}`);
    const ok = await confirmSheet({ title: `Revenir avant ce message ? (${plan.steps.length} fichier${plan.steps.length > 1 ? "s" : ""})`,
      body: `${list.join("\n")}\n\nC'est définitif.`, confirm: "Revenir en arrière", danger: true });
    if (!ok) return;
    try {
      const r = await this.api.call("work.rewind_apply", { chat_id: this.chatId, message_id: p.message_id, ...expected });
      toast(`${r.count} fichier(s) remis comme avant ce message.`, { kind: "success" });
      this.actions.changed?.();
    } catch (e) { toast(e.message, { kind: "error" }); }
    this.load();
  }
}
