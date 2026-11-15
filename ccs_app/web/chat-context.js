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
