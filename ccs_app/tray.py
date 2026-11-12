"""Indicateur de la barre du haut (GTK 3 + AyatanaAppIndicator, processus séparé)."""

import os
import subprocess
import sys
from dataclasses import dataclass

from . import core, daemon, pause, quiet
from .forecast import fmt_when
from .settings import load_settings, save_settings
from .updates import PROJECT_URL

REFRESH_S = 30
# Nouvelle version installée : le code est relu toutes les 10 s, et l'indicateur
# se relance une fois l'empreinte stable (dpkg a fini de remplacer les fichiers).
CODE_CHECK_S = 10
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


def label_for(state, paused=False, waiting=0, quiet=False):
    """Libellé de l'indicateur ; « · 💬 n » quand n sessions attendent une réponse,
    « 🔕 » pendant un silence (ne pas déranger)."""
    text = _label(state)
    if quiet:
        text = f"🔕 {text}"
    if paused:
        text = f"⏸ {text}"
    return f"{text} · 💬 {waiting}" if waiting else text


def _label(state):
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
    for a in accounts:
        wf = a.get("weekly_forecast") or {}
        eta = core.parse_dt(wf.get("eta")) if wf.get("verdict") == "limit" else None
        if eta is not None and eta > now:
            out.append((f"⚠ {a['name']} : semaine épuisée {fmt_when(eta, now)} au rythme actuel",
                        None))
    if o.get("enabled"):
        ends = sorted((core.parse_dt(w["end"]), w["name"]) for w in o.get("plan") or []
                      if core.parse_dt(w["end"]) and core.parse_dt(w["end"]) > now)
        if ends:
            out.append((f"Prochaine recharge : {ends[0][0].astimezone():%H:%M} ({ends[0][1]})", None))
    out.append((f"Capacité restante : {core.fr(state.get('capacity') or 0)} session(s)", None))
    update = state.get("update") or {}
    url = update.get("url")
    if update.get("version") and isinstance(url, str) and url.startswith(PROJECT_URL):
        out.append((f"⬆ CCS {update['version']} disponible — voir la version", ("open", url)))
    return out


def restart_due(start_stamp, previous, current):
    """Relance quand le code a changé depuis le démarrage et n'a plus bougé depuis le
    contrôle précédent (mise à jour terminée)."""
    return current != start_stamp and current == previous


def restart_command():
    """Même interpréteur, mêmes arguments (y compris « -m ccs_app.cli »)."""
    return [sys.executable, *sys.orig_argv[1:]]


def pause_menu(st, now, hours=None):
    """(ligne d'état ou None, [(libellé, choix)]) : reprendre, ou durées de pause."""
    if st is not None:
        return (f"⏸ En pause {pause.label(st, now)} — bascule et orchestrateur suspendus",
                [("Reprendre maintenant", "reprendre")])
    return None, [(text, choice) for choice, text in pause.choices(now, hours)]


def quiet_menu(st, now, settings=None):
    """(libellé du sous-menu, [(libellé, choix)], « Reprendre » possible) pour « Ne pas
    déranger ». Le libellé porte l'état ; une plage de silence des réglages ne se lève pas
    d'un clic (seul un silence temporaire se reprend)."""
    if st is None:
        label = "Ne pas déranger"
    elif st.source == "plage":
        label = f"Ne pas déranger — plage de silence {quiet.label(st, now)}"
    else:
        label = f"Ne pas déranger — silence {quiet.label(st, now)}"
    items = [(text, choice) for choice, text in quiet.choices(now, settings)]
    return label, items, st is not None and st.source == "temporaire"


def install_entry(state):
    """« Installer CCS x.y.z… » quand une version plus récente est annoncée, sinon None."""
    from . import attention
    found = attention.update_banner((state or {}).get("update"))
    if found is None:
        return None
    version = found[0].split()[1]
    return f"Installer CCS {version}…" if version.replace(".", "").isdigit() else None


def session_lines(found):
    from . import sessions
    return [(f"{s.project} — {sessions.state_label(s)}", s) for s in found]


ALL_SESSIONS_ARGS = ("gui", "--page", "sessions")  # entrée « Toutes les sessions… »
SESSION_ORDER = {"waiting": 0, "busy": 1, "idle": 2}  # celles qui attendent ta réponse d'abord


@dataclass
class SessionEntry:
    label: str
    ref: str    # « <pid>:<identifiant> », pour `gui --session`
    cwd: str


def sort_sessions(found):
    """En attente d'abord, puis au travail, puis au repos ; dans un état, la plus ancienne d'abord."""
    return sorted(found, key=lambda s: (SESSION_ORDER.get(s.state, 3), s.state_since))


def elapsed_label(seconds):
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return f"depuis {int(seconds // 60)} min"
    if seconds < 86400:
        return f"depuis {int(seconds // 3600)} h {int(seconds % 3600 // 60):02d}"
    return f"depuis {int(seconds // 86400)} j"


def session_entries(found, title_of, now):
    """Entrées du sous-menu, triées : « titre — état, depuis … ». `title_of(session)` donne le
    titre de la conversation ; sans titre (ou en cas d'erreur), le nom du projet."""
    from . import sessions
    from .attention import session_ref
    out = []
    for s in sort_sessions(found):
        try:
            title = title_of(s)
        except Exception:
            title = None
        out.append(SessionEntry(
            f"{title or s.project} — {sessions.state_label(s)}, {elapsed_label(now - s.state_since)}",
            session_ref(s), s.cwd))
    return out


def sessions_root_label(found):
    n = sum(1 for s in found if s.state == "waiting")
    if n:
        return f"Sessions ({n} {'attend' if n == 1 else 'attendent'} ta réponse)"
    return f"Sessions ({len(found)})" if found else "Sessions"


def sessions_signature(found):
    """Ce qui change la liste affichée (hors horloge) : ne relire les titres que si besoin."""
    return tuple((s.pid, s.session_id, s.state, s.waiting_for, s.cwd) for s in sort_sessions(found))


def open_session(ref):
    """Ouvre l'application sur la session (détaché, comme la notification cliquable)."""
    try:
        from . import desktop
        return desktop.show_session(ref) is not None
    except Exception:
        return False


TASKS_ARGS = ("gui", "--page", "planning")  # entrée « Tâches » : onglet Planning


def tasks_label(all_tasks):
    """Libellé de l'entrée « Tâches » (None : aucune tâche en file ni en cours, pas d'entrée).
    En file = en attente ou à reprendre (limite atteinte)."""
    running = sum(1 for t in all_tasks if t.state == "running")
    queued = sum(1 for t in all_tasks if t.state in ("queued", "waiting"))
    parts = []
    if running:
        parts.append(f"{running} en cours")
    if queued:
        parts.append(f"{queued} en file")
    return f"Tâches ({', '.join(parts)})" if parts else None


def tasks_now():
    """Tâches connues (liste vide si le fichier est illisible : l'indicateur ne s'arrête jamais)."""
    try:
        from . import tasks
        return tasks.all()
    except Exception:
        return []


# Fin du menu : l'application sur la bonne page (noms français de `gui --page`).
APP_ENTRIES = (
    ("Journal des bascules", ("gui", "--page", "historique")),
    ("Bilan de la semaine", ("gui", "--page", "analyse")),
    ("Ouvrir CCS", ("gui",)),
)


def gui_argv(args):
    """Commande qui lance `claude-accounts <args>` avec le même interpréteur."""
    return [sys.executable, sys.argv[0], *args]


def switch_to(name, run=None):
    """Bascule demandée depuis le menu : origine « icone » notée pour le journal des
    bascules, puis `ccs use` ; True si la bascule a eu lieu."""
    from . import switch_log
    switch_log.note_origin(name, "icone")
    r = (run or core.run_ccs)(["use", name])
    if r.returncode != 0:
        switch_log.clear_origin()  # aucune bascule : la note ne doit rien attribuer plus tard
        return False
    daemon.request_refresh()
    return True


ICON_CACHE_VERSION = "v2"


def icon_dir():
    d = core.paths().home / ".cache" / "ccs" / f"icons-{ICON_CACHE_VERSION}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def gauge_for_name(name):
    """Icône dessinée d'après son nom (dizaine), pour que le cache corresponde au nom."""
    value = name.rsplit("-", 1)[-1]
    return gauge_svg(None if value == "none" else float(value))


def ensure_icon(name):
    path = icon_dir() / f"{name}.svg"
    if not path.exists():
        path.write_text(gauge_for_name(name))
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
    ind.set_title("CCS")

    def launch_gui(_item, args):
        subprocess.Popen(gui_argv(args), start_new_session=True)

    def use(_item, name):
        switch_to(name)
        GLib.timeout_add_seconds(2, lambda: (rebuild(), False)[1])

    def toggle(item, section):
        s = load_settings()
        s[section]["enabled"] = item.get_active()
        save_settings(s)
        daemon.request_refresh()

    def refresh(*_):
        if not daemon.request_refresh():
            subprocess.Popen([sys.executable, sys.argv[0], "collect"], start_new_session=True)

    def set_pause(_item, choice):
        pause.apply(choice)
        daemon.request_refresh()
        GLib.idle_add(lambda: (rebuild(), False)[1])

    def set_quiet(_item, choice):
        quiet.apply(choice)
        daemon.request_refresh()
        GLib.idle_add(lambda: (rebuild(), False)[1])

    def open_uri(_item, url):
        subprocess.Popen(["gio", "open", url], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    stamp = daemon.code_stamp()
    seen = [stamp]

    def watch_code():
        """Nouvelle version installée : l'indicateur se relance avec le nouveau code."""
        current = daemon.code_stamp()
        if not restart_due(stamp, seen[0], current):
            seen[0] = current
            return True
        ind.set_status(AppIndicator.IndicatorStatus.PASSIVE)
        if not current:  # plus aucun fichier : paquet désinstallé
            Gtk.main_quit()
            return False
        print("nouvelle version installée : relance de l'indicateur", file=sys.stderr, flush=True)
        try:
            os.execv(sys.executable, restart_command())
        except OSError:
            Gtk.main_quit()
        return False

    titles = {"sig": None, "map": {}}

    def cached_title(s):
        from . import sessions
        key = (s.pid, s.session_id)
        if key not in titles["map"]:
            titles["map"][key] = sessions.conversation_title(s.cwd, s.session_id)
        return titles["map"][key]

    def rebuild():
        state = core.load_json(daemon.state_path())
        now = datetime.now(timezone.utc)
        s = load_settings()
        # Lu directement (et non dans state.json) : le menu suit aussitôt un clic.
        paused = pause.pause_state(now)
        silence = quiet.quiet_state(now, s)
        name = icon_name_for(state)
        ensure_icon(name)
        ind.set_icon_full(name, "Usage du compte Claude actif")
        from . import sessions
        try:
            found = sessions.list_sessions()
        except Exception:
            found = []  # une fiche inattendue ne doit pas arrêter l'indicateur
        waiting = sum(1 for s in found if s.state == "waiting")
        ind.set_label(label_for(state, paused is not None, waiting, silence is not None),
                     "⏸ 🔕 ⚠ 100 % · 💬 9")
        sig = sessions_signature(found)
        if sig != titles["sig"]:  # titres relus seulement si la liste des sessions a changé
            titles["sig"] = sig
            titles["map"] = {}
        menu = Gtk.Menu()
        pause_line, pause_items = pause_menu(paused, now, s["orchestrator"]["active_hours"])
        if pause_line:
            it = Gtk.MenuItem(label=pause_line, use_underline=False)
            it.set_sensitive(False)
            menu.append(it)
        for text, action in menu_lines(state, now):
            if text == "-":
                menu.append(Gtk.SeparatorMenuItem())
                continue
            it = Gtk.MenuItem(label=text, use_underline=False)
            if action and action[0] == "use" and daemon.state_fresh(state):
                it.connect("activate", use, action[1])
            elif action and action[0] == "open":
                it.connect("activate", open_uri, action[1])
            else:
                it.set_sensitive(False)
            menu.append(it)
        menu.append(Gtk.SeparatorMenuItem())
        root = Gtk.MenuItem(label=sessions_root_label(found), use_underline=False)
        sub = Gtk.Menu()
        entries = session_entries(found, cached_title, now.timestamp())
        for e in entries:
            it = Gtk.MenuItem(label=e.label, use_underline=False)
            it.connect("activate", lambda _i, r=e.ref: open_session(r))
            sub.append(it)
        if entries:
            more = Gtk.MenuItem(label="Terminal ou dossier d'une session")
            more_sub = Gtk.Menu()
            for e in entries:
                it = Gtk.MenuItem(label=e.label, use_underline=False)
                actions = Gtk.Menu()
                for label, cb in (("Ouvrir un terminal ici",
                                   lambda *_, c=e.cwd: sessions.open_terminal(c, start_claude=False)),
                                  ("Ouvrir le dossier", lambda *_, c=e.cwd: sessions.open_folder(c))):
                    a = Gtk.MenuItem(label=label)
                    a.connect("activate", cb)
                    actions.append(a)
                it.set_submenu(actions)
                more_sub.append(it)
            more.set_submenu(more_sub)
            sub.append(Gtk.SeparatorMenuItem())
            sub.append(more)
        else:
            it = Gtk.MenuItem(label="Aucune session ouverte")
            it.set_sensitive(False)
            sub.append(it)
        sub.append(Gtk.SeparatorMenuItem())
        it = Gtk.MenuItem(label="Toutes les sessions…")
        it.connect("activate", launch_gui, ALL_SESSIONS_ARGS)
        sub.append(it)
        root.set_submenu(sub)
        menu.append(root)
        text = tasks_label(tasks_now())
        if text:
            it = Gtk.MenuItem(label=text, use_underline=False)
            it.connect("activate", launch_gui, TASKS_ARGS)
            menu.append(it)
        menu.append(Gtk.SeparatorMenuItem())
        for label, section in (("Bascule automatique", "auto_switch"), ("Orchestrateur", "orchestrator")):
            check = Gtk.CheckMenuItem(label=label + (" (en pause)" if paused else ""))
            check.set_active(s[section]["enabled"])
            check.connect("toggled", toggle, section)
            menu.append(check)
        if paused:
            for text, choice in pause_items:
                it = Gtk.MenuItem(label=f"▶ {text}")
                it.connect("activate", set_pause, choice)
                menu.append(it)
        else:
            root = Gtk.MenuItem(label="Mettre en pause")
            sub = Gtk.Menu()
            for text, choice in pause_items:
                it = Gtk.MenuItem(label=text)
                it.connect("activate", set_pause, choice)
                sub.append(it)
            root.set_submenu(sub)
            menu.append(root)
        # « Ne pas déranger » : dans le menu principal, à côté de la pause (même famille de
        # réglages), et non dans le sous-menu Sessions.
        label, choices, can_resume = quiet_menu(silence, now, s)
        root = Gtk.MenuItem(label=label, use_underline=False)
        sub = Gtk.Menu()
        for text, choice in choices:
            it = Gtk.MenuItem(label=text)
            it.connect("activate", set_quiet, choice)
            sub.append(it)
        sub.append(Gtk.SeparatorMenuItem())
        it = Gtk.MenuItem(label="Reprendre les notifications")
        it.set_sensitive(can_resume)
        it.connect("activate", set_quiet, "reprendre")
        sub.append(it)
        root.set_submenu(sub)
        menu.append(root)
        install = install_entry(state)
        if install:
            it = Gtk.MenuItem(label=install, use_underline=False)
            # L'application s'ouvre ; son bandeau propose « Installer ».
            it.connect("activate", launch_gui, ("gui",))
            menu.append(it)
        it = Gtk.MenuItem(label="Actualiser")
        it.connect("activate", refresh)
        menu.append(it)
        menu.append(Gtk.SeparatorMenuItem())
        for label, args in APP_ENTRIES:
            it = Gtk.MenuItem(label=label)
            it.connect("activate", launch_gui, args)
            menu.append(it)
        menu.show_all()
        ind.set_menu(menu)
        return True

    rebuild()
    GLib.timeout_add_seconds(REFRESH_S, rebuild)
    GLib.timeout_add_seconds(CODE_CHECK_S, watch_code)
    Gtk.main()
    return 0
