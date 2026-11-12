"""Terminal intégré : sessions Claude Code et shells dans des onglets de l'application.

Le terminal est un widget VTE (paquet gir1.2-vte-3.91), importé à la demande : s'il
manque, l'application garde le terminal externe et rien ici n'est construit. Ce qui se
décide sans GTK (commande, environnement, textes, état des onglets) est dans
`ccs_app.terminal`.
"""

import os
import signal
import time
from datetime import datetime, timezone

import gi
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from .. import alerts, conversations, limit_events, notify, phone, sessions, settings, terminal, terminal_store
from .common import in_thread
from .session_workspace import ASK_CREATE_TEXT, SessionWorkspace
from .terminal_split import SplitView

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
SAVE_DELAY_MS = 1000
STOP_WAIT_TRIES = 60       # 60 × 100 ms : temps laissé au chat pour s'arrêter avant le terminal
ELSEWHERE_TEXT = "Cette conversation est ouverte ailleurs : tu pourras écrire quand elle sera fermée."
SPLIT_ACCEL = "<Control><Shift>e"
QUEUE_ACCEL = "<Control><Shift>m"
CSS = b"""
.ccs-restore { padding: 6px 12px; background-color: alpha(@accent_bg_color, 0.18); }
.ccs-split-half { border: 2px solid transparent; border-radius: 8px; margin: 2px; }
.ccs-split-half.active { border-color: @accent_bg_color; }
.ccs-split-header { padding: 2px 4px 2px 10px; }
.ccs-split-half:not(.active) .ccs-split-header { opacity: 0.55; }
.ccs-split-half.active .ccs-split-header > label { font-weight: bold; }
.ccs-queue { padding: 6px 10px; border-top: 1px solid alpha(currentColor, 0.15); }
.ccs-queue-strip { padding: 2px 6px 2px 10px; border-top: 1px solid alpha(currentColor, 0.15); }
"""

_vte = None


def _chat_classes():
    """(ChatTab, module chat_options) : importés à la demande (le chat n'a pas besoin de VTE)."""
    from .. import chat_options
    from . import chat_tab
    return chat_tab.ChatTab, chat_options
_css = False


def install_css():
    """Styles propres à la page Terminaux (une fois par affichage)."""
    global _css
    if not _css:
        _css = True
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS, -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


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


def menu_item(label, action, accel=None):
    """Entrée de menu cachée quand son action est indisponible (raccourci affiché)."""
    item = Gio.MenuItem.new(label, action)
    item.set_attribute_value("hidden-when", GLib.Variant.new_string("action-disabled"))
    if accel:
        item.set_attribute_value("accel", GLib.Variant.new_string(accel))
    return item


def is_chat(tab):
    """Onglet de chat (et non un terminal VTE)."""
    return not isinstance(tab, TerminalTab)


def insert_reference(tab, relpath):
    """« Insérer @chemin » depuis l'arbre : dans la zone de saisie du chat."""
    if hasattr(tab, "insert_reference"):
        tab.insert_reference(relpath)
    elif hasattr(tab, "composer"):
        tab.composer.insert_reference(relpath)


def set_read_only(tab, flag):
    """Chat ouvert ailleurs : la saisie est grisée (le chat lui-même sait le faire, sinon la
    zone de saisie)."""
    if hasattr(tab, "set_read_only"):
        tab.set_read_only(flag)
    elif hasattr(tab, "composer"):
        tab.composer.set_sensitive(not flag)


def chat_record(options):
    """Options du chat telles que `terminal_store` les garde (droits « manual » : None)."""
    if options is None:
        return None
    rights = getattr(options, "rights", None)
    return {"model": options.model, "effort": options.effort, "ultracode": bool(options.ultracode),
            "rights": None if rights in (None, "manual") else rights}


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
    après une limite), la file de messages (claude) et le bandeau de fin, réunis dans
    `panel` : la vue côte à côte emprunte ce panneau puis le rend (l'onglet reste l'enfant
    de sa page d'Adw.TabView)."""

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
        self.queue_rev = None      # file de messages (onglets de claude)
        self.queue_reason = None
        self.queue_shown = None
        self.back = None           # ouvert depuis un chat : de quoi y revenir (cwd, session, options)

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.notice = Adw.Banner(revealed=False, button_label="OK", use_markup=False)
        self.notice.connect("button-clicked", lambda b: b.set_revealed(False))
        self.panel.append(self.notice)

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
        self.panel.append(body)
        if launch.kind == "claude":
            self.build_queue()

        self.bar = Gtk.ActionBar(revealed=False)
        self.bar_label = Gtk.Label(xalign=0, wrap=True, css_classes=["heading"])
        self.bar.pack_start(self.bar_label)
        close = Gtk.Button(label="Fermer")
        close.connect("clicked", lambda *_: self.owner.close(self))
        self.relaunch_btn = Gtk.Button(css_classes=["suggested-action"])
        self.relaunch_btn.connect("clicked", lambda *_: self.relaunch())
        self.back_btn = Gtk.Button(label="Revenir au chat", visible=False)
        self.back_btn.connect("clicked", lambda *_: self.owner.back_to_chat(self))
        self.bar.pack_end(self.relaunch_btn)
        self.bar.pack_end(self.back_btn)
        self.bar.pack_end(close)
        self.panel.append(self.bar)
        self.append(self.panel)

    # ---- messages en attente ---------------------------------------------------------

    def build_queue(self):
        """« Envoyer quand Claude sera libre » : bandeau replié (N en attente) et panneau
        (file éditable, champ de saisie)."""
        self.queue_count = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        show = Gtk.Button(label="Afficher", css_classes=["flat"])
        show.connect("clicked", lambda *_: self.toggle_queue(True))
        strip = Gtk.Box(spacing=8, css_classes=["ccs-queue-strip"])
        for w in (Gtk.Image(icon_name="mail-send-symbolic"), self.queue_count, show):
            strip.append(w)
        self.queue_strip = Gtk.Revealer(child=strip)

        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label="Envoyer quand Claude sera libre", xalign=0, css_classes=["heading"]))
        self.queue_status = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                      css_classes=["dim-label", "caption"])
        head.append(self.queue_status)
        fold = Gtk.Button(icon_name="pan-down-symbolic", css_classes=["flat"], tooltip_text="Replier")
        fold.connect("clicked", lambda *_: self.toggle_queue(False))
        head.append(fold)
        self.queue_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.queue_entry = Gtk.Entry(hexpand=True, placeholder_text="Message à envoyer quand Claude aura fini…")
        self.queue_entry.connect("activate", lambda *_: self.add_message())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_queue_key)
        self.queue_entry.add_controller(keys)
        add = Gtk.Button(label="Ajouter", css_classes=["suggested-action"])
        add.connect("clicked", lambda *_: self.add_message())
        line = Gtk.Box(spacing=6)
        line.append(self.queue_entry)
        line.append(add)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["ccs-queue"])
        for w in (head, self.queue_rows, line):
            box.append(w)
        self.queue_rev = Gtk.Revealer(child=box)
        self.panel.append(self.queue_strip)
        self.panel.append(self.queue_rev)
        self.refresh_queue()

    def on_queue_key(self, _ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.toggle_queue(False)
            return True
        return False

    def toggle_queue(self, show=None):
        if self.queue_rev is None:
            return
        show = not self.queue_rev.get_reveal_child() if show is None else show
        self.queue_rev.set_reveal_child(show)
        self.refresh_queue()
        if show:
            GLib.idle_add(lambda: (self.queue_entry.grab_focus(), False)[1])
        else:
            self.focus()

    def refresh_queue(self):
        """Bandeau, état et lignes de la file (lignes refaites seulement si elle a changé,
        pour ne pas interrompre une modification en cours)."""
        if self.queue_rev is None:
            return
        queue, reason = list(self.state.queue), self.queue_reason
        n = len(queue)
        count = "1 message en attente" if n == 1 else f"{n} messages en attente"
        self.queue_count.set_label(count + (f" — {reason}" if reason else ""))
        self.queue_strip.set_reveal_child(bool(queue) and not self.queue_rev.get_reveal_child())
        self.queue_status.set_label(reason or ("" if queue else "Aucun message en attente."))
        if queue == self.queue_shown:
            return
        self.queue_shown = queue
        while (child := self.queue_rows.get_first_child()) is not None:
            self.queue_rows.remove(child)
        for i, text in enumerate(queue):
            row = Gtk.Box(spacing=4)
            row.append(Gtk.Label(label=f"{i + 1}.", css_classes=["dim-label"]))
            label = Gtk.EditableLabel(text=text, hexpand=True, tooltip_text="Cliquer pour modifier")
            label.connect("notify::editing", lambda w, _p, i=i, old=text: None if w.get_editing()
                          else self.edit_message(i, w.get_text(), old))
            row.append(label)
            for icon, tip, handler, sensitive in (
                    ("go-up-symbolic", "Monter", lambda i=i: self.move_message(i, -1), i > 0),
                    ("mail-send-symbolic", "Envoyer maintenant", lambda i=i: self.send_message_now(i), True),
                    ("edit-delete-symbolic", "Retirer", lambda i=i: self.remove_message(i), True)):
                b = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["flat"], sensitive=sensitive)
                b.connect("clicked", lambda *_a, h=handler: h())
                row.append(b)
            self.queue_rows.append(row)

    def set_queue(self, queue, added=False):
        if queue != self.state.queue:
            self.state.queue[:] = queue
            if added:
                self.state.queued_at = time.time()
            self.owner.queue_changed(self)

    def add_message(self):
        queue = terminal.queue_add(self.state.queue, self.queue_entry.get_text())
        if len(queue) > len(self.state.queue):
            self.queue_entry.set_text("")
            self.set_queue(queue, added=True)

    def edit_message(self, index, text, old):
        """Fin de modification d'une ligne ; ignorée si la file a changé entre-temps (message
        envoyé pendant la modification : la ligne ne désigne plus le même message)."""
        if 0 <= index < len(self.state.queue) and self.state.queue[index] == old:
            self.set_queue(terminal.queue_edit(self.state.queue, index, text))

    def move_message(self, index, delta):
        self.set_queue(terminal.queue_move(self.state.queue, index, delta))

    def remove_message(self, index):
        self.set_queue(terminal.queue_remove(self.state.queue, index))

    def send_message_now(self, index):
        """« Envoyer maintenant » : tout de suite, sauf pendant une demande de permission."""
        st = self.state
        if not 0 <= index < len(st.queue):
            return
        if st.state == "waiting" and not terminal.free_for_input(st):
            self.queue_status.set_label("Claude attend ta réponse : rien n'est envoyé.")
            return
        if self.send_auto(st.queue[index]):
            self.set_queue(terminal.queue_remove(st.queue, index))

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
        st.started_at = st.busy_since = st.typed_at = st.sent_at = st.state_since = None
        st.queued_at = st.limit_at = None  # file gardée : envoi après le prochain tour
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
        self.back_btn.set_visible(self.back is not None)
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
            self.owner.schedule_save()

    def on_window_title(self, *_):
        if self.state.kind == "shell":  # titre posé par le shell (dossier courant…)
            title = self.term.get_window_title()
            if title:
                self.page and self.page.set_tooltip(title)

    def on_contents(self, *_):
        if self.state.kind == "shell" and self.page and not self.owner.shown(self):
            self.attention()

    def attention(self):
        if self.page and not (self.owner.shown(self) and self.owner.on_screen()):
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
        if self.owner.is_split():
            self.owner.split_view.update(self)


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

    def __init__(self, window, overview=None):
        """`overview` : la page « Toutes les sessions » (SessionsPage), épinglée en première
        page de la barre d'onglets ; elle reste toujours là."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.overview = overview
        self.overview_page = None
        self.wants_attention = False
        self.seen = {}             # chats : dernier (état, depuis) vu, pour les alertes
        self.notifier = notify.send
        self.phoner = phone.send
        self.layout = self.saved_layout()
        self.available = vte() is not None
        self.menu_tab = None
        self.polling = False
        self.style = Adw.StyleManager.get_default()
        self.dark = self.style.get_dark()
        self.font = system_font()
        self.options = terminal_store.load_options()
        # Onglets de la dernière fois : gardés tant que la proposition n'a pas de réponse.
        self.pending, self.pending_selected, self.offering = None, None, False
        self.save_source, self.last_saved, self.closed = None, None, False
        if not self.available:
            if overview is not None:   # sans VTE : seulement la vue d'ensemble
                self.append(overview)
            return
        install_css()

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
        self.view.connect("page-reordered", lambda *_: self.schedule_save())
        tab_menu = Gio.Menu()
        tab_menu.append("Renommer la conversation…", "tabs.rename")
        tab_menu.append("Ouvrir le dossier", "tabs.folder")
        tab_menu.append_item(menu_item("Côte à côte", "tabs.split", SPLIT_ACCEL))
        tab_menu.append_item(menu_item("Revenir aux onglets", "tabs.unsplit", SPLIT_ACCEL))
        tab_menu.append_item(menu_item("Messages en attente…", "tabs.queue", QUEUE_ACCEL))
        tab_menu.append("Ouvrir cette conversation dans un terminal", "tabs.terminal")
        tab_menu.append("Fermer l'onglet", "tabs.close")
        self.view.set_menu_model(tab_menu)

        self.tab_actions = Gio.SimpleActionGroup()
        for name, handler in (("rename", self.rename_tab), ("folder", self.folder_of_tab),
                              ("split", self.split_with), ("queue", lambda tab: tab.toggle_queue()),
                              ("terminal", self.open_in_terminal), ("close", self.close)):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_a, h=handler: self.with_tab(h))
            self.tab_actions.add_action(a)
        unsplit = Gio.SimpleAction.new("unsplit", None)
        unsplit.connect("activate", lambda *_: (setattr(self, "menu_tab", None),
                                                self.unsplit(self.selected_tab())))
        self.tab_actions.add_action(unsplit)
        self.insert_action_group("tabs", self.tab_actions)
        keys = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        for accel, handler in ((SPLIT_ACCEL, self.toggle_split), (QUEUE_ACCEL, self.toggle_queue)):
            keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(accel),
                                           action=Gtk.CallbackAction.new(
                                               lambda *_a, h=handler: (h(), True)[1])))
        self.add_controller(keys)

        # Interrupteurs de la page (gardés dans terminals.json, pas dans les réglages généraux).
        self.page_actions = Gio.SimpleActionGroup()
        for name, key in (("auto-resume", "auto_resume"), ("reopen-at-start", "reopen_at_start")):
            a = Gio.SimpleAction.new_stateful(name, None, GLib.Variant.new_boolean(self.options[key]))
            a.connect("change-state", lambda act, value, k=key: self.set_option(act, k, value))
            self.page_actions.add_action(a)
        self.insert_action_group("terms", self.page_actions)
        options = Gio.Menu()
        options.append("Reprise automatique après une limite", "terms.auto-resume")
        options.append("Rouvrir les onglets au démarrage", "terms.reopen-at-start")
        page_menu = Gio.Menu()
        page_menu.append_section(None, tab_menu)
        page_menu.append_section(None, options)

        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=page_menu, css_classes=["flat"],
                              tooltip_text="Onglet et options")
        more.connect("notify::active", lambda b, _p: b.get_active() and self.prepare_menu(None))
        self.layout_btn = Gtk.Button(icon_name="view-dual-symbolic", css_classes=["flat"])
        self.layout_btn.connect("clicked", lambda *_: self.toggle_layout())
        self.update_layout_button()
        ends = Gtk.Box()
        ends.append(self.layout_btn)
        ends.append(more)
        self.bar = Adw.TabBar(view=self.view, autohide=False, end_action_widget=ends)

        # Bandeau « Rouvrir les N sessions de la dernière fois ? » et page vide qui l'accompagne.
        self.restore_label = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        ignore = Gtk.Button(label="Ignorer", valign=Gtk.Align.CENTER)
        ignore.connect("clicked", lambda *_: self.decline_restore())
        reopen = Gtk.Button(label="Rouvrir", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        reopen.connect("clicked", lambda *_: self.accept_restore())
        box = Gtk.Box(spacing=12, css_classes=["ccs-restore"])
        for w in (self.restore_label, ignore, reopen):
            box.append(w)
        self.restore_bar = Gtk.Revealer(child=box, reveal_child=False)
        self.empty = Adw.StatusPage(icon_name="document-open-recent-symbolic",
                                    title="Sessions de la dernière fois")

        self.split_view = SplitView(self.on_split_focus, lambda tab: self.unsplit(tab), self.close)
        self.content = Gtk.Stack(vexpand=True, hhomogeneous=False, vhomogeneous=False)
        self.content.add_named(self.view, "tabs")
        self.content.add_named(self.split_view, "split")
        self.content.add_named(self.empty, "empty")
        self.append(self.restore_bar)
        self.append(self.bar)
        self.append(self.content)

        if overview is not None:
            self.overview_page = self.view.append(overview)
            self.overview_page.set_title("Toutes les sessions")
            self.overview_page.set_icon(Gio.ThemedIcon.new("view-list-symbolic"))
            self.view.set_page_pinned(self.overview_page, True)
            self.view.set_selected_page(self.overview_page)
            self.update_content()
        window.connect("close-request", self.on_window_close)  # avant celui de la fenêtre
        window.connect("destroy", lambda *_: setattr(self, "closed", True))
        GLib.idle_add(self.startup)

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
        pages = (self.view.get_nth_page(i) for i in range(self.view.get_n_pages()))
        return [p.get_child() for p in pages if p.get_child() is not self.overview]

    def states(self):
        return [t.state for t in self.tabs()]

    def find(self, pid=None, session_id=None):
        state = terminal.find_tab(self.states(), pid=pid, session_id=session_id)
        return next((t for t in self.tabs() if t.state is state), None) if state else None

    def open_claude(self, cwd, resume=None, title=None, extra_args=()):
        """Nouvel onglet : un chat Claude Code dans `cwd` (`resume` : conversation à reprendre,
        `extra_args` : arguments de la nouvelle session avancée, traduits en options du chat
        par `chat_options.from_args`). Le processus ne démarre qu'au premier message."""
        _cls, chat_options = _chat_classes()
        return self.open_chat(cwd, resume, title, chat_options.from_args(tuple(extra_args or ())),
                              extra_args)

    def open_chat(self, cwd, resume=None, title=None, options=None, extra_args=(), present=True):
        """Onglet de chat (sans processus) dans un espace de session ; l'historique de la
        conversation `resume` est chargé depuis son journal. Une conversation qui tourne dans
        un autre terminal s'ouvre en lecture seule."""
        chat_cls, chat_options = _chat_classes()
        launch = terminal.claude_launch(cwd, resume, title, extra_args=tuple(extra_args or ()))
        history = None
        if resume:
            path = sessions.transcript_path(cwd, resume)
            history = path if path.exists() else None
        tab = chat_cls(self, launch, options if options is not None else chat_options.ChatOptions(),
                       history)
        tab.state.chat = True
        tab.elsewhere_pid = None
        self.install_workspace(tab)
        tab.page = self.view.append(tab)
        tab.update_page()
        self.update_content()
        if present:
            self.present(tab)
        self.changed(tab)
        if resume:
            in_thread(sessions.list_sessions, lambda live: self.check_elsewhere(tab, live))
        return tab

    def install_workspace(self, tab):
        """Le panneau du chat devient le centre d'un espace de session (arbre, éditeur,
        feuille de route) ; l'espace est le `panel` de l'onglet (la vue côte à côte l'emprunte)."""
        chat = tab.panel

        def ask():
            if not tab.send_auto(ASK_CREATE_TEXT):
                tab.state.queue[:] = terminal.queue_add(tab.state.queue, ASK_CREATE_TEXT)
                self.queue_changed(tab)
        workspace = SessionWorkspace(tab.state.cwd, chat, on_ask_create=ask, layout=self.layout)
        workspace.set_dark(self.dark)
        for name, handler in (("open-file", lambda _t, path, line=0: workspace.open_file(path, line or None)),
                              ("show-diff", lambda _t, path, old, new: workspace.show_diff(path, old, new))):
            if GObject.signal_lookup(name, type(tab)):
                tab.connect(name, handler)
        workspace.connect("insert-reference", lambda _w, rel: insert_reference(tab, rel))
        tab.remove(chat)
        tab.panel = workspace
        tab.append(workspace)

    # ---- disposition de l'espace de session --------------------------------------------

    def saved_layout(self):
        try:
            layout = settings.load_settings()["files"]["layout"]
        except Exception:  # noqa: BLE001 — réglages illisibles : disposition par défaut
            layout = "B"
        return layout if layout in ("A", "B") else "B"

    def workspaces(self):
        return [t.panel for t in self.tabs() if isinstance(t.panel, SessionWorkspace)]

    def set_layout(self, layout):
        """Disposition A (fichier au centre) ou B (fichier à droite) : tous les espaces,
        retenue dans les réglages (`files.layout`)."""
        if layout not in ("A", "B"):
            return
        self.layout = layout
        for ws in self.workspaces():
            ws.set_layout(layout)
        self.update_layout_button()
        try:
            current = settings.load_settings()
            if current["files"]["layout"] != layout:
                current["files"]["layout"] = layout
                settings.save_settings(current)
        except Exception:  # noqa: BLE001 — disposition appliquée même si elle n'est pas gardée
            pass

    def toggle_layout(self):
        self.set_layout("A" if self.layout == "B" else "B")

    def update_layout_button(self):
        btn = getattr(self, "layout_btn", None)
        if btn is not None:
            btn.set_tooltip_text("Disposition : fichier au centre, chat à droite" if self.layout == "B"
                                 else "Disposition : chat au centre, fichier à droite")

    def open_shell(self, cwd):
        return self.open(terminal.shell_launch(cwd))

    def open(self, launch, present=True):
        """Nouvel onglet pour un `terminal.Launch`, lancé et affiché (sauf `present=False`) ;
        renvoie le TerminalTab."""
        tab = TerminalTab(self, launch)
        tab.page = self.view.append(tab)
        tab.update_page()
        tab.spawn()
        self.update_content()
        if present:
            self.present(tab)
        self.changed(tab)
        return tab

    def present(self, tab):
        """Affiche l'onglet (page Terminaux, onglet choisi, focus clavier dans le terminal) ;
        hors de la vue côte à côte, celle-ci laisse la place aux onglets."""
        if tab.page is None:
            return  # onglet fermé depuis l'affichage du bouton
        if self.is_split() and not self.split_view.contains(tab):
            self.unsplit()
        self.window.show_terminals()
        self.view.set_selected_page(tab.page)
        tab.page.set_needs_attention(False)
        self.update_badge()
        tab.focus()

    def on_screen(self):
        return (self.window.stack.get_visible_child_name() == "sessions"
                and not self.overview_shown() and self.window.is_active())

    def on_selected(self, *_):
        page = self.view.get_selected_page()
        if self.is_split():
            if page is not None and self.split_view.contains(page.get_child()):
                self.split_view.set_active(page.get_child())
            else:
                self.unsplit()  # un autre onglet choisi dans la barre : retour aux onglets
        if page is not None and page.get_child() is not self.overview:
            page.set_needs_attention(False)
            page.get_child().focus()
        self.update_badge()
        self.schedule_save()
        on_page = getattr(self.window, "on_page", None)
        if on_page is not None:
            on_page()

    def focus_selected(self):
        page = self.view.get_selected_page() if self.available else None
        if page is not None and page.get_child() is not self.overview:
            page.set_needs_attention(False)
            page.get_child().focus()
        self.update_badge()

    def changed(self, tab=None):
        if tab is not None:
            tab.update_page()
        self.update_badge()
        if tab is not None and is_chat(tab):
            self.watch_chat(tab)
        self.update_actions()
        self.window.terminals_changed()
        self.schedule_save()
        if not self.polling and self.needs_poll():
            self.polling = True
            GLib.timeout_add_seconds(POLL_S, self.poll)

    def needs_poll(self):
        """Des sessions à suivre : un claude en marche, ou un chat en lecture seule qui attend
        la fin de l'autre processus."""
        return bool(terminal.running_claude(self.states())) or any(
            getattr(t, "elsewhere_pid", None) for t in self.tabs())

    def update_badge(self):
        """Le badge est celui de l'onglet Sessions de la fenêtre (`window.update_badge`) ;
        ici seulement : un onglet ou la proposition de réouverture demande-t-il de l'attention ?"""
        self.wants_attention = bool(self.offering or any(
            t.page.get_needs_attention() for t in self.tabs() if t.page))
        update = getattr(self.window, "update_badge", None)
        if update is not None:
            update()

    def overview_shown(self):
        """La page « Toutes les sessions » est la page affichée de la barre d'onglets."""
        if self.overview is not None and not self.available:
            return True
        if self.overview_page is None:
            return False
        return self.view.get_selected_page() is self.overview_page

    def show_overview(self):
        if self.overview_page is not None:
            self.view.set_selected_page(self.overview_page)

    def update_content(self):
        if self.available:
            self.content.set_visible_child_name(
                "split" if self.is_split() else "tabs" if self.view.get_n_pages() else "empty")

    # ---- côte à côte -----------------------------------------------------------------

    def is_split(self):
        return self.available and bool(self.split_view.halves)

    def shown(self, tab):
        """L'onglet est affiché dans la page (onglet choisi, ou moitié de la vue scindée)."""
        if self.is_split():
            return self.split_view.contains(tab)
        return tab.page is not None and tab.page.get_selected()

    def selected_tab(self):
        page = self.view.get_selected_page() if self.available else None
        return page.get_child() if page is not None and page.get_child() is not self.overview else None

    def split_with(self, tab):
        """Affiche `tab` à côté de l'onglet affiché (ou de son voisin s'il l'est déjà)."""
        tabs = self.tabs()
        if tab is None or tab.page is None or len(tabs) < 2:
            return
        if self.split_view.contains(tab):
            self.present(tab)
            return
        other = self.split_view.active if self.is_split() else self.selected_tab()
        if other is None or other is tab or other not in tabs:
            i = tabs.index(tab)
            other = tabs[i + 1] if i + 1 < len(tabs) else tabs[i - 1]
        left, right = sorted((tab, other), key=tabs.index)
        self.split_view.show(left, right)
        self.update_content()
        self.view.set_selected_page(tab.page)
        self.split_view.set_active(tab)
        tab.focus()
        self.update_actions()

    def unsplit(self, keep=None):
        """Retour à la vue par onglets (sur `keep` s'il est donné)."""
        if not self.is_split():
            return
        self.split_view.release()
        self.update_content()
        if keep is not None and keep.page is not None:
            self.view.set_selected_page(keep.page)
        tab = self.selected_tab()
        if tab is not None:
            tab.focus()
        self.update_actions()

    def toggle_split(self):
        if self.is_split():
            self.unsplit(self.selected_tab())
        else:
            self.split_with(self.selected_tab())

    def on_split_focus(self, tab):
        if tab.page is not None and self.view.get_selected_page() is not tab.page:
            self.view.set_selected_page(tab.page)
        self.split_view.set_active(tab)

    def reveal_page(self):
        """L'onglet Sessions est toujours visible : seul le badge est remis à jour."""
        self.update_badge()

    def on_detached(self, _view, page, _position):
        tab = page.get_child()
        tab.page = None
        if self.is_split() and self.split_view.contains(tab):
            self.unsplit()  # l'autre moitié revient dans son onglet
        if isinstance(tab.panel, SessionWorkspace):
            tab.panel.close()
        self.seen.pop(id(tab), None)
        self.emit("tab-closed", tab)
        self.update_badge()
        self.update_content()
        self.window.terminals_changed()
        self.schedule_save()
        if not self.tabs() and not self.offering and self.overview is None:
            self.window.hide_terminals()

    # ---- mémoire des onglets ---------------------------------------------------------

    def records(self):
        """(onglets à enregistrer, indice de celui affiché) ; ceux de la dernière fois restent
        tant que la proposition de les rouvrir n'a pas de réponse."""
        tabs = self.tabs()
        page = self.view.get_selected_page()
        current = [self.record_of(t) for t in tabs]
        selected = next((i for i, t in enumerate(tabs) if page is not None and t.page is page), None)
        if self.pending is not None:
            return terminal.merge_records(self.pending, self.pending_selected, current, selected)
        return current, selected

    def record_of(self, tab):
        if is_chat(tab):
            return terminal.tab_record(tab.state, chat=chat_record(getattr(tab, "options", None)))
        return terminal.tab_record(tab.state)

    def schedule_save(self):
        if self.available and not self.closed and self.save_source is None:
            self.save_source = GLib.timeout_add(SAVE_DELAY_MS, self.save_due)

    def save_due(self):
        self.save_source = None
        self.save_now()
        return False

    def save_now(self):
        if self.closed or not self.available:
            return
        data = self.records()
        if data != self.last_saved and terminal_store.save_tabs(*data):
            self.last_saved = data

    def flush_save(self):
        if self.save_source is not None:
            GLib.source_remove(self.save_source)
            self.save_source = None
        self.save_now()

    def on_window_close(self, *_):
        """Fermeture de la fenêtre : onglets enregistrés tels quels (avant l'arrêt des
        sessions), puis plus rien tant que la fermeture n'est pas annulée."""
        if self.available:
            self.flush_save()
            self.closed = True
            GLib.idle_add(self.close_cancelled)
        return False

    def close_cancelled(self):
        if self.window.get_visible():
            self.closed = False  # « Annuler » dans la confirmation de fermeture
        return False

    def startup(self):
        """Au lancement : onglets de la dernière fois rouverts (interrupteur) ou proposés."""
        records, selected = terminal_store.load_tabs()
        if records:
            self.pending, self.pending_selected = records, selected
            in_thread(lambda: self.plan(records, selected), self.offer)
        return False

    def plan(self, records, selected, present=()):
        return terminal.restore_plan(records, selected, opened=conversations.open_ids(), present=present)

    def offer(self, plan):
        if self.pending is None or not plan.tabs:
            return  # rien à rouvrir pour l'instant : proposé de nouveau au prochain lancement
        if self.options["reopen_at_start"]:
            self.reopen(plan, show=False)
            return
        self.offering = True
        question = terminal.restore_question(len(plan.tabs))
        self.restore_label.set_label(question)
        names = [t.title or sessions.project_name(t.cwd) if t.kind == "shell" else
                 f"{t.title or sessions.project_name(t.cwd)} — {sessions.project_name(t.cwd)}"
                 for t in plan.tabs]
        self.restore_label.set_tooltip_text("\n".join(names))
        self.empty.set_description(GLib.markup_escape_text("\n".join(names[:12])))
        self.restore_bar.set_reveal_child(True)
        self.update_content()
        self.reveal_page()
        toasts = getattr(self.window, "toasts", None)
        if toasts is not None:
            toast = Adw.Toast(title=GLib.markup_escape_text(question), button_label="Rouvrir", timeout=10)
            toast.connect("button-clicked", lambda *_: self.accept_restore())
            toasts.add_toast(toast)

    def accept_restore(self):
        if self.pending is None:
            return
        records, selected = self.pending, self.pending_selected
        present = {t.state.session_id for t in self.tabs() if t.state.session_id}
        self.end_offer()
        in_thread(lambda: self.plan(records, selected, present), lambda plan: self.reopen(plan, show=True))

    def decline_restore(self):
        self.end_offer()
        self.pending = None
        self.flush_save()
        if not self.tabs() and self.overview is None:
            self.window.hide_terminals()

    def end_offer(self):
        self.offering = False
        self.restore_bar.set_reveal_child(False)
        self.update_badge()

    def reopen(self, plan, show):
        """Rouvre les onglets du plan (sans voler l'affichage au démarrage si `show` est faux)."""
        opened = []
        for item in plan.tabs:
            if item.kind == "claude":  # onglets de la 0.9 et chats : un chat sans processus
                tab = self.open_chat(item.cwd, item.session_id, item.title or None,
                                     self.options_of(item), item.extra_args, present=False)
            else:
                tab = self.open(item.launch(), present=False)
            tab.state.queue[:] = list(item.queue)
            tab.refresh_queue()
            opened.append(tab)
        self.pending = None
        target = (opened[plan.selected] if plan.selected is not None else opened[0]) if opened else None
        if target is not None:
            self.view.set_selected_page(target.page)
            if show:
                self.present(target)
            else:
                self.reveal_page()
        elif not self.tabs() and self.overview is None:
            self.window.hide_terminals()
        self.update_content()
        self.window.toast(terminal.restore_summary(len(opened), plan.skipped))
        self.flush_save()

    def options_of(self, item):
        """ChatOptions d'un onglet rouvert : celles gardées (v2), complétées par les arguments
        de lancement d'un onglet de la 0.9 (--model, --permission-mode, --effort)."""
        _cls, chat_options = _chat_classes()
        base = chat_options.from_args(tuple(item.extra_args or ()))
        kept = item.chat or {}
        return chat_options.ChatOptions(
            model=kept.get("model") or base.model, effort=kept.get("effort") or base.effort,
            ultracode=bool(kept.get("ultracode")) or base.ultracode,
            rights=kept.get("rights") or base.rights)

    # ---- fermeture -----------------------------------------------------------------

    def close(self, tab):
        if tab.page is not None:
            self.view.close_page(tab.page)

    def on_close_page(self, view, page):
        tab = page.get_child()
        if tab is self.overview:
            view.close_page_finish(page, False)  # la vue d'ensemble reste toujours là
            return True
        if tab.state.kind == "shell":
            tab.state.busy = tab.foreground_busy()
        forced = getattr(tab, "skip_confirm", False)
        question = None if forced else terminal.tab_close_question(tab.state)
        if question is None and not forced and is_chat(tab) \
                and isinstance(tab.panel, SessionWorkspace) and tab.panel.has_unsaved():
            question = (f"Fermer « {tab.state.title} » ?", "Des fichiers modifiés ne sont pas enregistrés.")
        if question is None:
            if not forced:
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
        return page.get_child() if page is not None and page.get_child() is not self.overview else None

    def update_actions(self):
        if not self.available:
            return
        tab = self.menu_target()
        can_rename = bool(tab and tab.state.kind == "claude" and tab.state.session_id)
        self.tab_actions.lookup_action("rename").set_enabled(can_rename)
        for name in ("folder", "close"):
            self.tab_actions.lookup_action(name).set_enabled(tab is not None)
        split = self.is_split()
        self.tab_actions.lookup_action("split").set_enabled(
            tab is not None and len(self.tabs()) >= 2 and not (split and self.split_view.contains(tab)))
        self.tab_actions.lookup_action("unsplit").set_enabled(split)
        self.tab_actions.lookup_action("queue").set_enabled(bool(tab and tab.state.kind == "claude"))
        self.tab_actions.lookup_action("terminal").set_enabled(
            bool(tab and is_chat(tab) and tab.state.session_id))

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
        if not self.needs_poll():
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
            if is_chat(tab):
                self.watch_chat(tab)
        self.release_elsewhere(tabs, live)
        self.update_actions()
        if any(before[id(t.state)][0] != t.state.session_id for t in moved):
            self.window.terminals_changed()
        for tab in moved:
            self.emit("tab-state-changed", tab)
        blocked = self.handle_limits(tabs, limits)
        for tab in tabs:
            if tab.state.kind == "claude" and (tab.state.queue or tab.queue_reason):
                self.send_queue(tab, tab in blocked)
        self.schedule_save()
        wanted = [(t, t.state.cwd, t.state.session_id) for t in tabs
                  if t.state.kind == "claude" and t.state.session_id]
        if wanted:
            in_thread(lambda: [(t, sessions.conversation_title(cwd, sid)) for t, cwd, sid in wanted],
                      lambda found: [t.set_title(title) for t, title in found if title])

    def handle_limits(self, tabs, limits):
        """Reprise automatique : « continue » dans l'onglet dont la conversation a été bloquée
        par une limite, une fois le compte changé par le hook StopFailure."""
        now, blocked = time.time(), set()
        for tab in tabs:
            event = limits.get(tab.state.session_id) if tab.state.session_id else None
            decision = terminal.resume_decision(tab.state, event, now, enabled=self.options["auto_resume"])
            if decision is None:
                continue
            if decision.action == "wait":
                blocked.add(tab)  # limite en cours de traitement : la file attend aussi
                continue
            key = (event.session_id, event.ts)
            if key not in tab.limits_done:  # une seule fois par événement
                tab.limits_done.add(key)
                if decision.action == "resume" and tab.send_auto(terminal.RESUME_TEXT):
                    tab.state.resumes.append(now)
                elif decision.text:
                    tab.state.limit_at = event.ts  # pas relancée : la file attend un nouveau tour
                if decision.text:
                    tab.show_notice(decision.text)
                    tab.attention()
            limit_events.consume(event.session_id, event.ts)
        return blocked

    # ---- messages en attente ---------------------------------------------------------

    def queue_changed(self, tab):
        tab.refresh_queue()
        self.schedule_save()
        self.send_queue(tab)

    def send_queue(self, tab, blocked=False):
        """Envoie le premier message de la file si claude est libre (terminal.queue_next)."""
        if getattr(tab, "elsewhere_pid", None):  # conversation ouverte ailleurs : lecture seule
            tab.queue_reason = "Conversation ouverte ailleurs : rien n'est envoyé."
            tab.refresh_queue()
            return
        decision = terminal.queue_next(tab.state, time.time(), blocked)
        tab.queue_reason = decision.reason
        if decision.text is not None and tab.send_auto(decision.text):
            tab.state.queue[:] = tab.state.queue[1:]
            self.schedule_save()
        tab.refresh_queue()

    def toggle_queue(self):
        tab = self.selected_tab()
        if tab is not None and tab.state.kind == "claude":
            tab.toggle_queue()

    # ---- apparence -----------------------------------------------------------------

    def on_dark(self, *_):
        self.dark = self.style.get_dark()
        for tab in self.tabs():
            tab.apply_colors(self.dark)
            if isinstance(tab.panel, SessionWorkspace):
                tab.panel.set_dark(self.dark)

    def on_font(self, *_):
        self.font = system_font()
        for tab in self.tabs():
            if not is_chat(tab):
                tab.term.set_font(self.font)

    # ---- chats : conversation ouverte ailleurs ---------------------------------------

    def check_elsewhere(self, tab, live):
        """Une session Claude Code vivante, hors de nos onglets, tient déjà la conversation :
        le chat passe en lecture seule (deux processus la corrompraient)."""
        if tab.page is None or tab.state.running:
            return
        own = {t.state.pid for t in self.tabs() if t.state.pid}
        pid = terminal.elsewhere_pid(tab.state.session_id, live, own)
        if pid:
            self.set_read_only(tab, pid)
            self.changed(tab)

    def set_read_only(self, tab, pid):
        tab.elsewhere_pid = pid
        if isinstance(tab.panel, SessionWorkspace):
            tab.panel.set_notice(ELSEWHERE_TEXT)
        set_read_only(tab, True)

    def release_elsewhere(self, tabs, live):
        """La saisie se réactive quand l'autre processus a disparu."""
        alive = {s.pid for s in live}
        for tab in tabs:
            pid = getattr(tab, "elsewhere_pid", None)
            if pid and pid not in alive:
                tab.elsewhere_pid = None
                if isinstance(tab.panel, SessionWorkspace):
                    tab.panel.set_notice(None)
                set_read_only(tab, False)
                self.send_queue(tab)

    # ---- chats : alerte « attend ta réponse » (la mise en veille est faite par chaque ChatTab) ----

    def watch_chat(self, tab):
        """Suit l'état d'un chat (tenu par son moteur) : signal « tab-state-changed » et alerte
        quand il attend ta réponse sans être affiché."""
        st = tab.state
        key = (st.state, st.state_since)
        if self.seen.get(id(tab)) == key:
            return
        self.seen[id(tab)] = key
        if terminal.is_waiting_for_user(st) and not (self.shown(tab) and self.on_screen()):
            self.alert_waiting(tab)

    def alert_waiting(self, tab):
        """Alerte bureau et téléphone, une seule fois par attente, sauf « ne pas déranger »
        (`notify.send` et `phone.send` décident). Les fiches de session de Claude Code ne
        couvrent pas les processus `-p` d'un chat : CCS prévient lui-même."""
        key = terminal.waiting_alert_key(tab.state)
        if getattr(tab, "alerted", None) == key:
            return
        tab.alerted = key
        project = sessions.project_name(tab.state.cwd)
        alert = alerts.Alert(key=key, title=f"{project} attend ta réponse",
                             body=tab.state.title or project, urgency=1)
        try:
            cfg = settings.load_settings()
        except Exception:  # noqa: BLE001
            cfg = None
        try:
            self.phoner(alert, cfg, datetime.now(timezone.utc), project=project)
        except Exception:  # noqa: BLE001 — l'alerte ne doit jamais gêner l'interface
            pass
        in_thread(lambda: self.notifier(alert), lambda _r: None)

    # ---- sortie de secours : le terminal -----------------------------------------------

    def open_in_terminal(self, tab):
        """« Ouvrir cette conversation dans un terminal » : le chat s'arrête (après
        confirmation s'il travaille) et un terminal VTE reprend la conversation (`claude
        --resume`) sous le même compte ; « Revenir au chat » le rouvre."""
        if not is_chat(tab) or not tab.state.session_id:
            return
        if not terminal.needs_confirm(tab.state):
            self.finish_open_in_terminal(tab)
            return
        d = Adw.AlertDialog(heading=f"Ouvrir « {tab.state.title} » dans un terminal ?",
                            body="Claude travaille : le chat sera arrêté. "
                                 "La conversation est enregistrée et reprend dans le terminal.")
        d.add_response("cancel", "Annuler")
        d.add_response("open", "Arrêter et ouvrir")
        d.set_response_appearance("open", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "open" and self.finish_open_in_terminal(tab))
        d.present(self.window)

    def finish_open_in_terminal(self, tab):
        if tab.page is None:
            return
        state = tab.state
        back = {"cwd": state.cwd, "session_id": state.session_id, "title": state.title,
                "options": getattr(tab, "options", None)}
        position = self.view.get_page_position(tab.page)
        tab.hang_up()

        def open_terminal(tries=STOP_WAIT_TRIES):
            # laisser le chat finir d'écrire sa conversation avant de la rouvrir ailleurs
            if tab.state.running and tries > 0:
                GLib.timeout_add(100, lambda: (open_terminal(tries - 1), False)[1])
                return
            if tab.page is None:
                return
            tab.skip_confirm = True
            self.view.close_page(tab.page)
            term = self.open(terminal.claude_launch(back["cwd"], back["session_id"], back["title"]))
            term.back = back
            self.view.reorder_page(term.page, min(position, self.view.get_n_pages() - 1))
        open_terminal()

    def back_to_chat(self, term):
        """Le terminal de la conversation est fini : « Revenir au chat »."""
        back = term.back
        if back is None or term.page is None:
            return
        session_id = term.state.session_id or back["session_id"]
        position = self.view.get_page_position(term.page)
        term.skip_confirm = True
        self.view.close_page(term.page)
        tab = self.open_chat(back["cwd"], session_id, back["title"], back["options"])
        self.view.reorder_page(tab.page, min(position, self.view.get_n_pages() - 1))
