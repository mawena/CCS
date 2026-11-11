"""File de tâches Claude : des messages que le service fait exécuter sans fenêtre.

~/.claude-accounts/tasks.json (600, écriture atomique sous verrou `.tasks.lock`) :
    {"version": 1, "next": 3, "tasks": [{"id": "2", "message": "…", "cwd": "/home/u/App", …}]}
Journaux : ~/.claude-accounts/tasks/<id>.jsonl (sortie `stream-json` de `claude -p`).

Moments (`when`) :
- `quota` : dès qu'un compte a du quota ;
- `HH:MM` : à partir de cette heure (aujourd'hui, sinon demain), `not_before` est fixé à l'ajout ;
- `nuit` : au meilleur créneau (`best_time`) de la plage de nuit des réglages.

Une seule tâche à la fois, jamais pendant une pause de CCS. La décision (`decide`) est pure ;
`tick` l'applique en s'appuyant sur `task_runner` (processus, journal, relance après limite).
Les alertes de fin et d'échec sont des `alerts.Alert`, envoyées par l'appelant.
"""

import builtins
import fcntl
import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone

from . import core
from .forecast import TRANSIENT_ERRORS

FILE_VERSION = 1
DEFAULTS = {"enabled": True, "night": {"start": "23:00", "end": "07:00"}, "max_attempts": 3}

# droits -> valeur de --permission-mode (None : pas d'option ; en `-p`, ce qui demande une
# permission est refusé)
RIGHTS = {"lecture": None, "modifications": "acceptEdits", "tout": "bypassPermissions"}
DEFAULT_RIGHTS = "modifications"
RIGHTS_LABELS = {"lecture": "Lecture seule", "modifications": "Modifications des fichiers",
                 "tout": "Tout (aucune vérification)"}

QUEUED, RUNNING, WAITING, DONE, FAILED, CANCELLED = "queued", "running", "waiting", "done", "failed", "cancelled"
STATES = (QUEUED, RUNNING, WAITING, DONE, FAILED, CANCELLED)
STATE_LABELS = {QUEUED: "En attente", RUNNING: "En cours", WAITING: "À reprendre (limite atteinte)",
                DONE: "Finie", FAILED: "Échouée", CANCELLED: "Annulée"}
ACTIVE = (QUEUED, RUNNING, WAITING)
FINISHED = (DONE, FAILED, CANCELLED)

SESSION_MAX = 95        # un compte au-delà de ce pourcentage (session ou semaine) n'a plus de quota
RETRY_S = 300           # attente avant de réessayer quand aucun compte n'est disponible
NIGHT_DURATION_H = 3.0  # durée supposée d'une tâche de nuit pour choisir le créneau
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
ID_RE = re.compile(r"^[0-9]{1,9}$")
USAGE = ('usage : ccs tache [ajouter "<message>" [-C dossier] [--modele m] '
         '[--droits lecture|modifications|tout] [--quand quota|nuit|HH:MM]]\n'
         '       ccs tache [voir <id>] [annuler <id>] [supprimer <id>]')


@dataclass
class Task:
    id: str
    message: str
    cwd: str
    model: str | None = None
    rights: str = DEFAULT_RIGHTS
    when: str = "quota"
    not_before: float | None = None      # HH:MM : instant (timestamp) avant lequel on n'attend pas
    state: str = QUEUED
    created: float = 0.0
    started: float | None = None
    finished: float | None = None
    session_id: str | None = None
    account: str | None = None           # compte actif au dernier lancement
    attempts: int = 0                    # relances après une limite atteinte
    retry_at: float | None = None
    pid: int | None = None
    duration: float | None = None        # secondes, tous lancements compris
    cost: float | None = None            # équivalent API en dollars
    error: str | None = None
    note: str = ""                       # dernier motif d'attente ou d'échec, lisible
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        """Tâche lue du fichier, ou None si le contenu est inattendu."""
        if not isinstance(data, dict):
            return None
        tid, message, cwd = data.get("id"), data.get("message"), data.get("cwd")
        if not isinstance(tid, str) or not ID_RE.match(tid) or not isinstance(message, str) \
                or not message.strip() or not isinstance(cwd, str) or not os.path.isabs(cwd):
            return None
        kw = {}
        for f in fields(cls):
            if f.name in data and f.name not in ("id", "message", "cwd"):
                kw[f.name] = data[f.name]
        t = cls(tid, message, cwd, **{k: v for k, v in kw.items() if k in _TYPES and _ok(v, _TYPES[k])})
        if t.state not in STATES:
            t.state = QUEUED
        if t.rights not in RIGHTS:
            t.rights = DEFAULT_RIGHTS
        if t.when != "quota" and t.when != "nuit" and not TIME_RE.match(str(t.when)):
            t.when = "quota"
        return t


_TYPES = {"model": (str, type(None)), "rights": (str,), "when": (str,), "not_before": (int, float, type(None)),
          "state": (str,), "created": (int, float), "started": (int, float, type(None)),
          "finished": (int, float, type(None)), "session_id": (str, type(None)),
          "account": (str, type(None)), "attempts": (int,), "retry_at": (int, float, type(None)),
          "pid": (int, type(None)), "duration": (int, float, type(None)),
          "cost": (int, float, type(None)), "error": (str, type(None)), "note": (str,), "extra": (dict,)}


def _ok(value, types):
    return isinstance(value, types) and not (isinstance(value, bool) and bool not in types)


# --------------------------------------------------------------------------
# Réglages
# --------------------------------------------------------------------------

def config(settings=None):
    """Section `tasks` des réglages, complétée par les valeurs par défaut (repli si invalide)."""
    raw = (settings or {}).get("tasks")
    raw = raw if isinstance(raw, dict) else {}
    night = raw.get("night") if isinstance(raw.get("night"), dict) else {}
    out = {"enabled": raw["enabled"] if isinstance(raw.get("enabled"), bool) else DEFAULTS["enabled"],
           "night": {k: night[k] if isinstance(night.get(k), str) and TIME_RE.match(night[k])
                     else DEFAULTS["night"][k] for k in ("start", "end")},
           "max_attempts": DEFAULTS["max_attempts"]}
    n = raw.get("max_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 10:
        out["max_attempts"] = n
    return out


# --------------------------------------------------------------------------
# Stockage
# --------------------------------------------------------------------------

def path():
    return core.paths().store / "tasks.json"


def journal_dir():
    return core.paths().store / "tasks"


def journal_path(task_id):
    return journal_dir() / f"{task_id}.jsonl"


@contextmanager
def _locked():
    lock = core.paths().store / ".tasks.lock"
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read():
    """([Task], prochain numéro) du fichier (vide s'il est absent, illisible ou d'un autre format)."""
    data = core.load_json(path())
    if data.get("version") != FILE_VERSION or not isinstance(data.get("tasks"), list):
        return [], 1
    tasks = [t for t in (Task.from_dict(d) for d in data["tasks"]) if t is not None]
    nxt = data.get("next")
    floor = max((int(t.id) for t in tasks), default=0) + 1
    return tasks, max(floor, nxt if isinstance(nxt, int) and not isinstance(nxt, bool) else 1)


def _write(tasks, nxt):
    core.atomic_write_json(path(), {"version": FILE_VERSION, "next": nxt,
                                    "tasks": [t.to_dict() for t in tasks]})


def all():  # noqa: A001 — nom de l'API demandée (ccs tache)
    """Tâches enregistrées, dans l'ordre d'ajout."""
    return _read()[0]


def get(task_id):
    task_id = str(task_id)
    return next((t for t in _read()[0] if t.id == task_id), None)


def normalize_when(text):
    """`quota`, `nuit` ou `HH:MM` (zéro initial ajouté) ; ValueError sinon."""
    w = str(text or "quota").strip().lower()
    if w in ("quota", "nuit"):
        return w
    m = TIME_RE.match(w)
    if not m:
        raise ValueError(f"moment inconnu : {text!r} (quota, nuit ou HH:MM)")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def next_occurrence(hhmm, now, tz=None):
    """Prochain instant (UTC) où il est HH:MM à l'heure locale, `now` compris."""
    tz = tz or _local_tz()
    h, m = (int(x) for x in hhmm.split(":"))
    local = now.astimezone(tz)
    at = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if at < local:
        at = datetime.combine(local.date() + timedelta(days=1), at.timetz().replace(tzinfo=None), tzinfo=tz)
    return at.astimezone(timezone.utc)


def _local_tz():
    from .orchestrator import local_tz
    return local_tz()


def add(message, cwd=None, model=None, rights=DEFAULT_RIGHTS, when="quota", now=None, tz=None):
    """Ajoute une tâche en attente et la renvoie. Lève ValueError (message vide, droits ou
    moment inconnus, dossier inexistant, modèle invalide), OSError."""
    from . import launch_options
    message = (message or "").strip()
    if not message:
        raise ValueError("le message de la tâche est vide")
    if rights not in RIGHTS:
        raise ValueError(f"droits inconnus : {rights!r} (lecture, modifications, tout)")
    when = normalize_when(when)
    folder = os.path.normpath(os.path.abspath(os.path.expanduser(cwd or os.getcwd())))
    if not os.path.isdir(folder):
        raise ValueError(f"dossier introuvable : {folder}")
    launch_options.claude_args(model=model)          # valide le modèle
    model = launch_options._model(model)
    now = now or datetime.now(timezone.utc)
    not_before = next_occurrence(when, now, tz).timestamp() if TIME_RE.match(when) else None
    with _locked():
        tasks, nxt = _read()
        task = Task(str(nxt), message, folder, model, rights, when, not_before, QUEUED, now.timestamp())
        tasks.append(task)
        _write(tasks, nxt + 1)
    return task


def update(task_id, **changes):
    """Modifie des champs d'une tâche (sous verrou) ; renvoie la tâche, ou None si elle n'existe plus."""
    task_id = str(task_id)
    with _locked():
        tasks, nxt = _read()
        task = next((t for t in tasks if t.id == task_id), None)
        if task is None:
            return None
        for k, v in changes.items():
            if not hasattr(task, k):
                raise AttributeError(k)
            setattr(task, k, v)
        _write(tasks, nxt)
        return task


def cancel(task_id, now=None):
    """Annule une tâche en attente, à reprendre ou en cours (le processus est arrêté par `tick`
    ou ici, via `task_runner.stop`). Renvoie la tâche ; None si inconnue ; ValueError si finie."""
    task = get(task_id)
    if task is None:
        return None
    if task.state in FINISHED:
        raise ValueError(f"la tâche {task.id} est déjà {STATE_LABELS[task.state].lower()}")
    if task.state == RUNNING:
        from . import task_runner
        task_runner.stop(task)
    now = now or datetime.now(timezone.utc)
    return update(task.id, state=CANCELLED, finished=now.timestamp(), pid=None, note="annulée")


def remove(task_id):
    """Supprime une tâche finie, échouée ou annulée (et son journal). Renvoie la tâche ;
    None si inconnue ; ValueError si elle est encore active (l'annuler d'abord)."""
    task_id = str(task_id)
    with _locked():
        tasks, nxt = _read()
        task = next((t for t in tasks if t.id == task_id), None)
        if task is None:
            return None
        if task.state in ACTIVE:
            raise ValueError(f"la tâche {task.id} est encore active : l'annuler d'abord")
        _write([t for t in tasks if t.id != task_id], nxt)
    try:
        journal_path(task.id).unlink()
    except OSError:
        pass
    return task


# --------------------------------------------------------------------------
# Décision (pure)
# --------------------------------------------------------------------------

def has_quota(state, now):
    """Vrai si un compte du relevé `state` (state.json) est utilisable et sous `SESSION_MAX` %
    en session comme en semaine (réinitialisation passée comptée à 0)."""
    for a in (state or {}).get("accounts") or []:
        err = a.get("error")
        if err and not str(err).startswith(TRANSIENT_ERRORS):
            continue
        limits = a.get("limits") or []
        if not limits:
            continue
        if builtins.all(_pct(lim, now) < SESSION_MAX for lim in limits):
            return True
    return False


def _pct(lim, now):
    reset = core.parse_dt(lim.get("resets_at"))
    if reset is not None and reset <= now:
        return 0.0
    try:
        return float(lim.get("percent") or 0)
    except (TypeError, ValueError):
        return 0.0


def night_window(now, start, end, tz=None):
    """(début, fin) UTC de la plage de nuit en cours à `now`, sinon de la prochaine."""
    tz = tz or _local_tz()
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    local = now.astimezone(tz)
    upcoming = None
    for off in (-1, 0, 1):
        day = local.date() + timedelta(days=off)
        s = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
        span_days = 0 if (eh, em) > (sh, sm) else 1
        eday = day + timedelta(days=span_days)
        e = datetime(eday.year, eday.month, eday.day, eh, em, tzinfo=tz)
        if (sh, sm) == (eh, em):
            e = s + timedelta(hours=24)
        s, e = s.astimezone(timezone.utc), e.astimezone(timezone.utc)
        if s <= now < e:
            return s, e
        if s > now and upcoming is None:
            upcoming = (s, e)
    return upcoming


def night_due(now, settings, state, tz=None):
    """(prêt, explication) pour une tâche `nuit` : dans la plage de nuit et au meilleur
    créneau de `best_time` calculé jusqu'à la fin de la plage."""
    from . import best_time
    night = config(settings)["night"]
    win = night_window(now, night["start"], night["end"], tz)
    if win is None or not win[0] <= now < win[1]:
        return False, f"attend la nuit ({night['start']}–{night['end']})"
    span = min(max((win[1] - now).total_seconds() / 3600, best_time.SPAN_RANGE[0]), best_time.SPAN_RANGE[1])
    res = best_time.compute(state or {}, NIGHT_DURATION_H, span, now)
    if res.best is None:
        return False, "aucun créneau avec du quota cette nuit"
    if res.best.start <= now:
        return True, ""
    return False, f"attend le meilleur créneau ({res.best.start.astimezone(tz or _local_tz()):%H:%M})"


def due(task, now, settings=None, state=None, paused=False, tz=None):
    """(prête, explication) : la tâche peut-elle démarrer maintenant ? (`explication` dit
    pourquoi elle attend)."""
    if task.state not in (QUEUED, WAITING):
        return False, ""
    if paused:
        return False, "CCS est en pause"
    if task.state == WAITING and task.retry_at and now.timestamp() < task.retry_at:
        return False, "nouvel essai bientôt"
    if task.state == QUEUED and task.not_before and now.timestamp() < task.not_before:
        return False, f"attend {task.when}"
    if not has_quota(state, now):
        return False, "aucun compte n'a de quota"
    if task.state == QUEUED and task.when == "nuit":
        return night_due(now, settings, state, tz)
    return True, ""


def decide(tasks, now, settings=None, state=None, paused=False, tz=None):
    """Tâche à lancer maintenant, ou None : jamais deux à la fois ni pendant une pause ;
    les tâches à reprendre (limite atteinte) passent avant les autres, puis l'ordre d'ajout."""
    if not config(settings)["enabled"] or paused or any(t.state == RUNNING for t in tasks):
        return None
    for group in (WAITING, QUEUED):
        for t in tasks:
            if t.state == group and due(t, now, settings, state, paused, tz)[0]:
                return t
    return None


# --------------------------------------------------------------------------
# Alertes
# --------------------------------------------------------------------------

def _duration_text(seconds):
    s = int(seconds or 0)
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min {sec:02d} s" if m else f"{sec} s"


def _short(text, n=60):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def summary(task):
    """Une ligne : durée et coût équivalent d'une tâche terminée."""
    from . import costs
    parts = []
    if task.duration is not None:
        parts.append(_duration_text(task.duration))
    if task.cost:
        parts.append(f"≈ {costs.format_dollars(task.cost)}")
    return " · ".join(parts)


def finished_alert(task):
    """Alerte de fin (finie ou échouée) ; un clic ouvre l'application sur la tâche (`task:<id>`)."""
    ok = task.state == DONE
    body = _short(task.message)
    extra = summary(task)
    if not ok and task.error:
        body += f"\n{task.error}"
    if extra:
        body += f"\n{extra}"
    return alerts_alert(f"task:{task.id}:{task.state}", "Tâche finie" if ok else "Tâche échouée",
                        body, 1 if ok else 2, task.id)


def alerts_alert(key, title, body, urgency, task_id):
    from .alerts import Alert
    return Alert(key, title, body, urgency, (("task:" + task_id, "Voir la tâche"),), "task:" + task_id)


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------

def tick(now=None, settings=None, state=None, paused=False, runner=None, tz=None):
    """Un tour du service : suit la tâche en cours (fin, limite atteinte), puis lance la
    suivante si la décision le permet. Renvoie les alertes (fin, échec) à envoyer.
    `state` : state.json ; `runner` : module `task_runner` (injectable pour les tests)."""
    now = now or datetime.now(timezone.utc)
    cfg = config(settings)
    if runner is None:
        from . import task_runner as runner
    out = []
    tasks = all()
    for t in tasks:
        if t.state == RUNNING:
            res = runner.poll(t, now)
            if res is not None:
                alert = _apply_result(t, res, now, cfg)
                if alert:
                    out.append(alert)
    if not cfg["enabled"]:
        return out
    tasks = all()
    pick = decide(tasks, now, settings, state, paused, tz)
    if pick is not None:
        ok, msg = runner.prepare(pick, state, settings, now)
        if not ok:
            update(pick.id, note=msg or "", retry_at=now.timestamp() + RETRY_S,
                   **({"state": WAITING} if pick.state == WAITING else {}))
        elif pick.state == WAITING and pick.attempts >= cfg["max_attempts"]:
            alert = _fail(pick, f"limite atteinte {pick.attempts} fois : abandon", now)
            out.append(alert)
        else:
            try:
                runner.start(pick, now, resume=pick.state == WAITING, attempts=pick.attempts + (pick.state == WAITING))
            except (OSError, ValueError) as e:
                out.append(_fail(pick, f"lancement impossible : {e}", now))
    return out


def _fail(task, message, now):
    t = update(task.id, state=FAILED, finished=now.timestamp(), pid=None, error=message, note=message)
    return finished_alert(t) if t else None


def _apply_result(task, res, now, cfg):
    """Applique la fin d'un lancement (`task_runner.Result`) ; renvoie l'alerte éventuelle."""
    total = (task.duration or 0) + (res.duration or 0)
    changes = {"pid": None, "duration": total, "session_id": res.session_id or task.session_id}
    if task.state != RUNNING:     # annulée pendant ce temps
        return None
    if res.cost:
        changes["cost"] = res.cost if res.total else (task.cost or 0) + res.cost
    if res.limit and not res.cancelled:
        if task.attempts >= cfg["max_attempts"] or not (res.session_id or task.session_id):
            reason = (f"limite atteinte {task.attempts} fois : abandon" if task.attempts >= cfg["max_attempts"]
                      else "limite atteinte, conversation introuvable pour la reprendre")
            t = update(task.id, state=FAILED, finished=now.timestamp(), error=reason, note=reason, **changes)
            return finished_alert(t)
        update(task.id, state=WAITING, retry_at=now.timestamp(), note="limite atteinte : reprise après la bascule",
               **changes)
        return None
    if res.ok:
        t = update(task.id, state=DONE, finished=now.timestamp(), error=None, note="", **changes)
    else:
        t = update(task.id, state=FAILED, finished=now.timestamp(), error=res.error or "échec", note=res.error or "",
                   **changes)
    return finished_alert(t)


# --------------------------------------------------------------------------
# Textes et commande
# --------------------------------------------------------------------------

def when_text(task, tz=None):
    if task.when == "nuit":
        return "cette nuit"
    if task.when == "quota":
        return "dès qu'il y a du quota"
    return f"à partir de {task.when}"


def line(task):
    """Ligne de liste : « 3  En cours  ~/App  Corrige les tests… »."""
    home = str(core.paths().home)
    cwd = "~" + task.cwd[len(home):] if task.cwd == home or task.cwd.startswith(home + "/") else task.cwd
    extra = task.note if task.state in (QUEUED, WAITING) and task.note else summary(task)
    return f"{task.id:>3}  {STATE_LABELS[task.state]:<30} {cwd}  {_short(task.message, 50)}" + (f"  ({extra})" if extra else "")


def parse_add(args):
    """Arguments de `ccs tache ajouter` : dict (message, cwd, model, rights, when) ; ValueError."""
    out = {"message": None, "cwd": None, "model": None, "rights": DEFAULT_RIGHTS, "when": "quota"}
    keys = {"-C": "cwd", "--dossier": "cwd", "--modele": "model", "--modèle": "model",
            "--droits": "rights", "--quand": "when"}
    args = list(args)
    i = 0
    while i < len(args):
        a = args[i]
        if a in keys or any(a.startswith(k + "=") for k in keys if k.startswith("--")):
            if "=" in a and a.startswith("--"):
                k, v = a.split("=", 1)
            else:
                k = a
                i += 1
                if i >= len(args):
                    raise ValueError(f"{a} attend une valeur")
                v = args[i]
            out[keys[k]] = v
        elif a.startswith("-") and a != "-":
            raise ValueError(f"option inconnue : {a}")
        elif out["message"] is None:
            out["message"] = a
        else:
            raise ValueError("un seul message (entre guillemets)")
        i += 1
    if not out["message"]:
        raise ValueError("message manquant")
    return out


def follow(task_id, out, wait=True, sleep=None):
    """Affiche le journal lisible de la tâche ; suit jusqu'à la fin si `wait`. Code de sortie."""
    import time
    from . import task_runner
    pos = 0
    while True:
        p = journal_path(task_id)
        try:
            with open(p, "rb") as f:
                f.seek(pos)
                data = f.read()
            # seules les lignes complètes sont lues
            cut = data.rfind(b"\n") + 1
            for raw in data[:cut].splitlines():
                text = task_runner.readable(raw.decode("utf-8", "replace"))
                if text:
                    print(text, file=out)
            pos += cut
        except OSError:
            pass
        t = get(task_id)
        if not wait or t is None or t.state in FINISHED:
            if t is not None:
                print(f"— {STATE_LABELS[t.state]}" + (f" : {summary(t)}" if summary(t) else ""), file=out)
            return 0 if t is not None and t.state == DONE else (0 if not wait else 1)
        (sleep or time.sleep)(1.0)


def command(args, out=None, err=None, now=None):
    """`ccs tache [ajouter|voir|annuler|supprimer]` : renvoie le code de sortie."""
    import sys
    out, err = out or sys.stdout, err or sys.stderr
    args = list(args)
    sub = args.pop(0) if args else "liste"
    try:
        if sub in ("liste", "list", "ls"):
            tasks = all()
            if not tasks:
                print("Aucune tâche. Ajoute-en une : ccs tache ajouter \"<message>\"", file=out)
            for t in tasks:
                print(line(t), file=out)
            return 0
        if sub in ("ajouter", "add"):
            t = add(now=now, **parse_add(args))
            print(f"Tâche {t.id} ajoutée ({when_text(t)}, {RIGHTS_LABELS[t.rights].lower()}) dans {t.cwd}", file=out)
            return 0
        if sub in ("-h", "--help", "aide"):
            print(USAGE, file=out)
            return 0
        if sub in ("voir", "suivre", "show", "annuler", "cancel", "supprimer", "remove", "rm"):
            if len(args) != 1 or not ID_RE.match(args[0]):
                print(USAGE, file=err)
                return 2
            tid = args[0]
            if sub in ("voir", "suivre", "show"):
                if get(tid) is None:
                    print(f"ccs : tâche {tid} inconnue", file=err)
                    return 1
                return follow(tid, out)
            fn = cancel if sub in ("annuler", "cancel") else remove
            if fn(tid) is None:
                print(f"ccs : tâche {tid} inconnue", file=err)
                return 1
            print(f"Tâche {tid} " + ("annulée" if fn is cancel else "supprimée"), file=out)
            return 0
    except (ValueError, OSError) as e:
        print(f"ccs : {e}", file=err)
        return 1
    print(USAGE, file=err)
    return 2
