// Git du projet au web (phase 14) : état, diff, indexation, commit, fetch / pull / push.
// Volet ouvert depuis le chat (bouton « Git ») et depuis l'écran Projet. Version d'attente :
// le lot « pages » la remplit (méthodes `git.*` du pont, bridge_git.py).
import { el, emptyState } from "./dom.js";

export class GitPanel {
  constructor(container, api, cwd) {
    this.api = api;
    this.cwd = cwd;
    this.node = el("div", { class: "git" }, emptyState("Git arrive bientôt dans la version web."));
    container.append(this.node);
  }

  destroy() {}
}
