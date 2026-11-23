// Gestion des fichiers d'un projet : télécharger, envoyer, créer, renommer, supprimer, copier,
// couper et coller.
// Les transferts passent par le pont, morceau par morceau (une ligne RPC est bornée).
import { confirmSheet, el, toast } from "./dom.js";

export const CHUNK = 1024 * 1024;                 // octets par morceau, comme côté pont
export const MAX_TRANSFER = 200 * 1024 * 1024;

export function toBase64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function fromBase64(text) {
  const s = atob(text);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

export function size(n) {
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} Ko`;
  return `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} Mo`;
}

// Icônes SVG au trait (24 × 24, couleur du texte), dessinées ici : aucune dépendance. Partagées
// par le volet Fichiers, le gestionnaire de fichiers et leurs feuilles d'actions.
const DOC = "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5";
const FOLDER = "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z";
const TRAY = " M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3";
const ICONS = {
  dir: FOLDER,
  file: DOC,
  text: `${DOC} M9 13h6 M9 17h6`,
  doc: `${DOC} M9 13h6 M9 17h3`,
  code: `${DOC} M10 12.5l-2 2 2 2 M14 12.5l2 2-2 2`,
  config: `${DOC} M8.5 13h2 M13.5 13h2 M8.5 17h5`,
  image: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z M20 15l-5-5L5 20 M9 7.5a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3z",
  archive: "M4 4h16v4H4z M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8 M10 12h4",
  media: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z M10 9v6l5-3z",
  "new-file": `${DOC} M12 11v6 M9 14h6`,
  "new-dir": `${FOLDER} M12 10v6 M9 13h6`,
  upload: `M12 15V4 M7.5 8.5L12 4l4.5 4.5${TRAY}`,
  download: `M12 4v11 M7.5 10.5L12 15l4.5-4.5${TRAY}`,
  paste: "M9 3h6v4H9z M9 5H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-3",
  more: "M5 11a1 1 0 1 0 0 2a1 1 0 1 0 0-2z M12 11a1 1 0 1 0 0 2a1 1 0 1 0 0-2z M19 11a1 1 0 1 0 0 2a1 1 0 1 0 0-2z",
  chevron: "M9 6l6 6-6 6",
  grid: "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
  list: "M8 6h12 M8 12h12 M8 18h12 M4 6h.01 M4 12h.01 M4 18h.01",
  back: "M15 5l-7 7 7 7",
  search: "M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14z M20 20l-4-4",
  home: "M4 11l8-7 8 7 M6 9.5V20h12V9.5",
  wrap: "M4 6h16 M4 12h13a3 3 0 0 1 0 6h-4 M15 16l-2 2 2 2 M4 18h5",
  edit: "M4 20h4L19 9l-4-4L4 16z M13 7l4 4",
  save: "M5 12.5l4.5 4.5L19 7.5",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6z",
  copy: "M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1",
  cut: "M6 4a3 3 0 1 0 0 6a3 3 0 1 0 0-6z M6 14a3 3 0 1 0 0 6a3 3 0 1 0 0-6z M8.5 8.5L20 19 M8.5 15.5L20 5",
  trash: "M4 7h16 M10 11v6 M14 11v6 M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12 M9 7V4h6v3",
  open: "M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v1 M3 7v10a2 2 0 0 0 2 2h12l3.5-8H7.5L4 19",
};

// Icône de chaque action des feuilles d'actions (clés de FileManager.menu et du gestionnaire).
const ACTION_ICONS = { file: "new-file", dir: "new-dir", upload: "upload", paste: "paste", open: "open",
  project: "new-dir", download: "download", copy: "copy", move: "cut", rename: "edit", delete: "trash" };

export function icon(name, cls = "") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  const attrs = { class: `ico${cls ? ` ${cls}` : ""}`, viewBox: "0 0 24 24", width: "20", height: "20", fill: "none",
    stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round",
    "aria-hidden": "true", focusable: "false" };
  for (const [k, v] of Object.entries(attrs)) svg.setAttribute(k, v);
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICONS[name] || ICONS.file);
  svg.append(path);
  return svg;
}

// Libellé d'un bouton à icône : le texte reste dans le bouton (lecteurs d'écran, tests) ; au
// téléphone, la feuille de style peut le replier.
export const label = (text) => el("span", { class: "btn-label" }, text);

const KINDS = {
  image: "png jpg jpeg gif webp svg bmp ico avif heic tif tiff",
  code: "js mjs cjs ts tsx jsx py rb go rs c h cc cpp hpp java kt swift php sh bash zsh fish lua pl r sql css scss less html htm vue svelte dart cs",
  config: "json yaml yml toml ini cfg conf env xml lock service desktop gitignore editorconfig",
  text: "txt md markdown rst log csv tsv tex org adoc",
  archive: "zip tar gz tgz bz2 xz zst 7z rar deb rpm jar war iso",
  media: "mp3 wav ogg flac m4a opus mp4 mkv webm avi mov",
  doc: "pdf odt ods odp doc docx xls xlsx ppt pptx epub",
};
const BY_EXT = new Map(Object.entries(KINDS).flatMap(([kind, exts]) => exts.split(" ").map((e) => [e, kind])));
const BY_NAME = { makefile: "code", dockerfile: "code", license: "text", readme: "text", changelog: "text" };

// Famille d'un fichier d'après son nom : son icône et sa couleur.
export function kindOf(name, dir = false) {
  if (dir) return "dir";
  const low = name.toLowerCase();
  const dot = low.lastIndexOf(".");
  return BY_EXT.get(dot >= 0 ? low.slice(dot + 1) : "") || BY_NAME[low] || (dot === 0 ? "config" : "file");
}

// Tout le fichier, morceau par morceau ; `progress(reçu, total)` après chaque morceau.
// `archive` : jeton d'une archive préparée par `files.archive` (au lieu d'un chemin).
export async function fetchFile(api, path, progress = null, { archive = null } = {}) {
  const parts = [];
  let got = 0;
  for (;;) {
    const r = await api.call("files.download", archive ? { archive, offset: got } : { path, offset: got });
    const bytes = fromBase64(r.data);
    parts.push(bytes);
    got += bytes.length;
    progress?.(got, r.size);
    if (r.done || !bytes.length) return new Blob(parts);
  }
}

// `file` : un File (ou Blob) du navigateur. Le dernier morceau porte `last` : le pont donne alors
// au fichier son vrai nom.
export async function sendFile(api, dir, name, file, { replace = false, progress = null } = {}) {
  if (file.size > MAX_TRANSFER) throw new Error("Fichier trop gros pour être envoyé (200 Mo au plus).");
  let offset = 0;
  do {
    const bytes = new Uint8Array(await file.slice(offset, offset + CHUNK).arrayBuffer());
    const last = offset + bytes.length >= file.size;
    await api.call("files.upload", { dir, name, offset, data: toBase64(bytes), last, replace });
    offset += bytes.length;
    progress?.(offset, file.size);
  } while (offset < file.size);
}

// Remet le fichier au navigateur, qui l'enregistre dans ses téléchargements.
export function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: name, hidden: true });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export async function download(api, path) {
  const name = path.split("/").pop();
  const note = toast(`Téléchargement de « ${name} »…`, { timeout: 600000 });
  try {
    saveBlob(await fetchFile(api, path), name);
    toast(`« ${name} » téléchargé.`);
  } catch (e) {
    toast(e.message, { kind: "error" });
  } finally {
    note();
  }
}

// Un dossier entier : le pont en fait une archive .zip, téléchargée comme un fichier.
export async function downloadFolder(api, path) {
  const name = path.split("/").pop() || "dossier";
  const note = toast(`Archive de « ${name} » en préparation…`, { timeout: 600000 });
  try {
    const a = await api.call("files.archive", { path });
    saveBlob(await fetchFile(api, null, null, { archive: a.archive }), a.name);
    toast(`« ${a.name} » téléchargé.`);
  } catch (e) {
    toast(e.message, { kind: "error" });
  } finally {
    note();
  }
}

// Demande un nom ; renvoie le texte saisi, ou null si l'utilisateur annule.
export function nameSheet({ title, value = "", confirm = "Valider" }) {
  return new Promise((resolve) => {
    const dlg = el("dialog", { class: "sheet", "aria-label": title });
    const input = el("input", { type: "text", value, "aria-label": "Nom", autocapitalize: "off", autocomplete: "off", spellcheck: "false" });
    const done = (v) => { if (dlg.open) dlg.close(); dlg.remove(); resolve(v); };
    const form = el("form", { onsubmit: (e) => { e.preventDefault(); const v = input.value.trim(); if (v) done(v); } },
      el("h2", {}, title), input,
      el("div", { class: "sheet-actions" },
        el("button", { type: "button", onclick: () => done(null) }, "Annuler"),
        el("button", { type: "submit", class: "primary" }, confirm)));
    dlg.append(form);
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(null); });
    document.body.append(dlg);
    dlg.showModal();
    input.focus();
    const dot = value.lastIndexOf(".");
    input.setSelectionRange?.(0, dot > 0 ? dot : value.length);
  });
}

// Feuille d'actions d'une entrée ; renvoie l'action choisie (sa clé) ou null.
export function actionSheet(title, actions) {
  return new Promise((resolve) => {
    const dlg = el("dialog", { class: "sheet", "aria-label": title });
    const done = (v) => { if (dlg.open) dlg.close(); dlg.remove(); resolve(v); };
    dlg.append(el("h2", { class: "sheet-name" }, title),
      el("div", { class: "sheet-list" }, ...actions.map(([key, label, danger]) =>
        el("button", { type: "button", class: `menu-item${danger ? " danger-text" : ""}`, onclick: () => done(key) },
          ACTION_ICONS[key] ? icon(ACTION_ICONS[key]) : null, label))),
      el("div", { class: "sheet-actions" }, el("button", { type: "button", onclick: () => done(null) }, "Fermer")));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(null); });
    document.body.append(dlg);
    dlg.showModal();
  });
}

// Choix de fichiers sur l'appareil ; renvoie la liste (vide si rien n'est choisi).
export function pickFiles() {
  return new Promise((resolve) => {
    const input = el("input", { type: "file", multiple: true, hidden: true });
    input.addEventListener("change", () => { const files = [...input.files]; input.remove(); resolve(files); });
    input.addEventListener("cancel", () => { input.remove(); resolve([]); });
    document.body.append(input);
    input.click();
  });
}

// Ce qui attend d'être collé : { path, name, mode: "copy" | "move" }. Commun à tous les volets : on
// copie dans un dossier, on colle dans un autre.
let clip = null;
export const clipboard = () => clip;

// Actions de gestion, pour le volet Fichiers. `root` : dossier du projet ; chaque méthode renvoie
// true si quelque chose a changé (le volet recharge alors le dossier touché). `extra` : actions en
// plus sur un dossier, { actions(entry) → [[clé, libellé]], run(clé, entry) → { changed, … } }.
export class FileManager {
  constructor(api, root, extra = null) { this.api = api; this.root = root; this.extra = extra; }

  abs(rel) { return rel ? `${this.root}/${rel}` : this.root; }

  async guard(work) {
    try { return await work(); } catch (e) { toast(e.message, { kind: "error" }); return false; }
  }

  async create(rel, kind) {
    const name = await nameSheet({ title: kind === "dir" ? "Nouveau dossier" : "Nouveau fichier", confirm: "Créer" });
    if (!name) return false;
    return this.guard(async () => {
      await this.api.call(kind === "dir" ? "files.mkdir" : "files.create", { dir: this.abs(rel), name });
      return true;
    });
  }

  async upload(rel) {
    const files = await pickFiles();
    let changed = false;
    for (const file of files) {
      const note = toast(`Envoi de « ${file.name} »…`, { timeout: 600000 });
      const send = (replace) => sendFile(this.api, this.abs(rel), file.name, file, { replace });
      try {
        try { await send(false); } catch (e) {
          if (e.code !== "existe") throw e;
          if (!await confirmSheet({ title: `Remplacer « ${file.name} » ?`, body: "Un fichier de ce nom existe déjà dans ce dossier.",
            confirm: "Remplacer", danger: true })) continue;
          await send(true);
        }
        changed = true;
        toast(`« ${file.name} » envoyé (${size(file.size)}).`);
      } catch (e) {
        toast(e.message, { kind: "error" });
      } finally {
        note();
      }
    }
    return changed;
  }

  async rename(entry) {
    const name = await nameSheet({ title: `Renommer « ${entry.name} »`, value: entry.name, confirm: "Renommer" });
    if (!name || name === entry.name) return false;
    return this.guard(async () => {
      await this.api.call("files.rename", { path: this.abs(entry.path), name, root: this.root });
      return true;
    });
  }

  async remove(entry) {
    return this.guard(async () => {
      const info = await this.api.call("files.info", { path: this.abs(entry.path) });
      const body = info.dir
        ? (info.count ? `Ce dossier et les ${info.count} éléments qu'il contient seront supprimés pour de bon.` : "Ce dossier vide sera supprimé.")
        : `Ce fichier (${size(info.size)}) sera supprimé pour de bon.`;
      if (!await confirmSheet({ title: `Supprimer « ${entry.name} » ?`, body, confirm: "Supprimer", danger: true })) return false;
      await this.api.call("files.delete", { path: this.abs(entry.path), root: this.root });
      toast(`« ${entry.name} » supprimé.`);
      return true;
    });
  }

  hold(entry, mode) {
    clip = { path: this.abs(entry.path), name: entry.name, mode };
    toast(`« ${entry.name} » ${mode === "move" ? "coupé" : "copié"} : ouvre le menu « ⋯ » d'un dossier, puis « Coller ici ».`);
  }

  // Colle dans le dossier `rel` ce qui a été copié ou coupé.
  async paste(rel) {
    const held = clip;
    if (!held) return false;
    return this.guard(async () => {
      await this.api.call("files.paste", { path: held.path, dir: this.abs(rel), mode: held.mode, root: this.root });
      if (held.mode === "move") clip = null;
      toast(`« ${held.name} » ${held.mode === "move" ? "déplacé" : "copié"}.`);
      return true;
    });
  }

  // Menu d'une entrée de l'arbre. Renvoie { changed, inside } : `inside` dit que c'est le contenu
  // du dossier (et non son parent) qui a changé.
  async menu(entry) {
    const own = [["copy", "Copier"], ["move", "Couper"], ["rename", "Renommer"], ["delete", "Supprimer", true]];
    const extra = entry.dir && this.extra ? this.extra.actions(entry) : [];
    const actions = entry.dir
      ? [["file", "Nouveau fichier ici"], ["dir", "Nouveau dossier ici"], ["upload", "Envoyer un fichier ici"],
        ...(clip ? [["paste", `Coller « ${clip.name} » ici`]] : []), ...extra, ["zip", "Télécharger (.zip)"], ...own]
      : [["download", "Télécharger"], ...own];
    const pick = await actionSheet(entry.name, actions);
    if (extra.some(([key]) => key === pick)) return this.extra.run(pick, entry);
    if (pick === "copy" || pick === "move") { this.hold(entry, pick); return { changed: false, clip: true }; }
    if (pick === "paste") { const moved = clip?.mode === "move"; const changed = await this.paste(entry.path); return { changed, inside: true, all: changed && moved }; }
    if (pick === "zip") { await downloadFolder(this.api, this.abs(entry.path)); return { changed: false }; }
    if (pick === "download") { await download(this.api, this.abs(entry.path)); return { changed: false }; }
    if (pick === "file" || pick === "dir") return { changed: await this.create(entry.path, pick), inside: true };
    if (pick === "upload") return { changed: await this.upload(entry.path), inside: true };
    if (pick === "rename") return { changed: await this.rename(entry) };
    if (pick === "delete") return { changed: await this.remove(entry) };
    return { changed: false };
  }
}
