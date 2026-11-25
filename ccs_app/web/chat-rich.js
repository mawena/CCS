// Chat riche (phase 49) : dans une réponse de Claude déjà rendue (Markdown du pont, nettoyé par
// dom.js), les images restent en taille limitée et s'ouvrent en grand d'un clic, les liens et
// chemins de sons et de vidéos gagnent un lecteur, et les blocs ```ccs (JSON) deviennent des
// composants : choix, formulaire, carte, cartes. Format : docs/chat-riche.md.
// Tout est construit par el(), jamais en HTML brut ; un bloc ccs invalide reste un bloc de code.
import { el } from "./dom.js";
import { fromBase64 } from "./files-manage.js";

export const AUDIO = ["mp3", "ogg", "wav", "m4a", "opus"];
export const VIDEO = ["mp4", "webm", "mov"];
const MAX_LOCAL = 60 * 1024 * 1024;          // fichier local lu par l'explorateur : 60 Mo au plus
const TYPES = new Set(["choix", "formulaire", "carte", "cartes"]);

// « audio », « video » ou null d'après l'extension (avant ?requête et #ancre).
export function mediaKind(src) {
  const m = /\.([a-z0-9]+)$/i.exec(String(src || "").split(/[?#]/)[0]);
  const ext = m ? m[1].toLowerCase() : "";
  return AUDIO.includes(ext) ? "audio" : VIDEO.includes(ext) ? "video" : null;
}

// Adresse https gardée telle quelle ; un chemin local (absolu, ou relatif au dossier de la
// session) devient { path } ; le reste (javascript:, data:, http nu, //hôte…) est refusé.
export function resolveSrc(src, cwd) {
  const s = String(src || "").trim();
  if (/^https:\/\//i.test(s)) return { url: s };
  if (!s || /^([a-z][\w+.-]*:|\/\/)/i.test(s)) return null;
  const parts = [];
  for (const p of (s.startsWith("/") ? s : `${cwd || ""}/${s}`).split("/")) {
    if (!p || p === ".") continue;
    if (p === "..") parts.pop(); else parts.push(p);
  }
  return parts.length ? { path: `/${parts.join("/")}` } : null;
}

// Bloc ```ccs : l'objet décrit s'il est valide (JSON, type connu), sinon null.
export function parseBlock(text) {
  let spec;
  try { spec = JSON.parse(text); } catch { return null; }
  if (!spec || typeof spec !== "object" || Array.isArray(spec) || !TYPES.has(spec.type)) return null;
  if (spec.type === "choix" && !(Array.isArray(spec.options) && spec.options.length)) return null;
  if (spec.type === "formulaire" && !(Array.isArray(spec.champs) && spec.champs.length)) return null;
  if (spec.type === "cartes" && !(Array.isArray(spec.items) && spec.items.length)) return null;
  if (spec.type === "carte" && !spec.titre) return null;
  return spec;
}

const str = (v) => (v === undefined || v === null ? "" : String(v));
// Option d'un choix ou action d'une carte : "texte", ou { label, message } / { label, lien }.
const optionOf = (o) => (typeof o === "object" && o
  ? { label: str(o.label || o.message), message: str(o.message || o.label), lien: str(o.lien) }
  : { label: str(o), message: str(o), lien: "" });

// Message lisible envoyé par un formulaire : le titre puis « - Libellé : valeur » par champ rempli.
export function formMessage(spec, values) {
  const lines = spec.titre ? [str(spec.titre)] : [];
  for (const f of spec.champs) {
    const v = str(values[f.nom ?? f.label]).trim();
    if (v) lines.push(`- ${str(f.label || f.nom)} : ${v}`);
  }
  return lines.join("\n");
}

// ---- médias -----------------------------------------------------------------------------------
// ctx : { api, cwd, send(texte), cache: Map(chemin → Promise<url blob>) }
async function localUrl(ctx, path) {
  ctx.cache ||= new Map();
  if (!ctx.cache.has(path)) {
    ctx.cache.set(path, (async () => {
      const parts = [];
      let got = 0;
      for (;;) {
        const r = await ctx.api.call("files.download", { path, offset: got });
        if (r.size > MAX_LOCAL) throw new Error("Fichier trop gros pour être affiché ici.");
        const bytes = fromBase64(r.data);
        parts.push(bytes);
        got += bytes.length;
        if (r.done || !bytes.length) return URL.createObjectURL(new Blob(parts));
      }
    })());
    ctx.cache.get(path).catch(() => ctx.cache.delete(path));   // un échec n'est pas gardé
  }
  return ctx.cache.get(path);
}

// Pose l'adresse de `node` (img, audio, video) : directe en https, sinon lue par l'explorateur ;
// un fichier refusé ou illisible laisse un petit mot à la place.
function load(node, where, ctx, fallback) {
  if (where.url) { node.setAttribute("src", where.url); return; }
  localUrl(ctx, where.path).then((url) => node.setAttribute("src", url),
    (e) => node.replaceWith(el("span", { class: "rich-missing", title: e.message || "" }, fallback || where.path)));
}

function lightbox(src, alt) {
  const dlg = el("dialog", { class: "lightbox", "aria-label": alt || "Image" },
    el("img", { src, alt: alt || "" }));
  dlg.addEventListener("click", () => dlg.close());
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  return dlg;
}

function image(src, alt, ctx) {
  const where = resolveSrc(src, ctx.cwd);
  if (!where) return el("span", { class: "rich-missing" }, alt || str(src));
  const img = el("img", { class: "rich-img", alt: alt || "", loading: "lazy", title: "Agrandir" });
  img.addEventListener("click", () => { const s = img.getAttribute("src"); if (s) lightbox(s, alt); });
  load(img, where, ctx, alt);
  return img;
}

export function player(src, ctx, label = "") {
  const kind = mediaKind(src);
  const where = resolveSrc(src, ctx.cwd);
  if (!kind || !where) return null;
  const node = el(kind, { class: `rich-${kind}`, controls: true, preload: "metadata", title: label || str(src) });
  load(node, where, ctx, label);
  return node;
}

// ---- composants des blocs ccs -----------------------------------------------------------------
function sendOnce(ctx, box, text) {
  if (!text) return;
  for (const b of box.querySelectorAll("button")) b.disabled = true;
  box.classList.add("sent");
  ctx.send(text);
}

function choiceBox(spec, ctx) {
  const box = el("div", { class: "rich rich-choices" });
  if (spec.titre || spec.question) box.append(el("p", { class: "rich-title" }, str(spec.titre || spec.question)));
  const row = el("div", { class: "rich-row" });
  for (const o of spec.options.map(optionOf)) {
    if (!o.label) continue;
    row.append(el("button", { type: "button", class: "small", onclick: () => sendOnce(ctx, box, o.message) }, o.label));
  }
  box.append(row);
  return box;
}

function formBox(spec, ctx) {
  const inputs = [];
  const fields = spec.champs.filter((f) => f && typeof f === "object").map((f) => {
    const key = f.nom ?? f.label;
    let input;
    if (f.type === "liste") {
      input = el("select", {}, ...(Array.isArray(f.options) ? f.options : []).map((o) => el("option", { value: str(o) }, str(o))));
    } else {
      input = el("input", { type: f.type === "nombre" ? "number" : "text", placeholder: str(f.aide || ""),
        value: f.valeur === undefined ? undefined : str(f.valeur) });
    }
    if (f.valeur !== undefined) input.value = str(f.valeur);
    inputs.push([key, input]);
    return el("label", { class: "rich-field" }, el("span", {}, str(f.label || f.nom)), input);
  });
  const form = el("form", { class: "rich rich-form" });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    sendOnce(ctx, form, formMessage(spec, Object.fromEntries(inputs.map(([k, i]) => [k, i.value]))));
  });
  if (spec.titre) form.append(el("p", { class: "rich-title" }, str(spec.titre)));
  form.append(...fields, el("button", { type: "submit", class: "primary small" }, str(spec.envoyer || "Envoyer")));
  return form;
}

function card(spec, ctx) {
  const link = /^https?:\/\//i.test(str(spec.lien)) ? str(spec.lien) : "";
  const title = el("strong", { class: "rich-card-title" }, str(spec.titre));
  const box = el("article", { class: "rich rich-card" });
  if (spec.image) box.append(image(spec.image, str(spec.titre), ctx));
  const body = el("div", { class: "rich-card-body" },
    link ? el("a", { href: link, target: "_blank", rel: "noopener noreferrer" }, title) : title);
  const sub = spec.prix ?? spec.sous_titre;
  if (sub !== undefined && sub !== null && sub !== "") body.append(el("div", { class: spec.prix !== undefined ? "rich-price" : "subtle" }, str(sub)));
  if (spec.prix !== undefined && spec.sous_titre) body.append(el("div", { class: "subtle" }, str(spec.sous_titre)));
  if (spec.description) body.append(el("p", {}, str(spec.description)));
  const actions = (Array.isArray(spec.actions) ? spec.actions : []).map(optionOf).filter((o) => o.label);
  if (actions.length) {
    body.append(el("div", { class: "rich-row" }, ...actions.map((o) => (/^https?:\/\//i.test(o.lien)
      ? el("a", { class: "button small", href: o.lien, target: "_blank", rel: "noopener noreferrer" }, o.label)
      : el("button", { type: "button", class: "small", onclick: () => sendOnce(ctx, body, o.message) }, o.label)))));
  }
  box.append(body);
  return box;
}

export function component(spec, ctx) {
  if (spec.type === "choix") return choiceBox(spec, ctx);
  if (spec.type === "formulaire") return formBox(spec, ctx);
  if (spec.type === "carte") return card(spec, ctx);
  return el("div", { class: "rich-cards" },
    ...spec.items.filter((c) => c && typeof c === "object" && c.titre).map((c) => card(c, ctx)));
}

// ---- passage sur une réponse rendue -----------------------------------------------------------
export function enrich(root, ctx) {
  for (const code of root.querySelectorAll("pre > code")) {
    if (!/(^|\s)language-ccs(\s|$)/.test(code.className)) continue;
    const spec = parseBlock(code.textContent);
    if (spec) (code.closest(".code-wrap") || code.parentNode).replaceWith(component(spec, ctx));
  }
  for (const img of root.querySelectorAll("img")) {
    if (img.classList.contains("rich-img") || img.closest(".rich, dialog")) continue;
    const src = img.getAttribute("src") || img.dataset.path || "";
    const alt = img.getAttribute("alt") || "";
    img.replaceWith(player(src, ctx, alt) || image(src, alt, ctx));
  }
  // liens et chemins de sons ou de vidéos : un lecteur juste après
  for (const a of root.querySelectorAll("a")) {
    if (a.closest(".rich") || a.nextSibling?.classList?.contains("rich-media")) continue;
    const src = a.classList.contains("file-link") ? a.dataset.path || a.textContent : a.getAttribute("href");
    const p = player(src, ctx, a.textContent);
    if (p) a.after(el("div", { class: "rich-media" }, p));
  }
  for (const code of root.querySelectorAll("code")) {
    if (code.closest("pre, a, .rich") || code.nextSibling?.classList?.contains("rich-media")) continue;
    const p = player(code.textContent.trim(), ctx);
    if (p) code.after(el("div", { class: "rich-media" }, p));
  }
  return root;
}
