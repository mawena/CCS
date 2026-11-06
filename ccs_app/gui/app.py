"""Application « Comptes Claude » (GTK4/libadwaita)."""

import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import conversations, daemon, sessions, terminal  # noqa: E402
from ..settings import load_settings, save_settings  # noqa: E402
from ..store import Store  # noqa: E402
from .accounts import AccountsPage, add_account  # noqa: E402
from .analysis import AnalysisPage  # noqa: E402
from .common import ask_name, ask_title, in_thread, install_css, load_state, refresh_data, run_ccs_async  # noqa: E402
from .conversations_page import ConversationsPage, cap, error_text  # noqa: E402
from .history import HistoryPage  # noqa: E402
from .planning import PlanningPage  # noqa: E402
from .sessions_page import SessionsPage  # noqa: E402
from .prefs import PrefsPage  # noqa: E402
from .terminals import TerminalsPage  # noqa: E402

APP_ID = "io.ccs.ClaudeAccounts"
STALE_S = 600
# Sous cette largeur, les onglets passent dans la barre du bas : 7 onglets de même largeur
# tiennent en 1350 px, 8 (avec « Terminaux ») en 1540 px.
NARROW_SP = {False: 1350, True: 1540}


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Comptes Claude")
        self.set_default_size(1180, 860)
        install_css()
        self.store = Store()
        self._reload_pending = False
        self.closing = False
        self.back_to = None

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
        self.sessions = SessionsPage(self)
        self.conversations = ConversationsPage(self)
        self.terminals = TerminalsPage(self)
        self.history = HistoryPage(self)
        self.analysis = AnalysisPage(self)
        self.prefs = PrefsPage(self)
        for page, name, title, icon in (
                (self.accounts, "accounts", "Comptes", "system-users-symbolic"),
                (self.planning, "planning", "Planning", "x-office-calendar-symbolic"),
                (self.sessions, "sessions", "Sessions", "utilities-terminal-symbolic"),
                (self.conversations, "conversations", "Conversations", "chat-message-new-symbolic"),
                (self.terminals, "terminals", "Terminaux", "tab-new-symbolic"),
                (self.history, "history", "Historique", "document-open-recent-symbolic"),
                (self.analysis, "analysis", "Analyse", "edit-find-symbolic"),
                (self.prefs, "prefs", "Réglages", "emblem-system-symbolic")):
            self.stack.add_titled_with_icon(page, name, title, icon)
        self.terminals_page = self.stack.get_page(self.terminals)
        self.terminals_page.set_visible(False)  # visible tant qu'un onglet est ouvert
        self.stack.connect("notify::visible-child-name", self.on_page)
        top_switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(top_switcher)
        bottom_switcher = Adw.ViewSwitcherBar(stack=self.stack)

        self.toasts = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_bottom_bar(bottom_switcher)
        self.set_content(view)
        # Fenêtre étroite : onglets en bas, comme les applications GNOME (en dessous de
        # NARROW_SP, « Conversations » serait tronqué en haut).
        self.narrow = Adw.Breakpoint.new(self.narrow_condition())
        self.narrow.add_setter(top_switcher, "visible", False)
        self.narrow.add_setter(bottom_switcher, "reveal", True)
        self.add_breakpoint(self.narrow)
        self.set_size_request(360, 400)
        self.connect("close-request", self.on_close_request)

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
        self.closing = False
        self.back_to = None
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
        if name == "terminals":
            self.terminals.focus_selected()
        else:
            self.back_to = name
            self.terminals.update_badge()
        self.sessions.visible_page = name == "sessions"
        self.conversations.visible_page = name == "conversations"
        if name == "sessions":
            self.sessions.load()
        elif name == "conversations":
            self.conversations.load()
        if name == "history":
            self.history.render(load_state(), self.store)
        elif name == "analysis":
            self.analysis.ensure_loaded()
        elif name == "prefs":
            self.prefs.render()

    # ---- terminal intégré ----------------------------------------------------------

    def narrow_condition(self):
        width = NARROW_SP[self.terminals_page.get_visible()]
        return Adw.BreakpointCondition.parse(f"max-width: {width}sp")

    def show_terminals(self):
        if not self.terminals_page.get_visible():
            self.terminals_page.set_visible(True)
            self.narrow.set_condition(self.narrow_condition())
        if self.stack.get_visible_child_name() != "terminals":
            self.stack.set_visible_child_name("terminals")

    def hide_terminals(self):
        shown = self.stack.get_visible_child_name() == "terminals"
        back = self.back_to or "sessions"  # cacher la page visible fait afficher la première
        self.terminals_page.set_visible(False)
        self.narrow.set_condition(self.narrow_condition())
        if shown:
            self.stack.set_visible_child_name(back)

    def open_claude(self, cwd, resume=None, title=None, external=False):
        """Claude Code dans `cwd` (reprise de la conversation `resume`) : dans un onglet de
        l'application si le terminal intégré est là, sinon dans un terminal externe.
        Renvoie « integre » ou « externe »."""
        if terminal.choose(self.terminals.available, external) == "externe":
            sessions.open_terminal(cwd, resume)
            return "externe"
        tab = self.terminals.find(session_id=resume) if resume else None
        if tab is not None:
            self.terminals.present(tab)  # déjà dans un onglet : on y va
        else:
            self.terminals.open_claude(cwd, resume, title)
        return "integre"

    def open_shell(self, cwd, external=False):
        if terminal.choose(self.terminals.available, external) == "externe":
            sessions.open_terminal(cwd, start_claude=False)
            return "externe"
        self.terminals.open_shell(cwd)
        return "integre"

    def terminals_changed(self):
        """Un onglet s'est ouvert, arrêté, fermé ou a appris sa conversation : les boutons
        « Afficher » des onglets Sessions et Conversations suivent."""
        if self.sessions.visible_page:
            self.sessions.rerender()
        if self.conversations.visible_page:
            self.conversations.rerender()

    def on_close_request(self, *_):
        if self.closing:
            return False
        question = self.terminals.close_question()
        if question is None:
            self.terminals.hang_up_all()
            return False
        d = Adw.AlertDialog(heading=question[0], body=question[1])
        d.add_response("cancel", "Annuler")
        d.add_response("close", "Fermer")
        d.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")

        def on_response(_d, r):
            if r == "close":
                self.closing = True
                self.terminals.hang_up_all()
                self.close()
        d.connect("response", on_response)
        d.present(self)
        return True

    # ---- renommage -----------------------------------------------------------------

    def rename_conversation(self, session_id, cwd=None, path=None, current=""):
        """Demande un nouveau titre puis l'enregistre dans le journal de la conversation."""
        def chosen(title):
            def work():
                try:
                    return conversations.rename(session_id, title, cwd=cwd, path=path)
                except (ValueError, OSError) as e:
                    return e
            in_thread(work, lambda result: self.renamed(session_id, result))
        ask_title(self, "Renommer la conversation", current, chosen, conversations.RENAME_MAX)

    def renamed(self, session_id, result):
        if isinstance(result, ValueError):
            self.toast(cap(str(result)))
            return
        if isinstance(result, OSError):
            self.toast(error_text(result))
            return
        tab = self.terminals.find(session_id=session_id)
        if tab is not None:
            tab.set_title(result)
        self.toast(f"Conversation renommée « {result} »")
        if self.conversations.convs is not None:
            self.conversations.load()
        if self.sessions.visible_page:
            self.sessions.load()

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
