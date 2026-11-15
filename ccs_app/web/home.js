// Accueil : comptes Claude côte à côte (jauges session et semaine, compte actif, bascule),
// ligne d'état, pause, file de tâches. Rafraîchi chaque minute.
import { ago, clear, el } from "./dom.js";
import { TerminalView } from "./terminal.js";

function resetText(iso) {
  if (!iso) return "";
  const s = (new Date(iso) - Date.now()) / 1000;
  if (s <= 0) return "recharge en cours";
  if (s < 3600) return `recharge dans ${Math.ceil(s / 60)} min`;
  if (s < 86400) return `recharge dans ${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
  return `recharge ${new Date(iso).toLocaleDateString("fr-FR", { weekday: "long", hour: "2-digit", minute: "2-digit" })}`;
}

function gauge(limit, color) {
  const pct = Math.max(0, Math.min(100, Math.round(limit.percent)));
  const level = pct >= 90 ? "danger" : pct >= 70 ? "warn" : "";
  const bar = el("div", { class: `gauge-fill ${level}` });
  bar.style.width = `${pct}%`;
  if (!level) bar.style.background = color;
  return el("div", { class: "gauge" },
    el("div", { class: "gauge-head" }, el("span", {}, limit.label), el("strong", {}, `${pct} %`)),
    el("div", { class: "gauge-track" }, bar),
    el("div", { class: "subtle" }, resetText(limit.resets_at)));
}

function accountCard(acc, color, api, reload) {
  const limits = (acc.limits || []).filter((l) => l.kind === "session" || l.kind === "weekly_all");
  const dot = el("span", { class: "dot" });
  dot.style.background = color;
  const card = el("article", { class: `card account${acc.active ? " active" : ""}` },
    el("header", { class: "account-head" }, dot,
      el("div", {}, el("h2", {}, acc.name), el("div", { class: "subtle" }, `${acc.plan || ""} · ${acc.email || ""}`)),
      acc.active ? el("span", { class: "badge" }, "Actif") : null),
    acc.error ? el("p", { class: "message" }, acc.error) : null,
    ...limits.map((l) => gauge(l, color)),
    el("div", { class: "subtle" }, acc.fetched_at ? `Mis à jour ${ago(acc.fetched_at)}` : ""));
  if (!acc.active) {
    card.append(el("button", { class: "small", onclick: async (e) => {
      e.target.disabled = true;
      try { await api.call("accounts.switch", { name: acc.name }); } catch (err) { alert(err.message); }
      reload();
    } }, "Basculer sur ce compte"));
  }
  card.style.setProperty("--account", color);
  return card;
}

export function mountHome(root, api) {
  const status = el("div", { class: "card flat status-line" });
  const accounts = el("section", { class: "accounts" });
  const pauseBox = el("div", { class: "card flat pause-box" });
  const tasksBox = el("section", { class: "card flat" });
  const addBox = el("section", { class: "card flat" });
  root.append(status, accounts, pauseBox, tasksBox, addBox);
  let home = null;
  let addTerm = null;
  const nameInput = el("input", { placeholder: "Nom du compte (ex. perso2)", pattern: "[A-Za-z0-9_-]{1,32}" });
  addBox.append(el("h2", {}, "Ajouter un compte Claude"),
    el("p", { class: "subtle" }, "Lance « ccs add » dans un terminal : ouvre le lien de connexion sur ton téléphone ou ton PC, puis colle le code dans le terminal."),
    el("div", { class: "row" }, nameInput, el("button", { class: "small", onclick: () => {
      if (!/^[A-Za-z0-9_-]{1,32}$/.test(nameInput.value)) { alert("Nom : lettres, chiffres, - et _ seulement."); return; }
      addTerm?.destroy(true);
      const holder = el("div", { class: "term-box" });
      addBox.append(holder);
      addTerm = new TerminalView(holder, api, { cwd: home, command: "ccs add", name: nameInput.value });
    } }, "Ouvrir le terminal")));

  async function loadTasks() {
    clear(tasksBox).append(el("h2", {}, "File de tâches"));
    let list = [];
    try { list = (await api.call("tasks.list")).tasks || []; } catch { /* hors ligne */ }
    const live = list.filter((t) => !["done", "failed", "cancelled"].includes(t.state));
    if (!live.length) { tasksBox.append(el("p", { class: "subtle" }, "Aucune tâche en attente.")); return; }
    for (const t of live) {
      tasksBox.append(el("div", { class: "row" },
        el("div", { class: "grow" }, el("strong", {}, t.message.slice(0, 120)),
          el("div", { class: "subtle" }, `${t.state} · ${t.when} · ${t.cwd}`)),
        el("button", { class: "small flat", onclick: async () => { await api.call("tasks.cancel", { id: t.id }); loadTasks(); } }, "Annuler")));
    }
  }

  async function load() {
    let st;
    try { st = await api.call("accounts.state"); } catch (e) {
      clear(status).append(el("span", { class: "subtle" }, `Indisponible : ${e.message}`));
      return;
    }
    home = st.home;
    const s = st.state || {};
    const best = s.best?.name ? `Meilleur compte : ${s.best.name} (${s.best.reason})` : "";
    const decision = s.auto_switch?.decision?.reason ? `Bascule automatique : ${s.auto_switch.decision.reason}` : "";
    clear(status).append(el("strong", {}, `Compte actif : ${st.active || "aucun"}`),
      el("span", { class: "subtle" }, [best, decision].filter(Boolean).join(" · ")),
      el("button", { class: "small flat", onclick: async () => { await api.call("accounts.refresh"); load(); } }, "Actualiser"));
    const accs = (s.accounts && s.accounts.length) ? s.accounts : (st.profiles || []);
    clear(accounts).append(...accs.map((a) => accountCard(a, st.colors?.[a.name] || "#3584e4", api, load)));
    const select = el("select", { "aria-label": "Mettre en pause" },
      ...(st.pause_choices || []).map(([value, label]) => el("option", { value }, label)));
    clear(pauseBox).append(el("strong", {}, st.pause ? `En pause ${st.pause.label}` : "Bascule et orchestrateur actifs"),
      st.pause
        ? el("button", { class: "small", onclick: async () => { await api.call("pause.set", { choice: "off" }); load(); } }, "Reprendre")
        : el("div", { class: "row" }, select,
          el("button", { class: "small", onclick: async () => { await api.call("pause.set", { choice: select.value }); load(); } }, "Mettre en pause")));
  }

  load();
  loadTasks();
  const timer = setInterval(load, 60000);
  const off = api.on("reconnected", () => { load(); loadTasks(); });
  return () => { clearInterval(timer); off(); addTerm?.destroy(false); };
}
