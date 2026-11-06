"""Application « Comptes Claude » (GTK4/libadwaita)."""

import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import attention, conversations, daemon, desktop, doctor, launch_options, pause, sessions, terminal  # noqa: E402,E501
from ..settings import load_settings, save_settings  # noqa: E402
from ..store import Store  # noqa: E402
from .accounts import AccountsPage, add_account, set_pause  # noqa: E402
from .analysis import AnalysisPage  # noqa: E402
from .common import (ask_name, ask_title, in_thread, install_css, load_state, now_utc,  # noqa: E402
                     refresh_data, run_ccs_async)
from .conversations_page import ConversationsPage, cap, error_text  # noqa: E402
from .doctor_dialog import show_doctor  # noqa: E402
from .history import HistoryPage  # noqa: E402
from .new_session_dialog import ask_new_session  # noqa: E402
from .planning import PlanningPage  # noqa: E402
from .preview_dialog import show_preview  # noqa: E402
from .sessions_page import SessionsPage  # noqa: E402
from .prefs import PrefsPage  # noqa: E402
from .terminals import TerminalsPage  # noqa: E402

APP_ID = desktop.APP_ID
STALE_S = 600
DOCTOR_DELAY_S = 4   # bilan de santé du démarrage : après le premier affichage
# Sous cette largeur, les onglets passent dans la barre du bas : 7 onglets de même largeur
# tiennent en 1350 px, 8 (avec « Terminaux ») en 1540 px.
NARROW_SP = {False: 1350, True: 1540}
PAUSE_SP = 100       # « Auto ⏸ jusqu'à 14:00 » à la place de « Auto » pendant une pause


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Comptes Claude")
        self.set_default_size(1180, 860)
        install_css()
        self.store = Store()
        self._reload_pending = False
        self.closing = False
        self.back_to = None

        self.header = header = Adw.HeaderBar()
        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Ajouter un compte")
        add_btn.connect("clicked", lambda *_: ask_name(
            self, "Ajouter un compte", "Nom du profil (ex. pro, perso)…", "Se connecter",
            lambda n: add_account(self, n)))
        header.pack_start(add_btn)
        menu = Gio.Menu()
        menu.append("Nouvelle session…", "win.new-session")
        menu.append("Bilan de santé…", "win.doctor")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text="Menu principal"))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Actualiser (F5)")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh)
        self.auto_box = Gtk.Box(spacing=6, tooltip_text="Bascule automatique avant la coupure")
        # Pendant une pause, « Auto » devient « Auto ⏸ jusqu'à 14:00 » ; un clic propose de reprendre.
        self.auto_label = Gtk.Label(label="Auto", css_classes=["dim-label"])
        self.pause_btn = Gtk.MenuButton(css_classes=["flat"], valign=Gtk.Align.CENTER, visible=False,
                                        popover=self.resume_popover())
        self.pause_label = Gtk.Label(css_classes=["warning"])
        self.pause_btn.set_child(self.pause_label)
        self.auto_box.append(self.auto_label)
        self.auto_box.append(self.pause_btn)
        self.auto = Gtk.Switch(valign=Gtk.Align.CENTER,
                               active=load_settings()["auto_switch"]["enabled"])
        self.auto.connect("notify::active", self.on_auto)
        self.auto_box.append(self.auto)
        header.pack_end(self.auto_box)
        for name, handler in (("new-session", lambda *_: self.new_session()),
                              ("doctor", lambda *_: self.show_doctor())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

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
        # Bandeaux discrets : nouvelle version publiée, problème trouvé par le bilan de santé.
        self.update_url = None
        self.update_seen = None    # version dont le bandeau a été ouvert (pas réaffiché)
        self.update_banner = Adw.Banner(button_label="Voir")
        self.update_banner.connect("button-clicked", self.on_update_banner)
        view.add_top_bar(self.update_banner)
        self.doctor_banner = Adw.Banner(button_label="Voir le bilan")
        self.doctor_banner.connect("button-clicked", lambda *_: self.show_doctor())
        view.add_top_bar(self.doctor_banner)
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
        self.sessions.count_waiting()
        self.terminals.connect("tab-state-changed", lambda *_: self.sessions.count_waiting())
        GLib.timeout_add_seconds(DOCTOR_DELAY_S, self.check_health)

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
        self.show_pause()
        self.show_update(state)

    # ---- en-tête et bandeaux ---------------------------------------------------------

    def resume_popover(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)
        self.pause_text = Gtk.Label(wrap=True, max_width_chars=36, xalign=0)
        box.append(self.pause_text)
        resume = Gtk.Button(label="Reprendre maintenant", css_classes=["suggested-action"])
        box.append(resume)
        popover = Gtk.Popover(child=box)

        def clicked(*_):
            popover.popdown()
            set_pause(self, "reprendre")
        resume.connect("clicked", clicked)
        return popover

    def show_pause(self):
        """État de pause dans l'en-tête, d'après pause.json (que state.json recopie au relevé
        suivant du service : le fichier est plus frais)."""
        now = now_utc()
        st = pause.pause_state(now)
        shown = attention.pause_header(st.as_dict(now) if st else None, now)
        self.auto_label.set_visible(shown is None)
        if self.pause_btn.get_visible() != (shown is not None):
            self.pause_btn.set_visible(shown is not None)
            self.narrow.set_condition(self.narrow_condition())  # l'en-tête s'élargit pendant une pause
        if shown is not None:
            label, tooltip = shown
            self.pause_label.set_label(label)
            self.pause_btn.set_tooltip_text(tooltip)
            self.pause_text.set_label(tooltip.split("\n", 1)[0])

    def show_update(self, state):
        found = attention.update_banner(state.get("update"))
        if found is None or found[0] == self.update_seen:
            self.update_banner.set_revealed(False)
            return
        self.update_banner.set_title(found[0])
        self.update_url = found[1]
        self.update_banner.set_revealed(True)

    def on_update_banner(self, banner):
        self.update_seen = banner.get_title()  # vu : plus affiché jusqu'à la prochaine version
        banner.set_revealed(False)
        if self.update_url:
            def done(launcher, result):
                try:
                    launcher.launch_finish(result)
                except GLib.Error:
                    self.toast(f"Impossible d'ouvrir {self.update_url}")
            Gtk.UriLauncher.new(self.update_url).launch(self, None, done)

    def check_health(self):
        """Bilan de santé une fois par lancement, hors de l'interface : bandeau s'il trouve
        une erreur (les avertissements restent dans le dialogue)."""
        def work():
            try:
                return doctor.run_checks()
            except Exception:  # noqa: BLE001 — bilan impossible : pas de bandeau
                return []
        in_thread(work, self.health_checked)
        return False

    def health_checked(self, checks):
        title = attention.doctor_banner(checks)
        if title:
            self.doctor_banner.set_title(title)
        self.doctor_banner.set_revealed(bool(title))

    def show_doctor(self):
        self.doctor_banner.set_revealed(False)
        show_doctor(self)

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
        if self.pause_btn.get_visible():
            width += PAUSE_SP
        return Adw.BreakpointCondition.parse(f"max-width: {width}sp")

    def reveal_terminals(self):
        """Onglet « Terminaux » visible dans la barre de la fenêtre, sans l'afficher."""
        if not self.terminals_page.get_visible():
            self.terminals_page.set_visible(True)
            self.narrow.set_condition(self.narrow_condition())

    def show_terminals(self):
        self.reveal_terminals()
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

    def new_session(self, cwd=None):
        """Dialogue « Nouvelle session » (dossier, compte, modèle, permissions)."""
        ask_new_session(self, cwd or self.sessions.default_folder(), self.start_spec)

    def start_spec(self, spec):
        """Bascule sur le compte choisi s'il le faut (hors de l'interface), puis ouvre la session."""
        def work():
            try:
                return launch_options.switch_if_needed(spec)
            except OSError as e:
                return False, str(e)

        def switched(result):
            done, error = result
            if error:
                self.toast(f"Session non ouverte : {error}")
                return
            if done:
                daemon.request_refresh()
                self.toast(f"Basculé sur « {spec.profile} » — les sessions ouvertes suivront "
                           "à leur prochaine requête")
            self.open_spec(spec)
        in_thread(work, switched)

    def open_spec(self, spec):
        embedded = terminal.choose(self.terminals.available) == "integre"
        try:
            where = launch_options.open_session(spec, embedded, self.terminals.open_claude)
        except OSError as e:
            self.toast(error_text(e))
            return
        if where == "externe":
            self.toast("Nouvelle session lancée dans un terminal")
        for delay in (2000, 8000):  # le temps que la session apparaisse
            GLib.timeout_add(delay, lambda: (self.sessions.visible_page and self.sessions.load(), False)[1])

    def show_session(self, ref):
        """Session désignée par une notification : son onglet s'il y en a un, sinon sa carte
        dans l'onglet Sessions, mise en évidence."""
        target = attention.focus_target(ref, self.terminals.states())
        if target is None:
            return None
        if target[0] == "onglet":
            tab = next((t for t in self.terminals.tabs() if t.state is target[1]), None)
            if tab is not None:
                self.terminals.present(tab)
                return "onglet"
            target = ("sessions", target[1].pid, target[1].session_id)
        self.stack.set_visible_child_name("sessions")
        self.sessions.highlight(target[1], target[2])
        return "sessions"

    def preview(self, conv):
        show_preview(self, conv)

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
    """Instance unique. Action d'application « show-session » (paramètre : référence de
    session, cf. attention.parse_session_ref) : appelée par le service quand on clique sur
    une notification, ou par `claude-accounts gui --session <réf>`."""

    def __init__(self, session=None):
        # CCS_APP_ID : lancer une instance distincte (tests) sans réveiller l'application ouverte.
        super().__init__(application_id=desktop.app_id(), flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.pending_session = session
        show = Gio.SimpleAction.new(desktop.SHOW_ACTION, GLib.VariantType.new("s"))
        show.connect("activate", lambda _a, v: self.show_session(v.get_string()))
        self.add_action(show)

    def window(self):
        win = self.props.active_window or next(iter(self.get_windows()), None)
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
        return win

    def do_activate(self):
        win = self.window()
        win.present()
        if self.pending_session:
            ref, self.pending_session = self.pending_session, None
            win.show_session(ref)

    def show_session(self, ref):
        win = self.window()
        win.present()
        win.show_session(ref)


def run(session=None):
    app = App(session)
    if session:
        try:
            app.register(None)
        except GLib.Error:
            pass
        if app.get_is_remote():
            # Application déjà ouverte : elle affiche la session ; run() ci-dessous la met au
            # premier plan et envoie les deux messages avant de rendre la main.
            app.pending_session = None
            app.activate_action(desktop.SHOW_ACTION, GLib.Variant("s", session))
    return app.run([sys.argv[0]])
