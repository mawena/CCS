// Faux DOM minimal pour exécuter les vues du web dans node : il n'y a pas de navigateur sur la
// machine qui construit les paquets. Il couvre ce dont les vues se servent (arbre, classes,
// attributs, événements qui remontent, sélecteurs simples, formulaires), pas la mise en page.
// `installDom()` pose `document`, `window`, `Node`, `localStorage`… dans l'espace global.

const VOID_VALUE = new Set(["INPUT", "TEXTAREA", "SELECT", "OPTION", "BUTTON"]);

class FakeEvent {
  constructor(type, init = {}) {
    Object.assign(this, init);
    this.type = type;
    this.bubbles = init.bubbles !== false;
    this.defaultPrevented = false;
    this.stopped = false;
    this.target = null;
    this.currentTarget = null;
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this.stopped = true; }
}

class Target {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(fn);
  }
  removeEventListener(type, fn) {
    const list = this.listeners.get(type) || [];
    const i = list.indexOf(fn);
    if (i >= 0) list.splice(i, 1);
  }
  fire(ev) {
    ev.currentTarget = this;
    for (const fn of [...(this.listeners.get(ev.type) || [])]) fn.call(this, ev);
  }
  dispatchEvent(ev) {
    ev.target = this;
    for (let n = this; n && !ev.stopped; n = ev.bubbles ? n.parentNode || n.ownerTarget : null) n.fire(ev);
    return !ev.defaultPrevented;
  }
}

export class Node extends Target {
  static ELEMENT_NODE = 1;
  static TEXT_NODE = 3;
  constructor() {
    super();
    this.parentNode = null;
    this.childNodes = [];
  }
  get parentElement() { return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstElementChild() { return this.children[0] || null; }
  get lastElementChild() { const c = this.children; return c[c.length - 1] || null; }
  get isConnected() { for (let n = this; n; n = n.parentNode) if (n === globalThis.document.documentElement) return true; return false; }
  sibling(delta, elementsOnly) {
    if (!this.parentNode) return null;
    const list = elementsOnly ? this.parentNode.children : this.parentNode.childNodes;
    return list[list.indexOf(this) + delta] || null;
  }
  get nextSibling() { return this.sibling(1, false); }
  get previousSibling() { return this.sibling(-1, false); }
  get nextElementSibling() { return this.sibling(1, true); }
  get previousElementSibling() { return this.sibling(-1, true); }
  contains(other) { for (let n = other; n; n = n.parentNode) if (n === this) return true; return false; }
  remove() {
    if (!this.parentNode) return;
    const list = this.parentNode.childNodes;
    list.splice(list.indexOf(this), 1);
    this.parentNode = null;
  }
  static items(nodes) {
    const out = [];
    for (const n of nodes) {
      if (n instanceof Fragment) out.push(...n.childNodes.splice(0));
      else out.push(n instanceof Node ? n : new Text(String(n)));
    }
    return out;
  }
  insertAt(index, nodes) {
    let at = index;
    for (const n of Node.items(nodes)) {
      if (n.parentNode === this && this.childNodes.indexOf(n) < at) at -= 1;
      n.remove();
      n.parentNode = this;
      this.childNodes.splice(at, 0, n);
      at += 1;
    }
  }
  append(...nodes) { this.insertAt(this.childNodes.length, nodes); }
  prepend(...nodes) { this.insertAt(0, nodes); }
  appendChild(n) { this.append(n); return n; }
  removeChild(n) { n.remove(); return n; }
  insertBefore(n, ref) { this.insertAt(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, [n]); return n; }
  before(...nodes) { this.parentNode.insertAt(this.parentNode.childNodes.indexOf(this), nodes); }
  after(...nodes) { this.parentNode.insertAt(this.parentNode.childNodes.indexOf(this) + 1, nodes); }
  replaceWith(...nodes) {
    const parent = this.parentNode;
    const at = parent.childNodes.indexOf(this);
    this.remove();
    parent.insertAt(at, nodes);
  }
  replaceChildren(...nodes) { for (const n of [...this.childNodes]) n.remove(); this.append(...nodes); }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(value) { this.replaceChildren(...(value === "" || value == null ? [] : [String(value)])); }
}

export class Text extends Node {
  constructor(data) { super(); this.nodeType = 3; this.data = data; }
  get textContent() { return this.data; }
  set textContent(value) { this.data = String(value); }
  get nodeValue() { return this.data; }
}

class Fragment extends Node {
  constructor() { super(); this.nodeType = 11; }
  querySelectorAll(sel) { return Element.prototype.querySelectorAll.call(this, sel); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

class ClassList {
  constructor(node) { this.node = node; }
  get list() { return (this.node.attrs.get("class") || "").split(/\s+/).filter(Boolean); }
  set list(v) { this.node.attrs.set("class", v.join(" ")); }
  contains(c) { return this.list.includes(c); }
  add(...cs) { this.list = [...new Set([...this.list, ...cs])]; }
  remove(...cs) { this.list = this.list.filter((c) => !cs.includes(c)); }
  toggle(c, force) {
    const on = force === undefined ? !this.contains(c) : Boolean(force);
    if (on) this.add(c); else this.remove(c);
    return on;
  }
  get length() { return this.list.length; }
  [Symbol.iterator]() { return this.list[Symbol.iterator](); }
}

// Sélecteurs : étiquette, .classe, #id, [attr], [attr="v"], :not(simple), composés, « a b », « a > b », listes.
function parseCompound(text) {
  const parts = { tag: null, classes: [], id: null, attrs: [], not: [] };
  const re = /:not\(([^)]+)\)|\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]|([.#]?)([\w-]+|\*)/g;
  let m;
  while ((m = re.exec(text))) {
    if (m[1] !== undefined) parts.not.push(parseCompound(m[1]));
    else if (m[2] !== undefined) parts.attrs.push([m[2], m[3]]);
    else if (m[4] === ".") parts.classes.push(m[5]);
    else if (m[4] === "#") parts.id = m[5];
    else if (m[5] !== "*") parts.tag = m[5].toUpperCase();
  }
  return parts;
}

function matchCompound(node, p) {
  if (node.nodeType !== 1) return false;
  if (p.tag && node.tagName !== p.tag) return false;
  if (p.id && node.id !== p.id) return false;
  if (!p.classes.every((c) => node.classList.contains(c))) return false;
  for (const [name, value] of p.attrs) {
    const has = name === "hidden" ? node.hidden : node.hasAttribute(name);
    if (!has || (value !== undefined && node.getAttribute(name) !== value)) return false;
  }
  return !p.not.some((n) => matchCompound(node, n));
}

function parseSelector(sel) {
  return sel.split(",").map((one) => {
    const steps = [];
    for (const token of one.trim().replace(/\s*>\s*/g, " > ").split(/\s+/)) {
      if (token === ">") steps[steps.length - 1].child = true;
      else steps.push({ compound: parseCompound(token), child: false });
    }
    return steps;
  });
}

function matchSteps(node, steps, i = steps.length - 1) {
  if (!matchCompound(node, steps[i].compound)) return false;
  if (i === 0) return true;
  if (steps[i - 1].child) return Boolean(node.parentElement) && matchSteps(node.parentElement, steps, i - 1);
  for (let p = node.parentElement; p; p = p.parentElement) if (matchSteps(p, steps, i - 1)) return true;
  return false;
}

export class Element extends Node {
  constructor(tag) {
    super();
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.attrs = new Map();
    this.classList = new ClassList(this);
    this.style = { setProperty(k, v) { this[k] = v; }, removeProperty(k) { delete this[k]; } };
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.clientHeight = 0;
    this.offsetWidth = 0;
    if (VOID_VALUE.has(this.tagName)) this.ownValue = null;
    if (this.tagName === "TEXTAREA" || this.tagName === "INPUT") { this.selectionStart = null; this.selectionEnd = null; }
  }
  get localName() { return this.tagName.toLowerCase(); }
  get className() { return this.attrs.get("class") || ""; }
  set className(v) { this.attrs.set("class", String(v)); }
  get id() { return this.attrs.get("id") || ""; }
  set id(v) { this.attrs.set("id", String(v)); }
  get attributes() { return [...this.attrs].map(([name, value]) => ({ name, value })); }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  hasAttribute(name) { return this.attrs.has(name); }
  removeAttribute(name) { this.attrs.delete(name); }
  toggleAttribute(name, force) {
    const on = force === undefined ? !this.attrs.has(name) : Boolean(force);
    if (on) this.attrs.set(name, ""); else this.attrs.delete(name);
    return on;
  }
  get title() { return this.getAttribute("title") || ""; }
  set title(v) { this.setAttribute("title", v); }
  get type() { return this.getAttribute("type") || (this.tagName === "BUTTON" ? "submit" : "text"); }
  set type(v) { this.setAttribute("type", v); }
  get options() { return this.querySelectorAll("option"); }
  get selectedOptions() { return this.options.filter((o) => o.value === this.value).slice(0, 1); }
  get value() {
    if (this.tagName === "OPTION") return this.attrs.has("value") ? this.attrs.get("value") : this.textContent;
    if (this.tagName === "SELECT") {
      const opts = this.options;
      if (this.ownValue !== null && opts.some((o) => o.value === this.ownValue)) return this.ownValue;
      return opts.length ? opts[0].value : "";
    }
    return this.ownValue ?? this.getAttribute("value") ?? "";
  }
  set value(v) { this.ownValue = String(v); }
  matches(sel) { return parseSelector(sel).some((steps) => matchSteps(this, steps)); }
  closest(sel) { for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n.matches(sel)) return n; return null; }
  querySelectorAll(sel) {
    const lists = parseSelector(sel);
    const out = [];
    const walk = (node) => {
      for (const c of node.childNodes) {
        if (c.nodeType !== 1) continue;
        if (lists.some((steps) => matchSteps(c, steps))) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getElementsByTagName(tag) { return this.querySelectorAll(tag); }
  focus() { globalThis.document.activeElement = this; this.dispatchEvent(new FakeEvent("focus", { bubbles: false })); }
  blur() { if (globalThis.document.activeElement === this) globalThis.document.activeElement = null; }
  select() {}
  setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; }
  click() {
    if (this.disabled) return;
    const ev = new FakeEvent("click");
    this.dispatchEvent(ev);
    // un bouton d'envoi soumet son formulaire, comme dans un navigateur
    if (!ev.defaultPrevented && this.tagName === "BUTTON" && this.type === "submit") {
      const form = this.closest("form");
      if (form) form.dispatchEvent(new FakeEvent("submit"));
    }
  }
  scrollIntoView() { this.scrolledIntoView = (this.scrolledIntoView || 0) + 1; }
  getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  showModal() { this.open = true; }
  show() { this.open = true; }
  close() { this.open = false; this.dispatchEvent(new FakeEvent("close", { bubbles: false })); }
  animate() { return { finished: Promise.resolve(), cancel() {} }; }
  setPointerCapture() {}
  releasePointerCapture() {}
}

class Storage {
  constructor() { this.map = new Map(); }
  getItem(k) { return this.map.has(k) ? this.map.get(k) : null; }
  setItem(k, v) { this.map.set(k, String(v)); }
  removeItem(k) { this.map.delete(k); }
  clear() { this.map.clear(); }
}

// HTML rendu par le pont : le faux DOM ne l'analyse pas, il le pose en texte dans un paragraphe.
class FakeParser {
  parseFromString(html) {
    const body = new Element("body");
    const text = String(html).replace(/^<body>|<\/body>$/g, "").replace(/<[^>]+>/g, "");
    if (text) { const p = new Element("p"); p.append(text); body.append(p); }
    return { body };
  }
}

export function installDom() {
  const html = new Element("html");
  const body = new Element("body");
  html.append(body);
  const selection = { text: "", node: null };          // sélection simulée : setSelection(texte, nœud)
  const document = Object.assign(new Target(), {
    documentElement: html,
    body,
    activeElement: null,
    visibilityState: "visible",
    createElement: (tag) => new Element(tag),
    createElementNS: (_ns, tag) => new Element(tag),
    createTextNode: (data) => new Text(String(data)),
    createDocumentFragment: () => new Fragment(),
    querySelector: (sel) => html.querySelector(sel),
    querySelectorAll: (sel) => html.querySelectorAll(sel),
    getElementById: (id) => html.querySelector(`#${id}`),
  });
  html.ownerTarget = document;                          // les événements remontent jusqu'au document
  const clipboard = { text: "", writeText(t) { this.text = String(t); return Promise.resolve(); } };
  const win = {
    document,
    Node,
    Element,
    Event: FakeEvent,
    DOMParser: FakeParser,
    localStorage: new Storage(),
    sessionStorage: new Storage(),
    matchMedia: (query) => ({ matches: win.media.has(query), media: query, addEventListener() {}, removeEventListener() {} }),
    media: new Set(),                                   // requêtes média qui « correspondent »
    getSelection: () => ({
      isCollapsed: !selection.text,
      rangeCount: selection.text ? 1 : 0,
      toString: () => selection.text,
      getRangeAt: () => ({ commonAncestorContainer: selection.node }),
      removeAllRanges() { selection.text = ""; selection.node = null; },
    }),
    setSelection(text, node) { selection.text = text; selection.node = node; },
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    innerWidth: 1280,
    innerHeight: 800,
    clipboard,
  };
  win.window = win;
  for (const [key, value] of Object.entries(win)) globalThis[key] = value;
  Object.defineProperty(globalThis, "navigator", { value: { clipboard, userAgent: "node" }, configurable: true });
  return win;
}

// Laisse passer les promesses et les minuteries en attente (rendus différés, appels au pont).
export async function settle(ms = 0) {
  for (let i = 0; i < 5; i += 1) await new Promise((r) => setTimeout(r, ms));
}
