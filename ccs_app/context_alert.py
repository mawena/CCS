"""Alerte de contexte lourd : une conversation dont le contexte dépasse un seuil.

Taille du contexte = dernier usage de réponse du journal : `input_tokens` +
`cache_read_input_tokens` + `cache_creation_input_tokens` (ce que le modèle relit à chaque
message). Seule la fin du journal est lue. Au-delà du seuil (150 000 tokens par défaut),
une seule notification par session, avec le coût d'un message en équivalent dollars (prix de
lecture du cache du modèle, `costs`) et le conseil `/compact` ou nouvelle session.

L'état « déjà prévenu » est un petit fichier du store (`context-alerts.json`, 600), purgé des
sessions terminées ; si le contexte retombe sous le seuil (après un `/compact`), la session
pourra être signalée de nouveau. Une lecture impossible ne lève jamais.

Compactage automatique (`auto_compact`, désactivé par défaut) : dans un chat, CCS envoie
`/compact` lui-même quand le contexte dépasse ce même seuil, entre deux tours. La décision
(`AutoCompact`) est commune au pont (chats du serveur) et au bureau (chats locaux).
"""

import json
import os
import time
from dataclasses import dataclass

from . import core, costs, sessions
from .alerts import Alert

DEFAULTS = {"enabled": True, "threshold_tokens": 150_000, "auto_compact": False}
COMPACT_KEEP = 0.2            # part du contexte gardée après `/compact` (moyenne estimée)
TAIL_BYTES = 256 * 1024
TAIL_MAX = 4 * 1024 * 1024    # une réponse d'outil énorme peut éloigner le dernier usage
STATE_FILE = "context-alerts.json"


def config(settings=None):
    """Section `context_alert` des réglages avec repli sur les valeurs par défaut."""
    raw = (settings or {}).get("context_alert")
    raw = raw if isinstance(raw, dict) else {}
    try:
        threshold = int(raw.get("threshold_tokens", DEFAULTS["threshold_tokens"]))
    except (TypeError, ValueError):
        threshold = DEFAULTS["threshold_tokens"]
    if threshold <= 0:
        threshold = DEFAULTS["threshold_tokens"]
    out = {"threshold_tokens": threshold}
    for key in ("enabled", "auto_compact"):
        value = raw.get(key, DEFAULTS[key])
        out[key] = value if isinstance(value, bool) else DEFAULTS[key]
    return out


def auto_on(cfg):
    """Le compactage automatique est-il demandé ? Il suit l'alerte : sans elle, rien ne se fait."""
    return bool(cfg and cfg.get("enabled") and cfg.get("auto_compact"))


def compact_gain(tokens):
    """Jetons libérés (estimation) par `/compact` d'un contexte de `tokens` jetons."""
    return tokens - int(tokens * COMPACT_KEEP)


# --------------------------------------------------------------------------
# Lecture du contexte
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Context:
    tokens: int
    model: str


def _int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _last_usage(lines):
    """Dernière réponse de la conversation principale (hors sous-agents et messages
    synthétiques) dans `lines` ; None s'il n'y en a pas."""
    for raw in reversed(lines):
        if b'"usage"' not in raw or b'"assistant"' not in raw:
            continue
        try:
            d = json.loads(raw)
            msg = d["message"]
            usage = msg["usage"]
            model = str(msg.get("model") or "")
            if d.get("type") != "assistant" or d.get("isSidechain") or model == "<synthetic>":
                continue
            tokens = (_int(usage.get("input_tokens")) + _int(usage.get("cache_read_input_tokens"))
                      + _int(usage.get("cache_creation_input_tokens")))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if tokens:
            return Context(tokens, model)
    return None


def read_context(path):
    """Taille du contexte d'après la fin du journal `path`, ou None (absent, vide, illisible).
    La fin est relue de plus en plus large tant qu'aucune réponse n'y figure."""
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            span = TAIL_BYTES
            while True:
                start = max(0, size - span)
                fh.seek(start)
                lines = fh.read(size - start).split(b"\n")
                if start > 0:
                    lines = lines[1:]  # première ligne coupée
                found = _last_usage(lines)
                if found or start == 0 or span >= TAIL_MAX:
                    return found
                span *= 4
    except OSError:
        return None


def session_context(session):
    """Contexte d'une session ouverte (journal de sa conversation), ou None."""
    path = sessions.journal_path(session)
    return read_context(path) if path else None


def contexts_for(found):
    """{pid: Context ou None} pour la page Sessions (badges)."""
    return {s.pid: session_context(s) for s in found}


# --------------------------------------------------------------------------
# Coût d'un message
# --------------------------------------------------------------------------

def message_cost(context):
    """Coût en dollars de la relecture du contexte (un message de plus), au prix de lecture
    du cache du modèle ; None si le modèle est inconnu."""
    key = costs.normalize_model(context.model)
    price = costs.PRICES.get(key)
    if price is None:
        return None
    long_prompt = costs.LONG_PROMPT.get(key)
    if long_prompt and context.tokens > long_prompt[0]:
        price = long_prompt[1]
    return context.tokens * price.cache_read / 1e6


def is_heavy(context, settings=None):
    cfg = config(settings)
    return bool(cfg["enabled"] and context is not None and context.tokens >= cfg["threshold_tokens"])


# --------------------------------------------------------------------------
# Textes
# --------------------------------------------------------------------------

def _k(tokens):
    return f"{round(tokens / 1000)} k"


def badge_text(context):
    """Texte court du badge d'une carte : « contexte lourd · 182 k »."""
    return f"contexte lourd · {_k(context.tokens)}"


def statusline_hint(context, settings=None):
    """Avertissement court de la ligne d'état de Claude Code ; « » si le contexte est léger."""
    return f"⚠ contexte {_k(context.tokens)}" if is_heavy(context, settings) else ""


def advice_text(context):
    dollars = message_cost(context)
    cost = (f" : chaque message coûte environ {costs.format_dollars(dollars)} (équivalent API)"
            if dollars is not None else "")
    return (f"Le contexte atteint {_k(context.tokens)} tokens{cost}. Tape /compact pour le résumer, "
            "ou ouvre une nouvelle session.")


def alert_for(session, context):
    """Notification (une seule par session) ; un clic ouvre l'application sur la session."""
    from .attention import SHOW_PREFIX, session_ref
    show = SHOW_PREFIX + session_ref(session)
    return Alert(f"context:{session.session_id}", f"Contexte lourd dans {session.project}",
                 advice_text(context), 1, ((show, "Afficher"),), default=show)


# --------------------------------------------------------------------------
# État « déjà prévenu »
# --------------------------------------------------------------------------

def state_path():
    return core.paths().store / STATE_FILE


def load_state():
    """{identifiant de conversation: date de l'alerte} ; {} si le fichier est absent ou illisible."""
    raw = core.load_json(state_path()).get("notified")
    if not isinstance(raw, dict):
        return {}
    return {str(k): float(v) for k, v in raw.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def save_state(notified):
    """Écrit l'état (600) ; une écriture impossible n'est pas fatale (False)."""
    path = state_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        core.atomic_write_json(path, {"notified": notified})
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def decide(found, contexts, settings, notified, now):
    """Décision pure : (alertes à envoyer, nouvel état « déjà prévenu »).

    `contexts` : {pid: Context ou None}. Une session déjà signalée ne l'est plus tant que son
    contexte reste lourd (ou illisible) ; l'état ne garde que les sessions encore ouvertes."""
    cfg = config(settings)
    new, out = {}, []
    for s in found:
        if not s.session_id or s.session_id in new:
            continue
        ctx = contexts.get(s.pid)
        heavy = cfg["enabled"] and ctx is not None and ctx.tokens >= cfg["threshold_tokens"]
        if s.session_id in notified and (heavy or ctx is None):
            new[s.session_id] = notified[s.session_id]
        elif heavy:
            new[s.session_id] = now
            out.append(alert_for(s, ctx))
    return out, new


def tick(found, settings=None, now=None):
    """Lit les journaux des sessions ouvertes `found`, renvoie les alertes à envoyer (par
    l'appelant) et met à jour le fichier d'état. Une session déjà signalée ne l'est jamais
    deux fois. Désactivé : aucune lecture, aucune écriture."""
    if not config(settings)["enabled"]:
        return []
    now = time.time() if now is None else now
    notified = load_state()
    alerts, new = decide(found, contexts_for(found), settings, notified, now)
    if new != notified:
        save_state(new)
    return alerts


# --------------------------------------------------------------------------
# Compactage automatique des chats
# --------------------------------------------------------------------------

COMPACT_COMMAND = "/compact"


class AutoCompact:
    """Compactage automatique d'un chat : état et décision, sans entrée-sortie. Le pont (chats
    du serveur) et le bureau (chats locaux) lui passent ce qu'ils voient du moteur :

      measured(cfg, tokens)  après chaque mesure du contexte : « compact » (envoyer `/compact`
                             si Claude est au repos, puis appeler `sent`), « stuck » (à dire une
                             fois : le contexte est resté lourd après le compactage) ou None ;
      sent(ok)               `/compact` est parti, ou non (Claude n'était plus au repos) ;
      on_compacted()         la conversation vient d'être compactée ;
      on_state(state)        le moteur change d'état : « failed » (à dire : le compactage
                             demandé n'a pas abouti) ou None ;
      on_turn(ok)            un tour de Claude est fini.

    Jamais deux compactages de suite : après un compactage, rien ne repart tant que le contexte
    n'est pas repassé sous le seuil ; après un compactage qui n'a pas abouti (limite d'usage,
    arrêt), rien avant la fin réussie d'un nouveau tour."""

    def __init__(self):
        self.state = "armed"          # armed | fired | check | stuck | failed
        self._compacted = False       # un compactage a eu lieu depuis l'envoi de `/compact`

    def measured(self, cfg, tokens):
        if not auto_on(cfg):
            self.state = "armed"
            return None
        if self.state == "fired":     # mesure prise avant la fin du compactage en cours
            return None
        if tokens < cfg["threshold_tokens"]:
            self.state = "armed"
            return None
        if self.state == "armed":
            self.state, self._compacted = "fired", False
            return "compact"
        if self.state == "check":
            self.state = "stuck"
            return "stuck"
        return None

    def sent(self, ok):
        if not ok and self.state == "fired":
            self.state = "armed"      # pas parti : nouvelle décision à la prochaine mesure

    def on_compacted(self):
        self._compacted = True

    def on_state(self, state):
        if self.state != "fired" or state not in ("idle", "stopped", "suspended"):
            return None
        if state == "idle" and self._compacted:
            self.state = "check"      # la prochaine mesure dit si le contexte est redescendu
            return None
        self.state = "failed"
        return "failed"

    def on_turn(self, ok):
        if ok and self.state == "failed":
            self.state = "armed"


def _grouped(tokens):
    """152000 → « 152 000 » (espace insécable fine)."""
    return f"{int(tokens):,}".replace(",", " ")


def auto_note(kind, tokens=0):
    """(texte, genre) de la note écrite dans le fil pour une décision de `AutoCompact`."""
    if kind == "compact":
        return f"Compactage automatique : contexte de {_grouped(tokens)} jetons.", "info"
    if kind == "stuck":
        return (f"Contexte encore lourd après le compactage ({_grouped(tokens)} jetons) : pas de nouveau "
                "compactage automatique tant qu'il ne repasse pas sous le seuil.", "warning")
    return "Compactage automatique non abouti : nouvel essai après le prochain tour.", "warning"
