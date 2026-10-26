"""Service de collecte : relevés, prévisions, bascule automatique, alertes, état partagé."""

import fcntl
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from . import alerts, autoswitch, core, notify, orchestrator
from .forecast import (AccountState, best_account, capacity, effective_percent,
                       session_forecast, weekly_pace)
from .settings import load_settings
from .store import RETENTION_S, Store

log = logging.getLogger("ccs.daemon")

FAST_PERCENT = 85
FAST_ETA = timedelta(minutes=15)
HISTORY = timedelta(hours=5)
EVENTS_LOOKBACK = timedelta(hours=8)
ALERTS_LOOKBACK = timedelta(days=8)
RATE_LIMIT_PAUSE = timedelta(minutes=5)
SESSION_NOTIFY_GAP_S = 120


def _iso(dt):
    return dt.isoformat() if dt else None


def states_from_state(state):
    """AccountState reconstruits depuis state.json (hook, CLI)."""
    out = []
    for a in (state or {}).get("accounts") or []:
        limits = [core.Limit(l["kind"], l.get("label", l["kind"]), float(l["percent"]),
                             core.parse_dt(l.get("resets_at"))) for l in a.get("limits") or []]
        out.append(AccountState(a["name"], bool(a.get("active")), limits, a.get("fetched_at"),
                                a.get("error")))
    return out


def state_path():
    return core.paths().store / "state.json"


def pid_path():
    return core.paths().store / "daemon.pid"


class Daemon:
    def __init__(self, store, notifier=notify.send, starter=None):
        self.store = store
        self.notifier = notifier
        self.starter = starter or self._start_window
        self.states = {}            # dernier AccountState connu par profil
        self.previous_sessions = {}  # limite session au tick précédent
        self.last_full = None
        self.last_prune = None
        self.cooldown = {}          # profil -> instant avant lequel ne pas réinterroger (429)
        self.prev_sessions = None   # pid -> Session (dernier état vu)
        self.sessions_lock = threading.Lock()
        self.session_notified = {}  # pid -> instant de la dernière notification
        self.hooks = []             # fonctions (daemon, states, settings, now) appelées à chaque tick

    # ---- collecte ---------------------------------------------------------

    def collect(self, now, only=None):
        profiles = [p for p in core.list_profiles() if (only is None or p.name in only)
                    and self.cooldown.get(p.name, now) <= now]
        results = {}

        def fetch(name):
            results[name] = core.fetch_usage(name)
        threads = [threading.Thread(target=fetch, args=(p.name,)) for p in profiles]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        out = []
        for p in profiles:
            r = results[p.name]
            limits = core.parse_limits(r.usage)
            if r.error is None and limits:
                self.store.add_samples(r.fetched_at, p.name, limits)
            elif r.error:
                if r.error.startswith("HTTP 429"):
                    self.cooldown[p.name] = now + RATE_LIMIT_PAUSE
                last = self.store.last_event("error", p.name)
                if not last or last.detail.get("message") != r.error:
                    self.store.add_event(now.timestamp(), "error", p.name,
                                         {"op": "fetch", "message": r.error})
            out.append(AccountState(p.name, p.active, limits, r.fetched_at, r.error))
        return out

    def _start_window(self, name, now):
        from . import warmup
        t = threading.Thread(target=warmup.run, daemon=True,
                             args=(name, now.astimezone().strftime("%H:%M"), self.store, now),
                             kwargs={"mode": "orchestrateur"})
        t.start()
        self.workers = [w for w in getattr(self, "workers", []) if w.is_alive()] + [t]

    def join_workers(self, timeout=60):
        """À l'arrêt : laisse les démarrages en cours finir (jeton relu, dossier supprimé)."""
        for w in getattr(self, "workers", []):
            w.join(timeout)

    # ---- actions de notification et sessions ---------------------------------

    def handle_action(self, key, now, settings=None):
        """Bouton cliqué dans une notification : « use:<profil> », revérifié au moment du clic."""
        kind, _, name = key.partition(":")
        if kind != "use":
            return False
        names = {p.name for p in core.list_profiles()}
        if name not in names or core.active_profile_name() == name:
            return False
        settings = settings or load_settings()
        target = self.states.get(name)
        problem = None
        if target is None or target.fetched_at is None \
                or now.timestamp() - target.fetched_at > autoswitch.STALE_S:
            problem = "données trop anciennes"
        elif target.blocking_error:
            problem = target.blocking_error
        elif effective_percent(target.session, now) >= 95 \
                or target.other_max_effective(now) >= settings["auto_switch"]["target_max_weekly"]:
            problem = "presque épuisé"
        if problem:
            self.notifier(alerts.Alert(f"refus:{name}:{now.timestamp():.0f}",
                                       f"{name} n'est plus un bon choix", f"Bascule annulée : {problem}.", 1))
            return False
        r = core.run_ccs(["use", name])
        if r.returncode != 0:
            self.store.add_event(now.timestamp(), "error", name,
                                 {"op": "notification", "message": (r.stderr or r.stdout).strip()})
            return False
        self.store.add_event(now.timestamp(), "switch", name, {"mode": "manual", "via": "notification"})
        return True

    def on_sessions(self, settings, now):
        """Compare l'état des sessions Claude Code et prévient quand l'une finit ou attend."""
        with self.sessions_lock:
            self._on_sessions(settings, now)

    def _on_sessions(self, settings, now):
        from . import sessions
        cur = sessions.list_sessions()
        prev, self.prev_sessions = self.prev_sessions, {s.pid: s for s in cur}
        if prev is None or not (settings["alerts"]["enabled"] and settings["alerts"]["sessions"]):
            return
        ts = now.timestamp()
        for s, kind in sessions.transitions(prev, cur, ts):
            if ts - self.session_notified.get(s.pid, 0) < SESSION_NOTIFY_GAP_S:
                continue
            self.session_notified[s.pid] = ts
            if kind == "waiting":
                title = f"{s.project} attend ta réponse"
                body = f"Session {s.name}" + (f" — {s.waiting_for}" if s.waiting_for else "")
            else:
                title, body = f"{s.project} a terminé", f"Session {s.name} — prête pour la suite."
            self.notifier(alerts.Alert(f"session:{s.pid}:{ts:.0f}", title, body, 1))

    def detect_manual_switch(self, now):
        active = core.active_profile_name()
        if not active:
            return
        last = self.store.last_event("switch")
        if last is None:
            # Premier relevé : point de départ, pas une bascule de l'utilisateur.
            self.store.add_event(now.timestamp(), "switch", active, {"mode": "initial"})
        elif last.profile != active:
            self.store.add_event(now.timestamp(), "switch", active, {"mode": "manual"})

    # ---- tick ---------------------------------------------------------------

    def tick(self, settings, now):
        poll = settings["poll"]
        self.detect_manual_switch(now)
        profiles = {p.name: p for p in core.list_profiles()}
        active = next((n for n, p in profiles.items() if p.active), None)

        full = (self.last_full is None
                or (now - self.last_full).total_seconds() >= poll["normal_s"] - 1
                or not set(profiles) <= set(self.states))
        fresh = self.collect(now, None if full else [active] if active else [])
        if full:
            self.last_full = now
        for s in fresh:
            self.states[s.name] = s
        states = []
        for name, p in profiles.items():
            if name in self.states:
                s = self.states[name]
                s.active = p.active
                states.append(s)

        forecasts = {s.name: self._forecast(s, now) for s in states}
        paces = {s.name: weekly_pace(s.weekly, now) for s in states}
        fc = forecasts.get(active)
        act = next((s for s in states if s.name == active), None)
        fast = act is not None and (
            act.max_effective(now) >= FAST_PERCENT
            or (fc and fc.verdict == "limit" and fc.eta and fc.eta - now < FAST_ETA))
        delay = poll["fast_s"] if fast else poll["normal_s"]

        ocfg = settings["orchestrator"]
        orch_on = ocfg["enabled"]
        reserve = orchestrator.reserve_set(states, paces, ocfg) if orch_on else set()
        events = self.store.events((now - EVENTS_LOOKBACK).timestamp())
        decision = autoswitch.decide(states, active, fc, settings, now, events, delay, reserve)
        switched = False
        if decision.action == "switch":
            switched = autoswitch.execute(decision, self.store, now)
        elif orch_on and settings["auto_switch"]["enabled"]:
            early = orchestrator.expiring_decision(states, active, now, ocfg, events, reserve)
            if early is not None:
                decision = early
                switched = autoswitch.execute(early, self.store, now, mode="anticipee")
        if switched:
            delay = poll["fast_s"]
        best = best_account(states, now, reserve=reserve)

        if orch_on:
            for name in orchestrator.starts_due(states, now, ocfg, self.store):
                local = now.astimezone()
                self.store.add_event(now.timestamp(), "warmup", name, {
                    "mode": "orchestrateur", "date": local.date().isoformat(),
                    "time": f"{local:%H:%M}", "ok": None, "message": "en cours"})
                self.starter(name, now)
            wake = orchestrator.next_wake(states, now, ocfg)
            if wake is not None:
                delay = max(30.0, min(delay, (wake - now).total_seconds()))

        sent = {e.detail.get("key") for e in
                self.store.events((now - ALERTS_LOOKBACK).timestamp(), type="alert")}
        pending = alerts.pending_alerts(states, active, fc, paces, best, settings, now,
                                        sent, self.previous_sessions)
        da = alerts.decision_alert(decision, now)
        if decision.action == "switch" and not switched:
            da = None  # échec journalisé (event error), pas d'annonce trompeuse
        if da and da.key not in sent and settings["alerts"]["enabled"]:
            pending.append(da)
        for a in pending:
            self.notifier(a)
            self.store.add_event(now.timestamp(), "alert", None, {"key": a.key, "title": a.title})

        try:
            self.on_sessions(settings, now)
        except Exception:
            log.exception("suivi des sessions en échec")

        for hook in self.hooks:
            try:
                hook(self, states, settings, now)
            except Exception:  # un module optionnel ne doit pas arrêter la collecte
                log.exception("erreur dans un module du daemon")

        self.previous_sessions = {s.name: s.session for s in states}
        self.write_state(states, profiles, forecasts, paces, best, decision, settings, now,
                         reserve)
        if self.last_prune is None or now - self.last_prune > timedelta(days=1):
            self.store.prune(now.timestamp() - RETENTION_S)
            self.last_prune = now
        return delay

    def _forecast(self, s, now):
        samples = [(ts, pct) for ts, pct, _ in
                   self.store.samples(s.name, "session", (now - HISTORY).timestamp())]
        return session_forecast(samples, s.session, now)

    # ---- état partagé -------------------------------------------------------

    def write_state(self, states, profiles, forecasts, paces, best, decision, settings, now,
                    reserve=frozenset()):
        last_auto = self.store.last_event("switch")
        accounts = []
        for s in states:
            p = profiles[s.name]
            fc, pace = forecasts.get(s.name), paces.get(s.name)
            accounts.append({
                "name": s.name, "email": p.email, "org": p.org, "plan": p.plan,
                "active": s.active, "error": s.error, "fetched_at": s.fetched_at,
                "limits": [{"kind": l.kind, "label": l.label, "percent": l.percent,
                            "resets_at": _iso(l.resets_at)} for l in s.limits],
                "forecast": fc and {"verdict": fc.verdict, "eta": _iso(fc.eta),
                                    "rate_per_min": fc.rate_per_min,
                                    "minutes_before_reset": fc.minutes_before_reset},
                "pace": pace and {"ideal": pace.ideal, "margin": pace.margin,
                                  "per_day_budget": pace.per_day_budget,
                                  "days_left": pace.days_left},
            })
        core.atomic_write_json(state_path(), {
            "updated_at": now.timestamp(),
            "active": next((s.name for s in states if s.active), None),
            "capacity": capacity(states, now),
            "best": best and {"name": best.name, "reason": best.reason},
            "auto_switch": {
                "enabled": settings["auto_switch"]["enabled"],
                "decision": {"action": decision.action, "target": decision.target,
                             "reason": decision.reason},
                "last": last_auto and {"ts": last_auto.ts, "profile": last_auto.profile,
                                       "mode": last_auto.detail.get("mode")},
            },
            "accounts": accounts,
            "orchestrator": self._orchestrator_state(states, settings, now, reserve),
        })

    def _orchestrator_state(self, states, settings, now, reserve):
        ocfg = settings["orchestrator"]
        bounds = orchestrator.period_bounds(now, ocfg["active_hours"])
        wake = orchestrator.next_wake(states, now, ocfg) if ocfg["enabled"] else None
        return {
            "enabled": ocfg["enabled"],
            "active_now": bounds is not None,
            "period": bounds and [_iso(bounds[0]), _iso(bounds[1])],
            "reserve": sorted(reserve),
            "next_wake": _iso(wake),
            # Désactivé : seulement les fenêtres en cours, rien de « prévu ».
            "plan": [{"name": w.name, "start": _iso(w.start), "end": _iso(w.end), "kind": w.kind}
                     for w in orchestrator.plan(states, now, ocfg)
                     if ocfg["enabled"] or w.kind == "current"],
        }


# --------------------------------------------------------------------------
# Processus
# --------------------------------------------------------------------------

STALE_STATE_S = 600
# Code de sortie quand une nouvelle version est installée : systemd
# (Restart=on-failure) relance aussitôt le service avec le nouveau code.
EXIT_UPDATED = 75
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def code_stamp(path=PACKAGE_DIR):
    """Empreinte (mtime la plus récente) des fichiers Python du paquet."""
    latest = 0.0
    for root, _dirs, files in os.walk(path):
        for f in files:
            if f.endswith(".py"):
                try:
                    latest = max(latest, os.stat(os.path.join(root, f)).st_mtime)
                except OSError:
                    pass
    return latest


def state_fresh(state, now=None):
    now = time.time() if now is None else now
    updated = (state or {}).get("updated_at")
    return bool(updated) and now - updated <= STALE_STATE_S


def _is_our_daemon(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read()
    except OSError:
        return False
    return b"daemon" in cmd and (b"claude-accounts" in cmd or b"ccs_app" in cmd)


def clean_warmup_leftovers():
    """Supprime les dossiers temporaires de warm-up laissés par un arrêt brutal."""
    import glob
    import shutil
    import tempfile
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "ccs-warmup-*")):
        try:
            if os.stat(d).st_uid == os.getuid():
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def running_pid():
    """Pid du daemon, seulement s'il tient le verrou du fichier pid (pas de pid recyclé)."""
    try:
        with open(pid_path(), "r+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                pid = int(f.read().strip() or 0)
                return pid if pid and _is_our_daemon(pid) else None
            fcntl.flock(f, fcntl.LOCK_UN)
            return None
    except (OSError, ValueError):
        return None


def request_refresh():
    """Demande une collecte immédiate au daemon ; False s'il ne tourne pas."""
    pid = running_pid()
    if not pid:
        return False
    os.kill(pid, signal.SIGUSR1)
    return True


def run():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")
    wake = threading.Event()
    stop = threading.Event()
    # Gestionnaires posés avant d'annoncer le pid : un SIGUSR1 précoce ne tue pas le daemon.
    signal.signal(signal.SIGUSR1, lambda *_: wake.set())
    signal.signal(signal.SIGTERM, lambda *_: (stop.set(), wake.set()))
    signal.signal(signal.SIGINT, lambda *_: (stop.set(), wake.set()))
    core.paths().store.mkdir(mode=0o700, parents=True, exist_ok=True)
    pid_file = open(pid_path(), "a+")
    try:
        fcntl.flock(pid_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("daemon déjà lancé (pid %s)", running_pid())
        return 1
    pid_file.seek(0)
    pid_file.truncate()
    pid_file.write(str(os.getpid()))
    pid_file.flush()
    clean_warmup_leftovers()
    d = Daemon(Store())
    from . import desktop, sessions

    def now_utc():
        return datetime.now(timezone.utc)

    def on_action(key):
        if d.handle_action(key, now_utc()):
            wake.set()
    bridge = desktop.Bridge(on_action, lambda: d.on_sessions(load_settings(), now_utc()),
                            sessions.sessions_dir())
    bridge.start()
    d.notifier = bridge.send
    try:
        from . import warmup
        d.hooks.append(warmup.hook)
    except ImportError:
        pass
    log.info("daemon démarré")
    stamp = code_stamp()
    exit_code = 0
    try:
        while not stop.is_set():
            if code_stamp() != stamp:
                log.info("nouvelle version installée : redémarrage du service")
                exit_code = EXIT_UPDATED
                break
            try:
                delay = d.tick(load_settings(), datetime.now(timezone.utc))
            except Exception:
                log.exception("tick en échec")
                delay = 60
            wake.wait(delay)
            wake.clear()
    finally:
        d.join_workers()
        pid_file.seek(0)
        pid_file.truncate()
        pid_file.close()
    log.info("daemon arrêté")
    return exit_code


def observe_once():
    """Relevé et état partagé seulement : aucune bascule, alerte ni démarrage."""
    d = Daemon(Store(), notifier=lambda _a: None, starter=lambda *_: None)
    s = load_settings()
    s["auto_switch"]["enabled"] = False
    s["orchestrator"]["enabled"] = False
    s["alerts"]["enabled"] = False
    d.prev_sessions = {}
    d.tick(s, datetime.now(timezone.utc))
    return 0


def collect_once():
    d = Daemon(Store())
    d.tick(load_settings(), datetime.now(timezone.utc))
    return 0

