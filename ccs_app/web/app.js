// Charpente de la version web : connexion, navigation, bandeau de reconnexion, thème.
import { Api, post, session } from "./api.js";
import { clear, confirmSheet, el, toast } from "./dom.js";
import { offerInstall } from "./install.js";
import { showLogin } from "./login.js";
import { VIEWS } from "./views.js";

const state = { api: null, user: null, cleanup: null, view: null, route: null, title: "CCS", waiting: 0 };

function banner(text, kind = "info") {
  const b = document.getElementById("banner");
  b.textContent = text || "";
  b.className = `banner ${kind}`;
  b.hidden = !text;
}

// Adresse « #/<page>/<sous-adresse> » : la sous-adresse (un chat ouvert…) va à la page sans la
// remonter ; ainsi le bouton Retour du téléphone ferme le chat au lieu de quitter CCS.
function route() {
  const [name, ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  return { name: VIEWS[name] ? name : "accueil", sub: rest.join("/") };
}

function updateTitle() {
  document.title = (state.waiting ? `(${state.waiting}) ` : "") + state.title;
}

function render() {
  const { name, sub } = route();
  if (name === state.view && state.route) { state.route(sub); return; }
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active", a.dataset.view === name);
    if (a.dataset.view === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
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

function buildNav() {
  const nav = clear(document.getElementById("nav"));
  for (const [name, v] of Object.entries(VIEWS)) {
    nav.append(el("a", { href: `#/${name}`, dataset: { view: name } },
      el("span", { class: "nav-icon", "aria-hidden": "true" }, v.icon), el("span", { class: "nav-label" }, v.title)));
  }
}

function start(user) {
  state.user = user;
  document.getElementById("login").hidden = true;
  document.getElementById("shell").hidden = false;
  state.api = new Api();
  state.api.on("offline", () => banner("Connexion perdue : reconnexion…", "warning"));
  state.api.on("online", () => { banner(""); checkVersion(); });
  state.api.on("logged-out", () => { state.api.close(); showLogin(start); });
  state.api.on("notice", (d) => banner(d.text, "info"));
  state.api.on("chat.event", soonRefreshWaiting);
  state.api.on("reconnected", soonRefreshWaiting);
  state.api.connect();
  buildNav();
  render();
  refreshWaiting();
  offerInstall();
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

document.getElementById("logout").addEventListener("click", async () => {
  if (!await confirmSheet({ title: "Se déconnecter ?", body: "Les chats continuent sur le serveur.",
    confirm: "Se déconnecter" })) return;
  const r = await post("/api/logout");
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
