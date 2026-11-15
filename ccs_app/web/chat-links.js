// Chemins cités dans une réponse de Claude (`chemin` ou `chemin:ligne`) : ceux qui sont des
// fichiers du projet deviennent des liens qui ouvrent le volet Fichiers.
import { el } from "./dom.js";

const REF = /^(\/?[\w@+.-]+(?:\/[\w@+.-]+)*)(?::(\d+)(?::\d+)?)?$/;
const IN_TEXT = /(^|[^\w/.@+-])(\.?\/?[\w@+.-]+(?:\/[\w@+.-]+)*\.[A-Za-z0-9]+)(?::(\d+)(?::\d+)?)?/g;

// Chemin relatif au projet + ligne si `text` désigne un fichier de `files` (Set de chemins relatifs).
export function parsePathRef(text, cwd, files) {
  const m = REF.exec(String(text).trim());
  if (!m) return null;
  let path = m[1];
  if (path.startsWith("/")) {
    if (!path.startsWith(`${cwd}/`)) return null;
    path = path.slice(cwd.length + 1);
  } else if (path.startsWith("./")) path = path.slice(2);
  if (path.split("/").includes("..") || !files.has(path)) return null;
  return { path, line: m[2] ? Number(m[2]) : null };
}

// Références trouvées dans un texte libre : [{ path, line, text, index }].
export function findRefs(text, cwd, files) {
  const out = [];
  for (const m of String(text).matchAll(IN_TEXT)) {
    const text0 = m[0].slice(m[1].length);        // m[1] : le caractère qui précède (pas de lookbehind : Safari < 16.4)
    const ref = parsePathRef(text0, cwd, files);
    if (ref) out.push({ ...ref, text: text0, index: m.index + m[1].length });
  }
  return out;
}

function link(ref, label, onOpen) {
  return el("a", { href: "#", class: "file-link", title: `Ouvrir ${ref.path}`, onclick: (e) => {
    e.preventDefault();
    onOpen(ref.path, { line: ref.line });
  } }, label);
}

// Remplace, dans le Markdown rendu `root`, les chemins connus par des liens (code en ligne ou texte
// courant ; jamais dans un bloc de code ni dans un lien existant).
export function linkify(root, cwd, files, onOpen) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) texts.push(n);
  for (const node of texts) {
    const parent = node.parentElement;
    if (!parent || parent.closest("a, pre")) continue;
    if (parent.tagName === "CODE") {
      const ref = parsePathRef(node.textContent, cwd, files);
      if (ref) parent.replaceWith(link(ref, el("code", {}, node.textContent), onOpen));
      continue;
    }
    const refs = findRefs(node.textContent, cwd, files);
    if (!refs.length) continue;
    const frag = document.createDocumentFragment();
    let at = 0;
    for (const r of refs) {
      frag.append(node.textContent.slice(at, r.index), link(r, r.text, onOpen));
      at = r.index + r.text.length;
    }
    frag.append(node.textContent.slice(at));
    node.replaceWith(frag);
  }
}
