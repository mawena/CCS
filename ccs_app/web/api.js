// Connexion au pont par le WebSocket de ccs-web : appels (promesses), événements poussés,
// reconnexion automatique (1 s, 2 s, 4 s… jusqu'à 30000 ms) et signal « reconnected » pour que
// chaque écran se rattache (les chats rejouent ce qu'ils ont manqué).
// `machine` : la connexion passe par le pont du serveur jusqu'au pont CCS d'une autre machine
// (tunnel Ricochet) ; vide, c'est ce serveur. Le choix est gardé dans le navigateur.

const MACHINE_KEY = "ccs.machine";
// version du protocole du pont (`hello` côté pont, `?protocol=` sur /api/ws)
export const PROTOCOL = 1;
export const MACHINE_DOWN = 4010;

export async function post(path, body = {}) {
  const r = await fetch(path, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (r.status === 503) return { status: "error", message: "Service de connexion indisponible." };
  try { return await r.json(); } catch { return { status: "error", message: `Erreur ${r.status}` }; }
}

export async function session() {
  const r = await fetch("/api/session", { credentials: "same-origin" });
  return r.ok ? r.json() : null;
}

export class Api {
  constructor() {
    this.ws = null;
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = new Map();
    this.queue = [];
    this.delay = 1000;
    this.stopped = false;
    this.everOpen = false;
    try { this.machine = localStorage.getItem(MACHINE_KEY) || ""; } catch { this.machine = ""; }
  }

  on(event, fn) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event).add(fn);
    return () => this.handlers.get(event)?.delete(fn);
  }

  emit(event, data) {
    for (const fn of [...(this.handlers.get(event) || [])]) {
      try { fn(data); } catch (e) { console.error(event, e); }
    }
  }

  get online() { return this.ws?.readyState === WebSocket.OPEN; }

  connect() {
    this.stopped = false;
    // `protocol` : version du protocole du pont que cette page connaît
    const query = `?protocol=${PROTOCOL}` + (this.machine ? `&machine=${encodeURIComponent(this.machine)}` : "");
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws${query}`;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => {
      this.delay = 1000;
      const again = this.everOpen;
      this.everOpen = true;
      this.emit("online");
      if (again) this.emit("reconnected");
      for (const { id, msg } of this.queue.splice(0)) {
        const p = this.pending.get(id);
        if (p) p.sent = true;
        ws.send(msg);
      }
    };
    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      if (msg.event) { this.emit(msg.event, msg.data || {}); return; }
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id);
      if (msg.error) p.reject(Object.assign(new Error(msg.error.message), { code: msg.error.code }));
      else p.resolve(msg.result || {});
    };
    ws.onclose = (e) => {
      // Seuls les appels vraiment envoyés sont rejetés (leur sort est inconnu) ; ceux qui attendent
      // encore dans la file partiront à la reconnexion : les rejeter ferait un doublon au « Réessayer ».
      for (const [id, p] of [...this.pending]) {
        if (!p.sent) continue;
        this.pending.delete(id);
        p.reject(Object.assign(new Error("Connexion perdue."), { code: "hors_ligne" }));
      }
      if (this.stopped) return;
      if (e?.code === MACHINE_DOWN) this.emit("machine-down", { machine: this.machine, reason: e.reason || "" });
      else this.emit("offline");
      this.reconnect();
    };
  }

  async reconnect() {
    const wait = this.delay, ws = this.ws;
    this.delay = Math.min(this.delay * 2, 30000);
    await new Promise((r) => setTimeout(r, wait));
    if (this.stopped || this.ws !== ws) return;     // arrêté, ou machine changée entre-temps
    if (!(await session().catch(() => ({ offline: true })))) { this.emit("logged-out"); return; }
    this.connect();
  }

  call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      const msg = JSON.stringify({ id, method, params });
      const online = this.online;
      this.pending.set(id, { resolve, reject, sent: online });
      if (online) this.ws.send(msg);
      else if (this.queue.length < 100) this.queue.push({ id, msg });
      else { this.pending.delete(id); reject(new Error("Trop de demandes en attente.")); }
    });
  }

  // Change de machine : les appels en cours appartiennent à l'ancienne, ils sont rejetés.
  setMachine(id) {
    this.machine = id || "";
    try {
      if (this.machine) localStorage.setItem(MACHINE_KEY, this.machine);
      else localStorage.removeItem(MACHINE_KEY);
    } catch { /* navigation privée */ }
    const old = this.ws;
    if (old) { old.onclose = null; old.onmessage = null; old.close(); }
    this.queue = [];
    for (const p of this.pending.values()) {
      p.reject(Object.assign(new Error("Machine changée."), { code: "hors_ligne" }));
    }
    this.pending.clear();
    this.everOpen = false;
    this.delay = 1000;
    this.emit("machine", this.machine);
    this.connect();
  }

  close() {
    this.stopped = true;
    this.ws?.close();
  }
}
