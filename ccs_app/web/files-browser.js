// Gestionnaire de fichiers de tous les appareils : le serveur CCS et chaque PC du réseau maillé
// où CCS est installé (connexion à part, relayée par le pont du serveur jusqu'au pont de la machine
// : SSH par le réseau maillé, Ricochet en secours). Dans chacun, parcourir les dossiers permis
// (dossier personnel, /var/www, /srv), y faire tout ce que fait le volet Fichiers d'un projet
// (ouvrir, modifier, créer, envoyer, télécharger, renommer, supprimer, copier, déplacer) et
// ajouter un dossier aux projets de CCS. Adresse : #/fichiers/<chemin> pour le serveur,
// #/fichiers/@<machine>/<chemin> pour un autre appareil.
import { Api } from "./api.js";
import { clear, confirmSheet, el, errorState, loading, toast } from "./dom.js";
import { FilesPanel, icon, label } from "./files.js";
import { deviceKind, icon as netIcon } from "./reseau.js";

const DEVICE_KEY = "ccs.files.device";

const under = (path, root) => path === root || path.startsWith(`${root.replace(/\/$/, "")}/`);
const base = (p) => p.split("/").filter(Boolean).pop() || "/";
// « @pc-bureau/%2Fhome%2Fu » → { device: "pc-bureau", path: "/home/u" }
export function parseSub(sub) {
  const raw = sub || "";
  const m = /^@([A-Za-z0-9_-]{1,64})(?:\/(.*))?$/.exec(raw);
  if (m) return { device: m[1], path: m[2] ? decodeURIComponent(m[2]) : "" };
  return { device: "", path: raw ? decodeURIComponent(raw) : "" };
}

export function address(path, device = "") {
  return `#/fichiers/${device ? `@${device}/` : ""}${encodeURIComponent(path)}`;
}

export async function addProject(api, cwd) {
  try {
    const r = await api.call("projects.add", { cwd });
    toast(`« ${base(r.cwd)} » ajouté aux projets.`, { kind: "success",
      action: { label: "Ouvrir", run: () => { location.hash = `#/sessions/${encodeURIComponent(`projet/${r.cwd}`)}`; } } });
  } catch (e) { toast(e.message, { kind: "error" }); }
}

export function mountFiles(container, api, ctx) {
  const devices = el("div", { class: "file-devices", role: "tablist", "aria-label": "Appareil" });
  const crumbs = el("nav", { class: "crumbs", "aria-label": "Dossier ouvert" });
  const holder = el("div", { class: "browser-body" });
  const node = el("section", { class: "card browser" }, el("div", { class: "browser-head" }, crumbs,
    el("button", { type: "button", class: "small add-project", title: "Ajouter ce dossier aux projets de CCS",
      onclick: () => state.path && addProject(state.api, state.path) }, icon("new-dir"), label("Ajouter aux projets"))), holder);
  container.append(devices, node);
  // device : "" pour le serveur ; api : connexion de l'appareil ouvert
  const state = { device: null, api, own: null, roots: null, home: null, path: null, panel: null, machines: [], token: 0 };

  const extra = {
    actions: () => [["open", "Ouvrir ce dossier"], ["project", "Ajouter aux projets de CCS"]],
    run: async (key, entry) => {
      const path = `${state.path}/${entry.path}`;
      if (key === "open") go(path); else await addProject(state.api, path);
      return { changed: false };
    },
  };

  // ---- appareils ---------------------------------------------------------------------------

  // Les PC joignables : en ligne, par le réseau maillé ou le tunnel Ricochet. Les téléphones n'ont
  // pas de CCS : on ne peut pas y parcourir de dossiers.
  const reachable = (m) => !m.local && m.online && (m.mesh_ip || m.tunnel);

  function drawDevices() {
    const list = [{ id: "", name: "Serveur CCS", kind: "server", ok: true },
      ...state.machines.filter((m) => !m.local).map((m) => ({ id: m.id, name: m.name || m.id,
        kind: deviceKind({ name: m.mesh || m.id, os: "linux" }), ok: reachable(m),
        why: !m.online ? "hors ligne" : "ni réseau maillé ni tunnel" }))];
    clear(devices).append(...list.map((d) => el("button", {
      type: "button", role: "tab", class: `file-device${d.ok ? "" : " off"}`, disabled: !d.ok,
      "aria-selected": String(d.id === state.device), title: d.ok ? `Fichiers de ${d.name}` : `${d.name} : ${d.why}`,
      onclick: () => { if (d.id !== state.device) go("", d.id); },
    }, netIcon(d.kind === "server" ? "server" : d.kind, 18), el("span", {}, d.name),
    d.ok ? null : el("small", { class: "subtle" }, d.why))));
    devices.hidden = list.length < 2;
  }

  async function loadDevices() {
    try { state.machines = (await api.call("machines.list")).machines || []; } catch { state.machines = []; }
    drawDevices();
  }

  // ---- navigation --------------------------------------------------------------------------

  async function go(path, device = state.device) {
    if (state.panel?.dirty && !await confirmSheet({ title: "Abandonner les modifications ?",
      body: "Le fichier ouvert n'est pas enregistré.", confirm: "Abandonner", danger: true })) return;
    const to = address(path, device);
    if (location.hash === to) open(device, path); else location.hash = to;
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
    state.panel = new FilesPanel(clear(holder), state.api, clean, { extra });
  }

  // Ouvre un appareil (nouvelle connexion s'il change), puis le dossier demandé.
  async function open(device, path) {
    if (device === state.device && state.roots) { show(path); return; }
    const token = ++state.token;
    state.own?.close();
    state.own = null;
    state.device = device;
    state.roots = null;
    try { localStorage.setItem(DEVICE_KEY, device); } catch { /* privé */ }
    drawDevices();
    clear(crumbs);
    clear(holder).append(loading());
    // La connexion principale suit la machine pilotée : on la réutilise seulement si c'est
    // l'appareil choisi, sinon (serveur CCS ou autre PC) on ouvre une connexion à part.
    if (device === (api.machine || "")) state.api = api;
    else {
      state.own = new Api({ machine: device });
      state.own.connect();
      state.api = state.own;
    }
    try {
      const r = await state.api.call("files.roots");
      if (token !== state.token) return;
      state.roots = r.roots;
      state.home = r.home;
    } catch (e) {
      if (token !== state.token) return;
      const name = state.machines.find((m) => m.id === device)?.name || device;
      clear(holder).append(errorState(device ? `${name} injoignable : ${e.message}` : e.message,
        () => { state.device = null; open(device, path); }));
      return;
    }
    show(path);
  }

  const first = parseSub(ctx.sub);
  let remembered = "";
  try { remembered = localStorage.getItem(DEVICE_KEY) || ""; } catch { /* privé */ }
  open(ctx.sub ? first.device : remembered, first.path);
  loadDevices();
  return {
    cleanup: () => { state.token += 1; state.own?.close(); },
    route: (sub) => { const w = parseSub(sub); open(w.device, w.path); },
  };
}
