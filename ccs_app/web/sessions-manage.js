// Gérer projets et conversations (phase 15) : ajouter un projet (dossier existant ou nouveau,
// git init en option), le retirer de la liste (rien n'est effacé), supprimer une conversation
// (corbeille CCS, restaurable 30 jours) et la corbeille elle-même.
import { ago, clear, confirmSheet, el, errorState, loading, toast } from "./dom.js";
import { sheet, titleOf } from "./sessions-conv.js";

const base = (p) => (p || "").split("/").filter(Boolean).pop() || p;

// ---- ajouter un projet ----------------------------------------------------------------------

export function addProject(api, { onDone, folders = [] }) {
  const mode = (value, label, checked) => el("label", { class: "check" },
    el("input", { type: "radio", name: "add-mode", value, checked }), el("span", {}, label));
  const modes = el("div", { class: "add-modes", role: "radiogroup", "aria-label": "Type de projet" },
    mode("existing", "Dossier existant", true), mode("new", "Nouveau dossier", false));
  const list = el("datalist", { id: "add-project-folders" }, ...folders.map((f) => el("option", { value: f })));
  const cwd = el("input", { type: "text", placeholder: "~/Work/mon-projet", list: "add-project-folders", "aria-label": "Dossier du projet", autocapitalize: "off", spellcheck: "false" });
  const parent = el("input", { type: "text", value: "~/Work", "aria-label": "Dossier parent", autocapitalize: "off", spellcheck: "false" });
  const name = el("input", { type: "text", placeholder: "mon-projet", "aria-label": "Nom du nouveau dossier", autocapitalize: "off", spellcheck: "false" });
  const git = el("input", { type: "checkbox", checked: true });
  const existing = el("div", { class: "stack" }, el("label", {}, "Dossier", cwd), list);
  const fresh = el("div", { class: "stack", hidden: true }, el("label", {}, "Dans le dossier", parent), el("label", {}, "Nom", name),
    el("label", { class: "check" }, git, el("span", {}, "Initialiser un dépôt git")));
  const msg = el("p", { class: "form-error", role: "alert" });
  const isNew = () => modes.querySelector("input:checked").value === "new";
  modes.addEventListener("change", () => { existing.hidden = isNew(); fresh.hidden = !isNew(); (isNew() ? name : cwd).focus(); });
  const form = el("form", { class: "stack add-project" }, modes, existing, fresh, msg);
  const submit = el("button", { type: "button", class: "primary", onclick: () => form.requestSubmit() }, "Ajouter");
  const { close } = sheet("Ajouter un projet", form, [el("button", { type: "button", onclick: () => close() }, "Annuler"), submit]);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "";
    const params = isNew() ? { parent: parent.value.trim(), name: name.value.trim(), git: git.checked } : { cwd: cwd.value.trim() };
    if (isNew() ? !params.name : !params.cwd) { msg.textContent = isNew() ? "Donne un nom au dossier." : "Choisis ou tape un dossier."; return; }
    submit.disabled = true;
    try {
      const r = await api.call("projects.add", params);
      close();
      toast(`Projet ajouté : ${base(r.cwd)}`, { kind: "success" });
      onDone?.(r.cwd);
    } catch (err) { msg.textContent = err.message; submit.disabled = false; }
  });
  cwd.focus();
}

// ---- retirer un projet de la liste ------------------------------------------------------------

export async function removeProject(api, p, { onDone }) {
  if (!await confirmSheet({ title: `Retirer « ${p.name} » de la liste ?`,
    body: "Le dossier et ses conversations ne sont pas effacés ; le projet revient dans la liste si une nouvelle conversation y démarre.",
    confirm: "Retirer", danger: true })) return;
  try {
    await api.call("projects.remove", { cwd: p.cwd });
    toast(`« ${p.name} » retiré de la liste.`, { kind: "success" });
    onDone?.();
  } catch (e) { toast(e.message, { kind: "error" }); }
}

// ---- supprimer une conversation (corbeille) ------------------------------------------------------

export async function trashConversation(api, c, { onDone }) {
  if (!await confirmSheet({ title: "Supprimer cette conversation ?", body: `« ${titleOf(c)} » part dans la corbeille de CCS : tu peux la restaurer pendant 30 jours.`,
    confirm: "Supprimer", danger: true })) return;
  try {
    const r = await api.call("conversation.trash", { path: c.path, session_id: c.session_id, cwd: c.cwd, title: titleOf(c) });
    onDone?.();
    toast("Conversation mise à la corbeille.", { kind: "success", timeout: 8000, action: { label: "Annuler", run: async () => {
      try { await api.call("conversation.restore", { tid: r.tid }); toast("Conversation restaurée.", { kind: "success" }); onDone?.(); }
      catch (e) { toast(e.message, { kind: "error" }); }
    } } });
  } catch (e) { toast(e.message, { kind: "error" }); }
}

// ---- corbeille ----------------------------------------------------------------------------------

export function openTrash(api, { onDone }) {
  const body = el("div", { class: "trash-list" });
  const { close } = sheet("Corbeille", body, [el("button", { type: "button", onclick: () => close() }, "Fermer")]);
  const load = async () => {
    clear(body).append(loading());
    let r;
    try { r = await api.call("conversation.trash_list"); } catch (e) { clear(body).append(errorState(e.message, load)); return; }
    clear(body).append(el("p", { class: "subtle" }, `Les conversations supprimées y restent ${r.days} jours, puis sont effacées.`));
    const items = (r.items || []).sort((a, b) => (b.trashed_at || 0) - (a.trashed_at || 0));
    if (!items.length) { body.append(el("p", {}, "La corbeille est vide.")); return; }
    for (const it of items) {
      const btn = el("button", { type: "button", class: "small", onclick: async () => {
        btn.disabled = true;
        try { await api.call("conversation.restore", { tid: it.tid }); toast("Conversation restaurée.", { kind: "success" }); onDone?.(); load(); }
        catch (e) { toast(e.message, { kind: "error" }); btn.disabled = false; }
      } }, "Restaurer");
      body.append(el("div", { class: "item trash-item" },
        el("div", { class: "grow trash-text" }, el("strong", {}, it.title || "(sans titre)"),
          el("span", { class: "subtle" }, [base(it.cwd), it.trashed_at ? `supprimée ${ago(it.trashed_at)}` : ""].filter(Boolean).join(" · "))),
        btn));
    }
  };
  load();
}
