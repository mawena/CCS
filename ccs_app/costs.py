"""Coût d'une conversation Claude Code : tokens par type et équivalent en dollars au
tarif de l'API Anthropic.

Un abonnement Claude (Pro, Max…) ne facture pas au token : le montant affiché est
seulement ce que la même conversation aurait coûté via l'API, pour comparer des
conversations entre elles. Les tokens viennent de `message.usage` de chaque réponse
du journal ; une réponse écrite sur plusieurs lignes (une par bloc de contenu, même
identifiant, même usage) n'est comptée qu'une fois. Les sous-agents de la conversation
(`<session>/subagents/*.jsonl`) sont inclus par défaut.
"""

import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from . import core, transcripts

# --------------------------------------------------------------------------
# Tarifs de l'API ($ par million de tokens)
# --------------------------------------------------------------------------
#
# Source : skill « claude-api » livré avec Claude Code 2.1.319 — table « Current
# Models (cached: 2026-10-06) » pour l'entrée et la sortie, guide de migration et
# guide du cache pour les lectures du cache par modèle et les écritures (1,25 × l'entrée
# pour le cache de 5 min, 2 × pour celui d'une heure). Relu le 2026-11-06 ; la page
# officielle (platform.claude.com/docs/en/about-claude/pricing) n'a pas pu être
# consultée depuis le poste ce jour-là.
#
# Modèles absents (Opus 4.5, Sonnet 4.5, Opus 4.1 et plus anciens) : volontairement
# non renseignés faute de source à jour — leurs réponses sont comptées en tokens et
# signalées « tarif inconnu », jamais estimées au hasard.

PRICES_DATE = "2026-10-06"
PRICES_SOURCE = ("skill claude-api de Claude Code 2.1.319 (table « Current Models », cache du "
                 "2026-10-06, guide de migration et guide du cache), tarifs de l'API Anthropic")

CACHE_WRITE_5M = 1.25   # × prix d'entrée
CACHE_WRITE_1H = 2.0    # × prix d'entrée


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


def _price(input_, output, cache_read):
    return Price(input_, output, input_ * CACHE_WRITE_5M, input_ * CACHE_WRITE_1H, cache_read)


PRICES = {
    # Fable / Mythos 5.1 : lecture du cache à 0,025 × l'entrée.
    "claude-fable-5-1": _price(10.00, 50.00, 0.25),
    "claude-mythos-5-1": _price(10.00, 50.00, 0.25),
    # Fable / Mythos 5 : même tarif, lecture du cache à 1 $.
    "claude-fable-5": _price(10.00, 50.00, 1.00),
    "claude-mythos-5": _price(10.00, 50.00, 1.00),
    # Opus 5.5 : lecture du cache à 0,05 × l'entrée.
    "claude-opus-5-5": _price(4.00, 20.00, 0.20),
    "claude-opus-5": _price(5.00, 25.00, 0.50),
    "claude-opus-4-8": _price(5.00, 25.00, 0.50),
    "claude-opus-4-7": _price(5.00, 25.00, 0.50),
    "claude-opus-4-6": _price(5.00, 25.00, 0.50),
    "claude-sonnet-5-5": _price(2.00, 10.00, 0.20),
    "claude-sonnet-5": _price(2.00, 10.00, 0.20),
    "claude-sonnet-4-6": _price(3.00, 15.00, 0.30),
    # Haiku 5.5 : grille pour un prompt de 100 000 tokens au plus (voir LONG_PROMPT).
    "claude-haiku-5-5": _price(0.10, 0.50, 0.01),
    "claude-haiku-4-5": _price(1.00, 5.00, 0.10),
}

# Grille plus chère au-delà d'une taille de prompt (entrée + cache écrit + cache lu).
LONG_PROMPT = {
    "claude-haiku-5-5": (100_000, _price(0.50, 2.50, 0.05)),
}

# Mode rapide (`usage.speed == "fast"`) : 2 × le tarif standard (8 $ / 40 $ pour Opus 5.5,
# 10 $ / 50 $ pour Opus 5). Le multiplicateur est appliqué à tous les types de tokens.
# Ailleurs (Opus 4.8…), le tarif rapide n'est pas documenté : tarif inconnu.
FAST_MULTIPLIER = {
    "claude-opus-5-5": 2.0,
    "claude-opus-5": 2.0,
}

# Inférence limitée aux États-Unis (`usage.inference_geo == "us"`) : 1,1 × le prix.
GEO_MULTIPLIER = {"us": 1.1}

TOKEN_TYPES = ("entree", "sortie", "cache_ecriture", "cache_lecture")
DATE_SUFFIX = re.compile(r"-\d{8}$")
GEO_PREFIX = re.compile(r"^(?:[a-z]{2,6}\.)?anthropic\.")


def normalize_model(model):
    """Nom de modèle sans préfixe de plateforme, date, version Bedrock ni suffixe « [1m] »."""
    m = str(model or "").strip().lower()
    m = GEO_PREFIX.sub("", m)
    m = m.split("@", 1)[0]
    m = re.sub(r"\[[^\]]*\]$", "", m)
    m = re.sub(r"-v\d+(?::\d+)?$", "", m)
    return DATE_SUFFIX.sub("", m)


def price_for(model):
    """Tarif standard du modèle, ou None s'il est inconnu."""
    return PRICES.get(normalize_model(model)) if model else None


# --------------------------------------------------------------------------
# Résultat
# --------------------------------------------------------------------------

def _zero():
    return dict.fromkeys(TOKEN_TYPES, 0)


@dataclass
class ModelCost:
    tokens_par_type: dict = field(default_factory=_zero)
    dollars: float | None = 0.0      # None : tarif inconnu pour ce modèle
    reponses: int = 0

    @property
    def total_tokens(self):
        return sum(self.tokens_par_type.values())


@dataclass
class Cost:
    tokens_par_type: dict           # {"entree", "sortie", "cache_ecriture", "cache_lecture"} -> tokens
    dollars: float                  # équivalent API ; minimum si `inconnu`
    modeles: dict                   # nom du modèle -> ModelCost
    inconnu: bool                   # au moins une réponse sans tarif connu
    reponses: int = 0

    @classmethod
    def empty(cls):
        return cls(_zero(), 0.0, {}, False, 0)

    @property
    def total_tokens(self):
        return sum(self.tokens_par_type.values())

    @property
    def modeles_inconnus(self):
        return [m for m, mc in self.modeles.items() if mc.dollars is None]

    def __add__(self, other):
        models = {}
        for src in (self.modeles, other.modeles):
            for name, mc in src.items():
                cur = models.setdefault(name, ModelCost())
                for k in TOKEN_TYPES:
                    cur.tokens_par_type[k] += mc.tokens_par_type.get(k, 0)
                cur.dollars = None if cur.dollars is None or mc.dollars is None else cur.dollars + mc.dollars
                cur.reponses += mc.reponses
        tokens = {k: self.tokens_par_type.get(k, 0) + other.tokens_par_type.get(k, 0) for k in TOKEN_TYPES}
        return Cost(tokens, self.dollars + other.dollars, models, self.inconnu or other.inconnu,
                    self.reponses + other.reponses)


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

def _int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _usage_tokens(u):
    """(entrée, sortie, cache écrit 5 min, cache écrit 1 h, cache lu)."""
    written = _int(u.get("cache_creation_input_tokens"))
    detail = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    w1h = _int(detail.get("ephemeral_1h_input_tokens"))
    w5m = _int(detail.get("ephemeral_5m_input_tokens"))
    # Détail absent ou incomplet : le reste est compté au tarif de 5 min.
    w5m += max(0, written - w5m - w1h)
    return (_int(u.get("input_tokens")), _int(u.get("output_tokens")), w5m, w1h,
            _int(u.get("cache_read_input_tokens")))


def _dollars(model, usage, tokens):
    key = normalize_model(model)
    price = PRICES.get(key)
    if price is None:
        return None
    inp, out, w5m, w1h, read = tokens
    long_prompt = LONG_PROMPT.get(key)
    if long_prompt and inp + w5m + w1h + read > long_prompt[0]:
        price = long_prompt[1]
    mult = 1.0
    if usage.get("speed") == "fast":
        if key not in FAST_MULTIPLIER:
            return None
        mult *= FAST_MULTIPLIER[key]
    mult *= GEO_MULTIPLIER.get(usage.get("inference_geo"), 1.0)
    total = (inp * price.input + out * price.output + w5m * price.cache_write_5m
             + w1h * price.cache_write_1h + read * price.cache_read)
    return total * mult / 1e6


def _read_file(path):
    """Coût d'un seul journal (lecture en flux, lignes illisibles ignorées)."""
    answers = {}
    try:
        fh = open(path, "rb")
    except OSError:
        return Cost.empty()
    with fh:
        for n, raw in enumerate(fh):
            if b'"assistant"' not in raw or b'"usage"' not in raw:
                continue
            try:
                d = json.loads(raw)
                if d.get("type") != "assistant":
                    continue
                msg = d["message"]
                usage = msg["usage"]
                model = msg.get("model") or "inconnu"
                if not isinstance(usage, dict) or model == "<synthetic>":
                    continue
                tokens = _usage_tokens(usage)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if not any(tokens):
                continue
            answers[msg.get("id") or f"ligne-{n}"] = (model, usage, tokens)
    total = Cost.empty()
    for model, usage, tokens in answers.values():
        inp, out, w5m, w1h, read = tokens
        by_type = {"entree": inp, "sortie": out, "cache_ecriture": w5m + w1h, "cache_lecture": read}
        dollars = _dollars(model, usage, tokens)
        mc = ModelCost(dict(by_type), dollars, 1)
        total = total + Cost(by_type, dollars or 0.0, {model: mc}, dollars is None, 1)
    return total


_CACHE = OrderedDict()   # chemin -> ((taille, mtime_ns), Cost)
_CACHE_MAX = 512
_LOCK = threading.Lock()


def clear_cache():
    with _LOCK:
        _CACHE.clear()


def file_cost(path):
    """Coût d'un journal, relu seulement s'il a changé (taille ou date de modification)."""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return Cost.empty()
    key, stamp = str(path), (st.st_size, st.st_mtime_ns)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == stamp:
            _CACHE.move_to_end(key)
            return hit[1]
    cost = _read_file(path)
    with _LOCK:
        _CACHE[key] = (stamp, cost)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return cost


def subagent_files(path):
    d = Path(path).with_suffix("") / "subagents"
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def conversation_cost(path, subagents=True):
    """Coût d'une conversation (`~/.claude/projects/<projet>/<id>.jsonl`), sous-agents
    compris sauf si `subagents` est faux."""
    total = file_cost(path)
    if subagents:
        for f in subagent_files(path):
            total = total + file_cost(f)
    return total


# --------------------------------------------------------------------------
# Formats
# --------------------------------------------------------------------------

def format_dollars(value):
    if value <= 0:
        return "0 $"
    if value < 0.01:
        return "< 0,01 $"
    if value >= 1000:
        return f"{value:,.0f}".replace(",", " ") + " $"
    return f"{core.fr(value, 2)} $"


def _tokens(n):
    return f"{transcripts.fmt_tokens(n)} token{'s' if n > 1 else ''}"


def _amount(dollars, unknown, partial_label):
    if unknown and not dollars:
        return "tarif inconnu"
    text = format_dollars(dollars)
    if unknown:
        return f"≥ {text} ({partial_label})"
    return text if text.startswith("<") else f"≈ {text}"


def format_cost(cost):
    """« 1,2 M tokens · ≈ 3,40 $ »."""
    if not cost.reponses and not cost.total_tokens:
        return "aucun usage enregistré"
    return f"{_tokens(cost.total_tokens)} · {_amount(cost.dollars, cost.inconnu, 'tarif inconnu pour une partie')}"


def format_details(cost):
    """Une ligne par modèle, du plus cher au moins cher."""
    rows = sorted(cost.modeles.items(), key=lambda kv: (kv[1].dollars is None, -(kv[1].dollars or 0)))
    out = []
    for name, mc in rows:
        amount = "tarif inconnu" if mc.dollars is None else _amount(mc.dollars, False, "")
        out.append(f"{name} : {_tokens(mc.total_tokens)} · {amount} "
                   f"({mc.reponses} réponse{'s' if mc.reponses > 1 else ''})")
    return out
