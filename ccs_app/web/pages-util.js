// Petits outils communs aux pages Accueil, Réglages, Analyse et Git.
import { el, toast } from "./dom.js";

// Copie dans le presse-papiers (HTTPS : API moderne ; sinon, repli par un champ caché).
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copié.", { kind: "success" });
    return true;
  } catch { /* repli ci-dessous */ }
  const area = el("textarea", { "aria-hidden": "true", readonly: true });
  area.value = text;
  document.body.append(area);
  area.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  area.remove();
  toast(ok ? "Copié." : "Copie impossible : sélectionne le texte à la main.", { kind: ok ? "success" : "error" });
  return ok;
}

// Désactive le bouton le temps de l'action (évite le double appui au téléphone).
export async function busy(button, action) {
  if (button) button.disabled = true;
  try { return await action(); } finally { if (button) button.disabled = false; }
}

export function field(label, input, hint = "") {
  return el("label", { class: "field" }, label, input, hint ? el("span", { class: "hint" }, hint) : null);
}

export function shortPath(path) {
  return String(path || "").replace(/^\/home\/[^/]+/, "~");
}

// Enregistre un réglage (settings.set) : toast « Enregistré. », ou l'erreur dans le formulaire
// (sous le champ), jamais de fenêtre bloquante. Renvoie vrai si c'est enregistré.
export async function saveSetting(api, path, value, errorBox, input = null) {
  if (errorBox) errorBox.textContent = "";
  try {
    await api.call("settings.set", { path, value });
  } catch (e) {
    input?.classList.add("invalid");
    if (errorBox) errorBox.textContent = e.message; else toast(e.message, { kind: "error" });
    return false;
  }
  input?.classList.remove("invalid");
  toast("Enregistré.", { kind: "success" });
  return true;
}

// Ligne de réglage : libellé + champ selon `type` (bool, number, time, text, ou liste de [valeur, texte]),
// enregistrée à chaque changement ; l'erreur s'affiche sous le champ.
export function settingRow(api, s, { path, label, type, hint = "", min, max, step }) {
  const get = (o, p) => p.split(".").reduce((x, k) => (x ? x[k] : undefined), o);
  const value = get(s, path);
  const error = el("p", { class: "form-error", role: "alert" });
  let input;
  if (type === "bool") {
    input = el("input", { type: "checkbox" });
    input.checked = Boolean(value);
    input.addEventListener("change", async () => {
      if (!await saveSetting(api, path, input.checked, error, input)) input.checked = !input.checked;
    });
    return el("div", {}, el("label", { class: "check" }, input, label), hint ? el("div", { class: "subtle" }, hint) : null, error);
  }
  if (Array.isArray(type)) {
    input = el("select", {}, ...type.map(([v, text]) => el("option", { value: v }, text)));
    input.value = value;
  } else if (type === "number") {
    input = el("input", { type: "number", inputmode: "decimal", value: value ?? "", min, max, step: step ?? "any" });
  } else if (type === "time") {
    input = el("input", { type: "time", value: value ?? "" });
  } else {
    input = el("input", { type: "text", value: value ?? "", autocapitalize: "off", autocomplete: "off" });
  }
  input.addEventListener("change", () => {
    if (type === "number") {
      if (input.value.trim() === "" || Number.isNaN(Number(input.value))) {
        input.classList.add("invalid");
        error.textContent = "Entre un nombre.";
        return;
      }
      saveSetting(api, path, Number(input.value), error, input);
    } else {
      saveSetting(api, path, input.value, error, input);
    }
  });
  return el("div", {}, field(label, input, hint), error);
}
