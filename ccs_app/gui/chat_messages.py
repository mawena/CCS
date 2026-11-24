"""Liste des messages du chat : bulles, texte de Claude en Markdown, cartes d'outils,
demandes d'autorisation, liste de tâches.

Rien ici ne parle à `claude` : `ChatTab` y verse les événements du moteur. Les événements
sont lus par leurs champs (`ToolUse.name`, `.input`…), les formes sont celles de
`ccs_app.chat_protocol`.
"""

import difflib
import json
import os
import time

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk, Pango  # noqa: E402

from .. import chat_protocol as proto, chat_quote, message_tags, preview, token_use, voice  # noqa: E402
from ..conversations import fold  # noqa: E402
from .markdown_view import MarkdownView  # noqa: E402

PAGE = 50                   # messages d'historique construits à la fois
LIVE_MAX = 300              # longue session : au-delà, les plus anciennes lignes du fil sont retirées…
LIVE_KEEP = 200             # … pour n'en garder que celles-ci (mémoire bornée ; relues du journal à la demande)
RENDER_MS = 90              # un rendu Markdown au plus toutes les 90 ms pendant le flux…
RENDER_MAX_MS = 1000        # … espacé si le rendu coûte (4 × sa durée), sans dépasser 1 s
RESULT_CHARS = 20_000       # résultat d'outil montré (le reste est coupé à l'affichage)
FOLD_LINES = 14             # un message de l'utilisateur plus long est replié (« Afficher tout »)
FOLD_CHARS = 1500
STICK_PX = 48               # à moins de 48 px du bas, la liste suit le texte qui arrive
TAG_FLASH_MS = 1600         # message retrouvé depuis le volet Étiquettes : mis en évidence
TAG_SUGGESTIONS = 12        # étiquettes proposées dans la fenêtre « Étiqueter »
QUOTE_LINES = 4             # lignes montrées d'un message cité dans une bulle (un clic déplie)
QUOTE_CHARS = 320
MAX_WIDTH = 920

TOOL_LABELS = {"Read": "Lecture", "Edit": "Modification", "MultiEdit": "Modifications",
               "Write": "Écriture", "Bash": "Commande", "Grep": "Recherche", "Glob": "Fichiers",
               "Task": "Sous-agent", "Agent": "Sous-agent", "WebFetch": "Page web",
               "WebSearch": "Recherche web", "NotebookEdit": "Notebook", "LS": "Dossier",
               "TodoWrite": "Tâches"}
TOOL_ICONS = {"Read": "text-x-generic-symbolic", "Edit": "document-edit-symbolic",
              "MultiEdit": "document-edit-symbolic", "Write": "document-new-symbolic",
              "Bash": "utilities-terminal-symbolic", "Grep": "system-search-symbolic",
              "Glob": "system-search-symbolic", "Task": "avatar-default-symbolic",
              "Agent": "avatar-default-symbolic", "WebFetch": "web-browser-symbolic",
              "WebSearch": "web-browser-symbolic", "NotebookEdit": "document-edit-symbolic",
              "LS": "folder-symbolic"}
EDIT_TOOLS = ("Edit", "MultiEdit", "Write")
AGENT_TOOLS = ("Task", "Agent")   # leur carte reste seule (pastille et « Voir le sous-agent »)
# catégories du résumé d'un groupe : (clé, singulier, pluriel), dans cet ordre
GROUP_KINDS = (("read", "lecture", "lectures"), ("edit", "modification", "modifications"),
               ("run", "commande", "commandes"), ("search", "recherche", "recherches"),
               ("web", "page web", "pages web"), ("other", "autre", "autres"))
KIND_OF = {"Read": "read", "Edit": "edit", "MultiEdit": "edit", "Write": "edit", "NotebookEdit": "edit",
           "Bash": "run", "Grep": "search", "Glob": "search", "LS": "search",
           "WebFetch": "web", "WebSearch": "web"}
FILE_TOOLS = ("Read", "Edit", "MultiEdit", "Write", "NotebookEdit")

CSS = """
.ccs-find-hit { background-color: alpha(@warning_bg_color, 0.22); }
.ccs-find-current { background-color: alpha(@warning_bg_color, 0.55); }
.ccs-chat-notice { padding: 6px 12px; border-radius: 10px; font-size: 0.92em;
  background-color: alpha(@window_fg_color, 0.06); }
.ccs-chat-notice.error { background-color: alpha(@error_bg_color, 0.16); }
.ccs-chat-notice.warning { background-color: alpha(@warning_bg_color, 0.20); }
.ccs-code-box { background-color: alpha(@window_fg_color, 0.07); border-radius: 8px;
  padding: 6px 10px; font-family: monospace; font-size: 0.92em; }
.ccs-code-box.command { font-weight: 600; font-size: 1.0em; padding: 8px 12px; }
.ccs-tool-head { padding: 2px 0; min-height: 0; }
.ccs-tool-card .ccs-tool-name { font-weight: 700; }
.ccs-diff-add { color: @success_color; font-weight: 700; font-feature-settings: "tnum"; }
.ccs-diff-del { color: @error_color; font-weight: 700; font-feature-settings: "tnum"; }
.ccs-tool-group { background-color: alpha(@window_fg_color, 0.035); border-radius: 10px;
  padding: 2px 6px; }
.ccs-tool-group.error { background-color: alpha(@error_bg_color, 0.10); }
.ccs-tool-group .ccs-group-title { font-size: 0.92em; }
.ccs-tool-group.error .ccs-group-title, .ccs-tool-group.error .ccs-group-icon { color: @error_color; }
.ccs-tool-group .ccs-group-count { font-size: 0.85em; }
.ccs-todo-done label { text-decoration: line-through; opacity: 0.6; }
.ccs-todo-now label { font-weight: 700; }
.ccs-busy-row { padding: 4px 6px; }
.ccs-composer { background-color: @card_bg_color; border-radius: 14px;
  box-shadow: 0 0 0 1px alpha(@window_fg_color, 0.14); padding: 6px 8px; }
.ccs-composer.drop { box-shadow: 0 0 0 2px @accent_bg_color; }
.ccs-composer textview, .ccs-composer textview text { background: transparent; }
.ccs-copy { min-width: 28px; min-height: 28px; margin: 2px; transition: opacity 120ms; }
.ccs-hover-actions { transition: opacity 120ms; }
.ccs-tag { font-size: 0.82em; padding: 1px 9px; border-radius: 99px;
  background-color: alpha(@accent_bg_color, 0.18); }
.ccs-tag-flash { background-color: alpha(@warning_bg_color, 0.55); transition: background-color 300ms; }
.ccs-quoted { border-left: 3px solid @accent_color; border-radius: 6px; padding: 4px 10px;
  background-color: alpha(@window_fg_color, 0.07); }
.ccs-quote-author { font-weight: 700; font-size: 0.88em; color: @accent_color; }
.ccs-quoted .ccs-quote-text { font-size: 0.92em; }
.ccs-quote-bar { border-left: 3px solid @accent_color; border-radius: 8px; padding: 2px 2px 2px 10px;
  background-color: alpha(@window_fg_color, 0.05); }
.ccs-thumb { border-radius: 8px; }
.ccs-chat-bar button.ccs-barbtn { padding: 2px 10px; min-height: 0; border-radius: 99px; font-size: 0.92em; }
.ccs-chat-bar button.ccs-barbtn:checked { background-color: alpha(@warning_bg_color, 0.30);
  color: @window_fg_color; }
.ccs-chat-bar { padding: 2px 4px; }
.ccs-queue-row { padding: 1px 0; }
"""

_css = False


def install_css():
    """Styles du chat (une fois par affichage)."""
    global _css
    display = Gdk.Display.get_default()
    if _css or display is None:
        return
    _css = True
    provider = Gtk.CssProvider()
    if hasattr(provider, "load_from_string"):
        provider.load_from_string(CSS)
    else:
        provider.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_display(display, provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)


# ---- lecture des appels d'outils -----------------------------------------------------------

def _duration(seconds):
    """42 s, 2 min 05 s, 1 h 03 min."""
    s = int(round(seconds or 0))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {(s % 3600) // 60:02d} min"


def _fold(text, max_lines=FOLD_LINES, max_chars=FOLD_CHARS):
    """Les `max_lines` premières lignes (et au plus `max_chars` caractères) suivies de « … »,
    ou le texte tel quel s'il est court."""
    lines = text.split("\n")
    short = "\n".join(lines[:max_lines])
    if len(short) > max_chars:
        short = short[:max_chars].rstrip()
    return text if short == text else short.rstrip() + " …"


def _first_line(text, limit=160):
    for line in str(text).splitlines():
        if line.strip():
            line = line.strip()
            return line if len(line) <= limit else line[:limit - 1] + "…"
    return ""


def tool_target(name, data, base_dir=None):
    """Ce sur quoi porte l'outil, en une ligne : fichier (relatif au projet), commande,
    motif, adresse…"""
    data = data if isinstance(data, dict) else {}
    for key in ("file_path", "notebook_path", "path"):
        if isinstance(data.get(key), str) and data[key]:
            return relative(data[key], base_dir)
    for key in ("command", "pattern", "url", "query", "description", "prompt"):
        if isinstance(data.get(key), str) and data[key].strip():
            return _first_line(data[key])
    for value in data.values():
        if isinstance(value, str) and value.strip():
            return _first_line(value)
    return ""


def relative(path, base_dir):
    if base_dir and path.startswith(str(base_dir).rstrip("/") + "/"):
        return os.path.relpath(path, base_dir)
    return path


def _counts(old, new):
    plus = minus = 0
    a, b = old.splitlines(), new.splitlines()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            minus += i2 - i1
        if tag in ("replace", "insert"):
            plus += j2 - j1
    return plus, minus


def edit_info(name, data):
    """(chemin, ancien texte, nouveau texte, +n, −m) d'une modification de fichier, ou None."""
    if name not in EDIT_TOOLS or not isinstance(data, dict):
        return None
    path = data.get("file_path")
    if not isinstance(path, str) or not path:
        return None
    if name == "Write":
        new = str(data.get("content", ""))
        return path, "", new, len(new.splitlines()), 0
    if name == "Edit":
        old, new = str(data.get("old_string", "")), str(data.get("new_string", ""))
    else:
        edits = [e for e in data.get("edits") or () if isinstance(e, dict)]
        old = "\n".join(str(e.get("old_string", "")) for e in edits)
        new = "\n".join(str(e.get("new_string", "")) for e in edits)
    plus, minus = _counts(old, new)
    return path, old, new, plus, minus


def tool_label(name):
    if name in TOOL_LABELS:
        return TOOL_LABELS[name]
    if name.startswith("mcp__"):
        return " · ".join(p for p in name.split("__")[1:] if p) or name
    return name


SPEAKER = voice.Speaker()          # une seule lecture à voix haute à la fois, tous chats confondus


def read_aloud(bubble):
    """« Lire » une réponse de Claude ; sur celle qu'on lit déjà : arrêter."""
    if bubble is None:
        return
    if SPEAKER.key is bubble and SPEAKER.speaking():
        SPEAKER.stop()
        return
    button = getattr(bubble, "speak_button", None)

    def mark(on):
        if button is not None:
            button.set_icon_name("media-playback-stop-symbolic" if on else "audio-speakers-symbolic")
            button.set_tooltip_text("Arrêter la lecture" if on else "Lire à voix haute")
    if SPEAKER.speak(getattr(bubble, "copy_text", "") or "", key=bubble,
                     on_end=lambda: GLib.idle_add(lambda: (mark(False), False)[1])):
        mark(True)


def _clear(box):
    while (child := box.get_first_child()) is not None:
        box.remove(child)


def _cut(text, limit=RESULT_CHARS):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} caractères de plus)"


# ---- widgets -------------------------------------------------------------------------------

RESET_TEXT = "Nouvelle conversation — Claude ne voit plus les messages au-dessus"
RESET_AUTO_TEXT = "Sujet terminé : Claude a effacé la conversation — il ne voit plus les messages au-dessus"

class ToolCard(Gtk.Box):
    """Carte repliable d'une action de Claude : icône (roue tant qu'elle tourne), nom, cible,
    `+n −m` pour une modification ; le détail montre la commande et le résultat.

    Le clic sur l'en-tête fait l'action principale (diff d'une modification, ouverture d'un
    fichier lu, sinon déplier) ; la flèche déplie toujours."""

    def __init__(self, name, target="", data=None, on_diff=None, on_open=None, nested=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["ccs-tool-card"])
        self.name, self.target, self.data = name, target, data or {}
        self.on_diff, self.on_open = on_diff, on_open
        self.edit = edit_info(name, self.data)
        self.running = True
        self.group = None
        self.result_text = None
        if nested:
            self.set_margin_start(24)

        self.icon = Gtk.Image(icon_name=TOOL_ICONS.get(name, "emblem-system-symbolic"))
        self.spinner = Gtk.Spinner(spinning=True)
        self.stack = Gtk.Stack()
        self.stack.add_named(self.icon, "icon")
        self.stack.add_named(self.spinner, "spin")
        self.stack.set_visible_child_name("spin")

        head = Gtk.Box(spacing=8)
        head.append(self.stack)
        head.append(Gtk.Label(label=tool_label(name), css_classes=["ccs-tool-name"]))
        head.append(Gtk.Label(label=target, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE,
                              css_classes=["ccs-subtle"], tooltip_text=target or None))
        if self.edit:
            _p, _o, _n, plus, minus = self.edit
            self.counts = Gtk.Box(spacing=6)
            self.counts.append(Gtk.Label(label=f"+{plus}", css_classes=["ccs-diff-add"]))
            self.counts.append(Gtk.Label(label=f"−{minus}", css_classes=["ccs-diff-del"]))
            head.append(self.counts)
        self.main = Gtk.Button(child=head, css_classes=["flat", "ccs-tool-head"], hexpand=True)
        self.main.connect("clicked", self._on_main)
        self.chevron = Gtk.Button(icon_name="pan-end-symbolic", css_classes=["flat", "circular"],
                                  valign=Gtk.Align.CENTER, tooltip_text="Détail")
        self.chevron.connect("clicked", lambda *_: self.toggle())
        top = Gtk.Box(spacing=2)
        top.append(self.main)
        top.append(self.chevron)
        self.append(top)

        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=4, margin_end=4,
                              margin_bottom=4)
        self.revealer = Gtk.Revealer(child=self.detail, reveal_child=False,
                                     transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.append(self.revealer)
        self._detail_built = False     # commande et résultat : construits au premier dépliage

    # -- états --

    def _fill_detail(self):
        """Commande et résultat (texte sélectionnable, coûteux en mémoire) : seulement quand la
        carte est dépliée ; la plupart ne le sont jamais."""
        if not self.revealer.get_reveal_child():
            self._detail_built = False
            return
        self._detail_built = True
        _clear(self.detail)
        command = self.data.get("command") if self.name == "Bash" else None
        if isinstance(command, str) and command:
            self.detail.append(self._code("$ " + command))
        elif self.edit:
            self.detail.append(Gtk.Label(label="Clique sur la ligne pour voir le diff dans le panneau du fichier.",
                                         xalign=0, css_classes=["ccs-subtle"], wrap=True))
        if self.result_text:
            self.detail.append(self._result(self.result_text))
        elif self.running and not self.detail.get_first_child():
            self.detail.append(Gtk.Label(label="En cours…", xalign=0, css_classes=["ccs-subtle"]))

    @staticmethod
    def _code(text):
        return Gtk.Label(label=_cut(text, 4000), xalign=0, selectable=True, wrap=True,
                         wrap_mode=Pango.WrapMode.WORD_CHAR, css_classes=["ccs-code-box", "command"])

    @staticmethod
    def _result(text):
        label = Gtk.Label(label=_cut(text), xalign=0, yalign=0, selectable=True, wrap=True,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, css_classes=["ccs-code-box"])
        scroll = Gtk.ScrolledWindow(child=label, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    propagate_natural_height=True, max_content_height=260)
        return scroll

    def set_result(self, text, is_error=False):
        self.running = False
        self.result_text = (text or "").strip() or None
        self.stack.set_visible_child_name("icon")
        self.spinner.set_spinning(False)
        self.icon.set_from_icon_name("dialog-error-symbolic" if is_error else "object-select-symbolic")
        self.add_css_class("error" if is_error else "done")
        if is_error:
            self.revealer.set_reveal_child(True)
            self.chevron.set_icon_name("pan-down-symbolic")
        self._fill_detail()

    def toggle(self, show=None):
        show = (not self.revealer.get_reveal_child()) if show is None else show
        self.revealer.set_reveal_child(show)
        self.chevron.set_icon_name("pan-down-symbolic" if show else "pan-end-symbolic")
        if show and not self._detail_built:
            self._fill_detail()

    def _on_main(self, *_):
        if self.edit and self.on_diff:
            path, old, new, _p, _m = self.edit
            self.on_diff(path, old, new)
        elif self.name in ("Read", "NotebookEdit") and self.on_open and self.data.get("file_path"):
            self.on_open(self.data["file_path"], 0)
        else:
            self.toggle()


class ToolGroup(Gtk.Box):
    """Des actions de Claude qui s'enchaînent, en un bloc discret.

    En-tête : roue, action en cours et compte tant que ça travaille ; puis coche et résumé
    (« 5 actions · 3 lectures, 1 modification (+12 −3), 1 commande »). Une erreur est
    signalée dans l'en-tête (icône et couleur d'erreur, « 1 erreur »). Replié, il se déplie
    d'un clic et montre les cartes, inchangées ; il se replie seul à la fin du travail, sauf
    si on l'a ouvert ou fermé à la main."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["ccs-tool-group"])
        self.cards = []
        self.touched = False
        self.running = True

        self.icon = Gtk.Image(icon_name="object-select-symbolic", css_classes=["ccs-group-icon"])
        self.spinner = Gtk.Spinner(spinning=True)
        self.stack = Gtk.Stack()
        self.stack.add_named(self.icon, "icon")
        self.stack.add_named(self.spinner, "spin")
        self.stack.set_visible_child_name("spin")
        self.title = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                               css_classes=["ccs-group-title", "ccs-subtle"])
        self.count = Gtk.Label(css_classes=["ccs-group-count", "ccs-subtle"])
        self.chevron = Gtk.Image(icon_name="pan-end-symbolic")
        self.header = Gtk.Box(spacing=8)
        for w in (self.stack, self.title, self.count, self.chevron):
            self.header.append(w)
        self.main = Gtk.Button(child=self.header, css_classes=["flat", "ccs-tool-head"], hexpand=True)
        self.main.connect("clicked", self._on_click)
        self.append(self.main)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=6, margin_bottom=4)
        self.revealer = Gtk.Revealer(child=self.body, reveal_child=False,
                                     transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.append(self.revealer)

    def add(self, card):
        self.cards.append(card)
        card.group = self
        self.body.append(card)
        self.refresh()

    def _on_click(self, *_):
        self.touched = True
        self.toggle()

    def toggle(self, show=None):
        show = (not self.revealer.get_reveal_child()) if show is None else show
        self.revealer.set_reveal_child(show)
        self.chevron.set_from_icon_name("pan-down-symbolic" if show else "pan-end-symbolic")

    @staticmethod
    def _noun(n, one, many):
        return f"{n} {one if n == 1 else many}"

    def summary(self):
        """« 5 actions · 3 lectures, 1 modification (+12 −3), 1 commande »."""
        plus = sum(c.edit[3] for c in self.cards if c.edit)
        minus = sum(c.edit[4] for c in self.cards if c.edit)
        parts = []
        for kind, one, many in GROUP_KINDS:
            n = sum(1 for c in self.cards if KIND_OF.get(c.name, "other") == kind)
            if n:
                text = self._noun(n, one, many)
                if kind == "edit" and any(c.edit for c in self.cards):
                    text += f" (+{plus} −{minus})"
                parts.append(text)
        return f"{len(self.cards)} actions · " + ", ".join(parts)

    def refresh(self):
        errors = sum(1 for c in self.cards if c.has_css_class("error"))
        err_text = f" · {self._noun(errors, 'erreur', 'erreurs')}" if errors else ""
        running = [c for c in self.cards if c.running]
        was = self.running
        self.running = bool(running)
        self.count.set_visible(self.running)
        if self.running:
            card = running[-1]
            verb = tool_label(card.name)
            if card.name in FILE_TOOLS and card.target:
                what = f"{verb} de {card.target}"
            else:
                what = f"{verb} : {card.target}" if card.target else f"{verb}…"
            self.title.set_label(what)
            self.title.set_tooltip_text(what)
            self.count.set_label(f"{len(self.cards)} actions{err_text}")
            self.stack.set_visible_child_name("spin")
            self.spinner.set_spinning(True)
        else:
            text = self.summary() + err_text
            self.title.set_label(text)
            self.title.set_tooltip_text(text)
            self.spinner.set_spinning(False)
            self.stack.set_visible_child_name("icon")
            self.icon.set_from_icon_name("dialog-error-symbolic" if errors else "object-select-symbolic")
            if was and not self.touched:
                self.toggle(False)
        if errors:
            self.add_css_class("error")
        else:
            self.remove_css_class("error")


class PermissionCard(Gtk.Box):
    """Demande d'autorisation : la commande en évidence, puis Autoriser / Toujours / Refuser
    (motif facultatif pour le refus)."""

    def __init__(self, req, on_answer, base_dir=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["ccs-permission-card"])
        self.req, self.on_answer = req, on_answer
        name = getattr(req, "display_name", "") or req.tool_name
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Image(icon_name="dialog-password-symbolic"))
        who = "Un sous-agent de Claude" if getattr(req, "agent_id", None) else "Claude"
        head.append(Gtk.Label(label=f"{who} demande l'autorisation : {name}", xalign=0, hexpand=True,
                              wrap=True, css_classes=["heading"]))
        self.append(head)
        desc = getattr(req, "description", "") or ""
        if desc:
            self.append(Gtk.Label(label=desc, xalign=0, wrap=True, css_classes=["ccs-subtle"]))
        self.append(Gtk.Label(label=_cut(self._shown(req, base_dir), 4000), xalign=0, selectable=True,
                              wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                              css_classes=["ccs-code-box", "command"]))
        blocked = getattr(req, "blocked_path", None)
        if blocked:
            self.append(Gtk.Label(label=f"Chemin concerné : {blocked}", xalign=0, wrap=True,
                                  css_classes=["ccs-subtle"]))

        self.reason = Gtk.Entry(placeholder_text="Motif du refus (facultatif)", hexpand=True)
        self.allow = Gtk.Button(label="Autoriser", css_classes=["suggested-action"])
        self.allow.connect("clicked", lambda *_: self._answer("allow"))
        rules = [s for s in (getattr(req, "suggestions", None) or ())
                 if isinstance(s, dict) and s.get("type") == "addRules"]
        self.always = Gtk.Button(label="Toujours pour cette commande",
                                 tooltip_text="Autorise cette commande exacte pour la suite, dans les "
                                 "réglages du projet (pas les commandes voisines). Pour ne plus être "
                                 "interrompu, choisis « Modifications acceptées » ou « Tout autoriser » "
                                 "dans la barre du chat.", visible=bool(rules))
        self.always.connect("clicked", lambda *_: self._answer("always"))
        self.deny = Gtk.Button(label="Refuser", css_classes=["destructive-action"])
        self.deny.connect("clicked", lambda *_: self._answer("deny"))
        self.reason.connect("activate", lambda *_: self._answer("deny"))
        row = Gtk.Box(spacing=8)
        for w in (self.allow, self.always, self.reason, self.deny):
            row.append(w)
        self.buttons = row
        self.append(row)
        keys = "1 Autoriser · " + ("2 Toujours · " if rules else "") + "3 Refuser"
        self.keys_hint = Gtk.Label(label=f"Au clavier, la saisie vide : {keys}", xalign=0,
                                   css_classes=["caption", "dim-label"])
        self.append(self.keys_hint)
        self.verdict = Gtk.Label(xalign=0, css_classes=["heading"], visible=False)
        self.append(self.verdict)

    KEY_DECISIONS = {"1": "allow", "2": "always", "3": "deny"}

    def answer_key(self, key):
        """Réponse au clavier (1, 2, 3, comme l'extension VS Code). Vrai si la touche a servi."""
        decision = self.KEY_DECISIONS.get(key)
        if decision is None or self.answered or (decision == "always" and not self.always.get_visible()):
            return False
        self._answer(decision)
        return True

    @staticmethod
    def _shown(req, base_dir):
        data = req.input if isinstance(req.input, dict) else {}
        if isinstance(data.get("command"), str):
            return data["command"]
        for key in ("file_path", "path", "url", "pattern", "query"):
            if isinstance(data.get(key), str):
                return relative(data[key], base_dir)
        try:
            return json.dumps(data, ensure_ascii=False, indent=1)
        except (TypeError, ValueError):
            return str(data)

    def _answer(self, decision):
        if self.answered:
            return
        self.resolve(decision)
        self.on_answer(self.req.request_id, decision, self.reason.get_text().strip() if decision == "deny" else "")

    @property
    def answered(self):
        return self.verdict.get_visible()

    def resolve(self, decision):
        """Fige la carte : l'autorisation a reçu sa réponse."""
        self.buttons.set_visible(False)
        self.keys_hint.set_visible(False)
        self.verdict.set_label({"allow": "Autorisé", "always": "Autorisé, et toujours pour cette règle",
                                "deny": "Refusé", "cancelled": "Annulée"}.get(decision, decision))
        self.verdict.add_css_class("success" if decision in ("allow", "always") else "error")
        self.verdict.set_visible(True)


class QuestionCard(Gtk.Box):
    """Questions à choix de Claude (outil AskUserQuestion) : pour chacune, ses choix (un seul,
    ou plusieurs si `multiSelect`) et « Autre » en texte libre ; « Envoyer les réponses » les
    rend à Claude, « Répondre dans le chat » les écarte."""

    OTHER = "Autre…"

    def __init__(self, req, on_submit, on_skip):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["ccs-permission-card"])
        self.req, self.on_submit, self.on_skip = req, on_submit, on_skip
        self.items = proto.question_items(req.input)
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Image(icon_name="dialog-question-symbolic"))
        n = len(self.items)
        head.append(Gtk.Label(label="Claude te pose une question" if n == 1 else f"Claude te pose {n} questions",
                              xalign=0, hexpand=True, css_classes=["heading"]))
        self.append(head)
        self.choices = []     # par question : (texte, [(bouton, libellé)], bouton « Autre », champ libre)
        for text, header, options, multi in self.items:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            if header:
                box.append(Gtk.Label(label=header, xalign=0, css_classes=["caption", "dim-label"]))
            box.append(Gtk.Label(label=text, xalign=0, wrap=True, css_classes=["ccs-question"]))
            group, buttons = None, []
            for n_opt, (label, desc) in enumerate(options, 1):
                btn = Gtk.CheckButton(label=f"{n_opt}. {label}", group=None if multi else group)
                if not multi and group is None:
                    group = btn
                child = btn.get_last_child()
                if isinstance(child, Gtk.Label):
                    child.set_wrap(True)
                if desc:
                    btn.set_tooltip_text(desc)
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                row.append(btn)
                if desc:
                    row.append(Gtk.Label(label=desc, xalign=0, wrap=True, margin_start=28,
                                         css_classes=["caption", "dim-label"]))
                box.append(row)
                buttons.append((btn, label))
                btn.connect("toggled", lambda *_: self._update())
            other = Gtk.CheckButton(label=self.OTHER, group=None if multi else group)
            entry = Gtk.Entry(placeholder_text="Ta réponse", hexpand=True, margin_start=28)
            entry.connect("changed", lambda e, o=other: (e.get_text().strip() and o.set_active(True), self._update()))
            entry.connect("activate", lambda *_: self._submit())
            other.connect("toggled", lambda *_: self._update())
            box.append(other)
            box.append(entry)
            self.choices.append((text, buttons, other, entry))
            self.append(box)
        self.send = Gtk.Button(label="Envoyer les réponses", css_classes=["suggested-action"], sensitive=False)
        self.send.connect("clicked", lambda *_: self._submit())
        self.skip = Gtk.Button(label="Répondre dans le chat",
                               tooltip_text="Écarte les questions : Claude attend ta réponse écrite")
        self.skip.connect("clicked", lambda *_: self._skip())
        self.buttons = Gtk.Box(spacing=8)
        self.buttons.append(self.send)
        self.buttons.append(self.skip)
        self.append(self.buttons)
        self.verdict = Gtk.Label(xalign=0, wrap=True, css_classes=["heading"], visible=False)
        self.append(self.verdict)

    def answers(self):
        """{texte de la question: libellé, [libellés] ou texte libre} des questions répondues."""
        out = {}
        for (text, buttons, other, entry), (_t, _h, _o, multi) in zip(self.choices, self.items):
            picked = [label for btn, label in buttons if btn.get_active()]
            free = entry.get_text().strip()
            if other.get_active() and free:
                picked.append(free)
            if picked:
                out[text] = picked if multi and len(picked) > 1 else picked[0]
        return out

    def _update(self):
        self.send.set_sensitive(bool(self.answers()) and not self.answered)

    def _submit(self):
        answers = self.answers()
        if not answers or self.answered:
            return
        self._close("Réponses envoyées : " + " · ".join(
            v if isinstance(v, str) else ", ".join(v) for v in answers.values()), True)
        self.on_submit(self.req.request_id, answers)

    def _skip(self):
        if self.answered:
            return
        self._close("Questions écartées : réponds dans le chat.", False)
        self.on_skip(self.req.request_id)

    def _close(self, text, ok):
        for _text, buttons, other, entry in self.choices:
            for btn, _l in buttons:
                btn.set_sensitive(False)
            other.set_sensitive(False)
            entry.set_sensitive(False)
        self.buttons.set_visible(False)
        self.verdict.set_label(text)
        self.verdict.add_css_class("success" if ok else "dim-label")
        self.verdict.set_visible(True)

    @property
    def answered(self):
        return self.verdict.get_visible()

    def resolve(self, decision):
        if not self.answered:
            self._close("Questions annulées.", False)

    def answer_key(self, key):
        """1, 2, 3… choisissent dans la première question à choix unique sans réponse ; si
        toutes ont une réponse, la touche envoie."""
        if self.answered or not key.isdigit():
            return False
        for (text, buttons, other, entry), (_t, _h, _o, multi) in zip(self.choices, self.items):
            if multi or any(btn.get_active() for btn, _l in buttons) or other.get_active():
                continue
            n = int(key)
            if 1 <= n <= len(buttons):
                buttons[n - 1][0].set_active(True)
                if all(q in self.answers() for q, *_rest in self.choices):
                    self._submit()
                return True
            return False
        return False


class TodosCard(Gtk.Box):
    """Liste de tâches de Claude, en cases à cocher mises à jour."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["ccs-card", "flat"])
        self.title = Gtk.Label(xalign=0, css_classes=["ccs-card-title"])
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.append(self.title)
        self.append(self.rows)

    def update(self, items):
        _clear(self.rows)
        done = 0
        for text, status in items:
            check = Gtk.CheckButton(label=text, active=status == "completed", can_target=False,
                                    focusable=False)
            child = check.get_last_child()
            if isinstance(child, Gtk.Label):
                child.set_wrap(True)
            if status == "completed":
                done += 1
                check.add_css_class("ccs-todo-done")
            row = Gtk.Box(spacing=8)
            row.append(check)
            if status == "in_progress":
                check.add_css_class("ccs-todo-now")
                row.append(Gtk.Spinner(spinning=True))
            self.rows.append(row)
        self.title.set_label(f"Tâches · {done}/{len(items)}")


class TodosBar(Gtk.Box):
    """Liste de tâches de Claude épinglée au-dessus de la saisie (comme l'extension VS Code) :
    l'en-tête dit où en est Claude (« Tâches 2/5 · Écrire les tests »), un clic déplie la liste.
    Elle reste visible tant que la liste n'est pas finie ; finie, elle s'efface au message
    suivant."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["ccs-todos-bar"],
                         visible=False, margin_start=12, margin_end=12, margin_top=4)
        self.card = TodosCard()
        self.card.remove_css_class("ccs-card")
        self.card.title.set_visible(False)
        head = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        self.summary = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        head.append(self.spinner)
        head.append(self.summary)
        self.expander = Gtk.Expander(label_widget=head, child=self.card)
        self.append(self.expander)
        self.done = False

    def update(self, items):
        items = list(items or ())
        self.card.update(items)
        total = len(items)
        done = sum(1 for _t, s in items if s == "completed")
        current = next((t for t, s in items if s == "in_progress"), None)
        self.done = total > 0 and done == total
        if self.done:
            text = f"✓ Tâches terminées · {done}/{total}"
        elif current:
            text = f"Tâches {done}/{total} · {' '.join(current.split())}"
        else:
            text = f"Tâches {done}/{total}"
        self.summary.set_label(text)
        self.spinner.set_visible(current is not None and not self.done)
        self.spinner.set_spinning(current is not None and not self.done)
        self.set_visible(total > 0)

    def new_turn(self):
        """Un nouveau message part : une liste finie n'a plus à rester épinglée."""
        if self.done:
            self.set_visible(False)


def give_back_memory():
    """Rend au système la mémoire libérée (glibc garde sinon les pages libérées pour lui) :
    après un élagage du fil, la fenêtre redescend vraiment."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass
    return False


def release(widget):
    """Libère un sous-arbre retiré du fil. Un gestionnaire de signal qui pointe vers son widget
    ou un parent (`self.toggle`…) forme un cycle Python ↔ GTK que ni l'un ni l'autre ne libère :
    on « dispose » chaque widget et contrôleur, du haut vers le bas, ce qui détruit leurs
    gestionnaires et casse ces cycles."""
    order, stack = [], [widget]
    while stack:
        w = stack.pop()
        order.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    for w in order:                   # parents d'abord : ils détachent leurs enfants
        controllers = w.observe_controllers()
        for ctrl in [controllers.get_item(i) for i in range(controllers.get_n_items())]:
            ctrl.run_dispose()
        w.run_dispose()


def _show_actions(controller, *args):
    """Survol d'un message : montre ou cache ses boutons (« Répondre », « Copier ») ; l'opacité
    est le dernier argument."""
    actions = getattr(controller.get_widget(), "hover_actions", None)
    if actions is not None:
        actions.set_opacity(args[-1])


def _owner(widget, attr="copy_text"):
    """Le message (bulle, réponse) qui contient `widget` : son premier ancêtre qui porte `attr`.
    Les gestionnaires passent par là au lieu de garder une référence à la bulle (cycle)."""
    while widget is not None and not hasattr(widget, attr):
        widget = widget.get_parent()
    return widget


def selected_text(widget):
    """Texte sélectionné à la souris dans un message (texte ou bloc de code), ou ""."""
    for w in (widget, *_descendants(widget)):
        if isinstance(w, Gtk.Label):
            bounds = w.get_selection_bounds()
            if bounds and bounds[0]:
                return w.get_text()[bounds[1]:bounds[2]].strip()
        elif isinstance(w, Gtk.TextView):
            buf = w.get_buffer()
            bounds = buf.get_selection_bounds()
            if bounds:
                return buf.get_text(bounds[0], bounds[1], False).strip()
    return ""


def _toggle_quote(gesture, *_args):
    """Clic sur la citation d'une bulle : la déplie en entier, ou la replie."""
    box = gesture.get_widget()
    label = getattr(box, "quote_label", None)
    if label is not None:
        label.set_label(box.quote_full if label.get_label() == box.quote_short else box.quote_short)


class _Segment:
    """Un morceau de réponse de Claude (une bulle) : texte brut accumulé et rendu différé."""

    def __init__(self, bubble, view):
        self.bubble, self.view = bubble, view
        self.text, self.timer, self.closed = "", 0, False
        self.interval = RENDER_MS


# ---- la liste ------------------------------------------------------------------------------

def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


def open_bubble_menu(row, rewind=None, reply=None, tag=None):
    """Menu de la bulle d'un message de l'utilisateur (clic droit) : « Répondre », « Étiqueter… »
    et « Revenir à avant ce message ». `reply(ligne)`, `tag(ligne)` et `rewind(ligne)` reçoivent
    la bulle."""
    pop = Gtk.Popover()
    pop.set_parent(row)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    for attr, label, callback in (("reply_button", "Répondre", reply),
                                  ("tag_button", "Étiqueter…", tag),
                                  ("rewind_button", "Revenir à avant ce message", rewind)):
        if callback is None:
            continue
        button = Gtk.Button(css_classes=["flat"], child=Gtk.Label(label=label, xalign=0))
        button.connect("clicked", lambda btn, cb=callback: (btn.get_ancestor(Gtk.Popover).popdown(),
                                                            cb(btn.get_ancestor(Gtk.Popover).get_parent())))
        box.append(button)
        setattr(row, attr, button)
    pop.set_child(box)
    pop.popup()
    return pop


def open_rewind_menu(row, callback):
    """Menu réduit à « Revenir à avant ce message » ; renvoie son bouton."""
    open_bubble_menu(row, rewind=callback)
    return row.rewind_button


def fill_tags(box, tags):
    """Pastilles des étiquettes d'un message (sous sa bulle) ; cachées s'il n'en a pas."""
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt
    for tag in tags or ():
        box.append(Gtk.Label(label=tag, css_classes=["ccs-tag"], tooltip_text="Étiquette (clic : modifier)"))
    box.set_visible(bool(tags))


def open_tag_editor(row, current, known, on_done):
    """Petite fenêtre « Étiqueter » sur un message : champ prérempli (étiquettes séparées par des
    virgules), étiquettes déjà utilisées en suggestion (un clic l'ajoute), Valider / Annuler.
    on_done(étiquettes) à la validation ; une liste vide les retire."""
    pop = Gtk.Popover()
    pop.set_parent(row)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6, margin_bottom=6,
                  margin_start=6, margin_end=6, width_request=300)
    box.append(Gtk.Label(label="Étiquettes, séparées par des virgules", xalign=0, css_classes=["caption"]))
    entry = Gtk.Entry(text=", ".join(current), placeholder_text="important, à revoir", hexpand=True)
    box.append(entry)
    have = {t.casefold() for t in current}
    offered = [t for t in known if t.casefold() not in have][:TAG_SUGGESTIONS]
    pop.tag_suggestions = []
    if offered:
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, row_spacing=2,
                           column_spacing=2)

        def add(btn):
            tags = message_tags.parse(entry.get_text())
            if btn.tag.casefold() not in {t.casefold() for t in tags}:
                tags.append(btn.tag)
            entry.set_text(", ".join(tags))
            entry.set_position(-1)
            btn.set_sensitive(False)
        for tag in offered:
            btn = Gtk.Button(label=tag, css_classes=["flat", "small"], tooltip_text="Ajouter cette étiquette")
            btn.tag = tag
            btn.connect("clicked", add)
            flow.append(btn)
            pop.tag_suggestions.append(btn)
        box.append(flow)
    buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END)
    cancel = Gtk.Button(label="Annuler")
    ok = Gtk.Button(label="Valider", css_classes=["suggested-action"])
    buttons.append(cancel)
    buttons.append(ok)
    box.append(buttons)
    pop.set_child(box)

    def validate(*_a):
        tags = message_tags.parse(entry.get_text())
        pop.popdown()
        on_done(tags)
    ok.connect("clicked", validate)
    entry.connect("activate", validate)
    cancel.connect("clicked", lambda *_a: pop.popdown())
    # refermée : détachée de la bulle (pas de fenêtre orpheline gardée en mémoire)
    pop.connect("closed", lambda p: GLib.idle_add(lambda: (p.get_parent() is not None and p.unparent(), False)[1]))
    pop.tag_entry, pop.tag_ok, pop.tag_cancel = entry, ok, cancel
    pop.popup()
    entry.grab_focus()
    return pop


class MessageList(Gtk.ScrolledWindow):
    """Fil de la conversation. Les widgets sont ajoutés en bas ; l'historique d'un chat rouvert
    se construit par paquets de 50 en remontant."""

    def __init__(self, on_diff=None, on_open=None, on_link=None, base_dir=None, on_older=None,
                 on_rewind=None, on_reply=None, on_tag=None):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, hexpand=True)
        install_css()
        self.on_diff, self.on_open, self.on_link = on_diff, on_open, on_link
        self.on_rewind = on_rewind    # on_rewind(ligne) : « Revenir à avant ce message »
        self.on_reply = on_reply      # on_reply(auteur, texte) : « Répondre » en citant un message
        # on_tag(identifiant, étiquettes, texte, rôle) : « Étiqueter » un message
        self.on_tag = on_tag
        self._tags = {}           # identifiant de message -> entrée de message_tags
        self.known_tags = []      # étiquettes déjà utilisées (suggestions)
        self.on_older = on_older
        self._dropped = 0         # lignes retirées du haut du fil par trim()
        self.base_dir = base_dir
        self._dark = False
        self._views = []
        self._segs = {}           # msg_id -> segment courant
        self.last_reply = None    # dernier segment de réponse fini (lecture à voix haute en fin de tour)
        self._tools = {}          # tool_id -> ToolCard
        self._run = None          # dernière action ajoutée (carte ou groupe) : la suite s'y regroupe
        self._perms = {}          # request_id -> PermissionCard
        self._todos = None
        self._last = None         # dernier widget de contenu (avant la ligne d'activité)
        self._hist, self._hist_pos = [], 0
        self._hits, self._find_at = [], 0    # recherche dans le fil
        self._built = 0
        self._stick, self._moving = True, False

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_bottom=14,
                           margin_start=16, margin_end=16)
        self.busy_label = Gtk.Label(xalign=0, css_classes=["ccs-subtle"])
        self.busy_spinner = Gtk.Spinner(spinning=True)
        self.busy_row = Gtk.Box(spacing=8, css_classes=["ccs-busy-row"], visible=False)
        self.busy_row.append(self.busy_spinner)
        self.busy_row.append(self.busy_label)
        self.box.append(self.busy_row)
        # « N éléments plus anciens retirés… — Afficher » : en tête du fil après un élagage.
        self.older_label = Gtk.Label(xalign=0, wrap=True, hexpand=True, css_classes=["ccs-subtle"])
        self.older_button = Gtk.Button(label="Afficher", css_classes=["flat"], valign=Gtk.Align.CENTER)
        self.older_button.connect("clicked", lambda *_: self.on_older and self.on_older())
        self.older_row = Gtk.Box(spacing=8, visible=False)
        self.older_row.append(self.older_label)
        self.older_row.append(self.older_button)
        self.box.prepend(self.older_row)
        self.set_child(Adw.Clamp(child=self.box, maximum_size=MAX_WIDTH, tightening_threshold=MAX_WIDTH - 200))
        # « ↓ Nouveaux messages » : posé en surimpression par l'onglet (Gtk.Overlay), visible
        # quand du contenu arrive alors qu'on lit plus haut.
        self.new_button = Gtk.Button(label="↓ Nouveaux messages", visible=False, halign=Gtk.Align.CENTER,
                                     valign=Gtk.Align.END, margin_bottom=12,
                                     css_classes=["pill", "suggested-action"])
        self.new_button.connect("clicked", lambda *_: self.follow())
        self._scroll_pending = False
        self._history_loading = False
        self._busy_text, self._busy_started, self._busy_timer = "", time.time(), 0
        self._last_footer = None
        adj = self.get_vadjustment()
        adj.connect("value-changed", self._on_value)
        adj.connect("notify::upper", self._on_upper)

    # -- défilement --

    def _on_value(self, adj):
        if self._moving:
            return
        self._stick = adj.get_upper() - adj.get_page_size() - adj.get_value() < STICK_PX
        if self._stick:
            self.new_button.set_visible(False)
        if adj.get_value() < 80 and self._hist_pos > 0:
            self._load_more()

    def _on_upper(self, adj, _p):
        if self._history_loading:
            return  # l'historique s'ajoute en haut : _load_more garde la position
        if self._stick:
            self._queue_scroll_end()

    def _queue_scroll_end(self):
        """Ramène en bas APRÈS la mise en page. Changer l'ajustement pendant l'allocation
        (dans `notify::upper`) est ignoré par GTK : le contenu ajouté restait hors de la vue
        tant qu'on ne faisait pas défiler."""
        if not self._scroll_pending:
            self._scroll_pending = True
            GLib.idle_add(self._scroll_end_idle)

    def _scroll_end_idle(self):
        self._scroll_pending = False
        if self._stick:
            self.scroll_end()
        return False

    def _content_added(self):
        """Du nouveau en bas du fil : on suit si l'on est en bas, sinon le bouton apparaît."""
        if self._stick:
            self._queue_scroll_end()
        else:
            self.new_button.set_visible(True)

    def follow(self):
        """Retour en bas (bouton « Nouveaux messages ») ; la vue suit de nouveau."""
        self._stick = True
        self.scroll_end()
        self._queue_scroll_end()

    def scroll_end(self):
        adj = self.get_vadjustment()
        self._moving = True
        adj.set_value(max(0.0, adj.get_upper() - adj.get_page_size()))
        self._moving = False
        self.new_button.set_visible(False)

    # -- ajout --

    def _append(self, widget):
        """Ajoute en bas du fil, avant la ligne d'activité."""
        self.box.insert_child_after(widget, self._last or self.older_row)
        self._last = widget
        self._built += 1
        self._content_added()
        return widget

    def _bubble_widget(self, role_class, child, halign):
        bubble = Gtk.Box(css_classes=[role_class], halign=halign)
        bubble.append(child)
        return bubble

    def _markdown(self, text=""):
        view = MarkdownView(text, base_dir=self.base_dir, on_link=lambda uri: self.on_link and self.on_link(uri))
        view.set_dark(self._dark)
        self._views.append(view)
        return view

    def _user_widget(self, text, images=(), during=False, on_rewind=None, msg_id=""):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for media_type, data in images or ():
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            except (GLib.Error, TypeError):
                continue
            pic = Gtk.Picture(paintable=texture, content_fit=Gtk.ContentFit.SCALE_DOWN, halign=Gtk.Align.START,
                              css_classes=["ccs-thumb"], height_request=min(180, texture.get_height()),
                              width_request=min(320, texture.get_width()))
            col.append(pic)
        raw = text or ""
        quoted = chat_quote.split(raw)
        if quoted is not None:
            # réponse à un message : ce qu'elle cite d'abord, à part, puis la réponse
            col.append(self._quote_widget(quoted))
            text = quoted.body
        if text:
            label = Gtk.Label(label=text, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                              selectable=True, max_width_chars=80)
            col.append(label)
            short = _fold(text)
            if short != text:
                # un long texte collé n'occupe pas tout l'écran : replié, « Afficher tout »
                # (le texte est coupé à la main : la limite de lignes de GTK ignore les vrais
                # retours à la ligne)
                label.set_label(short)
                more = Gtk.Button(label="Afficher tout", halign=Gtk.Align.START, css_classes=["flat", "small"])

                def toggle(btn, label=label, full=text, short=short):
                    unfold = btn.get_label() == "Afficher tout"
                    label.set_label(full if unfold else short)
                    btn.set_label("Replier" if unfold else "Afficher tout")
                more.connect("clicked", toggle)
                col.append(more)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.END, margin_start=60, spacing=2)
        bubble = self._bubble_widget("ccs-bubble-user", col, Gtk.Align.END)
        reply = self._reply_from if self.on_reply is not None and raw.strip() else None
        tag = self.edit_tags if self.on_tag is not None and msg_id else None
        if reply is not None or tag is not None:
            # « Répondre » et « Étiqueter » à gauche de la bulle, visibles au survol
            line = Gtk.Box(spacing=4, halign=Gtk.Align.END)
            actions = Gtk.Box(valign=Gtk.Align.CENTER, opacity=0, css_classes=["ccs-hover-actions"])
            if reply is not None:
                outer.reply_hover = self._reply_button()
                actions.append(outer.reply_hover)
            if tag is not None:
                outer.tag_hover = self._tag_button()
                actions.append(outer.tag_hover)
            line.append(actions)
            line.append(bubble)
            outer.append(line)
            outer.hover_actions = actions
            hover = Gtk.EventControllerMotion()
            hover.connect("enter", _show_actions, 1)
            hover.connect("leave", _show_actions, 0)
            outer.add_controller(hover)
        else:
            outer.append(bubble)
        if during:
            outer.append(Gtk.Label(label="envoyé pendant que Claude travaille", xalign=1,
                                   css_classes=["ccs-subtle", "caption"]))
        outer.is_user = True
        outer.copy_text, outer.quote_author = raw, chat_quote.ME
        outer.tag_id, outer.tag_role = msg_id or "", preview.USER
        if msg_id:
            outer.tags_box = self._tags_widget(msg_id, Gtk.Align.END)
            outer.append(outer.tags_box)
        callback = on_rewind or self.on_rewind
        if callback is not None or reply is not None or tag is not None:
            # clic droit : menu de la bulle (sans référence à la ligne : pas de cycle)
            click = Gtk.GestureClick(button=3)
            click.connect("pressed", lambda g, _n, _x, _y, cb=callback, rp=reply, tg=tag: open_bubble_menu(
                g.get_widget(), rewind=cb, reply=rp, tag=tg))
            outer.add_controller(click)
        return outer

    def _quote_widget(self, quoted):
        """Citation en tête d'une bulle : l'auteur, puis le début du passage (un clic le déplie).
        Replié à la main, comme un long message : la limite de lignes de GTK ignore les vrais
        retours à la ligne."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["ccs-quoted"])
        box.append(Gtk.Label(label=chat_quote.SHOWN[quoted.author], xalign=0, css_classes=["ccs-quote-author"]))
        box.quote_full, box.quote_short = quoted.text, _fold(quoted.text, QUOTE_LINES, QUOTE_CHARS)
        label = Gtk.Label(label=box.quote_short, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                          max_width_chars=80, css_classes=["ccs-quote-text"])
        box.append(label)
        box.quote_label = label
        if box.quote_short != box.quote_full:
            box.set_tooltip_text("Message cité (clic : tout afficher)")
            click = Gtk.GestureClick(button=1)
            click.connect("released", _toggle_quote)
            box.add_controller(click)
        return box

    def _reply_button(self):
        # focus_on_click=False : le clic ne déplace pas le focus, le texte sélectionné dans le
        # message reste sélectionné (c'est lui qu'on cite)
        button = Gtk.Button(icon_name="mail-reply-sender-symbolic", tooltip_text="Répondre en citant ce message",
                            css_classes=["flat", "circular", "ccs-copy"], focus_on_click=False)
        button.connect("clicked", lambda btn: self._reply_from(_owner(btn)))
        return button

    def _reply_from(self, row):
        """« Répondre » sur un message : cite le passage sélectionné dedans, sinon son texte (le
        début d'un long message ; pour une bulle qui citait déjà quelque chose, sa réponse)."""
        if row is None or self.on_reply is None:
            return
        author = getattr(row, "quote_author", chat_quote.CLAUDE)
        raw = getattr(row, "copy_text", "") or ""
        picked = selected_text(row)
        if picked:
            text = chat_quote.excerpt(picked, chat_quote.SELECTION_MAX)
        else:
            text = chat_quote.excerpt(chat_quote.source_text(raw) if author == chat_quote.ME else raw)
        if text:
            self.on_reply(author, text)

    def _assistant_widget(self, text="", msg_id=""):
        view = self._markdown(text)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["ccs-bubble-claude"], hexpand=True,
                         margin_end=24, visible=bool(text))
        # « Répondre » et « Copier » (texte Markdown brut) : visibles au survol de la réponse, dans
        # une colonne à droite du texte (posés par-dessus, ils cachaient la fin de la première ligne)
        view.set_hexpand(True)
        row = Gtk.Box(spacing=4, hexpand=True)
        row.append(view)
        actions = Gtk.Box(halign=Gtk.Align.END, valign=Gtk.Align.START, opacity=0,
                          css_classes=["ccs-hover-actions"])
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copier la réponse",
                          css_classes=["flat", "circular", "ccs-copy"])
        bubble.copy_text, bubble.quote_author = text, chat_quote.CLAUDE
        # Gestionnaires sans référence à la bulle ni au bouton qu'elle contient : un cycle
        # Python ↔ GTK la garderait en mémoire après son retrait du fil.
        copy.connect("clicked", lambda btn: self._to_clipboard(getattr(_owner(btn), "copy_text", "") or ""))
        if self.on_reply is not None:
            bubble.reply_button = self._reply_button()
            actions.append(bubble.reply_button)
        if self.on_tag is not None and msg_id:
            bubble.tag_hover = self._tag_button()
            actions.append(bubble.tag_hover)
        if voice.can_speak():
            bubble.speak_button = Gtk.Button(icon_name="audio-speakers-symbolic", tooltip_text="Lire à voix haute",
                                             css_classes=["flat", "circular", "ccs-copy"], focus_on_click=False)
            bubble.speak_button.connect("clicked", lambda btn: read_aloud(_owner(btn)))
            actions.append(bubble.speak_button)
        actions.append(copy)
        row.append(actions)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", _show_actions, 1)
        hover.connect("leave", _show_actions, 0)
        bubble.add_controller(hover)
        bubble.copy_button, bubble.hover_actions = copy, actions
        bubble.append(row)
        bubble.tag_id, bubble.tag_role = msg_id or "", preview.ASSISTANT
        if msg_id:
            bubble.tags_box = self._tags_widget(msg_id, Gtk.Align.START)
            bubble.append(bubble.tags_box)
        return bubble, view

    # -- étiquettes --

    def _tag_button(self):
        button = Gtk.Button(icon_name="bookmark-new-symbolic", tooltip_text="Étiqueter ce message",
                            css_classes=["flat", "circular", "ccs-copy"], focus_on_click=False)
        button.connect("clicked", lambda btn: self.edit_tags(_owner(btn, "tag_id")))
        return button

    def _tags_widget(self, msg_id, halign):
        box = Gtk.Box(spacing=4, halign=halign, margin_top=2)
        fill_tags(box, (self._tags.get(msg_id) or {}).get("tags"))
        click = Gtk.GestureClick(button=1)
        click.connect("released", lambda g, *_a: self.edit_tags(_owner(g.get_widget(), "tag_id")))
        box.add_controller(click)
        return box

    def edit_tags(self, row):
        """« Étiqueter » un message : fenêtre préremplie ; la validation passe par on_tag (le fil
        se met à jour quand l'enregistrement est confirmé, `update_tags`)."""
        msg_id = getattr(row, "tag_id", "")
        if row is None or not msg_id or self.on_tag is None:
            return None
        raw = getattr(row, "copy_text", "") or ""
        role = getattr(row, "tag_role", "")
        text = chat_quote.source_text(raw) if role == preview.USER else raw
        current = (self._tags.get(msg_id) or {}).get("tags") or []
        row.tag_popover = open_tag_editor(row, current, self.known_tags,
                                          lambda tags: self.on_tag(msg_id, tags, text, role))
        return row.tag_popover

    def _tagged_rows(self, msg_id=None):
        """Lignes du fil qui portent un identifiant de message (`msg_id` : celles-là seulement)."""
        return [w for w in self._content_rows()
                if getattr(w, "tag_id", "") and (msg_id is None or w.tag_id == msg_id)]

    def set_tags(self, messages):
        """Toutes les étiquettes de la conversation ({identifiant: entrée}) : pastilles à jour."""
        self._tags = dict(messages or {})
        for row in self._tagged_rows():
            fill_tags(row.tags_box, (self._tags.get(row.tag_id) or {}).get("tags"))

    def update_tags(self, msg_id, entry):
        """Étiquettes d'un message changées (entrée None : retirées) ; sans recharger le fil."""
        if entry and entry.get("tags"):
            self._tags[msg_id] = entry
        else:
            self._tags.pop(msg_id, None)
        for row in self._tagged_rows(msg_id):
            fill_tags(row.tags_box, (entry or {}).get("tags"))

    def tagged(self):
        """{identifiant: entrée} des messages étiquetés de la conversation."""
        return dict(self._tags)

    def tags_of(self, msg_id):
        return list((self._tags.get(msg_id) or {}).get("tags") or [])

    def show_message(self, msg_id):
        """Défile jusqu'au message `msg_id` et le met brièvement en évidence ; l'historique pas
        encore construit est construit au besoin. Faux s'il n'est pas dans le fil."""
        rows = self._tagged_rows(msg_id)
        while not rows and self._hist_pos > 0:
            self._load_more()
            rows = self._tagged_rows(msg_id)
        if not rows:
            return False
        target = rows[0]
        target.add_css_class("ccs-tag-flash")
        GLib.timeout_add(TAG_FLASH_MS, lambda w=target: (w.remove_css_class("ccs-tag-flash"), False)[1])
        self._stick = False
        self.new_button.set_visible(False)

        def scroll():
            ok, point = target.compute_point(self.box, Graphene.Point().init(0, 0))
            if ok:
                adj = self.get_vadjustment()
                self._moving = True
                adj.set_value(max(0.0, point.y - adj.get_page_size() / 3))
                self._moving = False
            return False
        scroll()
        GLib.idle_add(scroll)        # après la mise en page de l'historique tout juste construit
        return True

    def _to_clipboard(self, text):
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(text)

    # -- fin de tour, activité --

    def add_turn_footer(self, seconds, cost_usd=None, usage=None):
        """« ✓ Terminé en 42 s · 36 k lus · 2 k écrits · 850 produits · 0,12 $ éq. » sous la
        réponse : durée du tour, tokens (`token_use.summary`) et coût de ce tour."""
        parts = [f"✓ Terminé en {_duration(seconds)}"]
        tokens = token_use.summary({**(usage or {}), "cost_usd": 0}) if usage else ""
        if tokens:
            parts.append(tokens)
        if cost_usd:
            parts.append(f"{cost_usd:.2f}".replace(".", ",") + " $ éq.")
        label = Gtk.Label(label=" · ".join(parts), xalign=0, css_classes=["ccs-subtle", "caption"],
                          margin_start=4)
        self._last_footer = label
        self._append(label)
        return label

    def _tick_busy(self):
        if not self.busy_row.get_visible():
            self._busy_timer = 0
            return False
        elapsed = int(time.time() - self._busy_started)
        self.busy_label.set_label(self._busy_text + (f" · {_duration(elapsed)}" if elapsed >= 1 else ""))
        return True

    def _tool_widget(self, name, target, data=None, nested=False):
        return ToolCard(name, target, data, on_diff=lambda *a: self.on_diff and self.on_diff(*a),
                        on_open=lambda *a: self.on_open and self.on_open(*a), nested=nested)

    def _notice_widget(self, text, kind="info", action=None):
        row = Gtk.Box(spacing=8, css_classes=["ccs-chat-notice"] + ([kind] if kind != "info" else []))
        icon = {"error": "dialog-error-symbolic", "warning": "dialog-warning-symbolic"}.get(
            kind, "dialog-information-symbolic")
        row.append(Gtk.Image(icon_name=icon, valign=Gtk.Align.START))
        row.append(Gtk.Label(label=text, xalign=0, hexpand=True, wrap=True, selectable=True,
                             wrap_mode=Pango.WrapMode.WORD_CHAR))
        actions = action if isinstance(action, list) else [action] if action else []
        for n, (label, callback) in enumerate(actions):
            button = Gtk.Button(label=label, valign=Gtk.Align.CENTER,
                                css_classes=["suggested-action"] if n == 0 else [])
            button.connect("clicked", lambda b, cb=callback: cb())
            row.append(button)
        return row

    def add_shell_card(self, command):
        """Carte d'une commande `!` : la commande, « Arrêter » tant qu'elle tourne, puis sa sortie
        (`card.set_output(code, texte, tronquée)`)."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["ccs-tool-card"])
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Spinner(spinning=True))
        head.append(Gtk.Label(label="$ " + command, xalign=0, hexpand=True, selectable=True,
                              ellipsize=Pango.EllipsizeMode.END, css_classes=["monospace"]))
        card.status = Gtk.Label(label="", css_classes=["ccs-subtle"])
        card.stop_button = Gtk.Button(label="Arrêter", css_classes=["flat", "destructive-action"])
        head.append(card.status)
        head.append(card.stop_button)
        card.append(head)
        card.output = Gtk.Label(xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.CHAR,
                                css_classes=["monospace", "ccs-code-box"], visible=False)
        card.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                         max_content_height=320, visible=False, child=card.output)
        card.append(card.scroll)

        def set_output(code, text, truncated=False):
            head.get_first_child().set_spinning(False)
            card.stop_button.set_visible(False)
            note = " — sortie tronquée" if truncated else ""
            card.status.set_label(("code " + str(code) if code is not None else "arrêtée") + note)
            card.output.set_label(text if text.strip() else "(aucune sortie)")
            card.output.set_visible(True)
            card.scroll.set_visible(True)
            self.scroll_end_if_stuck()
        card.set_output = set_output
        card.command = command
        self._append(card)
        self.scroll_end_if_stuck()
        return card

    def add_user(self, text, images=(), during=False, on_rewind=None, msg_id=""):
        row = self._append(self._user_widget(text, images, during, on_rewind, msg_id))
        self.scroll_end_if_stuck()
        return row

    # -- recherche dans le fil (Ctrl+F) --

    def _search_units(self):
        """(widget, texte) de chaque bulle et carte d'action du fil, dans l'ordre."""
        out = []

        def walk(widget):
            if getattr(widget, "is_user", False):
                out.append((widget, " ".join(
                    w.get_label() or "" for w in _descendants(widget) if isinstance(w, Gtk.Label))))
            elif hasattr(widget, "copy_text"):
                out.append((widget, widget.copy_text or ""))
            elif isinstance(widget, ToolCard):
                out.append((widget, f"{tool_label(widget.name)} {widget.name} {widget.target or ''}"))
            else:
                child = widget.get_first_child()
                while child is not None:
                    walk(child)
                    child = child.get_next_sibling()
        for row in self._content_rows():
            walk(row)
        return out

    def find(self, query):
        """Cherche `query` (sans tenir compte des accents ni de la casse) dans le texte des bulles
        et le titre et la cible des cartes ; met en évidence le premier résultat et y défile.
        Renvoie le nombre de résultats."""
        self.find_clear()
        needle = fold(query or "").strip()
        if not needle:
            return 0
        while self._hist_pos > 0:                 # l'historique pas encore construit se cherche aussi
            self._load_more()
        self._hits = [w for w, text in self._search_units() if needle in fold(text)]
        for w in self._hits:
            w.add_css_class("ccs-find-hit")
        if self._hits:
            self._find_at = 0
            self._show_hit()
        return len(self._hits)

    def trimmed(self):
        """Vrai si l'élagage a retiré des lignes du haut du fil."""
        return self._dropped > 0

    def find_count(self):
        return len(self._hits)

    def find_position(self):
        """Rang (à partir de 1) du résultat en évidence ; 0 s'il n'y en a pas."""
        return self._find_at + 1 if self._hits else 0

    def find_next(self):
        if self._hits:
            self._find_at = (self._find_at + 1) % len(self._hits)
            self._show_hit()

    def find_prev(self):
        if self._hits:
            self._find_at = (self._find_at - 1) % len(self._hits)
            self._show_hit()

    def find_clear(self):
        for w in self._hits:
            w.remove_css_class("ccs-find-hit")
            w.remove_css_class("ccs-find-current")
        self._hits, self._find_at = [], 0

    def _show_hit(self):
        for i, w in enumerate(self._hits):
            if i == self._find_at:
                w.add_css_class("ccs-find-current")
            else:
                w.remove_css_class("ccs-find-current")
        target = self._hits[self._find_at]
        ok, point = target.compute_point(self.box, Graphene.Point().init(0, 0))
        if ok:
            adj = self.get_vadjustment()
            self._stick = False
            adj.set_value(max(0.0, point.y - adj.get_page_size() / 3))

    def user_index_from_end(self, row):
        """Rang de la bulle `row` parmi les messages de l'utilisateur du fil, en comptant depuis
        le dernier (0) ; None si elle n'y est plus."""
        users = [w for w in self._content_rows() if getattr(w, "is_user", False)]
        for i, w in enumerate(reversed(users)):
            if w is row:
                return i
        return None

    def _segment(self, msg_id, create=True):
        seg = self._segs.get(msg_id)
        if seg is not None and seg.bubble is self._last and not seg.closed:
            return seg
        if not create:
            return None
        bubble, view = self._assistant_widget(msg_id=msg_id or "")
        seg = _Segment(bubble, view)
        self._append(bubble)
        self._segs[msg_id] = seg
        return seg

    def start_assistant(self, msg_id):
        self._segment(msg_id)

    def append_delta(self, msg_id, text):
        seg = self._segment(msg_id)
        seg.text += text
        if not seg.timer:
            seg.timer = GLib.timeout_add(seg.interval, self._render, seg)

    def _render(self, seg):
        seg.timer = 0
        seg.bubble.set_visible(bool(seg.text.strip()))
        seg.bubble.copy_text = seg.text
        start = time.monotonic()
        if seg.closed:
            seg.view.set_text(seg.text)              # rendu exact, une fois, à la fin
        else:
            seg.view.set_text_streaming(seg.text)    # pendant le flux : la fin seulement
            spent_ms = (time.monotonic() - start) * 1000
            seg.interval = int(min(RENDER_MAX_MS, max(RENDER_MS, 4 * spent_ms)))
        self.scroll_end_if_stuck()
        return False

    def finish_assistant(self, msg_id, text):
        seg = self._segment(msg_id, create=bool(text and text.strip()))
        if seg is None:
            return
        self.last_reply = seg
        if seg.timer:
            GLib.source_remove(seg.timer)
            seg.timer = 0
        if text and text.strip():
            seg.text = text
        seg.closed = True
        self._render(seg)

    def add_tool(self, ev):
        card = self._tool_widget(ev.name, tool_target(ev.name, ev.input, self.base_dir), ev.input,
                                 nested=bool(getattr(ev, "parent_id", None)))
        self._tools[ev.tool_id] = card
        if ev.name in AGENT_TOOLS or getattr(ev, "parent_id", None):
            self._run = None
            self._append(card)
        else:
            self._add_to_run(card)
        self.scroll_end_if_stuck()
        return card

    def _add_to_run(self, card):
        """Une action qui suit directement une autre (aucun texte entre elles) rejoint son
        groupe ; la deuxième transforme la carte seule en groupe."""
        run = self._run
        if run is None or run is not self._last or run.get_parent() is not self.box:
            self._run = card
            self._append(card)
            return
        if isinstance(run, ToolGroup):
            run.add(card)
        else:
            group = ToolGroup()
            self.box.insert_child_after(group, run.get_prev_sibling())
            self.box.remove(run)
            group.add(run)
            group.add(card)
            self._last = self._run = group
        self._content_added()

    def set_tool_result(self, ev):
        card = self._tools.get(ev.tool_id)
        if card is not None:
            card.set_result(ev.text, ev.is_error)
            if card.group is not None:
                card.group.refresh()

    def pending_permission(self):
        """La plus ancienne demande d'autorisation encore sans réponse, ou None."""
        return next((card for card in self._perms.values() if not card.answered), None)

    def add_permission(self, req, on_answer, on_questions=None):
        if req.tool_name == proto.QUESTION_TOOL and on_questions is not None and proto.question_items(req.input):
            card = QuestionCard(req, on_questions,
                                lambda rid: on_answer(rid, "deny", "L'utilisateur préfère répondre dans le "
                                                      "chat : pose-lui la question par écrit et attends sa réponse."))
            self._perms[req.request_id] = card
            self._append(card)
            self.scroll_end_if_stuck()
            return card
        card = PermissionCard(req, on_answer, self.base_dir)
        self._perms[req.request_id] = card
        self._append(card)
        self.scroll_end_if_stuck()
        return card

    def resolve_permission(self, request_id, decision):
        card = self._perms.get(request_id)
        if card is not None and not card.answered:
            card.resolve(decision)

    def cancel_permissions(self):
        for card in self._perms.values():
            if not card.answered:
                card.resolve("cancelled")

    def set_todos(self, ev):
        if self._todos is None:
            self._todos = TodosCard()
            self._append(self._todos)
        self._todos.update(ev.items)
        self.scroll_end_if_stuck()

    def add_reset_separator(self, auto=False):
        """Après `/clear` : les messages d'avant restent lisibles (et sélectionnables) mais
        grisés, sous un séparateur « Nouvelle conversation ». `auto` : effacée par Claude en fin
        de sujet (`ccs chat clear`)."""
        child = self.box.get_first_child()
        while child is not None:
            if child not in (self.busy_row, self.older_row):
                child.set_opacity(0.55)
                child.add_css_class("ccs-before-reset")
            child = child.get_next_sibling()
        row = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6, css_classes=["ccs-reset-separator"])
        row.append(Gtk.Separator(hexpand=True, valign=Gtk.Align.CENTER))
        row.append(Gtk.Label(label=RESET_AUTO_TEXT if auto else RESET_TEXT,
                             wrap=True, justify=Gtk.Justification.CENTER, css_classes=["caption", "dim-label"]))
        row.append(Gtk.Separator(hexpand=True, valign=Gtk.Align.CENTER))
        self._append(row)
        self.scroll_end_if_stuck()
        return row

    def add_notice(self, text, kind="info", action=None):
        widget = self._notice_widget(text, kind, action)
        self._append(widget)
        self.scroll_end_if_stuck()
        return widget

    def set_busy(self, busy, text="Claude travaille…"):
        """Ligne d'activité : ce que fait Claude, et depuis combien de temps dans ce tour."""
        was = self.busy_row.get_visible()
        self.busy_row.set_visible(bool(busy))
        self.busy_spinner.set_spinning(bool(busy))
        self._busy_text = text
        if busy and not was:
            self._busy_started = time.time()
        if busy and not self._busy_timer:
            self._busy_timer = GLib.timeout_add_seconds(1, self._tick_busy)
        if busy:
            self._tick_busy()
            self.scroll_end_if_stuck()
        else:
            self.busy_label.set_label(text)

    def scroll_end_if_stuck(self):
        self._content_added()

    def set_dark(self, dark):
        self._dark = bool(dark)
        for view in self._views:
            view.set_dark(dark)

    # -- historique --

    @property
    def built_count(self):
        """Lignes de contenu réellement construites."""
        return self._built

    def row_count(self):
        """Lignes du fil (sans la ligne d'activité ; avec « plus anciens » si elle est montrée)."""
        return self.box.observe_children().get_n_items() - 2 + int(self.older_row.get_visible())

    def _content_rows(self):
        out, child = [], self.older_row.get_next_sibling()
        while child is not None and child is not self.busy_row:
            out.append(child)
            child = child.get_next_sibling()
        return out

    def _forget_detached(self):
        """Oublie les références vers des widgets qui ne sont plus dans le fil (sinon ils
        restent en mémoire)."""
        inside = lambda w: w is not None and w.is_ancestor(self.box)
        self._views = [v for v in self._views if inside(v)]
        self._segs = {k: s for k, s in self._segs.items() if inside(s.bubble)}
        self._tools = {k: c for k, c in self._tools.items() if inside(c)}
        self._perms = {k: c for k, c in self._perms.items() if inside(c)}
        if not inside(self._todos):
            self._todos = None
        if not inside(self._run):
            self._run = None
        if not inside(self._last_footer):
            self._last_footer = None

    def trim(self):
        """Longue session : au-delà de LIVE_MAX lignes, retire les plus anciennes pour n'en
        garder que LIVE_KEEP (une longue session faisait grossir la fenêtre de centaines de
        Mo). Seulement quand on est en bas du fil : on ne retire jamais ce qu'on lit. Une ligne
        en tête propose de relire la conversation depuis son journal. Renvoie le nombre retiré."""
        rows = self._content_rows()
        if len(rows) <= LIVE_MAX or not self._stick:
            return 0
        drop = rows[:len(rows) - LIVE_KEEP]
        for widget in drop:
            self.box.remove(widget)
        self._forget_detached()
        for widget in drop:
            release(widget)
        GLib.idle_add(give_back_memory)
        self._hist, self._hist_pos = [], 0      # l'historique pas encore construit part avec
        self._dropped += len(drop)
        self.older_label.set_label(f"{self._dropped} éléments plus anciens retirés de l'affichage pour "
                                   "garder CCS léger.")
        self.older_button.set_visible(self.on_older is not None)
        self.older_row.set_visible(True)
        self._queue_scroll_end()
        return len(drop)

    def reset(self):
        """Vide le fil (avant de le relire depuis le journal)."""
        for seg in self._segs.values():
            if seg.timer:
                GLib.source_remove(seg.timer)
        for widget in self._content_rows():
            self.box.remove(widget)
            release(widget)
        self._views, self._segs, self._tools, self._perms = [], {}, {}, {}
        self._todos = self._run = self._last = self._last_footer = None
        self._hist, self._hist_pos = [], 0
        self._hits, self._find_at = [], 0
        self._dropped = 0
        self.older_row.set_visible(False)

    def load_history(self, messages):
        """Montre `messages` (preview.Message) : les derniers d'abord, les plus anciens au
        défilement vers le haut."""
        self._hist, self._hist_pos = list(messages), len(messages)
        self._stick = True
        self._load_more(initial=True)

    def _history_widget(self, m):
        if m.role == preview.USER:
            return self._user_widget(m.text, msg_id=getattr(m, "uuid", "") or "")
        if m.role == preview.ASSISTANT:
            if not (m.text or "").strip():
                return None
            bubble, _view = self._assistant_widget(m.text, getattr(m, "msg_id", "") or "")
            return bubble
        if m.role == preview.TOOL and m.tool is not None:
            card = self._tool_widget(m.tool.name, m.tool.target or "")
            card.set_result(m.tool.result, m.tool.is_error)
            if not m.tool.is_error:
                card.remove_css_class("done")
            return card
        if m.text:
            return self._notice_widget(m.text)
        return None

    def _history_widgets(self, batch):
        """Les widgets d'un paquet d'historique ; les actions qui s'enchaînent sont groupées."""
        run = []

        def flush():
            if len(run) == 1:
                yield run[0]
            elif run:
                group = ToolGroup()
                for card in run:
                    group.add(card)
                yield group
            run.clear()

        for m in batch:
            widget = self._history_widget(m)
            if widget is None:
                continue
            if isinstance(widget, ToolCard) and widget.name not in AGENT_TOOLS:
                run.append(widget)
                continue
            yield from flush()
            yield widget
        yield from flush()

    def _load_more(self, initial=False):
        start = max(0, self._hist_pos - PAGE)
        batch = self._hist[start:self._hist_pos]
        self._hist_pos = start
        adj = self.get_vadjustment()
        old_upper, old_value = adj.get_upper(), adj.get_value()
        prev = self.older_row
        for widget in self._history_widgets(batch):
            self.box.insert_child_after(widget, prev)
            self._built += 1
            prev = widget
        if initial:
            self._last = self.busy_row.get_prev_sibling()  # la fin de l'historique est la fin du fil
        elif prev is not None:
            # garde à l'écran ce que l'on regardait : le contenu ajouté pousse tout vers le bas
            handler = []
            self._history_loading = True

            def keep(a, _p):
                a.disconnect(handler[0])
                self._moving = True
                a.set_value(old_value + a.get_upper() - old_upper)
                self._moving = False
                self._history_loading = False
            handler.append(adj.connect("notify::upper", keep))
