"""Fichier ouvert : onglets de fichiers (GtkSourceView), aperçu Markdown, images,
rechargement quand le disque change, diff."""

import difflib
import os
import webbrowser

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, GtkSource

from .. import file_tree
from .common import in_thread

MAX_VIEW_BYTES = 8 * 1024 * 1024   # au-delà, un fichier trop gros est coupé à l'affichage
CHECK_MS = 300
CSS = b"""
.ccs-file-notice { background: alpha(@warning_color, 0.18); padding: 6px 12px; }
.ccs-file-head { padding: 4px 8px; }
"""
_css_done = False


def _install_css():
    global _css_done
    if _css_done:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS, -1)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_done = True


def _read(path):
    """Travail du fil : (type, texte, encodage, coupé, cachet)."""
    k = file_tree.kind(path)
    if k in ("text", "too_big"):
        try:
            if k == "too_big":
                with open(path, "rb") as f:
                    raw = f.read(MAX_VIEW_BYTES)
                truncated = os.path.getsize(path) > MAX_VIEW_BYTES
                try:
                    text, enc = raw.decode("utf-8"), "utf-8"
                except UnicodeDecodeError:
                    text, enc = raw.decode("utf-8", "replace"), "utf-8"
                return k, text, enc, truncated, file_tree.stamp(path)
            stp = file_tree.stamp(path)
            text, enc = file_tree.read_text(path)
            return k, text, enc, False, stp
        except OSError:
            return "missing", "", "utf-8", False, None
    try:
        stp = file_tree.stamp(path)
    except OSError:
        stp = None
    return k, "", "utf-8", False, stp


class _Doc:
    """Un fichier (ou un diff) ouvert dans un onglet."""

    def __init__(self, key, path, title):
        self.key = key
        self.path = path
        self.title = title
        self.state = "loading"      # loading, text, too_big, image, binary, missing, diff
        self.encoding = "utf-8"
        self.stamp = None
        self.dirty = False
        self.loading = False        # vrai pendant qu'on remplit le tampon
        self.readonly = False
        self.closed = False
        self.page = None
        self.holder = None          # Gtk.Box de la page
        self.body = None            # contenu courant dans `holder`
        self.notice = None
        self.buffer = None
        self.view = None
        self.stack = None           # source / aperçu pour .md
        self.preview = None
        self.preview_timer = 0
        self.search = None
        self.monitor = None
        self.pending_line = None
        self.reading = False


class FileEditor(Gtk.Box):
    """Onglets de fichiers. Signal `empty` : le dernier fichier vient de se fermer."""

    __gsignals__ = {"empty": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        _install_css()
        self._docs = {}
        self._dark = False
        self._check_timer = 0
        self.tab_view = Adw.TabView()
        self.tab_bar = Adw.TabBar(view=self.tab_view, autohide=False)
        self.tab_view.connect("close-page", self._on_close_page)
        self.tab_view.connect("notify::n-pages", self._on_n_pages)
        self.append(self.tab_bar)
        self.append(self.tab_view)
        self.tab_view.set_vexpand(True)

        ctl = Gtk.ShortcutController()
        ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctl.set_scope(Gtk.ShortcutScope.LOCAL)
        for accel, handler in (("<Control>s", self.save_current),
                               ("<Control>f", self.find)):
            ctl.add_shortcut(Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string(accel),
                Gtk.CallbackAction.new(lambda *_a, h=handler: (h(), True)[1])))
        self.add_controller(ctl)
        self.connect("destroy", self._on_destroy)

    # ---- informations (tests et assemblage) -------------------------------------

    def paths(self):
        return [d.path for d in self._docs.values() if d.state != "diff"]

    def doc(self, path):
        return self._docs.get(os.path.abspath(os.fspath(path)))

    def state(self, path):
        d = self.doc(path)
        return d.state if d else None

    def text(self, path):
        d = self.doc(path)
        if d is None or d.buffer is None:
            return None
        return d.buffer.get_text(d.buffer.get_start_iter(), d.buffer.get_end_iter(), False)

    def set_text(self, path, text):
        """Remplace le texte comme le ferait une saisie (le fichier devient modifié)."""
        d = self.doc(path)
        if d is not None and d.buffer is not None and not d.readonly:
            d.buffer.set_text(text)

    def is_dirty(self, path):
        d = self.doc(path)
        return bool(d and d.dirty)

    def diff_text(self, path):
        d = self._docs.get("diff:" + os.path.abspath(os.fspath(path)))
        return self._buffer_text(d) if d else None

    def current_path(self):
        page = self.tab_view.get_selected_page()
        for d in self._docs.values():
            if d.page is page:
                return d.path
        return None

    @staticmethod
    def _buffer_text(d):
        return d.buffer.get_text(d.buffer.get_start_iter(), d.buffer.get_end_iter(), False)

    # ---- ouvrir ----------------------------------------------------------------------

    def open(self, path, line=None):
        path = os.path.abspath(os.fspath(path))
        d = self._docs.get(path)
        if d is not None:
            self.tab_view.set_selected_page(d.page)
            if line:
                self._goto(d, line)
            return
        d = self._new_doc(path, path, os.path.basename(path) or path)
        d.pending_line = line
        self._read_into(d)
        self._watch(d)

    def _new_doc(self, key, path, title):
        d = _Doc(key, path, title)
        d.holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        d.holder.set_vexpand(True)
        d.page = self.tab_view.append(d.holder)
        d.page.set_title(title)
        d.page.set_tooltip(path)
        self._docs[key] = d
        self.tab_view.set_selected_page(d.page)
        return d

    def _read_into(self, d, reload=False):
        if d.reading:
            return
        d.reading = True

        def done(res):
            d.reading = False
            if d.closed:
                return
            self._show(d, res, reload)

        in_thread(lambda: _read(d.path), done)

    # ---- construction des contenus ----------------------------------------------------

    def _clear_holder(self, d):
        child = d.holder.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            d.holder.remove(child)
            child = nxt
        d.body = d.notice = d.stack = d.preview = d.view = d.search = None
        if d.preview_timer:
            GLib.source_remove(d.preview_timer)
            d.preview_timer = 0

    def _show(self, d, res, reload=False):
        kind, text, enc, truncated, stp = res
        d.stamp = stp
        d.encoding = enc
        if kind in ("text", "too_big"):
            if d.state in ("text", "too_big") and d.buffer is not None:
                self._set_buffer_text(d, text)
                d.dirty = False
                self._update_indicator(d)
                self._hide_notice(d)
                return
            d.state = kind
            d.readonly = kind == "too_big"
            self._clear_holder(d)
            self._build_text(d, text)
            if kind == "too_big":
                msg = ("Fichier de plus de 2 Mo : ouvert en lecture seule."
                       if not truncated else
                       "Fichier de plus de 2 Mo : ouvert en lecture seule, "
                       "seuls les premiers 8 Mo sont affichés.")
                banner = Adw.Banner(title=msg, revealed=True)
                d.holder.prepend(banner)
            if d.pending_line:
                self._goto(d, d.pending_line)
                d.pending_line = None
            return
        d.state = kind
        d.buffer = None
        d.dirty = False
        self._update_indicator(d)
        self._clear_holder(d)
        if kind == "image":
            pic = Gtk.Picture.new_for_filename(d.path)
            pic.set_can_shrink(True)
            pic.set_vexpand(True)
            d.holder.append(pic)
        else:
            title, desc, icon = {
                "binary": ("Fichier binaire", "Ce fichier n'est pas du texte : il n'est pas affiché.",
                           "application-x-executable-symbolic"),
                "missing": ("Fichier introuvable",
                            "Ce fichier n'existe pas (ou plus) sur le disque.",
                            "dialog-warning-symbolic"),
            }[kind]
            page = Adw.StatusPage(title=title, description=desc, icon_name=icon)
            page.set_vexpand(True)
            d.holder.append(page)

    def _language_for(self, path):
        lm = GtkSource.LanguageManager.get_default()
        return lm.guess_language(path, None)

    def _scheme(self):
        mgr = GtkSource.StyleSchemeManager.get_default()
        for sid in (("Adwaita-dark", "oblivion", "classic-dark") if self._dark
                    else ("Adwaita", "classic")):
            scheme = mgr.get_scheme(sid)
            if scheme is not None:
                return scheme
        return None

    def _build_text(self, d, text):
        buf = GtkSource.Buffer()
        d.buffer = buf
        lang = self._language_for(d.path)
        if lang is not None:
            buf.set_language(lang)
        buf.set_highlight_syntax(True)
        scheme = self._scheme()
        if scheme is not None:
            buf.set_style_scheme(scheme)
        d.loading = True
        buf.set_text(text)
        buf.set_modified(False)
        buf.place_cursor(buf.get_start_iter())
        d.loading = False
        d.dirty = False
        self._update_indicator(d)
        buf.connect("changed", lambda _b: self._on_changed(d))

        view = GtkSource.View(buffer=buf, monospace=True, show_line_numbers=True,
                              highlight_current_line=True, auto_indent=True,
                              editable=not d.readonly, top_margin=4, bottom_margin=4,
                              left_margin=6)
        d.view = view
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(view)

        search_bar = self._build_search(d)
        is_md = d.path.lower().endswith((".md", ".markdown"))
        if is_md:
            d.stack = Gtk.Stack(vexpand=True, hexpand=True)
            d.stack.add_named(scroller, "source")
            head = Gtk.Box(spacing=6)
            head.add_css_class("ccs-file-head")
            src_btn = Gtk.ToggleButton(label="Source", active=True)
            prev_btn = Gtk.ToggleButton(label="Aperçu", group=src_btn)
            head.append(src_btn)
            head.append(prev_btn)
            d.toggle = (src_btn, prev_btn)
            prev_btn.connect("toggled", lambda b: self._on_preview_toggled(d, b.get_active()))
            d.holder.append(head)
            d.holder.append(search_bar)
            d.holder.append(d.stack)
            d.body = d.stack
        else:
            d.holder.append(search_bar)
            d.holder.append(scroller)
            d.body = scroller

    def _build_search(self, d):
        bar = Gtk.SearchBar()
        entry = Gtk.SearchEntry(hexpand=True, placeholder_text="Chercher dans le fichier")
        bar.set_child(entry)
        bar.connect_entry(entry)
        ctx = GtkSource.SearchContext.new(d.buffer, None)
        ctx.get_settings().set_wrap_around(True)
        d.search = (bar, entry, ctx)

        def find(forward):
            buf = d.buffer
            ins = buf.get_iter_at_mark(buf.get_insert())
            if forward:
                ins.forward_char()
                ok, start, end, _w = ctx.forward(ins)
            else:
                ok, start, end, _w = ctx.backward(ins)
            if ok:
                buf.select_range(start, end)
                d.view.scroll_to_iter(start, 0.1, False, 0, 0)

        entry.connect("search-changed", lambda e: (
            ctx.get_settings().set_search_text(e.get_text() or None), find(True)))
        entry.connect("activate", lambda _e: find(True))
        entry.connect("next-match", lambda _e: find(True))
        entry.connect("previous-match", lambda _e: find(False))
        return bar

    def find(self):
        d = self._current_doc()
        if d is not None and d.search is not None:
            d.search[0].set_search_mode(True)
            d.search[1].grab_focus()

    def _current_doc(self):
        page = self.tab_view.get_selected_page()
        for d in self._docs.values():
            if d.page is page:
                return d
        return None

    def _set_buffer_text(self, d, text):
        buf = d.buffer
        off = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        d.loading = True
        buf.set_text(text)
        buf.set_modified(False)
        it = buf.get_iter_at_offset(min(off, buf.get_char_count()))
        buf.place_cursor(it)
        d.loading = False
        self._refresh_preview(d)

    def _goto(self, d, line):
        if d.buffer is None:
            d.pending_line = line
            return
        ok, it = d.buffer.get_iter_at_line(max(int(line) - 1, 0))
        d.buffer.place_cursor(it)
        if d.view is not None:
            GLib.idle_add(lambda: (d.view.scroll_to_iter(it, 0.2, True, 0, 0.3), False)[1])

    # ---- aperçu Markdown ------------------------------------------------------------

    def _on_preview_toggled(self, d, active):
        if d.stack is None:
            return
        if active:
            if d.preview is None:
                from .markdown_view import MarkdownView
                d.preview = MarkdownView(self._buffer_text(d),
                                         base_dir=os.path.dirname(d.path),
                                         on_link=lambda url, dd=d: self._on_link(dd, url))
                d.preview.set_dark(self._dark)
                scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
                scroller.set_child(d.preview)
                d.stack.add_named(scroller, "preview")
            else:
                d.preview.set_text(self._buffer_text(d))
            d.stack.set_visible_child_name("preview")
        else:
            d.stack.set_visible_child_name("source")

    def _refresh_preview(self, d):
        if d.preview is not None and d.stack is not None \
                and d.stack.get_visible_child_name() == "preview":
            d.preview.set_text(self._buffer_text(d))

    def _on_link(self, d, url):
        if "://" in url or url.startswith("mailto:"):
            if url.split(":", 1)[0] in ("http", "https", "mailto"):
                webbrowser.open(url)
            return
        target = os.path.normpath(os.path.join(os.path.dirname(d.path), url.split("#")[0]))
        if os.path.isfile(target):
            self.open(target)

    def _schedule_preview(self, d):
        if d.preview is None or d.preview_timer:
            return

        def fire():
            d.preview_timer = 0
            self._refresh_preview(d)
            return False

        d.preview_timer = GLib.timeout_add(250, fire)

    # ---- modifications --------------------------------------------------------------

    def _on_changed(self, d):
        if d.loading:
            return
        if not d.dirty:
            d.dirty = True
            self._update_indicator(d)
        self._schedule_preview(d)

    def _update_indicator(self, d):
        d.page.set_indicator_icon(
            Gio.ThemedIcon.new("media-record-symbolic") if d.dirty else None)
        d.page.set_title(("• " if d.dirty else "") + d.title)

    def save_current(self):
        d = self._current_doc()
        if d is not None:
            self.save(d.path)

    def save(self, path, done=None):
        """Enregistre (atomique, droits conservés) dans un fil ; `done(ok)` ensuite."""
        d = self.doc(path)
        if d is None or d.buffer is None or d.readonly:
            if done:
                done(False)
            return
        text = self._buffer_text(d)
        enc = d.encoding

        def finish(res):
            if isinstance(res, Exception):
                self._notice(d, f"Enregistrement impossible : {res}", [])
                if done:
                    done(False)
                return
            d.stamp = res
            if not d.closed and self._buffer_text(d) == text:
                d.dirty = False
                d.buffer.set_modified(False)
                self._update_indicator(d)
            self._hide_notice(d)
            if done:
                done(True)

        def work():
            try:
                return file_tree.save(d.path, text, enc)
            except (OSError, ValueError) as e:
                return e

        in_thread(work, finish)

    # ---- bandeaux --------------------------------------------------------------------

    def _hide_notice(self, d):
        if d.notice is not None:
            d.holder.remove(d.notice)
            d.notice = None

    def _notice(self, d, message, actions):
        self._hide_notice(d)
        box = Gtk.Box(spacing=8)
        box.add_css_class("ccs-file-notice")
        label = Gtk.Label(label=message, xalign=0, hexpand=True, wrap=True)
        box.append(label)
        for text, handler in actions:
            b = Gtk.Button(label=text)
            b.connect("clicked", lambda _b, h=handler: h())
            box.append(b)
        d.holder.prepend(box)
        d.notice = box

    def _on_disk_changed(self, d):
        if d.closed or d.state == "diff" or d.reading:
            return
        if not file_tree.changed(d.path, d.stamp) if d.stamp else False:
            return
        exists = os.path.isfile(d.path)
        if not exists:
            if d.dirty and d.buffer is not None:
                self._notice(d, "Le fichier a été supprimé sur le disque ; vos modifications "
                                "restent ici.", [("Compris", lambda: self._hide_notice(d))])
                d.stamp = None
            elif d.state != "missing":
                self._show(d, ("missing", "", "utf-8", False, None))
            return
        if d.state == "missing" or not d.dirty:
            self._read_into(d, reload=True)
            self._blink(d)
            return
        self._notice(d, "Ce fichier a changé sur le disque et vous avez des modifications "
                        "non enregistrées.",
                     [("Garder les miens", lambda: self._keep_mine(d)),
                      ("Prendre la version sur le disque", lambda: self._take_disk(d)),
                      ("Voir les différences", lambda: self._show_conflict_diff(d))])

    def _keep_mine(self, d):
        try:
            d.stamp = file_tree.stamp(d.path)
        except OSError:
            d.stamp = None
        self._hide_notice(d)

    def _take_disk(self, d):
        d.dirty = False
        self._read_into(d, reload=True)

    def _show_conflict_diff(self, d):
        def done(res):
            if res[0] in ("text", "too_big"):
                self.show_diff(d.path, res[1], self._buffer_text(d))

        in_thread(lambda: _read(d.path), done)

    def _blink(self, d):
        if self.tab_view.get_selected_page() is d.page:
            return
        d.page.set_needs_attention(True)
        GLib.timeout_add(1500, lambda: (d.page.set_needs_attention(False), False)[1])

    def check_changes(self):
        """Vérifie tous les fichiers ouverts (appelé par les moniteurs, regroupé)."""
        for d in list(self._docs.values()):
            self._on_disk_changed(d)

    def _watch(self, d):
        try:
            d.monitor = Gio.File.new_for_path(d.path).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error:
            return
        d.monitor.connect("changed", lambda *_a: self._schedule_check())

    def _schedule_check(self):
        if self._check_timer:
            return
        self._check_timer = GLib.timeout_add(CHECK_MS, self._fire_check)

    def _fire_check(self):
        self._check_timer = 0
        self.check_changes()
        return False

    # ---- diff --------------------------------------------------------------------------

    def show_diff(self, path, old, new):
        """Diff coloré de `old` vers `new` (difflib.unified_diff), avec un bouton
        « Fichier entier »."""
        path = os.path.abspath(os.fspath(path))
        key = "diff:" + path
        name = os.path.basename(path)
        lines = list(difflib.unified_diff(
            old.splitlines(True), new.splitlines(True),
            fromfile=f"avant/{name}", tofile=f"après/{name}"))
        text = "".join(l if l.endswith("\n") else l + "\n" for l in lines) \
            or "(aucune différence)\n"
        d = self._docs.get(key)
        if d is None:
            d = self._new_doc(key, path, f"Diff · {name}")
            d.state = "diff"
            d.readonly = True
            buf = GtkSource.Buffer()
            d.buffer = buf
            lang = GtkSource.LanguageManager.get_default().get_language("diff")
            if lang is not None:
                buf.set_language(lang)
            scheme = self._scheme()
            if scheme is not None:
                buf.set_style_scheme(scheme)
            head = Gtk.Box(spacing=6)
            head.add_css_class("ccs-file-head")
            head.append(Gtk.Label(label=f"Modification de {name}", xalign=0, hexpand=True))
            full = Gtk.Button(label="Fichier entier")
            full.connect("clicked", lambda _b: self.open(path))
            head.append(full)
            view = GtkSource.View(buffer=buf, monospace=True, editable=False,
                                  show_line_numbers=False, top_margin=4, bottom_margin=4,
                                  left_margin=6)
            d.view = view
            scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
            scroller.set_child(view)
            d.holder.append(head)
            d.holder.append(scroller)
        d.buffer.set_text(text)
        self.tab_view.set_selected_page(d.page)

    # ---- fermeture ---------------------------------------------------------------------

    def close(self, path, force=False):
        d = self.doc(path) or self._docs.get(os.path.abspath(os.fspath(path)))
        if d is None:
            return
        if force:
            d.dirty = False
        self.tab_view.close_page(d.page)

    def _on_close_page(self, view, page):
        d = next((x for x in self._docs.values() if x.page is page), None)
        if d is None or not d.dirty or d.state == "diff":
            self._finish_close(d, page, True)
            return True
        dialog = Adw.AlertDialog(heading=f"Enregistrer « {d.title} » ?",
                                 body="Ce fichier a des modifications non enregistrées.")
        dialog.add_response("cancel", "Annuler")
        dialog.add_response("discard", "Ne pas enregistrer")
        dialog.add_response("save", "Enregistrer")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        self._last_dialog = dialog

        def answered(_dlg, response):
            if response == "discard":
                d.dirty = False
                self._finish_close(d, page, True)
            elif response == "save":
                self.save(d.path, lambda ok: self._finish_close(d, page, ok))
            else:
                self._finish_close(d, page, False)

        dialog.connect("response", answered)
        dialog.present(self)
        return True

    def _finish_close(self, d, page, confirm):
        if confirm and d is not None:
            d.closed = True
            if d.monitor is not None:
                d.monitor.cancel()
            if d.preview_timer:
                GLib.source_remove(d.preview_timer)
                d.preview_timer = 0
            self._docs.pop(d.key, None)
        self.tab_view.close_page_finish(page, confirm)

    def _on_n_pages(self, view, _p):
        if view.get_n_pages() == 0:
            self.emit("empty")

    def has_unsaved(self):
        return any(d.dirty for d in self._docs.values())

    # ---- thème -------------------------------------------------------------------------

    def set_dark(self, dark):
        self._dark = bool(dark)
        scheme = self._scheme()
        for d in self._docs.values():
            if d.buffer is not None and scheme is not None:
                d.buffer.set_style_scheme(scheme)
            if d.preview is not None:
                d.preview.set_dark(self._dark)

    def _on_destroy(self, _w):
        if self._check_timer:
            GLib.source_remove(self._check_timer)
            self._check_timer = 0
        for d in self._docs.values():
            d.closed = True
            if d.monitor is not None:
                d.monitor.cancel()
            if d.preview_timer:
                GLib.source_remove(d.preview_timer)
                d.preview_timer = 0
