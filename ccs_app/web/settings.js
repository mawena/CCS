// Réglages : thème (gardé dans le navigateur), les réglages du bureau (enregistrés par le pont,
// validés comme au bureau, chacun confirmé par un toast), le téléphone (ntfy) et les appareils
// connectés (jetons d'application, appareils retenus), révocables.
import { post } from "./api.js";
import { clear, confirmSheet, el, toast } from "./dom.js";
import { canInstall, install, installSteps, installed } from "./install.js";
import { phoneGroup } from "./pages-phone.js";
import { settingRow } from "./pages-util.js";

const THEME_KEY = "ccs-theme";
const THEMES = [["auto", "Automatique"], ["light", "Clair"], ["dark", "Sombre"]];

export function storedTheme() {
  try { const t = localStorage.getItem(THEME_KEY); return THEMES.some(([v]) => v === t) ? t : "auto"; } catch { return "auto"; }
}

export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

applyTheme(storedTheme());           // au chargement de la page, avant le premier écran

const RIGHTS = [["manual", "Manuel"], ["acceptEdits", "Accepter les modifications"], ["plan", "Plan"],
  ["auto", "Auto"], ["dontAsk", "Sans question"], ["bypassPermissions", "Aucune vérification"]];

const OUTSIDE = [["notify", "Notification"], ["resume", "Relance en arrière-plan"]];

const GROUPS = [
  ["Bascule automatique", [
    { path: "auto_switch.enabled", label: "Basculer avant la limite", type: "bool" },
    { path: "auto_switch.threshold", label: "Seuil de bascule (%)", type: "number", min: 1, max: 100 },
    { path: "auto_switch.target_max_session", label: "Session maximale du compte visé (%)", type: "number", min: 0, max: 100 },
    { path: "auto_switch.target_max_weekly", label: "Semaine maximale du compte visé (%)", type: "number", min: 0, max: 100 },
  ]],
  ["Orchestrateur", [
    { path: "orchestrator.enabled", label: "Orchestrateur des fenêtres de 5 h", type: "bool" },
    { path: "orchestrator.active_hours.start", label: "Début de la plage active", type: "time" },
    { path: "orchestrator.active_hours.end", label: "Fin de la plage active", type: "time" },
    { path: "orchestrator.reserve_points", label: "Réserve (points)", type: "number", min: 0, max: 100 },
  ]],
  ["Alertes", [
    { path: "alerts.enabled", label: "Alertes", type: "bool" },
    { path: "alerts.eta_minutes", label: "Prévenir avant la limite (minutes)", type: "number", min: 1, max: 1440 },
    { path: "alerts.weekly_forecast", label: "Prévision de la semaine", type: "bool" },
    { path: "alerts.waiting_reminder", label: "Rappel quand une session attend ma réponse", type: "bool" },
    { path: "alerts.waiting_reminder_min", label: "Rappel après (minutes)", type: "number", min: 1, max: 1440 },
    { path: "context_alert.enabled", label: "Alerte de contexte lourd", type: "bool" },
    { path: "context_alert.threshold_tokens", label: "Seuil du contexte lourd (jetons)", type: "number", min: 1000, max: 10000000 },
    { path: "context_alert.auto_compact", label: "Compacter automatiquement les chats au-delà du seuil", type: "bool" },
    { path: "budget.enabled", label: "Budgets par projet", type: "bool" },
  ]],
  ["Ne pas déranger", [
    { path: "alerts.quiet.enabled", label: "Plage de silence", type: "bool" },
    { path: "alerts.quiet.start", label: "Début", type: "time" },
    { path: "alerts.quiet.end", label: "Fin", type: "time" },
    { path: "alerts.quiet.allow_waiting", label: "Prévenir quand même si une session attend ma réponse", type: "bool" },
  ]],
  ["Chat et sessions", [
    { path: "chat.rights", label: "Droits des nouveaux chats", type: RIGHTS },
    { path: "limit_resume.enabled", label: "Relancer les conversations bloquées quand la limite est levée", type: "bool" },
    { path: "limit_resume.outside", label: "Conversation fermée hors de CCS, à la levée", type: OUTSIDE },
    { path: "chat.auto_clear", label: "Effacement automatique : Claude vide la conversation (/clear) en fin de sujet", type: "bool" },
    { path: "chat.idle_suspend_min", label: "Mise en veille d'un chat inactif (minutes, 0 = jamais)", type: "number", min: 0, max: 1440 },
    { path: "sessions.idle_hours", label: "Session inactive après (heures)", type: "number", min: 0.01, max: 720 },
  ]],
  ["Git", [
    { path: "git.fetch_minutes", label: "Fetch automatique (minutes, 0 = jamais)", type: "number", min: 0, max: 1440 },
    { path: "git.layout", label: "Disposition de la page Git (bureau)", type: [["A", "A"], ["B", "B"], ["C", "C"]] },
    { path: "git.avatars", label: "Avatars des auteurs (bureau)", type: "bool" },
  ]],
  ["Tâches de nuit", [
    { path: "tasks.enabled", label: "Lancer les tâches", type: "bool" },
    { path: "tasks.night.start", label: "Début de la nuit", type: "time" },
    { path: "tasks.night.end", label: "Fin de la nuit", type: "time" },
    { path: "tasks.max_attempts", label: "Relances après une limite atteinte", type: "number", min: 1, max: 10, step: 1 },
  ]],
  ["Archive des conversations", [
    { path: "archive.enabled", label: "Archiver les conversations", type: "bool" },
    { path: "archive.idle_days", label: "Archiver après (jours inactifs)", type: "number", min: 0, max: 3650, step: 1 },
    { path: "archive.max_age_days", label: "Supprimer après (jours, 0 = jamais)", type: "number", min: 0, max: 36500, step: 1 },
  ]],
  ["Mises à jour", [{ path: "updates.enabled", label: "Chercher les nouvelles versions", type: "bool" }]],
];

const KINDS = { session: "Navigateur", device: "Appareil retenu (sans code)", app: "Application" };

function themeGroup() {
  const group = el("section", { class: "card flat settings-group" }, el("h2", {}, "Apparence"),
    el("p", { class: "subtle" }, "Gardé dans ce navigateur : chaque appareil a le sien."));
  const row = el("div", { class: "theme-choice", role: "group", "aria-label": "Thème" });
  const draw = () => {
    clear(row).append(...THEMES.map(([value, label]) => el("button", { "aria-pressed": String(storedTheme() === value),
      onclick: () => {
        try { localStorage.setItem(THEME_KEY, value); } catch { toast("Ce navigateur ne garde pas le thème.", { kind: "error" }); }
        applyTheme(value);
        draw();
        toast("Enregistré.", { kind: "success" });
      } }, label)));
  };
  draw();
  group.append(row);
  return group;
}

// « Application » : installer CCS sur l'écran d'accueil (comme Outlook), ou rappeler qu'il l'est.
function installGroup() {
  const group = el("section", { class: "card flat settings-group" }, el("h2", {}, "Application"));
  if (installed()) group.append(el("p", { class: "subtle" }, "CCS est installé sur cet appareil."));
  else if (!canInstall()) group.append(el("p", { class: "subtle" }, "Ce navigateur ne propose pas l'installation. Sur iPhone : Safari ou Chrome ; ailleurs : Chrome ou Edge."));
  else {
    const steps = installSteps();
    group.append(el("p", { class: "subtle" }, "Une icône sur l'écran d'accueil, en plein écran, sans barre du navigateur."),
      steps || el("button", { type: "button", class: "primary", onclick: async () => {
        if (await install()) toast("CCS est installé.", { kind: "success" });
      } }, "Installer CCS"));
  }
  return group;
}

// « Machines » : lien vers la page des machines du relais Ricochet et des commandes lancées dessus.
function machinesGroup() {
  return el("section", { class: "card flat settings-group" }, el("h2", {}, "Machines"),
    el("p", { class: "subtle" }, "Les machines du relais Ricochet, les commandes lancées dessus et les réglages du relais."),
    el("div", {}, el("button", { type: "button", class: "manage-machines", onclick: () => { location.hash = "#/machines"; } }, "Gérer les machines")));
}

export function mountSettings(root, api) {
  const wrap = el("div", { class: "settings-wrap" });
  const forms = el("div", { class: "settings-wrap" });
  const devices = el("section", { class: "card flat" });
  wrap.append(themeGroup(), installGroup(), machinesGroup(), forms, devices);
  root.append(wrap);

  async function loadSettings() {
    let s;
    try { s = (await api.call("settings.get")).settings; } catch (e) {
      clear(forms).append(el("p", { class: "form-error" }, e.message));
      return;
    }
    clear(forms).append(phoneGroup(api, s, loadSettings),
      ...GROUPS.map(([title, rows]) => el("section", { class: "card flat settings-group" }, el("h2", {}, title),
        ...rows.map((r) => settingRow(api, s, r)))));
  }

  async function loadDevices() {
    clear(devices).append(el("h2", {}, "Appareils"),
      el("p", { class: "subtle" }, "Navigateurs, appareils retenus et applications (bureau, ccs tui) connectés à ton compte."));
    const r = await fetch("/api/tokens", { credentials: "same-origin" });
    if (!r.ok) { devices.append(el("p", { class: "form-error" }, "Liste indisponible.")); return; }
    const { tokens } = await r.json();
    for (const t of tokens) {
      devices.append(el("div", { class: "row" },
        el("div", { class: "grow" }, el("strong", {}, t.name || KINDS[t.kind] || t.kind),
          el("div", { class: "subtle" }, `${KINDS[t.kind] || t.kind} · utilisé le ${new Date(t.last_used * 1000).toLocaleString("fr-FR")}`)),
        el("button", { class: "small flat", onclick: async () => {
          if (!await confirmSheet({ title: "Révoquer cet accès ?", body: "L'appareil devra se reconnecter.", confirm: "Révoquer", danger: true })) return;
          const res = await post("/api/revoke", { token_id: t.id }).catch((e) => ({ status: "error", message: e.message }));
          if (!res || res.status === "error" || res.revoked === false) { toast((res && res.message) || "Révocation impossible : cet accès n'existe plus.", { kind: "error" }); return; }
          toast("Accès révoqué.", { kind: "success" });
          loadDevices();
        } }, "Révoquer")));
    }
  }

  loadSettings();
  loadDevices();
}
