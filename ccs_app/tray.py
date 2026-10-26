"""Indicateur de la barre du haut (GTK 3 + AyatanaAppIndicator, processus séparé)."""

import subprocess
import sys

from . import core, daemon
from .settings import load_settings, save_settings

REFRESH_S = 30
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


GAUGE_COLORS = ((90, "#e01b24"), (70, "#f6a034"), (0, "#33d17a"))


def gauge_svg(percent):
    """Icône anneau-jauge : remplie selon le pourcentage, vert / orange / rouge."""
    ring = ('<circle cx="16" cy="16" r="11" fill="none" stroke="#9a9996" stroke-opacity="0.45" '
            'stroke-width="5"/>')
    arc = ""
    if percent is not None:
        p = max(0.0, min(100.0, float(percent)))
        color = next(c for t, c in GAUGE_COLORS if p >= t)
        arc = (f'<circle cx="16" cy="16" r="11" fill="none" stroke="{color}" stroke-width="5" '
               f'pathLength="100" stroke-dasharray="{p:.1f} 100" stroke-linecap="butt" '
               'transform="rotate(-90 16 16)"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'
            f'{ring}{arc}<circle cx="16" cy="16" r="3.5" fill="#deddda"/></svg>')


def _gauge_value(state):
    acc = _active_account(state) if state else None
    limits = (acc or {}).get("limits") or []
    if not limits:
        return None
    worst = max(l["percent"] for l in limits)
    session = next((l["percent"] for l in limits if l["kind"] == "session"), worst)
    return worst if worst >= 90 else session


def icon_name_for(state):
    v = _gauge_value(state)
    return "ccs-gauge-none" if v is None else f"ccs-gauge-{int(min(v, 100) // 10 * 10)}"


def _hm(iso):
    dt = core.parse_dt(iso)
    return f"{dt.astimezone():%H:%M}" if dt else ""


def _age(ts, now):
    minutes = int((now.timestamp() - ts) // 60)
    if minutes < 1:
        return "à l'instant"
    if minutes < 60:
        return f"il y a {minutes} min"
    return f"il y a {minutes // 60} h {minutes % 60:02d}"


def menu_lines(state, now):
    """Lignes du menu : [(texte, action)] ; action = ("use", profil) ou None ; "-" = séparateur."""
    accounts = (state or {}).get("accounts") or []
    if not accounts:
        return [("Pas encore de données — lance le service", None)]
    active = state.get("active")
    out = [(f"Compte actif : {active or 'non enregistré'} · données "
            f"{_age(state.get('updated_at') or now.timestamp(), now)}", None), ("-", None)]
    o = state.get("orchestrator") or {}
    reserve = set(o.get("reserve") or [])
    for a in accounts:
        lims = {l["kind"]: l for l in a.get("limits") or []}
        s, w = lims.get("session"), lims.get("weekly_all")
        parts = []
        if s:
            parts.append(f"session {s['percent']:.0f} %" + (f" → {_hm(s['resets_at'])}" if s.get("resets_at") else ""))
        if w:
            parts.append(f"semaine {w['percent']:.0f} %")
        if a["name"] in reserve:
            parts.append("réserve")
        text = f"{'●' if a.get('active') else '○'} {a['name']} — {' · '.join(parts) or 'pas de données'}"
        if a.get("error"):
            text += " ⚠"
        out.append((text, None if a.get("active") else ("use", a["name"])))
    out.append(("-", None))
    best = state.get("best")
    if best:
        action = ("use", best["name"]) if best["name"] != active else None
        out.append((f"Meilleur compte : {best['name']} — {best['reason']}", action))
    fc = ((_active_account(state) or {}).get("forecast") or {})
    if fc.get("verdict") == "limit" and fc.get("eta"):
        out.append((f"⏱ Limite estimée vers {_hm(fc['eta'])}", None))
    if o.get("enabled"):
        ends = sorted((core.parse_dt(w["end"]), w["name"]) for w in o.get("plan") or []
                      if core.parse_dt(w["end"]) and core.parse_dt(w["end"]) > now)
        if ends:
            out.append((f"Prochaine recharge : {ends[0][0].astimezone():%H:%M} ({ends[0][1]})", None))
    out.append((f"Capacité restante : {core.fr(state.get('capacity') or 0)} session(s)", None))
    return out


def session_lines(found):
    from . import sessions
    return [(f"{s.project} — {sessions.state_label(s)}", s) for s in found]


def icon_dir():
    d = core.paths().home / ".cache" / "ccs" / "icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_icon(name, state):
    path = icon_dir() / f"{name}.svg"
    if not path.exists():
        path.write_text(gauge_svg(_gauge_value(state)))
    return path


def run():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from datetime import datetime, timezone

    from gi.repository import AyatanaAppIndicator3 as AppIndicator
    from gi.repository import GLib, Gtk

    if not watcher_available():
        print("L'indicateur restera invisible tant que l'extension GNOME AppIndicator est "
              f"désactivée : gnome-extensions enable {EXTENSION}", file=sys.stderr)
    ind = AppIndicator.Indicator.new("ccs-tray", "ccs-gauge-none",
                                     AppIndicator.IndicatorCategory.APPLICATION_STATUS)
    ind.set_icon_theme_path(str(icon_dir()))
    ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    ind.set_title("Comptes Claude")

    def launch_gui(*_):
        subprocess.Popen([sys.executable, sys.argv[0], "gui"], start_new_session=True)

    def use(_item, name):
        r = core.run_ccs(["use", name])
        if r.returncode == 0:
            daemon.request_refresh()
        GLib.timeout_add_seconds(2, lambda: (rebuild(), False)[1])

    def toggle(item, section):
        s = load_settings()
        s[section]["enabled"] = item.get_active()
        save_settings(s)
        daemon.request_refresh()

    def refresh(*_):
        if not daemon.request_refresh():
            subprocess.Popen([sys.executable, sys.argv[0], "collect"], start_new_session=True)

    def rebuild():
        state = core.load_json(daemon.state_path())
        name = icon_name_for(state)
        ensure_icon(name, state)
        ind.set_icon_full(name, "Usage du compte Claude actif")
        ind.set_label(label_for(state), "⚠ 100 %")
        menu = Gtk.Menu()
        for text, action in menu_lines(state, datetime.now(timezone.utc)):
            if text == "-":
                menu.append(Gtk.SeparatorMenuItem())
                continue
            it = Gtk.MenuItem(label=text)
            if action and action[0] == "use" and daemon.state_fresh(state):
                it.connect("activate", use, action[1])
            else:
                it.set_sensitive(False)
            menu.append(it)
        from . import sessions
        lines = session_lines(sessions.list_sessions())
        if lines:
            menu.append(Gtk.SeparatorMenuItem())
            root = Gtk.MenuItem(label=f"Sessions Claude Code ({len(lines)})")
            sub = Gtk.Menu()
            for text, sess in lines:
                it = Gtk.MenuItem(label=text)
                actions = Gtk.Menu()
                for label, cb in (("Ouvrir un terminal ici",
                                   lambda *_, c=sess.cwd: sessions.open_terminal(c, start_claude=False)),
                                  ("Ouvrir le dossier", lambda *_, c=sess.cwd: sessions.open_folder(c))):
                    a = Gtk.MenuItem(label=label)
                    a.connect("activate", cb)
                    actions.append(a)
                it.set_submenu(actions)
                sub.append(it)
            root.set_submenu(sub)
            menu.append(root)
        menu.append(Gtk.SeparatorMenuItem())
        s = load_settings()
        for label, section in (("Bascule automatique", "auto_switch"), ("Orchestrateur", "orchestrator")):
            check = Gtk.CheckMenuItem(label=label)
            check.set_active(s[section]["enabled"])
            check.connect("toggled", toggle, section)
            menu.append(check)
        for label, cb in (("Actualiser", refresh), ("Ouvrir Comptes Claude", launch_gui)):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", cb)
            menu.append(it)
        menu.show_all()
        ind.set_menu(menu)
        return True

    rebuild()
    GLib.timeout_add_seconds(REFRESH_S, rebuild)
    Gtk.main()
    return 0
