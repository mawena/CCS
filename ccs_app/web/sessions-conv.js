// Conversations de l'historique : ligne (reprise d'un tap, marque « ouverte », coût), menu « ⋯ »
// avec aperçu sans ouvrir et renommage. Utilisé par la liste de Sessions et par l'écran Projet.
import { ago, clear, el, errorState, loading, toast } from "./dom.js";

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
    try { const r = await api.call("conversation.cost", { path: c.path }); costs.set(key, r); show(r); } catch { /* le coût est un plus : on l'omet */ }
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
  whenVisible(row, () => loadCost(ctx.api, c, cost));
  return row;
}

function convMenu(c, ctx, nameNode) {
  const { close } = sheet(titleOf(c), el("p", { class: "subtle" }, base(c.cwd)), [
    el("button", { type: "button", onclick: () => { close(); preview(c, ctx); } }, "Aperçu"),
    el("button", { type: "button", onclick: () => { close(); rename(c, ctx, nameNode); } }, "Renommer"),
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
    try { r = await ctx.api.call("conversation.messages", { path: c.path, limit: PREVIEW_MESSAGES * 3 }); } catch (e) {
      clear(body).append(errorState(e.message, load));
      return;
    }
    // le pont envoie « utilisateur » / « assistant » (preview.py) ; les majuscules restent acceptées
    const kind = (m) => { const role = String(m.role || "").toLowerCase(); return role === "utilisateur" || role === "user" ? "user" : role === "assistant" ? "claude" : null; };
    const shown = (r.messages || []).filter((m) => kind(m) && m.text).slice(-PREVIEW_MESSAGES);
    clear(body);
    if (!shown.length) { body.append(el("p", { class: "subtle" }, "Rien à afficher dans cette conversation.")); return; }
    for (const m of shown) {
      const text = m.text.length > 700 ? `${m.text.slice(0, 700)}…` : m.text;
      body.append(el("div", { class: `pv ${kind(m)}` },
        el("span", { class: "subtle" }, kind(m) === "user" ? "Toi" : "Claude"), el("div", { class: "pv-text" }, text)));
    }
  };
  load();
}

// ---- renommer -------------------------------------------------------------------------------

function rename(c, ctx, nameNode) {
  const input = el("input", { type: "text", value: titleOf(c), "aria-label": "Nouveau titre", maxlength: "200", enterkeyhint: "done" });
  const msg = el("p", { class: "message", role: "alert" });
  const form = el("form", { class: "rename" }, input, msg);
  const { close } = sheet("Renommer la conversation", form, [
    el("button", { type: "button", onclick: () => close() }, "Annuler"),
    el("button", { type: "button", class: "primary", onclick: () => form.requestSubmit() }, "Renommer"),
  ]);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "";
    try {
      const r = await ctx.api.call("conversation.rename", { session_id: c.session_id, title: input.value, path: c.path });
      c.title = r.title;
      nameNode.textContent = r.title;
      close();
      toast("Conversation renommée.", { kind: "success" });
    } catch (err) { msg.textContent = err.message; }
  });
  input.focus();
  input.select();
}
