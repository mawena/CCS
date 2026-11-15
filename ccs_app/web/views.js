// Écrans de la version web. Chaque écran : { title, icon, mount(container, api, ctx) → nettoyage }.
import { el } from "./dom.js";

function placeholder(title) {
  return (root) => { root.append(el("div", { class: "card empty" }, el("h2", {}, title), el("p", { class: "subtle" }, "Bientôt ici."))); };
}

export const VIEWS = {
  accueil: { title: "Accueil", icon: "⌂", mount: placeholder("Accueil") },
  sessions: { title: "Sessions", icon: "💬", mount: placeholder("Sessions") },
  analyse: { title: "Analyse", icon: "▤", mount: placeholder("Analyse") },
  reglages: { title: "Réglages", icon: "⚙", mount: placeholder("Réglages") },
};
