"""Dialogue d'aperçu d'une conversation : lecture seule, copie et export en Markdown."""

from datetime import datetime
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .. import conversations, core, costs, fiche, preview
from .common import in_thread
from .fiche_view import FicheView

PREVIEW_LIMIT = 300        # messages affichés d'abord (les plus récents)
UI_TEXT_MAX = 20_000       # au-delà, un message est tronqué à l'écran (l'export reste complet)
RENDER_CHUNK = 150         # messages construits par passage de la boucle GTK

CSS = b"""
.ccs-bubble { padding: 10px 14px; border-radius: 12px; }
.ccs-bubble-user { background-color: alpha(@accent_bg_color, 0.16); }
.ccs-bubble-assistant { background-color: alpha(currentColor, 0.05); }
.ccs-tools { padding: 2px 4px; }
.ccs-tool-result { font-family: monospace; font-size: 0.85em; padding: 6px 10px;
                   border-radius: 6px; background-color: alpha(currentColor, 0.06); }
.ccs-note { font-style: italic; }
"""
_css_installed = False


def _install_css():
    global _css_installed
    display = Gdk.Display.get_default()
    if _css_installed or display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS, -1)
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_installed = True


def _label(text, *css, selectable=True):
    if len(text) > UI_TEXT_MAX:
        text = text[:UI_TEXT_MAX] + "\n\n… (message tronqué à l'écran : exporte en Markdown pour tout lire)"
    return Gtk.Label(label=text, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                     selectable=selectable, use_markup=False, css_classes=list(css))


def _when(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M") if ts else ""


class PreviewDialog(Adw.Dialog):
    """Conversation affichée sans la reprendre. `conversation` : objet
    `conversations.Conversation` (chemin du journal, titre, projet, dates…)."""

    def __init__(self, conversation, limit=PREVIEW_LIMIT):
        super().__init__(title=conversation.title or "Conversation", content_width=780, content_height=760)
        _install_css()
        self.conv = conversation
        self.limit = limit
        self.messages = []
        self.generation = 0        # numéro du rendu en cours (rendu par lots)
        self.scroll_top = False    # après « de plus » : montrer le haut (messages plus anciens)

        header = Adw.HeaderBar()
        self.heading = Adw.WindowTitle(title=conversation.title or "Conversation",
                                       subtitle=conversation.project)
        header.set_title_widget(self.heading)
        self.copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", sensitive=False,
                                   tooltip_text="Copier la conversation (Markdown)")
        self.copy_btn.connect("clicked", self.on_copy)
        header.pack_start(self.copy_btn)
        self.export_btn = Gtk.Button(label="Exporter en Markdown…", sensitive=False,
                                     css_classes=["suggested-action"])
        self.export_btn.connect("clicked", self.on_export)
        header.pack_end(self.export_btn)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.fiche_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)   # fiche « où j'en étais »
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                         margin_top=12, margin_bottom=18, margin_start=12, margin_end=12)
        column.append(self.fiche_box)
        column.append(self.body)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                           child=Adw.Clamp(maximum_size=760, child=column))
        self.toasts = Adw.ToastOverlay(child=self.scroller)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_child(view)
        self.load()

    # ---- lecture ---------------------------------------------------------------------

    def load(self):
        self.show_status("content-loading-symbolic", "Lecture de la conversation…", spinner=True)
        conv, path, limit = self.conv, self.conv.path, self.limit

        def work():
            try:
                msgs = preview.read_messages(path, limit=limit + 1 if limit else None)
                cost = conversations.cost_for_path(path)
                try:
                    card = fiche.build(conv)
                except (OSError, ValueError):
                    card = None   # la fiche est un plus : l'aperçu s'affiche sans elle
                return msgs, cost, card
            except OSError as e:
                return e
        in_thread(work, self.loaded)

    def loaded(self, result):
        if isinstance(result, OSError):
            self.show_status("dialog-error-symbolic", "Lecture impossible",
                             f"{result.strerror or result} ({result.filename or self.conv.path})")
            return
        msgs, cost, card = result
        self.cost = cost
        while (child := self.fiche_box.get_first_child()) is not None:
            self.fiche_box.remove(child)
        if card is not None and (card.last_request or card.last_reply):
            self.fiche_box.append(FicheView(card))
        truncated = bool(self.limit) and len(msgs) > self.limit
        self.messages = msgs[1:] if truncated else msgs
        sub = [self.conv.project] + (["archivée"] if self.conv.archived else [])
        if cost.reponses:
            sub.append(costs.format_cost(cost))
        self.heading.set_subtitle(" · ".join(s for s in sub if s))
        self.copy_btn.set_sensitive(True)
        self.export_btn.set_sensitive(True)
        self.render(truncated)

    # ---- rendu -----------------------------------------------------------------------

    def clear(self):
        self.generation += 1  # arrête un rendu par lots encore en cours
        while (child := self.body.get_first_child()) is not None:
            self.body.remove(child)

    def show_status(self, icon, title, description="", spinner=False):
        self.clear()
        if spinner:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER,
                          margin_top=64)
            sp = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
            sp.set_size_request(32, 32)
            box.append(sp)
            box.append(Gtk.Label(label=title, css_classes=["dim-label"]))
            self.body.append(box)
        else:
            self.body.append(Adw.StatusPage(icon_name=icon, title=title, description=description))

    def render(self, truncated):
        self.clear()
        if truncated:
            # Pas de « tout afficher » : des milliers de messages figeraient la mise en page.
            banner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER,
                             margin_bottom=6)
            banner.append(Gtk.Label(label=f"Les {self.limit} derniers messages sont affichés. Pour tout lire "
                                          "d'un coup, exporte la conversation en Markdown.",
                                    wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"]))
            more = Gtk.Button(label=f"Afficher {PREVIEW_LIMIT} messages de plus", halign=Gtk.Align.CENTER,
                              css_classes=["pill", "small"])
            more.connect("clicked", self.on_more)
            banner.append(more)
            self.body.append(banner)
        if not self.messages:
            self.body.append(Adw.StatusPage(icon_name="chat-message-new-symbolic", title="Aucun message lisible",
                                            description="Cette conversation ne contient pas d'échange à afficher."))
            return
        # Construction par lots dans une boîte encore détachée (pas de mise en page à chaque
        # lot), attachée en une fois : la fenêtre reste réactive pendant la construction.
        gen, msgs = self.generation, self.messages
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        state = {"i": 0, "tools": None, "box": content}
        waiting = None
        if len(msgs) > RENDER_CHUNK:
            waiting = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=24)
            sp = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
            waiting.append(sp)
            waiting.append(Gtk.Label(label=f"Mise en page de {len(msgs)} messages…", css_classes=["dim-label"]))
            self.body.append(waiting)

        def step():
            if gen != self.generation:
                return False  # rendu remplacé par un plus récent
            end = min(len(msgs), state["i"] + RENDER_CHUNK)
            for m in msgs[state["i"]:end]:
                self.append_message(m, state)
            state["i"] = end
            if end < len(msgs):
                return True
            if waiting is not None:
                self.body.remove(waiting)
            self.body.append(content)
            # Ouverture : on montre la fin (là où la conversation s'est arrêtée) ; après
            # « de plus », le haut, où apparaissent les messages plus anciens.
            GLib.idle_add(self.scroll_to, self.scroll_top)
            return False

        if step():
            GLib.idle_add(step)
        self.export_btn.grab_focus()  # sinon le premier texte sélectionnable est tout sélectionné

    def append_message(self, m, state):
        box = state["box"]
        if m.role == preview.TOOL:
            if state["tools"] is None:  # appels d'outils consécutifs : un seul bloc compact
                state["tools"] = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["ccs-tools"])
                box.append(state["tools"])
            state["tools"].append(self.tool_row(m))
            return
        state["tools"] = None
        if m.role == preview.USER:
            box.append(self.bubble("Toi", m, "ccs-bubble-user", Gtk.Align.END))
        elif m.role == preview.ASSISTANT:
            box.append(self.bubble("Claude", m, "ccs-bubble-assistant", Gtk.Align.FILL))
        else:
            box.append(_label(m.text, "dim-label", "ccs-note", "caption", selectable=False))

    def bubble(self, who, m, css, halign):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=halign,
                      css_classes=["ccs-bubble", css])
        if halign == Gtk.Align.END:
            box.set_margin_start(80)
        head = f"{who} · {_when(m.ts)}" if m.ts else who
        box.append(Gtk.Label(label=head, xalign=0, css_classes=["caption-heading", "dim-label"]))
        box.append(_label(m.text))
        return box

    def tool_row(self, m):
        tool = m.tool or preview.ToolCall(m.text)
        title = f"{tool.label} · {tool.target}" if tool.target else tool.label
        if tool.is_error:
            title += "  (erreur)"
        head = Gtk.Box(spacing=6)
        head.append(Gtk.Image(icon_name="dialog-error-symbolic" if tool.is_error else "applications-system-symbolic",
                              css_classes=["error" if tool.is_error else "dim-label"]))
        head.append(Gtk.Label(label=title, xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True,
                              css_classes=["caption", "dim-label"], tooltip_text=title))
        if not tool.result:
            head.set_margin_start(18)  # aligné avec les lignes repliables
            return head
        exp = Gtk.Expander(label_widget=head)
        exp.set_child(_label(tool.result, "ccs-tool-result"))
        return exp

    def scroll_to(self, top):
        adj = self.scroller.get_vadjustment()
        adj.set_value(0 if top else adj.get_upper() - adj.get_page_size())
        return False

    # ---- actions -----------------------------------------------------------------------

    def on_more(self, *_):
        self.limit = (self.limit or 0) + PREVIEW_LIMIT
        self.scroll_top = True
        self.load()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def on_copy(self, *_):
        conv = self.conv
        in_thread(lambda: _safe(lambda: preview.markdown_for(conv)), self.copied)

    def copied(self, result):
        if isinstance(result, Exception):
            self.toast(f"Copie impossible : {result}")
            return
        self.get_clipboard().set(result)
        self.toast("Conversation copiée (Markdown)")

    def on_export(self, *_):
        dialog = Gtk.FileDialog(title="Exporter la conversation en Markdown", modal=True,
                                initial_name=preview.suggested_filename(self.conv), accept_label="Exporter")
        docs = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        start = docs if docs and Path(docs).is_dir() else str(core.paths().home)
        dialog.set_initial_folder(Gio.File.new_for_path(start))
        md = Gtk.FileFilter(name="Markdown")
        md.add_pattern("*.md")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(md)
        dialog.set_filters(filters)

        def done(d, result):
            try:
                chosen = d.save_finish(result)
            except GLib.Error:
                return  # annulé
            path = chosen.get_path() if chosen is not None else None
            if not path:
                return
            conv = self.conv
            cost = costs.format_cost(self.cost) if getattr(self, "cost", None) is not None else None
            in_thread(lambda: _safe(lambda: preview.export_markdown(conv, path, cost=cost)), self.exported)
        dialog.save(self.get_root(), None, done)

    def exported(self, result):
        if isinstance(result, Exception):
            self.toast(f"Export impossible : {result}")
        else:
            self.toast(f"Exporté : {Path(result).name}")


def _safe(work):
    try:
        return work()
    except (OSError, ValueError) as e:
        return e


def show_preview(parent, conversation, limit=PREVIEW_LIMIT):
    """Ouvre l'aperçu de `conversation` (conversations.Conversation) au-dessus de `parent`."""
    dialog = PreviewDialog(conversation, limit)
    dialog.present(parent)
    return dialog
