"""Application « CCS » (GTK4/libadwaita)."""

import shutil
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import (attention, conversations, daemon, desktop, doctor, installer, launch_options, pause,  # noqa: E402
               sessions, switch_log, terminal)
from ..settings import load_settings, save_settings  # noqa: E402
from ..store import Store  # noqa: E402
from .accounts import add_account, set_pause  # noqa: E402
from .analysis_hub import AnalysisHub  # noqa: E402
from .common import (ask_name, ask_title, cap, error_text, in_thread, install_css, load_state,  # noqa: E402
                     now_utc, refresh_data, run_ccs_async)
from .doctor_dialog import show_doctor  # noqa: E402
from . import style  # noqa: E402
from .home_page import HomePage  # noqa: E402
from .new_session_dialog import ask_new_session  # noqa: E402
from .preview_dialog import show_preview  # noqa: E402
from .prefs_dialog import PrefsDialog  # noqa: E402
from .sessions_page import SessionsPage  # noqa: E402
from .update_dialog import show_update  # noqa: E402
from .terminals import TerminalsPage  # noqa: E402

APP_ID = desktop.APP_ID
STALE_S = 600
DOCTOR_DELAY_S = 4   # bilan de santé du démarrage : après le premier affichage
# Sous cette largeur, les onglets passent dans la barre du bas : 6 onglets de même largeur
# tenaient en 1080 px, 7 en 1202 px (mesuré : environ 100 px par onglet) ; 4 onglets, plus une marge.
NARROW_SP = 900
# Pendant une pause, « Auto ⏸ jusqu'à 14:00 » remplace « Auto » : le seuil monte de la
# différence de largeur (mesurée), plus cette marge.
PAUSE_MARGIN_SP = 16
FRESH_CHECK_S = 30   # vérifie toutes les 30 s si un nouveau paquet a été installé


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="CCS")
        self.set_default_size(1180, 860)
        install_css()
        style.apply_color_scheme(load_settings()["appearance"]["color_scheme"])
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
        menu.append("Réglages", "win.prefs")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text="Menu principal"))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Actualiser (F5)")
        refresh.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh)
        self.auto_box = Gtk.Box(spacing=6, tooltip_text="Bascule automatique avant la coupure")
        # Pendant une pause, « Auto » devient « Auto ⏸ jusqu'à 14:00 » ; un clic propose de reprendre.
        self.auto_label = Gtk.Label(label="Auto", css_classes=["dim-label"])
        self.auto_width = self.auto_label.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        self.pause_extra = 0   # largeur ajoutée à l'en-tête par l'indicateur de pause
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
                              ("doctor", lambda *_: self.show_doctor()),
                              ("prefs", lambda *_: self.show_prefs())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        tab_action = Gio.SimpleAction.new("show-tab", GLib.VariantType.new("s"))
        tab_action.connect("activate", lambda _a, v: self.show_page(v.get_string()))
        self.add_action(tab_action)

        self.stack = Adw.ViewStack()
        self.home = HomePage(self)
        self.accounts, self.planning = self.home.accounts, self.home.planning
        self.sessions = SessionsPage(self)
        # Onglet Sessions : la vue d'ensemble est la première page épinglée de la barre
        # d'onglets des chats et des terminaux.
        self.terminals = TerminalsPage(self, overview=self.sessions)
        self.analysis_hub = AnalysisHub(self)
        self.history, self.analysis = self.analysis_hub.history, self.analysis_hub.analysis
        for page, name, title, icon in (
                (self.home, "home", "Accueil", "go-home-symbolic"),
                (self.terminals, "sessions", "Sessions", "utilities-terminal-symbolic"),
                (self.analysis_hub, "analysis", "Analyse", "edit-find-symbolic")):
            self.stack.add_titled_with_icon(page, name, title, icon)
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
        self.update_version = self.update_title = None
        self.update_packaged = None   # None : pas encore su ; False : copie de développement
        self.update_banner = Adw.Banner(button_label="Voir")
        self.update_banner.connect("button-clicked", self.on_update_banner)
        view.add_top_bar(self.update_banner)
        self.doctor_banner = Adw.Banner(button_label="Voir le bilan")
        self.doctor_banner.connect("button-clicked", lambda *_: self.show_doctor())
        view.add_top_bar(self.doctor_banner)
        # Un nouveau paquet installé pendant que l'application tourne : proposer de la relancer.
        self._code_stamp = installer.code_stamp()
        self.restart_banner = Adw.Banner(title="CCS a été mis à jour : relance-le pour profiter des nouveautés",
                                         button_label="Relancer")
        self.restart_banner.connect("button-clicked", lambda *_: self.relaunch_app())
        view.add_top_bar(self.restart_banner)
        view.add_bottom_bar(bottom_switcher)
        self.set_content(view)
        # Fenêtre étroite : onglets en bas, comme les applications GNOME (en dessous de
        # NARROW_SP, les onglets du haut seraient tronqués).
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
        GLib.timeout_add_seconds(FRESH_CHECK_S, self.check_fresh)

        self.reload()
        state = load_state()
        if time.time() - (state.get("updated_at") or 0) > STALE_S and not daemon.running_pid():
            self.refresh()
        self.sessions.count_waiting()
        self.update_badge()
        self.terminals.connect("tab-state-changed", lambda *_: (self.sessions.count_waiting(),
                                                                self.update_badge()))
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
        self.home.render(state, self.store)
        self.analysis_hub.reload(state, self.store, self.stack.get_visible_child_name() == "analysis")
        self.show_pause()
        self.show_update(state)
        self.update_badge()

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
        self.pause_btn.set_visible(shown is not None)
        extra = 0
        if shown is not None:
            label, tooltip = shown
            self.pause_label.set_label(label)
            self.pause_btn.set_tooltip_text(tooltip)
            self.pause_text.set_label(tooltip.split("\n", 1)[0])
            width = self.pause_btn.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            extra = max(0, width - self.auto_width) + PAUSE_MARGIN_SP
        if extra != self.pause_extra:
            # L'en-tête s'élargit pendant une pause : les onglets passent en bas plus tôt.
            self.pause_extra = extra
            self.narrow.set_condition(self.narrow_condition())

    def show_update(self, state):
        found = attention.update_banner(state.get("update"))
        if found is None or found[0] == self.update_seen:
            self.update_banner.set_revealed(False)
            return
        self.update_url = found[1]
        self.update_title = found[0]
        self.update_version = found[0].split()[1]
        self.update_banner.set_title(found[0])
        if self.update_packaged is None:
            # Paquet dpkg ou copie de développement : sondé une fois, hors de l'interface.
            def known(packaged):
                self.update_packaged = packaged
                self.show_update(state)
            in_thread(installer.is_package_install, known)
            self.update_banner.set_button_label("Voir")
        elif self.update_packaged:
            self.update_banner.set_button_label("Installer")
        else:
            self.update_banner.set_title(f"{found[0]} — copie de développement : mise à jour par git")
            self.update_banner.set_button_label("Voir")
        self.update_banner.set_revealed(True)

    def on_update_banner(self, banner):
        self.update_seen = self.update_title  # vu : plus affiché jusqu'à la prochaine version
        banner.set_revealed(False)
        if self.update_packaged and self.update_version:
            show_update(self, self.update_version, self.update_url)
        elif self.update_url:
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
        if getattr(self, "terminals", None) is None:
            return  # la page Sessions se construit encore
        name = self.stack.get_visible_child_name()
        on_terminals = name == "sessions" and not self.terminals.overview_shown()
        if on_terminals:
            self.terminals.focus_selected()
        else:
            self.terminals.update_badge()
        if name != "sessions":
            self.back_to = name
        self.sessions.visible_page = name == "sessions" and not on_terminals
        if self.sessions.visible_page:
            self.sessions.load()
        if name == "analysis":
            self.analysis_hub.on_shown()
        self.update_badge()

    def update_badge(self):
        """Badge de l'onglet Sessions : nombre de sessions (chats compris) qui attendent une
        réponse ou une autorisation ; point d'attention si un onglet demande de l'attention."""
        def work():
            try:
                return attention.waiting_count(sessions.list_sessions())
            except Exception:  # noqa: BLE001 — pas de badge plutôt qu'une erreur
                return 0

        def done(n):
            page = self.stack.get_page(self.stack.get_child_by_name("sessions"))
            page.set_badge_number(n)
            page.set_needs_attention(
                self.stack.get_visible_child_name() != "sessions"
                and (n > 0 or self.terminals.wants_attention))
        in_thread(work, done)

    # ---- terminal intégré ----------------------------------------------------------

    def narrow_condition(self):
        return Adw.BreakpointCondition.parse(f"max-width: {NARROW_SP + self.pause_extra}sp")

    def reveal_terminals(self):
        """Les terminaux sont toujours accessibles dans l'onglet Sessions."""

    def show_terminals(self):
        self.stack.set_visible_child_name("sessions")

    def hide_terminals(self):
        """Plus de chat ouvert : retour à la vue d'ensemble des sessions."""
        self.terminals.show_overview()

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

    def show_page(self, name):
        """Affiche la page `name` (ancien ou nouveau nom, cf. desktop.page_name) : l'onglet et
        sa sous-partie. « prefs » ouvre la fenêtre des réglages. Renvoie le nom de l'onglet
        (ou « prefs »), None si le nom est inconnu."""
        found = desktop.page_name(name)
        if found is None:
            return None
        page, sub = found
        if page == "prefs":
            self.show_prefs()
            return page
        self.stack.set_visible_child_name(page)
        if page == "home":
            self.home.show(sub)
        elif page == "analysis":
            self.analysis_hub.show(sub)
        return page

    def show_prefs(self):
        PrefsDialog(self).present(self)

    def open_session(self, cwd):
        """Ouvre une session Claude dans `cwd` (bouton de la page Projets)."""
        return self.open_claude(cwd)

    def show_session(self, ref):
        """Session désignée par une notification : son onglet s'il y en a un, sinon sa carte
        dans l'onglet Sessions (projet de la session choisi), mise en évidence."""
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
        self.terminals.show_overview()
        self.sessions.highlight(target[1], target[2])
        return "sessions"

    def show_task(self, task_id):
        """Tâche désignée par la notification de fin : Accueil, partie Planning, journal de la
        tâche ouvert. Renvoie « planning » (la tâche est affichée) ou None (identifiant inconnu :
        on n'affiche alors que l'onglet)."""
        self.show_page("planning")
        return "planning" if self.planning.tasks_view.show_task(task_id) else None

    def preview(self, conv):
        show_preview(self, conv)

    def terminals_changed(self):
        """Un onglet s'est ouvert, arrêté, fermé ou a appris sa conversation : les boutons
        « Afficher » de l'onglet Sessions suivent."""
        if self.sessions.visible_page:
            self.sessions.rerender()
        self.update_badge()

    def check_fresh(self):
        """Le code sur le disque a changé depuis le lancement : bandeau « Relancer »."""
        stamp = installer.code_stamp()
        if stamp is not None and self._code_stamp is not None and stamp != self._code_stamp:
            self.restart_banner.set_revealed(True)
        return True

    def relaunch_app(self):
        """« Relancer » : une nouvelle instance démarre une seconde après la fermeture de celle-ci
        (la confirmation habituelle s'applique si des sessions tournent)."""
        exe = shutil.which("claude-accounts") or "claude-accounts"
        subprocess.Popen(["sh", "-c", 'sleep 1; exec "$0" gui', exe], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.close()

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
        if self.sessions.visible_page or self.sessions.convs is not None:
            self.sessions.load()

    # ---- actions -----------------------------------------------------------------

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def switch(self, name):
        switch_log.note_origin(name, "application")   # pour le journal des bascules
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


# Action d'application déclenchée depuis desktop.py (clic sur « tâche finie »), comme
# `desktop.SHOW_ACTION` pour les sessions.
SHOW_TASK_ACTION = getattr(desktop, "SHOW_TASK_ACTION", "show-task")


class App(Adw.Application):
    """Instance unique. Actions d'application, appelées aussi par une deuxième instance
    (`claude-accounts gui …` alors que l'application tourne) :
    - « show-session » (paramètre : référence de session, cf. attention.parse_session_ref) :
      clic sur une notification, ou `gui --session <réf>` ;
    - « show-task » (paramètre : identifiant de la tâche) : clic sur la notification de fin d'une
      tâche (onglet Planning, journal de la tâche) ;
    - « show-page » (paramètre : nom d'un onglet, cf. desktop.page_name) : `gui --page` ;
    - « new-session » (sans paramètre) : `gui --new-session`."""

    def __init__(self, session=None, page=None, new_session=False, task=None):
        # CCS_APP_ID : lancer une instance distincte (tests) sans réveiller l'application ouverte.
        super().__init__(application_id=desktop.app_id(), flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.pending_session = session
        self.pending_page = page
        self.pending_task = task
        self.pending_new_session = bool(new_session)
        for name, kind, handler in ((desktop.SHOW_ACTION, "s", lambda v: self.show_session(v.get_string())),
                                    (SHOW_TASK_ACTION, "s", lambda v: self.show_task(v.get_string())),
                                    (desktop.SHOW_PAGE_ACTION, "s", lambda v: self.show_page(v.get_string())),
                                    (desktop.NEW_SESSION_ACTION, None, lambda _v: self.new_session())):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new(kind) if kind else None)
            action.connect("activate", lambda _a, v, h=handler: h(v))
            self.add_action(action)

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
            self.set_accels_for_action("win.prefs", ["<Control>comma"])
            for key, tab in enumerate(desktop.PAGES, 1):
                self.set_accels_for_action(f"win.show-tab::{tab}", [f"<Control>{key}"])
        return win

    def do_activate(self):
        win = self.window()
        win.present()
        if self.pending_page:
            page, self.pending_page = self.pending_page, None
            win.show_page(page)
        if self.pending_session:
            ref, self.pending_session = self.pending_session, None
            win.show_session(ref)
        if self.pending_task:
            task_id, self.pending_task = self.pending_task, None
            win.show_task(task_id)
        if self.pending_new_session:
            self.pending_new_session = False
            GLib.idle_add(lambda: (win.new_session(), False)[1])   # fenêtre affichée d'abord

    def show_session(self, ref):
        win = self.window()
        win.present()
        win.show_session(ref)

    def show_task(self, task_id):
        win = self.window()
        win.present()
        win.show_task(task_id)

    def show_page(self, name):
        win = self.window()
        win.present()
        win.show_page(name)

    def new_session(self):
        win = self.window()
        win.present()
        win.new_session()


def remote_actions(session=None, page=None, new_session=False, task=None):
    """[(action, paramètre)] à envoyer à l'application déjà ouverte, dans l'ordre."""
    out = []
    if page:
        out.append((desktop.SHOW_PAGE_ACTION, GLib.Variant("s", page)))
    if session:
        out.append((desktop.SHOW_ACTION, GLib.Variant("s", session)))
    if task:
        out.append((SHOW_TASK_ACTION, GLib.Variant("s", str(task))))
    if new_session:
        out.append((desktop.NEW_SESSION_ACTION, None))
    return out


def run(session=None, page=None, new_session=False, task=None):
    app = App(session, page, new_session, task)
    actions = remote_actions(session, page, new_session, task)
    if actions:
        try:
            app.register(None)
        except GLib.Error:
            pass
        if app.get_is_remote():
            # Application déjà ouverte : elle affiche l'onglet, la session ou le dialogue ;
            # run() ci-dessous la met au premier plan et envoie les messages avant de rendre
            # la main.
            app.pending_session, app.pending_page, app.pending_new_session = None, None, False
            app.pending_task = None
            for name, value in actions:
                app.activate_action(name, value)
    return app.run([sys.argv[0]])
