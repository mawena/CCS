// Page « Jarvis » (#/jarvis) : parler à Jarvis, l'assistant vocal de la maison, depuis n'importe où.
// Appairage une fois par navigateur (adresse jarvis://pair?… donnée par « jarvis pair » sur la
// machine du cerveau, ou code + empreinte), puis un bouton : maintenir pour parler (fin au
// relâché), ou appui court (fin au silence). Le texte de la réponse s'affiche et la voix de
// Jarvis est jouée. Machine et port du cerveau : réglages du serveur (`jarvis.settings`), jamais
// ceux d'une machine pilotée.
import { clear, confirmSheet, el, toast } from "./dom.js";
import { Ear, forgetPairing, loadPairing, pair, parsePairingUri, validCode, validFingerprint } from "./jarvis-ear.js";
import { busy, field } from "./pages-util.js";

const HOLD_MS = 400;                      // appui plus long : on parle tant que le bouton est tenu
const HISTORY = 20;

function defaultName() {
  const ua = navigator.userAgent || "";
  const what = /iPhone/.test(ua) ? "iPhone" : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "Mac"
    : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "appareil";
  return `CCS web (${what})`;
}

function settingsCard(api) {
  const box = el("details", { class: "card flat jarvis-settings" }, el("summary", {}, "Où est le cerveau de Jarvis ?"));
  const machine = el("input", { autocapitalize: "none", spellcheck: "false", maxlength: "64" });
  const port = el("input", { type: "number", min: "1", max: "65535", inputmode: "numeric" });
  const info = el("p", { class: "subtle" });
  const error = el("p", { class: "form-error", role: "alert" });
  const save = el("button", { type: "submit" }, "Enregistrer");
  const show = (r) => {
    machine.value = r.machine;
    port.value = r.port;
    info.textContent = r.fingerprint_short ? `Empreinte enregistrée sur le serveur : ${r.fingerprint_short}`
      : "Aucune empreinte enregistrée sur le serveur.";
  };
  const form = el("form", { class: "stack" },
    field("Machine (relais Ricochet)", machine, "Le tunnel Ricochet de cette machine doit laisser passer ce port."),
    field("Port", port), info, error, el("div", { class: "row" }, save));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    error.textContent = "";
    busy(save, async () => {
      try {
        show(await api.call("jarvis.configure", { machine: machine.value.trim(), port: Number(port.value) }));
        toast("Enregistré.", { kind: "success" });
      } catch (err) { error.textContent = err.message; }
    });
  });
  box.append(form);
  api.call("jarvis.settings").then(show).catch((e) => { error.textContent = e.message; });
  return box;
}

function pairingCard(onPaired) {
  const uri = el("input", { placeholder: "jarvis://pair?v=1&…", autocapitalize: "none", spellcheck: "false", autocomplete: "off" });
  const code = el("input", { inputmode: "numeric", maxlength: "6", pattern: "[0-9]{6}", autocomplete: "off" });
  const fp = el("input", { autocapitalize: "none", spellcheck: "false", maxlength: "43", autocomplete: "off" });
  const name = el("input", { maxlength: "60", value: defaultName() });
  const error = el("p", { class: "form-error", role: "alert" });
  const submit = el("button", { type: "submit", class: "primary" }, "Appairer");
  const manual = el("details", {}, el("summary", {}, "Saisir le code et l'empreinte à la main"),
    el("div", { class: "stack" }, field("Code à 6 chiffres", code), field("Empreinte du cerveau", fp,
      "43 caractères, dans l'adresse après « fp= »")));
  const form = el("form", { class: "card flat stack" },
    el("h2", {}, "Appairer ce navigateur"),
    el("p", { class: "subtle" }, "Sur la machine de Jarvis, lance « jarvis pair », puis colle ici l'adresse affichée "
      + "sous le QR code (valable quelques minutes)."),
    field("Adresse d'appairage", uri), manual, field("Nom de cet appareil", name, "Affiché par « jarvis ears »."),
    error, el("div", { class: "row" }, submit));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    error.textContent = "";
    let target;
    try {
      if (uri.value.trim()) {
        const u = parsePairingUri(uri.value);
        target = { code: u.code, fingerprint: u.fingerprint };
      } else {
        if (!validCode(code.value.trim())) throw new Error("Code d'appairage : 6 chiffres.");
        if (!validFingerprint(fp.value.trim())) throw new Error("Empreinte invalide : 43 caractères (lettres, chiffres, - et _).");
        target = { code: code.value.trim(), fingerprint: fp.value.trim() };
      }
    } catch (err) { error.textContent = err.message; return; }
    busy(submit, async () => {
      submit.textContent = "Appairage…";
      try {
        const p = await pair({ ...target, name: name.value.trim() || defaultName() });
        toast(`Appairé avec ${p.brainName}.`, { kind: "success" });
        onPaired(p);
      } catch (err) {
        error.textContent = err.message;
      } finally { submit.textContent = "Appairer"; }
    });
  });
  return form;
}

function talkCard(pairing, onForget) {
  const ear = new Ear(pairing);
  const state = el("p", { class: "jarvis-state subtle", role: "status", "aria-live": "polite" }, "Prêt.");
  const button = el("button", { type: "button", class: "jarvis-talk", "aria-label": "Parler à Jarvis" },
    el("span", { class: "jarvis-mic", "aria-hidden": "true" }, "🎙"), el("span", {}, "Parler à Jarvis"));
  const log = el("div", { class: "jarvis-log", "aria-live": "polite" });
  const forget = el("button", { type: "button", class: "small flat" }, "Oublier l'appairage");
  let pressedAt = 0;

  const setState = (text) => {
    state.textContent = text || (ear.listening ? "Écoute…" : "Prêt.");
    button.classList.toggle("listening", ear.listening);
    button.setAttribute("aria-pressed", ear.listening ? "true" : "false");
  };
  const add = (who, text, kind = "") => {
    if (!text) return;
    log.prepend(el("div", { class: `jarvis-line ${kind}` }, el("strong", {}, who), " ", text));
    while (log.children.length > HISTORY) log.lastChild.remove();
  };
  ear.on("state", setState)
    .on("heard", ({ text, speech }) => { add("Toi :", text, "me"); add(`${ear.pairing.brainName || "Jarvis"} :`, speech, "jarvis"); })
    .on("error", (m) => { add("", m, "err-text"); setState(""); })
    .on("unpaired", () => { forgetPairing(); onForget(); })
    .on("closed", () => setState(""));

  // Appui long : parler tant que le bouton est tenu ; appui court : fin au silence ; second appui : fin.
  const down = (e) => {
    e.preventDefault();
    if (ear.listening) { ear.stop(); return; }
    pressedAt = Date.now();
    try { button.setPointerCapture?.(e.pointerId); } catch { /* sans capture */ }
    ear.start({ auto: false });
  };
  const up = () => {
    if (!pressedAt) return;
    const held = Date.now() - pressedAt;
    pressedAt = 0;
    if (!ear.listening) return;
    if (held >= HOLD_MS) ear.stop();
    else if (ear.capture) { ear.capture.auto = true; setState("Écoute… (fin au silence, ou touche encore)"); }
  };
  button.addEventListener("pointerdown", down);
  button.addEventListener("pointerup", up);
  button.addEventListener("pointercancel", up);
  button.addEventListener("contextmenu", (e) => e.preventDefault());
  button.addEventListener("keydown", (e) => {
    if (e.repeat || (e.key !== " " && e.key !== "Enter")) return;
    e.preventDefault();
    if (ear.listening) ear.stop(); else ear.start({ auto: true });
  });
  forget.addEventListener("click", async () => {
    if (!await confirmSheet({ title: "Oublier l'appairage ?", body: "Ce navigateur ne pourra plus parler à Jarvis "
      + "sans un nouvel appairage. Pour le retirer aussi côté Jarvis : « jarvis unpair <nom> ».", confirm: "Oublier", danger: true })) return;
    ear.close();
    forgetPairing();
    onForget();
  });

  const card = el("section", { class: "card flat jarvis-card" },
    el("div", { class: "page-head" }, el("h2", {}, pairing.brainName || "Jarvis"), forget),
    el("div", { class: "jarvis-center" }, button, state),
    el("p", { class: "subtle" }, "Maintiens le bouton pendant que tu parles, ou touche-le une fois : "
      + "l'écoute s'arrête quand tu te tais."),
    log);
  return { card, close: () => ear.close() };
}

export function mountJarvis(root, api) {
  const wrap = el("div", { class: "settings-wrap jarvis-page" });
  const main = el("div", { class: "stack" });
  if (!navigator.mediaDevices?.getUserMedia || !globalThis.isSecureContext) {
    wrap.append(el("p", { class: "form-error" }, "Le micro n'est disponible que sur une page sécurisée (https)."));
  }
  wrap.append(main, settingsCard(api));
  root.append(wrap);
  let current = null;

  function show() {
    current?.close?.();
    current = null;
    clear(main);
    const pairing = loadPairing();
    if (!pairing) { main.append(pairingCard(show)); return; }
    current = talkCard(pairing, show);
    main.append(current.card);
  }
  show();
  return () => current?.close?.();
}
