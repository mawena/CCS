"""Conseil de modèle près des limites : passer à la famille moins chère.

Quand le compte actif approche d'une limite (session de 5 h ou semaine) et que les
réponses récentes viennent surtout d'un modèle cher, une notification (une seule par
fenêtre de 5 h) propose la famille suivante : Fable → Opus → Sonnet → Haiku.

Le gain « ×N » est estimé d'après les tarifs de l'API (`costs`) appliqués aux tokens
réellement consommés ces 30 dernières minutes : les limites des abonnements ne suivent
pas exactement ces tarifs, c'est un ordre de grandeur. Les journaux ne sont lus qu'en
fin de fichier, avec un cache par chemin, taille et date de modification.
"""

import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from . import core, costs, transcripts
from .alerts import Alert, window_id
from .forecast import effective_percent

CHEAPER = {"fable": "opus", "opus": "sonnet", "sonnet": "haiku"}
# Modèle choisi par `/model <famille>` : le plus récent de chaque famille dans costs.PRICES.
REFERENCE = {"fable": "claude-fable-5-1", "opus": "claude-opus-5-5",
             "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
LABELS = {"fable": "Fable", "opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"}
KIND_LABELS = {"session": "session", "weekly": "semaine"}

RECENT = timedelta(minutes=30)
TAIL_BYTES = 512 * 1024
MIN_STRETCH = 1.25     # en dessous, changer de modèle ne vaut pas une notification
MAX_STRETCH_SHOWN = 5


def family(model):
    """Famille d'un modèle (« opus »…), « fable » pour Mythos, None sans modèle."""
    if not model:
        return None
    f = transcripts.model_family(str(model))
    return "fable" if "mythos" in f else f


# --------------------------------------------------------------------------
# Usage récent
# --------------------------------------------------------------------------

@dataclass
class RecentUsage:
    family: str        # famille dominante (en dollars au tarif de l'API)
    model: str         # dernier modèle de cette famille
    tokens: tuple      # tokens de cette famille (entrée, sortie, cache 5 min, cache 1 h, cache lu)
    dollars: float     # leur coût au tarif de l'API
    answers: int


def _dollars(a):
    if a.dollars is not None:
        return a.dollars
    ref = REFERENCE.get(family(a.model))
    return (costs.reprice(a.tokens, ref) if ref else None) or 0.0


def summarize(answers):
    """Famille dominante d'une suite de réponses (`costs.Answer`), ou None."""
    groups = {}
    for a in sorted(answers, key=lambda a: a.ts):
        f = family(a.model)
        if f is None:
            continue
        g = groups.setdefault(f, {"tokens": [0] * 5, "dollars": 0.0, "n": 0, "model": a.model})
        g["tokens"] = [x + y for x, y in zip(g["tokens"], a.tokens)]
        g["dollars"] += _dollars(a)
        g["n"] += 1
        g["model"] = a.model
    if not groups:
        return None
    f, g = max(groups.items(), key=lambda kv: (kv[1]["dollars"], kv[1]["n"]))
    return RecentUsage(f, g["model"], tuple(g["tokens"]), g["dollars"], g["n"])


def stretch(usage, target):
    """Combien de fois plus longtemps dureraient les mêmes tokens avec la famille `target`."""
    alt = costs.reprice(usage.tokens, REFERENCE[target]) if target in REFERENCE else None
    if not alt or usage.dollars <= 0:
        return None
    return usage.dollars / alt


def stretch_text(n):
    if n >= MAX_STRETCH_SHOWN:
        return f"plus de ×{MAX_STRETCH_SHOWN}"
    n = round(n, 1)
    return f"×{n:.0f}" if n == int(n) else f"×{core.fr(n)}"


_TAILS = OrderedDict()   # chemin -> ((taille, mtime_ns), [Answer])
_TAILS_MAX = 64
_LOCK = threading.Lock()


def clear_cache():
    with _LOCK:
        _TAILS.clear()


def _read_tail(path):
    with open(path, "rb") as fh:
        size = fh.seek(0, 2)
        start = max(0, size - TAIL_BYTES)
        fh.seek(start)
        data = fh.read()
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]  # première ligne coupée par la lecture de la fin
    return costs.parse_lines(lines)


def tail_answers(path):
    """Réponses de la fin d'un journal, relues seulement s'il a changé."""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return []
    key, stamp = str(path), (st.st_size, st.st_mtime_ns)
    with _LOCK:
        hit = _TAILS.get(key)
        if hit and hit[0] == stamp:
            _TAILS.move_to_end(key)
            return hit[1]
    try:
        answers = _read_tail(path)
    except OSError:
        return []
    with _LOCK:
        _TAILS[key] = (stamp, answers)
        _TAILS.move_to_end(key)
        while len(_TAILS) > _TAILS_MAX:
            _TAILS.popitem(last=False)
    return answers


def recent_usage(now, projects_dir=None):
    """Usage des 30 dernières minutes d'après les conversations écrites récemment."""
    projects_dir = Path(projects_dir or core.paths().config_dir / "projects")
    if not projects_dir.is_dir():
        return None
    since = (now - RECENT).timestamp()
    answers = []
    for f in projects_dir.glob("*/*.jsonl"):
        try:
            if f.stat().st_mtime < since:
                continue
        except OSError:
            continue
        answers += [a for a in tail_answers(f) if a.ts >= since]
    return summarize(answers)


# --------------------------------------------------------------------------
# Conseil
# --------------------------------------------------------------------------

@dataclass
class ModelAdvice:
    account: str
    kind: str          # "session" | "weekly"
    percent: float
    window: object     # fin de la fenêtre de 5 h en cours (clé de dédoublonnage)
    family: str
    target: str
    stretch: float


def _over(acc, threshold, now):
    """(limite la plus haute au-dessus du seuil, %) ou None."""
    best = None
    for kind, lim in (("session", acc.session), ("weekly", acc.weekly)):
        pct = effective_percent(lim, now)
        if lim is not None and pct >= threshold and (best is None or pct > best[1]):
            best = (kind, pct)
    return best


def advice_for(acc, usage, cfg, now):
    """Conseil pour le compte actif (pur), ou None."""
    over = _over(acc, cfg.get("model_advice_pct", 80), now)
    if over is None or usage is None:
        return None
    target = CHEAPER.get(usage.family)
    n = stretch(usage, target) if target else None
    if n is None or n < MIN_STRETCH:
        return None
    window = acc.session.resets_at if acc.session is not None else acc.weekly.resets_at
    return ModelAdvice(acc.name, over[0], over[1], window, usage.family, target, n)


def alert_key(acc):
    window = acc.session.resets_at if acc.session is not None else (
        acc.weekly.resets_at if acc.weekly is not None else None)
    return f"model_advice:{acc.name}:{window_id(window)}"


def alert_for(advice):
    cur, target = LABELS.get(advice.family, advice.family), LABELS.get(advice.target, advice.target)
    return Alert(
        f"model_advice:{advice.account}:{window_id(advice.window)}",
        f"{advice.account} : {KIND_LABELS[advice.kind]} à {advice.percent:.0f} % avec {cur}",
        f"Passer à {target} (/model {advice.target}) ferait durer ce qui reste environ "
        f"{stretch_text(advice.stretch)}, d'après les tarifs de l'API appliqués à tes réponses des "
        f"30 dernières minutes (ordre de grandeur : les limites ne suivent pas exactement ces tarifs).",
        1)


def pending(acc, cfg, now, sent_keys, usage_source=None):
    """Notification à envoyer pour le compte actif : seuil vérifié d'abord (sans lecture),
    journaux lus seulement si le conseil de cette fenêtre n'a pas encore été donné."""
    if acc is None or not cfg.get("model_advice", True):
        return None
    if _over(acc, cfg.get("model_advice_pct", 80), now) is None or alert_key(acc) in sent_keys:
        return None
    usage = (usage_source or recent_usage)(now)
    advice = advice_for(acc, usage, cfg, now)
    return alert_for(advice) if advice else None


# --------------------------------------------------------------------------
# Ligne d'état
# --------------------------------------------------------------------------

def _payload_model(model):
    if isinstance(model, dict):
        return model.get("id") or model.get("display_name")
    return model


def statusline_hint(state, model, settings, now):
    """« → sonnet ? » quand le compte actif dépasse le seuil avec un modèle cher, sinon ""."""
    cfg = settings["alerts"]
    if not cfg.get("model_advice", True):
        return ""
    target = CHEAPER.get(family(_payload_model(model)))
    if not target:
        return ""
    active = (state or {}).get("active")
    acc = next((a for a in (state or {}).get("accounts") or [] if a.get("name") == active), None)
    for lim in (acc or {}).get("limits") or []:
        if lim.get("kind") not in ("session", "weekly_all"):
            continue
        reset = core.parse_dt(lim.get("resets_at"))
        if reset is not None and reset <= now:
            continue
        if float(lim.get("percent") or 0) >= cfg.get("model_advice_pct", 80):
            return f"→ {target} ?"
    return ""
