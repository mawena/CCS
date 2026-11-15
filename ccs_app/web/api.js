// Connexion au pont par le WebSocket de ccs-web : appels (promesses), événements poussés,
// reconnexion automatique (1 s, 2 s, 4 s… jusqu'à 30000 ms) et signal « reconnected » pour que
// chaque écran se rattache (les chats rejouent ce qu'ils ont manqué).

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
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => {
      this.delay = 1000;
      const again = this.everOpen;
      this.everOpen = true;
      this.emit("online");
      if (again) this.emit("reconnected");
      for (const msg of this.queue.splice(0)) ws.send(msg);
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
    ws.onclose = () => {
      for (const p of this.pending.values()) p.reject(Object.assign(new Error("Connexion perdue."), { code: "hors_ligne" }));
      this.pending.clear();
      if (this.stopped) return;
      this.emit("offline");
      this.reconnect();
    };
  }

  async reconnect() {
    const wait = this.delay;
    this.delay = Math.min(this.delay * 2, 30000);
    await new Promise((r) => setTimeout(r, wait));
    if (this.stopped) return;
    if (!(await session().catch(() => ({ offline: true })))) { this.emit("logged-out"); return; }
    this.connect();
  }

  call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      const msg = JSON.stringify({ id, method, params });
      this.pending.set(id, { resolve, reject });
      if (this.online) this.ws.send(msg);
      else if (this.queue.length < 100) this.queue.push(msg);
      else { this.pending.delete(id); reject(new Error("Trop de demandes en attente.")); }
    });
  }

  close() {
    this.stopped = true;
    this.ws?.close();
  }
}
