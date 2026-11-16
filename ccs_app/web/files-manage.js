// Gestion des fichiers d'un projet : télécharger, envoyer, créer, renommer, supprimer.
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

// Tout le fichier, morceau par morceau ; `progress(reçu, total)` après chaque morceau.
export async function fetchFile(api, path, progress = null) {
  const parts = [];
  let got = 0;
  for (;;) {
    const r = await api.call("files.download", { path, offset: got });
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
        el("button", { type: "button", class: `menu-item${danger ? " danger-text" : ""}`, onclick: () => done(key) }, label))),
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

// Actions de gestion, pour le volet Fichiers. `root` : dossier du projet ; chaque méthode renvoie
// true si quelque chose a changé (le volet recharge alors le dossier touché).
export class FileManager {
  constructor(api, root) { this.api = api; this.root = root; }

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

  // Menu d'une entrée de l'arbre. Renvoie { changed, inside } : `inside` dit que c'est le contenu
  // du dossier (et non son parent) qui a changé.
  async menu(entry) {
    const actions = entry.dir
      ? [["file", "Nouveau fichier ici"], ["dir", "Nouveau dossier ici"], ["upload", "Envoyer un fichier ici"],
        ["rename", "Renommer"], ["delete", "Supprimer", true]]
      : [["download", "Télécharger"], ["rename", "Renommer"], ["delete", "Supprimer", true]];
    const pick = await actionSheet(entry.name, actions);
    if (pick === "download") { await download(this.api, this.abs(entry.path)); return { changed: false }; }
    if (pick === "file" || pick === "dir") return { changed: await this.create(entry.path, pick), inside: true };
    if (pick === "upload") return { changed: await this.upload(entry.path), inside: true };
    if (pick === "rename") return { changed: await this.rename(entry) };
    if (pick === "delete") return { changed: await this.remove(entry) };
    return { changed: false };
  }
}
