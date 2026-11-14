"""Onglet de chat : messages, zone de saisie et barre, reliés au moteur `chat_engine`.

Pour la page Terminaux, un `ChatTab` se présente comme un `TerminalTab` (même interface :
`state`, `panel`, `page`, `focus`, `hang_up`, `update_page`, `attention`, `refresh_queue`,
`toggle_queue`, `send_auto`, `show_notice`, `apply_colors`, `set_title`, `spawn`,
`foreground_busy`, `queue_reason`, `limits_done`) et tient à jour un `terminal.TabState` :
la file de messages, la reprise après une limite et les alertes marchent sans changement.

Signaux : `open-file(path, line)` et `show-diff(path, ancien, nouveau)`, pour l'espace de
session (panneau Fichiers).
"""

import dataclasses
import os
import re
import threading
import time

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from .. import chat_engine, chat_options, chat_protocol as proto, context_alert, preview, sessions, settings  # noqa: E402
from .. import terminal  # noqa: E402
from ..chat_options import ChatOptions  # noqa: E402
from .chat_bar import ChatBar  # noqa: E402
from .chat_composer import Composer  # noqa: E402
from .chat_messages import MessageList, TodosBar, tool_label  # noqa: E402
from .common import in_thread  # noqa: E402

SUSPEND_CHECK_S = 60
FILE_SCAN_MAX = 20_000
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build", "target", "site-packages"}
LINK_LINE = re.compile(r"^(?P<path>.*?)(?::(?P<line>\d+)(?::\d+)?|#L(?P<hl>\d+))?$")
NOT_STARTED = ("stopped", "suspended")


def scan_files(root, limit=FILE_SCAN_MAX):
    """Fichiers du projet (chemins relatifs), sans dossiers cachés ni dépendances."""
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(names):
            if not name.startswith("."):
                out.append(os.path.relpath(os.path.join(base, name), root))
                if len(out) >= limit:
                    return out
    return out


class _NoTerm:
    """Ce que la page Terminaux attend d'un `tab.term` (changement de police du bureau) : rien."""

    def set_font(self, _font):
        pass


AGENT_TOOLS = ("Task", "Agent")   # outils qui lancent un sous-agent


JOURNAL_TAIL = 2 * 1024 * 1024   # fin du journal relue pour les avis de fin des sous-agents de fond


class _Agent:
    """Un sous-agent lancé par Claude dans ce chat : sa pastille et sa vue."""

    def __init__(self, name, messages, view, pill, spinner, icon, background=False):
        self.name, self.messages, self.view, self.pill = name, messages, view, pill
        self.spinner, self.icon = spinner, icon
        self.background = background
        self.done = False
        self.card = None


class ChatTab(Gtk.Box):
    """Un chat (voir le docstring du module)."""

    __gsignals__ = {
        "open-file": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),
        "show-diff": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str)),
        # une action de Claude (nom de l'outil, entrée) : l'espace de session suit le projet
        "tool-used": (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
    }

    def __init__(self, owner, launch, options=None, history_path=None, claude=None, environ=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.owner = owner
        self.launch = launch
        self.options = options if options is not None else chat_options.from_args(launch.extra_args)
        self.state = terminal.TabState("claude", launch.cwd, launch.title, launch.session_id,
                                       extra_args=launch.extra_args)
        self.page = None
        self.limits_done = set()
        self.queue_reason = None
        self.term = _NoTerm()
        self._turn_done = False
        self._pending = None        # (texte, images) envoyé, sans tour terminé : rendu si le démarrage échoue
        self._error_notice = None
        self._closed = False
        self._files = None
        self._thinking = False

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.messages = MessageList(on_diff=lambda p, o, n: self.emit("show-diff", p, o, n),
                                    on_open=lambda p, line: self.emit("open-file", p, line),
                                    on_link=self.open_link, base_dir=launch.cwd)
        self.composer = Composer(base_dir=launch.cwd)
        self.bar = ChatBar()
        self.bar.set_options(self.options)
        self.messages_overlay = Gtk.Overlay(child=self.messages, vexpand=True)
        self.messages_overlay.add_overlay(self.messages.new_button)   # « ↓ Nouveaux messages »
        # Sous-agents : une pastille par sous-agent au-dessus du fil, chacun sa vue (comme VS Code).
        self.agents = {}                                              # tool_use_id -> _Agent
        self._turn_started, self._cost_seen = None, 0.0               # bilan de chaque tour
        self.view_stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.view_stack.add_named(self.messages_overlay, "principale")
        self.agent_pills = Gtk.Box(spacing=6)
        self.main_pill = Gtk.ToggleButton(label="Conversation principale", active=True,
                                          css_classes=["pill", "small"])
        self.main_pill.connect("toggled", lambda b: b.get_active() and self.show_agent(None))
        self.agent_pills.append(self.main_pill)
        self.agent_bar = Gtk.ScrolledWindow(child=self.agent_pills, visible=False, margin_start=12,
                                            margin_end=12, margin_top=6, vscrollbar_policy=Gtk.PolicyType.NEVER,
                                            propagate_natural_height=True)
        self.todos_bar = TodosBar()           # liste de tâches épinglée au-dessus de la saisie
        for w in (self.agent_bar, self.view_stack, self.todos_bar, self.composer, self.bar):
            self.panel.append(w)
        self.append(self.panel)

        self.composer.set_file_source(self._file_source)
        self.composer.connect("send", self._on_send)
        self.composer.connect("cycle-rights", lambda *_: self.bar.cycle_rights())
        self.composer.connect("stop", lambda *_: self.stop_turn())
        self.composer.connect("queue-edit", lambda _c, i, text, old: self.edit_message(i, text, old))
        self.composer.connect("queue-move", lambda _c, i, d: self.move_message(i, d))
        self.composer.connect("queue-remove", lambda _c, i: self.remove_message(i))
        self.composer.connect("queue-send-now", lambda _c, i: self.send_message_now(i))
        self.bar.connect("changed", self._on_options)

        self.engine = chat_engine.ChatSession(
            launch.cwd, launch.session_id, self.options,
            on_event=lambda ev: GLib.idle_add(self._dispatch, ev), claude=claude, environ=environ)
        self._load_history(history_path)
        GLib.timeout_add_seconds(SUSPEND_CHECK_S, self._tick)

    # ---- historique ----------------------------------------------------------------------

    def _load_history(self, history_path):
        path = history_path
        if path is None and self.state.session_id:
            path = sessions.transcript_path(self.state.cwd, self.state.session_id)
        if path is None or not os.path.exists(path):
            return

        def read():
            try:
                return preview.read_messages(path)
            except (OSError, ValueError):
                return []

        def show(messages):
            if messages and not self._closed:
                self.messages.load_history(messages)
        in_thread(read, show)

    # ---- interface attendue par TerminalsPage --------------------------------------------

    def spawn(self, launch=None):
        """« Lance » l'onglet : le chat est prêt, mais `claude` ne démarre qu'au premier envoi."""
        if launch is not None:
            self.launch = launch
            if launch.session_id and launch.session_id != self.engine.session_id:
                self.engine.session_id = launch.session_id
                self.state.session_id = launch.session_id
        st = self.state
        st.exit_status, st.state, st.waiting_for = None, "idle", None
        st.running = True
        st.busy_since = st.typed_at = st.sent_at = st.queued_at = st.limit_at = None
        st.state_since = time.time()
        self._turn_done = False
        self._dismiss_error()
        self.composer.set_enabled(True)
        self.owner.changed(self)
        self.owner.emit("tab-started", self)

    def relaunch(self):
        """Après une erreur de démarrage : le message qui n'est pas parti revient dans la zone
        de saisie, le prochain envoi relance `claude` (`--resume`)."""
        self.spawn()
        self.focus()

    def focus(self):
        self.composer.focus()

    def foreground_busy(self):
        return False

    def hang_up(self):
        """Ferme le chat : `claude` s'arrête (stdin fermé, puis SIGTERM, puis SIGKILL), la
        conversation est déjà enregistrée par Claude Code."""
        self._closed = True
        engine = self.engine
        threading.Thread(target=engine.stop, daemon=True).start()

    def suspend_if_idle(self, idle_s):
        """Met `claude` en veille s'il est resté au repos `idle_s` secondes."""
        return self.engine.suspend_if_idle(time.time(), idle_s)

    def _tick(self):
        if self._closed:
            return False
        try:
            minutes = int(settings.load_settings().get("chat", {}).get("idle_suspend_min", 0))
        except (TypeError, ValueError, AttributeError):
            minutes = 0
        if minutes > 0 and self.engine.suspend_if_idle(time.time(), minutes * 60):
            self.state.pid = None
        return True

    def apply_colors(self, dark):
        self.messages.set_dark(dark)
        self.composer.set_dark(dark)

    def set_account(self, name, color, usage=None):
        """Compte et couleur montrés à droite de la barre."""
        self.bar.set_account(name, color, usage)

    def show_notice(self, text):
        self.messages.add_notice(text, "info")
        self.attention()

    def set_title(self, title):
        if title and title != self.state.title:
            self.state.title = title
            self.update_page()
            self.owner.schedule_save()

    def attention(self):
        if self.page and not (self.owner.shown(self) and self.owner.on_screen()):
            self.page.set_needs_attention(True)
            self.owner.update_badge()

    def update_page(self):
        if self.page is None:
            return
        self.page.set_title(self.state.title)
        where = sessions.project_name(self.state.cwd)
        self.page.set_tooltip("\n".join([self.state.title, f"{where} · {self.state.cwd}"]))
        loading, icon, tooltip = terminal.indicator(self.state)
        self.page.set_loading(loading)
        self.page.set_indicator_icon(Gio.ThemedIcon.new(icon) if icon else None)
        self.page.set_indicator_tooltip(tooltip or "")
        if self.owner.is_split():
            self.owner.split_view.update(self)

    # ---- envoi ---------------------------------------------------------------------------

    def _engine_busy(self):
        return self.engine.state in ("busy", "permission", "starting")

    def _on_send(self, _composer, text, images):
        """Entrée dans la zone de saisie : envoi tout de suite, même pendant que Claude travaille
        (la CLI le lit en cours de route ou juste après ; la page n'a rien à mettre en file)."""
        self.state.typed_at = time.time()
        if not self._send(text, images):
            self.composer.restore(text, images)

    def _send(self, text, images=()):
        """Envoie au moteur et montre la bulle ; faux si Claude ne démarre pas. Pendant un tour,
        le message part aussi tout de suite (bulle marquée « envoyé pendant que Claude travaille »)."""
        during = self._engine_busy()
        self.todos_bar.new_turn()
        if not during and not self.state.running:
            self.spawn()
        if not self.engine.send(text, images):
            if not self._engine_busy():
                self._start_failed("Claude Code n'a pas pu démarrer.")
            return False
        self.messages.add_user(text, images, during=during)
        if during:
            return True
        self._turn_started = time.time()
        self._pending = (text, list(images))
        self._turn_done = False
        self._on_state(chat_engine.StateChanged("busy"))   # tout de suite : la page lit cet état
        return True

    def send_auto(self, text):
        """Envoi décidé par l'application (reprise après une limite, file de messages, « créer
        une feuille de route »). Un chat sans processus — c'est le cas de tout chat ouvert ou
        rouvert par la page Sessions — le lance comme un envoi au clavier (`_send`) ; seule une
        conversation ouverte ailleurs (lecture seule) refuse."""
        if getattr(self, "elsewhere_pid", None):
            return False
        if not self._send(text):
            return False
        self.state.sent_at = time.time()
        return True

    def stop_turn(self):
        """Bouton Arrêter (Échap) : interrompt le tour ; la CLI s'arrête puis repart au message suivant."""
        if self._engine_busy():
            self.engine.interrupt()

    # ---- options -------------------------------------------------------------------------

    def _on_options(self, _bar, options):
        old = self.options
        self.options = options
        self.engine.set_options(options)
        what = []
        if options.model != old.model:
            what.append("Modèle changé")
        if options.effort != old.effort or options.ultracode != old.ultracode:
            what.append("Effort changé")
        if options.rights != old.rights:
            what.append("Droits changés")
        if what:
            self.messages.add_notice(" · ".join(what) + " : pris en compte au prochain message.")
        self.owner.schedule_save()

    # ---- file de messages (même gestion que TerminalTab) ----------------------------------

    def refresh_queue(self):
        self.composer.set_queue(self.state.queue, self.queue_reason)

    def toggle_queue(self, show=None):
        self.composer.toggle_queue(show)

    def set_queue(self, queue, added=False):
        if queue != self.state.queue:
            self.state.queue[:] = queue
            if added:
                self.state.queued_at = time.time()
            self.owner.queue_changed(self)
        self.refresh_queue()

    def edit_message(self, index, text, old):
        if 0 <= index < len(self.state.queue) and self.state.queue[index] == old:
            self.set_queue(terminal.queue_edit(self.state.queue, index, text))

    def move_message(self, index, delta):
        self.set_queue(terminal.queue_move(self.state.queue, index, delta))

    def remove_message(self, index):
        self.set_queue(terminal.queue_remove(self.state.queue, index))

    def send_message_now(self, index):
        st = self.state
        if not 0 <= index < len(st.queue):
            return
        if self.send_auto(st.queue[index]):   # même pendant un tour : la CLI le lit
            self.set_queue(terminal.queue_remove(st.queue, index))
        else:   # jamais en silence : le bandeau de la file dit pourquoi rien n'est parti
            self.queue_reason = ("Conversation ouverte ailleurs : rien n'est envoyé."
                                 if getattr(self, "elsewhere_pid", None)
                                 else "Envoi impossible : Claude Code n'a pas démarré.")
            self.refresh_queue()

    # ---- événements du moteur ------------------------------------------------------------

    def _dispatch(self, ev):
        """Un événement du moteur (déjà ramené dans la boucle GTK)."""
        parent = getattr(ev, "parent_id", None)
        if parent and parent in getattr(self, "agents", {}):
            self._agent_event(self.agents[parent], ev)
            return False
        if isinstance(ev, proto.ToolResult) and ev.tool_id in getattr(self, "agents", {}):
            self._agent_done(ev.tool_id)
        if isinstance(ev, proto.TaskNotice):
            if ev.tool_id in getattr(self, "agents", {}):
                self._agent_done(ev.tool_id, notice=True)
            return False
        if self._closed and not isinstance(ev, (chat_engine.StateChanged, chat_engine.ProcessExited)):
            return False
        handler = {
            chat_engine.StateChanged: self._on_state,
            chat_engine.ProcessExited: self._on_exited,
            chat_engine.ContextUsage: self._on_context,
            chat_engine.OptionRefused: self._on_option_refused,
            chat_engine.UnhandledRequest: lambda e: self.messages.add_notice(
                f"Claude Code a posé une question que CCS ne sait pas encore afficher ({e.subtype}"
                + (f" — {e.summary}" if e.summary else "") + ") : réponse « non pris en charge », "
                "pour qu'il ne reste pas bloqué.", "warning"),
            proto.Status: self._on_status,
            proto.Init: self._on_init,
            proto.Hello: self._on_hello,
            proto.TextDelta: lambda e: self._text(e, delta=True),
            proto.AssistantText: lambda e: self._text(e, delta=False),
            proto.Thinking: self._on_thinking,
            proto.ToolUse: self._on_tool,
            proto.ToolResult: lambda e: self.messages.set_tool_result(e),
            proto.Todos: lambda e: self.todos_bar.update(e.items),
            proto.PermissionRequest: self._on_permission,
            proto.TurnResult: self._on_result,
            proto.LocalCommand: self._on_local,
            proto.Compacted: lambda e: self.messages.add_notice(
                f"Conversation compactée ({e.pre_tokens:,} jetons avant).".replace(",", " ")),
            proto.Retrying: lambda e: self.messages.set_busy(
                True, f"Nouvelle tentative (essai {e.attempt}, dans {e.delay_s:.0f} s)…"),
        }.get(type(ev))
        if handler is not None:
            handler(ev)
        return False

    def _on_state(self, ev):
        st, now = self.state, time.time()
        previous = st.state
        waiting_for = None
        if ev.state in ("busy", "starting"):
            new = "busy"
        elif ev.state == "permission":
            new, waiting_for = "waiting", "permission"
        elif ev.state == "idle" and self._turn_done:
            new, waiting_for = "waiting", "input"  # fin de réponse : Claude attend la suite
        else:
            new = "idle"
        if new == "busy" and previous != "busy":
            st.busy_since = now
        if new != previous or st.state_since is None:
            st.state_since = now
        st.state, st.waiting_for = new, waiting_for
        st.pid, st.started_at = self.engine.pid, self.engine.started_at or st.started_at
        busy = new == "busy"
        self.composer.set_busy(busy or waiting_for == "permission")
        if not busy:
            self._thinking = False
        self.messages.set_busy(busy, "Claude travaille…")
        if new == "waiting":
            self.attention()
        self.owner.changed(self)
        self.owner.emit("tab-state-changed", self)

    def _on_init(self, ev):
        if ev.session_id and ev.session_id != self.state.session_id:
            self.state.session_id = ev.session_id
            self.owner.changed(self)

    def _on_status(self, ev):
        """Mode de droits réellement en vigueur, confirmé par la CLI : la barre le reflète."""
        mode = "manual" if ev.permission_mode in (None, "default") else ev.permission_mode
        if mode != self.options.rights:
            self.options = dataclasses.replace(self.options, rights=mode)
            self.bar.set_options(self.options)
            self.owner.schedule_save()

    def _on_option_refused(self, ev):
        what = "Les droits" if ev.what == "set_permission_mode" else "Le modèle"
        self.messages.add_notice(f"{what} : Claude Code a refusé le changement en direct ; il sera "
                                 "appliqué en relançant la conversation au prochain message.", "warning")

    def _on_hello(self, ev):
        self.composer.set_commands(ev.commands)
        try:
            models = chat_options.merge_hello(ev) or chat_options.MODELS
        except (TypeError, ValueError, AttributeError):
            models = chat_options.MODELS
        self.bar.set_choices(models, chat_options.efforts_for, chat_options.ultracode_possible)

    def _text(self, ev, delta):
        if delta:
            self.messages.append_delta(ev.msg_id, ev.text)
        else:
            self.messages.finish_assistant(ev.msg_id, ev.text)

    def _on_thinking(self, _ev):
        self._thinking = True
        self.messages.set_busy(True, "Claude réfléchit…")

    def _on_tool(self, ev):
        if ev.name in proto.TODO_TOOLS:
            return  # la liste de tâches a sa propre carte (événement Todos)
        card = self.messages.add_tool(ev)
        self.messages.set_busy(True, f"{tool_label(ev.name)}…")
        self.emit("tool-used", ev.name, dict(ev.input or {}))
        if ev.name in AGENT_TOOLS and not ev.parent_id:
            self._new_agent(ev, card)

    # ---- sous-agents ----------------------------------------------------------------------

    def _new_agent(self, ev, card):
        """Un sous-agent démarre : sa pastille, sa vue (fil en lecture seule), et « Voir » sur sa carte."""
        data = ev.input or {}
        name = str(data.get("description") or data.get("subagent_type") or "Sous-agent")[:60]
        messages = MessageList(on_diff=lambda p, o, n: self.emit("show-diff", p, o, n),
                               on_open=lambda p, line: self.emit("open-file", p, line),
                               on_link=self.open_link, base_dir=self.launch.cwd)
        view = Gtk.Overlay(child=messages, vexpand=True)
        view.add_overlay(messages.new_button)
        pill_box = Gtk.Box(spacing=6)
        spinner = Gtk.Spinner(spinning=True)
        icon = Gtk.Image(icon_name="emblem-ok-symbolic", visible=False)
        pill_box.append(spinner)
        pill_box.append(icon)
        pill_box.append(Gtk.Label(label=name, ellipsize=Pango.EllipsizeMode.END, max_width_chars=28))
        pill = Gtk.ToggleButton(child=pill_box, group=self.main_pill, css_classes=["pill", "small"],
                                tooltip_text=f"Sous-agent : {name}")
        agent = _Agent(name, messages, view, pill, spinner, icon,
                       background=bool(data.get("run_in_background")))
        self.agents[ev.tool_id] = agent
        self.view_stack.add_named(view, ev.tool_id)
        pill.connect("toggled", lambda b, tid=ev.tool_id: b.get_active() and self.show_agent(tid))
        self.agent_pills.append(pill)
        self.agent_bar.set_visible(True)
        agent.card = card
        if card is not None:
            see = Gtk.Button(label="Voir le sous-agent", halign=Gtk.Align.START, css_classes=["flat"])
            see.connect("clicked", lambda *_b, tid=ev.tool_id: self.show_agent(tid))
            card.append(see)

    def show_agent(self, tool_id):
        """Affiche la vue d'un sous-agent, ou la conversation principale (`None`)."""
        agent = self.agents.get(tool_id) if tool_id else None
        if agent is None:
            self.view_stack.set_visible_child(self.messages_overlay)
            if not self.main_pill.get_active():
                self.main_pill.set_active(True)
            self._tidy_pills()
            return
        agent.pill.set_visible(True)          # un sous-agent fini se rouvre depuis sa carte
        self.agent_bar.set_visible(True)
        self.view_stack.set_visible_child(agent.view)
        if not agent.pill.get_active():
            agent.pill.set_active(True)
        self._tidy_pills()

    def _tidy_pills(self):
        """Comme VS Code : un sous-agent fini quitte la barre (sa carte dans le fil garde « Voir
        le sous-agent ») ; il n'y reste que ceux qui travaillent et celui qu'on regarde. La barre
        disparaît quand il ne reste que la conversation principale."""
        shown = self.view_stack.get_visible_child()
        left = False
        for agent in self.agents.values():
            keep = not agent.done or agent.view is shown
            agent.pill.set_visible(keep)
            left = left or keep
        self.agent_bar.set_visible(left)

    def _agent_event(self, agent, ev):
        """Événement émis par un sous-agent : dans sa vue, pas dans le fil principal."""
        if isinstance(ev, proto.ToolUse):
            if ev.name not in proto.TODO_TOOLS:
                agent.messages.add_tool(ev)
            self.emit("tool-used", ev.name, dict(ev.input or {}))
        elif isinstance(ev, proto.ToolResult):
            agent.messages.set_tool_result(ev)
        elif isinstance(ev, proto.AssistantText):
            agent.messages.finish_assistant(ev.msg_id, ev.text)

    def _agent_done(self, tool_id, notice=False):
        """Fin d'un sous-agent : son résultat (premier plan) ou son avis de fin (arrière-plan, qui
        rend la main tout de suite : son résultat immédiat ne compte pas)."""
        agent = self.agents.get(tool_id)
        if agent is None or agent.done or (agent.background and not notice):
            return
        agent.done = True
        agent.spinner.set_spinning(False)
        agent.spinner.set_visible(False)
        agent.icon.set_visible(True)
        if agent.background and agent.card is not None:
            agent.card.append(Gtk.Label(label="✓ Sous-agent terminé", xalign=0,
                                        css_classes=["caption", "dim-label"]))
        self._tidy_pills()

    def _permission_key(self, key):
        card = self.messages.pending_permission()
        done = card is not None and card.answer_key(key)
        self._sync_permission_keys()
        return done

    def _sync_permission_keys(self):
        """1, 2, 3 répondent dans la saisie tant qu'une autorisation attend (comme VS Code)."""
        card = self.messages.pending_permission()
        question = card is not None and card.req.tool_name == proto.QUESTION_TOOL and hasattr(card, "answers")
        self.composer.set_permission_keys(self._permission_key if card is not None else None,
                                          question=question)

    def _on_permission(self, ev):
        self.messages.add_permission(ev, self._answer, on_questions=self._answer_questions)
        self._sync_permission_keys()
        self.messages.set_busy(False)
        self.attention()

    def _answer_questions(self, request_id, answers):
        self.engine.answer_questions(request_id, answers)
        GLib.idle_add(lambda: (self._sync_permission_keys(), False)[1])

    def _answer(self, request_id, decision, message=""):
        self.engine.answer(request_id, decision, message)
        GLib.idle_add(lambda: (self._sync_permission_keys(), False)[1])

    def _on_local(self, ev):
        if ev.text and ev.text.strip():
            self.messages.add_notice(ev.text.strip())

    def _check_background(self):
        """Filet : si la CLI ne redonne pas l'avis de fin d'un sous-agent de fond dans son flux,
        il est de toute façon écrit dans le journal de la conversation. Relu à chaque fin de tour
        (fin du fichier seulement, dans un fil)."""
        waiting = [tid for tid, a in self.agents.items() if a.background and not a.done]
        session_id = self.engine.session_id or self.state.session_id
        if not waiting or not session_id:
            return
        path = sessions.transcript_path(self.state.cwd, session_id)

        def read():
            try:
                with open(path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - JOURNAL_TAIL))
                    return proto.journal_notices(f.read())
            except (OSError, TypeError):
                return []

        def apply(notices):
            if self._closed:
                return
            for n in notices:
                if n.tool_id in waiting:
                    self.engine.background_finished(n.tool_id)
                    self._agent_done(n.tool_id, notice=True)
        in_thread(read, apply)

    def _on_result(self, ev):
        self._turn_done = True
        self._check_background()
        self._pending = None
        # bilan du tour : durée et coût de CE tour (la CLI donne un total cumulé sur la session)
        total = ev.cost_usd if isinstance(ev.cost_usd, (int, float)) else None
        turn_cost = (total - self._cost_seen) if total is not None and total >= self._cost_seen else total
        if total is not None:
            self._cost_seen = total
        if ev.ok and not ev.interrupted and self._turn_started is not None:
            self.messages.add_turn_footer(time.time() - self._turn_started, turn_cost)
        self._turn_started = None
        if ev.interrupted:
            self.messages.add_notice("Arrêté.")
        elif getattr(ev, "is_limit", False):
            self.messages.add_notice("Limite d'usage atteinte : " + (ev.text or "attends la fin de la période "
                                     "ou change de compte."), "warning")
        elif not ev.ok:
            self.messages.add_notice(ev.text or "Claude n'a pas pu finir sa réponse.", "error")
        self.messages.cancel_permissions()
        self._sync_permission_keys()
        self.engine.request_context()

    def _on_context(self, ev):
        threshold = context_alert.config(settings.load_settings())["threshold_tokens"]
        pct = threshold * 100 / ev.maximum if ev.maximum else None
        self.bar.set_context(ev.percentage, pct)

    def _on_exited(self, ev):
        self.state.pid = None
        if ev.requested or ev.code == 0:
            return
        text = "Claude Code s'est arrêté" + (f" (code {ev.code})" if ev.code is not None else "") + "."
        tail = (ev.stderr_tail or "").strip()
        self._start_failed(text + (f"\n{tail}" if tail else ""))

    def _start_failed(self, text):
        """Erreur de démarrage ou arrêt inattendu : encart avec la fin de stderr et « Relancer »."""
        self.state.running = False
        self.state.state, self.state.waiting_for = None, None
        self.state.exit_status = 1
        self.messages.set_busy(False)
        self.messages.cancel_permissions()
        self._sync_permission_keys()
        self._dismiss_error()
        self._error_notice = self.messages.add_notice(text, "error", action=("Relancer", self.relaunch))
        if self._pending and not self.composer.text.strip():
            self.composer.restore(*self._pending)
        self._pending = None
        self.composer.set_busy(False)
        self.attention()
        self.owner.changed(self)
        self.owner.emit("tab-exited", self, 1)

    def _dismiss_error(self):
        if self._error_notice is not None and self._error_notice.get_parent() is not None:
            self._error_notice.set_visible(False)
        self._error_notice = None

    # ---- liens et fichiers ---------------------------------------------------------------

    def open_link(self, uri):
        """Lien d'un message : adresse web dans le navigateur, fichier du projet dans le panneau."""
        if re.match(r"^(https?|mailto):", uri):
            Gtk.UriLauncher(uri=uri).launch(self.get_root(), None, None)
            return
        if uri.startswith("file://"):
            uri = Gio.File.new_for_uri(uri).get_path() or uri
        m = LINK_LINE.match(uri)
        path, line = m.group("path"), int(m.group("line") or m.group("hl") or 0)
        full = path if path.startswith("/") else os.path.join(self.state.cwd, path)
        if os.path.isfile(full):
            self.emit("open-file", full, line)

    def _file_source(self):
        """Fichiers proposés après `@` : listés une fois en arrière-plan (la liste du panneau
        Fichiers la remplace par `composer.set_file_source`)."""
        if self._files is None:
            self._files = []
            root = self.state.cwd

            def done(files):
                self._files = files
                if not self._closed:
                    self.composer._update_completion()
            in_thread(lambda: scan_files(root), done)
        return self._files

    def set_file_source(self, source):
        self.composer.set_file_source(source)
