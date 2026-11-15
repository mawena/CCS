// Charpente de la version web : connexion, navigation, bandeau de reconnexion, thème.
import { Api, post, session } from "./api.js";
import { clear, el } from "./dom.js";
import { showLogin } from "./login.js";
import { VIEWS } from "./views.js";

const state = { api: null, user: null, cleanup: null };

function banner(text, kind = "info") {
  const b = document.getElementById("banner");
  b.textContent = text || "";
  b.className = `banner ${kind}`;
  b.hidden = !text;
}

function route() {
  const name = (location.hash.replace(/^#\/?/, "").split("/")[0]) || "accueil";
  return VIEWS[name] ? name : "accueil";
}

function render() {
  const name = route();
  for (const a of document.querySelectorAll("#nav a")) a.classList.toggle("active", a.dataset.view === name);
  if (state.cleanup) { try { state.cleanup(); } catch (e) { console.error(e); } }
  const view = clear(document.getElementById("view"));
  view.dataset.view = name;
  document.title = `${VIEWS[name].title} · CCS`;
  state.cleanup = VIEWS[name].mount(view, state.api, { user: state.user, banner }) || null;
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
  state.api.on("online", () => banner(""));
  state.api.on("logged-out", () => { state.api.close(); showLogin(start); });
  state.api.on("notice", (d) => banner(d.text, "info"));
  state.api.connect();
  buildNav();
  render();
}

window.addEventListener("hashchange", () => { if (state.api) render(); });

document.getElementById("logout").addEventListener("click", async () => {
  await post("/api/logout");
  state.api?.close();
  state.api = null;
  location.hash = "";
  showLogin(start);
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

session().then((s) => (s ? start(s.user) : showLogin(start)))
  .catch(() => { banner("Serveur injoignable.", "error"); showLogin(start); });
