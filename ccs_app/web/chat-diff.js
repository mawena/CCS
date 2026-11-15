// Modifications de Claude (Edit, MultiEdit, Write) en diff coloré, repliable, avec « Ouvrir le fichier ».
import { el } from "./dom.js";

const LCS_MAX = 90000;      // au-delà (lignes × lignes), pas de LCS : tout retiré puis tout ajouté

function lines(text) {
  if (typeof text !== "string" || text === "") return [];
  const out = text.split("\n");
  if (out[out.length - 1] === "") out.pop();
  return out;
}

// Lignes communes au début et à la fin gardées en contexte ; le milieu par plus longue sous-suite.
export function lineDiff(before, after) {
  const a = lines(before);
  const b = lines(after);
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head++;
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail++;
  const ma = a.slice(head, a.length - tail);
  const mb = b.slice(head, b.length - tail);
  const out = a.slice(0, head).map((s) => ({ t: " ", s }));
  if (ma.length * mb.length > LCS_MAX) {
    out.push(...ma.map((s) => ({ t: "-", s })), ...mb.map((s) => ({ t: "+", s })));
  } else {
    const n = ma.length;
    const m = mb.length;
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) dp[i][j] = ma[i] === mb[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (ma[i] === mb[j]) { out.push({ t: " ", s: ma[i] }); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: "-", s: ma[i++] });
      else out.push({ t: "+", s: mb[j++] });
    }
    while (i < n) out.push({ t: "-", s: ma[i++] });
    while (j < m) out.push({ t: "+", s: mb[j++] });
  }
  out.push(...a.slice(a.length - tail).map((s) => ({ t: " ", s })));
  return out;
}

// [{ path, lines }] pour un outil qui modifie un fichier ; null pour les autres outils.
export function editDiffs(name, input) {
  const i = input || {};
  const path = i.file_path || "";
  if (!path) return null;
  if (name === "Edit") return [{ path, lines: lineDiff(i.old_string, i.new_string)}];
  if (name === "MultiEdit" && Array.isArray(i.edits)) {
    const all = [];
    i.edits.forEach((e, k) => {
      if (k) all.push({ t: "@", s: `modification ${k + 1}` });
      all.push(...lineDiff(e && e.old_string, e && e.new_string));
    });
    return [{ path, lines: all }];
  }
  if (name === "Write") return [{ path, lines: lineDiff("", i.content) }];
  return null;
}

export function countLines(list) {
  let add = 0;
  let del = 0;
  for (const l of list) { if (l.t === "+") add++; else if (l.t === "-") del++; }
  return { add, del };
}

// Diff unifié (texte du pont) → mêmes lignes ; les en-têtes `---` / `+++` sont ignorés.
export function parseUnified(text) {
  const out = [];
  for (const raw of String(text || "").split("\n")) {
    if (raw.startsWith("--- ") || raw.startsWith("+++ ")) continue;
    if (raw.startsWith("@@")) out.push({ t: "@", s: raw });
    else if (raw.startsWith("+")) out.push({ t: "+", s: raw.slice(1) });
    else if (raw.startsWith("-")) out.push({ t: "-", s: raw.slice(1) });
    else if (raw.startsWith(" ")) out.push({ t: " ", s: raw.slice(1) });
  }
  return out;
}

const SIGN = { "+": "+", "-": "−", " ": " ", "@": "" };

export function diffBlock(list) {
  const pre = el("pre", { class: "diff" });
  for (const l of list) {
    pre.append(el("span", { class: `dl ${l.t === "+" ? "add" : l.t === "-" ? "del" : l.t === "@" ? "hunk" : "ctx"}` },
      el("span", { class: "sign", "aria-hidden": "true" }, SIGN[l.t]), l.s, "\n"));
  }
  return pre;
}

export function statBadges(list) {
  const { add, del } = countLines(list);
  return [el("span", { class: "stat add" }, `+${add}`), el("span", { class: "stat del" }, `−${del}`)];
}

// Carte d'un outil de modification : résumé (outil, fichier, +n −n), diff, bouton « Ouvrir le fichier ».
export function diffCard({ label, diffs, nested, onOpen }) {
  const [d] = diffs;
  const result = el("pre", { class: "tool-result", hidden: true });
  const card = el("details", { class: `tool edit${nested ? " nested" : ""}` },
    el("summary", {}, el("strong", {}, label), " ", el("span", { class: "subtle path" }, d.path), ...statBadges(d.lines)),
    diffBlock(d.lines),
    el("div", { class: "tool-actions" },
      el("button", { type: "button", class: "small", onclick: () => onOpen(d.path) }, "Ouvrir le fichier")),
    result);
  card.result = result;
  return card;
}
