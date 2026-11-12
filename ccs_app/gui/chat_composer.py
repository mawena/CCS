"""Zone de saisie du chat, comme celle de l'extension Claude Code de VS Code.

Entrée envoie, Maj+Entrée va à la ligne ; `@` propose des fichiers, `/` des commandes ; une
image collée ou glissée devient une vignette ; un fichier glissé insère `@chemin` ; Échap
arrête Claude pendant qu'il travaille. Les messages écrits pendant ce temps rejoignent la file
(`TabState.queue`, tenue par l'onglet et par la page Terminaux) : ce module n'en montre que
les lignes.
"""

import os
import re

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, GtkSource, Pango  # noqa: E402

from .chat_messages import install_css  # noqa: E402

IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".webp": "image/webp"}
IMAGE_MAX_BYTES = 10 * 1024 * 1024
MAX_CHOICES = 12
FILE_TOKEN = re.compile(r"(?:^|\s)@([^\s@]*)$")
COMMAND_TOKEN = re.compile(r"^/([^\s/]*)$")

# Indications dans le texte gris de la zone vide (plus de ligne à part sous la saisie).
HINT_IDLE = "Écris à Claude…  (@ fichiers · / commandes)"
HINT_BUSY = "Claude travaille — écris quand même, Entrée envoie · Échap arrête"
SEND_TIP = "Envoyer (Entrée) · Maj+Entrée : nouvelle ligne"


def _command(item):
    """(nom, description) d'une commande annoncée par Claude Code (texte, couple ou dict)."""
    if isinstance(item, dict):
        return str(item.get("name") or item.get("command") or ""), str(item.get("description") or "")
    if isinstance(item, (tuple, list)):
        return str(item[0]), str(item[1]) if len(item) > 1 else ""
    return str(item), ""


class Composer(Gtk.Box):
    """Zone de saisie. Signaux : `send(text, images)` (images : liste de (type, octets)),
    `stop()`, et pour la file de messages `queue-edit(index, texte, ancien)`,
    `queue-move(index, delta)`, `queue-remove(index)`, `queue-send-now(index)`."""

    __gsignals__ = {
        "send": (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
        "stop": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "queue-edit": (GObject.SignalFlags.RUN_FIRST, None, (int, str, str)),
        "queue-move": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "queue-remove": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "queue-send-now": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, base_dir=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=12, margin_end=12,
                         margin_top=6, margin_bottom=4)
        install_css()
        GtkSource.init()
        self.base_dir = base_dir
        self.busy = False
        self.images = []                 # [(type MIME, octets)]
        self._commands = []              # [(nom, description)]
        self._files = lambda: []
        self._token = None               # (type, début, fin) de la complétion en cours
        self._queue_shown = None

        self._build_queue()

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["ccs-composer"])
        self.thumbs = Gtk.Box(spacing=8, visible=False, margin_start=2, margin_top=2)
        card.append(Gtk.ScrolledWindow(child=self.thumbs, vscrollbar_policy=Gtk.PolicyType.NEVER,
                                       hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, propagate_natural_height=True))
        self.view = GtkSource.View(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False, top_margin=6,
                                   bottom_margin=6, left_margin=6, right_margin=6, hexpand=True)
        self.buffer = self.view.get_buffer()
        self.buffer.set_highlight_syntax(False)
        self.buffer.connect("changed", self._on_changed)
        # Le tampon garde sinon le schéma clair par défaut : texte noir sur fond sombre.
        style = Adw.StyleManager.get_default()
        self.set_dark(style.get_dark())
        style.connect("notify::dark", lambda sm, _p: self.set_dark(sm.get_dark()))
        overlay = Gtk.Overlay(hexpand=True, child=Gtk.ScrolledWindow(
            child=self.view, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
            min_content_height=40, max_content_height=220))
        self.placeholder = Gtk.Label(label=HINT_IDLE, xalign=0, halign=Gtk.Align.START,
                                     valign=Gtk.Align.START, margin_start=12, margin_top=12,
                                     ellipsize=Pango.EllipsizeMode.END, css_classes=["ccs-subtle"],
                                     can_target=False)
        overlay.add_overlay(self.placeholder)

        self.stop_button = Gtk.Button(icon_name="media-playback-stop-symbolic", css_classes=["circular"],
                                      tooltip_text="Arrêter Claude (Échap)", visible=False)
        self.stop_button.connect("clicked", lambda *_: self.emit("stop"))
        self.send_button = Gtk.Button(icon_name="go-up-symbolic", css_classes=["circular", "suggested-action"],
                                      tooltip_text=SEND_TIP)
        self.send_button.connect("clicked", lambda *_: self.submit())
        # Boutons à droite du texte, comme dans VS Code : pas de ligne à part sous la saisie.
        buttons = Gtk.Box(spacing=6, valign=Gtk.Align.END, margin_bottom=4, margin_end=2)
        buttons.append(self.stop_button)
        buttons.append(self.send_button)
        self.input_row = Gtk.Box(spacing=6)
        self.input_row.append(overlay)
        self.input_row.append(buttons)
        card.append(self.input_row)
        self.card = card
        self.append(card)

        self._build_popover()
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.view.add_controller(keys)
        drop = Gtk.DropTarget(actions=Gdk.DragAction.COPY)
        drop.set_gtypes([Gdk.FileList, str])
        drop.connect("enter", lambda *_: (self.card.add_css_class("drop"), Gdk.DragAction.COPY)[1])
        drop.connect("leave", lambda *_: self.card.remove_css_class("drop"))
        drop.connect("drop", self._on_drop)
        self.card.add_controller(drop)

    def do_dispose(self):
        self.popover.unparent()
        Gtk.Box.do_dispose(self)

    # ---- file de messages ----------------------------------------------------------------

    def _build_queue(self):
        self.queue_count = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        show = Gtk.Button(label="Afficher", css_classes=["flat"])
        show.connect("clicked", lambda *_: self.toggle_queue(True))
        strip = Gtk.Box(spacing=8, css_classes=["ccs-queue-strip"])
        for w in (Gtk.Image(icon_name="mail-send-symbolic"), self.queue_count, show):
            strip.append(w)
        self.queue_strip = Gtk.Revealer(child=strip)

        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label="Messages en attente", xalign=0, css_classes=["heading"]))
        self.queue_status = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                      css_classes=["dim-label", "caption"])
        head.append(self.queue_status)
        fold = Gtk.Button(icon_name="pan-down-symbolic", css_classes=["flat"], tooltip_text="Replier")
        fold.connect("clicked", lambda *_: self.toggle_queue(False))
        head.append(fold)
        self.queue_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["ccs-queue"])
        box.append(head)
        box.append(self.queue_rows)
        self.queue_rev = Gtk.Revealer(child=box)
        self.append(self.queue_strip)
        self.append(self.queue_rev)

    def toggle_queue(self, show=None):
        show = (not self.queue_rev.get_reveal_child()) if show is None else show
        self.queue_rev.set_reveal_child(show)
        self._queue_strip_update()
        if not show:
            self.focus()

    def _queue_strip_update(self):
        self.queue_strip.set_reveal_child(bool(self._queue_shown) and not self.queue_rev.get_reveal_child())

    def set_queue(self, queue, reason=None):
        """Montre la file (`TabState.queue`) et pourquoi elle attend. Les lignes ne sont refaites
        que si la file a changé, pour ne pas interrompre une modification en cours."""
        queue = list(queue)
        n = len(queue)
        count = "1 message en attente" if n == 1 else f"{n} messages en attente"
        self.queue_count.set_label(count + (f" — {reason}" if reason else ""))
        self.queue_status.set_label(reason or ("" if queue else "Aucun message en attente."))
        changed = queue != self._queue_shown
        self._queue_shown = queue
        if not queue:
            self.queue_rev.set_reveal_child(False)
        self._queue_strip_update()
        if not changed:
            return
        _clear = self.queue_rows
        while (child := _clear.get_first_child()) is not None:
            _clear.remove(child)
        for i, text in enumerate(queue):
            row = Gtk.Box(spacing=4, css_classes=["ccs-queue-row"])
            row.append(Gtk.Label(label=f"{i + 1}.", css_classes=["dim-label"]))
            label = Gtk.EditableLabel(text=text, hexpand=True, tooltip_text="Cliquer pour modifier")
            label.connect("notify::editing", lambda w, _p, i=i, old=text: None if w.get_editing()
                          else self.emit("queue-edit", i, w.get_text(), old))
            row.append(label)
            for icon, tip, signal, args, sensitive in (
                    ("go-up-symbolic", "Monter", "queue-move", (i, -1), i > 0),
                    ("mail-send-symbolic", "Envoyer maintenant", "queue-send-now", (i,), True),
                    ("edit-delete-symbolic", "Retirer", "queue-remove", (i,), True)):
                b = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["flat"], sensitive=sensitive)
                b.connect("clicked", lambda _b, s=signal, a=args: self.emit(s, *a))
                row.append(b)
            self.queue_rows.append(row)

    # ---- état ----------------------------------------------------------------------------

    def set_dark(self, dark):
        """Schéma de couleurs du texte saisi, lisible en clair comme en sombre."""
        manager = GtkSource.StyleSchemeManager.get_default()
        for name in (("Adwaita-dark", "classic-dark") if dark else ("Adwaita", "classic")):
            scheme = manager.get_scheme(name)
            if scheme:
                self.buffer.set_style_scheme(scheme)
                return

    def set_busy(self, busy):
        """Pendant que Claude travaille : bouton Arrêter ; Entrée envoie quand même."""
        self.busy = bool(busy)
        self.stop_button.set_visible(self.busy)
        self.placeholder.set_label(HINT_BUSY if self.busy else HINT_IDLE)
        self.send_button.set_tooltip_text(SEND_TIP + (" · même pendant que Claude travaille" if self.busy else ""))

    def set_enabled(self, enabled):
        self.view.set_editable(bool(enabled))
        self.send_button.set_sensitive(bool(enabled))

    def set_base_dir(self, base_dir):
        self.base_dir = base_dir

    def focus(self):
        GLib.idle_add(lambda: (self.view.grab_focus(), False)[1])

    @property
    def text(self):
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False)

    def set_text(self, text):
        self.buffer.set_text(text)

    def insert_text(self, text):
        self.buffer.insert_at_cursor(text)

    def clear(self):
        self.buffer.set_text("")
        self.images.clear()
        self._refresh_thumbs()
        self._close_popover()

    def restore(self, text, images=()):
        """Remet un message que l'onglet n'a pas pu envoyer."""
        self.buffer.set_text(text)
        self.images[:] = list(images)
        self._refresh_thumbs()

    def submit(self):
        """Envoie le texte (et les images) : ne fait rien si tout est vide."""
        text, images = self.text.strip(), list(self.images)
        if not text and not images:
            return False
        self.clear()
        self.emit("send", text, images)
        return True

    def _on_changed(self, *_):
        self.placeholder.set_visible(self.buffer.get_char_count() == 0)
        self._update_completion()

    # ---- images --------------------------------------------------------------------------

    def add_image(self, media_type, data):
        self.images.append((media_type, bytes(data)))
        self._refresh_thumbs()

    def _refresh_thumbs(self):
        while (child := self.thumbs.get_first_child()) is not None:
            self.thumbs.remove(child)
        for i, (_t, data) in enumerate(self.images):
            overlay = Gtk.Overlay()
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                overlay.set_child(Gtk.Picture(paintable=texture, content_fit=Gtk.ContentFit.COVER,
                                              width_request=72, height_request=72, css_classes=["ccs-thumb"]))
            except GLib.Error:
                overlay.set_child(Gtk.Image(icon_name="image-x-generic-symbolic", pixel_size=48))
            close = Gtk.Button(icon_name="window-close-symbolic", css_classes=["circular", "osd"],
                               halign=Gtk.Align.END, valign=Gtk.Align.START, tooltip_text="Retirer l'image")
            close.connect("clicked", lambda _b, i=i: self._remove_image(i))
            overlay.add_overlay(close)
            self.thumbs.append(overlay)
        self.thumbs.set_visible(bool(self.images))

    def _remove_image(self, index):
        if 0 <= index < len(self.images):
            del self.images[index]
            self._refresh_thumbs()

    def _paste_image(self):
        """Colle l'image du presse-papiers ; faux s'il n'y en a pas (le collage de texte suit)."""
        clipboard = self.get_clipboard()
        formats = clipboard.get_formats()
        if not formats.contain_gtype(Gdk.Texture) or formats.contain_gtype(str):
            return False

        def done(cb, result):
            try:
                texture = cb.read_texture_finish(result)
                if texture is not None:
                    self.add_image("image/png", texture.save_to_png_bytes().get_data())
            except GLib.Error:
                pass
        clipboard.read_texture_async(None, done)
        return True

    def _on_drop(self, _target, value, _x, _y):
        self.card.remove_css_class("drop")
        paths = []
        if isinstance(value, Gdk.FileList):
            paths = [f.get_path() for f in value.get_files() if f.get_path()]
        elif isinstance(value, str):
            for line in value.splitlines():
                line = line.strip()
                if line.startswith("file://"):
                    line = Gio.File.new_for_uri(line).get_path() or ""
                if line.startswith("/"):
                    paths.append(line)
        for path in paths:
            self.add_path(path)
        self.focus()
        return bool(paths)

    def add_path(self, path):
        """Un fichier glissé : une image devient une vignette, le reste une référence `@chemin`."""
        media = IMAGE_EXT.get(os.path.splitext(path)[1].lower())
        if media:
            try:
                if os.path.getsize(path) <= IMAGE_MAX_BYTES:
                    with open(path, "rb") as fh:
                        self.add_image(media, fh.read())
                    return
            except OSError:
                pass
        self.insert_reference(path)

    def insert_reference(self, path):
        """Insère `@chemin` (relatif au projet s'il y est) à la position du curseur."""
        rel = path
        if self.base_dir and path.startswith(str(self.base_dir).rstrip("/") + "/"):
            rel = os.path.relpath(path, self.base_dir)
        before = self.text[:self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset()]
        lead = "" if not before or before[-1].isspace() else " "
        self.buffer.insert_at_cursor(f"{lead}@{rel} ")

    # ---- complétion ----------------------------------------------------------------------

    def set_commands(self, commands):
        """Commandes proposées après `/` (annoncées par Claude Code, plus les personnalisées)."""
        seen, out = set(), []
        for item in commands or ():
            name, desc = _command(item)
            name = name.lstrip("/")
            if name and name not in seen:
                seen.add(name)
                out.append((name, desc))
        self._commands = sorted(out)

    def set_file_source(self, source):
        """`source()` renvoie les fichiers du projet (chemins relatifs) proposés après `@`."""
        self._files = source

    def _build_popover(self):
        self.choices = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, css_classes=["navigation-sidebar"])
        self.choices.connect("row-activated", lambda _l, row: self._accept(row))
        scroll = Gtk.ScrolledWindow(child=self.choices, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    propagate_natural_height=True, max_content_height=240, min_content_width=360)
        self.popover = Gtk.Popover(child=scroll, autohide=False, has_arrow=False, position=Gtk.PositionType.TOP)
        self.popover.set_parent(self.card)
        self.popover.set_halign(Gtk.Align.START)

    def _close_popover(self):
        self._token = None
        self.popover.popdown()

    def popover_visible(self):
        return self.popover.get_visible()

    def _update_completion(self):
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        before = self.buffer.get_text(self.buffer.get_start_iter(), cursor, False)
        offset = cursor.get_offset()
        items, token = [], None
        m = COMMAND_TOKEN.match(before)
        if m and self._commands:
            q = m.group(1).lower()
            token = ("/", 0, offset)
            items = [("/" + n, d, "/" + n + " ") for n, d in self._commands if q in n.lower()
                     ][:MAX_CHOICES]
            items.sort(key=lambda it: not it[0][1:].lower().startswith(q))
        else:
            m = FILE_TOKEN.search(before)
            if m:
                q = m.group(1).lower()
                token = ("@", offset - len(m.group(1)) - 1, offset)
                try:
                    files = list(self._files() or ())
                except Exception:  # noqa: BLE001 — une source de fichiers ne doit jamais bloquer la saisie
                    files = []
                hits = [f for f in files if q in f.lower()]
                hits.sort(key=lambda f: (not os.path.basename(f).lower().startswith(q), len(f)))
                items = [(os.path.basename(f) or f, os.path.dirname(f), "@" + f + " ") for f in hits[:MAX_CHOICES]]
        if not items:
            self._close_popover()
            return
        self._token = token
        while (child := self.choices.get_first_child()) is not None:
            self.choices.remove(child)
        for title, sub, insert in items:
            row = Gtk.ListBoxRow()
            row.insert_text = insert
            box = Gtk.Box(spacing=10, margin_start=6, margin_end=6, margin_top=3, margin_bottom=3)
            box.append(Gtk.Label(label=title, xalign=0, css_classes=["heading"] if token[0] == "/" else []))
            box.append(Gtk.Label(label=sub, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE,
                                 css_classes=["ccs-subtle"]))
            row.set_child(box)
            self.choices.append(row)
        self.choices.select_row(self.choices.get_row_at_index(0))
        if not self.popover.get_visible():
            self.popover.popup()

    def _move_choice(self, delta):
        row = self.choices.get_selected_row()
        index = (row.get_index() if row else -1) + delta
        count = 0
        while self.choices.get_row_at_index(count) is not None:
            count += 1
        if count:
            self.choices.select_row(self.choices.get_row_at_index(index % count))

    def _accept(self, row=None):
        row = row or self.choices.get_selected_row()
        if row is None or self._token is None:
            return False
        _kind, start, end = self._token
        a, b = self.buffer.get_iter_at_offset(start), self.buffer.get_iter_at_offset(end)
        self._close_popover()
        self.buffer.begin_user_action()
        self.buffer.delete(a, b)
        self.buffer.insert(self.buffer.get_iter_at_offset(start), row.insert_text)
        self.buffer.end_user_action()
        return True

    # ---- clavier -------------------------------------------------------------------------

    def _on_key(self, _ctrl, keyval, _code, state):
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if self.popover.get_visible():
            if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
                self._move_choice(1 if keyval == Gdk.KEY_Down else -1)
                return True
            if keyval in (Gdk.KEY_Tab, Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not shift:
                return self._accept()
            if keyval == Gdk.KEY_Escape:
                self._close_popover()
                return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not shift:
            self.submit()
            return True
        if keyval == Gdk.KEY_Escape and self.busy:
            self.emit("stop")
            return True
        if ctrl and keyval in (Gdk.KEY_v, Gdk.KEY_V) and not shift:
            return self._paste_image()
        return False
