// Oreille « bouton » de Jarvis (assistant vocal, projet voisin) : parle au cerveau par le relais
// de CCS (`/api/jarvis/oreille`, session CCS exigée), qui ouvre le tunnel Ricochet vers la machine
// du cerveau et y fait le TLS épinglé. Les messages sont ceux du protocole des oreilles
// (crates/jarvis-protocol) : `pair` / `hello`, puis `wake`, trames de son, `listen_end`.
// Le son du micro part en PCM mono 16 kHz i16 (trames `0x01` + phrase u32 + échantillons LE).
// L'appairage (identifiant d'oreille, jeton, empreinte du cerveau) est gardé dans ce navigateur.

const STORE_KEY = "ccs.jarvis";
export const RATE = 16000;
export const MAX_FRAME_SAMPLES = 16000;
export const MAX_PHRASE_S = 14;
const FRAME_SAMPLES = 1600;               // une trame toutes les 100 ms
const IDLE_CLOSE_MS = 120000;             // lien fermé après 2 min sans phrase
const SILENCE_STOP_MS = 1200;             // mode « appui court » : fin après ce silence
const SPEECH_RMS = 0.02;                  // au-dessus : on parle
const RELAY_DOWN = 4011;

// ── Appairage ─────────────────────────────────────────────────────────────────────────────────

// jarvis://pair?v=1&id=…&h=…&p=7341&fp=…&c=482913 (crates/jarvis-protocol/src/pairing_uri.rs)
export function parsePairingUri(text) {
  const s = String(text || "").trim();
  const prefix = "jarvis://pair?";
  if (!s.startsWith(prefix)) throw new Error("Ce n'est pas une adresse d'appairage Jarvis (jarvis://pair?…).");
  const params = new Map();
  for (const kv of s.slice(prefix.length).split("&")) {
    const i = kv.indexOf("=");
    if (i < 0 || params.has(kv.slice(0, i))) throw new Error("Adresse d'appairage mal formée.");
    params.set(kv.slice(0, i), kv.slice(i + 1));
  }
  if (params.get("v") !== "1") throw new Error("Version d'appairage inconnue : mets Jarvis à jour.");
  const fingerprint = params.get("fp") || "";
  const code = params.get("c") || "";
  if (!validFingerprint(fingerprint)) throw new Error("Empreinte du cerveau invalide dans l'adresse.");
  if (!validCode(code)) throw new Error("Code d'appairage invalide dans l'adresse.");
  return { brainId: params.get("id") || "", port: Number(params.get("p")) || 0, fingerprint, code };
}

export const validFingerprint = (fp) => /^[A-Za-z0-9_-]{43}$/.test(String(fp || ""));
export const validCode = (c) => /^\d{6}$/.test(String(c || ""));

export function loadPairing() {
  try {
    const p = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
    return p && p.earId && p.token && validFingerprint(p.fingerprint) ? p : null;
  } catch { return null; }
}

function savePairing(p) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(p)); } catch { /* navigation privée */ }
}

export function forgetPairing() {
  try { localStorage.removeItem(STORE_KEY); } catch { /* navigation privée */ }
}

// ── Son ───────────────────────────────────────────────────────────────────────────────────────

// Rééchantillonnage vers 16 kHz par moyenne glissante (filtre suffisant pour la voix) ; l'état
// est gardé d'un morceau à l'autre.
export class Resampler {
  constructor(inRate) {
    this.step = inRate / RATE;
    this.pos = 0;             // position du prochain échantillon de sortie, dans l'entrée courante
    this.acc = 0;
    this.n = 0;
  }

  push(input) {
    const out = [];
    for (let i = 0; i < input.length; i++) {
      this.acc += input[i];
      this.n += 1;
      if (i + 1 >= this.pos + this.step) {
        const v = Math.max(-1, Math.min(1, this.acc / this.n));
        out.push(v < 0 ? Math.round(v * 32768) : Math.round(v * 32767));
        this.acc = 0;
        this.n = 0;
        this.pos += this.step;
      }
    }
    this.pos -= input.length;
    return Int16Array.from(out);
  }
}

export function micFrame(utterance, samples) {
  const buf = new ArrayBuffer(5 + 2 * samples.length);
  const view = new DataView(buf);
  view.setUint8(0, 1);
  view.setUint32(1, utterance >>> 0, true);
  for (let i = 0; i < samples.length; i++) view.setInt16(5 + 2 * i, samples[i], true);
  return buf;
}

export function decodePcm(b64) {
  const bin = atob(String(b64 || ""));
  const out = new Int16Array(bin.length >> 1);
  for (let i = 0; i < out.length; i++) {
    const v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
    out[i] = v >= 0x8000 ? v - 0x10000 : v;
  }
  return out;
}

const rms = (chunk) => {
  let s = 0;
  for (const x of chunk) s += x * x;
  return chunk.length ? Math.sqrt(s / chunk.length) : 0;
};

// ── Lien avec le relais ───────────────────────────────────────────────────────────────────────

function relayUrl(fingerprint) {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/jarvis/oreille`
    + `?fp=${encodeURIComponent(fingerprint)}`;
}

const REJECTIONS = {
  unknown_ear: "Cet appareil n'est plus appairé (retiré par « jarvis unpair » ?). Refais l'appairage.",
  bad_token: "Jeton refusé par Jarvis : refais l'appairage.",
  version: "Version du protocole refusée : mets CCS ou Jarvis à jour.",
  pairing_closed: "Pas de fenêtre d'appairage ouverte : lance « jarvis pair » sur la machine de Jarvis.",
  wrong_code: "Code d'appairage faux.",
};

export function rejectionText(reason) {
  const kind = reason?.kind || "";
  let text = REJECTIONS[kind] || "Jarvis a refusé la connexion.";
  if (kind === "wrong_code" && Number.isInteger(reason.attempts_left)) text += ` Essais restants : ${reason.attempts_left}.`;
  return text;
}

// Ouvre un WebSocket vers le relais et y envoie `first` ; résout au premier message du cerveau
// qui répond (`welcome`, `paired`), rejette sur `rejected`, `relay_error` ou fermeture.
function openRelay(fingerprint, first, onMessage) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(relayUrl(fingerprint));
    ws.binaryType = "arraybuffer";
    let settled = false;
    const done = (fn, v) => { if (!settled) { settled = true; fn(v); } };
    ws.onopen = () => ws.send(JSON.stringify(first));
    ws.onmessage = (e) => {
      if (typeof e.data !== "string") return;
      let m;
      try { m = JSON.parse(e.data); } catch { return; }
      if (m.type === "relay_error") { done(reject, Object.assign(new Error(m.message), { relay: true })); return; }
      if (m.type === "rejected") {
        done(reject, Object.assign(new Error(rejectionText(m.reason)), { rejected: m.reason?.kind || "?" }));
        return;
      }
      if (!settled && (m.type === "welcome" || m.type === "paired")) { done(resolve, { ws, first: m }); return; }
      onMessage?.(m);
    };
    ws.onclose = (e) => {
      const why = e.code === RELAY_DOWN && e.reason ? e.reason : "Connexion au relais de Jarvis perdue.";
      done(reject, new Error(why));
    };
  });
}

// Appairage : `pair` avec le code donné par `jarvis pair` ; le cerveau répond `paired` puis ferme.
export async function pair({ code, fingerprint, name }) {
  const { ws, first } = await openRelay(fingerprint, {
    type: "pair", version: 1, code, name: String(name || "web").slice(0, 60), platform: "web",
  });
  try { ws.close(); } catch { /* déjà fermé */ }
  if (first.type !== "paired") throw new Error("Réponse inattendue de Jarvis.");
  const p = { earId: first.ear_id, token: first.token, fingerprint, brainName: first.brain_name || "Jarvis",
    brainId: first.brain_id || "" };
  savePairing(p);
  return p;
}

// Oreille appairée : un lien gardé ouvert tant qu'on s'en sert, une phrase à la fois.
// Événements (`on`) : state(texte d'état), heard({text, speech}), error(message), closed().
export class Ear {
  constructor(pairing, { audioContext = null } = {}) {
    this.pairing = pairing;
    this.ws = null;
    this.connecting = null;
    this.handlers = {};
    this.utterance = (Math.random() * 0x7fffffff) >>> 0;
    this.capture = null;
    this.idle = null;
    this.ctx = audioContext;
    this.player = null;
  }

  on(name, fn) { this.handlers[name] = fn; return this; }
  emit(name, data) { try { this.handlers[name]?.(data); } catch (e) { console.error(name, e); } }

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return Promise.resolve(this.ws);
    if (this.connecting) return this.connecting;
    const p = this.pairing;
    this.connecting = openRelay(p.fingerprint, { type: "hello", version: 1, ear_id: p.earId, token: p.token },
      (m) => this.received(m))
      .then(({ ws, first }) => {
        this.ws = ws;
        if (first.brain_name) this.pairing.brainName = first.brain_name;
        ws.onclose = () => { this.ws = null; this.abortCapture(); this.emit("closed"); };
        return ws;
      })
      .finally(() => { this.connecting = null; });
    return this.connecting;
  }

  send(data) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(data);
  }

  armIdle() {
    clearTimeout(this.idle);
    this.idle = setTimeout(() => { if (!this.capture) this.ws?.close(); }, IDLE_CLOSE_MS);
  }

  received(m) {
    const c = this.capture;
    if (m.type === "relay_error") {
      this.abortCapture();
      this.emit("error", m.message || "Lien avec Jarvis rompu.");
    } else if (m.type === "stop" && c && m.utterance === c.utterance) {
      this.abortCapture();
      this.emit("error", "Une autre oreille a pris la phrase.");
    } else if (m.type === "response" && m.response) {
      this.armIdle();
      const r = m.response;
      if (r.type === "heard") {
        this.emit("heard", { text: r.text || "", speech: r.speech || "" });
        this.play(r.audio, r.ear_action === "await_reply");
      } else if (r.type === "error") {
        this.emit("error", r.message || "Erreur de Jarvis.");
      } else if (r.type === "reply") {
        this.emit("heard", { text: "", speech: r.speech || "" });
      }
      this.emit("state", "");
    }
  }

  audioContext() {
    if (!this.ctx) this.ctx = new (globalThis.AudioContext || globalThis.webkitAudioContext)();
    if (this.ctx.state === "suspended") this.ctx.resume().catch(() => {});
    return this.ctx;
  }

  // Voix de Jarvis : PCM i16 mono à `sample_rate` ; `thenListen` : Jarvis attend un oui / non.
  play(audio, thenListen = false) {
    this.stopPlaying();
    if (!audio?.pcm) { if (thenListen) this.start({ followUp: true, auto: true }); return; }
    const pcm = decodePcm(audio.pcm);
    if (!pcm.length) return;
    const ctx = this.audioContext();
    const buf = ctx.createBuffer(1, pcm.length, audio.sample_rate || 22050);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    src.onended = () => {
      if (this.player === src) this.player = null;
      if (thenListen) this.start({ followUp: true, auto: true });
    };
    this.player = src;
    src.start();
  }

  stopPlaying() {
    const p = this.player;
    this.player = null;
    if (p) { p.onended = null; try { p.stop(); } catch { /* déjà fini */ } }
  }

  // Début d'une phrase : le micro tourne tout de suite, le son attend le lien (tunnel) dans
  // `pending`. `auto` : fin au silence (appui court, réponse attendue) ; sinon au relâché.
  async start({ auto = false, followUp = false } = {}) {
    if (this.capture) return;
    this.stopPlaying();
    const utterance = this.utterance = (this.utterance + 1) >>> 0;
    const c = { utterance, auto, followUp, pending: [], sent: 0, total: 0, spoke: false, lastVoice: Date.now(),
      buffer: [], stream: null, node: null, source: null, ready: false, ended: false };
    this.capture = c;
    this.emit("state", "Écoute…");
    try {
      const ctx = this.audioContext();
      c.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (this.capture !== c) { c.stream.getTracks().forEach((t) => t.stop()); return; }
      if (!ctx.audioWorklet) throw new Error("Ce navigateur ne sait pas lire le micro (AudioWorklet).");
      await ctx.audioWorklet.addModule("/jarvis-worklet.js");
      const resampler = new Resampler(ctx.sampleRate);
      c.source = ctx.createMediaStreamSource(c.stream);
      c.node = new AudioWorkletNode(ctx, "jarvis-capture");
      c.node.port.onmessage = (e) => this.chunk(c, e.data, resampler);
      c.source.connect(c.node);
    } catch (e) {
      this.abortCapture();
      this.emit("error", e?.name === "NotAllowedError" ? "Micro refusé : autorise-le pour ce site." : (e.message || String(e)));
      return;
    }
    try {
      await this.connect();
    } catch (e) {
      this.abortCapture();
      if (e.rejected === "unknown_ear" || e.rejected === "bad_token") this.emit("unpaired");
      this.emit("error", e.message);
      return;
    }
    if (this.capture !== c) return;
    clearTimeout(this.idle);
    this.send(JSON.stringify(followUp ? { type: "listen_start", utterance }
      : { type: "wake", utterance, score: 2.0, level_db: 0, muted: false }));
    c.ready = true;
    this.flush(c, true);
    if (c.ended) this.finish(c);
  }

  chunk(c, floats, resampler) {
    if (this.capture !== c || c.ended) return;
    const loud = rms(floats) > SPEECH_RMS;
    if (loud) { c.spoke = true; c.lastVoice = Date.now(); }
    const samples = resampler.push(floats);
    c.total += samples.length;
    for (const s of samples) c.buffer.push(s);
    this.flush(c, false);
    if (c.total >= MAX_PHRASE_S * RATE) this.stop();
    else if (c.auto && c.spoke && Date.now() - c.lastVoice > SILENCE_STOP_MS) this.stop();
    else if (c.auto && !c.spoke && c.total > 6 * RATE) this.stop();
  }

  flush(c, all) {
    if (!c.ready) return;
    while (c.buffer.length >= FRAME_SAMPLES || (all && c.buffer.length)) {
      const part = c.buffer.splice(0, Math.min(MAX_FRAME_SAMPLES, all ? c.buffer.length : FRAME_SAMPLES));
      this.send(micFrame(c.utterance, part));
      c.sent += part.length;
    }
  }

  // Fin de la phrase (bouton relâché, silence ou 14 s) : `listen_end`.
  stop() {
    const c = this.capture;
    if (!c || c.ended) return;
    c.ended = true;
    this.releaseMic(c);
    if (c.ready) this.finish(c);
    else this.emit("state", "Connexion à Jarvis…");
  }

  finish(c) {
    this.flush(c, true);
    const noSpeech = !c.spoke || c.total < 0.3 * RATE;
    this.send(JSON.stringify({ type: "listen_end", utterance: c.utterance, muted: false, no_speech: noSpeech }));
    if (this.capture === c) this.capture = null;
    this.emit("state", noSpeech ? "" : "Jarvis réfléchit…");
    if (noSpeech) this.emit("error", "Rien entendu.");
    this.armIdle();
  }

  releaseMic(c) {
    try { c.source?.disconnect(); c.node?.disconnect(); } catch { /* déjà débranché */ }
    if (c.node) c.node.port.onmessage = null;
    c.stream?.getTracks().forEach((t) => t.stop());
  }

  abortCapture() {
    const c = this.capture;
    if (!c) return;
    this.capture = null;
    this.releaseMic(c);
    if (c.ready && !c.ended) {
      this.send(JSON.stringify({ type: "listen_end", utterance: c.utterance, muted: false, no_speech: true }));
    }
    this.emit("state", "");
  }

  get listening() { return Boolean(this.capture && !this.capture.ended); }

  close() {
    clearTimeout(this.idle);
    this.abortCapture();
    this.stopPlaying();
    const ws = this.ws;
    this.ws = null;
    if (ws) { ws.onclose = null; ws.close(); }
    this.ctx?.close?.().catch(() => {});
    this.ctx = null;
  }
}
