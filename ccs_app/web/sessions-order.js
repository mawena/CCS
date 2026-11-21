// Ordre des sessions ouvertes (« En cours » et la barre d'onglets) : un tri au choix, ou un
// ordre manuel (glisser-déposer, ou « Monter » / « Descendre » du menu, pratique au téléphone).
// Le choix et l'ordre manuel sont gardés dans le navigateur.

const MODE_KEY = "ccs-sessions-tri";
const ORDER_KEY = "ccs-sessions-ordre";
const ORDER_MAX = 200;              // clés gardées au plus (les plus anciennes s'en vont)

export const MODES = [
  ["manuel", "Ordre manuel"],
  ["recent", "Activité récente"],
  ["nom", "Nom"],
  ["projet", "Projet"],
  ["etat", "État"],
];

// État : qui demande une action d'abord, puis ce qui travaille, puis le reste.
const STATE_RANK = { permission: 0, busy: 1, starting: 2, idle: 3, suspended: 4, term: 5, stopped: 6 };

export function getMode() {
  const m = localStorage.getItem(MODE_KEY);
  return MODES.some(([k]) => k === m) ? m : "manuel";
}

export function setMode(mode) {
  localStorage.setItem(MODE_KEY, mode);
}

// Clé stable d'une session : sa conversation (l'identifiant de chat change à la reprise).
export const keyOf = (id, t) => (t.term ? id : t.sessionId || id);

function loadOrder() {
  try {
    const v = JSON.parse(localStorage.getItem(ORDER_KEY) || "[]");
    return Array.isArray(v) ? v.filter((k) => typeof k === "string") : [];
  } catch { return []; }
}

function saveOrder(keys) {
  localStorage.setItem(ORDER_KEY, JSON.stringify(keys.slice(-ORDER_MAX)));
}

const collator = new Intl.Collator("fr", { sensitivity: "base", numeric: true });
const base = (p) => (p || "").replace(/\/+$/, "").split("/").pop() || p || "";

// entries : [[id, t], …] dans l'ordre d'ouverture → nouvel ordre selon le mode.
// Ordre manuel : les sessions déjà placées d'abord, les nouvelles à la fin (ordre d'ouverture).
export function sortEntries(entries, mode = getMode()) {
  const opened = new Map(entries.map(([id], i) => [id, i]));
  const tie = (a, b) => opened.get(a[0]) - opened.get(b[0]);
  const list = [...entries];
  if (mode === "recent") return list.sort((a, b) => (b[1].activeAt || 0) - (a[1].activeAt || 0) || tie(a, b));
  if (mode === "nom") return list.sort((a, b) => collator.compare(a[1].title || "", b[1].title || "") || tie(a, b));
  if (mode === "projet") {
    return list.sort((a, b) => collator.compare(base(a[1].cwd), base(b[1].cwd))
      || collator.compare(a[1].title || "", b[1].title || "") || tie(a, b));
  }
  if (mode === "etat") {
    const rank = (t) => STATE_RANK[t.term ? "term" : t.state] ?? 9;
    return list.sort((a, b) => rank(a[1]) - rank(b[1]) || tie(a, b));
  }
  const pos = new Map(loadOrder().map((k, i) => [k, i]));
  const at = ([id, t]) => pos.get(keyOf(id, t)) ?? Infinity;
  return list.sort((a, b) => at(a) - at(b) || tie(a, b));
}

// Ordre manuel : `entries` (l'ordre affiché) devient l'ordre gardé. Les clés des sessions
// fermées restent (une session rouverte retrouve sa place), après celles qui sont ouvertes.
export function remember(entries) {
  const keys = entries.map(([id, t]) => keyOf(id, t));
  const shown = new Set(keys);
  saveOrder([...keys, ...loadOrder().filter((k) => !shown.has(k))]);
}

// Déplace la session `id` à la place de `target` (avant elle, ou après si `after`), ou de
// `delta` rangs (-1 : monter, +1 : descendre). Renvoie le nouvel ordre ; il est gardé, et le
// mode passe en « Ordre manuel » (déplacer à la main, c'est choisir son ordre).
export function move(entries, id, { target = null, after = false, delta = 0 } = {}) {
  const list = [...entries];
  const from = list.findIndex(([k]) => k === id);
  if (from < 0) return list;
  const [item] = list.splice(from, 1);
  let to;
  if (target !== null) {
    to = list.findIndex(([k]) => k === target);
    if (to < 0) return entries;
    if (after) to += 1;
  } else {
    to = Math.max(0, Math.min(list.length, from + delta));
  }
  list.splice(to, 0, item);
  setMode("manuel");
  remember(list);
  return list;
}
