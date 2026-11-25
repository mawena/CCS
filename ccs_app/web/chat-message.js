// Messages du fil : bulle de l'utilisateur (avec ce qu'elle cite), réponse de Claude, et leur rangée
// d'actions (« Répondre »). Les boutons n'ont pas de texte dans la page (icône, libellé posé par la
// feuille de style) : la recherche dans le fil lit le texte des messages.
import { el } from "./dom.js";
import { CLAUDE, ME, QUOTE_MAX, SELECTION_MAX, SHOWN, excerpt, sourceText, split } from "./chat-quote.js";

const SVG = "http://www.w3.org/2000/svg";
export function icon(shapes) {                       // petite icône 14 px au trait, construite nœud par nœud
  const svg = document.createElementNS(SVG, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: 14, height: 14, fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(k, v);
  for (const [tag, attrs] of shapes) {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    svg.append(n);
  }
  return svg;
}
export const REPLY_ICON = [["path", { d: "m9 14-5-5 5-5" }], ["path", { d: "M4 9h10.5a5.5 5.5 0 0 1 0 11H11" }]];

// Citation montrée dans une bulle : l'auteur (posé par la feuille de style) et le passage, replié
// sur quelques lignes (un clic le déplie). `render(nœud, markdown)` : rend le passage d'une réponse
// de Claude (du Markdown) ; sans lui, ou en attendant, le texte tel quel. Un message de
// l'utilisateur cité reste tel quel, comme dans sa bulle (ses retours à la ligne comptent).
export function quoteBlock(q, render = null) {
  const text = el("div", { class: "quoted-text" }, q.text);
  if (q.author === CLAUDE) render?.(text, q.text);
  return el("blockquote", { class: "quoted", dataset: { author: SHOWN[q.author], key: q.author } }, text);
}

// Sélection de texte faite en entier dans `node` : { text, quoted } (`quoted` : l'auteur du passage
// cité si la sélection est dans la citation d'une bulle), ou null.
export function selectionIn(node) {
  const sel = window.getSelection?.();
  if (!node || !sel || sel.isCollapsed || !sel.rangeCount) return null;
  const where = sel.getRangeAt(0).commonAncestorContainer;
  const text = where && node.contains(where) ? sel.toString().trim() : "";
  if (!text) return null;
  const inside = where.nodeType === 1 ? where : where.parentElement;
  return { text, quoted: inside?.closest?.(".quoted")?.dataset.key || null };
}

// Rangée d'actions d'un message. `actions` : [{ key, label, icon, run(msg) }].
function actionsRow(msg, actions) {
  const row = el("div", { class: "msg-actions" });
  for (const a of actions) {
    row.append(el("button", { type: "button", class: "msg-act", "aria-label": a.label, title: a.label,
      dataset: { act: a.key, label: a.label }, onclick: () => a.run(msg) }, icon(a.icon)));
  }
  // Le passage sélectionné est relevé à l'appui : le clic sur le bouton peut défaire la sélection.
  row.addEventListener("pointerdown", () => { msg.selected = selectionIn(msg.content); });
  row.addEventListener("mousedown", (e) => e.preventDefault());
  return row;
}

// `msgId` : identifiant stable du message (étiquettes), le même en direct et à la relecture.
export function setMsgId(node, msgId) {
  node.msgId = msgId || "";
  if (msgId) node.dataset.msg = msgId; else delete node.dataset.msg;
}

function messageNode(kind, author, content, actions, msgId = "") {
  const node = el("div", { class: `msg ${kind}` }, content);
  node.author = author;          // CLAUDE | ME
  node.content = content;        // ce que le message montre (bulle, Markdown rendu)
  node.raw = "";                 // son texte d'origine
  node.selected = null;
  node.tagsNode = null;          // pastilles des étiquettes, entre le message et ses actions
  setMsgId(node, msgId);
  if (actions?.length) node.append(actionsRow(node, actions));
  return node;
}

// Images jointes à une bulle : `images` est la liste des images ({ media_type, data } en base64)
// ou leur nombre ; avec un nombre, `load()` les relit (journal) et leur place reste réservée.
// Un clic agrandit une image, un second la réduit.
export function imageStrip(images, load = null) {
  const n = Array.isArray(images) ? images.length : images;
  if (!n) return null;
  const strip = el("div", { class: "bubble-images" });
  const show = list => {
    strip.replaceChildren(...list.map(img => {
      const node = el("img", { class: "bubble-image", alt: "Image jointe", loading: "lazy",
        src: `data:${img.media_type};base64,${img.data}` });
      node.addEventListener("click", () => node.classList.toggle("big"));
      return node;
    }));
  };
  const fallback = () => strip.replaceChildren(el("div", { class: "subtle" }, `${n} image(s) jointe(s)`));
  if (Array.isArray(images)) show(images);
  else if (!load) fallback();
  else {
    strip.append(...Array.from({ length: n }, () => el("div", { class: "bubble-image pending" })));
    load().then(list => (list?.length ? show(list) : fallback()), fallback);
  }
  return strip;
}

// Bulle d'un message de l'utilisateur ; `text` peut commencer par une citation (chat-quote.js).
// `images`, `loadImages` : voir imageStrip.
export function userNode(text, images = 0, actions = [], renderQuote = null, msgId = "", loadImages = null) {
  const q = split(text);
  const bubble = el("div", { class: "bubble" }, q ? quoteBlock(q, renderQuote) : null, q ? q.body : text,
    imageStrip(images, loadImages));
  const node = messageNode("user", ME, bubble, actions, msgId);
  node.raw = text;
  return node;
}

// Réponse de Claude : le Markdown rendu va dans `node.content`, son texte d'origine dans `node.raw`.
export function claudeNode(actions = [], msgId = "") {
  return messageNode("claude", CLAUDE, el("div", { class: "md" }), actions, msgId);
}

// Ce qu'on cite d'un message : le passage sélectionné dedans, sinon son texte (début d'un long
// message). Pour une bulle qui citait déjà quelque chose : la réponse, pas sa citation.
export function quoteOf(msg) {
  const picked = msg.selected || selectionIn(msg.content);
  msg.selected = null;
  if (picked) return { author: picked.quoted || msg.author, text: excerpt(picked.text, SELECTION_MAX) };
  const text = excerpt(msg.author === ME ? sourceText(msg.raw) : msg.raw, QUOTE_MAX);
  return text ? { author: msg.author, text } : null;
}
