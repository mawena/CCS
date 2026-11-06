"""Terminal intégré : sessions Claude Code et shells dans des onglets de l'application.

Le terminal est un widget VTE (paquet gir1.2-vte-3.91), importé à la demande : s'il
manque, l'application garde le terminal externe et rien ici n'est construit. Ce qui se
décide sans GTK (commande, environnement, textes, état des onglets) est dans
`ccs_app.terminal`.
"""

import os
import signal
import time

import gi
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from .. import limit_events, sessions, terminal, terminal_store
from .common import in_thread

SCROLLBACK_LINES = 100_000
POLL_S = 3
FONT_FALLBACK = "Monospace 11"
# Adresses affichées en clair (Claude Code affiche ainsi ses liens de connexion).
URL_REGEX = r"(?:https?|file)://[^\s<>\"'`]*[^\s<>\"'`.,;:!?)\]}]"
PCRE2_MULTILINE = 0x00000400
PCRE2_CASELESS = 0x00000008
# Palette « GNOME » de GNOME Terminal, lisible sur fond clair comme sur fond sombre.
PALETTE = ("#171421", "#c01c28", "#26a269", "#a2734c", "#12488b", "#a347ba", "#2aa1b3", "#d0cfcc",
           "#5e5c64", "#f66151", "#33d17a", "#e9ad0c", "#2a7bde", "#c061cb", "#33c7de", "#ffffff")
COLORS = {False: ("#1e1e1e", "#ffffff"), True: ("#ffffff", "#1e1e1e")}  # sombre ? -> (texte, fond)

_vte = None


def vte():
    """Module Vte pour GTK4, ou None s'il n'est pas installé (ou écarté par CCS_NO_VTE)."""
    global _vte
    if _vte is None:
        _vte = False
        if not terminal.embedded_disabled():
            try:
                gi.require_version("Vte", "3.91")
                from gi.repository import Vte
                _vte = Vte
            except (ImportError, ValueError):
                pass
    return _vte or None


def _rgba(spec):
    color = Gdk.RGBA()
    color.parse(spec)
    return color


def system_font():
    """Police à chasse fixe du bureau (réglage GNOME), sinon « Monospace 11 »."""
    schema = "org.gnome.desktop.interface"
    source = Gio.SettingsSchemaSource.get_default()
    if source is not None and source.lookup(schema, True) is not None:
        name = Gio.Settings.new(schema).get_string("monospace-font-name")
        if name:
            return Pango.FontDescription.from_string(name)
    return Pango.FontDescription.from_string(FONT_FALLBACK)


class TerminalTab(Gtk.Box):
    """Un onglet : le terminal, sa barre de défilement, le bandeau d'information (reprise
    après une limite) et le bandeau de fin."""

    def __init__(self, owner, launch):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        Vte = vte()
        self.owner = owner
        self.launch = launch
        self.state = terminal.TabState(launch.kind, launch.cwd, launch.title, launch.session_id,
                                       extra_args=launch.extra_args)
        self.page = None
        self.menu_uri = None
        self.feeding = False       # texte envoyé par l'application : pas une saisie
        self.limits_done = set()   # (session_id, date) des limites déjà traitées

        self.notice = Adw.Banner(revealed=False, button_label="OK", use_markup=False)
        self.notice.connect("button-clicked", lambda b: b.set_revealed(False))
        self.append(self.notice)

        self.term = Vte.Terminal(hexpand=True, vexpand=True, css_classes=["ccs-terminal"])
        self.term.set_scrollback_lines(SCROLLBACK_LINES)
        self.term.set_mouse_autohide(True)
        self.term.set_allow_hyperlink(True)
        self.term.set_audible_bell(False)
        self.term.set_font(owner.font)
        self.apply_colors(owner.dark)
        regex = Vte.Regex.new_for_match(URL_REGEX, -1, PCRE2_MULTILINE | PCRE2_CASELESS)
        tag = self.term.match_add_regex(regex, 0)
        self.term.match_set_cursor_name(tag, "pointer")
        self.term.connect("child-exited", self.on_exited)
        self.term.connect("window-title-changed", self.on_window_title)
        self.term.connect("contents-changed", self.on_contents)
        self.term.connect("bell", lambda *_: self.attention())
        self.term.connect("commit", self.on_commit)
        self.install_input()

        body = Gtk.Box()
        body.append(self.term)
        body.append(Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL,
                                  adjustment=self.term.get_vadjustment()))
        self.append(body)

        self.bar = Gtk.ActionBar(revealed=False)
        self.bar_label = Gtk.Label(xalign=0, wrap=True, css_classes=["heading"])
        self.bar.pack_start(self.bar_label)
        close = Gtk.Button(label="Fermer")
        close.connect("clicked", lambda *_: self.owner.close(self))
        self.relaunch_btn = Gtk.Button(css_classes=["suggested-action"])
        self.relaunch_btn.connect("clicked", lambda *_: self.relaunch())
        self.bar.pack_end(self.relaunch_btn)
        self.bar.pack_end(close)
        self.append(self.bar)

    # ---- confort -------------------------------------------------------------------

    def install_input(self):
        keys = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        for accel, handler in (("<Control><Shift>c", self.copy), ("<Control><Shift>v", self.paste),
                               ("<Control><Shift>a", lambda: self.term.select_all()),
                               ("<Control>plus", lambda: self.zoom(1.1)),
                               ("<Control>equal", lambda: self.zoom(1.1)),
                               ("<Control>minus", lambda: self.zoom(1 / 1.1)),
                               ("<Control>0", lambda: self.zoom(None))):
            keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(accel),
                                           action=Gtk.CallbackAction.new(
                                               lambda *_a, h=handler: (h(), True)[1])))
        self.term.add_controller(keys)

        # Ctrl+clic sur un lien : ouverture dans le navigateur.
        click = Gtk.GestureClick(button=1, propagation_phase=Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self.on_click)
        self.term.add_controller(click)

        actions = Gio.SimpleActionGroup()
        for name, handler in (("copy", self.copy), ("paste", self.paste),
                              ("select-all", lambda: self.term.select_all()),
                              ("open-link", lambda: self.open_uri(self.menu_uri)),
                              ("copy-link", lambda: self.copy_text(self.menu_uri))):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_a, h=handler: h())
            actions.add_action(a)
        self.actions = actions
        self.term.insert_action_group("term", actions)
        self.term.set_context_menu_model(self.owner.context_menu)
        self.term.connect("setup-context-menu", self.on_setup_menu)

    def link_at(self, x, y):
        uri = self.term.check_hyperlink_at(x, y)
        if not uri:
            uri, _tag = self.term.check_match_at(x, y)
        return uri

    def on_click(self, gesture, _n, x, y):
        if not gesture.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            return
        uri = self.link_at(x, y)
        if uri:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.open_uri(uri)

    def on_setup_menu(self, _term, context):
        if context is None:
            return  # menu refermé
        ok, x, y = context.get_coordinates()
        self.menu_uri = self.link_at(x, y) if ok else None
        self.actions.lookup_action("copy").set_enabled(self.term.get_has_selection())
        for name in ("open-link", "copy-link"):
            self.actions.lookup_action(name).set_enabled(bool(self.menu_uri))

    def open_uri(self, uri):
        if uri:
            Gtk.UriLauncher(uri=uri).launch(self.get_root(), None, None)

    def copy_text(self, text):
        if text:
            self.get_clipboard().set(text)

    def copy(self):
        if self.term.get_has_selection():
            self.term.copy_clipboard_format(vte().Format.TEXT)

    def paste(self):
        self.term.paste_clipboard()

    def zoom(self, factor):
        self.term.set_font_scale(1.0 if factor is None else
                                 min(4.0, max(0.25, self.term.get_font_scale() * factor)))

    def apply_colors(self, dark):
        fg, bg = COLORS[bool(dark)]
        self.term.set_colors(_rgba(fg), _rgba(bg), [_rgba(c) for c in PALETTE])

    def focus(self):
        GLib.idle_add(lambda: (self.term.grab_focus(), False)[1])

    def send_text(self, text, enter=False):
        """Écrit `text` dans le terminal comme s'il était tapé (Entrée en plus si `enter`).
        Renvoie False si le processus est arrêté."""
        if not self.state.running:
            return False
        data = (text + ("\r" if enter else "")).encode()
        self.feeding = True
        try:
            self.term.feed_child(data)
        finally:
            self.feeding = False
        return True

    def send_auto(self, text):
        """Envoi décidé par l'application (reprise, file de messages) : texte puis Entrée."""
        if not self.send_text(text, enter=True):
            return False
        self.state.sent_at = time.time()
        return True

    def on_commit(self, *_):
        if not self.feeding:
            self.state.typed_at = time.time()

    def show_notice(self, text):
        self.notice.set_title(text)
        self.notice.set_revealed(True)

    # ---- processus -----------------------------------------------------------------

    def spawn(self, launch=None):
        Vte = vte()
        self.launch = launch or self.launch
        st = self.state
        st.exit_status, st.state, st.waiting_for = None, None, None
        st.started_at = st.busy_since = st.typed_at = st.sent_at = None
        self.bar.set_revealed(False)
        self.term.spawn_async(Vte.PtyFlags.DEFAULT, self.launch.cwd, list(self.launch.argv),
                              self.launch.envv(), GLib.SpawnFlags.DEFAULT, None, None, -1, None,
                              self.on_spawned, None)

    def on_spawned(self, _term, pid, error, *_):
        if error is not None or pid <= 0:
            self.state.running = False
            self.show_bar(f"Lancement impossible : {error.message if error else 'erreur inconnue'}")
        else:
            self.state.pid, self.state.running = pid, True
            self.state.started_at = time.time()
        self.owner.changed(self)
        if self.state.running:
            self.owner.emit("tab-started", self)

    def on_exited(self, _term, status):
        self.state.running, self.state.exit_status = False, status
        self.show_bar(terminal.exit_text(self.state.kind, status))
        self.attention()
        self.owner.changed(self)
        self.owner.emit("tab-exited", self, status)

    def show_bar(self, text):
        self.bar_label.set_label(text)
        self.relaunch_btn.set_label(terminal.relaunch_label(self.state))
        self.bar.set_revealed(True)

    def relaunch(self):
        if not self.state.running:
            self.term.reset(True, False)
            self.spawn(terminal.relaunch(self.state))
            self.focus()

    def foreground_busy(self):
        """Shell : un programme tourne au premier plan (groupe du terminal ≠ shell)."""
        pty = self.term.get_pty()
        if not self.state.running or pty is None or self.state.pid is None:
            return False
        try:
            return os.tcgetpgrp(pty.get_fd()) != self.state.pid
        except OSError:
            return False

    def hang_up(self):
        """Ferme la session comme on ferme une fenêtre de terminal (SIGHUP) : claude
        enregistre la conversation et s'arrête."""
        if not (self.state.running and self.state.pid):
            return
        groups = {self.state.pid}  # le processus de l'onglet dirige sa propre session
        pty = self.term.get_pty()
        try:
            groups.add(os.tcgetpgrp(pty.get_fd()))  # programme lancé au premier plan du shell
        except (OSError, AttributeError):
            pass
        for group in groups:
            try:
                os.killpg(group, signal.SIGHUP)
            except OSError:
                pass

    # ---- titre et activité -----------------------------------------------------------

    def set_title(self, title):
        if title and title != self.state.title:
            self.state.title = title
            self.update_page()

    def on_window_title(self, *_):
        if self.state.kind == "shell":  # titre posé par le shell (dossier courant…)
            title = self.term.get_window_title()
            if title:
                self.page and self.page.set_tooltip(title)

    def on_contents(self, *_):
        if self.state.kind == "shell" and self.page and not self.page.get_selected():
            self.attention()

    def attention(self):
        if self.page and not (self.page.get_selected() and self.owner.on_screen()):
            self.page.set_needs_attention(True)
            self.owner.update_badge()

    def update_page(self):
        if self.page is None:
            return
        self.page.set_title(self.state.title)
        where = sessions.project_name(self.state.cwd)
        tip = [self.state.title] if self.state.kind == "claude" else []
        self.page.set_tooltip("\n".join(tip + [f"{where} · {self.state.cwd}"]))
        loading, icon, tooltip = terminal.indicator(self.state)
        self.page.set_loading(loading)
        self.page.set_indicator_icon(Gio.ThemedIcon.new(icon) if icon else None)
        self.page.set_indicator_tooltip(tooltip or "")


class TerminalsPage(Gtk.Box):
    """Page « Terminaux » : les onglets de sessions intégrées.

    Signaux (le premier argument après la page est le TerminalTab) :
    - « tab-started » : processus lancé (au démarrage et à chaque relance) ;
    - « tab-exited » (tab, statut waitpid) : processus arrêté, l'onglet reste ouvert ;
    - « tab-state-changed » : identifiant de conversation ou état (travaille, attend ta
      réponse, au repos) appris des fiches de session ;
    - « tab-closed » : onglet fermé (après confirmation s'il le fallait)."""

    __gsignals__ = {
        "tab-started": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "tab-exited": (GObject.SignalFlags.RUN_FIRST, None, (object, int)),
        "tab-state-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "tab-closed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.available = vte() is not None
        self.menu_tab = None
        self.polling = False
        self.style = Adw.StyleManager.get_default()
        self.dark = self.style.get_dark()
        self.font = system_font()
        self.options = terminal_store.load_options()
        if not self.available:
            return

        self.context_menu = Gio.Menu()
        edit = Gio.Menu()
        edit.append("Copier", "term.copy")
        edit.append("Coller", "term.paste")
        edit.append("Tout sélectionner", "term.select-all")
        link = Gio.Menu()
        link.append("Ouvrir le lien", "term.open-link")
        link.append("Copier le lien", "term.copy-link")
        self.context_menu.append_section(None, edit)
        self.context_menu.append_section(None, link)

        self.view = Adw.TabView(vexpand=True)
        self.view.connect("close-page", self.on_close_page)
        self.view.connect("page-detached", self.on_detached)
        self.view.connect("notify::selected-page", self.on_selected)
        self.view.connect("setup-menu", self.on_setup_menu)
        tab_menu = Gio.Menu()
        tab_menu.append("Renommer la conversation…", "tabs.rename")
        tab_menu.append("Ouvrir le dossier", "tabs.folder")
        tab_menu.append("Fermer l'onglet", "tabs.close")
        self.view.set_menu_model(tab_menu)

        self.tab_actions = Gio.SimpleActionGroup()
        for name, handler in (("rename", self.rename_tab), ("folder", self.folder_of_tab),
                              ("close", self.close)):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_a, h=handler: self.with_tab(h))
            self.tab_actions.add_action(a)
        self.insert_action_group("tabs", self.tab_actions)

        # Interrupteurs de la page (gardés dans terminals.json, pas dans les réglages généraux).
        self.page_actions = Gio.SimpleActionGroup()
        for name, key in (("auto-resume", "auto_resume"),):
            a = Gio.SimpleAction.new_stateful(name, None, GLib.Variant.new_boolean(self.options[key]))
            a.connect("change-state", lambda act, value, k=key: self.set_option(act, k, value))
            self.page_actions.add_action(a)
        self.insert_action_group("terms", self.page_actions)
        options = Gio.Menu()
        options.append("Reprise automatique après une limite", "terms.auto-resume")
        page_menu = Gio.Menu()
        page_menu.append_section(None, tab_menu)
        page_menu.append_section(None, options)

        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=page_menu, css_classes=["flat"],
                              tooltip_text="Onglet et options")
        more.connect("notify::active", lambda b, _p: b.get_active() and self.prepare_menu(None))
        self.bar = Adw.TabBar(view=self.view, autohide=False, end_action_widget=more)
        self.append(self.bar)
        self.append(self.view)

        self.style.connect("notify::dark", self.on_dark)
        schema = "org.gnome.desktop.interface"
        source = Gio.SettingsSchemaSource.get_default()
        if source is not None and source.lookup(schema, True) is not None:
            self.desktop = Gio.Settings.new(schema)
            self.desktop.connect("changed::monospace-font-name", self.on_font)

    # ---- onglets -------------------------------------------------------------------

    def tabs(self):
        if not self.available:
            return []
        return [self.view.get_nth_page(i).get_child() for i in range(self.view.get_n_pages())]

    def states(self):
        return [t.state for t in self.tabs()]

    def find(self, pid=None, session_id=None):
        state = terminal.find_tab(self.states(), pid=pid, session_id=session_id)
        return next((t for t in self.tabs() if t.state is state), None) if state else None

    def open_claude(self, cwd, resume=None, title=None, extra_args=()):
        """Nouvel onglet : Claude Code dans `cwd` (`resume` : identifiant à reprendre,
        `extra_args` : arguments ajoutés à claude, gardés pour la relance)."""
        return self.open(terminal.claude_launch(cwd, resume, title, extra_args=extra_args))

    def open_shell(self, cwd):
        return self.open(terminal.shell_launch(cwd))

    def open(self, launch):
        """Nouvel onglet pour un `terminal.Launch`, affiché et lancé ; renvoie le TerminalTab."""
        tab = TerminalTab(self, launch)
        tab.page = self.view.append(tab)
        tab.update_page()
        tab.spawn()
        self.present(tab)
        self.changed(tab)
        return tab

    def present(self, tab):
        """Affiche l'onglet (page Terminaux, onglet choisi, focus clavier dans le terminal)."""
        if tab.page is None:
            return  # onglet fermé depuis l'affichage du bouton
        self.window.show_terminals()
        self.view.set_selected_page(tab.page)
        tab.page.set_needs_attention(False)
        self.update_badge()
        tab.focus()

    def on_screen(self):
        return self.window.stack.get_visible_child_name() == "terminals" and self.window.is_active()

    def on_selected(self, *_):
        page = self.view.get_selected_page()
        if page is not None:
            page.set_needs_attention(False)
            page.get_child().focus()
        self.update_badge()

    def focus_selected(self):
        page = self.view.get_selected_page() if self.available else None
        if page is not None:
            page.set_needs_attention(False)
            page.get_child().focus()
        self.update_badge()

    def changed(self, tab=None):
        if tab is not None:
            tab.update_page()
        self.update_badge()
        self.update_actions()
        self.window.terminals_changed()
        if not self.polling and terminal.running_claude(self.states()):
            self.polling = True
            GLib.timeout_add_seconds(POLL_S, self.poll)

    def update_badge(self):
        page = self.window.terminals_page
        tabs = self.tabs()
        page.set_badge_number(len(tabs))
        page.set_needs_attention(any(t.page.get_needs_attention() for t in tabs if t.page)
                                 and self.window.stack.get_visible_child_name() != "terminals")

    def on_detached(self, _view, page, _position):
        tab = page.get_child()
        tab.page = None
        self.emit("tab-closed", tab)
        self.update_badge()
        self.window.terminals_changed()
        if not self.tabs():
            self.window.hide_terminals()

    # ---- fermeture -----------------------------------------------------------------

    def close(self, tab):
        if tab.page is not None:
            self.view.close_page(tab.page)

    def on_close_page(self, view, page):
        tab = page.get_child()
        if tab.state.kind == "shell":
            tab.state.busy = tab.foreground_busy()
        question = terminal.tab_close_question(tab.state)
        if question is None:
            tab.hang_up()
            view.close_page_finish(page, True)
            return True
        d = Adw.AlertDialog(heading=question[0], body=question[1])
        d.add_response("cancel", "Annuler")
        d.add_response("close", "Fermer")
        d.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")

        def on_response(_d, r):
            if r == "close":
                tab.hang_up()
            view.close_page_finish(page, r == "close")
            if r != "close":
                tab.focus()
        d.connect("response", on_response)
        d.present(self.window)
        return True

    def close_question(self):
        for tab in self.tabs():
            if tab.state.kind == "shell":
                tab.state.busy = tab.foreground_busy()
        return terminal.close_question(self.states())

    def hang_up_all(self):
        for tab in self.tabs():
            tab.hang_up()

    # ---- menu des onglets ------------------------------------------------------------

    def on_setup_menu(self, _view, page):
        if page is not None:  # None : menu refermé, l'action choisie vise encore cet onglet
            self.prepare_menu(page.get_child())

    def prepare_menu(self, tab):
        self.menu_tab = tab
        self.update_actions()

    def menu_target(self):
        if self.menu_tab is not None and self.menu_tab.page is not None:
            return self.menu_tab
        page = self.view.get_selected_page()
        return page.get_child() if page is not None else None

    def update_actions(self):
        if not self.available:
            return
        tab = self.menu_target()
        can_rename = bool(tab and tab.state.kind == "claude" and tab.state.session_id)
        self.tab_actions.lookup_action("rename").set_enabled(can_rename)
        for name in ("folder", "close"):
            self.tab_actions.lookup_action(name).set_enabled(tab is not None)

    def with_tab(self, handler):
        tab = self.menu_target()
        self.menu_tab = None
        if tab is not None:
            handler(tab)

    def rename_tab(self, tab):
        self.window.rename_conversation(tab.state.session_id, cwd=tab.state.cwd, current=tab.state.title)

    def folder_of_tab(self, tab):
        sessions.open_folder(tab.state.cwd)

    # ---- suivi des sessions ----------------------------------------------------------

    def set_option(self, action, key, value):
        action.set_state(value)
        self.options[key] = value.get_boolean()
        terminal_store.save_options(self.options)

    def poll(self):
        states = self.states()
        if not terminal.running_claude(states):
            self.polling = False
            return False

        in_thread(lambda: (sessions.list_sessions(), limit_events.load_all()), self.synced)
        return True

    def synced(self, found):
        live, limits = found
        tabs = self.tabs()
        before = {id(t.state): (t.state.session_id, t.state.state) for t in tabs}
        done = terminal.sync_tabs([t.state for t in tabs], live)
        moved = [t for t in tabs if before.get(id(t.state)) != (t.state.session_id, t.state.state)]
        for tab in tabs:
            if tab.state in done:
                tab.attention()
            tab.update_page()
        self.update_actions()
        if any(before[id(t.state)][0] != t.state.session_id for t in moved):
            self.window.terminals_changed()
        for tab in moved:
            self.emit("tab-state-changed", tab)
        self.handle_limits(tabs, limits)
        wanted = [(t, t.state.cwd, t.state.session_id) for t in tabs
                  if t.state.kind == "claude" and t.state.session_id]
        if wanted:
            in_thread(lambda: [(t, sessions.conversation_title(cwd, sid)) for t, cwd, sid in wanted],
                      lambda found: [t.set_title(title) for t, title in found if title])

    def handle_limits(self, tabs, limits):
        """Reprise automatique : « continue » dans l'onglet dont la conversation a été bloquée
        par une limite, une fois le compte changé par le hook StopFailure."""
        now = time.time()
        for tab in tabs:
            event = limits.get(tab.state.session_id) if tab.state.session_id else None
            decision = terminal.resume_decision(tab.state, event, now, enabled=self.options["auto_resume"])
            if decision is None or decision.action == "wait":
                continue
            key = (event.session_id, event.ts)
            if key not in tab.limits_done:  # une seule fois par événement
                tab.limits_done.add(key)
                if decision.action == "resume" and tab.send_auto(terminal.RESUME_TEXT):
                    tab.state.resumes.append(now)
                if decision.text:
                    tab.show_notice(decision.text)
                    tab.attention()
            limit_events.consume(event.session_id, event.ts)

    # ---- apparence -----------------------------------------------------------------

    def on_dark(self, *_):
        self.dark = self.style.get_dark()
        for tab in self.tabs():
            tab.apply_colors(self.dark)

    def on_font(self, *_):
        self.font = system_font()
        for tab in self.tabs():
            tab.term.set_font(self.font)
