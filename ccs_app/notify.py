"""Notifications bureau via D-Bus (org.freedesktop.Notifications), sans dépendance."""

import logging

APP_NAME = "Comptes Claude"
ICON = "io.ccs.ClaudeAccounts"

log = logging.getLogger(__name__)


def actions_for(alert):
    """Liste plate [clé, libellé, …] du champ `actions` de Notify. L'action « default »
    est celle d'un clic sur la notification elle-même (GNOME n'en fait pas un bouton) ;
    le service la traduit en `alert.default`."""
    out = ["default", "Afficher"] if getattr(alert, "default", None) else []
    return out + [x for key, label in getattr(alert, "actions", ()) for x in (key, label)]


def send(alert, transient=False):
    """Affiche l'alerte ; renvoie son identifiant, ou None (sans lever) si le
    bureau est injoignable. `transient` : bulle seulement, pas gardée dans la liste
    des notifications (résultat d'un raccourci clavier)."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        hints = {"urgency": GLib.Variant("y", alert.urgency),
                 "desktop-entry": GLib.Variant("s", ICON)}
        if transient:
            hints["transient"] = GLib.Variant("b", True)
        r = bus.call_sync(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify",
            GLib.Variant("(susssasa{sv}i)", (APP_NAME, 0, ICON, alert.title, alert.body,
                                             actions_for(alert), hints, -1)),
            None, Gio.DBusCallFlags.NONE, 5000, None)
        return r.unpack()[0]
    except Exception as e:  # bureau absent, session sans D-Bus…
        log.warning("notification impossible : %s", e)
        return None


def message(title, body="", urgency=1):
    """Notification simple et passagère : résultat d'une commande lancée par un raccourci
    clavier (`ccs next --notifier`…). Identifiant, ou None si le bureau est injoignable."""
    from .alerts import Alert
    return send(Alert("message", title, body, urgency), transient=True)
