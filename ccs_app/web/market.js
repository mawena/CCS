// Onglet Market (phase 45) : le chat Claude dédié à Facebook Marketplace au Togo. Le pont prépare son
// dossier et rejoint le chat Market déjà ouvert ou reprend sa dernière conversation (`market.open`) ;
// Claude y cherche par `ccs market …` (toujours par pc-bureau) et répond par un classement avec liens.
import { ChatView } from "./chat.js";
import { clear, el, errorState, loading } from "./dom.js";

export const MARKET_HINT = "Pose ta question (« le routeur le moins cher compatible WireGuard à Lomé ») ou colle le lien d'un vendeur : "
  + "Market cherche sur Facebook Marketplace au Togo et répond par un classement avec les liens des annonces.";

export function mountMarket(root, api) {
  const box = el("div", { class: "market" });
  root.append(box);
  let view = null;
  let dead = false;

  async function open() {
    if (view) { view.destroy(); view = null; }
    clear(box).append(loading("Ouverture du chat Market…"));
    let r;
    try { r = await api.call("market.open"); } catch (e) {
      if (!dead) clear(box).append(errorState(e.message, open));
      return;
    }
    if (dead) return;
    const holder = el("div", { class: "holder" });
    clear(box).append(el("p", { class: "subtle market-hint" }, MARKET_HINT), holder);
    view = new ChatView(holder, api, { chatId: r.chat_id, cwd: r.cwd, title: "Market", history: r.path || null,
      sessionId: r.session_id || null, options: r.options || null,
      host: { back: () => { location.hash = "#/accueil"; }, resume: () => open(), stopped: () => {} } });
  }
  open();
  // Le chat reste ouvert dans le pont (repris au retour sur l'onglet, ou depuis un autre appareil).
  return () => { dead = true; if (view) view.destroy(); };
}
