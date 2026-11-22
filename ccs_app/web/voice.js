// Vocal : dictée (Web Speech API, reconnaissance du navigateur) et lecture à voix haute des
// réponses de Claude (synthèse du système). Rien ne passe par CCS : le navigateur s'en charge.
// Navigateur sans reconnaissance (Firefox) : pas de bouton micro ; sans synthèse : pas de « Lire ».

const READ_KEY = "ccs-voice-read";
const LANG = "fr-FR";

const Recognition = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition || null;
const synth = globalThis.speechSynthesis || null;

export const canDictate = () => Boolean(Recognition);
export const canSpeak = () => Boolean(synth && globalThis.SpeechSynthesisUtterance);

// Réglage « Lire les réponses à voix haute » : gardé dans ce navigateur, désactivé par défaut.
export function autoRead() {
  try { return localStorage.getItem(READ_KEY) === "1"; } catch { return false; }
}
export function setAutoRead(on) {
  try { if (on) localStorage.setItem(READ_KEY, "1"); else localStorage.removeItem(READ_KEY); } catch { /* sans stockage */ }
}

// Texte à lire d'une réponse en Markdown : sans le code, les marques ni les adresses des liens.
export function speechText(markdown) {
  return String(markdown || "")
    .replace(/```[\s\S]*?(```|$)/g, " bloc de code. ")
    .replace(/`([^`\n]*)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "lien")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\|?[\s:|-]+\|[\s:|-]*$/gm, "")
    .replace(/\|/g, ", ")
    .replace(/(\*\*|__|\*|_|~~)(?=\S)([\s\S]*?\S)\1/g, "$2")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

// ── Lecture ────────────────────────────────────────────────────────────────────────────────
let reading = null;              // { key, onEnd } de la lecture en cours

function frenchVoice() {
  const voices = synth.getVoices?.() || [];
  return voices.find((v) => v.lang === LANG && v.localService) || voices.find((v) => v.lang?.startsWith("fr")) || null;
}

export function stopSpeaking() {
  if (!canSpeak()) return;
  const r = reading;
  reading = null;
  synth.cancel();
  r?.onEnd?.();
}

export const speakingKey = () => reading?.key ?? null;

// Lit `markdown` ; `key` repère ce qui est lu (le même bouton arrête), `onEnd` à la fin ou à l'arrêt.
export function speak(markdown, { key = null, onEnd = null } = {}) {
  if (!canSpeak()) return false;
  stopSpeaking();
  const text = speechText(markdown);
  if (!text) return false;
  const me = { key, onEnd };
  reading = me;
  // Les longs textes sont coupés en phrases : certaines synthèses s'arrêtent seules après ~15 s.
  const parts = text.match(/[^.!?\n]+[.!?]*|\n/g)?.map((p) => p.trim()).filter(Boolean) || [text];
  const voice = frenchVoice();
  parts.forEach((p, i) => {
    const u = new SpeechSynthesisUtterance(p);
    u.lang = LANG;
    if (voice) u.voice = voice;
    if (i === parts.length - 1) u.onend = u.onerror = () => { if (reading === me) { reading = null; onEnd?.(); } };
    synth.speak(u);
  });
  return true;
}

// Safari (iPhone) ne lit qu'après un geste de l'utilisateur : une phrase vide au moment d'envoyer
// débloque la lecture automatique de la réponse qui viendra plus tard.
export function unlockSpeech() {
  if (!canSpeak() || reading) return;
  try { const u = new SpeechSynthesisUtterance(""); u.volume = 0; synth.speak(u); } catch { /* rien */ }
}

// ── Dictée ─────────────────────────────────────────────────────────────────────────────────
// `onText(texte)` : ce qui est reconnu jusqu'ici (partiel puis final) ; `onEnd(erreur|null)`.
// Rend une fonction qui arrête la dictée.
export function dictate({ onText, onEnd }) {
  if (!Recognition) { onEnd?.("unsupported"); return () => {}; }
  const rec = new Recognition();
  rec.lang = LANG;
  rec.interimResults = true;
  rec.continuous = true;
  let failure = null;
  rec.onresult = (e) => {
    let text = "";
    for (const r of e.results) text += r[0].transcript;
    onText?.(text.trim());
  };
  rec.onerror = (e) => { if (e.error !== "no-speech" && e.error !== "aborted") failure = e.error || "error"; };
  rec.onend = () => onEnd?.(failure);
  stopSpeaking();                // le micro n'entend pas la synthèse
  try { rec.start(); } catch { onEnd?.("busy"); return () => {}; }
  return () => { try { rec.stop(); } catch { /* déjà arrêtée */ } };
}

export function dictationError(code) {
  if (code === "not-allowed" || code === "service-not-allowed") return "Micro refusé : autorise-le pour ce site dans le navigateur.";
  if (code === "audio-capture") return "Aucun micro trouvé.";
  if (code === "network") return "La reconnaissance vocale du navigateur n'est pas joignable.";
  if (code === "unsupported") return "Ce navigateur ne sait pas dicter (essaie Chrome, Edge ou Safari).";
  return "La dictée s'est arrêtée.";
}
