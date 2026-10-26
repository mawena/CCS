"""Application « Comptes Claude » (GTK4/libadwaita)."""

import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import daemon  # noqa: E402
from ..settings import load_settings, save_settings  # noqa: E402
from ..store import Store  # noqa: E402
from .accounts import AccountsPage, add_account  # noqa: E402
from .analysis import AnalysisPage  # noqa: E402
from .common import ask_name, install_css, load_state, refresh_data, run_ccs_async  # noqa: E402
from .history import HistoryPage  # noqa: E402
from .planning import PlanningPage  # noqa: E402
from .prefs import PrefsPage  # noqa: E402

APP_ID = "io.ccs.ClaudeAccounts"
STALE_S = 600


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Comptes Claude")
        self.set_default_size(900, 860)
        install_css()
        self.store = Store()
        self._reload_pending = False

        header = Adw.HeaderBar()
        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Ajouter un compte")
        add_btn.connect("clicked", lambda *_: ask_name(
            self, "Ajouter un compte", "Nom du profil (ex. pro, perso)…", "Se connecter",
            lambda n: add_account(self, n)))
        header.pack_start(add_btn)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Actualiser (F5)")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh)
        auto_box = Gtk.Box(spacing=6, tooltip_text="Bascule automatique avant la coupure")
        auto_box.append(Gtk.Label(label="Auto", css_classes=["dim-label"]))
        self.auto = Gtk.Switch(valign=Gtk.Align.CENTER,
                               active=load_settings()["auto_switch"]["enabled"])
        self.auto.connect("notify::active", self.on_auto)
        auto_box.append(self.auto)
        header.pack_end(auto_box)

        self.stack = Adw.ViewStack()
        self.accounts = AccountsPage(self)
        self.planning = PlanningPage(self)
        self.history = HistoryPage(self)
        self.analysis = AnalysisPage(self)
        self.prefs = PrefsPage(self)
        for page, name, title, icon in (
                (self.accounts, "accounts", "Comptes", "system-users-symbolic"),
                (self.planning, "planning", "Planning", "x-office-calendar-symbolic"),
                (self.history, "history", "Historique", "document-open-recent-symbolic"),
                (self.analysis, "analysis", "Analyse", "edit-find-symbolic"),
                (self.prefs, "prefs", "Réglages", "emblem-system-symbolic")):
            self.stack.add_titled_with_icon(page, name, title, icon)
        self.stack.connect("notify::visible-child-name", self.on_page)
        top_switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(top_switcher)
        bottom_switcher = Adw.ViewSwitcherBar(stack=self.stack)

        self.toasts = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_bottom_bar(bottom_switcher)
        self.set_content(view)
        # Fenêtre étroite : onglets en bas, comme les applications GNOME.
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 820sp"))
        narrow.add_setter(top_switcher, "visible", False)
        narrow.add_setter(bottom_switcher, "reveal", True)
        self.add_breakpoint(narrow)
        self.set_size_request(360, 400)

        state_file = Gio.File.new_for_path(str(daemon.state_path()))
        self.monitor = state_file.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", lambda *_: self.schedule_reload())
        GLib.timeout_add_seconds(60, lambda: (self.reload(), True)[1])

        self.reload()
        state = load_state()
        if time.time() - (state.get("updated_at") or 0) > STALE_S and not daemon.running_pid():
            self.refresh()

    # ---- données -----------------------------------------------------------------

    def schedule_reload(self):
        if not self._reload_pending:
            self._reload_pending = True
            GLib.timeout_add(300, self._do_reload)

    def _do_reload(self):
        self._reload_pending = False
        self.reload()
        return False

    def reload(self):
        state = load_state()
        self.accounts.render(state, self.store)
        self.planning.render(state)
        if self.stack.get_visible_child_name() == "history":
            self.history.render(state, self.store)
        else:
            self.history.last = (state, self.store)

    def refresh(self):
        refresh_data(self.reload)

    def on_page(self, *_):
        name = self.stack.get_visible_child_name()
        if name == "history":
            self.history.render(load_state(), self.store)
        elif name == "analysis":
            self.analysis.ensure_loaded()
        elif name == "prefs":
            self.prefs.render()

    # ---- actions -----------------------------------------------------------------

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def switch(self, name):
        run_ccs_async(self, ["use", name],
                      f"Basculé sur « {name} » — les sessions ouvertes suivront à leur prochaine requête")

    def rename(self, old):
        ask_name(self, f"Renommer « {old} »", "Nouveau nom…", "Renommer",
                 lambda new: run_ccs_async(self, ["rename", old, new]), initial=old)

    def delete(self, name):
        d = Adw.AlertDialog(heading=f"Supprimer le profil « {name} » ?",
                            body="Le compte n'est pas déconnecté chez Anthropic, "
                                 "mais il faudra le rajouter pour l'utiliser ici.")
        d.add_response("cancel", "Annuler")
        d.add_response("delete", "Supprimer")
        d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "delete" and run_ccs_async(self, ["rm", name]))
        d.present(self)

    def on_auto(self, sw, _p):
        s = load_settings()
        if s["auto_switch"]["enabled"] != sw.get_active():
            s["auto_switch"]["enabled"] = sw.get_active()
            save_settings(s)
            daemon.request_refresh()
            self.toast("Bascule automatique " + ("activée" if sw.get_active() else "désactivée"))

    def sync_auto_switch(self, enabled):
        if self.auto.get_active() != enabled:
            self.auto.set_active(enabled)


class App(Adw.Application):
    def __init__(self):
        # CCS_APP_ID : lancer une instance distincte (tests) sans réveiller l'application ouverte.
        super().__init__(application_id=os.environ.get("CCS_APP_ID", APP_ID),
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = Window(self)
            for action, handler in (("rename", win.rename), ("delete", win.delete)):
                a = Gio.SimpleAction.new(action, GLib.VariantType.new("s"))
                a.connect("activate", lambda _a, v, h=handler: h(v.get_string()))
                win.add_action(a)
            refresh = Gio.SimpleAction.new("refresh", None)
            refresh.connect("activate", lambda *_: win.refresh())
            win.add_action(refresh)
            self.set_accels_for_action("win.refresh", ["F5", "<Control>r"])
        win.present()


def run():
    return App().run([sys.argv[0]])
