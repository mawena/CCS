// Charpente de la version web : connexion, navigation, bandeau de reconnexion, thème.
import { Api, post, session } from "./api.js";
import { clear, confirmSheet, el, toast } from "./dom.js";
import { offerInstall } from "./install.js";
import { showLogin } from "./login.js";
import { machineName, machineSheet, otherMachines, pickMachine } from "./machines.js";
import { RootWatch } from "./root.js";
import { VIEWS } from "./views.js";

const state = { api: null, user: null, cleanup: null, view: null, route: null, title: "CCS", waiting: 0, root: null };

function banner(text, kind = "info") {
  const b = document.getElementById("banner");
  b.textContent = text || "";
  b.className = `banner ${kind}`;
  b.hidden = !text;
}

// Adresse « #/<page>/<sous-adresse> » : la sous-adresse (un chat ouvert…) va à la page sans la
// remonter ; ainsi le bouton Retour du téléphone ferme le chat au lieu de quitter CCS.
function route() {
  let [name, ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  if (name === "machines") name = "reseau";          // ancienne page, fondue dans l'onglet Réseau
  return { name: VIEWS[name] ? name : "accueil", sub: rest.join("/") };
}

function updateTitle() {
  document.title = (state.waiting ? `(${state.waiting}) ` : "") + state.title;
}

function render() {
  const { name, sub } = route();
  if (name === state.view && state.route) { state.route(sub); return; }
  const tab = VIEWS[name].parent || name;
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active", a.dataset.view === tab);
    if (a.dataset.view === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  if (state.cleanup) { try { state.cleanup(); } catch (e) { console.error(e); } }
  const view = clear(document.getElementById("view"));
  view.dataset.view = name;
  state.view = name;
  state.title = `${VIEWS[name].title} · CCS`;
  updateTitle();
  // mount() renvoie une fonction de nettoyage, ou { cleanup, route(sub) } pour suivre les sous-adresses
  const out = VIEWS[name].mount(view, state.api, { user: state.user, banner, sub }) || null;
  state.cleanup = typeof out === "function" ? out : out?.cleanup || null;
  state.route = out && typeof out === "object" ? out.route || null : null;
}

// Pastille sur « Sessions » : chats qui attendent ta réponse (autorisation, question), sur
// tous les appareils ; rafraîchie à chaque événement de chat et toutes les 20 s.
async function refreshWaiting() {
  if (!state.api) return;
  let r;
  try { r = await state.api.call("chat.list"); } catch { return; }
  state.waiting = (r.chats || []).filter((c) => c.state === "permission").length;
  const link = document.querySelector('#nav a[data-view="sessions"]');
  if (link) {
    let badge = link.querySelector(".nav-badge");
    if (!badge) { badge = el("span", { class: "nav-badge" }); link.append(badge); }
    badge.textContent = String(state.waiting);
    badge.hidden = !state.waiting;
    badge.setAttribute("aria-label", `${state.waiting} chat(s) attendent ta réponse`);
  }
  updateTitle();
}
let waitingTimer = null;
function soonRefreshWaiting() {
  clearTimeout(waitingTimer);
  waitingTimer = setTimeout(refreshWaiting, 400);
}

// Bouton de la machine pilotée (barre du haut) : caché tant qu'il n'y a pas d'autre machine.
function showMachine() {
  const b = document.getElementById("machine");
  const api = state.api;
  if (!b || !api) return;
  b.textContent = `${api.machine ? "🖥" : "☁"} ${machineName(api)}`;
  b.classList.toggle("elsewhere", Boolean(api.machine));
  b.title = api.machine ? `Tu pilotes ${machineName(api)} (changer de machine)` : "Changer de machine";
  document.body.classList.toggle("on-machine", Boolean(api.machine));
}

async function offerMachines() {
  const b = document.getElementById("machine");
  if (!b) return;
  if (state.api.machine) { b.hidden = false; return; }
  const { machines } = await otherMachines(state.api);
  b.hidden = !machines.length && !state.api.machine;
}

let announced = null;
function switchMachine(id, name) {
  announced = null;
  pickMachine(state.api, id, name);
  showMachine();
  banner(id ? `Connexion à ${name}…` : "", "info");
  state.view = null;                 // chaque page repart de zéro sur la nouvelle machine
  render();
  soonRefreshWaiting();
}

function buildNav() {
  const nav = clear(document.getElementById("nav"));
  for (const [name, v] of Object.entries(VIEWS)) {
    if (v.hidden) continue;
    nav.append(el("a", { href: `#/${name}`, dataset: { view: name } },
      el("span", { class: "nav-icon", "aria-hidden": "true" }, v.icon), el("span", { class: "nav-label" }, v.title)));
  }
}

function stopRoot() {
  state.root?.stop();
  state.root = null;
}

function start(user) {
  state.user = user;
  document.getElementById("login").hidden = true;
  document.getElementById("shell").hidden = false;
  state.api = new Api();
  state.api.on("offline", () => banner("Connexion perdue : reconnexion…", "warning"));
  // vers une autre machine, le WebSocket s'ouvre avant le tunnel : « machines.ready » le confirme
  state.api.on("online", () => {
    banner(state.api.machine ? `Connexion à ${machineName(state.api)}…` : "", "info");
    checkVersion();
  });
  state.api.on("machines.ready", (d) => {
    banner("");
    if (announced !== d.machine) toast(`Tu pilotes ${d.name || d.machine}.`);   // pas à chaque reconnexion
    announced = d.machine;
  });
  state.api.on("machine-down", (d) => banner(`${machineName(state.api)} injoignable : ${d.reason || "sans détail"}. `
    + "Nouvel essai bientôt ; ☁ en haut pour revenir au serveur.", "error"));
  state.api.on("logged-out", () => { stopRoot(); state.api.close(); showLogin(start); });
  state.api.on("notice", (d) => banner(d.text, "info"));
  state.api.on("chat.event", soonRefreshWaiting);
  state.api.on("reconnected", soonRefreshWaiting);
  // mot de passe root demandé par la machine pilotée : fenêtre au premier plan, bandeau « gardé »
  stopRoot();
  state.root = new RootWatch(state.api).start();
  state.api.connect();
  showMachine();
  buildNav();
  render();
  refreshWaiting();
  offerInstall();
  offerMachines();
}

// Version du serveur : une page restée ouverte pendant une mise à jour garde l'ancien code en
// mémoire (nouveautés absentes, comme le séparateur après `/clear`) ; on propose de recharger.
let loadedVersion = null, offeredVersion = null;
async function checkVersion() {
  let v = null;
  try { v = (await (await fetch("/api/health", { cache: "no-store" })).json()).version; } catch { return; }
  if (!v) return;
  if (loadedVersion === null) { loadedVersion = v; return; }
  if (v === loadedVersion || v === offeredVersion) return;
  offeredVersion = v;
  toast(`CCS ${v} est installé sur le serveur : recharge la page pour en profiter.`,
    { action: { label: "Recharger", run: () => location.reload() }, timeout: 24 * 3600 * 1000 });
}
checkVersion();

setInterval(() => { if (!document.hidden) refreshWaiting(); }, 20000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) { refreshWaiting(); checkVersion(); } });

window.addEventListener("hashchange", () => { if (state.api) render(); });

document.getElementById("machine").addEventListener("click", () => {
  if (state.api) machineSheet(state.api, switchMachine);
});

document.getElementById("logout").addEventListener("click", async () => {
  if (!await confirmSheet({ title: "Se déconnecter ?", body: "Les chats continuent sur le serveur.",
    confirm: "Se déconnecter" })) return;
  const r = await post("/api/logout");
  stopRoot();
  state.api?.close();
  state.api = null;
  if (r?.redirect) {                     // mode Portier : la déconnexion se fait sur Portier
    location.href = r.redirect;
    return;
  }
  location.hash = "";
  showLogin(start);
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

session().then((s) => (s ? start(s.user) : showLogin(start)))
  .catch(() => { banner("Serveur injoignable.", "error"); showLogin(start); });
