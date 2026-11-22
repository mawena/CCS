// Écrans de la version web. Chaque écran : { title, icon, mount(container, api, ctx) → nettoyage }.
// `hidden` : absent de la barre de navigation ; `parent` : l'onglet allumé quand il est ouvert.
import { mountAnalysis } from "./analysis.js";
import { el } from "./dom.js";
import { mountFiles } from "./files-browser.js";
import { mountHome } from "./home.js";
import { mountJarvis } from "./jarvis.js";
import { mountMachines } from "./pages-machines.js";
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
  jarvis: { title: "Jarvis", icon: "🎙", mount: mountJarvis },
  reglages: { title: "Réglages", icon: "⚙", mount: mountSettings },
  // hors de la barre de navigation : ouverte depuis Réglages et la feuille « Machine pilotée »
  machines: { title: "Machines", icon: "🖥", mount: mountMachines, hidden: true, parent: "reglages" },
};
