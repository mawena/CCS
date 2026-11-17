// Gestionnaire de fichiers : parcourir les dossiers permis du serveur (dossier personnel, /var/www,
// /srv), y faire tout ce que fait le volet Fichiers d'un projet (ouvrir, modifier, créer, envoyer,
// télécharger, renommer, supprimer, copier, déplacer) et ajouter un dossier aux projets de CCS.
import { clear, confirmSheet, el, errorState, loading, toast } from "./dom.js";
import { FilesPanel, icon, label } from "./files.js";

const under = (path, root) => path === root || path.startsWith(`${root.replace(/\/$/, "")}/`);
const base = (p) => p.split("/").filter(Boolean).pop() || "/";
const address = (path) => `#/fichiers/${encodeURIComponent(path)}`;

export async function addProject(api, cwd) {
  try {
    const r = await api.call("projects.add", { cwd });
    toast(`« ${base(r.cwd)} » ajouté aux projets.`, { kind: "success",
      action: { label: "Ouvrir", run: () => { location.hash = `#/sessions/${encodeURIComponent(`projet/${r.cwd}`)}`; } } });
  } catch (e) { toast(e.message, { kind: "error" }); }
}

export function mountFiles(container, api, ctx) {
  const crumbs = el("nav", { class: "crumbs", "aria-label": "Dossier ouvert" });
  const holder = el("div", { class: "browser-body" });
  const node = el("section", { class: "card browser" }, el("div", { class: "browser-head" }, crumbs,
    el("button", { type: "button", class: "small add-project", title: "Ajouter ce dossier aux projets de CCS",
      onclick: () => state.path && addProject(api, state.path) }, icon("new-dir"), label("Ajouter aux projets"))), holder);
  container.append(node);
  const state = { roots: null, home: null, path: null, panel: null };

  const extra = {
    actions: () => [["open", "Ouvrir ce dossier"], ["project", "Ajouter aux projets de CCS"]],
    run: async (key, entry) => {
      const path = `${state.path}/${entry.path}`;
      if (key === "open") go(path); else await addProject(api, path);
      return { changed: false };
    },
  };

  async function go(path) {
    if (state.panel?.dirty && !await confirmSheet({ title: "Abandonner les modifications ?",
      body: "Le fichier ouvert n'est pas enregistré.", confirm: "Abandonner", danger: true })) return;
    if (location.hash === address(path)) show(path); else location.hash = address(path);
  }

  // Fil d'Ariane : la racine (« Personnel », /var/www…), puis chaque dossier jusqu'à celui ouvert.
  function drawCrumbs(path) {
    const root = state.roots.find((r) => under(path, r)) || state.home;
    const parts = path.slice(root.length).split("/").filter(Boolean);
    clear(crumbs);
    if (state.roots.length > 1) {
      const pick = el("select", { "aria-label": "Racine", onchange: () => go(pick.value) },
        ...state.roots.map((r) => el("option", { value: r, selected: r === root }, r === state.home ? "Personnel" : r)));
      crumbs.append(el("span", { class: "crumb-root" }, icon(root === state.home ? "home" : "dir"), pick));
    } else crumbs.append(el("button", { type: "button", class: "small flat crumb", onclick: () => go(root) }, icon("home"), "Personnel"));
    let at = root;
    parts.forEach((name, i) => {
      at = `${at.replace(/\/$/, "")}/${name}`;
      const here = at;
      crumbs.append(el("span", { class: "crumb-sep", "aria-hidden": "true" }, icon("chevron")),
        i === parts.length - 1 ? el("strong", { class: "crumb here", "aria-current": "page" }, name)
          : el("button", { type: "button", class: "small flat crumb", onclick: () => go(here) }, name));
    });
    crumbs.scrollLeft = crumbs.scrollWidth;        // au téléphone, le dossier ouvert reste visible
  }

  function show(path) {
    if (!state.roots) return;
    const clean = path && state.roots.some((r) => under(path, r)) ? path.replace(/(.)\/+$/, "$1") : state.home;
    state.path = clean;
    drawCrumbs(clean);
    state.panel = new FilesPanel(clear(holder), api, clean, { extra });
  }

  async function start() {
    clear(holder).append(loading());
    try {
      const r = await api.call("files.roots");
      state.roots = r.roots;
      state.home = r.home;
    } catch (e) { clear(holder).append(errorState(e.message, start)); return; }
    show(wanted);
  }

  let wanted = ctx.sub ? decodeURIComponent(ctx.sub) : "";
  start();
  return { cleanup: () => {}, route: (sub) => { wanted = sub ? decodeURIComponent(sub) : ""; show(wanted); } };
}
