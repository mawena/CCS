// Écrans de la version web. Chaque écran : { title, icon, mount(container, api, ctx) → nettoyage }.
import { mountAnalysis } from "./analysis.js";
import { el } from "./dom.js";
import { mountFiles } from "./files-browser.js";
import { mountHome } from "./home.js";
import { mountSessions } from "./sessions.js";
import { mountSettings } from "./settings.js";

function placeholder(title) {
  return (root) => { root.append(el("div", { class: "card empty" }, el("h2", {}, title), el("p", { class: "subtle" }, "Bientôt ici."))); };
}

export const VIEWS = {
  accueil: { title: "Accueil", icon: "⌂", mount: mountHome },
  sessions: { title: "Sessions", icon: "💬", mount: mountSessions },
  fichiers: { title: "Fichiers", icon: "📁", mount: mountFiles },
  analyse: { title: "Analyse", icon: "▤", mount: mountAnalysis },
  reglages: { title: "Réglages", icon: "⚙", mount: mountSettings },
};
