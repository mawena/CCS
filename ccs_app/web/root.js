// Mot de passe root demandé aux appareils (phase 34), version web : suit `root.*` du pont de la
// machine pilotée, montre la fenêtre de la demande (`root.ask`) au premier plan et le bandeau
// « root gardé sur X, N min » avec « Oublier ». Même comportement que les applis Android et iPhone.
//
// Le mot de passe ne fait que passer : lu dans le champ, champ vidé aussitôt, envoyé par
// `root.answer`. Jamais gardé ici, jamais dans localStorage, sessionStorage, la console ni l'adresse ;
// jamais confié à la file d'attente de l'Api hors ligne (il y resterait jusqu'à la reconnexion).
//
// Les heures du pont (`expires_at`, secondes depuis 1970) viennent d'une autre horloge : les
// échéances sont recalculées sur celle du navigateur, bornées par les durées du gardien
// (5 min pour une demande, 1 h pour le mot de passe gardé).
import { el, toast } from "./dom.js";

export const ASK_MS = 5 * 60_000;
export const KEEP_MS = 60 * 60_000;
const MARGIN_MS = 30_000;              // décalage d'horloge admis entre le pont et le navigateur
const ANSWER_MS = 45_000;              // vérification par `sudo -k -S -v` : jusqu'à 30 s, plus le relais

const text = (v) => (typeof v === "string" ? v.trim() : "");

// Échéance locale d'une heure du pont ; si l'écart n'est pas plausible, maintenant + `defMs`.
export function deadline(expiresAt, nowMs, defMs) {
  const delta = typeof expiresAt === "number" ? Math.round(expiresAt * 1000) - nowMs : null;
  return delta === null || delta <= 0 || delta > defMs + MARGIN_MS ? nowMs + defMs : nowMs + delta;
}

// Lit un `root.ask` (ou le `pending` de `root.status`) ; null sans identifiant.
export function readAsk(d, nowMs) {
  const id = text(d?.id);
  if (!id) return null;
  return {
    id,
    machine: text(d.machine) || "Une machine",
    command: text(d.command),
    until: deadline(d.expires_at, nowMs, ASK_MS),
    tries: Number.isInteger(d.tries_left) ? d.tries_left : 0,
    error: text(d.error) || null,
  };
}

// Minutes restantes, arrondies au-dessus (« 1 min » jusqu'à la fin).
export const minutes = (ms) => (ms <= 0 ? 0 : Math.ceil(ms / 60_000));

// Compte à rebours « 4:05 ».
export function clock(ms) {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function triesText(n) {
  if (n <= 0) return "";
  return n === 1 ? "Dernier essai." : `${n} essais restants.`;
}

export function keptText(machine, ms, forever = false) {
  if (forever) return machine ? `Root gardé sur ${machine} (chiffré)` : "Root gardé (chiffré)";
  const m = minutes(ms);
  return machine ? `Root gardé sur ${machine}, ${m} min` : `Root gardé, ${m} min`;
}

export function errorText(code, message) {
  switch (code) {
    case "introuvable": return "Demande expirée ou déjà réglée.";
    case "conflit": return "Un autre appareil a répondu : vérification en cours.";
    case "invalide": return "Réponse invalide.";
    case "delai": return "Pas de réponse du serveur.";
    case "hors_ligne": return "Connexion perdue : réessaie une fois reconnecté.";
    default: return text(message) || "Réponse non envoyée.";
  }
}

export function usedText(d) {
  const machine = text(d?.machine) || "La machine", command = text(d?.command);
  return command ? `${machine} a lancé en root : ${command}` : `${machine} a lancé une commande root.`;
}

export function forgottenText(reason) {
  switch (reason) {
    case "expired": return "Mot de passe root effacé (1 h passée).";
    case "revoke": return "Mot de passe root révoqué.";
    case "stop": return "Mot de passe root effacé (pont arrêté).";
    default: return "Mot de passe root oublié.";
  }
}

function withTimeout(promise, ms) {
  let timer;
  const late = new Promise((_, reject) => {
    timer = setTimeout(() => reject(Object.assign(new Error("délai"), { code: "delai" })), ms);
  });
  return Promise.race([promise, late]).finally(() => clearTimeout(timer));
}

// Suit le mot de passe root de la connexion en cours (`api` : la même pour toutes les machines,
// `machines.attach` passe par Api.setMachine et l'événement « machine »).
export class RootWatch {
  constructor(api, { now = () => Date.now(), host = null, tick = 1000 } = {}) {
    this.api = api;
    this.now = now;
    this.host = host;
    this.tickMs = tick;
    this.ask = null;          // demande en cours { id, machine, command, until, tries, error }
    this.kept = null;         // mot de passe gardé { machine, until }
    this.sending = false;     // réponse envoyée, en attente du pont
    this.notice = null;       // erreur locale de la dernière réponse
    this.asks = 0;            // `root.ask` reçus (le dernier dit déjà l'erreur et les essais)
    this.forgetting = false;  // « Oublier » cliqué ici, en cours
    this.gen = 0;             // change avec la machine : les réponses d'avant sont ignorées
    this.dialog = null;
    this.bar = null;
    this.offs = [];
    this.timer = null;
  }

  start() {
    const api = this.api;
    this.offs = [
      api.on("root.ask", (d) => this.onAsk(d)),
      api.on("root.resolved", (d) => this.onResolved(d)),
      api.on("root.used", (d) => { toast(usedText(d)); this.refresh(); }),
      api.on("root.forgotten", (d) => this.onForgotten(d)),
      // ce serveur : prêt dès l'ouverture ; une autre machine : quand le tunnel est prêt
      api.on("online", () => { if (!api.machine) this.refresh(); }),
      api.on("machines.ready", () => this.refresh()),
      api.on("machine", () => this.reset()),
    ];
    this.timer = setInterval(() => this.tick(), this.tickMs);
    if (api.online && !api.machine) this.refresh();
    return this;
  }

  stop() {
    for (const off of this.offs) off();
    this.offs = [];
    clearInterval(this.timer);
    this.timer = null;
    this.closeDialog();
    this.bar?.remove();
    this.bar = null;
  }

  // Autre machine pilotée : ce qu'on savait de l'ancienne ne vaut plus (relu à la connexion).
  reset() {
    this.gen += 1;
    this.ask = null;
    this.kept = null;
    this.sending = false;
    this.notice = null;
    this.render();
  }

  // `root.status` : garde et demande en cours ; silencieux en cas d'échec (ancien pont…).
  async refresh() {
    const gen = this.gen;
    let r;
    try { r = await this.api.call("root.status"); } catch { return; }
    if (gen !== this.gen || !r) return;
    const now = this.now();
    if (r.kept) {
      const left = Number(r.remaining);
      const until = left > 0 ? now + Math.min(left, KEEP_MS / 1000) * 1000 : deadline(r.expires_at, now, KEEP_MS);
      this.kept = { machine: text(r.machine), until: r.forever ? Infinity : until, forever: Boolean(r.forever) };
    } else {
      this.kept = null;
    }
    const ask = readAsk(r.pending, now);
    // une réponse en cours pour la même demande reste affichée telle quelle
    const keepSending = Boolean(ask && this.sending && this.ask?.id === ask.id);
    if (!keepSending) {
      if (ask?.id !== this.ask?.id) this.notice = null;
      this.ask = ask;
      this.sending = false;
    }
    this.render();
  }

  onAsk(d) {
    const ask = readAsk(d, this.now());
    if (!ask) return;
    this.ask = ask;
    this.asks += 1;
    this.sending = false;
    this.notice = null;
    this.render();
  }

  onResolved(d) {
    if (!this.ask || this.ask.id !== text(d?.id)) return;
    this.ask = null;
    this.sending = false;
    this.notice = null;
    this.render();
  }

  onForgotten(d) {
    const had = Boolean(this.kept);
    this.kept = null;
    if (d?.reason === "forget" || d?.reason === "stop") { this.ask = null; this.sending = false; this.notice = null; }
    this.render();
    if (had && !this.forgetting) toast(forgottenText(d?.reason));
  }

  tick() {
    const now = this.now();
    let changed = false;
    if (this.ask && now >= this.ask.until) { this.ask = null; this.sending = false; this.notice = null; changed = true; }
    if (this.kept && now >= this.kept.until) { this.kept = null; changed = true; }
    if (changed || this.ask || this.kept) this.render();
  }

  // Envoie la réponse à la demande en cours : mot de passe, ou refus (`cancel`).
  async answer(password, cancel = false) {
    const ask = this.ask, gen = this.gen, asks = this.asks;
    if (!ask || this.sending) return;
    if (!cancel && !password) return;
    if (!this.api.online) { this.notice = errorText("hors_ligne"); this.render(); return; }
    this.sending = true;
    this.notice = null;
    this.render();
    let r = null, err = null;
    try {
      r = await withTimeout(this.api.call("root.answer", cancel ? { id: ask.id, cancel: true } : { id: ask.id, password }), ANSWER_MS);
    } catch (e) { err = e; }
    password = null;
    if (gen !== this.gen || this.ask?.id !== ask.id) return;
    this.sending = false;
    if (err) {
      if (err.code === "introuvable") this.ask = null;
      else this.notice = errorText(err.code, err.message);
    } else if (r?.ok || cancel) {
      this.ask = null;
      if (r?.ok) this.refresh();                // durée de la garde
    } else if (asks === this.asks) {
      // le `root.ask` de la même demande, arrivé avant cette réponse, dit déjà l'erreur
      this.notice = text(r?.error) || "Mot de passe refusé.";
    }
    this.render();
  }

  async forget() {
    this.forgetting = true;               // l'avis vient d'ici, pas de `root.forgotten`
    try {
      const r = await this.api.call("root.forget");
      this.kept = null;
      this.render();
      toast(r?.had ? "Mot de passe root effacé." : "Aucun mot de passe root gardé.");
    } catch (e) {
      toast(`Impossible d'effacer : ${errorText(e.code, e.message)}`, { kind: "error" });
    } finally {
      this.forgetting = false;
    }
  }

  render() {
    this.renderDialog();
    this.renderBar();
  }

  // ---- fenêtre de la demande --------------------------------------------------------------

  closeDialog() {
    const dlg = this.dialog;
    if (!dlg) return;
    this.dialog = null;
    if (dlg.parts?.input) dlg.parts.input.value = "";
    if (dlg.open) dlg.close();
    dlg.remove();
  }

  buildDialog() {
    const input = el("input", {
      type: "password", autocomplete: "off", autocapitalize: "none", spellcheck: "false",
      "aria-label": "Mot de passe root", "data-lpignore": "true", "data-1p-ignore": "true",
    });
    const title = el("h2", {});
    const command = el("pre", { class: "root-command" });
    const error = el("p", { class: "root-error", role: "alert" });
    const info = el("p", { class: "subtle root-info" });
    const send = el("button", { type: "submit", class: "primary" }, "Envoyer");
    const refuse = el("button", { type: "button", onclick: () => { input.value = ""; this.answer(null, true); } }, "Refuser");
    const form = el("form", { class: "root-form", autocomplete: "off" },
      command, el("label", {}, "Mot de passe", input), error, info,
      el("div", { class: "sheet-actions" }, refuse, send));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const pw = input.value;
      input.value = "";                          // vidé dès la lecture
      if (pw) this.answer(pw);
    });
    const dlg = el("dialog", { class: "sheet root-sheet", "aria-label": "Mot de passe root demandé" }, title, form);
    // ni Échap ni clic à côté : on répond (Envoyer ou Refuser), ou la demande expire
    dlg.addEventListener("cancel", (e) => e.preventDefault());
    dlg.parts = { input, title, command, error, info, send, refuse };
    document.body.append(dlg);
    dlg.showModal();
    input.focus?.();
    return dlg;
  }

  renderDialog() {
    const ask = this.ask;
    if (!ask) { this.closeDialog(); return; }
    const fresh = !this.dialog || this.dialog.dataset.askId !== ask.id;
    if (!this.dialog) this.dialog = this.buildDialog();
    const dlg = this.dialog, p = dlg.parts;
    if (fresh) p.input.value = "";
    dlg.dataset.askId = ask.id;
    p.title.textContent = `${ask.machine} demande le mot de passe root`;
    p.command.textContent = ask.command;
    p.command.hidden = !ask.command;
    const error = this.notice || ask.error;
    p.error.textContent = error || "";
    p.error.hidden = !error;
    p.info.textContent = this.sending ? "Vérification…"
      : [triesText(ask.tries), `Expire dans ${clock(ask.until - this.now())}.`].filter(Boolean).join(" ");
    p.input.disabled = this.sending;
    p.send.disabled = this.sending;
    p.refuse.disabled = this.sending;
    if (!dlg.open) dlg.showModal();
  }

  // ---- bandeau « root gardé » --------------------------------------------------------------

  renderBar() {
    const kept = this.kept;
    if (!kept) {
      if (this.bar) this.bar.hidden = true;
      setBarHeight(0);
      return;
    }
    if (!this.bar) {
      this.bar = el("div", { class: "root-bar", role: "status" },
        el("span", { class: "root-bar-ico", "aria-hidden": "true" }, "🔒"),
        el("span", { class: "grow root-bar-text" }),
        el("button", { type: "button", class: "small flat", onclick: () => this.forget() }, "Oublier"));
      const host = this.host || document.getElementById("shell") || document.body;
      const view = host.querySelector?.("#view");
      if (view) host.insertBefore(this.bar, view); else host.append(this.bar);
    }
    this.bar.hidden = false;
    this.bar.querySelector(".root-bar-text").textContent = keptText(kept.machine, kept.until - this.now(), kept.forever);
    setBarHeight(this.bar.offsetHeight);
  }
}

// Hauteur du bandeau retirée de celle des sessions (style.css), sinon la page défile.
function setBarHeight(px) {
  document.documentElement?.style?.setProperty?.("--root-bar-h", `${px || 0}px`);
}
