// Choix de la machine pilotée : ce serveur, ou une autre machine de Charles jointe par le tunnel
// Ricochet (son pont CCS, celui de l'application de bureau). Tout le web suit la machine choisie :
// sessions, chats, fichiers, feuille de route, Git, terminal.
import { el } from "./dom.js";

const LIST_KEY = "ccs.machines";
const NAME_KEY = "ccs.machine.name";

export function knownMachines() {
  try { return JSON.parse(localStorage.getItem(LIST_KEY) || "[]"); } catch { return []; }
}

function remember(list) {
  try { localStorage.setItem(LIST_KEY, JSON.stringify(list)); } catch { /* navigation privée */ }
}

export function machineName(api) {
  if (!api.machine) return "Ce serveur";
  try { return localStorage.getItem(NAME_KEY) || api.machine; } catch { return api.machine; }
}

export function describe(m) {
  if (!m.online) return "hors ligne";
  const parts = ["en ligne"];
  if (m.cores) parts.push(`charge ${Number(m.load || 0).toFixed(1)} sur ${m.cores} cœurs`);
  if (!m.tunnel) parts.push("tunnel SSH non activé");
  return parts.join(" · ");
}

// Machines autres que ce serveur ; la liste vient toujours du pont du serveur (`machines.*` n'est
// jamais relayé), et la dernière connue sert si la connexion est coupée.
export async function otherMachines(api) {
  let r;
  try {
    r = await Promise.race([api.call("machines.list"),
      new Promise((_, no) => setTimeout(() => no(new Error("délai")), 15000))]);
  } catch {
    return { machines: knownMachines(), message: "" };
  }
  const list = (r.machines || []).filter((m) => !m.local);
  remember(list);
  return { machines: list, message: r.message || "" };
}

// Fenêtre de choix ; `onPick(id, name)` reçoit "" pour ce serveur.
export function machineSheet(api, onPick) {
  const dlg = el("dialog", { class: "sheet", "aria-label": "Machine" });
  const close = () => { if (dlg.open) dlg.close(); dlg.remove(); };
  const list = el("div", { class: "sheet-list", role: "list" });
  const note = el("p", { class: "subtle" }, "Recherche des machines…");
  const item = (id, name, detail, enabled) => el("button", {
    type: "button", class: `menu-item machine-item${id === api.machine ? " current" : ""}`,
    role: "listitem", disabled: !enabled, "aria-current": id === api.machine ? "true" : null,
    onclick: () => { close(); if (id !== api.machine) onPick(id, name); },
  }, el("span", { class: "ico", "aria-hidden": "true" }, id ? "🖥" : "☁"),
  el("span", { class: "grow" }, el("strong", {}, name), el("br"), el("span", { class: "subtle" }, detail)));
  list.append(item("", "Ce serveur", "le VPS, toujours là", true));
  dlg.append(el("h2", {}, "Machine pilotée"), list, note,
    el("div", { class: "sheet-actions" },
      el("button", { type: "button", class: "manage-machines", onclick: () => { close(); location.hash = "#/reseau"; } }, "Gérer les machines"),
      el("button", { type: "button", onclick: close }, "Fermer")));
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dlg);
  dlg.showModal();
  otherMachines(api).then(({ machines, message }) => {
    for (const m of machines) list.append(item(m.id, m.name || m.id, describe(m), m.online && m.tunnel));
    note.textContent = message || (machines.length ? "Le PC doit être allumé, avec CCS installé."
      : "Aucune autre machine sur le relais Ricochet.");
  });
  return dlg;
}

export function pickMachine(api, id, name) {
  try {
    if (id) localStorage.setItem(NAME_KEY, name || id);
    else localStorage.removeItem(NAME_KEY);
  } catch { /* navigation privée */ }
  api.setMachine(id);
}
