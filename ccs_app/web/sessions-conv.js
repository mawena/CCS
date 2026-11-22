// Conversations de l'historique : ligne (reprise d'un tap, marque « ouverte », coût), menu « ⋯ »
// avec aperçu sans ouvrir et renommage. Utilisé par la liste de Sessions et par l'écran Projet.
import { ago, clear, contextMenu, el, errorState, loading, promptSheet, toast } from "./dom.js";
import { quoteBlock } from "./chat-message.js";
import { split } from "./chat-quote.js";

const base = (p) => (p || "").split("/").filter(Boolean).pop() || p;
export const titleOf = (c) => c.title || c.first_prompt || "(sans titre)";

// Feuille modale : titre, contenu, boutons. Renvoie { dlg, close }.
export function sheet(title, content, actions = []) {
  const dlg = el("dialog", { class: "sheet wide", "aria-label": title });
  const close = () => { if (dlg.open) dlg.close(); dlg.remove(); };
  dlg.append(el("h2", {}, title), content, el("div", { class: "sheet-actions" }, ...actions));
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dlg);
  dlg.showModal();
  return { dlg, close };
}

// ---- coût : demandé quand la ligne est visible, une requête à la fois -----------------------

const costs = new Map();             // chemin + date → { short, text }
let queue = Promise.resolve();

function loadCost(api, c, node) {
  const key = `${c.path}:${c.updated_at}`;
  const show = (r) => { if (r.short) { node.textContent = r.short; node.title = `Coût de la conversation (équivalent API) : ${r.text}`; } };
  if (costs.has(key)) { show(costs.get(key)); return; }
  queue = queue.then(async () => {
    if (!node.isConnected) return;
    try { const r = await api.call("conversations.cost", { path: c.path }); costs.set(key, r); show(r); } catch { /* le coût est un plus : on l'omet */ }
  });
}

function whenVisible(node, run) {
  if (!("IntersectionObserver" in window)) { run(); return; }
  const io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { io.disconnect(); run(); }
  });
  io.observe(node);
}

// ---- ligne ----------------------------------------------------------------------------------

// ctx : { api, opened: Set de session_id, resume(c), changed() }
export function convRow(c, ctx, { showProject = true } = {}) {
  const cost = el("span", { class: "conv-cost subtle" });
  const name = el("strong", {}, titleOf(c));
  const meta = [showProject ? base(c.cwd) : null, ago(c.updated_at)].filter(Boolean).join(" · ");
  const main = el("button", { class: "conv-main", disabled: !c.folder_exists, onclick: () => ctx.resume(c) },
    el("span", { class: "conv-title" }, name, ctx.opened.has(c.session_id) ? el("span", { class: "badge open" }, "ouverte") : null),
    el("span", { class: "subtle conv-meta" }, meta, " ", cost));
  const more = el("button", { class: "flat conv-more", "aria-label": `Actions pour ${titleOf(c)}`, onclick: () => convMenu(c, ctx, name) }, "⋯");
  const row = el("div", { class: "item conv" }, main, more);
  row.addEventListener("contextmenu", (e) => contextMenu(e, [
    { label: "Reprendre", disabled: !c.folder_exists, run: () => ctx.resume(c) },
    { label: "Aperçu", run: () => preview(c, ctx) },
    { label: "Renommer…", run: () => rename(c, ctx, name) },
    null,
    { label: "Copier le chemin du projet", run: () => copy(c.cwd) },
    ...(ctx.trash ? [null, { label: "Supprimer…", danger: true, run: () => ctx.trash(c) }] : []),
  ]));
  whenVisible(row, () => loadCost(ctx.api, c, cost));
  return row;
}

function convMenu(c, ctx, nameNode) {
  const { close } = sheet(titleOf(c), el("p", { class: "subtle" }, base(c.cwd)), [
    el("button", { type: "button", onclick: () => { close(); preview(c, ctx); } }, "Aperçu"),
    el("button", { type: "button", onclick: () => { close(); rename(c, ctx, nameNode); } }, "Renommer"),
    ctx.trash ? el("button", { type: "button", class: "danger", onclick: () => { close(); ctx.trash(c); } }, "Supprimer") : null,
    el("button", { type: "button", class: "primary", disabled: !c.folder_exists, onclick: () => { close(); ctx.resume(c); } }, "Reprendre"),
  ]);
}

// ---- aperçu sans ouvrir ---------------------------------------------------------------------

const PREVIEW_MESSAGES = 12;

function preview(c, ctx) {
  const body = el("div", { class: "preview-body" });
  const { close } = sheet(titleOf(c), body, [
    el("button", { type: "button", onclick: () => close() }, "Fermer"),
    el("button", { type: "button", class: "primary", disabled: !c.folder_exists, onclick: () => { close(); ctx.resume(c); } }, "Reprendre"),
  ]);
  const load = async () => {
    clear(body).append(loading());
    let r;
    try { r = await ctx.api.call("conversations.messages", { path: c.path, limit: PREVIEW_MESSAGES * 3 }); } catch (e) {
      clear(body).append(errorState(e.message, load));
      return;
    }
    // le pont envoie « utilisateur » / « assistant » (preview.py) ; les majuscules restent acceptées
    const kind = (m) => { const role = String(m.role || "").toLowerCase(); return role === "user" ? "user" : role === "assistant" ? "claude" : null; };
    const shown = (r.messages || []).filter((m) => kind(m) && m.text).slice(-PREVIEW_MESSAGES);
    clear(body);
    if (!shown.length) { body.append(el("p", { class: "subtle" }, "Rien à afficher dans cette conversation.")); return; }
    for (const m of shown) {
      // réponse à un message cité : la citation à part (repliée), puis la réponse
      const q = kind(m) === "user" ? split(m.text) : null;
      const full = q ? q.body : m.text;
      const text = full.length > 700 ? `${full.slice(0, 700)}…` : full;
      body.append(el("div", { class: `pv ${kind(m)}` },
        el("span", { class: "subtle" }, kind(m) === "user" ? "Toi" : "Claude"),
        el("div", { class: "pv-text" }, q ? quoteBlock(q) : null, text)));
    }
  };
  load();
}

// ---- renommer -------------------------------------------------------------------------------

export async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copié.", { kind: "success" }); } catch { toast("Copie impossible ici.", { kind: "error" }); }
}

// Renomme une conversation (journal de Claude Code) ; prévient les onglets ouverts par
// l'événement « ccs:conv-renamed ». Promesse : le nouveau titre, ou null.
export async function renameConversation(api, c) {
  const title = await promptSheet({ title: "Renommer la conversation", value: titleOf(c), label: "Nouveau titre", confirm: "Renommer",
    check: async (v) => (await api.call("conversations.rename", { session_id: c.session_id, title: v, path: c.path })).title });
  if (title === null) return null;
  c.title = title;
  document.dispatchEvent(new CustomEvent("ccs:conv-renamed", { detail: { session_id: c.session_id, title } }));
  toast("Conversation renommée.", { kind: "success" });
  return title;
}

async function rename(c, ctx, nameNode) {
  const title = await renameConversation(ctx.api, c);
  if (title !== null) nameNode.textContent = title;
}
