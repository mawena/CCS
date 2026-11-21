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
      if (url && !/^(https?:|mailto:|#|\/(?!\/))/i.test(url)) { child.removeAttribute("href"); child.removeAttribute("src"); }
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

// ---- retours à l'utilisateur : toasts, confirmation, chargement, états vides ----------------
// (à la place d'alert() et de confirm(), illisibles au téléphone)

function toastHost() {
  let host = document.getElementById("toasts");
  if (!host) {
    host = el("div", { id: "toasts", class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(host);
  }
  return host;
}

// Message bref en bas de l'écran, effacé seul (4 s, 8 s pour une erreur). `action` :
// { label, run } ajoute un bouton (« Réessayer », « Annuler »…). Renvoie la fonction qui le ferme.
export function toast(text, { kind = "info", action = null, timeout = null } = {}) {
  const node = el("div", { class: `toast ${kind}` }, el("span", { class: "grow" }, text));
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    clearTimeout(timer);
    node.classList.add("leaving");
    setTimeout(() => node.remove(), 200);
  };
  if (action) node.append(el("button", { class: "small flat", onclick: () => { close(); action.run(); } }, action.label));
  node.append(el("button", { class: "small flat toast-close", "aria-label": "Fermer", onclick: close }, "×"));
  toastHost().append(node);
  const timer = setTimeout(close, timeout ?? (kind === "error" ? 8000 : 4000));
  return close;
}

// Carte de confirmation : promesse vraie si l'on confirme, fausse sinon (Échap, Annuler).
export function confirmSheet({ title, body = "", confirm = "Confirmer", cancel = "Annuler", danger = false }) {
  return new Promise((resolve) => {
    const dlg = el("dialog", { class: "sheet", "aria-label": title });
    const done = (ok) => { if (dlg.open) dlg.close(); dlg.remove(); resolve(ok); };
    dlg.append(el("h2", {}, title), body ? el("p", { class: "subtle" }, body) : null,
      el("div", { class: "sheet-actions" },
        el("button", { type: "button", onclick: () => done(false) }, cancel),
        el("button", { type: "button", class: danger ? "danger" : "primary", onclick: () => done(true) }, confirm)));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(false); });
    document.body.append(dlg);
    dlg.showModal();
  });
}

// Feuille à plusieurs choix : `choices` = [{ value, label, primary }] ; renvoie la valeur choisie,
// ou null (Annuler, Échap).
export function choiceSheet({ title, body = "", choices = [], cancel = "Annuler" }) {
  return new Promise((resolve) => {
    const dlg = el("dialog", { class: "sheet", "aria-label": title });
    const done = (v) => { if (dlg.open) dlg.close(); dlg.remove(); resolve(v); };
    dlg.append(el("h2", {}, title), body ? el("p", { class: "subtle" }, body) : null,
      el("div", { class: "sheet-actions" },
        el("button", { type: "button", onclick: () => done(null) }, cancel),
        ...choices.map((c) => el("button", { type: "button", class: c.primary ? "primary" : "", onclick: () => done(c.value) }, c.label))));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(null); });
    document.body.append(dlg);
    dlg.showModal();
  });
}

export function loading(text = "Chargement…") {
  return el("div", { class: "state loading", role: "status" }, el("span", { class: "spinner", "aria-hidden": "true" }), text);
}

// État vide avec, si possible, l'action qui en sort (« Nouveau chat », « Essayer 30 jours »…).
export function emptyState(text, ...actions) {
  return el("div", { class: "state empty" }, el("p", {}, text),
    actions.length ? el("div", { class: "state-actions" }, ...actions) : null);
}

export function errorState(message, retry = null) {
  return el("div", { class: "state error", role: "alert" }, el("p", {}, message),
    retry ? el("button", { class: "small", onclick: retry }, "Réessayer") : null);
}

// Section redimensionnable à la souris par son bord droit ; la largeur est gardée (localStorage).
export function resizable(node, key, { min = 200, max = 900 } = {}) {
  const store = `ccs-width:${key}`;
  const saved = Number(localStorage.getItem(store));
  if (saved) node.style.width = `${Math.min(Math.max(saved, min), max)}px`;
  node.classList.add("resizable");
  const handle = document.createElement("div");
  handle.className = "resize-handle";
  handle.setAttribute("role", "separator");
  handle.setAttribute("aria-orientation", "vertical");
  handle.title = "Glisser pour redimensionner (double-clic : taille par défaut)";
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    const left = node.getBoundingClientRect().left;
    const move = (ev) => { node.style.width = `${Math.min(Math.max(ev.clientX - left, min), max)}px`; };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      document.body.classList.remove("resizing");
      localStorage.setItem(store, String(Math.round(node.getBoundingClientRect().width)));
    };
    document.body.classList.add("resizing");
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
  handle.addEventListener("dblclick", () => { node.style.width = ""; localStorage.removeItem(store); });
  node.append(handle);
  return handle;
}

// Menu du clic droit, posé sous le pointeur. items : [{ label, run, danger?, disabled? }] ou null
// (séparateur). Se ferme au clic ailleurs, à Échap, au défilement ou au changement de taille.
let openMenu = null;
export function contextMenu(event, items) {
  event.preventDefault();
  event.stopPropagation();
  openMenu?.();
  const node = el("div", { class: "ctx-menu", role: "menu" });
  const close = () => {
    node.remove();
    document.removeEventListener("pointerdown", outside, true);
    document.removeEventListener("keydown", onKey, true);
    window.removeEventListener("blur", close);
    window.removeEventListener("resize", close);
    window.removeEventListener("scroll", close, true);
    if (openMenu === close) openMenu = null;
  };
  const outside = (e) => { if (!node.contains(e.target)) close(); };
  const onKey = (e) => {
    const buttons = [...node.querySelectorAll("button:not([disabled])")];
    const at = buttons.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      buttons[(at + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
    }
  };
  for (const it of items) {
    if (!it) { if (node.lastChild && !node.lastChild.classList.contains("sep")) node.append(el("hr", { class: "sep" })); continue; }
    node.append(el("button", { type: "button", role: "menuitem", class: `menu-item${it.danger ? " danger-text" : ""}`, disabled: it.disabled,
      onclick: () => { close(); it.run(); } }, it.label));
  }
  if (node.lastChild?.classList.contains("sep")) node.lastChild.remove();
  document.body.append(node);
  const { innerWidth: w, innerHeight: h } = window;
  const r = node.getBoundingClientRect();
  node.style.left = `${Math.max(4, Math.min(event.clientX, w - r.width - 4))}px`;
  node.style.top = `${Math.max(4, Math.min(event.clientY, h - r.height - 4))}px`;
  node.querySelector("button:not([disabled])")?.focus({ preventScroll: true });
  setTimeout(() => {
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("scroll", close, true);
  });
  document.addEventListener("keydown", onKey, true);
  window.addEventListener("blur", close);
  window.addEventListener("resize", close);
  openMenu = close;
  return close;
}

// Demande un texte dans une feuille (renommer…). Promesse : le texte, ou null si l'on annule.
// check(texte) peut lever : son message s'affiche et la feuille reste ouverte.
export function promptSheet({ title, value = "", label = "Nom", confirm = "Valider", maxlength = 200, check = null }) {
  return new Promise((resolve) => {
    const input = el("input", { type: "text", value, "aria-label": label, maxlength: String(maxlength), enterkeyhint: "done" });
    const msg = el("p", { class: "message", role: "alert" });
    const form = el("form", { class: "rename" }, input, msg);
    const dlg = el("dialog", { class: "sheet", "aria-label": title });
    const done = (v) => { if (dlg.open) dlg.close(); dlg.remove(); resolve(v); };
    dlg.append(el("h2", {}, title), form, el("div", { class: "sheet-actions" },
      el("button", { type: "button", onclick: () => done(null) }, "Annuler"),
      el("button", { type: "button", class: "primary", onclick: () => form.requestSubmit() }, confirm)));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(null); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      msg.textContent = "";
      try { done(check ? await check(input.value) : input.value); } catch (err) { msg.textContent = err.message; }
    });
    document.body.append(dlg);
    dlg.showModal();
    input.focus();
    input.select();
  });
}
