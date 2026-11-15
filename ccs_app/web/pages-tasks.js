// Tâches de nuit : liste par état, journal d'une tâche, nouvelle tâche, reprise dans un chat,
// annulation et suppression (avec confirmation). Montée par l'Accueil.
import { ago, clear, confirmSheet, el, emptyState, errorState, loading, toast } from "./dom.js";
import { busy, field, shortPath } from "./pages-util.js";

const STATE = { queued: "En attente", running: "En cours", waiting: "À reprendre (limite atteinte)",
  done: "Finie", failed: "Échouée", cancelled: "Annulée" };
const ACTIVE = ["queued", "running", "waiting"];
const FILTERS = [["actives", "À venir", ACTIVE], ["done", "Finies", ["done"]],
  ["failed", "Échouées", ["failed"]], ["cancelled", "Annulées", ["cancelled"]]];
const RIGHTS = [["lecture", "Lecture seule", "Claude lit et analyse ; tout ce qui demande une permission est refusé."],
  ["modifications", "Modifications des fichiers", "Claude modifie les fichiers du dossier sans demander ; le reste est refusé."],
  ["tout", "Tout (aucune vérification)", "Attention : Claude peut tout faire sans rien demander, y compris supprimer."]];
const MODELS = [["", "Modèle par défaut"], ["opus", "Opus"], ["sonnet", "Sonnet"], ["haiku", "Haiku"], ["fable", "Fable"]];

function whenText(t) {
  if (t.when === "quota") return "dès qu'il y a du quota";
  if (t.when === "nuit") return "cette nuit";
  return `à ${t.when}`;
}

function subtitle(t) {
  const parts = [STATE[t.state] || t.state];
  if (t.state === "queued" || t.state === "waiting") parts.push(t.note || whenText(t));
  else if (t.error) parts.push(t.error);
  else if (t.finished) parts.push(ago(t.finished));
  parts.push(shortPath(t.cwd));
  return parts.join(" · ");
}

function sheet(title, wide = true) {
  const dlg = el("dialog", { class: `sheet${wide ? " wide" : ""}`, "aria-label": title });
  dlg.addEventListener("close", () => dlg.remove());
  dlg.addEventListener("cancel", () => { /* Échap ferme : comportement natif */ });
  document.body.append(dlg);
  return dlg;
}

export function tasksSection(api, ctx) {
  const root = el("section", { class: "card flat section" });
  const head = el("div", { class: "page-head" }, el("h2", {}, "Tâches de nuit"),
    el("button", { class: "small primary", onclick: () => newTask() }, "Nouvelle tâche"));
  const tabs = el("div", { class: "seg", role: "group", "aria-label": "État des tâches" });
  const list = el("div", { class: "stack" });
  root.append(head, tabs, list);
  let all = [];
  let filter = null;
  let timer = null;

  async function load() {
    try { all = (await api.call("tasks.list")).tasks || []; } catch (e) {
      clear(list).append(errorState(e.message, load));
      return;
    }
    if (filter === null) filter = FILTERS.find(([, , st]) => all.some((t) => st.includes(t.state)))?.[0] || "actives";
    render();
  }

  function render() {
    clear(tabs).append(...FILTERS.map(([key, label, states]) => {
      const n = all.filter((t) => states.includes(t.state)).length;
      return el("button", { class: "small", "aria-pressed": String(filter === key),
        onclick: () => { filter = key; render(); } }, `${label} (${n})`);
    }));
    const states = FILTERS.find(([k]) => k === filter)[2];
    const shown = all.filter((t) => states.includes(t.state)).reverse();
    clear(list);
    if (!shown.length) {
      list.append(emptyState(all.length ? "Rien dans cette catégorie." : "Aucune tâche pour l'instant.",
        ...(all.length ? [] : [el("button", { class: "small", onclick: () => newTask() }, "Créer une tâche")])));
      return;
    }
    for (const t of shown) {
      list.append(el("button", { class: "task", onclick: () => detail(t.id) },
        el("div", { class: "grow" }, el("strong", {}, t.message.split("\n")[0].slice(0, 120)),
          el("div", { class: "subtle" }, subtitle(t))),
        el("span", { class: `pill ${t.state}` }, STATE[t.state] || t.state)));
    }
  }

  // ---- détail et journal -------------------------------------------------------------

  async function detail(id) {
    const dlg = sheet("Tâche");
    const title = el("h2", {});
    const meta = el("div", { class: "subtle" });
    const log = el("pre", { class: "log", tabindex: "0", "aria-label": "Journal de la tâche" }, "Chargement…");
    const actions = el("div", { class: "sheet-actions" });
    dlg.append(title, meta, log, actions);
    let poll = null;
    const stop = () => { clearInterval(poll); poll = null; };
    dlg.addEventListener("close", stop);

    async function refresh() {
      let r;
      try { r = await api.call("tasks.log", { id }); } catch (e) {
        stop();
        log.textContent = e.message;
        if (e.code === "introuvable") { await load(); }
        return;
      }
      const t = r.task;
      title.textContent = t.message.split("\n")[0].slice(0, 120);
      clear(meta).append(subtitle(t), r.summary ? ` · ${r.summary}` : "", el("br"),
        `${RIGHTS.find((x) => x[0] === t.rights)?.[1] || t.rights}${t.model ? ` · ${t.model}` : ""}`);
      const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
      log.textContent = (r.truncated ? "… (début du journal omis)\n" : "") + (r.lines.length ? r.lines.join("\n") : "Pas encore de journal.");
      if (atEnd) log.scrollTop = log.scrollHeight;
      clear(actions).append(
        t.session_id ? el("button", { class: "primary", onclick: (e) => busy(e.currentTarget, () => resume(t, dlg)) }, "Reprendre") : null,
        ACTIVE.includes(t.state) ? el("button", { class: "danger", onclick: (e) => busy(e.currentTarget, async () => { if (await cancel(t)) dlg.close(); }) }, "Annuler la tâche") : null,
        !ACTIVE.includes(t.state) ? el("button", { class: "danger", onclick: (e) => busy(e.currentTarget, async () => { if (await remove(t)) dlg.close(); }) }, "Supprimer") : null,
        el("button", { onclick: () => dlg.close() }, "Fermer"));
      if (!ACTIVE.includes(t.state)) stop();
    }
    dlg.showModal();
    await refresh();
    if (dlg.open) poll = setInterval(() => { if (dlg.open) refresh(); }, 3000);
  }

  async function resume(t, dlg) {
    try {
      const r = await api.call("chat.open", { cwd: t.cwd, session_id: t.session_id });
      dlg.close();
      location.hash = `#/sessions/${r.chat_id}`;
    } catch (e) { toast(e.message, { kind: "error" }); }
  }

  async function cancel(t) {
    if (!await confirmSheet({ title: "Annuler cette tâche ?", body: t.state === "running" ? "Claude est en train de la faire : il sera arrêté." : "Elle ne sera pas lancée.",
      confirm: "Annuler la tâche", cancel: "Garder", danger: true })) return false;
    try { await api.call("tasks.cancel", { id: t.id }); } catch (e) { toast(e.message, { kind: "error" }); return false; }
    toast("Tâche annulée.", { kind: "success" });
    load();
    return true;
  }

  async function remove(t) {
    if (!await confirmSheet({ title: "Supprimer cette tâche ?", body: "Son journal sera supprimé aussi.", confirm: "Supprimer", danger: true })) return false;
    try { await api.call("tasks.remove", { id: t.id }); } catch (e) { toast(e.message, { kind: "error" }); return false; }
    toast("Tâche supprimée.", { kind: "success" });
    load();
    return true;
  }

  // ---- nouvelle tâche ----------------------------------------------------------------

  async function newTask() {
    const dlg = sheet("Nouvelle tâche");
    const folder = el("input", { type: "text", list: "task-projects", autocomplete: "off", autocapitalize: "off",
      placeholder: "~/Work/mon-projet", value: ctx.home || "" });
    const datalist = el("datalist", { id: "task-projects" });
    const message = el("textarea", { rows: "5", placeholder: "Ce que Claude doit faire…" });
    const when = el("select", {}, el("option", { value: "quota" }, "Dès qu'il y a du quota"),
      el("option", { value: "nuit" }, "Cette nuit (meilleur créneau)"), el("option", { value: "heure" }, "À une heure précise…"));
    const time = el("input", { type: "time", hidden: true, "aria-label": "Heure" });
    const rights = el("select", {}, ...RIGHTS.map(([v, l]) => el("option", { value: v }, l)));
    rights.value = "modifications";
    const rightsHelp = el("span", { class: "hint" });
    const model = el("select", {}, ...MODELS.map(([v, l]) => el("option", { value: v }, l)));
    const error = el("p", { class: "form-error", role: "alert" });
    const submit = el("button", { class: "primary", type: "submit" }, "Ajouter");
    const showHelp = () => { rightsHelp.textContent = RIGHTS.find((x) => x[0] === rights.value)[2]; rightsHelp.className = `hint${rights.value === "tout" ? " err-text" : ""}`; };
    showHelp();
    rights.addEventListener("change", showHelp);
    when.addEventListener("change", () => { time.hidden = when.value !== "heure"; });
    const form = el("form", { class: "stack" }, el("h2", {}, "Nouvelle tâche"),
      field("Dossier du projet", folder), datalist, field("Message", message),
      field("Quand", when), time, field("Droits", rights, ""), rightsHelp, field("Modèle", model), error,
      el("div", { class: "sheet-actions" }, el("button", { type: "button", onclick: () => tryClose() }, "Annuler"), submit));
    dlg.append(form);
    // du texte tapé ne part pas sans confirmation (bouton Annuler, Échap)
    const tryClose = async () => {
      if (message.value.trim() && !await confirmSheet({ title: "Abandonner cette tâche ?", body: "Le message tapé sera perdu.",
        confirm: "Abandonner", cancel: "Continuer", danger: true })) return;
      dlg.close();
    };
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); tryClose(); });
    api.call("projects.list", {}).then((r) => {
      for (const p of (r.entries || []).filter((x) => x.cwd && x.exists)) datalist.append(el("option", { value: p.cwd }));
    }).catch(() => {});
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      error.textContent = "";
      let cwd = folder.value.trim();
      if (cwd.startsWith("~") && ctx.home) cwd = ctx.home + cwd.slice(1);
      if (!cwd) { error.textContent = "Indique le dossier du projet."; return; }
      if (!message.value.trim()) { error.textContent = "Écris ce que Claude doit faire."; return; }
      if (when.value === "heure" && !time.value) { error.textContent = "Choisis l'heure."; return; }
      await busy(submit, async () => {
        try {
          await api.call("tasks.add", { cwd, message: message.value, rights: rights.value,
            model: model.value || null, when: when.value === "heure" ? time.value : when.value });
        } catch (e) { error.textContent = e.message; return; }
        dlg.close();
        toast("Tâche ajoutée.", { kind: "success" });
        filter = "actives";
        load();
      });
    });
    dlg.showModal();
    message.focus();
  }

  clear(list).append(loading());
  load();
  timer = setInterval(() => { if (!document.hidden && all.some((t) => ACTIVE.includes(t.state))) load(); }, 15000);
  return { node: root, reload: load, destroy() { clearInterval(timer); } };
}
