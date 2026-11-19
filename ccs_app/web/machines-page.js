// Page « Machines » : calcul réparti par Ricochet. Les machines du relais (en ligne ou non, charge,
// mémoire, outils), les commandes `ccs distant lancer` en cours sur ce serveur (avec arrêt) et les
// réglages du client Ricochet. `machines.*` n'est jamais relayé : tout vient du serveur.
import { ago, clear, confirmSheet, el, emptyState, errorState, loading, toast } from "./dom.js";
import { busy, field, shortPath } from "./pages-util.js";

const REFRESH_MS = 10000;

function gb(bytes) {
  return `${(bytes / 2 ** 30).toFixed(0)} Go`;
}

function since(ts) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")}`;
  return `${Math.floor(s / 3600)} h ${String(Math.floor(s / 60) % 60).padStart(2, "0")}`;
}

function loadBar(m) {
  const ratio = m.cores ? Math.min(1, (m.load || 0) / m.cores) : 0;
  const kind = ratio > 0.85 ? "bad" : ratio > 0.5 ? "warn" : "ok";
  return el("div", { class: `machine-load ${kind}`, role: "meter", "aria-valuemin": "0",
    "aria-valuemax": String(m.cores || 1), "aria-valuenow": String(m.load || 0),
    "aria-label": "Charge" }, el("span", { style: `width:${Math.round(ratio * 100)}%` }));
}

export function mountMachines(root, api) {
  const machinesBox = el("section", { class: "card flat section" });
  const runningBox = el("section", { class: "card flat section" });
  const settingsBox = el("section", { class: "card flat section settings-group" });
  root.append(el("div", { class: "settings-wrap" }, runningBox, machinesBox, settingsBox));
  let timer = null;
  let gone = false;
  const probing = new Set();

  // ---------------------------------------------------------------- commandes en cours
  async function loadRunning() {
    let list;
    try { list = (await api.call("machines.running")).running || []; } catch (e) {
      clear(runningBox).append(el("h2", {}, "Commandes en cours"), errorState(e.message, loadRunning));
      return;
    }
    clear(runningBox).append(el("h2", {}, "Commandes en cours"));
    if (!list.length) {
      runningBox.append(el("p", { class: "subtle" },
        "Aucune. Les chats lancent ici leurs builds et tests lourds avec « ccs distant lancer »."));
      return;
    }
    for (const r of list) {
      const where = shortPath(r.projet) + (r.dossier ? `/${r.dossier}` : "");
      runningBox.append(el("div", { class: "row machine-run" },
        el("div", { class: "grow" },
          el("code", {}, r.commande),
          el("div", { class: "subtle" }, `${r.machine} · ${where} · depuis ${since(r.debut)}`)),
        el("button", { class: "small danger", onclick: (e) => stopRun(e.currentTarget, r) }, "Arrêter")));
    }
  }

  async function stopRun(button, r) {
    if (!await confirmSheet({ title: "Arrêter cette commande ?", body: `${r.commande}\nsur ${r.machine}`,
      confirm: "Arrêter", danger: true })) return;
    await busy(button, async () => {
      try {
        await api.call("machines.stop", { pid: r.pid });
        toast("Commande arrêtée.", { kind: "success" });
      } catch (e) { toast(e.message, { kind: "error" }); }
      setTimeout(loadRunning, 1500);
    });
  }

  // ---------------------------------------------------------------- machines
  function card(m) {
    const facts = [];
    if (m.online) {
      facts.push(m.cores ? `charge ${Number(m.load || 0).toFixed(1)} sur ${m.cores} cœurs` : "charge inconnue");
      if (m.mem_total) facts.push(`mémoire ${gb(m.mem_used)} / ${gb(m.mem_total)}`);
    }
    let note = "";
    if (!m.online) note = "Hors ligne.";
    else if (m.local) note = "Ce serveur.";
    else if (!m.tunnel) note = "Tunnel SSH non activé : ajoute [tunnel] ports = [22] à son agent.toml.";
    const tools = el("div", { class: "machine-tools" });
    const showTools = (list, at) => {
      clear(tools);
      if (list && list.length) tools.append(...list.map((t) => el("span", { class: "chip" }, t)));
      else tools.append(el("span", { class: "subtle" }, at ? "Aucun outil de la liste." : "Outils pas encore relevés."));
      if (at) tools.append(el("span", { class: "subtle" }, ` relevés ${ago(at)}`));
    };
    showTools(m.tools, m.tools_at);
    const canProbe = m.online && m.tunnel && !m.local;
    const probe = canProbe ? el("button", { class: "small flat", disabled: probing.has(m.id),
      onclick: async (e) => {
        const b = e.currentTarget;
        probing.add(m.id);
        b.textContent = "Relevé…";
        await busy(b, async () => {
          try {
            const r = await api.call("machines.tools", { machine: m.id });
            showTools(r.tools, r.tools_at);
          } catch (err) { toast(err.message, { kind: "error" }); }
        });
        probing.delete(m.id);
        b.textContent = "Relever les outils";
      } }, probing.has(m.id) ? "Relevé…" : "Relever les outils") : null;
    return el("div", { class: `machine-card${m.online ? "" : " offline"}` },
      el("div", { class: "page-head" },
        el("span", { class: `dot ${m.online ? "ok" : "off"}`, "aria-hidden": "true" }),
        el("h3", { class: "grow" }, m.name && m.name !== m.id ? `${m.name} (${m.id})` : m.id), probe),
      m.online && m.cores ? loadBar(m) : null,
      facts.length ? el("div", { class: "subtle" }, facts.join(" · ")) : null,
      note ? el("div", { class: "subtle" }, note) : null,
      m.online && !m.local ? tools : null);
  }

  async function loadMachines(first = false) {
    if (first) clear(machinesBox).append(el("h2", {}, "Machines"), loading("Lecture du relais Ricochet…"));
    let r;
    try { r = await api.call("machines.list"); } catch (e) {
      clear(machinesBox).append(el("h2", {}, "Machines"), errorState(e.message, () => loadMachines(true)));
      return;
    }
    const list = r.machines || [];
    clear(machinesBox).append(el("div", { class: "page-head" }, el("h2", {}, "Machines"),
      el("button", { class: "small flat", onclick: (e) => busy(e.currentTarget, () => loadMachines()) }, "Actualiser")));
    if (r.message) machinesBox.append(el("p", { class: "subtle" }, r.message));
    else if (!list.length) machinesBox.append(emptyState("Aucune machine sur le relais Ricochet."));
    machinesBox.append(el("div", { class: "stack" }, ...list.map(card)));
  }

  // ---------------------------------------------------------------- réglages
  async function loadSettings() {
    let s;
    try { s = (await api.call("machines.settings")).settings; } catch (e) {
      clear(settingsBox).append(el("h2", {}, "Réglages du calcul réparti"), errorState(e.message, loadSettings));
      return;
    }
    const relais = el("input", { type: "url", value: s.relais || "", placeholder: "https://ricochet.mawena.cloud",
      autocomplete: "off", spellcheck: "false" });
    const jeton = el("input", { type: "password", value: "", autocomplete: "off",
      placeholder: s.jeton ? "•••••• (inchangé si vide)" : "jeton des tunnels" });
    const error = el("p", { class: "form-error", role: "alert" });
    const save = el("button", { class: "primary", type: "submit" }, "Enregistrer");
    const form = el("form", { class: "stack", onsubmit: async (e) => {
      e.preventDefault();
      error.textContent = "";
      await busy(save, async () => {
        try {
          await api.call("machines.configure", { relais: relais.value.trim(), jeton: jeton.value.trim() || null });
          toast("Enregistré.", { kind: "success" });
          loadSettings();
          loadMachines(true);
        } catch (err) { error.textContent = err.message; }
      });
    } },
    field("Adresse du relais", relais),
    field("Jeton", jeton, "Jeton du relais limité aux tunnels ; il n'est jamais réaffiché."),
    error, el("div", { class: "row" }, save));
    clear(settingsBox).append(el("h2", {}, "Réglages du calcul réparti"),
      s.agent ? null : el("p", { class: "form-error" },
        "ricochet-agent (0.3.0 ou plus) n'est pas installé sur ce serveur : le calcul réparti ne marchera pas."),
      el("p", { class: "subtle" }, "Enregistrés dans ~/.config/ricochet/client.toml (droits 600). "
        + "Utilisateur et port SSH par machine : ~/.config/ccs/distant.toml."),
      form);
  }

  function tick() {
    if (gone) return;
    if (document.visibilityState === "visible") { loadRunning(); loadMachines(); }
    timer = setTimeout(tick, REFRESH_MS);
  }

  loadRunning();
  loadMachines(true);
  loadSettings();
  timer = setTimeout(tick, REFRESH_MS);
  return () => { gone = true; clearTimeout(timer); };
}
