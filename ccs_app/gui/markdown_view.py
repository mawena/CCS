"""Rendu Markdown natif (sans WebKit) : sert au chat et à l'aperçu des fichiers."""

import threading
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

gi.require_version("GtkSource", "5")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkSource, Pango  # noqa: E402

from .. import chat_rich  # noqa: E402
from .. import markdown_render as md  # noqa: E402

IMAGE_MAX_WIDTH = 600
LIST_INDENT = 22        # px : du début de la puce au début du texte (liste courte en un label)
SHORT_ITEM = 60         # caractères : un élément plus court tient sur une ligne dans le chat
CELL_WRAP = 40          # caractères : une cellule de tableau plus longue passe à la ligne, à cette largeur
CELL_MAX = 60           # caractères : largeur au plus d'une cellule longue
_HEADING_CLASS = {1: "title-1", 2: "title-2", 3: "title-3"}
_ALIGN = {"left": 0.0, "center": 0.5, "right": 1.0, None: 0.0}
CARD_WIDTH = 220        # px : largeur d'une carte (bloc ```ccs « cartes »)
CARD_PHOTO = 140        # px : hauteur de sa photo
FORM_WIDTH = 360        # px : largeur d'un formulaire (bloc ```ccs « formulaire »)
IMAGE_MAX_HEIGHT = 400  # px : hauteur au plus d'une image Markdown distante
PHOTO_MAX = 8 * 1024 * 1024   # octets : image distante (photo de carte, image Markdown), au plus
_photos = {}            # adresse -> octets : images distantes déjà téléchargées (30 au plus)


def _fetch(url):
    """Octets d'une image https, ou None. Appelé hors du fil GTK."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CCS"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read(PHOTO_MAX + 1)
        return data if len(data) <= PHOTO_MAX else None
    except (OSError, ValueError):
        return None


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


def _on_activate_link(label, uri):
    """Lien cliqué dans un label du rendu. Fonction du module, pas `self._activate_link` : un
    gestionnaire qui pointe vers la vue parente forme un cycle Python ↔ GTK jamais libéré (chaque
    vue restait en mémoire, même retirée du fil ou refaite pendant le flux)."""
    view = label.get_ancestor(MarkdownView)
    if view is not None:
        return view._activate_link(label, uri)
    return False


_GROUP = "ccs-rich-group"   # boutons d'un même bloc ccs : un seul envoi


_INPUT = "ccs-rich-input"   # champ d'un formulaire, dans l'ordre de `champs`


def _group_of(widget):
    group = widget.get_parent()
    while group is not None and not group.has_css_class(_GROUP):
        group = group.get_parent()
    return group


def _on_rich_send(button, message):
    """Choix, action de carte ou formulaire : le message part une fois, les boutons et champs
    du bloc sont désactivés. Fonction du module (pas de cycle avec la vue, voir
    `_on_activate_link`)."""
    if not message:
        return
    group = _group_of(button)
    for child in _descendants(group) if group is not None else (button,):
        if isinstance(child, (Gtk.Button, Gtk.Entry, Gtk.DropDown)):
            child.set_sensitive(False)
    view = button.get_ancestor(MarkdownView)
    if view is not None and view.on_send:
        view.on_send(message)


def _input_value(widget):
    if isinstance(widget, Gtk.DropDown):
        item = widget.get_selected_item()
        return item.get_string() if item is not None else ""
    return widget.get_text()


def _on_form_send(widget, spec):
    """Formulaire envoyé (bouton, ou Entrée dans un champ) : même message que la version web.
    La fermeture ne retient que `spec` (dict Python), aucun widget : pas de cycle."""
    view = widget.get_ancestor(MarkdownView)
    group = _group_of(widget)
    if group is None or view is None or not view.on_send or not widget.get_sensitive():
        return                                     # déjà envoyé : champs et bouton désactivés
    inputs = [w for w in _descendants(group) if w.has_css_class(_INPUT)]
    values = {f["cle"]: _input_value(w) for f, w in zip(chat_rich.form_fields(spec), inputs)}
    _on_rich_send(widget, chat_rich.form_message(spec, values))


def _size_player(video, kind):
    if kind == "audio":
        video.set_size_request(min(IMAGE_MAX_WIDTH, 360), 48)
    else:
        video.set_size_request(IMAGE_MAX_WIDTH, IMAGE_MAX_WIDTH * 9 // 16)


def _on_remote_play(button, url, kind):
    """« Lire » d'un son ou d'une vidéo https : le lecteur n'est créé qu'à ce moment (GStreamer
    lit l'adresse en continu, dans ses propres fils) ; rien n'est chargé à l'affichage."""
    box = button.get_parent()
    video = Gtk.Video.new_for_file(Gio.File.new_for_uri(url))
    video.set_autoplay(True)
    video.set_halign(Gtk.Align.START)
    video.add_css_class(f"ccs-rich-{kind}")
    video.set_tooltip_text(url)
    _size_player(video, kind)
    box.remove(button)
    box.append(video)


def _load_remote(url, done):
    """Image https : depuis le cache, sinon téléchargée dans un fil à part ; `done(octets ou
    None)` est toujours appelé dans le fil GTK."""
    if url in _photos:
        done(_photos[url])
        return

    def work():
        data = _fetch(url)
        if data is not None:
            if len(_photos) >= 30:
                _photos.pop(next(iter(_photos)), None)
            _photos[url] = data
        GLib.idle_add(lambda: (done(data), False)[1])
    threading.Thread(target=work, daemon=True).start()


def _set_image(picture, fallback, data):
    """Image Markdown distante reçue : affichée dans IMAGE_MAX_WIDTH × IMAGE_MAX_HEIGHT ; en
    cas d'échec, le lien `fallback` prend sa place."""
    texture = None
    if data:
        try:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
        except (GLib.Error, TypeError):
            texture = None
    if texture is None:
        picture.set_visible(False)
        fallback.set_visible(True)
        return
    w, h = texture.get_width(), texture.get_height()
    scale = min(1.0, IMAGE_MAX_WIDTH / max(w, 1), IMAGE_MAX_HEIGHT / max(h, 1))
    picture.set_paintable(texture)
    picture.set_size_request(max(1, int(w * scale)), max(1, int(h * scale)))


def _descendants(widget):
    child = widget.get_first_child()
    while child:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


def _set_photo(picture, data):
    if not data:
        picture.set_visible(False)
        return
    try:
        picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
    except (GLib.Error, TypeError):
        picture.set_visible(False)


class MarkdownView(Gtk.Box):
    """Colonne de widgets : un par bloc Markdown. Le texte est sélectionnable."""

    def __init__(self, text="", base_dir=None, on_link=None, on_send=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.base_dir = Path(base_dir) if base_dir else None
        self.on_link = on_link
        self.on_send = on_send      # on_send(texte) : un choix ou une action de carte répond à Claude
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
            return self._paragraph(block) if block.spans else None
        if isinstance(block, md.ListBlock):
            return self._list(block)
        if isinstance(block, md.Code):
            if block.lang.lower() == "ccs":
                rich = self._rich(chat_rich.parse_block(block.text))
                if rich is not None:
                    return rich
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
        label.connect("activate-link", _on_activate_link)
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
            grid.attach(self._cell(bold, align), c, 0, 1, 1)
        for r, row in enumerate(block.rows, start=1):
            for c, spans in enumerate(row):
                align = block.align[c] if c < len(block.align) else None
                grid.attach(self._cell(spans, align), c, r, 1, 1)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                      vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
        scroller.set_child(grid)
        return scroller

    def _cell(self, spans, align):
        """Cellule de tableau. Le tableau est dans un défilement horizontal : GTK y mesure sa
        hauteur pour sa largeur minimale. Une cellule qui passe librement à la ligne a pour
        minimum un seul mot, et sa hauteur à cette largeur (un mot par ligne) laissait un grand
        vide sous le tableau. Une cellule courte ne passe donc jamais à la ligne ; une longue
        garde une largeur minimale de CELL_WRAP caractères."""
        label = self._label(spans, xalign=_ALIGN.get(align, 0.0))
        label.set_hexpand(False)
        if sum(len(s.text) for s in spans) <= CELL_WRAP:
            label.set_wrap(False)
        else:
            label.set_width_chars(CELL_WRAP)
            label.set_max_width_chars(CELL_MAX)
        return label

    def _quote(self, block):
        row = Gtk.Box(spacing=8)
        row.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True, css_classes=["dim-label"])
        for widget in self._build(block.blocks):
            body.append(widget)
        row.append(body)
        return row

    def _image(self, block):
        player = self._player(block.src, block.alt)
        if player is not None:
            return player
        local = self._local_path(block.src)
        if local is None:
            url = chat_rich.remote_src(block.src)
            if url:
                return self._remote_image(url, block.alt)
            return self._image_link(block.src, block.alt)
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

    def _image_link(self, src, alt):
        uri = md.escape(src).replace('"', "&quot;")
        label = Gtk.Label(use_markup=True, xalign=0.0, wrap=True, selectable=True,
                          label=f'image distante : <a href="{uri}">{md.escape(alt) or uri}</a>')
        label.connect("activate-link", _on_activate_link)
        return label

    def _remote_image(self, url, alt):
        """Image https : place réservée tout de suite, image téléchargée à part (8 Mo au plus,
        gardée en mémoire) puis affichée en taille limitée ; un échec laisse le lien."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.START,
                      css_classes=["ccs-rich-image"])
        picture = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN,
                              halign=Gtk.Align.START, alternative_text=alt, tooltip_text=alt or url)
        fallback = self._image_link(url, alt)
        fallback.set_visible(False)
        box.append(picture)
        box.append(fallback)
        _load_remote(url, lambda data: _set_image(picture, fallback, data))
        return box

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

    # -- chat riche : lecteurs et blocs ```ccs (docs/chat-riche.md) ----------------------------

    def _paragraph(self, block):
        """Paragraphe ; un lien ou un `chemin` vers un son ou une vidéo du disque gagne un lecteur."""
        label = self._label(block.spans)
        players = []
        for span in block.spans:
            src = span.link or (span.text.strip() if span.code else "")
            player = self._player(src, span.text) if src else None
            if player is not None:
                players.append(player)
        if not players:
            return label
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(label)
        for player in players:
            box.append(player)
        return box

    def _player(self, src, label=""):
        """Lecteur (Gtk.Video) d'un son ou d'une vidéo du disque, ou None. Un média https reçoit
        un bouton « Lire » qui crée le lecteur au clic (rien n'est chargé avant)."""
        kind = chat_rich.media_kind(src)
        url = chat_rich.remote_src(src) if kind else ""
        if url:
            return self._remote_player(url, kind)
        local = self._local_path(src) if kind else None
        if local is None or not local.is_file():
            return None
        video = Gtk.Video.new_for_filename(str(local))
        video.set_autoplay(False)
        video.set_halign(Gtk.Align.START)
        video.add_css_class(f"ccs-rich-{kind}")
        video.set_tooltip_text(label or local.name)
        _size_player(video, kind)
        return video

    def _remote_player(self, url, kind):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.START,
                      css_classes=["ccs-rich-remote"])
        content = Gtk.Box(spacing=6)
        content.append(Gtk.Image(icon_name="media-playback-start-symbolic"))
        content.append(Gtk.Label(label="Lire le son" if kind == "audio" else "Lire la vidéo"))
        button = Gtk.Button(child=content, tooltip_text=url)
        button.connect("clicked", lambda b, u=url, k=kind: _on_remote_play(b, u, k))
        box.append(button)
        return box

    def _rich(self, spec):
        """Composant d'un bloc ```ccs : choix, formulaire, carte(s)."""
        if spec is None:
            return None
        if spec["type"] == "choix":
            return self._choices(spec)
        if spec["type"] == "formulaire":
            return self._form(spec) if chat_rich.form_fields(spec) else None
        if spec["type"] in ("carte", "cartes"):
            cards = chat_rich.cards_of(spec)
            return self._cards(cards) if cards else None
        return None

    def _choices(self, spec):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["ccs-rich-choices"])
        title = spec.get("titre") or spec.get("question")
        if title:
            box.append(Gtk.Label(label=str(title), xalign=0.0, wrap=True, css_classes=["heading"]))
        row = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                          column_spacing=6, row_spacing=6, homogeneous=False, css_classes=[_GROUP])
        for option in map(chat_rich.option_of, spec["options"]):
            if option["label"]:
                row.append(self._send_button(option["label"], option["message"]))
        box.append(row)
        return box

    def _form(self, spec):
        """Formulaire : un champ par entrée de `champs` (texte, nombre, liste), puis le bouton
        `envoyer` ; Entrée dans un champ envoie aussi. Le message part une fois."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=FORM_WIDTH,
                      halign=Gtk.Align.START, css_classes=["card", "ccs-rich-form", _GROUP])
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=12, margin_end=12,
                        margin_top=10, margin_bottom=12)
        if spec.get("titre"):
            inner.append(Gtk.Label(label=str(spec["titre"]), xalign=0.0, wrap=True, css_classes=["heading"]))
        active = self.on_send is not None
        for field in chat_rich.form_fields(spec):
            inner.append(Gtk.Label(label=field["label"], xalign=0.0, wrap=True, css_classes=["caption"]))
            if field["type"] == "liste":
                widget = Gtk.DropDown.new_from_strings(field["options"])
                if field["valeur"] in field["options"]:
                    widget.set_selected(field["options"].index(field["valeur"]))
            else:
                widget = Gtk.Entry(text=field["valeur"] or "", placeholder_text=field["aide"])
                if field["type"] == "nombre":
                    widget.set_input_purpose(Gtk.InputPurpose.NUMBER)
                widget.connect("activate", lambda w, s=spec: _on_form_send(w, s))
            widget.add_css_class(_INPUT)
            widget.set_sensitive(active)
            inner.append(widget)
        button = Gtk.Button(label=str(spec.get("envoyer") or "Envoyer"), halign=Gtk.Align.START,
                            sensitive=active, margin_top=4, css_classes=["suggested-action"])
        button.connect("clicked", lambda b, s=spec: _on_form_send(b, s))
        inner.append(button)
        box.append(inner)
        return box

    def _send_button(self, label, message):
        button = Gtk.Button(label=label, sensitive=self.on_send is not None)
        button.connect("clicked", lambda b, m=message: _on_rich_send(b, m))
        return button

    def _cards(self, cards):
        row = Gtk.Box(spacing=10)
        for spec in cards:
            row.append(self._card(spec))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                      vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      css_classes=["ccs-rich-cards"])
        scroller.set_child(row)
        return scroller

    def _card(self, spec):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=CARD_WIDTH,
                       valign=Gtk.Align.START, css_classes=["card", "ccs-rich-card"])
        if spec.get("image"):
            photo = self._photo(str(spec["image"]), str(spec["titre"]))
            if photo is not None:
                card.append(photo)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_start=10, margin_end=10,
                       margin_top=6, margin_bottom=8)
        title, link = md.escape(str(spec["titre"])), chat_rich.web_link(spec.get("lien"))
        markup = f'<a href="{md.escape(link)}">{title}</a>' if link else title
        body.append(self._small_label(f"<b>{markup}</b>"))
        if spec.get("prix") not in (None, ""):
            body.append(self._small_label(f"<b>{md.escape(str(spec['prix']))}</b>", "accent"))
        if spec.get("sous_titre"):
            body.append(self._small_label(md.escape(str(spec["sous_titre"])), "dim-label"))
        if spec.get("description"):
            body.append(self._small_label(md.escape(str(spec["description"]))))
        actions = [a for a in map(chat_rich.option_of, spec.get("actions") or []) if a["label"]]
        if actions:
            row = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6,
                              css_classes=[_GROUP])
            for action in actions:
                url = chat_rich.web_link(action["lien"])
                if url:
                    button = Gtk.Button(label=action["label"], css_classes=["flat"], tooltip_text=url)
                    button.connect("clicked", lambda b, u=url: _on_activate_link(b, u))
                else:
                    button = self._send_button(action["label"], action["message"])
                row.append(button)
            body.append(row)
        card.append(body)
        return card

    def _small_label(self, markup, *css):
        label = Gtk.Label(use_markup=True, label=markup, xalign=0.0, wrap=True,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=28, selectable=True,
                          css_classes=list(css))
        label.connect("activate-link", _on_activate_link)
        return label

    def _photo(self, src, alt):
        """Photo d'une carte : fichier du disque, ou adresse https téléchargée à part (8 Mo au
        plus, gardée en mémoire) ; tout autre schéma est ignoré."""
        picture = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.COVER,
                              height_request=CARD_PHOTO, alternative_text=alt)
        url = chat_rich.remote_src(src)
        if url:
            _load_remote(url, lambda data: _set_photo(picture, data))
            return picture
        local = self._local_path(src)
        if local is None or not local.is_file():
            return None
        picture.set_filename(str(local))
        return picture
