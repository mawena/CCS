// Écran Son, autonome (`mountSon(conteneur, api)`) et encore inclus dans l'onglet Réseau
// (`createSon`) : appareils annoncés (sorties qui jouent, sources qui captent leur son), flux en
// cours avec Arrêter, « Envoyer le son de … vers … » entre deux appareils quelconques, et les
// lecteurs (VLC, Firefox… par MPRIS) de chaque PC Linux : ⏮ ⏯ ⏭, −10 s / +10 s, volume.
// Le web ne joue ni ne capte rien lui-même : télécommande seulement.
// Méthodes `audio.*` (docs/audio.md), toujours sur ce serveur. Rechargement toutes les 5 s.
import { clear, el, toast } from "./dom.js";
import { busy } from "./pages-util.js";
import { icon as netIcon } from "./reseau.js";

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

const STATUS = { Playing: "▶", Paused: "⏸", Stopped: "■" };

// Appareils qui rapportent leurs lecteurs (`players` absent : pas d'agent Linux à jour).
export function withPlayers(devices) {
  return (devices || []).filter((d) => Array.isArray(d.players));
}

// « Artiste — Titre », ou ce qu'on a.
export function trackOf(p) {
  return [p.artist, p.title].filter(Boolean).join(" — ") || "(rien en cours)";
}

// `box` : partage puis lecteurs (pour l'onglet Réseau) ; `shareBox` et `playersBox` séparés pour
// l'écran Son (mountSon), qui leur donne chacun sa section.
export function createSon(api, icon = netIcon, { heading = true } = {}) {
  const shareBox = el("div", { class: "son-share" });
  const playersBox = el("div", { class: "son-players" });
  const box = el("div", { class: "son-box" }, shareBox, playersBox);
  let data = { devices: [], streams: [] };
  let soon = null;
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

  // Une commande à un lecteur, puis relecture (l'agent rapporte l'état ~0,3 s après).
  async function control(device, player, command, value) {
    try {
      await api.call("audio.control", { device, player: player.id, command, ...(value != null ? { value } : {}) });
      clearTimeout(soon);
      soon = setTimeout(refresh, 600);
    } catch (e) { toast(e.message, { kind: "error" }); }
  }

  function playerRow(d, p) {
    const btn = (label, title, command, value, enabled = true) => {
      const b = el("button", { type: "button", class: "small flat net-btn son-key", title, "aria-label": title }, label);
      if (!enabled) b.disabled = true;
      b.addEventListener("click", () => busy(b, () => control(d.device, p, command, value)));
      return b;
    };
    const keys = el("div", { class: "son-keys" },
      btn("⏮", "Précédent", "prev", null, p.can_prev !== false),
      btn(p.status === "Playing" ? "⏸" : "▶", p.status === "Playing" ? "Pause" : "Lecture", "toggle", null,
        p.can_pause !== false || p.can_play !== false),
      btn("⏭", "Suivant", "next", null, p.can_next !== false),
      ...(p.can_seek ? [btn("−10 s", "Reculer de 10 s", "seek", -10), btn("+10 s", "Avancer de 10 s", "seek", 10)] : []));
    if (p.volume != null) {
      const vol = el("input", { type: "range", min: "0", max: "100", step: "5", value: String(p.volume),
        class: "son-volume", "aria-label": `Volume de ${p.name}`, title: `Volume ${p.volume} %` });
      vol.addEventListener("change", () => { control(d.device, p, "volume", Number(vol.value)); vol.blur?.(); });
      keys.append(vol);
    }
    return el("li", { class: "son-player" },
      el("div", { class: "son-track" },
        el("b", {}, `${STATUS[p.status] || "■"} ${p.name}`), " ",
        el("span", { class: "subtle" }, trackOf(p))),
      keys);
  }

  function renderPlayers() {
    clear(playersBox);
    const list = withPlayers(data.devices);
    if (!list.length) {
      if (!heading) playersBox.append(el("p", { class: "subtle" },
        "Aucun PC Linux ne rapporte ses lecteurs : lance `ccs audio enable` dessus (agent à jour)."));
      return;
    }
    playersBox.append(...(heading ? [el("h3", { class: "son-h3" }, "Lecteurs")] : []),
      ...list.map((d) => el("div", { class: "son-machine" },
        el("div", { class: "subtle" }, d.label),
        d.players.length
          ? el("ul", { class: "son-list" }, ...d.players.map((p) => playerRow(d, p)))
          : el("p", { class: "subtle" }, "Aucun lecteur ouvert."))));
  }

  // On ne redessine pas les lecteurs pendant qu'on tient un curseur de volume.
  function render() {
    const held = document.activeElement;
    if (!(held && held.tagName === "INPUT" && playersBox.contains?.(held))) renderPlayers();
    renderShare();
  }

  function renderShare() {
    const box = clear(shareBox);
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
      clear(playersBox);
      clear(shareBox).append(el("p", { class: "net-error" }, e.message || "Son partagé indisponible."));
    }
  }

  function schedule() {
    clearTimeout(timer);
    if (!alive) return;
    timer = setTimeout(async () => { if (!document.hidden) await refresh(); schedule(); }, REFRESH_MS);
  }

  return {
    box, shareBox, playersBox,
    start() { refresh().then(schedule); return () => { alive = false; clearTimeout(timer); clearTimeout(soon); }; },
  };
}

// Écran Son autonome : `mountSon(conteneur, api)` → fonction de nettoyage (comme mountReseau).
// Le 3ᵉ argument que passe l'appli est le contexte ({ user, banner… }), pas une fonction d'icônes.
export function mountSon(root, api) {
  const icon = netIcon;
  const son = createSon(api, icon, { heading: false });
  const wrap = el("div", { class: "settings-wrap net-page son-page" },
    el("section", { class: "card flat section", "aria-label": "Son partagé" },
      el("h2", { class: "net-h2" }, icon("pulse", 20), "Son partagé"), son.shareBox),
    el("section", { class: "card flat section", "aria-label": "Lecteurs" },
      el("h2", { class: "net-h2" }, icon("play", 20), "Lecteurs"), son.playersBox));
  root.append(wrap);
  return son.start();
}
