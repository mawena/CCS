// Analyse : usage pondéré par projet, modèle, compte et heure, sur 1, 7, 30 ou 90 jours.
import { clear, el, emptyState, errorState, loading } from "./dom.js";

const PERIODS = [[1, "24 heures"], [7, "7 jours"], [30, "30 jours"], [90, "90 jours"]];

function fmt(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} G`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)} k`;
  return String(Math.round(n));
}

function bars(title, data, total) {
  const rows = Object.entries(data || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  return el("section", { class: "card flat" }, el("h2", {}, title),
    ...rows.map(([name, v]) => {
      const fill = el("div", { class: "bar-fill" });
      fill.style.width = `${total ? (100 * v) / total : 0}%`;
      return el("div", { class: "bar" }, el("span", { class: "bar-name", title: name }, name),
        el("div", { class: "bar-track" }, fill), el("span", { class: "bar-value" }, `${total ? ((100 * v) / total).toFixed(1) : 0} %`));
    }));
}

export function mountAnalysis(root, api) {
  let days = 7;
  const tabs = el("div", { class: "seg", role: "group", "aria-label": "Période" });
  const body = el("div", { class: "analysis" });
  root.append(el("div", { class: "page-head" }, el("h2", {}, "Analyse")), tabs, body);
  let token = 0;

  function drawTabs() {
    clear(tabs).append(...PERIODS.map(([d, label]) => el("button", { class: "small", "aria-pressed": String(d === days),
      onclick: () => { days = d; load(); } }, label)));
  }

  async function load() {
    const mine = ++token;
    drawTabs();
    clear(body).append(loading("Lecture des journaux…"));
    let r;
    try { r = await api.call("analysis.report", { days }); } catch (e) {
      if (mine === token) clear(body).append(errorState(e.message, load));
      return;
    }
    if (mine !== token) return;                 // une autre période a été choisie entre-temps
    if (!r.responses) {
      const actions = days === 30 ? [] : [el("button", { class: "small", onclick: () => { days = 30; load(); } }, "Essayer 30 jours")];
      clear(body).append(el("div", { class: "card analysis-empty" },
        emptyState("Aucune activité sur cette période.", ...actions)));
      return;
    }
    const peak = Math.max(...r.by_hour, 1);
    const hours = el("div", { class: "hours", role: "img", "aria-label": "Usage par heure de la journée" }, ...r.by_hour.map((v, h) => {
      const col = el("div", { class: "hour", title: `${h} h : ${fmt(v)}` });
      col.style.height = `${(100 * v) / peak}%`;
      return col;
    }));
    clear(body).append(
      el("section", { class: "card" }, el("div", { class: "big-number" }, fmt(r.total)),
        el("div", { class: "subtle" }, `jetons pondérés · ${r.responses} réponses`)),
      bars("Par projet", r.by_project, r.total), bars("Par modèle", r.by_model, r.total),
      bars("Par compte", r.by_account, r.total),
      el("section", { class: "card flat" }, el("h2", {}, "Par heure"), hours));
  }
  load();
}
