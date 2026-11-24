// Section « Son partagé » de l'onglet Réseau : appareils annoncés (sorties qui jouent, sources qui
// captent leur son), flux en cours avec Arrêter, et « Envoyer le son de … vers … » entre deux
// appareils quelconques. Le web ne joue ni ne capte rien lui-même : télécommande seulement.
// Méthodes `audio.*` (docs/audio.md), toujours sur ce serveur. Rechargement toutes les 5 s.
import { clear, el, toast } from "./dom.js";
import { busy } from "./pages-util.js";

const REFRESH_MS = 5_000;
const SYSTEMS = { linux: "PC Linux", macos: "Mac", windows: "PC Windows", android: "Android", ios: "iPhone", web: "Web", autre: "Appareil" };

export function abilities(d) {
  return [d.play && "joue", d.capture && "capte"].filter(Boolean).join(" · ") || "—";
}

// Sources et sorties possibles pour le formulaire (une source ne s'envoie pas à elle-même).
export function choices(devices) {
  return {
    sources: devices.filter((d) => d.capture),
    outputs: devices.filter((d) => d.play),
  };
}

export function labelOf(devices, name) {
  return (devices.find((d) => d.device === name) || {}).label || name;
}

export function createSon(api, icon) {
  const box = el("div", { class: "son-box" });
  let data = { devices: [], streams: [] };
  let timer = null;
  let alive = true;
  const srcSel = el("select", { "aria-label": "Source" });
  const dstSel = el("select", { "aria-label": "Sortie" });
  const send = el("button", { type: "button", class: "small net-btn" }, icon("play", 14), "Envoyer");
  send.addEventListener("click", () => busy(send, async () => {
    if (!srcSel.value || !dstSel.value) return;
    try {
      await api.call("audio.send", { source: srcSel.value, target: dstSel.value });
      toast(`Son de ${labelOf(data.devices, srcSel.value)} → ${labelOf(data.devices, dstSel.value)}.`, { kind: "success" });
      refresh();
    } catch (e) { toast(e.message, { kind: "error" }); }
  }));

  function fill(sel, list, keep) {
    clear(sel).append(...list.map((d) => el("option", { value: d.device }, d.label)));
    if (list.some((d) => d.device === keep)) sel.value = keep;
  }

  function render() {
    clear(box);
    const devices = data.devices || [];
    const streams = data.streams || [];
    if (!devices.length) {
      box.append(el("p", { class: "subtle" },
        "Aucun appareil annoncé. Ouvre CCS sur le téléphone (écran Son), ou lance `ccs audio enable` sur un PC Linux."));
      return;
    }
    box.append(el("ul", { class: "son-list" }, ...devices.map((d) =>
      el("li", { class: "son-dev" },
        el("b", {}, d.label), " ",
        el("span", { class: "subtle" }, `${SYSTEMS[d.system] || d.system} · ${d.ip} · ${abilities(d)}`)))));
    if (streams.length) {
      box.append(el("ul", { class: "son-list" }, ...streams.map((s) => {
        const stop = el("button", { type: "button", class: "small flat net-btn danger" }, "Arrêter");
        stop.addEventListener("click", () => busy(stop, async () => {
          try { await api.call("audio.stop", { stream: s.stream }); refresh(); }
          catch (e) { toast(e.message, { kind: "error" }); }
        }));
        return el("li", { class: "son-stream" }, icon("arrows", 14), " ",
          `${labelOf(devices, s.source)} → ${labelOf(devices, s.target)}`, " ", stop);
      })));
    }
    const { sources, outputs } = choices(devices);
    if (sources.length && outputs.length) {
      fill(srcSel, sources, srcSel.value);
      fill(dstSel, outputs, dstSel.value || (outputs.find((d) => d.device !== srcSel.value) || {}).device);
      box.append(el("div", { class: "net-row son-form" },
        el("span", {}, "Envoyer le son de"), srcSel, el("span", {}, "vers"), dstSel, send));
    }
  }

  async function refresh() {
    try {
      data = await api.call("audio.list");
      if (document.activeElement !== srcSel && document.activeElement !== dstSel) render();
    } catch (e) {
      clear(box).append(el("p", { class: "net-error" }, e.message || "Son partagé indisponible."));
    }
  }

  function schedule() {
    clearTimeout(timer);
    if (!alive) return;
    timer = setTimeout(async () => { if (!document.hidden) await refresh(); schedule(); }, REFRESH_MS);
  }

  return {
    box,
    start() { refresh().then(schedule); return () => { alive = false; clearTimeout(timer); }; },
  };
}
