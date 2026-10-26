"""Éléments partagés par les onglets : styles, état, actions ccs, dialogues."""

import threading
from datetime import datetime, timezone

from gi.repository import Adw, Gdk, GLib, Gtk

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
.legend-session { color: #3584e4; font-weight: bold; }
.legend-weekly { color: #e66100; font-weight: bold; }
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
