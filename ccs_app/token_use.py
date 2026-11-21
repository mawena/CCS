"""Consommation de tokens d'un chat : usage de chaque réponse et cache expiré.

Commun au bureau et au pont (web, Android, iPhone, TUI) : les appareils n'ont qu'à afficher.

- `turn_usage(result)` : usage d'un tour, depuis l'événement `result` de la CLI (tokens lus
  dans le cache, écrits dans le cache, frais, produits ; coût ; taille du contexte à la fin ;
  durée de vie du cache, 5 min ou 1 h).
- `cache_expiry(usage, model)` : ce que coûtera le prochain message une fois le cache expiré
  (tout le contexte réécrit dans le cache), ou None si ce n'est pas la peine de prévenir.
"""

from . import costs

CACHE_TTL_5M = 300
CACHE_TTL_1H = 3600
EXPIRY_MIN_CONTEXT = 20_000     # tokens : en dessous, relire le contexte coûte peu, on ne dit rien


def _int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def turn_usage(result):
    """Usage d'un tour (dict), depuis l'événement `result` de la CLI ; {} sans usage.

    Clés : `input`, `cache_read`, `cache_write`, `output` (tokens du tour entier, toutes
    requêtes), `cost_usd`, `context` (tokens relus à la dernière requête + produits : la taille
    du contexte pour le message suivant), `cache_ttl_s` (300 ou 3600), `model`."""
    if not isinstance(result, dict):
        return {}
    u = result.get("usage")
    if not isinstance(u, dict):
        return {}
    out = {
        "input": _int(u.get("input_tokens")),
        "cache_read": _int(u.get("cache_read_input_tokens")),
        "cache_write": _int(u.get("cache_creation_input_tokens")),
        "output": _int(u.get("output_tokens")),
    }
    if not any(out.values()):
        return {}
    try:
        out["cost_usd"] = round(float(result.get("total_cost_usd") or 0.0), 6)
    except (TypeError, ValueError):
        out["cost_usd"] = 0.0
    # Coût du tour seul : `total_cost_usd` cumule la session ; le détail par modèle du tour est
    # dans `model_usage_since_last_result` quand la CLI le donne.
    since = result.get("model_usage_since_last_result")
    if isinstance(since, dict) and since:
        try:
            out["cost_usd"] = round(sum(float(m.get("costUSD") or 0.0) for m in since.values()
                                        if isinstance(m, dict)), 6)
        except (TypeError, ValueError):
            pass
    models = since if isinstance(since, dict) and since else result.get("modelUsage")
    if isinstance(models, dict) and models:
        out["model"] = max(models, key=lambda k: _int((models[k] or {}).get("outputTokens"))
                           if isinstance(models[k], dict) else 0)
    iterations = [i for i in u.get("iterations") or () if isinstance(i, dict)]
    last = iterations[-1] if iterations else u
    out["context"] = (_int(last.get("input_tokens")) + _int(last.get("cache_read_input_tokens"))
                      + _int(last.get("cache_creation_input_tokens")) + _int(last.get("output_tokens")))
    creation = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    five = _int(creation.get("ephemeral_5m_input_tokens"))
    hour = _int(creation.get("ephemeral_1h_input_tokens"))
    out["cache_ttl_s"] = CACHE_TTL_5M if five > hour else CACHE_TTL_1H
    return out


def rewrite_cost(context, ttl_s, model):
    """Prix en dollars (tarif de l'API) de la réécriture de `context` tokens dans le cache ;
    None si le modèle est inconnu."""
    price = costs.price_for(model)
    if price is None:
        return None
    per_m = price.cache_write_5m if ttl_s <= CACHE_TTL_5M else price.cache_write_1h
    return round(context * per_m / 1e6, 4)


def cache_expiry(usage, model=None):
    """Après `usage` (dict de `turn_usage`) : ce qu'il faut dire quand le cache aura expiré,
    ou None (contexte trop petit pour que ça compte). Dict : `context`, `ttl_s`,
    `rewrite_usd` (None si modèle inconnu), `text`."""
    context = _int((usage or {}).get("context"))
    if context < EXPIRY_MIN_CONTEXT:
        return None
    ttl = _int(usage.get("cache_ttl_s")) or CACHE_TTL_1H
    usd = rewrite_cost(context, ttl, model or usage.get("model"))
    cost = f" (environ {usd:.2f} $ au tarif de l'API)".replace(".", ",") if usd else ""
    delay = "1 h" if ttl >= CACHE_TTL_1H else f"{ttl // 60} min"
    text = (f"Cache expiré : rien depuis {delay}, le prochain message relira tout le contexte, "
            f"{fmt_tokens(context)} tokens, au prix fort{cost}. Si le sujet a changé, une nouvelle "
            "session coûte bien moins ; sinon « Compacter » réduit d'abord le contexte.")
    return {"context": context, "ttl_s": ttl, "rewrite_usd": usd, "text": text}


def fmt_tokens(value):
    """12 345 → « 12 k », 1 234 567 → « 1,2 M »."""
    value = _int(value)
    if value >= 1_000_000:
        return f"{value / 1e6:.1f} M".replace(".", ",")
    if value >= 1000:
        return f"{round(value / 1000)} k"
    return str(value)


def summary(usage):
    """Ligne courte sous une réponse : « 120 k lus · 3 k écrits · 850 produits · 0,04 $ »."""
    if not usage:
        return ""
    parts = []
    if usage.get("cache_read"):
        parts.append(f"{fmt_tokens(usage['cache_read'])} lus")
    written = _int(usage.get("cache_write")) + _int(usage.get("input"))
    if written:
        parts.append(f"{fmt_tokens(written)} écrits")
    parts.append(f"{fmt_tokens(usage.get('output'))} produits")
    if usage.get("cost_usd"):
        parts.append(f"{usage['cost_usd']:.2f} $".replace(".", ","))
    return " · ".join(parts)
