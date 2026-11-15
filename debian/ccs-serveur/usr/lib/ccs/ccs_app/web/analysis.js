// Analyse : usage pondéré par projet, modèle, compte et heure, sur 7 ou 30 jours.
import { clear, el } from "./dom.js";

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
      return el("div", { class: "bar" }, el("span", { class: "bar-name" }, name),
        el("div", { class: "bar-track" }, fill), el("span", { class: "bar-value" }, `${total ? ((100 * v) / total).toFixed(1) : 0} %`));
    }));
}

export function mountAnalysis(root, api) {
  const days = el("select", { "aria-label": "Période" }, el("option", { value: "7" }, "7 derniers jours"),
    el("option", { value: "30" }, "30 derniers jours"));
  const body = el("div", { class: "analysis" });
  root.append(el("div", { class: "row" }, el("h2", { class: "grow" }, "Analyse"), days), body);

  async function load() {
    clear(body).append(el("p", { class: "subtle" }, "Lecture des journaux…"));
    let r;
    try { r = await api.call("analysis.report", { days: Number(days.value) }); } catch (e) {
      clear(body).append(el("p", { class: "message" }, e.message));
      return;
    }
    if (!r.responses) { clear(body).append(el("div", { class: "card empty" }, "Aucune activité sur la période.")); return; }
    const peak = Math.max(...r.by_hour, 1);
    const hours = el("div", { class: "hours" }, ...r.by_hour.map((v, h) => {
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
  days.addEventListener("change", load);
  load();
}
