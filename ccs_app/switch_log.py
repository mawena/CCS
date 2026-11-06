"""Journal lisible des bascules : quand, de quel compte vers quel compte, et pourquoi.

Tout est lu dans l'historique (`history.db`, événements du service et du hook) :
- `switch` : `detail.mode` « auto » (seuil avant la coupure : `percent`, `threshold`,
  `projected`), « anticipee » (orchestrateur : `lost`, `minutes`), « blocage » (hook
  StopFailure), « manual » (`via`, `project`), « initial » (premier relevé du service) ;
  `from` (compte quitté), `reason` (texte de la décision). Les anciens événements, sans
  ces champs, restent lisibles : pourcentages relus dans `reason`, compte quitté déduit
  de la bascule précédente.
- `error` des bascules (`op` « auto_switch », « notification », « manual ») : échec et
  son message ; les erreurs de relevé (`op` « fetch ») ne sont pas des bascules.
- `alert` du hook (profil « blocage ») : limite atteinte sans bascule (pause, aucun
  autre compte disponible).
- `warmup` : démarrages de fenêtre (orchestrateur, créneaux de warm-up).
Les marqueurs `limits/<session_id>.json` (`limit_events`, lus sans les modifier)
donnent, tant qu'ils existent (24 h au plus, consommés par le terminal intégré), le
projet de la conversation bloquée.

Note d'origine : ~/.claude-accounts/switch-origin.json (600)
    {"profile": "pro", "via": "projet", "ts": 1793000000.0, "project": "/home/u/Work/App"}
écrite juste avant un « ccs use » lancé depuis l'application, l'icône… (`note_origin`), ou
par `ccs` lui-même pour une bascule lancée à la main (« ccs ») ou par un raccourci clavier
(« raccourci », option --notifier) ;
le service la lit et la retire quand il constate la bascule (`take_origin`, dans
`Daemon.detect_manual_switch`) pour enregistrer `via` dans l'événement.
"""

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import core

ORIGIN_MAX_AGE_S = 600
VIA = ("application", "icone", "notification", "ccs", "nouvelle-session", "projet", "raccourci")
SWITCH_ERROR_OPS = ("auto_switch", "notification", "manual")
PERIODS = (("7 jours", 7), ("30 jours", 30), ("Tout", None))
KINDS = ("auto", "anticipee", "blocage", "manuelle", "initial", "echec", "limite", "fenetre")
EVENT_TYPES = ("switch", "error", "alert", "warmup")

# Rapprochements (secondes) : marqueurs écrits par le hook après sa bascule ; détection
# d'une bascule par le service juste avant que le hook l'ait enregistrée.
MARKER_BEFORE_S = 5
MARKER_AFTER_S = 180
RACE_S = 15
WARMUP_STALE_S = 15 * 60

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre")

MANUAL_REASONS = {
    "notification": "Bascule manuelle depuis une notification",
    "application": "Bascule manuelle depuis l'application",
    "icone": "Bascule manuelle depuis l'icône",
    "ccs": "Bascule manuelle par la commande ccs",
    "raccourci": "Bascule manuelle par un raccourci clavier",
    "nouvelle-session": "Bascule pour une nouvelle session (compte choisi)",
}
MANUAL_UNKNOWN = "Bascule manuelle (application, icône ou « ccs use »)"
FAILURE_LABELS = {
    "auto": "Échec de la bascule automatique",
    "anticipee": "Échec de la bascule anticipée",
    "blocage": "Échec de la bascule après un blocage",
    "notification": "Échec de la bascule depuis une notification",
    "manual": "Échec de la bascule manuelle",
}
AUTO_RE = re.compile(r"à (\d+(?:[.,]\d+)?) %")
EARLY_RE = re.compile(r"va perdre (\d+) % de quota dans (\d+) min")


@dataclass(frozen=True)
class Entry:
    ts: float
    kind: str               # voir KINDS
    source: str | None      # compte quitté
    target: str | None      # compte choisi (ou concerné)
    title: str              # « perso → pro », « pro »
    reason: str             # raison en clair
    ok: bool = True         # False : échec, ou limite atteinte sans bascule
    detail: str = ""        # complément (texte de la décision, message brut)
    projects: tuple = ()    # projets des conversations bloquées (marqueurs)


# --------------------------------------------------------------------------
# Note d'origine d'une bascule manuelle
# --------------------------------------------------------------------------

def origin_path():
    return core.paths().store / "switch-origin.json"


def note_origin(profile, via, project=None, now=None):
    """Retient d'où vient la bascule vers `profile` qui va être lancée. Ne lève jamais ;
    renvoie True si la note est écrite."""
    if via not in VIA or not profile:
        return False
    data = {"profile": profile, "via": via, "ts": time.time() if now is None else float(now)}
    if project:
        data["project"] = str(project)
    try:
        core.atomic_write_json(origin_path(), data)
        return True
    except (OSError, TypeError, ValueError):
        return False


def clear_origin():
    try:
        os.unlink(origin_path())
    except OSError:
        pass


def take_origin(profile, now=None):
    """Origine notée pour une bascule vers `profile` ({"via", "project"?}), retirée une
    fois lue ; None si absente, illisible, trop ancienne (retirée) ou d'un autre compte
    (gardée : sa bascule n'a peut-être pas encore eu lieu)."""
    data = core.load_json(origin_path())
    if not data:
        return None
    now = time.time() if now is None else now
    ts = data.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not 0 <= now - ts <= ORIGIN_MAX_AGE_S \
            or data.get("via") not in VIA:
        clear_origin()
        return None
    if data.get("profile") != profile:
        return None
    clear_origin()
    out = {"via": data["via"]}
    if isinstance(data.get("project"), str) and data["project"]:
        out["project"] = data["project"]
    return out


def record_failure(store, profile, via, message, source=None, project=None, now=None):
    """Bascule manuelle en échec (« ccs use » lancé par l'application) : pour le journal."""
    detail = {"op": "manual", "message": message or ""}
    if via:
        detail["via"] = via
    if source:
        detail["from"] = source
    if project:
        detail["project"] = str(project)
    store.add_event(time.time() if now is None else now, "error", profile, detail)


# --------------------------------------------------------------------------
# Construction du journal (pure)
# --------------------------------------------------------------------------

def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _pct(value):
    return f"{value:.0f} %"


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " et " + names[-1]


def _title(source, target):
    if source and target and source != target:
        return f"{source} → {target}"
    return target or source or "?"


def _project_label(path):
    from . import sessions
    return sessions.project_name(path)


def _auto_reason(d, source):
    percent = _num(d.get("percent"))
    if percent is None:
        m = AUTO_RE.search(str(d.get("reason") or ""))
        percent = float(m.group(1).replace(",", ".")) if m else None
    if percent is None:
        return "Bascule automatique avant la coupure"
    who = f"{source} à {_pct(percent)}" if source else f"compte à {_pct(percent)}"
    projected, threshold = _num(d.get("projected")), _num(d.get("threshold"))
    if projected is not None and projected >= 100 and (threshold is None or percent < threshold):
        who += ", 100 % prévu avant le prochain relevé"
    return f"Bascule automatique avant la coupure ({who})"


def _early_reason(d, target):
    lost, minutes = _num(d.get("lost")), _num(d.get("minutes"))
    if lost is None or minutes is None:
        m = EARLY_RE.search(str(d.get("reason") or ""))
        if m:
            lost, minutes = float(m.group(1)), float(m.group(2))
    if lost is None or minutes is None:
        return "Bascule anticipée de l'orchestrateur (quota sur le point d'expirer)"
    return (f"Bascule anticipée de l'orchestrateur : {target} allait perdre {_pct(lost)} "
            f"de quota dans {minutes:.0f} min")


def _manual_reason(d):
    via = d.get("via")
    if via == "projet":
        project = d.get("project")
        return f"Bascule vers le compte du projet {_project_label(project)}" if project \
            else "Bascule vers le compte du projet"
    return MANUAL_REASONS.get(via, MANUAL_UNKNOWN)


def _failure_reason(d, target):
    op = d.get("op")
    key = (d.get("mode") or "auto") if op == "auto_switch" else op
    label = FAILURE_LABELS.get(key, FAILURE_LABELS["auto"])
    message = str(d.get("message") or "").strip()
    text = f"{label} vers {target}"
    return f"{text} : {message}" if message else text


def _warmup_entry(e, now):
    d = e.detail
    orchestrator = d.get("mode") == "orchestrateur"
    ok = d.get("ok")
    message = str(d.get("message") or "").strip()
    slot = d.get("time") or core.fmt_time(e.ts)
    if orchestrator:
        head = "Démarrage de la fenêtre par l'orchestrateur"
        if ok is True:
            reason = "Fenêtre de 5 h démarrée par l'orchestrateur"
        elif ok is False:
            reason = f"{head} impossible" + (f" : {message}" if message else "")
        else:
            reason = f"{head} " + ("en cours" if now - e.ts < WARMUP_STALE_S else "sans réponse")
    else:
        if ok is True:
            reason = f"Warm-up de {slot} : fenêtre de 5 h démarrée"
        elif ok is False:
            reason = f"Warm-up de {slot} impossible" + (f" : {message}" if message else "")
        else:
            reason = f"Warm-up de {slot} " + ("en cours" if now - e.ts < WARMUP_STALE_S else "sans réponse")
    failed = ok is False or (ok is None and now - e.ts >= WARMUP_STALE_S)
    return Entry(e.ts, "fenetre", None, e.profile, e.profile or "?", reason, not failed,
                 message if failed else "")


def _warmups(events):
    """Un démarrage par (compte, date, créneau) : le résultat remplace « en cours »
    (événements dans l'ordre chronologique)."""
    chosen = {}
    for e in events:
        d = e.detail
        key = (e.profile, d.get("date"), d.get("time")) if d.get("date") else (e.profile, e.ts, None)
        cur = chosen.get(key)
        if cur is None or d.get("ok") is not None or cur.detail.get("ok") is None:
            chosen[key] = e
    return list(chosen.values())


class _Markers:
    """Marqueurs de limite pas encore attribués à une entrée du journal."""

    def __init__(self, markers, project_of):
        self.left = sorted((markers or {}).values(), key=lambda m: m.ts)
        self.project_of = project_of
        self.names = {}

    def take(self, ts, outcomes, target=None, after=MARKER_AFTER_S):
        found = [m for m in self.left if m.outcome in outcomes and ts - MARKER_BEFORE_S <= m.ts <= ts + after
                 and (target is None or m.target == target)]
        for m in found:
            self.left.remove(m)
        return found

    def projects(self, found):
        out = []
        for m in found:
            if m.session_id not in self.names:
                try:
                    self.names[m.session_id] = self.project_of(m.session_id) if self.project_of else None
                except OSError:
                    self.names[m.session_id] = None
            name = self.names[m.session_id]
            if name and name not in out:
                out.append(name)
        return tuple(out)


def build(events, markers=None, previous=None, now=None, project_of=None):
    """Entrées du journal, de la plus récente à la plus ancienne.

    `events` : événements de `Store.events` (tous types, ordre chronologique) ;
    `markers` : {session_id: LimitEvent} ; `previous` : compte actif avant le premier
    événement ; `project_of(session_id)` : nom du projet d'une conversation."""
    now = time.time() if now is None else now
    if project_of is None:
        project_of = session_project
    marks = _Markers(markers, project_of)
    events = sorted(events, key=lambda e: e.ts)
    switches = [e for e in events if e.type == "switch"]
    errors = [e for e in events if e.type == "error" and isinstance(e.detail, dict)
              and e.detail.get("op") in SWITCH_ERROR_OPS]
    entries = []
    current = previous

    def near(items, ts, window=MARKER_BEFORE_S):
        return any(abs(x.ts - ts) <= window for x in items)

    for e in events:
        d = e.detail if isinstance(e.detail, dict) else {}
        if e.type == "switch":
            mode = d.get("mode")
            source = d.get("from") or (current if current != e.profile else None)
            if mode == "initial":
                source = None
            current = e.profile
            if mode == "manual" and not d.get("via"):
                # Le service a vu la bascule avant que son auteur (hook, service) l'enregistre.
                if any(s.profile == e.profile and 0 < s.ts - e.ts <= RACE_S
                       and s.detail.get("mode") in ("auto", "anticipee", "blocage") for s in switches):
                    continue
            raw = str(d.get("reason") or "")
            if mode == "auto":
                entries.append(Entry(e.ts, "auto", source, e.profile, _title(source, e.profile),
                                     _auto_reason(d, source), detail=raw))
            elif mode == "anticipee":
                entries.append(Entry(e.ts, "anticipee", source, e.profile, _title(source, e.profile),
                                     _early_reason(d, e.profile), detail=raw))
            elif mode == "blocage":
                found = marks.take(e.ts, ("switched", "already"), e.profile)
                projects = marks.projects(found)
                where = f"dans {_join(projects)}" if projects else f"sur {source}" if source else ""
                reason = f"Bascule après un blocage (limite atteinte {where})" if where \
                    else "Bascule après un blocage (limite atteinte)"
                entries.append(Entry(e.ts, "blocage", source, e.profile, _title(source, e.profile),
                                     reason, detail=raw, projects=projects))
            elif mode == "initial":
                entries.append(Entry(e.ts, "initial", None, e.profile, e.profile or "?",
                                     f"Début du suivi : {e.profile} était le compte actif"))
            else:
                entries.append(Entry(e.ts, "manuelle", source, e.profile, _title(source, e.profile),
                                     _manual_reason(d), detail=raw))
        elif e.type == "error" and d.get("op") in SWITCH_ERROR_OPS:
            source = d.get("from") or (current if current != e.profile else None)
            found = marks.take(e.ts, ("failed",), e.profile) if d.get("mode") == "blocage" else []
            entries.append(Entry(e.ts, "echec", source, e.profile, _title(source, e.profile),
                                 _failure_reason(d, e.profile), False, str(d.get("message") or ""),
                                 marks.projects(found)))
        elif e.type == "alert" and e.profile == "blocage":
            key = str(d.get("key") or "")
            if key == "pause":
                found = marks.take(e.ts, ("paused",))
                tail = " pendant une pause : pas de bascule"
            elif key.startswith("blocage:"):
                if near(switches, e.ts) or near(errors, e.ts):
                    continue  # bascule (ou échec) du même blocage : une seule entrée
                found = marks.take(e.ts, ("exhausted",), after=60)
                tail = " : aucun autre compte disponible"
            else:
                continue  # « deja » : la bascule qui vient d'avoir lieu porte cette limite
            projects = marks.projects(found)
            who = current or next((m.source for m in found if m.source), None)
            where = f" dans {_join(projects)}" if projects else ""
            entries.append(Entry(e.ts, "limite", who, None, who or "?",
                                 f"Limite atteinte{where}{tail}", False, projects=projects))
    for e in _warmups([e for e in events if e.type == "warmup"]):
        entries.append(_warmup_entry(e, now))
    entries.sort(key=lambda x: x.ts, reverse=True)
    return entries


# --------------------------------------------------------------------------
# Lecture, regroupement, texte
# --------------------------------------------------------------------------

def session_project(session_id):
    """Nom du projet d'une conversation, d'après le dossier noté dans son journal (None si
    le journal est introuvable)."""
    from . import sessions
    root = sessions.projects_dir()
    if not session_id or not root.is_dir():
        return None
    for path in root.glob(f"*/{session_id}.jsonl"):
        cwd = sessions._cwd_of(path)
        if cwd:
            return sessions.project_name(cwd)
    return None


def load(store, days=7, now=None, markers=None, project_of=None):
    """Journal des `days` derniers jours (None : tout l'historique gardé). Les marqueurs
    de limite sont lus sur le disque si `markers` n'est pas fourni."""
    now = time.time() if now is None else now
    since = 0.0 if days is None else now - days * 86400
    if markers is None:
        from . import limit_events
        markers = limit_events.load_all()
    events = store.events(since, types=EVENT_TYPES)
    before = store.last_event("switch", before=since) if since > 0 else None
    return build(events, markers, before.profile if before else None, now, project_of)


def day_label(ts, now=None):
    """« Aujourd'hui », « Hier », « Lundi 2 novembre » (année ajoutée si ce n'est pas celle-ci)."""
    today = datetime.fromtimestamp(time.time() if now is None else now).date()
    day = datetime.fromtimestamp(ts).date()
    if day == today:
        return "Aujourd'hui"
    if day == today - timedelta(days=1):
        return "Hier"
    text = f"{JOURS[day.weekday()]} {day.day} {MOIS[day.month - 1]}"
    if day.year != today.year:
        text += f" {day.year}"
    return text[:1].upper() + text[1:]


def group_by_day(entries, now=None):
    """[(libellé du jour, [entrées])], dans l'ordre des entrées (plus récentes d'abord)."""
    groups = []
    for e in entries:
        label = day_label(e.ts, now)
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(e)
    return groups


def format_text(entries, now=None):
    """Texte de « ccs journal » : un bloc par jour, une ligne par entrée (✗ : échec)."""
    if not entries:
        return "Aucune bascule sur cette période."
    width = max(len(e.title) for e in entries)
    lines = []
    for label, group in group_by_day(entries, now):
        if lines:
            lines.append("")
        lines.append(label)
        for e in group:
            mark = "✗" if not e.ok else " "
            lines.append(f"  {datetime.fromtimestamp(e.ts):%H:%M}  {mark} {e.title:<{width}}  {e.reason}")
    return "\n".join(lines)


USAGE = "usage : ccs journal [--jours N | --tout]"


def command(days=7, now=None, store=None):
    """(code de sortie, texte) de « ccs journal [--jours N | --tout] » (None : tout l'historique)."""
    if days is not None and (isinstance(days, bool) or not isinstance(days, int) or days <= 0):
        return 2, USAGE
    if store is None:
        from .store import Store
        store = Store()
    return 0, format_text(load(store, days, now), now)
