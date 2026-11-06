"""Conseiller de formule : combien de comptes Pro, Max ou Ultra pour l'usage réel.

Le besoin se lit dans l'historique des relevés (`store`) : chaque hausse du
pourcentage d'une limite est convertie en « unités Pro » selon la formule du compte
(1 % d'un Max vaut 5 % d'un Pro). On obtient, par semaine glissante de 7 jours, la
consommation hebdomadaire totale et le pic de consommation sur 5 h, tous comptes
confondus (CCS bascule d'un compte à l'autre : plusieurs comptes s'additionnent).
Les semaines où tous les comptes étaient épuisés sont majorées : l'usage mesuré y
était bridé. La combinaison conseillée est la moins chère qui couvre le besoin le
plus haut, marge comprise.

L'équivalent en dollars vient des journaux locaux de Claude Code (`costs`), au tarif
de l'API : c'est ce que le même usage aurait coûté sans abonnement.
"""

import itertools
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import core, costs

# --------------------------------------------------------------------------
# Formules et tarifs ($ par mois, facturation mensuelle)
# --------------------------------------------------------------------------
#
# Source : https://claude.com/pricing, consultée le 2026-11-06 :
#  - Pro : 20 $/mois en facturation mensuelle (17 $/mois en annuel, 200 $ payés d'avance) ;
#    sert de référence (« 1x ») pour la limite de 5 h et la limite hebdomadaire.
#  - Max : 100 $/mois, « 5x Pro usage every 5 hours and every week ».
#  - Ultra (l'ancien Max 20x, lien « plan=max_20x ») : 200 $/mois, « No 5-hour limit »
#    (comptes vérifiés) et « 10x Pro usage every week ».
# Prix hors taxes, « subject to change » : surchargeables par le réglage
# `advisor.plan_prices` ({"pro": 20, "max5": 100, "max20": 200}).

PLAN_PRICES_DATE = "2026-11-06"
PLAN_PRICES_SOURCE = "claude.com/pricing"
PLAN_PRICES_MAX_AGE_DAYS = 120   # au-delà, les tarifs sont signalés « à vérifier »


@dataclass(frozen=True)
class Plan:
    key: str
    label: str
    price: float            # $ par mois
    session: float | None   # capacité par fenêtre de 5 h, en unités Pro (None : pas de limite)
    weekly: float           # capacité par semaine, en unités Pro


PLANS = {
    "pro": Plan("pro", "Pro", 20.0, 1.0, 1.0),
    "max5": Plan("max5", "Max", 100.0, 5.0, 5.0),
    "max20": Plan("max20", "Ultra", 200.0, None, 10.0),
}
# Ordre d'affichage dans une combinaison : la plus grosse formule d'abord.
DISPLAY_ORDER = ("max20", "max5", "pro")

WEEK = timedelta(days=7)
SESSION_S = 5 * 3600
SAME_WINDOW_S = 30 * 60      # deux heures de réinitialisation à moins de 30 min : même fenêtre
DROP_POINTS = 1.0            # baisse au-delà de laquelle une nouvelle fenêtre a commencé
LIMIT_HIT = 99.0             # % à partir duquel une limite est considérée atteinte
MIN_COVERAGE = 0.5           # part d'une semaine couverte par les relevés pour la compter
CAPPED_BONUS = 0.15          # majoration d'une semaine bridée (tous les comptes épuisés)
BLOCK_SWITCH_S = 180         # un blocage suivi d'une bascule dans ce délai n'a rien bridé
DAYS_PER_MONTH = 30.44
MIN_HISTORY_S = 3 * 86400    # collecte minimale avant de conseiller
PROJECT_AFTER_S = 86400      # semaine en cours projetée à son rythme après un jour


def plan_key(subscription, tier=None):
    """Clé de formule (« pro », « max5 », « max20 ») d'après le compte, ou None."""
    s = str(subscription or "").strip().lower()
    t = str(tier or "").strip().lower()
    if "20x" in t or s in ("ultra", "max20", "max_20x"):
        return "max20"
    if s in ("max", "max5", "max_5x") or "max" in t:
        return "max5"
    if s == "pro":
        return "pro"
    return None


def _tier(name):
    """Palier de débit du profil (« default_claude_max_20x »…), seul champ lu de sa connexion."""
    oauth = core.load_json(core.paths().store / name / "oauth.json").get("claudeAiOauth")
    tier = oauth.get("rateLimitTier") if isinstance(oauth, dict) else None
    return tier if isinstance(tier, str) else None


def detect_plans(profiles, overrides, tiers=None):
    """({profil: clé}, [Max au palier supposé], [(profil, formule inconnue)])."""
    plans, uncertain, unknown = {}, [], []
    for p in profiles:
        forced = (overrides or {}).get(p.name)
        if forced in PLANS:
            plans[p.name] = forced
            continue
        tier = tiers.get(p.name) if tiers is not None else _tier(p.name)
        key = plan_key(p.plan, tier)
        if key is None:
            unknown.append((p.name, p.plan))
            continue
        plans[p.name] = key
        if key == "max5" and not tier and str(p.plan).lower() == "max":
            uncertain.append(p.name)
    return plans, uncertain, unknown


def plan_prices(settings):
    """({clé: prix retenu}, tarifs personnalisés ?) ; une surcharge invalide est ignorée."""
    prices = {k: p.price for k, p in PLANS.items()}
    custom = False
    for key, value in (settings.get("advisor", {}).get("plan_prices") or {}).items():
        if key in prices and isinstance(value, (int, float)) and not isinstance(value, bool) \
                and value >= 0:
            prices[key] = float(value)
            custom = True
    return prices, custom


def prices_stale(now):
    dated = datetime.fromisoformat(PLAN_PRICES_DATE).replace(tzinfo=timezone.utc)
    return now - dated > timedelta(days=PLAN_PRICES_MAX_AGE_DAYS)


# --------------------------------------------------------------------------
# Consommation mesurée
# --------------------------------------------------------------------------

def increments(samples):
    """Hausses de pourcentage entre relevés successifs : [(ts, points)].

    `samples` : [(ts, %, réinitialisation en secondes ou None)] triés. Une fenêtre
    nouvelle (réinitialisation passée, heure de réinitialisation déplacée, forte baisse)
    repart de 0 ; le premier relevé ne sert que de point de départ."""
    out, prev = [], None
    for ts, pct, reset in samples:
        if prev is not None:
            pts, ppct, preset = prev
            new_window = ((preset is not None and ts >= preset)
                          or (reset is not None and preset is not None
                              and reset - preset > SAME_WINDOW_S)
                          or pct < ppct - DROP_POINTS)
            delta = pct if new_window else pct - ppct
            if delta > 0:
                out.append((ts, delta))
        prev = (ts, pct, reset)
    return out


@dataclass(frozen=True)
class Window:
    start: float           # début de la fenêtre (secondes)
    end: float             # réinitialisation
    usage: float           # % le plus haut relevé (projeté pour une semaine en cours)
    hit_at: float | None   # premier relevé à la limite


def windows(rows, span, now_ts):
    """Fenêtres d'une limite d'après ses relevés [(ts, %, réinitialisation)] triés.

    Les pourcentages sont cumulés dans une fenêtre : le plus haut relevé donne tout
    l'usage de la fenêtre, même vue en cours de route (claude.ai et les autres appareils
    compris). Une fenêtre hebdomadaire en cours depuis plus d'un jour est projetée à son
    rythme moyen (plafonné à 100 %)."""
    span_s = span.total_seconds() if isinstance(span, timedelta) else float(span)
    groups = []
    for ts, pct, reset in rows:
        if reset is None or ts >= reset:
            continue  # pas de fenêtre en cours, ou relevé périmé
        if not groups or abs(reset - groups[-1]["end"]) > SAME_WINDOW_S:
            groups.append({"end": reset, "usage": pct, "hit": None})
        g = groups[-1]
        g["usage"] = max(g["usage"], pct)
        if pct >= LIMIT_HIT and g["hit"] is None:
            g["hit"] = ts
    out = []
    for g in groups:
        start, usage = g["end"] - span_s, g["usage"]
        elapsed = now_ts - start
        if span_s > SESSION_S and g["end"] > now_ts and elapsed >= PROJECT_AFTER_S:
            usage = min(100.0, usage * span_s / elapsed)
        out.append(Window(start, g["end"], usage, g["hit"]))
    return out


def _blocked(events):
    """Instants où l'usage a été bridé : tous les comptes épuisés, ou blocage (hook) sans
    bascule dans les minutes qui suivent."""
    switches = [e.ts for e in events if e.type == "switch"]
    out = []
    for e in events:
        key = str((e.detail or {}).get("key") or "")
        if e.type != "alert":
            continue
        if key.startswith("exhausted:"):
            out.append(e.ts)
        elif e.profile == "blocage" and key.startswith("blocage:"):
            if not any(e.ts <= s <= e.ts + BLOCK_SWITCH_S for s in switches):
                out.append(e.ts)
    return out


def _average(wins, cap, s, e):
    """(usage moyen en unités Pro sur la partie connue de [s, e), part connue)."""
    covered = total = 0.0
    for w in wins:
        a, b = max(w.start, s), min(w.end, e)
        if b > a:
            covered += b - a
            total += w.usage / 100 * cap * (b - a)
    return (total / covered if covered else None), min(1.0, covered / (e - s))


def _concurrent_peak(spans, s, e):
    """Plus forte somme d'usages de fenêtres [(début, fin, unités)] ouvertes en même temps."""
    points = []
    for start, end, units in spans:
        a, b = max(start, s), min(end, e)
        if b > a and units > 0:
            points += [(a, 1, units), (b, 0, -units)]  # une fin passe avant un début simultané
    best = total = 0.0
    for _t, _order, delta in sorted(points):
        total += delta
        best = max(best, total)
    return best


@dataclass
class WeekNeed:
    start: datetime
    end: datetime
    weekly: float          # unités Pro consommées par semaine (moyenne des fenêtres des comptes)
    session_peak: float    # sessions Pro consommées dans des fenêtres de 5 h simultanées
    coverage: float        # part de la semaine où l'usage des comptes est connu
    limit_hits: int        # fenêtres menées jusqu'à la limite
    blocked: int           # moments bridés (tous comptes épuisés)

    @property
    def bonus(self):
        return 1 + CAPPED_BONUS if self.blocked else 1.0

    @property
    def need(self):
        return self.weekly * self.bonus

    @property
    def session_need(self):
        return self.session_peak * self.bonus


def week_needs(samples, plans, now, weeks, events=()):
    """Besoin des `weeks` dernières semaines glissantes (la plus récente d'abord), sans les
    semaines trop peu connues : ([WeekNeed], nombre de semaines ignorées).

    Rien avant 3 jours de relevés. Chaque compte compte pour l'usage de ses propres
    fenêtres : une semaine glissante à cheval sur deux fenêtres ne compte jamais double."""
    now_ts = now.timestamp()
    weekly, sessions, hits = {}, [], []
    first = None
    for name, kinds in samples.items():
        plan = PLANS.get(plans.get(name))
        if plan is None:
            continue
        for rows in kinds.values():
            if rows:
                first = rows[0][0] if first is None else min(first, rows[0][0])
        wins = windows(kinds.get("weekly_all") or [], WEEK, now_ts)
        if wins:
            weekly[name] = (wins, plan.weekly)
        hits += [w.hit_at for w in wins if w.hit_at is not None]
        swins = windows(kinds.get("session") or [], SESSION_S, now_ts)
        hits += [w.hit_at for w in swins if w.hit_at is not None]
        if plan.session is not None:
            sessions += [(w.start, w.end, w.usage / 100 * plan.session) for w in swins]
    if first is None or now_ts - first < MIN_HISTORY_S:
        return [], weeks
    blocked = _blocked(events)
    out, ignored = [], 0
    for i in range(weeks):
        end = now - i * WEEK
        start = end - WEEK
        s, e = start.timestamp(), end.timestamp()
        total, shares = 0.0, []
        for wins, cap in weekly.values():
            avg, share = _average(wins, cap, s, e)
            shares.append(share)
            total += avg or 0.0
        coverage = sum(shares) / len(shares) if shares else 0.0
        if coverage < MIN_COVERAGE:
            ignored += 1
            continue
        out.append(WeekNeed(
            start, end, weekly=total,
            session_peak=_concurrent_peak(sessions, s, e),
            coverage=coverage,
            limit_hits=sum(1 for t in hits if s <= t < e),
            blocked=sum(1 for t in blocked if s <= t < e)))
    return out, ignored


# --------------------------------------------------------------------------
# Combinaisons de formules
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Combo:
    counts: tuple    # ((clé, nombre), …) dans l'ordre d'affichage
    price: float     # $ par mois
    weekly: float    # unités Pro par semaine
    session: float   # sessions Pro par fenêtre de 5 h (inf : sans limite de 5 h)
    accounts: int

    @property
    def label(self):
        parts = []
        for key, n in self.counts:
            name = PLANS[key].label
            parts.append(name if n == 1 else f"{n} {name}")
        return " + ".join(parts)


def combo_of(keys, prices):
    keys = [k for k in keys if k in PLANS]
    counts = tuple((k, keys.count(k)) for k in DISPLAY_ORDER if k in keys)
    session = 0.0
    for k in keys:
        cap = PLANS[k].session
        session = math.inf if cap is None else session + cap
    return Combo(counts, sum(prices[k] for k in keys), sum(PLANS[k].weekly for k in keys),
                 session, len(keys))


def combos(prices, max_accounts=3):
    out = []
    for n in range(1, max(1, int(max_accounts)) + 1):
        for keys in itertools.combinations_with_replacement(DISPLAY_ORDER, n):
            out.append(combo_of(list(keys), prices))
    return out


def recommend(weekly_target, session_target, prices, max_accounts=3):
    """(combinaison conseillée, combinaisons suffisantes triées par prix). Sans combinaison
    suffisante : la plus grande capacité."""
    cands = combos(prices, max_accounts)
    fits = sorted((c for c in cands if c.weekly >= weekly_target and c.session >= session_target),
                  key=lambda c: (c.price, c.accounts, -c.weekly))
    if fits:
        return fits[0], fits
    return max(cands, key=lambda c: (c.weekly, -c.price)), []


# --------------------------------------------------------------------------
# Conseil
# --------------------------------------------------------------------------

@dataclass
class Advice:
    weeks: list                 # WeekNeed retenues, la plus récente d'abord
    ignored: int                # semaines sans assez de relevés
    plans: dict                 # profil -> clé de formule
    uncertain: list             # profils Max au palier supposé
    unknown: list               # (profil, formule) non pris en charge
    prices: dict
    prices_custom: bool
    prices_stale: bool
    margin: float               # 0,2 pour 20 %
    current: Combo | None = None
    recommended: Combo | None = None
    alternatives: list = field(default_factory=list)
    weekly_target: float = 0.0
    session_target: float = 0.0
    unused_share: float | None = None
    api: costs.Cost | None = None
    api_days: float = 0.0
    reasons: list = field(default_factory=list)

    @property
    def enough_data(self):
        return bool(self.weeks)

    @property
    def api_monthly(self):
        if self.api is None or self.api_days <= 0:
            return None
        return self.api.dollars * DAYS_PER_MONTH / self.api_days

    @property
    def summary(self):
        if self.recommended is None:
            return "Pas encore assez de relevés pour conseiller une formule."
        return f"Conseil : {self.recommended.label} — {money(self.recommended.price)}/mois"


def money(value):
    if abs(value - round(value)) < 0.005:
        return f"{round(value):.0f} $"
    return f"{core.fr(value, 2)} $"


def _num(value):
    return core.fr(value, 1)


def _date(dt):
    local = dt.astimezone() if dt.tzinfo else dt
    return f"{local.day} {core.MONTHS[local.month - 1]}"


def _plural(n, word):
    return f"{n} {word}{'s' if n > 1 else ''}"


def _capacity_text(c):
    session = "sans limite de 5 h" if math.isinf(c.session) else f"{_num(c.session)} sessions Pro sur 5 h"
    return f"{_num(c.weekly)} Pro par semaine, {session}"


def analyze(samples, plans, now, settings, events=(), api=None, api_days=0.0, uncertain=(),
            unknown=()):
    """Conseil (pur). `samples` : {profil: {"session" | "weekly_all": [(ts, %, reset)]}}."""
    cfg = settings["advisor"]
    prices, custom = plan_prices(settings)
    margin = max(0.0, float(cfg.get("margin_pct", 20))) / 100
    weeks_n = max(1, int(cfg.get("weeks", 4)))
    weeks, ignored = week_needs(samples, plans, now, weeks_n, events)
    a = Advice(weeks, ignored, dict(plans), list(uncertain), list(unknown), prices, custom,
               prices_stale(now), margin, api=api, api_days=api_days)
    a.current = combo_of(list(plans.values()), prices) if plans else None
    r = a.reasons
    if not weeks:
        r.append("Pas assez de relevés : il faut au moins 3 jours de collecte par le service "
                 "pour estimer ton besoin.")
    else:
        a.weekly_target = max(w.need for w in weeks) * (1 + margin)
        a.session_target = max(w.session_need for w in weeks) * (1 + margin)
        a.recommended, fits = recommend(a.weekly_target, a.session_target, prices,
                                        cfg.get("max_accounts", 3))
        if a.recommended.accounts > 1:
            single = next((c for c in fits if c.accounts == 1), None)
            if single is not None:
                a.alternatives.append(single)
        _explain(a, now)
    _explain_api_and_prices(a)
    return a


def _explain(a, now):
    r, weeks = a.reasons, a.weeks
    oldest = weeks[-1].start
    r.append(f"Relevés analysés : {_plural(len(weeks), 'semaine')} (du {_date(oldest)} au "
             f"{_date(now)})." + (f" {_plural(a.ignored, 'semaine')} sans assez de relevés "
                                  f"ignorée{'s' if a.ignored > 1 else ''}." if a.ignored else ""))
    needs = [w.weekly for w in weeks]
    top = max(weeks, key=lambda w: w.need)
    r.append(f"Usage par semaine : {_num(sum(needs) / len(needs))} Pro en moyenne, "
             f"{_num(max(needs))} au plus (semaine du {_date(top.start)}) — 1 Pro = la limite "
             f"hebdomadaire d'un compte Pro ; la semaine en cours de chaque compte est projetée "
             f"à son rythme moyen.")
    r.append(f"Fenêtres de 5 h : jusqu'à {_num(max(w.session_peak for w in weeks))} sessions Pro "
             f"consommées en même temps, tous comptes confondus.")
    hits = sum(w.limit_hits for w in weeks)
    blocked = sum(w.blocked for w in weeks)
    if not hits and not blocked:
        r.append("Aucune limite atteinte sur la période.")
    else:
        with_hits = sum(1 for w in weeks if w.limit_hits or w.blocked)
        text = (f"Limite atteinte {hits} fois, {with_hits} semaine{'s' if with_hits > 1 else ''} "
                f"sur {len(weeks)}.")
        if blocked:
            text += (f" Bloqué sans autre compte disponible : {blocked} fois ; ces semaines comptent "
                     f"{CAPPED_BONUS * 100:.0f} % de plus (l'usage mesuré y était bridé).")
        r.append(text)
    cur = a.current
    if cur is not None and cur.weekly > 0:
        shares = [min(1.0, n / cur.weekly) for n in needs]
        a.unused_share = 1 - sum(shares) / len(shares)
        r.append(f"Capacité inutilisée : {a.unused_share * 100:.0f} % en moyenne de ce que tu paies "
                 f"({cur.label}, {_num(cur.weekly)} Pro par semaine) ; la semaine la plus chargée "
                 f"en a utilisé {max(shares) * 100:.0f} %.")
    r.append(f"Avec {a.margin * 100:.0f} % de marge : il te faut {_num(a.weekly_target)} Pro par "
             f"semaine et {_num(a.session_target)} sessions Pro sur 5 h.")
    rec = a.recommended
    enough = rec.weekly >= a.weekly_target and rec.session >= a.session_target
    r.append(f"La moins chère qui couvre ce besoin : {rec.label} — {money(rec.price)}/mois "
             f"({_capacity_text(rec)}).")
    if not enough:
        r.append(f"Même {rec.label} ne couvre pas ce besoin avec la marge : réserve Opus aux tâches "
                 f"qui le demandent.")
    if cur is not None:
        diff = rec.price - cur.price
        if rec.counts == cur.counts:
            r.append("C'est ta formule actuelle : rien à changer.")
        elif diff < 0:
            r.append(f"Tu paies {money(cur.price)}/mois ({cur.label}) : {money(-diff)}/mois d'économie.")
        elif diff > 0:
            r.append(f"Tu paies {money(cur.price)}/mois ({cur.label}) : {money(diff)}/mois de plus, "
                     f"pour ne plus être bloqué.")
        else:
            r.append(f"Même prix que ta formule actuelle ({cur.label}), mieux adaptée à ton usage.")
    for alt in a.alternatives:
        r.append(f"Sans bascule entre comptes : {alt.label} — {money(alt.price)}/mois.")
    for name in a.uncertain:
        r.append(f"« {name} » : Max supposé à 5× (le palier n'est pas indiqué par le compte) — "
                 f"précise-le dans le réglage advisor.profile_plans (« max5 » ou « max20 »).")


def _explain_api_and_prices(a):
    r = a.reasons
    for name, plan in a.unknown:
        r.append(f"« {name} » : formule « {plan} » non prise en charge, compte ignoré.")
    if a.api is not None and a.api.reponses:
        sign = "≥" if a.api.inconnu else "≈"
        monthly = a.api_monthly
        text = (f"Équivalent API : {sign} {costs.format_dollars(a.api.dollars)} sur "
                f"{a.api_days:.0f} jours de journaux Claude Code de ce PC, soit {sign} "
                f"{costs.format_dollars(monthly)}/mois")
        if a.current is not None and a.current.price > 0:
            text += f", contre {money(a.current.price)}/mois payés"
            if monthly and monthly > a.current.price:
                ratio = monthly / a.current.price
                text += f" (×{ratio:.0f})" if ratio >= 10 else f" (×{_num(ratio)})"
        r.append(text + ". claude.ai et les autres appareils n'y figurent pas.")
    names = ", ".join(f"{PLANS[k].label} {money(p)}" for k, p in a.prices.items())
    if a.prices_custom:
        r.append(f"Tarifs personnalisés (réglage advisor.plan_prices) : {names} par mois.")
    else:
        dated = datetime.fromisoformat(PLAN_PRICES_DATE)
        r.append(f"Tarifs du {_date(dated)} {dated.year} ({PLAN_PRICES_SOURCE}), facturation mensuelle, "
                 f"hors taxes : {names}" + (" — à vérifier." if a.prices_stale else "."))


def format_text(advice):
    """Texte de `ccs formule` : conseil puis raisonnement."""
    lines = ["Conseiller de formule", advice.summary, ""]
    lines += [f"• {r}" for r in advice.reasons]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Chargement (store, profils, journaux)
# --------------------------------------------------------------------------

def compute(now=None, settings=None, store=None, profiles=None, projects_dir=None, with_api=True):
    """Conseil à partir des relevés du service, des profils et des journaux locaux."""
    from .settings import load_settings
    from .store import Store
    now = now or datetime.now(timezone.utc)
    settings = settings or load_settings()
    cfg = settings["advisor"]
    own = store is None
    store = store or Store()
    try:
        profiles = core.list_profiles() if profiles is None else profiles
        weeks = max(1, int(cfg.get("weeks", 4)))
        start = now - weeks * WEEK
        # Une journée de plus : point de départ des premières hausses.
        since = (start - timedelta(days=1)).timestamp()
        samples = {p.name: {k: store.samples(p.name, k, since) for k in ("session", "weekly_all")}
                   for p in profiles}
        events = store.events(start.timestamp())
    finally:
        if own:
            store.close()
    plans, uncertain, unknown = detect_plans(profiles, cfg.get("profile_plans") or {})
    api = None
    if with_api:
        projects_dir = projects_dir or core.paths().config_dir / "projects"
        api = costs.period_cost(projects_dir, start.timestamp(), now.timestamp())
    return analyze(samples, plans, now, settings, events, api, weeks * 7.0, uncertain, unknown)
