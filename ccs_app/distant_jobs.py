"""Registre des commandes lancées par `ccs remote run` (calcul réparti).

Un fichier JSON par travail dans `~/.cache/ccs/machines/jobs/<id>.json` (`~/.cache` suit
`XDG_CACHE_HOME` ; `distant/travaux/` avant la 1.0.0, renommé tout seul), écrit de façon
atomique ; le journal d'un travail détaché est `<id>.log` à côté. Toute lecture-écriture passe
par un verrou (`fcntl.flock` sur `.lock`) : plusieurs `ccs remote run` simultanés comptent
ainsi les places des machines sans se marcher dessus.

États (en anglais, comme ceux des tâches) : `waiting` (pas de place libre), `scheduled`
(`--quand`), `sending` (copie du projet), `running`, puis `done`, `failed` ou `stopped`. Un
travail actif dont le processus a disparu est montré `stopped` (« processus disparu »).
L'affichage en français passe par `label(state)`. Les fichiers écrits avant la 1.0.0 portent les
anciens états français : ils sont convertis à la lecture (`OLD_STATES`).
"""

import fcntl
import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import core, migrate

ACTIVE = ("waiting", "scheduled", "sending", "running")
WAITING = ("waiting", "scheduled")
RUNNING = ("sending", "running")
FINAL = ("done", "failed", "stopped")
LABELS = {"waiting": "attente", "scheduled": "programmé", "sending": "envoi",
          "running": "en cours", "done": "fini", "failed": "échec", "stopped": "arrêté"}
# anciens états français (fichiers écrits avant la 1.0.0) → nouveaux
OLD_STATES = {v: k for k, v in LABELS.items()}
KEEP = 30                   # travaux finis gardés au moins
KEEP_RECENT = 24 * 3600     # et tous ceux de moins de 24 h
ID_RE = re.compile(r"^[0-9a-f]{6,16}$")


def jobs_dir():
    cache = core.ccs_dir("cache")
    d = migrate.renamed(cache / "machines" / "jobs", cache / "distant" / "travaux")
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def _path(job_id):
    return jobs_dir() / f"{job_id}.json"


def log_path(job_id):
    return jobs_dir() / f"{job_id}.log"


@contextmanager
def locked():
    """Verrou exclusif sur le registre, partagé entre processus."""
    with open(jobs_dir() / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read(job_id):
    if not isinstance(job_id, str) or not ID_RE.match(job_id):
        return None
    try:
        job = json.loads(_path(job_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(job, dict) or job.get("id") != job_id:
        return None
    if job.get("state") in OLD_STATES:
        job["state"] = OLD_STATES[job["state"]]
    return job


def label(state):
    """État d'un travail en français, pour l'affichage (`ccs remote jobs`, pages)."""
    return LABELS.get(state, state or "?")


def legacy_view(job):
    """Le travail avec l'ancien état français (anciens clients du pont). Compatibilité 1.x,
    à retirer en 2.0."""
    return dict(job, state=LABELS.get(job.get("state"), job.get("state")))


def _write(job):
    core.atomic_write_json(_path(job["id"]), job)


def _all():
    out = []
    for p in jobs_dir().glob("*.json"):
        job = _read(p.stem)
        if job is not None:
            out.append(job)
    return out


def _view(job):
    """Le travail tel qu’on le montre : actif mais processus mort → `stopped`."""
    if job.get("state") in ACTIVE and job.get("pid") and not alive(job["pid"]):
        job = dict(job, state="stopped", why="processus disparu")
    return job


def _prune(now):
    finished = sorted((j for j in map(_view, _all()) if j.get("state") in FINAL),
                      key=lambda j: j.get("ended") or j.get("created") or 0, reverse=True)
    for job in finished[KEEP:]:
        if now - (job.get("ended") or job.get("created") or 0) < KEEP_RECENT:
            continue
        for p in (_path(job["id"]), log_path(job["id"])):
            try:
                p.unlink()
            except OSError:
                pass


def create(command, cwd, machine=None, tool=None, when="", not_before=None, why="",
           detached=False, pid=None, now=time.time):
    """Inscrit un travail (`scheduled` si `not_before` est à venir, sinon `waiting`)."""
    t = now()
    with locked():
        _prune(t)
        while True:
            job_id = secrets.token_hex(3)
            if not _path(job_id).exists():
                break
        text = command[0] if len(command) == 1 else shlex.join(command)
        job = {"id": job_id, "command": list(command), "text": text, "cwd": str(cwd),
               "machine": machine, "tool": tool,
               "state": "scheduled" if not_before and not_before > t else "waiting",
               "code": None, "created": t, "started": None, "ended": None, "when": when or "",
               "not_before": not_before, "pid": pid if pid is not None else os.getpid(),
               "detached": bool(detached), "log": str(log_path(job_id)) if detached else "",
               "why": why or ""}
        _write(job)
    return job_id


def update(job_id, **fields):
    """Change des champs d'un travail ; renvoie le travail, ou None s'il n'existe pas."""
    with locked():
        job = _read(job_id)
        if job is None:
            return None
        if fields.get("state") in OLD_STATES:
            fields["state"] = OLD_STATES[fields["state"]]
        job.update(fields)
        _write(job)
        return job


def finish(job_id, state, code=None, why="", now=time.time):
    """État final, sauf si le travail est déjà fini (un arrêt demandé reste un arrêt)."""
    with locked():
        job = _read(job_id)
        if job is None:
            return None
        if job.get("state") not in FINAL:
            job.update(state=OLD_STATES.get(state, state), code=code, why=why or "", ended=now())
            _write(job)
        return job


def reserve(job_id, machine_id, limit, now=time.time):
    """Prend une place sur la machine si elle en a une : (pris, travaux qui y tournent)."""
    with locked():
        job = _read(job_id)
        if job is None or job.get("state") in FINAL:
            raise KeyboardInterrupt  # arrêté pendant l'attente
        busy = sum(1 for j in _all() if j["id"] != job_id and j.get("machine") == machine_id
                   and j.get("state") in RUNNING and alive(j.get("pid")))
        if busy >= limit:
            return False, busy
        job.update(state="sending", machine=machine_id, started=now(), why="")
        _write(job)
        return True, busy


def stopped(job_id):
    job = _read(job_id)
    return job is None or job.get("state") in FINAL


def counts():
    """{machine: {"running": n, "waiting": n}} des travaux actifs."""
    out = {}
    for job in map(_view, _all()):
        state, mid = job.get("state"), job.get("machine")
        if not mid or state not in ACTIVE:
            continue
        c = out.setdefault(mid, {"running": 0, "waiting": 0})
        c["running" if state in RUNNING else "waiting"] += 1
    return out


# ------------------------------------------------------------------ interface du contrat

def list_jobs():
    """Actifs d'abord (plus récents en tête), puis finis (plus récents en tête), 30 au plus."""
    jobs = [_view(j) for j in _all()]
    active = sorted((j for j in jobs if j.get("state") in ACTIVE),
                    key=lambda j: j.get("created") or 0, reverse=True)
    done = sorted((j for j in jobs if j.get("state") not in ACTIVE),
                  key=lambda j: j.get("ended") or j.get("created") or 0, reverse=True)
    return (active + done)[:KEEP]


def get(job_id):
    job = _read(job_id)
    return _view(job) if job is not None else None


def stop(job_id, now=time.time):
    """Arrête un travail : retiré de la file s'il attend, SIGTERM à son processus sinon."""
    with locked():
        job = _read(job_id)
        if job is None or _view(job).get("state") not in ACTIVE:
            return False
        pid = job.get("pid")
        if job.get("state") in WAITING or not alive(pid):
            job.update(state="stopped", ended=now(), code=None,
                       why="arrêté avant le départ" if job.get("state") in WAITING else "arrêté")
            _write(job)
    if alive(pid) and pid != os.getpid():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    return True


def read_log(job_id, tail=20000):
    """La fin du journal d'un travail détaché (« » s'il n'y en a pas)."""
    if not isinstance(job_id, str) or not ID_RE.match(job_id):
        return ""
    try:
        tail = max(int(tail), 0)
    except (TypeError, ValueError):
        tail = 20000
    try:
        with open(log_path(job_id), "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(size - tail, 0))
            data = f.read()
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


RUNNER = "import sys; from ccs_app import cli; sys.exit(cli.main(sys.argv[1:]))"


def start(command, cwd, machine=None, tool=None, when="", *, fetch=(), include=(),
          with_git=False, popen=None):
    """Lance un travail détaché (`ccs remote run --detach …` à part) ; renvoie son id."""
    from . import distant
    command = list(command)
    if not command:
        raise distant.DistantError("Aucune commande à lancer")
    not_before, why = distant.schedule(when)
    job_id = create(command, cwd, machine=machine, tool=tool, when=when, not_before=not_before,
                    why=why, detached=True, pid=0)
    argv = [sys.executable, "-c", RUNNER, "distant", "lancer", "--detache", "--travail", job_id]
    if machine:
        argv += ["--machine", machine]
    if tool:
        argv += ["--outil", tool]
    if when:
        argv += ["--quand", when]
    for p in fetch:
        argv += ["--rapatrier", p]
    for p in include:
        argv += ["--inclure", p]
    if with_git:
        argv.append("--avec-git")
    argv += ["--", *command]
    env = dict(os.environ)
    base = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = base + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        with open(log_path(job_id), "ab") as log:
            p = (popen or subprocess.Popen)(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
    except OSError as e:
        finish(job_id, "failed", why=f"lancement impossible : {e}")
        raise distant.DistantError(f"Lancement impossible : {e}") from None
    update(job_id, pid=p.pid)
    if hasattr(p, "wait"):  # pas de processus zombie dans le pont
        threading.Thread(target=p.wait, daemon=True).start()
    return job_id
