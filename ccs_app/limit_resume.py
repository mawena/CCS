"""Relance des conversations bloquées par une limite, une fois la limite levée.

Le hook StopFailure (`integration.stop_failure`) laisse un marqueur par conversation bloquée
(`limit_events`). Quand il a pu changer de compte, l'interface qui tient la conversation la
relance tout de suite. Sinon (aucun compte libre, bascule impossible, CCS en pause), ce module :

1. calcule quand la limite se lève (`lift_at`) : réinitialisation de la fenêtre de 5 h ou de la
   semaine du compte actif, ou retour d'un autre compte sous les seuils ;
2. écrit cette heure dans le marqueur (outcome « planned », `resume_at`) : chaque interface
   affiche « relance prévue à HH:MM » ;
3. à l'heure dite (`advance`), vérifie que la limite est bien levée, change de compte si c'est
   un autre qui s'est libéré, et passe le marqueur à « lifted ». Une seule bascule et une seule
   notification pour toutes les conversations bloquées en même temps ;
4. l'interface qui tient la conversation (onglet de terminal, chat du bureau, chat du pont pour
   le web, Android, iPhone et la TUI) prend le marqueur (`limit_events.consume`, un seul
   gagnant) et envoie « continue » ;
5. un marqueur « lifted » que personne n'a pris après `GRACE_S` est une conversation ouverte hors
   de CCS : notification, ou relance en arrière-plan (`claude --resume … -p continue`) si la
   conversation n'est plus ouverte nulle part et que le réglage le demande.

`advance` peut tourner dans plusieurs processus (service, application, pont) : un verrou (celui
du hook) fait qu'un seul agit à la fois ; s'il est pris, on passe son tour.

Réglage `limit_resume` : {"enabled": true, "outside": "notify" | "resume"}.
"""

import contextlib
import fcntl
import logging
import os
import subprocess
import time
from datetime import datetime, timezone

from . import core, limit_events

log = logging.getLogger(__name__)

TEXT = "continue"
CAP = 95                 # % au-delà duquel un compte est considéré comme bloqué
MARGIN_S = 60            # après la réinitialisation annoncée, le temps que le serveur suive
UNKNOWN_S = 3600         # levée inconnue : nouvel essai dans une heure
RETRY_S = 600            # heure passée mais limite pas levée : nouvel essai dans 10 min
GRACE_S = 180            # « lifted » non pris par une interface : conversation hors de CCS
MAX_AGE_S = 8 * 24 * 3600  # au-delà (plus d'une semaine), on abandonne
CHECK_S = 30             # cadence conseillée aux interfaces pour appeler `advance`
OUTSIDE = ("notify", "resume")
HOOK_WAIT_S = 60          # limite vue par une interface sans marqueur du hook
MAX_PER_HOUR = 3         # reprises automatiques par conversation et par heure


def config(settings):
    """Réglage `limit_resume` lu sans jamais lever."""
    cfg = (settings or {}).get("limit_resume") if isinstance(settings, dict) else None
    cfg = cfg if isinstance(cfg, dict) else {}
    outside = cfg.get("outside")
    return {"enabled": cfg.get("enabled", True) is not False,
            "outside": outside if outside in OUTSIDE else "notify"}


def hhmm(ts, now=None):
    """« 14:05 », ou « mar. 14:05 » si ce n'est pas aujourd'hui (heure locale)."""
    when = datetime.fromtimestamp(ts).astimezone()
    today = datetime.fromtimestamp(time.time() if now is None else now).astimezone().date()
    if when.date() == today:
        return f"{when:%H:%M}"
    days = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
    return f"{days[when.weekday()]} {when.day:02d}/{when.month:02d} {when:%H:%M}"


def planned_text(event, now=None):
    """Bandeau d'une relance prévue (ou None si rien n'est prévu)."""
    if event.outcome != "planned" or event.resume_at is None:
        return None
    head = f"Limite atteinte sur {event.source}" if event.source else "Limite atteinte"
    return f"{head} : relance prévue à {hhmm(event.resume_at, now)}."


def lifted_text(event):
    to = f" (compte {event.target})" if event.target else ""
    return f"Limite levée{to} : conversation relancée."


# ---- quand la limite se lève --------------------------------------------------------

def _blocked_until(account, now, cap_weekly):
    times = []
    from .forecast import effective_percent
    for lim in account.limits:
        cap = CAP if lim.kind == "session" else cap_weekly
        if effective_percent(lim, now) >= cap and lim.resets_at:
            times.append(lim.resets_at)
    return max(times) if times else None


def usable(account, now, cap_weekly=CAP):
    """Le compte peut-il reprendre maintenant ? (données présentes, pas d'erreur bloquante, toutes
    ses limites sous les seuils)."""
    from .forecast import effective_percent
    if account is None or account.blocking_error or not account.limits:
        return False
    return all(effective_percent(l, now) < (CAP if l.kind == "session" else cap_weekly)
               for l in account.limits)


def lift_at(accounts, active, now, cap_weekly=CAP):
    """Heure (datetime) où la limite se lève : la plus proche entre la réinitialisation du compte
    actif et le retour d'un autre compte sous les seuils. Inconnue : dans UNKNOWN_S."""
    from datetime import timedelta
    times = []
    for a in accounts:
        if a.blocking_error or not a.limits:
            continue
        t = _blocked_until(a, now, CAP if a.name == active else cap_weekly)
        if t is None and a.name == active:
            # Données en retard sur la limite : la fenêtre de 5 h en cours est la plus probable.
            session = next((l for l in a.limits if l.kind == "session" and l.resets_at), None)
            t = session.resets_at if session and session.resets_at > now else None
        if t is not None:
            times.append(t)
    if not times:
        return now + timedelta(seconds=UNKNOWN_S)
    return max(min(times), now) + timedelta(seconds=MARGIN_S)


def _pause_until(now):
    """None : pas en pause ; datetime : fin de la pause ; False : pause sans fin."""
    try:
        from . import pause
        st = pause.pause_state(now)
    except (OSError, ValueError, TypeError, OverflowError):
        return None
    if st is None:
        return None
    return st.until if st.until is not None else False


def plan(accounts, active, now, cap_weekly=CAP, paused=None):
    """Epoch de la relance à prévoir, ou None (pause sans fin : pas de relance)."""
    if paused is False:
        return None
    t = lift_at(accounts, active, now, cap_weekly)
    if paused is not None and paused > t:
        t = paused
    return t.timestamp()


# ---- avancement des marqueurs -------------------------------------------------------

@contextlib.contextmanager
def _try_lock():
    """Verrou du hook, sans attendre : None s'il est pris (un autre processus agit)."""
    path = core.paths().store / "hook.lock"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(path, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _states():
    from . import daemon
    st = core.load_json(daemon.state_path()) or {}
    accounts = daemon.states_from_state(st)
    active = next((a.name for a in accounts if a.active), None) or core.active_profile_name()
    reserve = set(((st.get("orchestrator") or {}).get("reserve")) or [])
    return accounts, active, reserve


def _settings():
    from . import settings
    try:
        return settings.load_settings()
    except Exception:   # réglages illisibles : valeurs par défaut
        return settings.DEFAULTS


def _switch(accounts, active, settings, now, reserve):
    """Bascule vers un compte libre (comme le hook) : nom du compte, ou None."""
    from . import autoswitch
    from .store import Store
    try:
        decision = autoswitch.rescue(accounts, active, settings, now, reserve)
    except (KeyError, TypeError):
        return None
    if decision.action != "switch":
        return None
    return decision.target if autoswitch.execute(decision, Store(), now, mode="relance") else None


def advance(now=None, accounts=None, active=None, settings=None, reserve=None, notifier=None,
            live=None, spawner=None):
    """Fait avancer les marqueurs : prévoit, lève, traite ceux restés sans preneur. Renvoie la
    prochaine échéance (epoch) ou None. Ne lève jamais. Arguments None : lus sur disque."""
    try:
        return _advance(now, accounts, active, settings, reserve, notifier, live, spawner)
    except Exception:
        log.exception("relance après limite en échec")
        return None


def _advance(now, accounts, active, settings, reserve, notifier, live, spawner):
    events = limit_events.load_all()
    work = [e for e in events.values() if e.outcome in limit_events.WAITING or e.outcome == "lifted"]
    if not work:
        return None
    settings = _settings() if settings is None else settings
    cfg = config(settings)
    ts = time.time() if now is None else now
    if not cfg["enabled"]:
        return None
    with _try_lock() as held:
        if not held:
            return ts + CHECK_S
        if accounts is None:
            accounts, active_disk, reserve_disk = _states()
            active = active_disk if active is None else active
            reserve = reserve_disk if reserve is None else reserve
        reserve = reserve or set()
        dt = datetime.fromtimestamp(ts, timezone.utc)
        try:
            cap_weekly = float(settings["auto_switch"]["target_max_weekly"])
        except (KeyError, TypeError, ValueError):
            cap_weekly = CAP
        paused = _pause_until(dt)
        nxt = []
        due, orphans = [], []
        for e in work:
            if ts - e.ts > MAX_AGE_S:
                limit_events.consume(e.session_id, e.ts)
                continue
            if e.outcome == "lifted":
                if ts - (e.lifted_at or e.ts) >= GRACE_S:
                    orphans.append(e)
                else:
                    nxt.append((e.lifted_at or e.ts) + GRACE_S)
                continue
            if e.outcome != "planned" or e.resume_at is None:
                at = plan(accounts, active, dt, cap_weekly, paused)
                if at is None:
                    continue           # pause sans fin : on attend la reprise manuelle
                e = limit_events.update(e, outcome="planned", resume_at=at) or e
            if e.resume_at is not None and e.resume_at <= ts:
                due.append(e)
            elif e.resume_at is not None:
                nxt.append(e.resume_at)
        if due:
            nxt += _lift(due, accounts, active, settings, dt, cap_weekly, reserve, paused, notifier)
        if orphans:
            _outside(orphans, cfg, notifier, live, spawner)
        return min(nxt) if nxt else None


def _lift(due, accounts, active, settings, dt, cap_weekly, reserve, paused, notifier):
    """Échéance atteinte : limite levée (même compte ou bascule) ou nouvelle échéance."""
    ts = dt.timestamp()
    target = None
    if paused is None:
        act = next((a for a in accounts if a.name == active), None)
        if usable(act, dt, cap_weekly):
            target = active
        else:
            target = _switch(accounts, active, settings, dt, reserve)
    if target is None:
        at = plan(accounts, active, dt, cap_weekly, paused)
        if at is not None and at <= ts + MARGIN_S:
            at = ts + RETRY_S        # données pas encore à jour : on réessaie bientôt
        out = []
        for e in due:
            if at is None:
                limit_events.update(e, outcome="paused", resume_at=None)
            else:
                limit_events.update(e, resume_at=at)
                out.append(at)
        return out
    for e in due:
        limit_events.update(e, outcome="lifted", lifted_at=ts, target=target,
                            switched=target != active)
    if notifier is not None:
        from .alerts import Alert
        n = len(due)
        what = "la conversation bloquée" if n == 1 else f"les {n} conversations bloquées"
        via = f" (compte {target})" if target != active else ""
        notifier(Alert(f"relance:{ts:.0f}", "Limite levée", f"Relance de {what}{via}.", 1))
    return [ts + GRACE_S]


def _outside(orphans, cfg, notifier, live, spawner):
    """Marqueurs levés que personne n'a pris : conversations ouvertes hors de CCS."""
    if live is None:
        from . import sessions
        try:
            live = sessions.list_sessions()
        except OSError:
            live = []
    open_ids = {s.session_id for s in live}
    notify_names = []
    for e in orphans:
        if not limit_events.consume(e.session_id, e.ts):
            continue            # pris entre-temps
        name = os.path.basename((e.cwd or "").rstrip("/")) or "une conversation"
        if e.session_id not in open_ids and cfg["outside"] == "resume" and e.cwd and os.path.isdir(e.cwd):
            if (spawner or spawn_resume)(e.cwd, e.session_id):
                continue
        notify_names.append(name)
    if notify_names and notifier is not None:
        from .alerts import Alert
        names = ", ".join(dict.fromkeys(notify_names))
        notifier(Alert(f"relance-dehors:{time.time():.0f}", "Limite levée",
                       f"Tu peux reprendre ({names}) : tape « continue » dans la session.", 1))


def spawn_resume(cwd, session_id):
    """Relance en arrière-plan une conversation fermée : `claude --resume <id> -p continue`,
    détachée, de faible priorité. Sortie dans ~/.claude-accounts/limits/<id>.log."""
    from . import sessions, terminal
    log_path = limit_events.directory() / f"{session_id}.log"
    try:
        out = open(log_path, "ab")
        os.chmod(log_path, 0o600)
    except OSError:
        return False
    try:
        subprocess.Popen(["nice", "-n", "10", sessions._claude_bin(), "--resume", session_id, "-p", TEXT],
                         cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                         env=terminal._unset_prefix(dict(os.environ)), start_new_session=True)
        return True
    except OSError:
        return False
    finally:
        out.close()


# ---- côté interface : une conversation tenue par CCS --------------------------------

class Follower:
    """Suit une conversation tenue par une interface (chat du pont, chat du bureau). `step` dit
    quoi faire à chaque passage : liste de (« notice », texte, genre) et (« send », TEXT).

    Une note par état (prévue, relancée…), un seul « continue » par événement, et au plus
    MAX_PER_HOUR par heure."""

    def __init__(self):
        self.shown = set()
        self.resumes = []
        self.typed_at = None
        self.limit_seen = None     # fin de tour « limite atteinte » vue par l'interface

    def typed(self, ts=None):
        self.typed_at = time.time() if ts is None else ts

    def limit_hit(self, ts=None):
        self.limit_seen = time.time() if ts is None else ts

    def step(self, event, now, can_send, enabled=True, session_id=None, cwd=None):
        """`event` : marqueur de la conversation (ou None) ; `can_send` : Claude attend un
        message (au repos ou suspendu). Les marqueurs pris sont consommés ici.

        Limite vue sans marqueur après HOOK_WAIT_S (hook absent ou pas déclenché) : on écrit
        nous-mêmes un marqueur « exhausted », pour que la relance soit prévue."""
        out = []
        if event is None:
            if (self.limit_seen is not None and session_id and enabled
                    and now - self.limit_seen >= HOOK_WAIT_S):
                seen, self.limit_seen = self.limit_seen, None
                if self.typed_at is None or self.typed_at <= seen:
                    limit_events.record(session_id, seen, core.active_profile_name(), None, False,
                                        "exhausted", cwd)
            return out
        self.limit_seen = None
        key = (event.ts, event.outcome, event.resume_at)
        if event.outcome == "planned":
            if key not in self.shown:
                self.shown.add(key)
                out.append(("notice", planned_text(event, now), "warning"))
            return out
        if event.outcome == "paused" and key not in self.shown:
            self.shown.add(key)
            out.append(("notice", "Limite atteinte : CCS est en pause, la relance attendra la reprise.",
                        "warning"))
            return out
        if event.outcome not in limit_events.RESUMABLE:
            return out
        since = event.lifted_at or event.ts
        if now - since > GRACE_S + 600:
            return out           # trop vieux : laissé au traitement « hors de CCS »
        if self.typed_at is not None and self.typed_at > event.ts:
            if limit_events.consume(event.session_id, event.ts):
                out.append(("notice", "Limite levée : pas de relance automatique, tu as écrit "
                                      "dans la conversation.", "info"))
            return out
        if not enabled:
            if limit_events.consume(event.session_id, event.ts):
                out.append(("notice", "Limite levée : tape « continue » pour reprendre.", "info"))
            return out
        if not can_send:
            return out
        recent = [t for t in self.resumes if now - t < 3600]
        if len(recent) >= MAX_PER_HOUR:
            if limit_events.consume(event.session_id, event.ts):
                out.append(("notice", f"Relance automatique suspendue ({len(recent)} en une heure) : "
                                      "tape « continue » pour reprendre.", "warning"))
            return out
        if limit_events.consume(event.session_id, event.ts):
            self.resumes = recent + [now]
            out.append(("send", TEXT))
            out.append(("notice", lifted_text(event) if event.outcome == "lifted" else
                        f"Compte changé pour {event.target or 'un autre compte'} : conversation relancée.",
                        "info"))
        return out


# ---- conversations lancées dans un terminal tenu par CCS (terminaux du pont) --------

def _ppid(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def descends_from(pid, ancestor, ppid=_ppid, depth=32):
    """`pid` est-il `ancestor` ou un de ses descendants ?"""
    for _ in range(depth):
        if pid is None or pid <= 1:
            return False
        if pid == ancestor:
            return True
        pid = ppid(pid)
    return False


def at_prompt(session):
    """Claude Code (session vivante) attend une nouvelle demande, comme `terminal.free_for_input`."""
    if session.state == "idle":
        return True
    return session.state == "waiting" and (session.waiting_for or "").lower().startswith("input")


def terminal_resumes(marks, live, shells, now, history, enabled=True, ppid=_ppid):
    """Relances à faire dans des terminaux shell tenus par CCS (où l'on a lancé `claude` à la
    main) : [(clé du terminal, session_id)]. `shells` : {clé: pid du shell} ; `history` :
    {session_id: [instants des relances]}, mis à jour. Les marqueurs pris sont consommés."""
    out = []
    for s in live:
        e = marks.get(s.session_id)
        if e is None or e.outcome not in limit_events.RESUMABLE or not at_prompt(s):
            continue
        key = next((k for k, shell in shells.items() if descends_from(s.pid, shell, ppid)), None)
        if key is None:
            continue
        if not enabled:
            continue
        recent = [t for t in history.get(s.session_id, ()) if now - t < 3600]
        if len(recent) >= MAX_PER_HOUR or not limit_events.consume(s.session_id, e.ts):
            continue
        history[s.session_id] = recent + [now]
        out.append((key, s.session_id))
    return out
