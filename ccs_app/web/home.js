// Accueil : comptes Claude (jauges, rythme, prévision, statut lisible, détails repliables),
// bascule avec confirmation, actualisation, pause, bilan de santé, tâches de nuit, ajout d'un
// compte. Rafraîchi chaque minute.
import { ago, clear, confirmSheet, el, errorState, toast } from "./dom.js";
import { healthCard } from "./pages-health.js";
import { tasksSection } from "./pages-tasks.js";
import { busy } from "./pages-util.js";
import { TerminalView } from "./terminal.js";

function gauge(g, color) {
  const pct = Math.max(0, Math.min(100, Math.round(g.percent)));
  const level = pct >= 90 ? "danger" : pct >= 70 ? "warn" : "";
  const bar = el("div", { class: `gauge-fill ${level}` });
  bar.style.width = `${pct}%`;
  if (!level) bar.style.background = color;
  return el("div", { class: "gauge" },
    el("div", { class: "gauge-head" }, el("span", {}, g.label), el("strong", {}, `${pct} %`)),
    el("div", { class: "gauge-track", role: "progressbar", "aria-label": g.label, "aria-valuemin": "0",
      "aria-valuemax": "100", "aria-valuenow": String(pct), "aria-valuetext": `${pct} %` }, bar),
    g.reset ? el("div", { class: "subtle" }, g.reset) : null);
}

function skeleton() {
  return el("div", { class: "accounts", "aria-busy": "true", "aria-label": "Chargement des comptes" },
    el("div", { class: "skeleton" }), el("div", { class: "skeleton" }));
}

export function mountHome(root, api) {
  const status = el("div", { class: "card flat status-line" });
  const accounts = el("section", { class: "accounts" });
  const pauseBox = el("div", { class: "card flat pause-box" });
  const addBox = el("section", { class: "card flat section" });
  const ctx = { home: "" };
  const opened = new Set();             // « Détails » ouverts, gardés d'un rafraîchissement à l'autre
  let runningChats = 0;
  let addTerm = null;
  const health = healthCard(api);
  const tasks = tasksSection(api, ctx);
  root.append(status, accounts, pauseBox, health, tasks.node, addBox);
  clear(accounts).append(skeleton());
  clear(status).append(el("div", { class: "skeleton line" }));

  const nameInput = el("input", { placeholder: "Nom du compte (ex. perso2)", pattern: "[A-Za-z0-9_-]{1,32}",
    autocapitalize: "off", "aria-label": "Nom du compte" });
  const addError = el("p", { class: "form-error", role: "alert" });
  addBox.append(el("h2", {}, "Ajouter un compte Claude"),
    el("p", { class: "subtle" }, "Lance « ccs add » dans un terminal : ouvre le lien de connexion sur ton téléphone ou ton PC, puis colle le code dans le terminal."),
    el("div", { class: "row" }, nameInput, el("button", { class: "small", onclick: () => {
      addError.textContent = "";
      if (!/^[A-Za-z0-9_-]{1,32}$/.test(nameInput.value)) { addError.textContent = "Nom : lettres, chiffres, - et _ seulement."; return; }
      addTerm?.destroy(true);
      const holder = el("div", { class: "term-box" });
      addBox.append(holder);
      addTerm = new TerminalView(holder, api, { cwd: ctx.home, command: "ccs add", name: nameInput.value });
    } }, "Ouvrir le terminal")), addError);

  async function switchTo(card, button) {
    const body = runningChats
      ? `${runningChats} chat(s) tournent en ce moment : ils risquent d'être perturbés par le changement de compte.`
      : "Les nouveaux chats et le terminal utiliseront ce compte.";
    if (!await confirmSheet({ title: `Basculer sur « ${card.name} » ?`, body, confirm: "Basculer" })) return;
    await busy(button, async () => {
      try {
        const r = await api.call("accounts.switch", { name: card.name });
        if (r.ok === false) throw new Error("La bascule a échoué.");
        toast(`Compte actif : ${card.name}.`, { kind: "success" });
      } catch (e) {
        toast(e.message || "La bascule a échoué.", { kind: "error", action: { label: "Réessayer", run: () => switchTo(card, button) } });
      }
    });
    load();
  }

  function accountCard(c) {
    const dot = el("span", { class: "dot" });
    dot.style.background = c.color;
    const card = el("article", { class: `card account${c.active ? " active" : ""}` },
      el("header", { class: "account-head" }, dot,
        el("div", {}, el("h2", {}, c.name), el("div", { class: "subtle" }, [c.email, c.org].filter(Boolean).join(" · "))),
        c.plan ? el("span", { class: "badge plan" }, c.plan) : null,
        c.active ? el("span", { class: "badge" }, "Actif") : null),
      ...c.main.map((g) => gauge(g, c.color)),
      !c.has_data && !c.status ? el("p", { class: "subtle" }, "Pas encore de relevé pour ce compte.") : null,
      c.status ? el("p", { class: `account-status ${c.status.kind}`, role: c.status.kind === "error" ? "alert" : null }, c.status.text) : null);
    const extra = [...c.others.map((g) => gauge(g, c.color)),
      ...c.details.map((t) => el("div", { class: "subtle" }, t)),
      c.error_raw ? el("div", { class: "subtle" }, `Message d'origine : ${c.error_raw}`) : null].filter(Boolean);
    if (extra.length) {
      const d = el("details", { class: "details" }, el("summary", {}, "Détails"), el("div", {}, ...extra));
      d.open = opened.has(c.name);
      d.addEventListener("toggle", () => { if (d.open) opened.add(c.name); else opened.delete(c.name); });
      card.append(d);
    }
    if (!c.active) {
      card.append(el("div", { class: "account-actions" },
        el("button", { onclick: (e) => switchTo(c, e.currentTarget) }, "Basculer sur ce compte")));
    }
    card.style.setProperty("--account", c.color);
    return card;
  }

  async function refreshAccounts(button) {
    await busy(button, async () => {
      try { await api.call("accounts.refresh"); } catch (e) { toast(e.message, { kind: "error", action: { label: "Réessayer", run: () => refreshAccounts(button) } }); return; }
      toast("Actualisation demandée : les chiffres arrivent dans quelques secondes.");
      setTimeout(async () => { await load(); toast("Comptes actualisés.", { kind: "success" }); }, 4000);
    });
  }

  async function setPause(choice, button, done) {
    await busy(button, async () => {
      try { await api.call("pause.set", { choice }); toast(done, { kind: "success" }); } catch (e) { toast(e.message, { kind: "error" }); }
    });
    load();
  }

  async function load() {
    let st, cards;
    try { [st, cards] = await Promise.all([api.call("accounts.state"), api.call("accounts.cards")]); } catch (e) {
      clear(accounts).append(errorState(`Comptes indisponibles : ${e.message}`, load));
      clear(status);
      return;
    }
    ctx.home = st.home;
    runningChats = cards.running_chats || 0;
    const best = cards.best?.name ? `Meilleur compte : ${cards.best.name} (${cards.best.reason})` : "";
    const decision = cards.auto_switch?.decision?.reason ? `Bascule automatique : ${cards.auto_switch.decision.reason}` : "";
    const refresh = el("button", { class: "small flat", onclick: (e) => refreshAccounts(e.currentTarget) }, "Actualiser");
    clear(status).append(el("strong", {}, `Compte actif : ${st.active || "aucun"}`),
      el("span", { class: "subtle" }, [best, decision, cards.updated_at ? `mis à jour ${ago(cards.updated_at)}` : ""].filter(Boolean).join(" · ")),
      refresh);
    clear(accounts).append(...(cards.cards.length ? cards.cards.map(accountCard)
      : [el("div", { class: "card flat empty" }, "Aucun compte enregistré : ajoute-en un plus bas.")]));
    const select = el("select", { "aria-label": "Mettre en pause" },
      ...(st.pause_choices || []).map(([value, label]) => el("option", { value }, label)));
    clear(pauseBox).append(el("strong", {}, st.pause ? `En pause ${st.pause.label}` : "Bascule et orchestrateur actifs"),
      st.pause
        ? el("button", { class: "small", onclick: (e) => setPause("off", e.currentTarget, "Pause levée.") }, "Reprendre")
        : el("div", { class: "row" }, select,
          el("button", { class: "small", onclick: (e) => setPause(select.value, e.currentTarget, "Bascule et orchestrateur en pause.") }, "Mettre en pause")));
  }

  load();
  const timer = setInterval(() => { if (!document.hidden) load(); }, 60000);
  const off = api.on("reconnected", () => { load(); tasks.reload(); });
  return () => { clearInterval(timer); off(); tasks.destroy(); addTerm?.destroy(false); };
}
