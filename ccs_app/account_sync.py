"""Synchronisation des comptes Claude entre les machines (réseau maillé, SSH).

Chaque machine garde ses profils dans ~/.claude-accounts/<nom>/ (account.json, oauth.json).
Un jeton OAuth renouvelé sur une machine invalide l'ancien partout ailleurs (rotation) : on
recopie donc partout la version la plus récente de chaque profil, celle dont `expiresAt` est
le plus grand. Le compte actif d'une machine est lu (et mis à jour) dans son fichier de
connexion vivant (~/.claude/.credentials.json), plus récent que sa copie dans le profil.

Le même petit script Python tourne sur chaque machine (ici comme là-bas, par `ssh`) : il ne
dépend pas de CCS, une machine avec une ancienne version suffit. Les jetons ne sont jamais
affichés ni écrits ailleurs que dans les fichiers 600 du profil.
"""

import json
import os
import shlex
import subprocess

# Script lancé par `python3 -c` : `lire` imprime les profils en JSON, `ecrire` lit sur l'entrée
# les profils à poser et n'écrit que ceux plus récents que la copie locale.
AGENT = r'''
import fcntl, json, os, sys, tempfile
from pathlib import Path
home = Path(os.environ.get("HOME") or Path.home())
cfg = Path(os.environ["CLAUDE_CONFIG_DIR"]) if os.environ.get("CLAUDE_CONFIG_DIR") else home / ".claude"
gjson = cfg / ".claude.json" if os.environ.get("CLAUDE_CONFIG_DIR") else home / ".claude.json"
creds = cfg / ".credentials.json"
store = Path(os.environ.get("CCS_HOME") or home / ".claude-accounts")
def load(p):
    try:
        with open(p) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}
def save(p, d):
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=p.parent)
    with os.fdopen(fd, "w") as f:
        json.dump(d, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
def key(a):
    return f"{a.get('accountUuid')}|{a.get('organizationUuid')}" if a.get("accountUuid") else None
def exp(o):
    return int((o.get("claudeAiOauth") or {}).get("expiresAt") or 0)
store.mkdir(mode=0o700, parents=True, exist_ok=True)
lock = open(store / ".lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX)
live_key = key(load(gjson).get("oauthAccount") or {})
live = load(creds)
tomb_file = store / ".supprimes.json"
tombs = load(tomb_file)
def profiles():
    out = {}
    for d in sorted(p for p in store.iterdir() if p.is_dir() and not p.name.startswith(".")):
        acc = load(d / "account.json")
        if not key(acc):
            continue
        oauth = load(d / "oauth.json")
        active = key(acc) == live_key
        if active and (live.get("claudeAiOauth") or {}).get("refreshToken") and exp(live) > exp(oauth):
            oauth = {**oauth, "claudeAiOauth": live["claudeAiOauth"]}
        out[d.name] = {"account": acc, "oauth": oauth, "active": active,
                       "added": (d / "account.json").stat().st_mtime}
    return out
def buried(name, p):
    t = tombs.get(name) or {}
    return t.get("key") == key(p.get("account") or {}) and t.get("at", 0) >= p.get("added", 0)
if sys.argv[1] == "lire":
    print(json.dumps({"p": profiles(), "s": tombs}))
else:
    inc = json.load(sys.stdin)
    changed = False
    for name, t in (inc.get("s") or {}).items():
        if (tombs.get(name) or {}).get("at", 0) < t.get("at", 0):
            tombs[name] = t
            changed = True
    if changed:
        save(tomb_file, tombs)
    have = profiles()
    done = []
    for name, p in have.items():
        if buried(name, p) and not p["active"]:
            for f in (store / name).iterdir():
                f.unlink()
            (store / name).rmdir()
            done.append("-" + name)
    have = {n: p for n, p in have.items() if not buried(n, p) or p["active"]}
    for name, p in (inc.get("p") or {}).items():
        if buried(name, p):
            continue
        if "/" in name or name.startswith(".") or not key(p.get("account") or {}):
            continue
        cur = have.get(name)
        if cur and key(cur["account"]) != key(p["account"]):
            continue
        if cur and exp(cur["oauth"]) >= exp(p["oauth"]):
            continue
        d = store / name
        save(d / "oauth.json", p["oauth"])
        if not cur:
            save(d / "account.json", p["account"])
        if cur and cur["active"] and (live.get("claudeAiOauth") or {}).get("refreshToken"):
            fresh = load(creds)
            if exp(fresh) < exp(p["oauth"]):
                fresh["claudeAiOauth"] = p["oauth"]["claudeAiOauth"]
                save(creds, fresh)
        done.append(name)
    print(json.dumps(done))
'''


class SyncError(Exception):
    pass


def _expires(profile):
    return int(((profile.get("oauth") or {}).get("claudeAiOauth") or {}).get("expiresAt") or 0)


def _key(profile):
    acc = profile.get("account") or {}
    return f"{acc.get('accountUuid')}|{acc.get('organizationUuid')}"


def tombs_of(views):
    """Suppressions connues de toutes les machines : {profil: {"key", "at"}}, la plus récente."""
    out = {}
    for view in views.values():
        for name, t in (view.get("s") or {}).items():
            if (out.get(name) or {}).get("at", 0) < t.get("at", 0):
                out[name] = t
    return out


def buried(name, p, tombs):
    t = tombs.get(name) or {}
    return t.get("key") == _key(p) and t.get("at", 0) >= p.get("added", 0)


def merge(views, tombs=None):
    """{machine: {"p": profils, "s": suppressions}} → {profil: (machine source, données)} :
    pour chaque profil, la version au jeton le plus récent. Deux comptes différents sous le même
    nom : le premier vu reste, l'autre est ignoré (jamais écrasé). Un profil supprimé (et non
    rajouté depuis) disparaît."""
    tombs = tombs_of(views) if tombs is None else tombs
    best = {}
    for machine, view in views.items():
        for name, p in (view.get("p") or {}).items():
            if buried(name, p, tombs):
                continue
            cur = best.get(name)
            if cur is None or (_key(cur[1]) == _key(p) and _expires(p) > _expires(cur[1])):
                best[name] = (machine, p)
    return best


def plan(views):
    """{machine: {"p": profils à poser, "s": suppressions}} : ce que chaque machine reçoit."""
    tombs = tombs_of(views)
    best = merge(views, tombs)
    out = {}
    for machine, view in views.items():
        profiles = view.get("p") or {}
        todo = {}
        for name, (_src, p) in best.items():
            mine = profiles.get(name)
            if mine is None or (_key(mine) == _key(p) and _expires(mine) < _expires(p)):
                todo[name] = {"account": p["account"], "oauth": p["oauth"], "added": p.get("added", 0)}
        dead = any(buried(n, p, tombs) for n, p in profiles.items())
        if todo or dead or (view.get("s") or {}) != tombs:
            out[machine] = {"p": todo, "s": tombs}
    return out


def bury(name, now=None):
    """Note ici la suppression du profil `name` (à appeler avant d'effacer son dossier) : la
    prochaine synchronisation l'efface aussi des autres machines."""
    import time
    from .core import load_json, atomic_write_json, paths
    store = paths().store
    acc = load_json(store / name / "account.json")
    if not acc.get("accountUuid"):
        return
    f = store / ".supprimes.json"
    tombs = load_json(f)
    tombs[name] = {"key": f"{acc.get('accountUuid')}|{acc.get('organizationUuid')}",
                   "at": time.time() if now is None else now}
    atomic_write_json(f, tombs)


def _local_runner(action, data=None, timeout=30):
    return subprocess.run(["python3", "-c", AGENT, action], input=data, capture_output=True,
                          text=True, timeout=timeout)


def _ssh_runner(machine, overrides):
    from . import distant

    def run(action, data=None, timeout=30):
        cmd = f"python3 -c {shlex.quote(AGENT)} {action}"
        return distant._ssh(machine, overrides, cmd, capture_output=True, text=True,
                            input=data, timeout=timeout)
    return run


def runners(only=None):
    """{nom de machine: fonction d'appel} : cette machine et les autres machines en ligne
    joignables en SSH, plus la liste des machines laissées de côté (avec la raison)."""
    from . import distant
    out = {"ici": _local_runner}
    skipped = []
    if os.environ.get("CCS_NO_ACCOUNT_SYNC") == "1":   # tests : jamais les vraies machines
        return out, [("réseau", "synchro coupée (CCS_NO_ACCOUNT_SYNC)")]
    try:
        overrides = distant.load_overrides()
        machines = distant.list_machines(overrides=overrides)
    except distant.DistantError as e:
        return out, [("réseau", str(e))]
    for m in machines:
        if m.local or (only and m.id not in only):
            continue
        if not m.online:
            skipped.append((m.id, "hors ligne"))
        elif distant.ssh_port(m, overrides) is None:
            skipped.append((m.id, "pas de SSH"))
        else:
            out[m.id] = _ssh_runner(m, overrides)
    return out, skipped


def sync(only=None, runners_fn=runners):
    """Synchronise les profils. Renvoie {"recu": {machine: [profils]}, "absentes": [(machine,
    raison)]}. Une machine injoignable est laissée de côté sans bloquer les autres."""
    calls, skipped = runners_fn(only)
    views = {}
    for name, run in calls.items():
        try:
            r = run("lire")
            if r.returncode != 0:
                raise SyncError((r.stderr or "").strip().splitlines()[-1:] or ["erreur"])
            views[name] = json.loads(r.stdout)
        except (subprocess.TimeoutExpired, OSError, ValueError, SyncError) as e:
            skipped.append((name, f"injoignable ({type(e).__name__})"))
    received = {}
    for name, todo in plan(views).items():
        try:
            r = calls[name]("ecrire", json.dumps(todo))
            if r.returncode == 0:
                received[name] = json.loads(r.stdout)
            else:
                skipped.append((name, "écriture refusée"))
        except (subprocess.TimeoutExpired, OSError, ValueError):
            skipped.append((name, "écriture interrompue"))
    return {"machines": sorted(views), "recu": received, "absentes": skipped}


def describe(res):
    lines = [f"Machines lues : {', '.join(res['machines']) or 'aucune'}."]
    for m, names in sorted(res["recu"].items()):
        got = [n for n in names if not n.startswith("-")]
        gone = [n[1:] for n in names if n.startswith("-")]
        if got:
            lines.append(f"{m} : {', '.join(got)} mis à jour.")
        if gone:
            lines.append(f"{m} : {', '.join(gone)} supprimé(s).")
    if not any(res["recu"].values()):
        lines.append("Tous les comptes étaient déjà à jour partout.")
    for m, why in res["absentes"]:
        lines.append(f"{m} : {why}.")
    return lines
