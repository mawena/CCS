// Étiquettes sur les messages du chat : pastilles sous un message, feuille « Étiqueter » (saisie
// séparée par des virgules, suggestions des étiquettes déjà utilisées) et volet « Étiquettes »
// (messages groupés par étiquette, un clic ramène au message). Le stockage est sur le serveur
// (`chat.tags`, `chat.tag`, message_tags.py) ; le nettoyage ici suit celui du serveur.
import { clear, el, emptyState } from "./dom.js";

export const MAX_TAGS = 10;
export const MAX_TAG_CHARS = 40;
export const TAG_ICON = [["path", { d: "M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" }], ["circle", { cx: "7.5", cy: "7.5", r: "1.5" }]];

export function cleanTag(tag) {
  return typeof tag === "string" ? tag.replace(/,/g, " ").split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_TAG_CHARS).trim() : "";
}

// Étiquettes propres, sans doublon (sans tenir compte de la casse), dans l'ordre donné.
export function cleanTags(tags) {
  const out = [], seen = new Set();
  for (const t of Array.isArray(tags) ? tags : []) {
    const tag = cleanTag(t), key = tag.toLocaleLowerCase("fr");
    if (tag && !seen.has(key)) { seen.add(key); out.push(tag); }
  }
  return out.slice(0, MAX_TAGS);
}

export function parseTags(text) {
  return typeof text === "string" ? cleanTags(text.split(",")) : [];
}

// [[étiquette, [[identifiant, entrée], …]], …] : étiquettes par ordre alphabétique (« Important »
// rejoint « important »), messages dans l'ordre où ils ont été étiquetés.
export function byTag(messages) {
  const groups = new Map();
  const items = Object.entries(messages || {}).sort((a, b) => (a[1].ts || 0) - (b[1].ts || 0));
  for (const [id, entry] of items) {
    for (const tag of entry.tags || []) {
      const key = tag.toLocaleLowerCase("fr");
      if (!groups.has(key)) groups.set(key, [tag, []]);
      groups.get(key)[1].push([id, entry]);
    }
  }
  return [...groups.values()].sort((a, b) => a[0].localeCompare(b[0], "fr", { sensitivity: "base" }));
}

// Pastilles sous un message ; un clic ouvre le volet sur cette étiquette.
export function tagChips(tags, onPick = null) {
  if (!tags?.length) return null;
  return el("div", { class: "msg-tags" }, ...tags.map((t) => el("button", { type: "button", class: "tag-chip",
    title: `Messages étiquetés « ${t} »`, onclick: (e) => { e.stopPropagation(); onPick?.(t); } }, t)));
}

// Feuille « Étiqueter » : rend la liste choisie (peut-être vide : tout retirer), ou null si annulé.
export function openTagSheet({ current = [], known = [], excerpt = "" }) {
  return new Promise((resolve) => {
    const dlg = el("dialog", { class: "sheet tag-sheet", "aria-label": "Étiqueter le message" });
    const input = el("input", { value: current.join(", "), placeholder: "important, à revoir…", "aria-label": "Étiquettes",
      enterkeyhint: "done", autocapitalize: "off", autocomplete: "off" });
    const suggest = el("div", { class: "tag-suggest" });
    let done = false;
    const finish = (value) => { if (done) return; done = true; if (dlg.open) dlg.close(); dlg.remove(); resolve(value); };
    const paint = () => {
      const have = new Set(parseTags(input.value).map((t) => t.toLocaleLowerCase("fr")));
      clear(suggest);
      for (const t of known.filter((k) => !have.has(k.toLocaleLowerCase("fr"))).slice(0, 12)) {
        suggest.append(el("button", { type: "button", class: "tag-chip", onclick: () => {
          input.value = [...parseTags(input.value), t].join(", ") + ", ";
          paint();
          input.focus();
        } }, `+ ${t}`));
      }
      suggest.hidden = !suggest.firstChild;
    };
    input.addEventListener("input", paint);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); finish(parseTags(input.value)); } });
    dlg.append(el("h2", {}, "Étiqueter le message"),
      excerpt ? el("p", { class: "subtle tag-excerpt" }, excerpt) : null,
      el("label", { class: "field" }, el("span", {}, "Étiquettes, séparées par des virgules"), input),
      suggest,
      el("div", { class: "sheet-actions" },
        current.length ? el("button", { type: "button", class: "danger", onclick: () => finish([]) }, "Tout retirer") : null,
        el("button", { type: "button", onclick: () => finish(null) }, "Annuler"),
        el("button", { type: "button", class: "primary", onclick: () => finish(parseTags(input.value)) }, "Valider")));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); finish(null); });
    paint();
    document.body.append(dlg);
    dlg.showModal();
    input.focus();
  });
}

// Volet « Étiquettes » : `messages()` rend { identifiant: entrée } ; `jump(identifiant)` ramène au message.
export class TagsPanel {
  constructor(holder, { messages, jump }) {
    this.messages = messages;
    this.jump = jump;
    this.filter = null;          // étiquette mise en avant (clic sur une pastille)
    this.body = el("div", { class: "tags-panel" });
    holder.append(this.body);
    this.refresh();
  }

  show(tag) { this.filter = tag || null; this.refresh(); }

  refresh() {
    clear(this.body);
    const groups = byTag(this.messages());
    if (!groups.length) {
      this.body.append(emptyState("Aucun message étiqueté dans cette conversation. Choisis « Étiqueter » sur un message."));
      return;
    }
    const want = this.filter?.toLocaleLowerCase("fr");
    for (const [tag, items] of groups) {
      const open = !want || tag.toLocaleLowerCase("fr") === want;
      const list = el("div", { class: "tag-items" });
      for (const [id, entry] of items) {
        list.append(el("button", { type: "button", class: "tag-item", onclick: () => this.jump(id) },
          el("span", { class: "subtle tag-who" }, entry.role === "utilisateur" ? "Moi" : "Claude"),
          el("span", { class: "tag-text" }, entry.excerpt || "(message sans texte)")));
      }
      const group = el("details", { class: "tag-group" }, el("summary", {}, el("strong", {}, tag), ` · ${items.length}`), list);
      group.open = open;
      this.body.append(group);
      if (want && open) setTimeout(() => group.scrollIntoView?.({ block: "nearest" }));
    }
  }
}
