"""Pont avec le bureau : boutons des notifications, surveillance des sessions, et
ouverture de l'application sur une session.

Une boucle GLib tourne dans un fil dédié du service : elle reçoit les clics sur nos
notifications (signaux D-Bus ActionInvoked et ActivationToken) et réagit aux
changements de ~/.claude/sessions (moniteur de fichiers, regroupés sur 1 s).

Afficher une session (`show_session`) : si l'application tourne, son action
« show-session » est appelée par D-Bus (org.freedesktop.Application) ; sinon elle est
lancée avec `gui --session <réf>`, dans sa propre unité systemd (`systemd-run --user
--scope`) pour qu'un redémarrage du service ne ferme pas la fenêtre.

Afficher une tâche (`show_task`) : même mécanisme avec l'action « show-task » (paramètre :
identifiant de la tâche) ; l'application fermée est lancée sur l'onglet Planning
(`gui --page planning`).

Onglets de la fenêtre (`page_name`) : quatre onglets (accueil, sessions, projets, analyse)
et les réglages, une fenêtre à part. `gui --page <nom>` accepte aussi les anciens noms
(comptes, planning, terminaux, historique) : `page_name` les ramène à (onglet, sous-partie).
`gui --page <onglet>` accepte le nom d'un onglet ou son titre en français ; l'application reçoit la demande par ses actions
« show-page » (paramètre : nom de l'onglet) et « new-session » (sans paramètre), y
compris quand elle tourne déjà.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from collections import OrderedDict

from . import notify

log = logging.getLogger("ccs.desktop")
DEBOUNCE_MS = 1000
WATCH_S = 5  # vérification de l'existence du dossier des sessions (un simple stat)
APP_ID = "io.ccs.ClaudeAccounts"
MAX_TRACKED = 200          # notifications suivies (clics, jetons d'activation)
SHOW_ACTION = "show-session"
SHOW_TASK_ACTION = "show-task"
SHOW_PAGE_ACTION = "show-page"
NEW_SESSION_ACTION = "new-session"

# Onglets de la fenêtre (noms du ViewStack, dans l'ordre) et titres acceptés par « gui --page ».
PAGES = ("home", "sessions", "projects", "analysis")
# Nom de page (ancien ou nouveau) -> (onglet, sous-partie). « prefs » n'est pas un onglet : il
# ouvre la fenêtre des réglages.
SUBPAGES = {"accounts": ("home", "accounts"), "planning": ("home", "planning"),
            "terminals": ("sessions", None), "history": ("analysis", "history"),
            "analysis": ("analysis", "analysis"), "prefs": ("prefs", None),
            "projects": ("projects", None), "home": ("home", None), "sessions": ("sessions", None)}
PAGE_CHOICES = ("accueil", "sessions", "projets", "analyse", "comptes", "planning", "historique",
                "terminaux", "reglages")
PAGE_ALIASES = {"accueil": "home", "projets": "projects", "comptes": "accounts",
                "terminaux": "terminals", "historique": "history", "analyse": "analysis",
                "reglages": "prefs",
                "conversations": "sessions"}   # ancien onglet, réuni à l'onglet Sessions


def app_id():
    """Identifiant de l'application ; CCS_APP_ID lance une copie distincte (essais)."""
    return os.environ.get("CCS_APP_ID") or APP_ID


def canonical_page(text):
    """Nom de page désigné par `text` (clé de SUBPAGES), sans tenir compte des accents ni de
    la casse ; None s'il n'existe pas. Anciens et nouveaux noms, français ou anglais."""
    if not isinstance(text, str):
        return None
    text = unicodedata.normalize("NFKD", text.strip()).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    name = PAGE_ALIASES.get(text, text)
    return name if name in SUBPAGES else None


def page_name(text):
    """(onglet, sous-partie) désignés par `text` ; None s'il n'existe pas. Onglet : un des
    PAGES, ou « prefs » (fenêtre des réglages). Sous-partie : None ou ce qu'attend l'onglet
    (« planning », « history »…)."""
    name = canonical_page(text)
    return SUBPAGES[name] if name else None


def _remember(table, key, value):
    table[key] = value
    table.move_to_end(key)
    while len(table) > MAX_TRACKED:
        table.popitem(last=False)


class Bridge:
    def __init__(self, on_action, on_sessions_changed, sessions_path):
        self.on_action = on_action  # (clé, jeton d'activation ou None)
        self.on_sessions_changed = on_sessions_changed
        self.sessions_path = sessions_path
        self.ids = OrderedDict()     # identifiant de nos notifications cliquables -> action « default »
        self.tokens = OrderedDict()  # identifiant -> jeton d'activation (premier plan à l'ouverture)
        self.lock = threading.Lock()
        self.ctx = None
        self.loop = None
        self.watch_s = WATCH_S
        self._pending = None
        self._monitor = None
        self._monitored = None  # (device, inode) du dossier surveillé

    def start(self):
        threading.Thread(target=self._run, name="ccs-desktop", daemon=True).start()

    def send(self, alert):
        nid = notify.send(alert)
        if nid and (alert.actions or alert.default):
            with self.lock:
                _remember(self.ids, nid, alert.default)
        return nid

    def _run(self):
        try:
            from gi.repository import Gio, GLib
            self.ctx = GLib.MainContext.new()
            self.ctx.push_thread_default()
            self.loop = loop = GLib.MainLoop(self.ctx)
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            for signal, handler in (("ActionInvoked", self._on_signal), ("ActivationToken", self._on_token)):
                bus.signal_subscribe(None, "org.freedesktop.Notifications", signal,
                                     "/org/freedesktop/Notifications", None,
                                     Gio.DBusSignalFlags.NONE, handler)
            # Le dossier peut apparaître après le démarrage (première utilisation de
            # Claude Code) ou être supprimé puis recréé : on le revérifie à intervalle
            # régulier et on (ré)installe le moniteur quand il change.
            self._sync_monitor(Gio, catch_up=False)
            src = GLib.timeout_source_new(int(self.watch_s * 1000))
            src.set_callback(lambda *_: self._sync_monitor(Gio) or True)
            src.attach(self.ctx)
            loop.run()
        except Exception:
            log.exception("pont bureau indisponible (notifications sans boutons)")

    def stop(self):
        if self.loop is not None:
            self.loop.quit()

    def _sync_monitor(self, gio, catch_up=True):
        """Aligne le moniteur sur l'état du dossier des sessions ; renvoie True si elle a changé."""
        try:
            st = self.sessions_path.stat()
            ident = (st.st_dev, st.st_ino) if self.sessions_path.is_dir() else None
        except OSError:
            ident = None
        if ident == self._monitored:
            return False
        if self._monitor is not None:
            self._monitor.cancel()  # dossier supprimé ou remplacé : l'ancien moniteur est mort
            self._monitor = None
        self._monitored = ident
        if ident is not None:
            monitor = gio.File.new_for_path(str(self.sessions_path)).monitor_directory(
                gio.FileMonitorFlags.NONE, None)
            monitor.connect("changed", self._on_changed)
            self._monitor = monitor  # garder une référence
        if catch_up:
            self._on_changed()  # l'état des sessions a pu changer entre-temps
        return True

    def _on_token(self, _conn, _sender, _path, _iface, _signal, params):
        """Émis juste avant ActionInvoked : permet à la fenêtre de passer au premier plan."""
        nid, token = params.unpack()
        with self.lock:
            if nid in self.ids:
                _remember(self.tokens, nid, token)

    def _on_signal(self, _conn, _sender, _path, _iface, _signal, params):
        nid, key = params.unpack()
        with self.lock:
            ours = nid in self.ids
            default = self.ids.pop(nid, None)
            token = self.tokens.pop(nid, None)
        if key == "default":
            key = default  # clic sur la notification elle-même
        if ours and key:
            try:
                self.on_action(key, token)
            except Exception:
                log.exception("action de notification en échec")

    def _on_changed(self, *_):
        from gi.repository import GLib
        if self._pending is not None:
            return
        src = GLib.timeout_source_new(DEBOUNCE_MS)
        src.set_callback(self._fire)
        src.attach(self.ctx)
        self._pending = src

    def _fire(self, *_):
        self._pending = None
        try:
            self.on_sessions_changed()
        except Exception:
            log.exception("suivi des sessions en échec")
        return False


# --------------------------------------------------------------------------
# Ouvrir l'application sur une session
# --------------------------------------------------------------------------

def object_path(application_id):
    """Chemin D-Bus d'une GApplication : « io.ccs.App » → « /io/ccs/App »."""
    return "/" + re.sub(r"[^A-Za-z0-9_/]", "_", application_id.replace(".", "/"))


def platform_data(token):
    if not token:
        return {}
    from gi.repository import GLib
    return {"activation-token": GLib.Variant("s", token), "desktop-startup-id": GLib.Variant("s", token)}


def activate_action(application_id, action, ref, token=None):
    """Active `action(ref)` dans l'application si elle tourne ; False si elle ne tourne pas."""
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    owned = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                          "NameHasOwner", GLib.Variant("(s)", (application_id,)),
                          GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
    if not owned:
        return False
    bus.call_sync(application_id, object_path(application_id), "org.freedesktop.Application",
                  "ActivateAction", GLib.Variant("(sava{sv})", (action, [GLib.Variant("s", ref)],
                                                                platform_data(token))),
                  None, Gio.DBusCallFlags.NONE, 5000, None)
    return True


def _launcher():
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if os.path.basename(argv0) == "claude-accounts" and os.path.isfile(argv0):
        return argv0
    return shutil.which("claude-accounts") or "/usr/bin/claude-accounts"


def gui_command(ref, python=None, launcher=None, systemd_run="", args=None):
    """Commande qui ouvre l'application sur la session `ref` (ou avec `args`, par exemple
    ("--page", "planning")). `systemd_run` : chemin de systemd-run (« » : cherché dans le
    PATH ; None : lancement direct)."""
    cmd = [python or sys.executable, launcher or _launcher(), "gui",
           *(args if args is not None else ("--session", ref))]
    if systemd_run == "":
        systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return cmd
    return [systemd_run, "--user", "--scope", "--quiet", "--collect", "--slice=app.slice", "--", *cmd]


def launch_gui(ref, token=None, args=None):
    env = dict(os.environ)
    if token:
        env.update(XDG_ACTIVATION_TOKEN=token, DESKTOP_STARTUP_ID=token)
    subprocess.Popen(gui_command(ref, args=args), env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_session(ref, token=None):
    """Affiche la session `ref` (« <pid>:<identifiant> ») dans l'application ; renvoie
    « action » (application déjà ouverte), « lancement », ou None (référence illisible)."""
    from .attention import parse_session_ref
    if parse_session_ref(ref) == (None, None):
        return None
    try:
        if activate_action(app_id(), SHOW_ACTION, ref, token):
            return "action"
    except Exception as e:  # bus injoignable, application qui ne répond pas…
        log.warning("application injoignable (%s) : lancement", e)
    launch_gui(ref, token)
    return "lancement"


def valid_task_id(task_id):
    """Vrai si `task_id` peut être un identifiant de tâche (jamais une option)."""
    return isinstance(task_id, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", task_id))


def show_task(task_id, token=None):
    """Affiche la tâche `task_id` dans l'onglet Planning ; renvoie « action » (application
    déjà ouverte), « lancement » (application lancée sur la tâche, onglet Planning), ou None
    (identifiant illisible)."""
    if not valid_task_id(task_id):
        return None
    try:
        if activate_action(app_id(), SHOW_TASK_ACTION, task_id, token):
            return "action"
    except Exception as e:  # bus injoignable, application qui ne répond pas…
        log.warning("application injoignable (%s) : lancement", e)
    launch_gui(task_id, token, args=("--page", "planning", "--task", task_id))
    return "lancement"
