// Alerte de contexte lourd du chat : décision pure (testée avec node).
// `ev` : mesure du contexte (ContextUsage) ; `cfg` : réglages du pont (work.commands) ;
// `heavy` : le contexte était déjà au-dessus du seuil à la mesure d'avant.
// Renvoie { heavy, gain } : `gain` (jetons qu'un compactage libérerait, estimation) seulement
// quand il faut montrer l'alerte et son bouton « Compacter », au franchissement du seuil.
export const COMPACT_KEEP = 0.2;      // part du contexte gardée après `/compact` (comme context_alert.py)

export function contextAlert(ev, cfg, heavy) {
  // Compactage automatique : le pont envoie `/compact` lui-même et l'écrit dans le fil (Notice).
  if (ev.auto_compact) return { heavy: false, gain: null };
  const over = Boolean(cfg.enabled && cfg.threshold_tokens && ev.total >= cfg.threshold_tokens);
  return { heavy: over, gain: over && !heavy ? ev.total - Math.floor(ev.total * COMPACT_KEEP) : null };
}

// ---- consommation de tokens (comme token_use.py) -------------------------------------------

// 12 345 → « 12 k », 1 234 567 → « 1,2 M ».
export function fmtTokens(v) {
  const n = Math.max(0, Math.floor(Number(v) || 0));
  if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(".", ",")} M`;
  if (n >= 1000) {                       // arrondi au pair comme Python (2 500 → « 2 k »)
    const x = n / 1000;
    let r = Math.round(x);
    if (x % 1 === 0.5 && r % 2) r -= 1;
    return `${r} k`;
  }
  return String(n);
}

// Ligne sous une fin de tour : « 36 k lus · 15 k écrits · 403 produits · 0,04 $ ».
export function usageSummary(u) {
  if (!u || typeof u !== "object" || !Object.keys(u).length) return "";
  const parts = [];
  if (u.cache_read) parts.push(`${fmtTokens(u.cache_read)} lus`);
  const written = (Number(u.cache_write) || 0) + (Number(u.input) || 0);
  if (written) parts.push(`${fmtTokens(written)} écrits`);
  parts.push(`${fmtTokens(u.output)} produits`);
  if (u.cost_usd) parts.push(`${Number(u.cost_usd).toFixed(2).replace(".", ",")} $`);
  return parts.join(" · ");
}

// Couleur de l'indicateur de contexte : vert sous la moitié du seuil, orange jusqu'au seuil,
// rouge au-delà (seuil : context_alert.threshold_tokens, 150 000 par défaut).
export const DEFAULT_THRESHOLD = 150000;
export function contextLevel(total, threshold = DEFAULT_THRESHOLD) {
  const t = Number(threshold) || DEFAULT_THRESHOLD;
  if (total >= t) return "crit";
  return total >= t / 2 ? "warn" : "ok";
}
