// Installer CCS comme une application, comme le propose Outlook :
// - Chrome sur Android ou ordinateur : bouton « Installer » (événement beforeinstallprompt) ;
// - iPhone / iPad (Safari ou Chrome, iOS 16.4+) : pas d'installation automatique possible, on
//   montre la marche à suivre : Partager, puis « Sur l'écran d'accueil ».
// Jamais une fois l'app installée ; « Plus tard » la cache 30 jours.
import { el } from "./dom.js";

const LATER_KEY = "ccs-install-later";
const LATER_DAYS = 30;
let deferred = null;                                  // invite d'installation de Chrome, gardée
const listeners = new Set();

export const isIos = () => /iPhone|iPad|iPod/.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);   // iPad en mode « ordinateur »
export const installed = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
export const canInstall = () => !installed() && (Boolean(deferred) || isIos());

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();                                 // on propose nous-mêmes, au bon moment
  deferred = e;
  for (const f of listeners) f();
});
window.addEventListener("appinstalled", () => { deferred = null; document.querySelector(".install-banner")?.remove(); });

function iosSteps() {
  const chrome = /CriOS/.test(navigator.userAgent);
  return el("ol", { class: "install-steps" },
    el("li", {}, chrome
      ? "Touche le bouton Partager ⬆ en haut à droite, dans la barre d'adresse (ou ⋯ puis Partager)."
      : "Touche le bouton Partager ⬆ en bas de l'écran."),
    el("li", {}, "Choisis « Sur l'écran d'accueil » (fais défiler la liste si besoin)."),
    el("li", {}, "Touche « Ajouter » : CCS s'ouvre ensuite en plein écran, comme une application."));
}

// Lance l'installation (Chrome) ou renvoie la marche à suivre (iPhone) : pour le bouton des Réglages.
export async function install() {
  if (deferred) {
    const prompt = deferred;
    deferred = null;
    prompt.prompt();
    const { outcome } = await prompt.userChoice;
    return outcome === "accepted";
  }
  return false;
}

export function installSteps() { return isIos() ? iosSteps() : null; }

function later() {
  try { localStorage.setItem(LATER_KEY, String(Date.now())); } catch { /* navigation privée */ }
}

function snoozed() {
  const t = Number(localStorage.getItem(LATER_KEY) || 0);
  return t && Date.now() - t < LATER_DAYS * 86400e3;
}

// Bandeau discret en bas de l'écran, une fois connecté.
export function offerInstall() {
  const show = () => {
    if (!canInstall() || snoozed() || document.querySelector(".install-banner")) return;
    const close = () => banner.remove();
    const banner = el("aside", { class: "install-banner card", role: "dialog", "aria-label": "Installer CCS" },
      el("img", { src: "/icons/ccs-192.png", alt: "", width: 40, height: 40 }),
      el("div", { class: "install-text" },
        el("strong", {}, "Installer CCS"),
        el("span", { class: "subtle" }, "Une icône sur ton écran d'accueil, en plein écran, sans barre du navigateur.")),
      el("div", { class: "install-actions" },
        el("button", { type: "button", class: "flat small", onclick: () => { later(); close(); } }, "Plus tard"),
        el("button", { type: "button", class: "primary small", onclick: async () => {
          if (deferred) { close(); await install(); return; }
          banner.querySelector(".install-steps") || banner.querySelector(".install-text").append(iosSteps());
        } }, isIos() && !deferred ? "Comment ?" : "Installer")));
    document.body.append(banner);
  };
  listeners.add(show);
  setTimeout(show, 1500);                             // laisser la page s'afficher d'abord
}
