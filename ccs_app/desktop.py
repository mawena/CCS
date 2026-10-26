"""Pont avec le bureau : boutons des notifications et surveillance des sessions.

Une boucle GLib tourne dans un fil dédié du service : elle reçoit les clics
sur les boutons de nos notifications (signal D-Bus ActionInvoked) et réagit
aux changements de ~/.claude/sessions (moniteur de fichiers, regroupés sur 1 s).
"""

import logging
import threading

from . import notify

log = logging.getLogger("ccs.desktop")
DEBOUNCE_MS = 1000


class Bridge:
    def __init__(self, on_action, on_sessions_changed, sessions_path):
        self.on_action = on_action
        self.on_sessions_changed = on_sessions_changed
        self.sessions_path = sessions_path
        self.ids = set()            # identifiants de nos notifications à boutons
        self.lock = threading.Lock()
        self.ctx = None
        self._pending = None

    def start(self):
        threading.Thread(target=self._run, name="ccs-desktop", daemon=True).start()

    def send(self, alert):
        nid = notify.send(alert)
        if nid and alert.actions:
            with self.lock:
                self.ids.add(nid)
        return nid

    def _run(self):
        try:
            from gi.repository import Gio, GLib
            self.ctx = GLib.MainContext.new()
            self.ctx.push_thread_default()
            loop = GLib.MainLoop(self.ctx)
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.signal_subscribe(None, "org.freedesktop.Notifications", "ActionInvoked",
                                 "/org/freedesktop/Notifications", None,
                                 Gio.DBusSignalFlags.NONE, self._on_signal)
            monitor = None
            if self.sessions_path.is_dir():
                monitor = Gio.File.new_for_path(str(self.sessions_path)).monitor_directory(
                    Gio.FileMonitorFlags.NONE, None)
                monitor.connect("changed", self._on_changed)
            self._monitor = monitor  # garder une référence
            loop.run()
        except Exception:
            log.exception("pont bureau indisponible (notifications sans boutons)")

    def _on_signal(self, _conn, _sender, _path, _iface, _signal, params):
        nid, key = params.unpack()
        with self.lock:
            ours = nid in self.ids
            self.ids.discard(nid)
        if ours:
            try:
                self.on_action(key)
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
