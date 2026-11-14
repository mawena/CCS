"""Rendu Markdown natif (sans WebKit) : sert au chat et à l'aperçu des fichiers."""

from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

gi.require_version("GtkSource", "5")
from gi.repository import GdkPixbuf, Gtk, GtkSource, Pango  # noqa: E402

from .. import markdown_render as md  # noqa: E402

IMAGE_MAX_WIDTH = 600
LIST_INDENT = 22        # px : du début de la puce au début du texte (liste courte en un label)
SHORT_ITEM = 60         # caractères : un élément plus court tient sur une ligne dans le chat
_HEADING_CLASS = {1: "title-1", 2: "title-2", 3: "title-3"}
_ALIGN = {"left": 0.0, "center": 0.5, "right": 1.0, None: 0.0}


def stable_end(text):
    """Fin de la partie « terminée » d'un texte en cours d'écriture : juste après la dernière
    ligne vide hors d'un bloc de code. Les blocs avant ne changeront plus (sauf rares cas :
    liste espacée), ceux d'après sont encore en train de s'écrire."""
    fence, offset, last = None, 0, 0
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if fence:
            if s.startswith(fence):
                fence = None
        elif s.startswith("```") or s.startswith("~~~"):
            fence = s[:3]
        elif not s and line.endswith("\n") and offset > 0:
            last = offset + len(line)
        offset += len(line)
    return last


class MarkdownView(Gtk.Box):
    """Colonne de widgets : un par bloc Markdown. Le texte est sélectionnable."""

    def __init__(self, text="", base_dir=None, on_link=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.base_dir = Path(base_dir) if base_dir else None
        self.on_link = on_link
        self._dark = False
        self._buffers = []
        self._stable = None          # flux : texte déjà rendu en blocs définitifs
        self._stable_buffers = 0     # flux : tampons de code des blocs définitifs
        self._tail = []              # flux : widgets du dernier bloc, encore en écriture
        self.set_text(text)

    # -- API publique --------------------------------------------------------

    def set_text(self, text):
        """Remplace tout le contenu par le rendu de `text`."""
        child = self.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.remove(child)
            child = nxt
        self._buffers = []
        self._stable, self._tail = None, []
        for widget in self._build(md.parse(text or "")):
            self.append(widget)

    def set_text_streaming(self, text):
        """Pendant que Claude écrit : seuls les blocs encore ouverts (après la dernière ligne
        vide) sont refaits ; les blocs terminés restent en place. Coût constant au lieu de
        tout refaire à chaque morceau (une longue réponse figeait l'interface). `set_text`
        refait le rendu exact à la fin."""
        text = text or ""
        cut = stable_end(text)
        stable = text[:cut]
        if self._stable is None or not stable.startswith(self._stable):
            self.set_text("")
            self._stable, self._stable_buffers = "", 0
        for widget in self._tail:
            self.remove(widget)
        self._tail = []
        del self._buffers[self._stable_buffers:]
        new = stable[len(self._stable):]
        if new.strip():
            for widget in self._build(md.parse(new)):
                self.append(widget)
        self._stable = stable
        self._stable_buffers = len(self._buffers)
        self._tail = self._build(md.parse(text[cut:])) if text[cut:].strip() else []
        for widget in self._tail:
            self.append(widget)

    def set_dark(self, dark):
        """Choisit le thème clair ou sombre de la coloration du code."""
        self._dark = bool(dark)
        for buf in self._buffers:
            buf.set_style_scheme(self._scheme())

    # -- construction --------------------------------------------------------

    def _scheme(self):
        manager = GtkSource.StyleSchemeManager.get_default()
        names = ("Adwaita-dark", "classic-dark") if self._dark else ("Adwaita", "classic")
        for name in names:
            scheme = manager.get_scheme(name)
            if scheme:
                return scheme
        return None

    def _build(self, blocks):
        return [w for w in (self._widget(b) for b in blocks) if w is not None]

    def _widget(self, block):
        if isinstance(block, md.Heading):
            return self._label(block.spans, _HEADING_CLASS.get(block.level, "heading"))
        if isinstance(block, md.Paragraph):
            return self._label(block.spans) if block.spans else None
        if isinstance(block, md.ListBlock):
            return self._list(block)
        if isinstance(block, md.Code):
            return self._code(block)
        if isinstance(block, md.Table):
            return self._table(block)
        if isinstance(block, md.Quote):
            return self._quote(block)
        if isinstance(block, md.Rule):
            return Gtk.Separator(margin_top=4, margin_bottom=4)
        if isinstance(block, md.Image):
            return self._image(block)
        return None

    def _label(self, spans, *css, xalign=0.0):
        label = Gtk.Label(use_markup=True, label=md.to_pango(spans), xalign=xalign, wrap=True,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True, hexpand=True,
                          css_classes=list(css))
        label.connect("activate-link", self._activate_link)
        return label

    def _activate_link(self, label, uri):
        if self.on_link:
            self.on_link(uri)
        else:
            Gtk.UriLauncher(uri=uri).launch(label.get_root(), None, None)
        return True

    def _list(self, block):
        simple = self._simple_list(block)
        if simple is not None:
            return simple
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=8)
        for n, item in enumerate(block.items):
            row = Gtk.Box(spacing=8, valign=Gtk.Align.START)
            if item.checked is not None:
                marker = Gtk.CheckButton(active=item.checked, sensitive=False, valign=Gtk.Align.START)
            else:
                text = f"{block.start + n}." if block.ordered else "•"
                marker = Gtk.Label(label=text, xalign=1.0, yalign=0.0, width_chars=2)
            row.append(marker)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
            for widget in self._build(item.blocks):
                body.append(widget)
            row.append(body)
            column.append(row)
        return column

    def _simple_list(self, block):
        """Liste courte (chaque élément : un seul paragraphe d'au plus SHORT_ITEM caractères, donc
        sur une ligne) : un seul label pour toute la liste au lieu d'une ligne de widgets par
        élément (4 fois moins de mémoire, 35 fois plus rapide à construire). None sinon : un
        élément long garde son retrait suspendu, une liste imbriquée ou à cases ses widgets."""
        lines = []
        for n, item in enumerate(block.items):
            if item.checked is not None or len(item.blocks) != 1 or not isinstance(item.blocks[0], md.Paragraph):
                return None
            spans = item.blocks[0].spans
            if sum(len(s.text) for s in spans) > SHORT_ITEM:
                return None
            marker = f"{block.start + n}." if block.ordered else "•"
            lines.append(f"{marker}\t{md.to_pango(spans)}")
        tabs = Pango.TabArray.new(1, True)
        tabs.set_tab(0, Pango.TabAlign.LEFT, LIST_INDENT)
        label = self._label([], xalign=0.0)
        label.set_markup("\n".join(lines))
        label.set_tabs(tabs)
        label.set_margin_start(8)
        label.add_css_class("ccs-md-list")
        return label

    def _code(self, block):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"])
        header = Gtk.Box(spacing=6, margin_start=10, margin_end=4, margin_top=2)
        header.append(Gtk.Label(label=block.lang, xalign=0.0, hexpand=True, css_classes=["dim-label", "caption"]))
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copier", css_classes=["flat"])
        copy.connect("clicked", lambda b: b.get_clipboard().set(block.text))
        header.append(copy)
        box.append(header)
        buf = GtkSource.Buffer()
        buf.set_text(block.text)
        lang = GtkSource.LanguageManager.get_default().get_language(block.lang.lower()) if block.lang else None
        if lang:
            buf.set_language(lang)
        buf.set_highlight_syntax(lang is not None)
        scheme = self._scheme()
        if scheme:
            buf.set_style_scheme(scheme)
        self._buffers.append(buf)
        view = GtkSource.View(buffer=buf, editable=False, cursor_visible=False, monospace=True,
                              left_margin=10, right_margin=10, top_margin=4, bottom_margin=8)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                      vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
        scroller.set_child(view)
        box.append(scroller)
        return box

    def _table(self, block):
        grid = Gtk.Grid(column_spacing=16, row_spacing=6, halign=Gtk.Align.START)
        for c, spans in enumerate(block.header):
            align = block.align[c] if c < len(block.align) else None
            bold = [md.Span(s.text, bold=True, italic=s.italic, code=s.code, strike=s.strike, link=s.link)
                    for s in spans]
            grid.attach(self._label(bold, xalign=_ALIGN.get(align, 0.0)), c, 0, 1, 1)
        for r, row in enumerate(block.rows, start=1):
            for c, spans in enumerate(row):
                align = block.align[c] if c < len(block.align) else None
                grid.attach(self._label(spans, xalign=_ALIGN.get(align, 0.0)), c, r, 1, 1)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                      vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
        scroller.set_child(grid)
        return scroller

    def _quote(self, block):
        row = Gtk.Box(spacing=8)
        row.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True, css_classes=["dim-label"])
        for widget in self._build(block.blocks):
            body.append(widget)
        row.append(body)
        return row

    def _image(self, block):
        local = self._local_path(block.src)
        if local is None:
            uri = md.escape(block.src).replace('"', "&quot;")
            label = Gtk.Label(use_markup=True, xalign=0.0, wrap=True, selectable=True,
                              label=f'image distante : <a href="{uri}">{md.escape(block.alt) or uri}</a>')
            label.connect("activate-link", self._activate_link)
            return label
        if not local.is_file():
            return Gtk.Label(label=f"image introuvable : {block.alt or block.src}", xalign=0.0,
                             css_classes=["dim-label"])
        picture = Gtk.Picture.new_for_filename(str(local))
        picture.set_can_shrink(True)
        picture.set_halign(Gtk.Align.START)
        info = GdkPixbuf.Pixbuf.get_file_info(str(local))
        width = info[1] if info and info[0] else IMAGE_MAX_WIDTH
        picture.set_size_request(min(width, IMAGE_MAX_WIDTH), -1)
        picture.set_alternative_text(block.alt)
        return picture

    def _local_path(self, src):
        """Chemin local d'une image, ou `None` pour une adresse distante (jamais chargée)."""
        parsed = urlparse(src)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path))
        if parsed.scheme or src.startswith("//"):
            return None
        path = Path(unquote(src))
        if path.is_absolute():
            return path
        return (self.base_dir / path) if self.base_dir else Path("/nonexistent") / path
