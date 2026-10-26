"""Notifications bureau via D-Bus (org.freedesktop.Notifications), sans dépendance."""

import logging

APP_NAME = "Comptes Claude"
ICON = "io.ccs.ClaudeAccounts"

log = logging.getLogger(__name__)


def send(alert):
    """Affiche l'alerte ; renvoie son identifiant, ou None (sans lever) si le
    bureau est injoignable."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        hints = {"urgency": GLib.Variant("y", alert.urgency),
                 "desktop-entry": GLib.Variant("s", ICON)}
        actions = [x for key, label in getattr(alert, "actions", ()) for x in (key, label)]
        r = bus.call_sync(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify",
            GLib.Variant("(susssasa{sv}i)", (APP_NAME, 0, ICON, alert.title, alert.body,
                                             actions, hints, -1)),
            None, Gio.DBusCallFlags.NONE, 5000, None)
        return r.unpack()[0]
    except Exception as e:  # bureau absent, session sans D-Bus…
        log.warning("notification impossible : %s", e)
        return None
