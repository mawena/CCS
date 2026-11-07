"""Éléments partagés par les onglets : styles, état, actions ccs, dialogues."""

import threading
from datetime import datetime, timezone
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .. import core, daemon

CSS = b"""
.profile-card { padding: 18px; }
.best-card { padding: 14px 18px; }
.badge { font-size: 0.75em; font-weight: bold; padding: 2px 8px; border-radius: 99px; }
.badge.active { background: @accent_bg_color; color: @accent_fg_color; }
.badge.plan { background: alpha(currentColor, 0.1); }
progressbar trough, progressbar progress { min-height: 8px; border-radius: 99px; }
progressbar.ok progress { background-color: @success_color; }
progressbar.warn progress { background-color: @warning_color; }
progressbar.crit progress { background-color: @error_color; }
.pct { font-feature-settings: "tnum"; font-weight: bold; }
.ccs-terminal { padding: 6px 10px; }
.ccs-highlight { box-shadow: inset 0 0 0 2px @accent_color; }
.ccs-dot { min-width: 8px; min-height: 8px; border-radius: 99px; }
.ccs-dot.ouverte { background: @success_color; }
.ccs-dot.attention { background: @accent_color; }
.ccs-projects { background: none; }
.ccs-projects row { padding: 2px 0; }
.ccs-count { font-feature-settings: "tnum"; }
.ccs-days > button { padding-left: 8px; padding-right: 8px; }
"""


def install_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS, -1)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def load_state():
    return core.load_json(daemon.state_path())


def parse_ts(iso):
    return core.parse_dt(iso) if iso else None


def now_utc():
    return datetime.now(timezone.utc)


def clear(box):
    while (child := box.get_first_child()) is not None:
        box.remove(child)


def bar_for(pct):
    bar = Gtk.ProgressBar(fraction=min(max(pct, 0), 100) / 100)
    bar.add_css_class("crit" if pct >= 90 else "warn" if pct >= 70 else "ok")
    return bar


def caption(text, error=False):
    return Gtk.Label(label=text, xalign=0, wrap=True,
                     css_classes=["caption", "error" if error else "dim-label"])


def cap(text):
    return text[:1].upper() + text[1:]


def error_text(e):
    if isinstance(e, FileNotFoundError) and e.filename:
        return f"Introuvable : {e.filename}"
    if e.strerror:
        return f"Échec : {e.strerror}" + (f" ({e.filename})" if e.filename else "")
    return cap(str(e))


def short_path(path):
    """Chemin avec ~ pour le dossier personnel."""
    home = str(core.paths().home)
    if path == home:
        return "~"
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def existing_parent(path):
    """Plus proche dossier existant en remontant depuis `path`, ou None."""
    p = Path(path) if path else None
    while p is not None and not p.is_dir():
        p = p.parent if p.parent != p else None
    return str(p) if p else None


def string_factory(ellipsize, short=None):
    """Fabrique de libellés pour un Gtk.DropDown de chaînes. `short` : {libellé: libellé
    court} affiché à la place (bouton d'une barre étroite, liste gardant les libellés complets)."""
    f = Gtk.SignalListItemFactory()
    mode = Pango.EllipsizeMode.END if ellipsize else Pango.EllipsizeMode.NONE
    short = short or {}

    def bind(_f, item):
        text = item.get_item().get_string()
        item.get_child().set_label(short.get(text, text))
    f.connect("setup", lambda _f, item: item.set_child(Gtk.Label(xalign=0, ellipsize=mode)))
    f.connect("bind", bind)
    return f


def menu_button(entries, tooltip="Autres actions"):
    """Bouton « ⋮ » : `entries` = [(libellé, « groupe.action », GLib.Variant)]."""
    menu = Gio.Menu()
    for label, action, target in entries:
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value(action, target)
        menu.append_item(item)
    return Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, css_classes=["flat"],
                          valign=Gtk.Align.CENTER, tooltip_text=tooltip)


def in_thread(work, done):
    """Exécute work() hors de l'interface puis done(résultat) dans l'interface."""
    def run():
        result = work()
        GLib.idle_add(lambda: (done(result), False)[1])
    threading.Thread(target=run, daemon=True).start()


def refresh_data(done=None):
    """Demande une collecte (daemon, sinon collecte directe) puis rappelle done()."""
    def work():
        if not daemon.request_refresh():
            daemon.collect_once()
    in_thread(work, lambda _r: done and done())


def run_ccs_async(window, args, success_text=None):
    def finish(r):
        lines = (r.stdout + r.stderr).strip().splitlines()
        text = lines[0] if lines else ("OK" if r.returncode == 0 else "échec")
        text = text.replace("ccs: ", "").lstrip("✔ ")
        if r.returncode == 0 and success_text:
            text = success_text
        window.toast(text)
        refresh_data(window.reload)
    in_thread(lambda: core.run_ccs(args), finish)


def valid_name(text, initial=""):
    return bool(text) and text != initial and all(c.isalnum() or c in "._-" for c in text)


def ask_name(window, heading, placeholder, action_label, callback, initial=""):
    entry = Gtk.Entry(placeholder_text=placeholder, text=initial, activates_default=True)
    d = Adw.AlertDialog(heading=heading, extra_child=entry)
    d.add_response("cancel", "Annuler")
    d.add_response("ok", action_label)
    d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("ok")
    d.set_response_enabled("ok", False)
    entry.connect("changed", lambda e: d.set_response_enabled("ok", valid_name(e.get_text(), initial)))

    def on_response(_d, r):
        name = entry.get_text().strip()
        if r == "ok" and valid_name(name, initial):
            callback(name)
    d.connect("response", on_response)
    d.present(window)
    entry.grab_focus()


def ask_title(window, heading, initial, callback, max_length=0):
    """Demande un titre (prérempli avec `initial`) ; refuse un titre vide ou inchangé."""
    entry = Gtk.Entry(text=initial or "", activates_default=True, max_length=max_length,
                      placeholder_text="Nouveau titre…")
    d = Adw.AlertDialog(heading=heading, extra_child=entry,
                        body="Comme /rename dans Claude Code : le titre est enregistré dans la "
                             "conversation et s'affiche partout, VS Code compris.")
    d.add_response("cancel", "Annuler")
    d.add_response("ok", "Renommer")
    d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    d.set_default_response("ok")
    d.set_close_response("cancel")

    def valid(text):
        text = " ".join(text.split())
        return bool(text) and text != " ".join((initial or "").split())
    d.set_response_enabled("ok", False)
    entry.connect("changed", lambda e: d.set_response_enabled("ok", valid(e.get_text())))

    def on_response(_d, r):
        if r == "ok" and valid(entry.get_text()):
            callback(" ".join(entry.get_text().split()))
    d.connect("response", on_response)
    d.present(window)
    entry.grab_focus()
