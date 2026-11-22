// Messages enregistrés (communs à tous les projets ou propres au projet) : feuille ouverte près de
// la saisie pour insérer, enregistrer le texte en cours ou supprimer.
import { clear, confirmSheet, el, emptyState, errorState, loading, toast } from "./dom.js";

const SCOPES = [["global", "Tous les projets"], ["projet", "Ce projet"]];

export function openSavedSheet({ api, cwd, currentText, onInsert }) {
  const dlg = el("dialog", { class: "sheet saved", "aria-label": "Messages enregistrés" });
  const body = el("div", { class: "saved-list" });
  const name = el("input", { placeholder: "Nom du message", "aria-label": "Nom du message", maxlength: "80",
    enterkeyhint: "done", autocapitalize: "sentences" });
  const scope = el("select", { "aria-label": "Portée" }, ...SCOPES.map(([v, t]) => el("option", { value: v }, t)));
  const close = () => { if (dlg.open) dlg.close(); dlg.remove(); };

  async function load() {
    clear(body).append(loading());
    let r;
    try { r = await api.call("saved.list", { cwd }); } catch (e) {
      clear(body).append(errorState(e.message, load));
      return;
    }
    clear(body);
    if (!r.items.length) body.append(emptyState("Aucun message enregistré pour l'instant."));
    for (const item of r.items) {
      body.append(el("div", { class: "saved-item" },
        el("button", { type: "button", class: "saved-pick", onclick: () => { close(); onInsert(item.text); } },
          el("strong", {}, item.name), el("span", { class: "subtle" }, ` · ${item.scope === "projet" ? "ce projet" : "tous"}`),
          el("span", { class: "subtle saved-text" }, item.text.replace(/\s+/g, " ").slice(0, 120))),
        el("button", { type: "button", class: "small flat", "aria-label": `Supprimer ${item.name}`, onclick: () => remove(item) }, "Supprimer")));
    }
  }

  async function remove(item) {
    const ok = await confirmSheet({ title: `Supprimer « ${item.name} » ?`, body: "Le message enregistré disparaît.",
      confirm: "Supprimer", danger: true });
    if (!ok) return;
    try { await api.call("saved.delete", { cwd, scope: item.scope, name: item.name }); } catch (e) { toast(e.message, { kind: "error" }); }
    load();
  }

  async function saveCurrent() {
    try {
      await api.call("saved.save", { cwd, scope: scope.value, name: name.value, text: currentText() });
      name.value = "";
      toast("Message enregistré.", { kind: "success" });
      load();
    } catch (e) { toast(e.message, { kind: "error" }); }
  }

  const form = currentText().trim() ? el("div", { class: "saved-new" },
    el("strong", {}, "Enregistrer le texte en cours"), name, scope,
    el("button", { type: "button", class: "primary", onclick: saveCurrent }, "Enregistrer")) : null;
  dlg.append(el("h2", {}, "Messages enregistrés"), body, form,
    el("div", { class: "sheet-actions" }, el("button", { type: "button", onclick: close }, "Fermer")));
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dlg);
  dlg.showModal();
  load();
}
