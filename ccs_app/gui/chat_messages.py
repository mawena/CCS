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
from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from .. import chat_protocol as proto, preview  # noqa: E402
from .markdown_view import MarkdownView  # noqa: E402

PAGE = 50                   # messages d'historique construits à la fois
RENDER_MS = 90              # un rendu Markdown au plus toutes les 90 ms pendant le flux…
RENDER_MAX_MS = 1000        # … espacé si le rendu coûte (4 × sa durée), sans dépasser 1 s
RESULT_CHARS = 20_000       # résultat d'outil montré (le reste est coupé à l'affichage)
FOLD_LINES = 14             # un message de l'utilisateur plus long est replié (« Afficher tout »)
FOLD_CHARS = 1500
STICK_PX = 48               # à moins de 48 px du bas, la liste suit le texte qui arrive
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


def _fold(text):
    """Les FOLD_LINES premières lignes (et au plus FOLD_CHARS caractères) suivies de « … »,
    ou le texte tel quel s'il est court."""
    lines = text.split("\n")
    short = "\n".join(lines[:FOLD_LINES])
    if len(short) > FOLD_CHARS:
        short = short[:FOLD_CHARS].rstrip()
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


def _clear(box):
    while (child := box.get_first_child()) is not None:
        box.remove(child)


def _cut(text, limit=RESULT_CHARS):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} caractères de plus)"


# ---- widgets -------------------------------------------------------------------------------

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


class _Segment:
    """Un morceau de réponse de Claude (une bulle) : texte brut accumulé et rendu différé."""

    def __init__(self, bubble, view):
        self.bubble, self.view = bubble, view
        self.text, self.timer, self.closed = "", 0, False
        self.interval = RENDER_MS


# ---- la liste ------------------------------------------------------------------------------

class MessageList(Gtk.ScrolledWindow):
    """Fil de la conversation. Les widgets sont ajoutés en bas ; l'historique d'un chat rouvert
    se construit par paquets de 50 en remontant."""

    def __init__(self, on_diff=None, on_open=None, on_link=None, base_dir=None):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, hexpand=True)
        install_css()
        self.on_diff, self.on_open, self.on_link = on_diff, on_open, on_link
        self.base_dir = base_dir
        self._dark = False
        self._views = []
        self._segs = {}           # msg_id -> segment courant
        self._tools = {}          # tool_id -> ToolCard
        self._run = None          # dernière action ajoutée (carte ou groupe) : la suite s'y regroupe
        self._perms = {}          # request_id -> PermissionCard
        self._todos = None
        self._last = None         # dernier widget de contenu (avant la ligne d'activité)
        self._hist, self._hist_pos = [], 0
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
        self.box.insert_child_after(widget, self._last)
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

    def _user_widget(self, text, images=(), during=False):
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
        outer.append(self._bubble_widget("ccs-bubble-user", col, Gtk.Align.END))
        if during:
            outer.append(Gtk.Label(label="envoyé pendant que Claude travaille", xalign=1,
                                   css_classes=["ccs-subtle", "caption"]))
        return outer

    def _assistant_widget(self, text=""):
        view = self._markdown(text)
        bubble = Gtk.Box(css_classes=["ccs-bubble-claude"], hexpand=True, margin_end=24, visible=bool(text))
        overlay = Gtk.Overlay(child=view, hexpand=True)
        # « Copier » (texte Markdown brut) : visible au survol de la réponse
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copier la réponse",
                          halign=Gtk.Align.END, valign=Gtk.Align.START, opacity=0,
                          css_classes=["flat", "circular", "ccs-copy"])
        bubble.copy_text = text
        copy.connect("clicked", lambda *_b: self._to_clipboard(bubble.copy_text or ""))
        overlay.add_overlay(copy)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_a: copy.set_opacity(1))
        hover.connect("leave", lambda *_a: copy.set_opacity(0))
        bubble.add_controller(hover)
        bubble.copy_button = copy
        bubble.append(overlay)
        return bubble, view

    def _to_clipboard(self, text):
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(text)

    # -- fin de tour, activité --

    def add_turn_footer(self, seconds, cost_usd=None):
        """« ✓ Terminé en 42 s · 0,12 $ éq. » sous la réponse : durée du tour et coût de ce tour."""
        parts = [f"✓ Terminé en {_duration(seconds)}"]
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
        if action:
            label, callback = action
            button = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
            button.connect("clicked", lambda b: callback())
            row.append(button)
        return row

    def add_user(self, text, images=(), during=False):
        self._append(self._user_widget(text, images, during))
        self.scroll_end_if_stuck()

    def _segment(self, msg_id, create=True):
        seg = self._segs.get(msg_id)
        if seg is not None and seg.bubble is self._last and not seg.closed:
            return seg
        if not create:
            return None
        bubble, view = self._assistant_widget()
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
        return self.box.observe_children().get_n_items() - 1

    def load_history(self, messages):
        """Montre `messages` (preview.Message) : les derniers d'abord, les plus anciens au
        défilement vers le haut."""
        self._hist, self._hist_pos = list(messages), len(messages)
        self._stick = True
        self._load_more(initial=True)

    def _history_widget(self, m):
        if m.role == preview.USER:
            return self._user_widget(m.text)
        if m.role == preview.ASSISTANT:
            if not (m.text or "").strip():
                return None
            bubble, _view = self._assistant_widget(m.text)
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
        prev = None
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
