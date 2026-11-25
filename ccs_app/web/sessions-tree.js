// Arbre des machines de la page Sessions : chaque onglet, chaque adresse et chaque projet dit sur
// quelle machine il vit, pour garder ouverts côte à côte des chats de plusieurs machines sans
// changer la machine pilotée. Logique pure (testée par node), sans DOM.

export const PROJECT_PREFIX = "projet/";
const TREE_KEY = "ccs.sessions.tree";

// Clé d'onglet : l'identifiant brut sur la machine pilotée (adresses d'avant inchangées),
// « m~<machine>~<id> » ailleurs (deux machines peuvent donner le même identifiant de chat).
export function tabKey(primary, machine, rid) {
  return machine === primary ? rid : `m~${machine}~${rid}`;
}

export function splitKey(primary, key) {
  if (typeof key === "string" && key.startsWith("m~")) {
    const i = key.indexOf("~", 2);
    if (i >= 2) return { machine: key.slice(2, i), rid: key.slice(i + 1) };
  }
  return { machine: primary, rid: key };
}

// Sous-adresse d'un écran Projet : « projet/<chemin> » ici, « projet~<machine>/<chemin> » ailleurs.
export function projectSub(primary, machine, cwd) {
  return machine === primary ? `${PROJECT_PREFIX}${cwd}` : `projet~${machine}/${cwd}`;
}

export function parseProject(primary, sub) {
  if (typeof sub !== "string") return null;
  if (sub.startsWith(PROJECT_PREFIX)) return { machine: primary, cwd: sub.slice(PROJECT_PREFIX.length) };
  if (sub.startsWith("projet~")) {
    const i = sub.indexOf("/", 7);
    if (i >= 7) return { machine: sub.slice(7, i), cwd: sub.slice(i + 1) };
  }
  return null;
}

// Racines de l'arbre : la machine pilotée d'abord, puis ce serveur et les autres machines connues.
export function roots(primary, machines, primaryName = "") {
  const all = [{ id: "", name: "Ce serveur", online: true, tunnel: true, server: true },
    ...(machines || []).filter((m) => m && m.id)];
  if (!all.some((m) => m.id === primary)) all.push({ id: primary, name: primaryName || primary, online: true, tunnel: true });
  return [...all.filter((m) => m.id === primary), ...all.filter((m) => m.id !== primary)];
}

// État gardé : nœuds dépliés (`open`) et machines dont les sessions sont rattachées (`attached`,
// reconnectées au chargement pour retrouver leurs onglets).
export function loadTree() {
  try {
    const t = JSON.parse(localStorage.getItem(TREE_KEY) || "{}") || {};
    return { open: t.open && typeof t.open === "object" ? t.open : {},
      attached: Array.isArray(t.attached) ? t.attached.filter((x) => typeof x === "string") : [] };
  } catch { return { open: {}, attached: [] }; }
}

export function saveTree(tree) {
  try { localStorage.setItem(TREE_KEY, JSON.stringify(tree)); } catch { /* navigation privée */ }
}

// Déplié par défaut : la machine pilotée seulement.
export function isOpen(tree, id, primary) {
  return Object.prototype.hasOwnProperty.call(tree.open, id) ? Boolean(tree.open[id]) : id === primary;
}
