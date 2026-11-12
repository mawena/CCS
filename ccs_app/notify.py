"""Notifications bureau via D-Bus (org.freedesktop.Notifications), sans dépendance."""

import logging

APP_NAME = "CCS"
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
    bureau est injoignable ou si l'alerte est retenue (ne pas déranger : voir `quiet`).
    `transient` : bulle seulement, pas gardée dans la liste des notifications (résultat
    d'un raccourci clavier, jamais retenue : action directe de l'utilisateur)."""
    if not transient and _held(alert):
        return None
    return _dbus_send(alert, transient)


def _held(alert):
    """Alerte retenue pendant un silence (comptée pour le résumé) ? Sans jamais lever :
    en cas de doute on notifie."""
    try:
        from . import quiet
        if quiet.should_hold(alert) is None:
            return False
        quiet.hold(alert)
        return True
    except Exception as e:
        log.warning("filtre ne pas déranger en échec : %s", e)
        return False


def _dbus_send(alert, transient=False):
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
