// Onglet « Réseau » (#/reseau) : le réseau maillé de tous les appareils (WireGuard, Headscale sur
// network.mawena.cloud). Carte du réseau (cet appareil au centre, un trait par liaison, coloré
// selon le chemin : réseau local, direct par internet, relais du VPS), une fiche par appareil
// (adresses publiées, trafic, ping réel, renommer, retirer) et l'ajout d'un appareil (PC Linux
// par une clé jetable, téléphone par l'appli Tailscale). Méthodes `network.*`, toujours sur ce
// serveur. Rechargement toutes les 10 s tant que la page est visible.
import { clear, confirmSheet, el, errorState, loading, promptSheet, toast } from "./dom.js";
import { busy, copyText } from "./pages-util.js";

const REFRESH_MS = 10_000;
const NS = "http://www.w3.org/2000/svg";

export const PATHS = {
  self: { label: "Cet appareil", short: "ici", tone: "self" },
  lan: { label: "Réseau local", short: "LAN", tone: "lan" },
  direct: { label: "Direct par internet", short: "Direct", tone: "direct" },
  relay: { label: "Relais du VPS", short: "Relais", tone: "relay" },
  idle: { label: "En veille", short: "Veille", tone: "idle" },
  offline: { label: "Hors ligne", short: "Hors ligne", tone: "offline" },
};

// ---- icônes (SVG en traits, couleur du texte) ------------------------------------------------

const ICONS = {
  server: "M4 4h16v6H4zM4 14h16v6H4zM7 7h.01M7 17h.01M11 7h6M11 17h6",
  laptop: "M5 5h14v10H5zM2 19h20M9 19l1-2h4l1 2",
  desktop: "M3 4h18v12H3zM8 20h8M12 16v4",
  phone: "M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM11 18h2",
  apple: "M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM10 4.5h4M11 19h2",
  mesh: "M12 3a2 2 0 1 0 0 .01M5 19a2 2 0 1 0 0 .01M19 19a2 2 0 1 0 0 .01M12 5l-6 12M12 5l6 12M7 19h10",
  globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9c-2.5-2.6-3.7-5.6-3.7-9S9.5 5.6 12 3z",
  home: "M3 11l9-7 9 7M5 10v10h14V10M10 20v-6h4v6",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  relay: "M4 12h4M16 12h4M12 4v4M12 16v4M9 9h6v6H9z",
  pulse: "M3 12h4l2-5 4 10 2-5h6",
  plus: "M12 5v14M5 12h14",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  copy: "M8 8h12v12H8zM4 16V4h12",
  key: "M15 7a4 4 0 1 1-3.9 5H3v3h3v3h3v-3h2.1A4 4 0 0 1 15 7zM16.5 10.5h.01",
  arrows: "M7 7h11l-3-3M17 17H6l3 3",
  shield: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z",
  check: "M5 12l5 5 9-10",
};

export function icon(name, size = 20, cls = "") {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  if (cls) svg.setAttribute("class", cls);
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", ICONS[name] || ICONS.mesh);
  svg.append(path);
  return svg;
}

// Icône d'un appareil d'après son système et son nom.
export function deviceKind(d) {
  const os = String(d.os || "").toLowerCase();
  const name = String(d.name || "").toLowerCase();
  if (os === "ios" || name.includes("iphone") || name.includes("ipad")) return "apple";
  if (os === "android" || name.includes("pixel") || name.includes("phone")) return "phone";
  if (os === "macos") return "laptop";
  if (name.includes("vps") || name.includes("cloud") || name.includes("server") || name.includes("serveur")) return "server";
  if (name.includes("laptop") || name.includes("portable")) return "laptop";
  return "desktop";
}

// ---- formats -----------------------------------------------------------------------------------

export function bytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} o`;
  const units = ["Ko", "Mo", "Go", "To"];
  let x = v / 1024;
  let i = 0;
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i += 1; }
  return `${x.toLocaleString("fr-FR", { maximumFractionDigits: x < 10 ? 1 : 0 })} ${units[i]}`;
}

// « 192.168.1.20:41641 » → { ip, kind } : kind = lan | public | v6 | mesh.
export function addrKind(addr) {
  const s = String(addr || "");
  const host = s.startsWith("[") ? s.slice(1, s.indexOf("]")) : s.replace(/:\d+$/, "");
  if (host.includes(":")) {
    if (/^(fe80|fc|fd)/i.test(host)) return { ip: host, kind: "lan" };
    return { ip: host, kind: "v6" };
  }
  const p = host.split(".").map(Number);
  if (p.length !== 4 || p.some((x) => Number.isNaN(x))) return { ip: host, kind: "public" };
  if (p[0] === 100 && p[1] >= 64 && p[1] < 128) return { ip: host, kind: "mesh" };
  if (p[0] === 10 || (p[0] === 172 && p[1] >= 16 && p[1] < 32) || (p[0] === 192 && p[1] === 168) || (p[0] === 169 && p[1] === 254)) {
    return { ip: host, kind: "lan" };
  }
  return { ip: host, kind: "public" };
}

const ADDR_LABEL = { lan: "Local", public: "Public", v6: "IPv6", mesh: "Réseau" };

export function summary(st) {
  const peers = st.peers || [];
  const count = (p) => peers.filter((d) => d.path === p).length;
  return {
    total: peers.length + (st.self ? 1 : 0),
    online: peers.filter((d) => d.online).length + (st.self ? 1 : 0),
    lan: count("lan"), direct: count("direct"), relay: count("relay"),
  };
}

// ---- carte du réseau -------------------------------------------------------------------------

function svgEl(tag, attrs) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  return n;
}

export function topology(st) {
  const peers = st.peers || [];
  const W = 640;
  const H = 300;
  const cx = W / 2;
  const cy = H / 2;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "net-map", role: "img",
    "aria-label": "Carte du réseau : cet appareil au centre, une ligne par liaison" });
  const n = Math.max(peers.length, 1);
  const rx = Math.min(250, 120 + n * 18);
  const ry = 105;
  const pts = peers.map((d, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return { d, x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a) };
  });
  for (const p of pts) {
    const tone = (PATHS[p.d.path] || PATHS.idle).tone;
    svg.append(svgEl("line", { x1: cx, y1: cy, x2: p.x, y2: p.y, class: `net-link ${tone}` }));
  }
  const node = (x, y, d, main) => {
    const g = svgEl("g", { class: `net-node${main ? " main" : ""}${d.online || main ? "" : " off"}`, transform: `translate(${x} ${y})` });
    g.append(svgEl("circle", { r: main ? 30 : 22, class: "net-dot" }));
    const ic = icon(deviceKind(d), main ? 26 : 20);
    ic.setAttribute("x", String(main ? -13 : -10));
    ic.setAttribute("y", String(main ? -13 : -10));
    g.append(ic);
    const label = svgEl("text", { y: main ? 46 : 38, "text-anchor": "middle", class: "net-label" });
    label.textContent = d.name;
    g.append(label);
    return g;
  };
  for (const p of pts) svg.append(node(p.x, p.y, p.d, false));
  if (st.self) svg.append(node(cx, cy, st.self, true));
  return svg;
}

// ---- page --------------------------------------------------------------------------------------

function pill(path) {
  const p = PATHS[path] || PATHS.idle;
  const ico = { lan: "home", direct: "bolt", relay: "relay", self: "check", offline: "pulse", idle: "pulse" }[path] || "pulse";
  return el("span", { class: `net-pill ${p.tone}` }, icon(ico, 14), p.label);
}

function stat(ic, value, label, tone = "") {
  return el("div", { class: `net-stat ${tone}` },
    el("span", { class: "net-stat-ico" }, icon(ic, 18)),
    el("span", { class: "net-stat-value" }, String(value)),
    el("span", { class: "net-stat-label" }, label));
}

function iconButton(ic, label, onclick, cls = "") {
  return el("button", { type: "button", class: `small flat net-btn ${cls}`, title: label, onclick }, icon(ic, 16), el("span", {}, label));
}

export function mountReseau(root, api) {
  const wrap = el("div", { class: "settings-wrap net-page" });
  const hero = el("section", { class: "net-hero" }, loading());
  const mapBox = el("section", { class: "card flat section net-map-card", "aria-label": "Carte du réseau" });
  const listBox = el("div", { class: "net-grid" });
  const addBox = el("section", { class: "card flat section net-add", "aria-label": "Ajouter un appareil" });
  wrap.append(hero, mapBox,
    el("section", { class: "section net-devices", "aria-label": "Appareils" },
      el("h2", { class: "net-h2" }, icon("mesh", 20), "Appareils"), listBox),
    addBox);
  root.append(wrap);

  let st = null;
  let timer = null;
  let alive = true;
  const pings = new Map();         // nom → résultat du dernier ping

  async function refresh() {
    try {
      st = await api.call("network.status");
      render();
    } catch (e) {
      clear(hero).append(errorState(e.message || "Réseau injoignable.", refresh));
    }
  }

  function schedule() {
    clearTimeout(timer);
    if (!alive) return;
    timer = setTimeout(async () => { if (!document.hidden) await refresh(); schedule(); }, REFRESH_MS);
  }

  function render() {
    renderHero();
    clear(mapBox);
    if (st.self || (st.peers || []).length) {
      mapBox.append(topology(st), legend());
    } else {
      mapBox.hidden = true;
    }
    renderList();
    renderAdd();
  }

  function legend() {
    return el("div", { class: "net-legend" }, ...["lan", "direct", "relay", "offline"].map((p) =>
      el("span", { class: `net-legend-item ${PATHS[p].tone}` }, el("i", {}), PATHS[p].label)));
  }

  function renderHero() {
    clear(hero);
    const s = summary(st);
    const running = st.state === "Running";
    const state = !st.installed ? "Pas encore dans le réseau" : running ? "Connecté" : (st.state || "Arrêté");
    hero.append(
      el("div", { class: "net-hero-top" },
        el("div", { class: "net-hero-ico" }, icon("globe", 34)),
        el("div", { class: "grow" },
          el("h1", {}, "Réseau"),
          el("p", { class: "net-hero-url" }, st.url.replace(/^https:\/\//, ""), " · ", el("span", { class: "mono" }, `*.${st.domain}`))),
        el("span", { class: `net-state ${running ? "on" : "off"}` }, el("i", {}), state)),
      el("div", { class: "net-stats" },
        stat("mesh", `${s.online}/${s.total}`, "en ligne"),
        stat("home", s.lan, "en local", "lan"),
        stat("bolt", s.direct, "en direct", "direct"),
        stat("relay", s.relay, "par relais", "relay")));
    if (st.error) hero.append(el("p", { class: "net-error" }, st.error));
  }

  function addrs(d) {
    const list = (d.addrs || []).map(addrKind).filter((a) => a.kind !== "mesh");
    if (!list.length) return null;
    return el("div", { class: "net-addrs" }, ...list.map((a) =>
      el("span", { class: `net-addr ${a.kind}`, title: ADDR_LABEL[a.kind] }, el("b", {}, ADDR_LABEL[a.kind]), a.ip)));
  }

  function card(d, self) {
    const ip = (d.ips || [])[0] || "";
    const ping = pings.get(d.name);
    const pingLine = ping ? el("div", { class: `net-ping ${ping.ok ? (PATHS[ping.path] || PATHS.idle).tone : "offline"}` },
      icon("pulse", 14), ping.ok ? `${ping.ms.toLocaleString("fr-FR")} ms · ${PATHS[ping.path]?.label || ping.path} · ${ping.via}` : ping.error) : null;
    const actions = el("div", { class: "net-actions" });
    if (!self && d.online) {
      actions.append(iconButton("pulse", "Ping", (e) => busy(e.currentTarget, async () => {
        try { pings.set(d.name, await api.call("network.ping", { name: d.name })); }
        catch (err) { pings.set(d.name, { ok: false, error: err.message }); }
        renderList();
      })));
    }
    if (st.server) {
      actions.append(iconButton("edit", "Renommer", async () => {
        const name = await promptSheet({ title: `Renommer ${d.name}`, value: d.name, label: "Nouveau nom",
          check: (v) => {
            const t = v.trim();
            if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(t)) throw new Error("Lettres minuscules, chiffres et tirets.");
            return t;
          } });
        if (!name || name === d.name) return;
        try { await api.call("network.rename", { name: d.name, new: name }); toast("Renommé.", { kind: "success" }); refresh(); }
        catch (err) { toast(err.message, { kind: "error" }); }
      }));
      if (!self) {
        actions.append(iconButton("trash", "Retirer", async () => {
          const ok = await confirmSheet({ title: `Retirer ${d.name} du réseau ?`, danger: true, confirm: "Retirer",
            body: "L'appareil perd l'accès au réseau. Il faudra l'inscrire à nouveau." });
          if (!ok) return;
          try { await api.call("network.remove", { name: d.name }); toast("Retiré.", { kind: "success" }); refresh(); }
          catch (err) { toast(err.message, { kind: "error" }); }
        }, "danger"));
      }
    }
    const tone = (PATHS[d.path] || PATHS.idle).tone;
    return el("article", { class: `net-card ${tone}${d.online ? "" : " off"}` },
      el("div", { class: "net-card-head" },
        el("span", { class: `net-avatar ${tone}` }, icon(deviceKind(d), 24)),
        el("div", { class: "grow net-card-title" },
          el("h3", {}, d.name),
          el("div", { class: "net-sub" }, pill(d.path),
            el("span", {}, [d.os, d.host && d.host !== d.name ? d.host : ""].filter(Boolean).join(" · "))))),
      el("div", { class: "net-ip" },
        el("span", { class: "mono" }, ip || "—"),
        ip ? el("button", { type: "button", class: "icon flat", title: "Copier l'adresse", "aria-label": "Copier l'adresse", onclick: () => copyText(ip) }, icon("copy", 15)) : null,
        el("span", { class: "net-fqdn mono" }, `${d.name}.${st.domain}`)),
      d.endpoint && !self ? el("div", { class: "net-via" }, icon("arrows", 14), d.endpoint) : null,
      addrs(d),
      d.rx || d.tx ? el("div", { class: "net-traffic" }, `↓ ${bytes(d.rx)}`, el("span", {}, "·"), `↑ ${bytes(d.tx)}`) : null,
      pingLine,
      actions.childNodes.length ? actions : null);
  }

  function renderList() {
    clear(listBox);
    const all = [...(st.self ? [[st.self, true]] : []), ...(st.peers || []).map((d) => [d, false])];
    // Appareils connus du serveur mais absents de la liste locale (pas encore vus par ce client)
    const seen = new Set(all.map(([d]) => d.name));
    for (const n of st.nodes || []) {
      if (!seen.has(n.name)) all.push([{ name: n.name, host: n.host, ips: n.ips, online: n.online, path: n.online ? "idle" : "offline" }, false]);
    }
    if (!all.length) {
      listBox.append(el("p", { class: "subtle" }, "Aucun appareil pour l'instant : ajoute le premier ci-dessous."));
      return;
    }
    listBox.append(...all.map(([d, self]) => card(d, self)));
  }

  function renderAdd() {
    clear(addBox);
    addBox.append(el("h2", { class: "net-h2" }, icon("plus", 20), "Ajouter un appareil"));
    if (!st.server) {
      addBox.append(el("p", { class: "subtle" }, "Les appareils s'ajoutent depuis le serveur du réseau (le VPS)."));
      return;
    }
    const tabs = el("div", { class: "net-tabs", role: "tablist" });
    const body = el("div", { class: "net-tab-body" });
    const pages = {
      pc: { label: "PC Linux", ico: "desktop", render: renderPc },
      android: { label: "Android", ico: "phone", render: renderPhone("Android") },
      iphone: { label: "iPhone", ico: "apple", render: renderPhone("iPhone") },
    };
    const show = (key) => {
      for (const b of tabs.children) b.setAttribute("aria-selected", String(b.dataset.key === key));
      clear(body);
      pages[key].render(body);
    };
    for (const [key, p] of Object.entries(pages)) {
      tabs.append(el("button", { type: "button", role: "tab", class: "net-tab", dataset: { key }, onclick: () => show(key) }, icon(p.ico, 16), p.label));
    }
    addBox.append(tabs, body);
    show("pc");
  }

  function renderPc(body) {
    const name = el("input", { type: "text", placeholder: "nom (facultatif) : laptop-maison", maxlength: "63", autocapitalize: "off", spellcheck: "false" });
    const out = el("div", {});
    const go = el("button", { type: "button", class: "primary net-btn" }, icon("key", 16), el("span", {}, "Créer la ligne d'inscription"));
    go.addEventListener("click", () => busy(go, async () => {
      const n = name.value.trim();
      if (n && !/^[a-z0-9][a-z0-9-]{0,62}$/.test(n)) { toast("Nom : lettres minuscules, chiffres et tirets.", { kind: "error" }); return; }
      try {
        const r = await api.call("network.key", n ? { name: n } : {});
        const line = `sudo sh -c '${r.linux.join(" && ")}'`;
        clear(out).append(
          el("p", { class: "subtle" }, "Sur le PC, colle dans un terminal (clé valable 15 min, une seule machine) :"),
          el("div", { class: "net-code" }, el("code", {}, line),
            el("button", { type: "button", class: "icon flat", title: "Copier", "aria-label": "Copier", onclick: () => copyText(line) }, icon("copy", 16))));
      } catch (e) { toast(e.message, { kind: "error" }); }
    }));
    body.append(el("ol", { class: "net-steps" },
      el("li", {}, "Choisis un nom pour la machine, puis crée la ligne."),
      el("li", {}, "Colle-la sur le PC : elle installe le client et l'inscrit."),
      el("li", {}, "Il apparaît ici en quelques secondes, avec son chemin.")),
      el("div", { class: "net-row" }, name, go), out);
  }

  function renderPhone(kind) {
    return (body) => {
      const key = el("input", { type: "text", placeholder: "hskey-authreq-… ou le lien affiché", autocapitalize: "off", spellcheck: "false" });
      const go = el("button", { type: "button", class: "primary net-btn" }, icon("check", 16), el("span", {}, "Valider l'appareil"));
      go.addEventListener("click", () => busy(go, async () => {
        try {
          const r = await api.call("network.register", { key: key.value });
          toast(`${r.name} ajouté au réseau.`, { kind: "success" });
          key.value = "";
          refresh();
        } catch (e) { toast(e.message, { kind: "error" }); }
      }));
      body.append(el("ol", { class: "net-steps" },
        el("li", {}, `Installe l'appli Tailscale (${kind === "iPhone" ? "App Store" : "Play Store"}).`),
        el("li", {}, kind === "iPhone"
          ? "Réglages de l'appli → Comptes → « Utiliser un serveur personnalisé » :"
          : "Écran de connexion → menu ⋮ → « Changer de serveur » :",
          " ", el("button", { type: "button", class: "small flat net-btn", onclick: () => copyText(st.url) }, icon("copy", 14), el("span", { class: "mono" }, st.url))),
        el("li", {}, "Connecte-toi : une page affiche une clé « hskey-authreq-… ». Copie-la ici :")),
        el("div", { class: "net-row" }, key, go));
    };
  }

  refresh().then(schedule);
  const onVisible = () => { if (!document.hidden) refresh(); };
  document.addEventListener("visibilitychange", onVisible);
  return () => { alive = false; clearTimeout(timer); document.removeEventListener("visibilitychange", onVisible); };
}
