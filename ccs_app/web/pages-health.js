// Carte « Bilan de santé » : lance `ccs doctor` côté pont ; erreurs et avertissements d'abord,
// avec la commande qui corrige et un bouton « Copier ».
import { clear, el, errorState, loading, toast } from "./dom.js";
import { busy, copyText } from "./pages-util.js";

const GLYPH = { erreur: "✖", avertissement: "⚠", ok: "✔" };
const CLASS = { erreur: "err-text", avertissement: "warn-text", ok: "ok-text" };

function checkRow(c) {
  return el("div", { class: "health-check" },
    el("div", { class: "health-check-head" }, el("span", { class: CLASS[c.statut] || "", "aria-hidden": "true" }, GLYPH[c.statut] || "•"),
      el("strong", {}, c.nom), el("span", { class: "visually-hidden" }, c.statut)),
    el("div", { class: "subtle" }, c.detail),
    c.commande ? el("div", { class: "health-check-cmd" }, el("code", {}, c.commande),
      el("button", { class: "small", "aria-label": `Copier la commande : ${c.commande}`, onclick: () => copyText(c.commande) }, "Copier")) : null);
}

export function healthCard(api) {
  const body = el("div", { class: "stack" });
  const run = el("button", { class: "small" }, "Lancer le bilan");
  const card = el("section", { class: "card flat section" },
    el("div", { class: "page-head" }, el("h2", {}, "Bilan de santé"), run),
    el("p", { class: "subtle" }, "Vérifie le service, les comptes, Claude Code, le téléphone et le serveur."), body);

  async function go() {
    clear(body).append(loading("Vérification en cours…"));
    let r;
    try { r = await api.call("doctor.run"); } catch (e) {
      clear(body).append(errorState(e.message, go));
      return;
    }
    const bad = r.checks.filter((c) => c.statut !== "ok");
    const good = r.checks.filter((c) => c.statut === "ok");
    clear(body).append(el("strong", { class: r.errors ? "err-text" : r.warnings ? "warn-text" : "ok-text" }, r.summary),
      ...bad.map(checkRow),
      good.length ? el("details", { class: "details" }, el("summary", {}, `${good.length} vérification(s) réussie(s)`),
        el("div", {}, ...good.map(checkRow))) : null);
    if (!r.errors && !r.warnings) toast("Tout va bien.", { kind: "success" });
  }
  run.addEventListener("click", () => busy(run, go));
  return card;
}
