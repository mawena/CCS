"""Pont avec le bureau : boutons des notifications, surveillance des sessions, et
ouverture de l'application sur une session.

Une boucle GLib tourne dans un fil dédié du service : elle reçoit les clics sur nos
notifications (signaux D-Bus ActionInvoked et ActivationToken) et réagit aux
changements de ~/.claude/sessions (moniteur de fichiers, regroupés sur 1 s).

Afficher une session (`show_session`) : si l'application tourne, son action
« show-session » est appelée par D-Bus (org.freedesktop.Application) ; sinon elle est
lancée avec `gui --session <réf>`, dans sa propre unité systemd (`systemd-run --user
--scope`) pour qu'un redémarrage du service ne ferme pas la fenêtre.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import OrderedDict

from . import notify

log = logging.getLogger("ccs.desktop")
DEBOUNCE_MS = 1000
APP_ID = "io.ccs.ClaudeAccounts"
MAX_TRACKED = 200          # notifications suivies (clics, jetons d'activation)
SHOW_ACTION = "show-session"


def app_id():
    """Identifiant de l'application ; CCS_APP_ID lance une copie distincte (essais)."""
    return os.environ.get("CCS_APP_ID") or APP_ID


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
        self._pending = None

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
            loop = GLib.MainLoop(self.ctx)
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            for signal, handler in (("ActionInvoked", self._on_signal), ("ActivationToken", self._on_token)):
                bus.signal_subscribe(None, "org.freedesktop.Notifications", signal,
                                     "/org/freedesktop/Notifications", None,
                                     Gio.DBusSignalFlags.NONE, handler)
            monitor = None
            if self.sessions_path.is_dir():
                monitor = Gio.File.new_for_path(str(self.sessions_path)).monitor_directory(
                    Gio.FileMonitorFlags.NONE, None)
                monitor.connect("changed", self._on_changed)
            self._monitor = monitor  # garder une référence
            loop.run()
        except Exception:
            log.exception("pont bureau indisponible (notifications sans boutons)")

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


def gui_command(ref, python=None, launcher=None, systemd_run=""):
    """Commande qui ouvre l'application sur la session `ref`. `systemd_run` : chemin de
    systemd-run (« » : cherché dans le PATH ; None : lancement direct)."""
    cmd = [python or sys.executable, launcher or _launcher(), "gui", "--session", ref]
    if systemd_run == "":
        systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return cmd
    return [systemd_run, "--user", "--scope", "--quiet", "--collect", "--slice=app.slice", "--", *cmd]


def launch_gui(ref, token=None):
    env = dict(os.environ)
    if token:
        env.update(XDG_ACTIVATION_TOKEN=token, DESKTOP_STARTUP_ID=token)
    subprocess.Popen(gui_command(ref), env=env, start_new_session=True, stdin=subprocess.DEVNULL,
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
