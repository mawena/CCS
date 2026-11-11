"""Budget par projet : un plafond hebdomadaire en équivalent dollars par dossier de projet.

~/.claude-accounts/budgets.json (600, écriture atomique sous verrou `.budgets.lock`) :
    {"version": 1,
     "budgets": {"/home/u/Work/App": {"weekly": 25.0}},
     "alerted": {"/home/u/Work/App": {"week": "2026-11-09", "pcts": [80]}}}

- Un sous-dossier compte pour le projet le plus proche qui a un budget (`nearest`).
- La semaine est la semaine calendaire de `ccs semaine` (`weekly_report.week_anchor`).
- La dépense est l'équivalent API (`costs`) des réponses de la semaine dont le dossier de
  travail est dans le projet ; les relectures de journaux passent par le cache de `costs`
  (chemin, taille et date de modification).
- Alertes à 80 % et 100 % (`alert_pcts`), une seule fois par seuil, projet et semaine :
  l'état est gardé dans `alerted` (une semaine neuve repart de zéro). Un budget ne bloque
  jamais rien.
- Fichier illisible ou d'un autre format : aucun budget (il est remplacé à l'écriture suivante).

Réglages (`settings["budget"]`) : {"enabled": true, "alert_pcts": [80, 100]}
"""

import fcntl
import logging
import math
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from . import core, costs
from .alerts import Alert
from .project_accounts import normalize, short_path

log = logging.getLogger("ccs.budget")

FILE_VERSION = 1
DEFAULTS = {"enabled": True, "alert_pcts": [80, 100]}
NONE_WORDS = ("aucun", "none")
MAX_BUDGET = 1_000_000.0
USAGE = "usage : ccs budget [<dossier> <montant>|aucun]"


@dataclass(frozen=True)
class Row:
    cwd: str            # dossier du projet
    budget: float       # plafond hebdomadaire (dollars)
    spent: float        # dépensé cette semaine (dollars, équivalent API)
    pct: float          # dépensé / budget, en %
    share: float        # part de la consommation totale de la semaine (0 à 1)


@dataclass(frozen=True)
class Status:
    start: datetime
    end: datetime
    rows: tuple         # Row, triées par pourcentage décroissant
    total: float        # consommation totale de la semaine (tous projets, dollars)


# --------------------------------------------------------------------------
# Réglages et stockage
# --------------------------------------------------------------------------

def config(settings=None):
    raw = settings.get("budget") if isinstance(settings, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    pcts = raw.get("alert_pcts")
    if not (isinstance(pcts, list) and pcts and all(
            isinstance(p, (int, float)) and not isinstance(p, bool) and 0 < p <= 1000 for p in pcts)):
        pcts = DEFAULTS["alert_pcts"]
    return {"enabled": raw.get("enabled") is not False, "alert_pcts": sorted(set(pcts))}


def path():
    return core.paths().store / "budgets.json"


def valid_amount(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 < value <= MAX_BUDGET)


@contextmanager
def _locked():
    lock = core.paths().store / ".budgets.lock"
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read_all():
    """({dossier: budget}, {dossier: {"week", "pcts"}}) du fichier (vides s'il est illisible)."""
    data = core.load_json(path())
    if data.get("version") != FILE_VERSION:
        return {}, {}
    budgets, alerted = {}, {}
    raw = data.get("budgets")
    for cwd, entry in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(cwd, str) and os.path.isabs(cwd) and isinstance(entry, dict) \
                and valid_amount(entry.get("weekly")):
            budgets[normalize(cwd)] = float(entry["weekly"])
    raw = data.get("alerted")
    for cwd, entry in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(cwd, str) and isinstance(entry, dict) and isinstance(entry.get("week"), str) \
                and isinstance(entry.get("pcts"), list):
            alerted[normalize(cwd)] = {"week": entry["week"], "pcts": [
                p for p in entry["pcts"] if isinstance(p, (int, float)) and not isinstance(p, bool)]}
    return budgets, alerted


def _write(budgets, alerted):
    core.atomic_write_json(path(), {
        "version": FILE_VERSION,
        "budgets": {c: {"weekly": budgets[c]} for c in sorted(budgets)},
        "alerted": {c: alerted[c] for c in sorted(alerted) if c in budgets}})


def load():
    """{dossier: budget hebdomadaire en dollars}, trié par dossier."""
    return dict(sorted(_read_all()[0].items()))


def set_budget(cwd, amount):
    """Budget hebdomadaire du dossier (None : le retire). Lève ValueError (montant), OSError.
    Un nouveau montant remet à zéro les alertes déjà envoyées de la semaine."""
    key = normalize(cwd)
    if amount is not None and not valid_amount(amount):
        raise ValueError(f"montant invalide : {amount!r}")
    with _locked():
        budgets, alerted = _read_all()
        if amount is None:
            budgets.pop(key, None)
            alerted.pop(key, None)
        else:
            if budgets.get(key) != float(amount):
                alerted.pop(key, None)
            budgets[key] = float(amount)
        _write(budgets, alerted)
    return None if amount is None else float(amount)


def nearest(cwd, budgets):
    """Dossier de projet (avec budget) le plus proche de `cwd`, ou None."""
    if not cwd:
        return None
    target = normalize(cwd)
    best = None
    for folder in budgets:
        if target == folder or folder == "/" or target.startswith(folder + "/"):
            if best is None or len(folder) > len(best):
                best = folder
    return best


# --------------------------------------------------------------------------
# Semaine et dépense
# --------------------------------------------------------------------------

def week_bounds(now, settings=None, accounts=None):
    """(début, fin) de la semaine en cours, comme `ccs semaine` (début de semaine d'après les
    comptes, sinon le lundi 9:00 ou le jour réglé)."""
    from . import weekly_report
    from .settings import load_settings
    settings = load_settings() if settings is None else settings
    start = weekly_report.week_anchor(accounts or [], now, settings)
    return start, now


def week_key(start):
    return start.astimezone().date().isoformat()


def spend(start, end, budgets, projects_dir=None):
    """({dossier avec budget: dollars}, total de la semaine en dollars), d'après les journaux
    de Claude Code. Une réponse sans dossier de travail ou hors de tout projet à budget ne
    compte que dans le total ; un tarif inconnu compte pour 0."""
    projects_dir = projects_dir or core.paths().config_dir / "projects"
    per = {folder: 0.0 for folder in budgets}
    total = 0.0
    for answers in costs.period_answers(projects_dir, start.timestamp(), end.timestamp()).values():
        for a in answers:
            dollars = a.dollars or 0.0
            total += dollars
            folder = nearest(a.cwd, budgets)
            if folder is not None:
                per[folder] += dollars
    return per, total


def status(now=None, settings=None, accounts=None, projects_dir=None, budgets=None):
    """État des budgets de la semaine en cours : `Status` (lignes triées du plus entamé au moins entamé)."""
    now = now or datetime.now(timezone.utc)
    budgets = load() if budgets is None else budgets
    start, end = week_bounds(now, settings, accounts)
    per, total = spend(start, end, budgets, projects_dir) if budgets else ({}, 0.0)
    rows = [Row(f, b, per[f], per[f] / b * 100.0, per[f] / total if total > 0 else 0.0)
            for f, b in budgets.items()]
    return Status(start, end, tuple(sorted(rows, key=lambda r: (-r.pct, r.cwd))), total)


# --------------------------------------------------------------------------
# Alertes
# --------------------------------------------------------------------------

def _crossed(row, pcts, done):
    """Plus haut seuil franchi et pas encore signalé, ou None (les seuils plus bas sont
    alors considérés comme signalés)."""
    hit = [p for p in pcts if row.pct >= p]
    if not hit or max(hit) in done:
        return None
    return max(hit)


def pending_alerts(now=None, settings=None, accounts=None, projects_dir=None, st=None):
    """Alertes de budget à envoyer maintenant ([Alert]), une par seuil, projet et semaine ;
    elles sont marquées envoyées dans `budgets.json` avant de revenir. Désactivé : liste vide.
    Clé : `budget:<dossier>:<semaine>:<seuil>` (genre « autre » pour `quiet.kind`).
    Calcul lourd possible (journaux de la semaine) : à appeler hors du relevé, dans un fil."""
    cfg = config(settings)
    if not cfg["enabled"]:
        return []
    st = st or status(now, settings, accounts, projects_dir)
    if not st.rows:
        return []
    week = week_key(st.start)
    out = []
    with _locked():
        budgets, alerted = _read_all()
        for row in st.rows:
            if row.cwd not in budgets:
                continue
            entry = alerted.get(row.cwd)
            done = set(entry["pcts"]) if entry and entry["week"] == week else set()
            pct = _crossed(row, cfg["alert_pcts"], done)
            if pct is None:
                continue
            alerted[row.cwd] = {"week": week, "pcts": sorted(done | {p for p in cfg["alert_pcts"] if p <= pct})}
            name = os.path.basename(row.cwd) or row.cwd
            over = pct >= 100
            out.append(Alert(
                f"budget:{row.cwd}:{week}:{pct:g}",
                f"{name} : budget " + ("dépassé" if over else f"à {pct:g} %"),
                f"{costs.format_dollars(row.spent)} dépensés sur {costs.format_dollars(row.budget)} "
                f"cette semaine ({row.pct:.0f} %). Rien n'est bloqué.", 1 if over else 0))
        if out:
            _write(budgets, alerted)
    return out


# --------------------------------------------------------------------------
# Texte et commande « ccs budget »
# --------------------------------------------------------------------------

def parse_amount(text):
    """Montant en dollars d'un texte (« 25 », « 12,5 », « 25$ »), ou None s'il est invalide."""
    try:
        value = float(str(text).strip().rstrip("$").strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
    return value if valid_amount(value) else None


def format_amount(value):
    return costs.format_dollars(value)


def format_text(st, home=None):
    """Texte de « ccs budget » : une ligne par projet avec budget, puis la consommation totale."""
    if not st.rows:
        return ("Aucun budget défini. Exemple : ccs budget ~/Work/App 25 "
                "(25 $ d'équivalent API par semaine).")
    paths = [short_path(r.cwd, home) for r in st.rows]
    width = max(len(p) for p in paths)
    lines = [f"Budgets de la semaine du {st.start.astimezone():%d/%m} (équivalent API) :"]
    for p, r in zip(paths, st.rows):
        mark = "  ⚠ dépassé" if r.pct >= 100 else ""
        lines.append(f"  {p:<{width}}  {format_amount(r.spent)} / {format_amount(r.budget)}"
                     f"  ({r.pct:.0f} %, {r.share * 100:.0f} % de la semaine){mark}")
    lines.append(f"Consommation totale : {format_amount(st.total)}")
    return "\n".join(lines)


def _accounts_from_state():
    """Comptes du dernier état du service (pour le début de semaine) ; [] si illisible."""
    try:
        from . import daemon
        return daemon.states_from_state(core.load_json(daemon.state_path()))
    except Exception:  # noqa: BLE001 — état absent ou illisible : semaine du lundi 9:00
        return []


def command(args, settings=None, accounts=None, projects_dir=None, now=None, home=None, cwd=None,
            out=None):
    """« ccs budget [<dossier> <montant>|aucun] » : renvoie le code de sortie (0, 1 erreur,
    2 usage). `out(texte)` reçoit les messages (défaut : print ; les erreurs vont aussi
    sur la sortie standard, le code de sortie les distingue)."""
    out = out or print
    args = list(args or [])
    if len(args) not in (0, 2):
        out(USAGE)
        return 2
    try:
        if not args:
            if accounts is None:
                accounts = _accounts_from_state()
            out(format_text(status(now, settings, accounts, projects_dir), home))
            return 0
        folder = normalize(os.path.join(cwd or os.getcwd(), os.path.expanduser(args[0])))
        where = short_path(folder, home)
        if args[1].lower() in NONE_WORDS:
            had = folder in load()
            set_budget(folder, None)
            out(f"Budget de {where} supprimé." if had else f"{where} n'avait pas de budget.")
            return 0
        amount = parse_amount(args[1])
        if amount is None:
            out(f"montant invalide : {args[1]} (un nombre de dollars supérieur à 0)\n{USAGE}")
            return 2
        if not os.path.isdir(folder):
            out(f"dossier introuvable : {where}")
            return 1
        set_budget(folder, amount)
        out(f"{where} : budget de {format_amount(amount)} par semaine (équivalent API). "
            "Alertes à 80 % et 100 %, rien n'est bloqué.")
        return 0
    except (OSError, ValueError) as e:
        out(f"enregistrement impossible : {e}")
        return 1
    except Exception as e:  # noqa: BLE001 — journaux illisibles : message, pas de trace
        log.exception("budget impossible")
        out(f"Calcul du budget impossible : {e}")
        return 1
