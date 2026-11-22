// « Nouvelle session » comme au bureau : dossier (récents, dépôts git du disque, chemin tapé),
// compte, modèle et droits. Le compte demande une bascule globale (accounts.switch) avant
// l'ouverture, comme le bureau ; la feuille le dit.
import { clear, el, errorState, loading } from "./dom.js";
import { sheet } from "./sessions-conv.js";

const RECENT_KEY = "ccs-recent-folders";
const MODELS = [["", "Par défaut"], ["opus", "Opus"], ["sonnet", "Sonnet"], ["haiku", "Haiku"], ["fable", "Fable"]];
const RIGHTS = [["manual", "Demander"], ["acceptEdits", "Modifications acceptées"], ["plan", "Plan"],
  ["bypassPermissions", "Tout autoriser"]];
const SHOWN = 30;

export function recentFolders() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]").filter((p) => typeof p === "string"); } catch { return []; }
}

export function rememberFolder(path) {
  if (!path) return;
  const list = [path, ...recentFolders().filter((p) => p !== path)].slice(0, 8);
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* stockage plein ou refusé */ }
}

const short = (p, home) => (home && p.startsWith(`${home}/`) ? `~${p.slice(home.length)}` : p);

// known : dossiers de projets connus [{ path, name }] ; onOpen(cwd, { model, rights }) ; onTerm(cwd).
export function newSession(api, { known = [], initial = "", onOpen, onTerm }) {
  const folder = el("input", { type: "text", value: initial, placeholder: "~/Repo/projet", "aria-label": "Dossier de la session",
    autocapitalize: "off", autocomplete: "off", spellcheck: "false", enterkeyhint: "go" });
  const hint = el("p", { class: "subtle account-hint" });
  const warn = el("p", { class: "notice warning", hidden: true }, "La bascule s'applique à toutes les sessions ouvertes.");
  const account = el("select", { "aria-label": "Compte Claude" });
  const accountBox = el("label", { hidden: true }, "Compte Claude", account, hint, warn);
  const model = el("select", { "aria-label": "Modèle" }, ...MODELS.map(([v, t]) => el("option", { value: v }, t)));
  const rights = el("select", { "aria-label": "Droits" }, ...RIGHTS.map(([v, t]) => el("option", { value: v }, t)));
  const danger = el("p", { class: "notice error", hidden: true }, "Claude pourra tout faire sans rien demander : à réserver à un dossier jetable.");
  rights.addEventListener("change", () => { danger.hidden = rights.value !== "bypassPermissions"; });
  const picker = el("div", { class: "folder-picker" });
  const msg = el("p", { class: "message", role: "alert" });

  // ---- dossiers : récents d'abord, puis les dépôts du disque, filtrés par ce qui est tapé ----
  let home = "";
  let repos = null;                 // null : pas encore chargés ; sinon liste
  let failed = "";
  const items = () => {
    const seen = new Set();
    const out = [];
    for (const [path, tag] of [...recentFolders().map((p) => [p, "récent"]), ...known.map((k) => [k.path, "projet"]),
      ...(repos || []).map((r) => [r.path, "git"])]) {
      if (seen.has(path)) continue;
      seen.add(path);
      out.push({ path, tag });
    }
    return out;
  };
  const renderPicker = () => {
    clear(picker);
    const q = folder.value.trim().toLowerCase();
    const matches = items().filter((i) => !q || i.path.toLowerCase().includes(q.replace(/^~/, home.toLowerCase())) || short(i.path, home).toLowerCase().includes(q));
    for (const i of matches.slice(0, SHOWN)) {
      picker.append(el("button", { type: "button", class: "item pick", onclick: () => { folder.value = i.path; renderPicker(); refreshAccount(); } },
        el("span", { class: "grow pick-path" }, short(i.path, home)), el("span", { class: "badge" }, i.tag)));
    }
    if (matches.length > SHOWN) picker.append(el("p", { class: "subtle" }, `${matches.length - SHOWN} autres : tape pour filtrer.`));
    if (repos === null && !failed) picker.append(loading("Recherche des dépôts git…"));
    if (failed) picker.append(errorState(failed, loadRepos));
    if (!matches.length && repos !== null) picker.append(el("p", { class: "subtle" }, "Aucun dossier connu ne correspond : le chemin tapé sera utilisé."));
  };
  async function loadRepos() {
    failed = "";
    repos = null;
    renderPicker();
    try { repos = (await api.call("projects.folders")).folders || []; } catch (e) { failed = e.message; }
    renderPicker();
  }
  folder.addEventListener("input", () => renderPicker());

  // ---- compte ---------------------------------------------------------------------------------
  let active = null;
  let touched = false;
  let seq = 0;
  async function refreshAccount() {
    const path = folder.value.trim();
    if (!path) return;
    const mine = ++seq;
    let r;
    try { r = await api.call("projects.account", { cwd: path }); } catch { return; }       // dossier refusé ou inconnu : on le dira à l'ouverture
    if (mine !== seq) return;
    active = r.active;
    accountBox.hidden = (r.profiles || []).length < 2;
    const keep = touched ? account.value : null;
    clear(account).append(...(r.profiles || []).map((p) => el("option", { value: p.name }, `${p.name} — ${p.email}${p.active ? " (actif)" : ""}`)));
    account.value = keep || r.preferred || r.active || "";
    hint.textContent = r.hint || "";
    warn.hidden = !account.value || account.value === active;
  }
  account.addEventListener("change", () => { touched = true; warn.hidden = account.value === active; });
  folder.addEventListener("change", refreshAccount);

  // ---- validation -----------------------------------------------------------------------------
  const open = async () => {
    const path = folder.value.trim();
    if (!path) { msg.textContent = "Choisis ou tape un dossier."; folder.focus(); return; }
    msg.textContent = "";
    go.disabled = true;
    try {
      if (account.value && active && account.value !== active) {
        const r = await api.call("accounts.switch", { name: account.value });
        if (!r.ok) { msg.textContent = "La bascule de compte a échoué : rien n'est ouvert."; return; }
      }
      const ok = await onOpen(path, { model: model.value || null, rights: rights.value });
      if (ok !== false) { rememberFolder(path); close(); }
    } catch (e) { msg.textContent = e.message; } finally { go.disabled = false; }
  };
  const term = el("button", { type: "button", onclick: () => { const p = folder.value.trim(); if (!p) { msg.textContent = "Choisis ou tape un dossier."; return; } rememberFolder(p); close(); onTerm(p); } }, "Terminal");
  const go = el("button", { type: "button", class: "primary", onclick: open }, "Ouvrir un chat");
  const form = el("form", { class: "new-sheet", onsubmit: (e) => { e.preventDefault(); open(); } },
    el("label", {}, "Dossier", folder), picker, accountBox,
    el("div", { class: "two" }, el("label", {}, "Modèle", model), el("label", {}, "Droits", rights)), danger, msg);
  const { close } = sheet("Nouvelle session", form, [el("button", { type: "button", class: "flat", onclick: () => close() }, "Annuler"), term, go]);

  renderPicker();
  loadRepos();
  api.call("accounts.state").then((s) => { home = s.home || ""; renderPicker(); }, () => {});
  refreshAccount();
  (initial ? go : folder).focus();      // dossier déjà choisi : reste à régler les options et ouvrir
}
