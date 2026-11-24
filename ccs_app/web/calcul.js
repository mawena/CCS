// Calcul réparti, affiché dans l'onglet Réseau (#/reseau) : la charge, la mémoire, les outils et
// les places de chaque machine (rattachées à leur fiche du réseau maillé), les commandes lancées
// dessus (`ccs distant lancer`), un formulaire pour en lancer une, l'ajout d'un PC et les réglages
// du relais Ricochet (le secours quand le réseau maillé ne joint pas une machine). Les méthodes
// `machines.*` répondent toujours sur ce serveur, même quand le web pilote une autre machine.
// Rechargement toutes les 5 s tant que la page est visible.
import { ago, clear, confirmSheet, el, emptyState, errorState, loading, toast } from "./dom.js";
import { busy, copyText, field, shortPath } from "./pages-util.js";

export const LAST_PROJECT_KEY = "ccs.project.last";
const REFRESH_MS = 5000;
const LOG_MS = 3000;
const ACTIVE = ["waiting", "scheduled", "sending", "running"];
const PILL = { waiting: "waiting", scheduled: "waiting", sending: "running", running: "running",
  done: "done", failed: "failed", stopped: "" };
// états des travaux en français, pour l'affichage
export const STATE_LABELS = { waiting: "attente", scheduled: "programmé", sending: "envoi", running: "en cours",
  done: "fini", failed: "échec", stopped: "arrêté" };
const LIMITS = [1, 2, 3, 4, 5, 6, 7, 8];

const num = (x, digits = 1) => Number(x || 0).toLocaleString("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export function duration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
  return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
}

// Le dernier projet ouvert dans Sessions, s'il l'a été sur ce serveur (pas sur une machine pilotée).
export function rememberProject(api, cwd) {
  try { localStorage.setItem(LAST_PROJECT_KEY, JSON.stringify({ machine: api.machine || "", cwd })); } catch { /* privé */ }
}

function lastProject() {
  try {
    const p = JSON.parse(localStorage.getItem(LAST_PROJECT_KEY) || "null");
    return p && !p.machine && p.cwd ? p.cwd : "";
  } catch { return ""; }
}

function bar(label, ratio, value, title) {
  const pct = Math.round(Math.min(1, Math.max(0, ratio)) * 100);
  const fill = el("div", { class: `bar-fill${pct >= 90 ? " hot" : ""}` });
  fill.style.width = `${pct}%`;                       // pas d'attribut style (politique de sécurité)
  return el("div", { class: "bar machine-bar", title },
    el("span", { class: "bar-name" }, label),
    el("div", { class: "bar-track", role: "progressbar", "aria-label": label, "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct) }, fill),
    el("span", { class: "bar-value" }, value));
}

export function jobLine(j, now = Date.now() / 1000) {
  const parts = [j.machine || "machine à choisir"];
  if (j.started) parts.push(duration((j.ended || now) - j.started));
  else parts.push(`créé ${ago(j.created)}`);
  if (j.code !== null && j.code !== undefined) parts.push(`code ${j.code}`);
  if (j.cwd) parts.push(shortPath(j.cwd));
  return parts.join(" · ");
}

function sheet(title) {
  const dlg = el("dialog", { class: "sheet wide", "aria-label": title });
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  return dlg;
}

// La machine de calcul d'une fiche du réseau : ce serveur pour sa propre fiche, sinon par
// l'adresse du réseau maillé, puis par le nom (`reseau` des réglages, identifiant, nom d'hôte).
export function matchMachine(machines, d, self) {
  if (self) return machines.find((m) => m.local) || null;
  const keys = [d.name, d.host].filter(Boolean).map((s) => String(s).toLowerCase());
  const ips = d.ips || [];
  return machines.find((m) => !m.local && ((m.mesh_ip && ips.includes(m.mesh_ip))
    || [m.mesh, m.id, m.host].some((k) => k && keys.includes(String(k).toLowerCase())))) || null;
}

// Tout le calcul réparti, en morceaux que la page Réseau place où il faut.
export function createCompute(api, { onMachines = () => {}, onSettings = () => {} } = {}) {
  const state = { machines: [], jobs: [], settings: null, message: "", configured: true, home: "",
    logs: new Set(), alive: true };
  const jobsBox = el("div", { class: "stack" }, loading());
  const formBox = el("div", {});
  const relayBox = el("div", { class: "stack" }, loading());

  // ---- bloc « calcul » d'une fiche ---------------------------------------------------------

  function block(m) {
    const box = el("div", { class: "net-compute", "aria-label": `Calcul sur ${m.name || m.id}` });
    if (m.online && m.cores) {
      const perCore = Number(m.load || 0) / m.cores;
      box.append(bar("Charge", perCore, `${num(perCore, 2)}/cœur`, `charge ${num(m.load)} sur ${m.cores} cœurs`));
    }
    if (m.online && m.mem_total) {
      box.append(bar("Mémoire", m.mem_used / m.mem_total,
        `${num(m.mem_used / 2 ** 30)}/${num(m.mem_total / 2 ** 30, 0)} Go`, "mémoire utilisée"));
    }
    const tools = m.tools || [];
    box.append(el("div", { class: "chips", "aria-label": "Outils" },
      tools.length ? tools.map((t) => el("span", { class: "chip" }, t)) : el("span", { class: "subtle" }, "outils pas encore inventoriés")));
    const limit = el("select", { "aria-label": `Limite de travaux sur ${m.name || m.id}` },
      ...LIMITS.map((n) => el("option", { value: String(n) }, String(n))));
    limit.value = String(m.limit || 2);
    limit.addEventListener("change", () => busy(limit, async () => {
      try { await api.call("machines.limit", { machine: m.id, limit: Number(limit.value) }); } catch (e) {
        toast(e.message, { kind: "error" });
        limit.value = String(m.limit || 2);
        return;
      }
      toast("Limite enregistrée.", { kind: "success" });
      refresh();
    }));
    const places = `Places : ${m.running || 0}/${m.limit || 2}` + (m.waiting ? ` · ${m.waiting} en attente` : "");
    box.append(el("div", { class: "machine-places" }, el("span", { class: "grow" }, places),
      el("label", { class: "machine-limit" }, "Limite", limit)));
    if (!m.tunnel && !m.local && !m.mesh_ip) box.append(el("p", { class: "subtle" }, "Ni réseau maillé ni tunnel SSH Ricochet sur cette machine."));
    return box;
  }

  // ---- travaux ---------------------------------------------------------------------------

  function jobRow(j) {
    const active = ACTIVE.includes(j.state);
    const cls = j.state === "done" && j.code ? "failed" : PILL[j.state] ?? "";
    return el("article", { class: `job${active ? " active" : ""}`, "aria-label": j.text },
      el("div", { class: "job-head" }, el("code", { class: "job-cmd", title: j.text }, j.text),
        el("span", { class: `pill ${cls}` }, STATE_LABELS[j.state] ?? j.state)),
      el("div", { class: "subtle" }, jobLine(j)),
      j.why ? el("div", { class: "job-why" }, j.why) : null,
      el("div", { class: "job-actions" },
        el("button", { type: "button", class: "small", onclick: () => showLog(j) }, "Journal"),
        active ? el("button", { type: "button", class: "small danger", onclick: (e) => busy(e.currentTarget, () => stopJob(j)) }, "Arrêter") : null));
  }

  function drawJobs(r, error) {
    clear(jobsBox);
    if (error) { jobsBox.append(errorState(error.message, refresh)); return; }
    const jobs = r.jobs || [];
    const active = jobs.filter((j) => ACTIVE.includes(j.state));
    const done = jobs.filter((j) => !ACTIVE.includes(j.state));
    if (!jobs.length) { jobsBox.append(emptyState("Aucune commande lancée pour l'instant.")); return; }
    jobsBox.append(el("h3", {}, `En cours et à venir (${active.length})`),
      active.length ? el("div", { class: "jobs" }, ...active.map(jobRow)) : el("p", { class: "subtle" }, "Rien en cours."));
    if (done.length) jobsBox.append(el("h3", {}, `Finis (${done.length})`), el("div", { class: "jobs" }, ...done.map(jobRow)));
  }

  async function stopJob(j) {
    const running = j.state === "running" || j.state === "sending";
    if (!await confirmSheet({ title: "Arrêter ce travail ?",
      body: running ? `« ${j.text} » sera arrêtée sur ${j.machine || "la machine"}.` : `« ${j.text} » ne sera pas lancée.`,
      confirm: "Arrêter", cancel: "Garder", danger: true })) return false;
    try { await api.call("machines.stop", { id: j.id }); } catch (e) { toast(e.message, { kind: "error" }); return false; }
    toast("Travail arrêté.", { kind: "success" });
    refresh();
    return true;
  }

  function showLog(j) {
    const dlg = sheet("Journal");
    const meta = el("div", { class: "subtle" }, jobLine(j));
    const log = el("pre", { class: "log", tabindex: "0", "aria-label": "Journal du travail" }, "Chargement…");
    dlg.append(el("h2", { class: "job-cmd" }, j.text), meta, log,
      el("div", { class: "sheet-actions" }, el("button", { type: "button", onclick: () => dlg.close() }, "Fermer")));
    let timer = null;
    const entry = { close: () => dlg.close() };
    state.logs.add(entry);
    dlg.addEventListener("close", () => { clearInterval(timer); state.logs.delete(entry); });
    async function load() {
      if (!dlg.open || document.hidden) return;
      let r;
      try { r = await api.call("machines.log", { id: j.id, tail: 20000 }); } catch (e) { log.textContent = e.message; return; }
      const fresh = state.jobs.find((x) => x.id === j.id);
      if (fresh) clear(meta).append(`${STATE_LABELS[fresh.state] ?? fresh.state} · ${jobLine(fresh)}`);
      const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
      log.textContent = r.text || "Pas encore de journal.";
      if (atEnd) log.scrollTop = log.scrollHeight;
    }
    dlg.showModal();
    load();
    timer = setInterval(load, LOG_MS);
    return dlg;
  }

  // ---- lancer une commande ---------------------------------------------------------------

  const command = el("input", { type: "text", autocomplete: "off", autocapitalize: "off", spellcheck: "false",
    placeholder: "flutter build apk", "aria-label": "Commande" });
  const folder = el("input", { type: "text", list: "machines-folders", autocomplete: "off", autocapitalize: "off",
    spellcheck: "false", placeholder: "~/Work/mon-projet", "aria-label": "Dossier" });
  const folders = el("datalist", { id: "machines-folders" });
  const target = el("select", { "aria-label": "Machine" }, el("option", { value: "" }, "La moins chargée"));
  const when = el("select", { "aria-label": "Quand" }, el("option", { value: "" }, "Maintenant"),
    el("option", { value: "nuit" }, "Cette nuit"), el("option", { value: "heure" }, "À une heure…"));
  const time = el("input", { type: "time", hidden: true, "aria-label": "Heure" });
  const formError = el("p", { class: "form-error", role: "alert" });
  const submit = el("button", { type: "submit", class: "primary" }, "Lancer");
  when.addEventListener("change", () => { time.hidden = when.value !== "heure"; });
  const form = el("form", { class: "stack" }, field("Commande", command, "Une ligne de shell, lancée dans le dossier."),
    field("Dossier", folder), folders, field("Machine", target), field("Quand", when), time, formError,
    el("div", { class: "sheet-actions" }, submit));
  formBox.append(form);

  function drawTargets() {
    const keep = target.value;
    clear(target).append(el("option", { value: "" }, "La moins chargée"),
      ...state.machines.filter((m) => !m.local || m.online).map((m) => el("option", { value: m.id, disabled: !m.online },
        `${m.name || m.id}${m.online ? "" : " (hors ligne)"}`)));
    target.value = state.machines.some((m) => m.id === keep) ? keep : "";
  }

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    formError.textContent = "";
    const text = command.value.trim();
    let cwd = folder.value.trim() || state.home;
    if (cwd.startsWith("~") && state.home) cwd = state.home + cwd.slice(1);
    if (!text) { formError.textContent = "Écris la commande à lancer."; return; }
    if (!cwd) { formError.textContent = "Indique le dossier."; return; }
    if (when.value === "heure" && !time.value) { formError.textContent = "Choisis l'heure."; return; }
    const params = { command: text, cwd, when: when.value === "heure" ? time.value : when.value };
    if (target.value) params.machine = target.value;
    busy(submit, async () => {
      try { await api.call("machines.start", params); } catch (e) { formError.textContent = e.message; return; }
      command.value = "";
      toast(params.when ? "Commande programmée." : "Commande lancée.", { kind: "success" });
      refresh();
    });
  });

  // ---- secours Ricochet ------------------------------------------------------------------

  function drawRelay(s, error) {
    clear(relayBox);
    if (error) { relayBox.append(errorState(error.message, loadRelay)); return; }
    if (state.message) relayBox.append(el("p", { class: state.configured === false ? "subtle" : "form-error" }, state.message));
    const address = el("input", { type: "url", inputmode: "url", autocomplete: "off", autocapitalize: "off", spellcheck: "false",
      placeholder: "https://ricochet.exemple", value: s.relay || "" });
    const token = el("input", { type: "password", autocomplete: "new-password", "aria-label": "Jeton",
      placeholder: s.token_set ? "laisser vide pour le garder" : "jeton du relais" });
    const status = el("span", { class: s.token_set ? "ok-text" : "subtle", "data-role": "token-status" },
      s.token_set ? "Jeton enregistré." : "Aucun jeton.");
    const error2 = el("p", { class: "form-error", role: "alert" });
    const save = el("button", { type: "submit", class: "primary" }, "Enregistrer");
    const f = el("form", { class: "stack" },
      el("p", { class: "subtle" }, "Le réseau maillé passe d'abord ; Ricochet prend le relais quand il ne joint pas une machine."),
      field("Adresse du relais", address),
      field("Jeton", token, status), error2,
      el("p", { class: "subtle" }, `Fichier : ${shortPath(s.path)} · limite par défaut : ${s.default_limit ?? 2} travaux à la fois par machine.`),
      el("div", { class: "sheet-actions" }, save));
    f.addEventListener("submit", (ev) => {
      ev.preventDefault();
      error2.textContent = "";
      const params = {};
      if (address.value.trim() !== (s.relay || "")) params.relay = address.value.trim();
      if (token.value) params.token = token.value;
      if (!Object.keys(params).length) { toast("Rien à changer."); return; }
      busy(save, async () => {
        try { await api.call("machines.configure", params); } catch (e) { error2.textContent = e.message; return; }
        token.value = "";
        toast("Enregistré.", { kind: "success" });
        await loadRelay();
        refresh();
      });
    });
    relayBox.append(f);
  }

  async function loadRelay() {
    try { state.settings = await api.call("machines.settings"); } catch (e) { drawRelay(null, e); return; }
    drawRelay(state.settings, null);
    onSettings(state.settings);
  }

  // ---- ajouter un PC par Ricochet (lien à usage unique, inscrit aussi au réseau maillé) -----

  const canAdd = () => Boolean(state.settings?.relay && state.settings?.token_set && state.settings?.operator_set);

  function addPc(box) {
    const id = el("input", { required: true, pattern: "[A-Za-z0-9_\\-]{1,64}", autocomplete: "off",
      autocapitalize: "off", spellcheck: "false", placeholder: "pc-salon", "aria-label": "Identifiant" });
    const user = el("input", { required: true, pattern: "[a-z_][a-z0-9_\\-]{0,31}", autocomplete: "off",
      autocapitalize: "off", spellcheck: "false", placeholder: "charles", "aria-label": "Compte" });
    const name = el("input", { maxlength: "100", placeholder: "PC du salon", "aria-label": "Nom affiché" });
    const full = el("input", { type: "checkbox" });
    const error2 = el("p", { class: "form-error", role: "alert" });
    const go = el("button", { type: "submit", class: "primary" }, "Créer le lien");
    const result = el("div", { class: "stack" });
    const f = el("form", { class: "stack" },
      field("Identifiant", id, "lettres, chiffres, - et _"),
      field("Ton compte sur ce PC", user, "terminal, fichiers et travaux tournent sous ce compte"),
      field("Nom affiché (facultatif)", name),
      el("div", {}, el("label", { class: "check" }, full, "Installer aussi CCS et Claude Code"),
        el("div", { class: "subtle" }, "pour ouvrir des sessions entières sur ce PC")), error2,
      el("div", { class: "sheet-actions" }, go));
    f.addEventListener("submit", (ev) => {
      ev.preventDefault();
      error2.textContent = "";
      clear(result);
      const params = { machine: id.value.trim(), user: user.value.trim() };
      if (name.value.trim()) params.name = name.value.trim();
      if (full.checked) params.full = true;
      busy(go, async () => {
        let r;
        try { r = await api.call("machines.add", params); } catch (e) { error2.textContent = e.message; return; }
        id.value = ""; name.value = "";
        const copy = el("button", { type: "button", class: "primary" }, "Copier");
        copy.addEventListener("click", () => copyText(r.command));
        result.append(
          el("p", {}, `Colle cette commande dans un terminal de « ${r.id} » (Ubuntu ou Debian). Le lien ne sert qu'une fois, pendant ${Math.round((r.expires_s || 900) / 60)} min.`),
          el("pre", { class: "log" }, r.command),
          el("p", { class: "subtle" }, "Elle installe le serveur SSH et l'agent Ricochet (secours), autorise la clé de ce serveur"
            + (r.mesh ? " et inscrit la machine au réseau maillé" : "")
            + (r.full ? ", puis installe CCS et Claude Code" : "")
            + " ; elle apparaît ensuite ici, avec sa charge et ses outils."),
          el("div", { class: "sheet-actions" }, copy));
        refresh();
      });
    });
    box.append(f, result);
  }

  // ---- chargement ------------------------------------------------------------------------

  async function refresh() {
    if (!state.alive) return;
    const [ml, jb] = await Promise.allSettled([api.call("machines.list"), api.call("machines.jobs")]);
    if (!state.alive) return;
    if (ml.status === "fulfilled") {
      state.machines = ml.value.machines || [];
      state.message = ml.value.message || "";
      state.configured = ml.value.configured !== false;
      drawTargets();
    } else {
      state.machines = [];
      state.message = ml.reason?.message || "Machines injoignables.";
    }
    onMachines(state.machines);
    if (jb.status === "fulfilled") state.jobs = jb.value.jobs || [];
    drawJobs(jb.value || {}, jb.status === "rejected" ? jb.reason : null);
  }

  // Dossier par défaut : le projet ouvert en dernier sur ce serveur, sinon le dossier personnel
  // (celui du serveur : `files.roots` serait celui de la machine pilotée, d'où le repli sur le
  // chemin du fichier du relais).
  async function loadHome() {
    if (!api.machine) {
      try { state.home = (await api.call("files.roots")).home || ""; } catch { /* repli ci-dessous */ }
      api.call("projects.list", {}).then((r) => {
        for (const p of (r.entries || []).filter((x) => x.cwd && x.exists)) folders.append(el("option", { value: p.cwd }));
      }).catch(() => {});
    }
    if (!state.home) {
      if (!state.settings) { try { state.settings = await api.call("machines.settings"); } catch { /* sans réglages */ } }
      state.home = (/^(\/home\/[^/]+|\/root)(?=\/|$)/.exec(state.settings?.path || "") || [""])[0];
    }
    if (!folder.value) folder.value = lastProject() || state.home;
  }

  function start() {
    const onVisible = () => { if (!document.hidden) refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    const timer = setInterval(() => { if (!document.hidden) refresh(); }, REFRESH_MS);
    const offs = [api.on?.("reconnected", refresh)].filter(Boolean);
    refresh();
    loadRelay().then(loadHome);
    return () => {
      state.alive = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      for (const off of offs) off();
      for (const l of [...state.logs]) l.close();
    };
  }

  return { block, jobsBox, formBox, relayBox, addPc, canAdd, start, refresh,
    get machines() { return state.machines; } };
}
