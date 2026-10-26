"""Indicateur de la barre du haut (GTK 3 + AyatanaAppIndicator, processus séparé)."""

import subprocess
import sys

from . import core, daemon
from .settings import load_settings, save_settings

REFRESH_S = 30
ICON = "io.ccs.ClaudeAccounts"
FALLBACK_ICON = "system-users-symbolic"
WATCHER = "org.kde.StatusNotifierWatcher"
EXTENSION = "ubuntu-appindicators@ubuntu.com"


def watcher_available():
    """Vrai si le bureau affiche les indicateurs (extension AppIndicator active)."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        r = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                          "NameHasOwner", GLib.Variant("(s)", (WATCHER,)),
                          None, Gio.DBusCallFlags.NONE, 2000, None)
        return bool(r.unpack()[0])
    except Exception:
        return False


def _active_account(state):
    active = state.get("active")
    return next((a for a in state.get("accounts") or [] if a.get("name") == active), None)


def label_for(state):
    acc = _active_account(state) if state else None
    limits = (acc or {}).get("limits") or []
    if not limits:
        return "—"
    worst = max(l["percent"] for l in limits)
    if worst >= 95:
        return f"⚠ {worst:.0f} %"
    session = next((l["percent"] for l in limits if l["kind"] == "session"), worst)
    glyph = "○" if session < 25 else "◔" if session < 50 else "◑" if session < 75 else "◕"
    return f"{glyph} {session:.0f} %"


def _summary(acc):
    parts = []
    for l in acc.get("limits") or []:
        short = "session" if l["kind"] == "session" else "semaine" if l["kind"] == "weekly_all" else l["label"]
        parts.append(f"{short} {l['percent']:.0f} %")
    return " · ".join(parts) or (acc.get("error") or "pas de données")


def run():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
    from gi.repository import GLib, Gtk

    if not watcher_available():
        print("L'indicateur restera invisible tant que l'extension GNOME AppIndicator est "
              f"désactivée : gnome-extensions enable {EXTENSION}", file=sys.stderr)
    theme = Gtk.IconTheme.get_default()
    icon = ICON if theme.has_icon(ICON) else FALLBACK_ICON
    ind = AppIndicator.Indicator.new("ccs-tray", icon,
                                     AppIndicator.IndicatorCategory.APPLICATION_STATUS)
    ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    ind.set_title("Comptes Claude")

    def launch_gui(*_):
        subprocess.Popen([sys.executable, sys.argv[0], "gui"], start_new_session=True)

    def use(_item, name):
        r = core.run_ccs(["use", name])
        if r.returncode == 0:
            daemon.request_refresh()
        GLib.timeout_add_seconds(2, lambda: (rebuild(), False)[1])

    def toggle_auto(item):
        s = load_settings()
        s["auto_switch"]["enabled"] = item.get_active()
        save_settings(s)
        daemon.request_refresh()

    def refresh(*_):
        if not daemon.request_refresh():
            subprocess.Popen([sys.executable, sys.argv[0], "collect"], start_new_session=True)

    def item(label, callback=None, sensitive=True):
        it = Gtk.MenuItem(label=label)
        it.set_sensitive(sensitive)
        if callback:
            it.connect("activate", callback)
        return it

    def rebuild():
        state = core.load_json(daemon.state_path())
        ind.set_label(label_for(state), "⚠ 100 %")
        menu = Gtk.Menu()
        accounts = state.get("accounts") or []
        if not accounts:
            menu.append(item("Aucun profil enregistré", sensitive=False))
        for acc in accounts:
            if acc.get("active"):
                menu.append(item(f"● {acc['name']} — {_summary(acc)}", sensitive=False))
            else:
                menu.append(item(f"   {acc['name']} — {_summary(acc)}", lambda i, n=acc["name"]: use(i, n)))
        best = state.get("best")
        active = _active_account(state)
        menu.append(Gtk.SeparatorMenuItem())
        if best:
            if best["name"] != state.get("active") and daemon.state_fresh(state):
                menu.append(item(f"Basculer sur le meilleur : {best['name']}",
                                 lambda i, n=best["name"]: use(i, n)))
            menu.append(item(best["reason"], sensitive=False))
        fc = (active or {}).get("forecast") or {}
        if fc.get("verdict") == "limit" and fc.get("eta"):
            eta = core.parse_dt(fc["eta"])
            menu.append(item(f"Limite estimée vers {eta.astimezone():%H:%M}", sensitive=False))
        menu.append(Gtk.SeparatorMenuItem())
        auto = Gtk.CheckMenuItem(label="Bascule automatique")
        auto.set_active(load_settings()["auto_switch"]["enabled"])
        auto.connect("toggled", toggle_auto)
        menu.append(auto)
        menu.append(item("Actualiser", refresh))
        menu.append(item("Ouvrir Comptes Claude", launch_gui))
        menu.show_all()
        ind.set_menu(menu)
        return True

    rebuild()
    GLib.timeout_add_seconds(REFRESH_S, rebuild)
    Gtk.main()
    return 0
