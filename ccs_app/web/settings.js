// Réglages : les réglages principaux (enregistrés par le pont, validés comme au bureau) et les
// appareils connectés (jetons d'application, appareils retenus), révocables.
import { post } from "./api.js";
import { clear, el } from "./dom.js";

const FIELDS = [
  ["auto_switch.enabled", "Bascule automatique avant la limite", "bool"],
  ["auto_switch.threshold", "Seuil de bascule (%)", "number"],
  ["orchestrator.enabled", "Orchestrateur des fenêtres de 5 h", "bool"],
  ["chat.idle_suspend_min", "Mise en veille d'un chat inactif (minutes, 0 = jamais)", "number"],
  ["chat.rights", "Droits des nouveaux chats", [["manual", "Manuel"], ["acceptEdits", "Accepter les modifications"],
    ["plan", "Plan"], ["auto", "Auto"], ["dontAsk", "Sans question"], ["bypassPermissions", "Aucune vérification"]]],
  ["context_alert.threshold_tokens", "Alerte de contexte lourd (jetons)", "number"],
  ["phone.enabled", "Notifications sur le téléphone (ntfy)", "bool"],
];

const KINDS = { session: "Navigateur", device: "Appareil retenu (sans code)", app: "Application" };

function get(obj, path) { return path.split(".").reduce((o, k) => (o ? o[k] : undefined), obj); }

export function mountSettings(root, api) {
  const form = el("section", { class: "card flat settings" }, el("h2", {}, "Réglages"));
  const devices = el("section", { class: "card flat" });
  root.append(form, devices);

  async function save(path, value, input) {
    try { await api.call("settings.set", { path, value }); input.classList.remove("invalid"); } catch (e) {
      input.classList.add("invalid");
      alert(e.message);
    }
  }

  async function loadSettings() {
    let s;
    try { s = (await api.call("settings.get")).settings; } catch (e) { form.append(el("p", { class: "message" }, e.message)); return; }
    for (const [path, label, type] of FIELDS) {
      const value = get(s, path);
      let input;
      if (type === "bool") {
        input = el("input", { type: "checkbox" });
        input.checked = Boolean(value);
        input.addEventListener("change", () => save(path, input.checked, input));
        form.append(el("label", { class: "check" }, input, label));
        continue;
      }
      if (Array.isArray(type)) {
        input = el("select", {}, ...type.map(([v, text]) => el("option", { value: v }, text)));
        input.value = value;
      } else {
        input = el("input", { type: "number", inputmode: "numeric", value: value ?? "" });
      }
      input.addEventListener("change", () => save(path, type === "number" ? Number(input.value) : input.value, input));
      form.append(el("label", {}, label, input));
    }
  }

  async function loadDevices() {
    clear(devices).append(el("h2", {}, "Appareils"),
      el("p", { class: "subtle" }, "Navigateurs, appareils retenus et applications (bureau, ccs tui) connectés à ton compte."));
    const r = await fetch("/api/tokens", { credentials: "same-origin" });
    if (!r.ok) { devices.append(el("p", { class: "message" }, "Liste indisponible.")); return; }
    const { tokens } = await r.json();
    for (const t of tokens) {
      devices.append(el("div", { class: "row" },
        el("div", { class: "grow" }, el("strong", {}, t.name || KINDS[t.kind] || t.kind),
          el("div", { class: "subtle" }, `${KINDS[t.kind] || t.kind} · utilisé le ${new Date(t.last_used * 1000).toLocaleString("fr-FR")}`)),
        el("button", { class: "small flat", onclick: async () => {
          if (!confirm("Révoquer cet accès ? L'appareil devra se reconnecter.")) return;
          await post("/api/revoke", { token_id: t.id });
          loadDevices();
        } }, "Révoquer")));
    }
  }

  loadSettings();
  loadDevices();
}
