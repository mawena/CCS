// Construction du DOM sans jamais interpréter de texte comme du HTML.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "hidden") node.hidden = Boolean(value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.firstChild.remove();
  return node;
}

// HTML venu du pont (Markdown rendu côté serveur, HTML brut déjà échappé) : on garde seulement
// les balises et attributs de cette liste, au cas où.
const TAGS = new Set(["P", "BR", "STRONG", "EM", "DEL", "CODE", "PRE", "A", "UL", "OL", "LI",
  "H1", "H2", "H3", "H4", "H5", "H6", "BLOCKQUOTE", "HR", "TABLE", "THEAD", "TBODY", "TR", "TH",
  "TD", "IMG", "SPAN"]);
const ATTRS = { A: ["href", "title"], IMG: ["src", "alt", "title"], TH: ["align"], TD: ["align"],
  CODE: ["class"], OL: ["start"] };

function clean(node) {
  for (const child of [...node.childNodes]) {
    if (child.nodeType === Node.ELEMENT_NODE) {
      if (!TAGS.has(child.tagName)) { child.replaceWith(document.createTextNode(child.textContent)); continue; }
      const keep = ATTRS[child.tagName] || [];
      for (const a of [...child.attributes]) if (!keep.includes(a.name)) child.removeAttribute(a.name);
      const url = child.getAttribute("href") || child.getAttribute("src") || "";
      if (url && !/^(https?:|mailto:|#|\/)/i.test(url)) { child.removeAttribute("href"); child.removeAttribute("src"); }
      if (child.tagName === "A") { child.setAttribute("target", "_blank"); child.setAttribute("rel", "noopener noreferrer"); }
      clean(child);
    } else if (child.nodeType !== Node.TEXT_NODE) {
      child.remove();
    }
  }
  return node;
}

export function sanitized(html) {
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  const frag = document.createDocumentFragment();
  for (const n of [...clean(doc.body).childNodes]) frag.append(n);
  return frag;
}

export function setHtml(node, html) {
  clear(node).append(sanitized(html));
}

export function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "hier" : `il y a ${d} j`;
}
