"""Widget Markdown (GTK, sous Xvfb)."""

import tempfile
import unittest
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("GtkSource", "5")
    from gi.repository import Gtk, GtkSource
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


def children(widget):
    out, child = [], widget.get_first_child()
    while child:
        out.append(child)
        child = child.get_next_sibling()
    return out


def walk(widget):
    yield widget
    for c in children(widget):
        yield from walk(c)


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class MarkdownViewTest(unittest.TestCase):
    def view(self, text, **kw):
        from ccs_app.gui.markdown_view import MarkdownView
        return MarkdownView(text, **kw)

    def test_builds_one_widget_per_block(self):
        v = self.view("# T\n\npara\n\n```py\nx\n```\n\n---\n")
        self.assertEqual(len(children(v)), 4)

    def test_code_block_uses_gtksource(self):
        v = self.view("```python\nprint(1)\n```")
        views = [w for w in walk(v) if isinstance(w, GtkSource.View)]
        self.assertEqual(len(views), 1)
        self.assertFalse(views[0].get_editable())
        buf = views[0].get_buffer()
        self.assertEqual(buf.get_language().get_id(), "python")
        v.set_dark(True)
        v.set_dark(False)

    def test_short_list_is_one_label(self):
        # Une ligne de widgets par élément coûtait ~220 Ko par liste de 10 : une liste courte
        # est un seul label (gras, code et liens gardés).
        v = self.view("- un **gras**\n- deux `code`\n- [lien](https://exemple.fr)\n")
        lists = [w for w in walk(v) if isinstance(w, Gtk.Label) and w.has_css_class("ccs-md-list")]
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0].get_text(), "•\tun gras\n•\tdeux code\n•\tlien")
        self.assertIn('<a href="https://exemple.fr">', lists[0].get_label())
        self.assertTrue(lists[0].get_selectable())

    def test_ordered_short_list_numbers(self):
        v = self.view("3. a\n4. b\n")
        label = next(w for w in walk(v) if isinstance(w, Gtk.Label) and w.has_css_class("ccs-md-list"))
        self.assertEqual(label.get_text(), "3.\ta\n4.\tb")

    def test_long_item_keeps_hanging_indent(self):
        v = self.view("- court\n- " + "mot " * 30 + "\n")
        self.assertFalse([w for w in walk(v) if isinstance(w, Gtk.Label) and w.has_css_class("ccs-md-list")])
        self.assertIn("•", [w.get_label() for w in walk(v) if isinstance(w, Gtk.Label)])

    def test_nested_list_keeps_widgets(self):
        v = self.view("- a\n  - b\n- c\n")
        labels = [w.get_label() for w in walk(v) if isinstance(w, Gtk.Label)]
        self.assertIn("•", labels)

    def test_task_items_and_table(self):
        v = self.view("- [x] a\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
        boxes = [w for w in walk(v) if isinstance(w, Gtk.CheckButton)]
        self.assertEqual(len(boxes), 1)
        self.assertTrue(boxes[0].get_active())
        self.assertFalse(boxes[0].get_sensitive())
        self.assertEqual(len([w for w in walk(v) if isinstance(w, Gtk.Grid)]), 1)

    def test_table_has_no_blank_space_below(self):
        """Une cellule qui passait à la ligne faisait mesurer au tableau la hauteur d'un mot par
        ligne : un grand vide apparaissait sous le tableau (749 px pour 5 lignes)."""
        v = self.view("| | Avant | Après |\n|---|---|---|\n| RAM utilisée | 11 Go (74 %) | 8,1 Go |\n"
                      "| Contenu de la zram | 10,8 Go (dans 2,6 Go de RAM) | 5,2 Go (dans 1,5 Go) |\n"
                      "| Long | " + "mot " * 30 + "| x |\n")
        scroller = next(w for w in walk(v) if isinstance(w, Gtk.ScrolledWindow))
        _min, natural, _b, _b2 = scroller.measure(Gtk.Orientation.VERTICAL, 900)
        self.assertLess(natural, 200)
        cells = [w for w in walk(v) if isinstance(w, Gtk.Label) and w.get_parent().__class__ is Gtk.Grid]
        self.assertFalse(cells[1].get_wrap())                     # « Avant » : courte
        self.assertTrue(cells[-2].get_wrap())                     # longue : passe à la ligne
        self.assertEqual(cells[-2].get_width_chars(), 40)

    def fetching(self, result):
        """Remplace le téléchargement (pas de réseau dans les tests) ; rend la liste des adresses."""
        import ccs_app.gui.markdown_view as mv
        fetched, old = [], mv._fetch
        mv._fetch = lambda url: (fetched.append(url), result)[1]
        self.addCleanup(setattr, mv, "_fetch", old)
        self.addCleanup(mv._photos.clear)
        return fetched

    def wait(self, until):
        from gi.repository import GLib
        ctx = GLib.MainContext.default()
        for _ in range(200):
            if until():
                return
            ctx.iteration(False)
            import time
            time.sleep(0.01)
        self.fail("délai dépassé")

    def test_remote_image_loaded_in_background(self):
        from gi.repository import GdkPixbuf
        with tempfile.TemporaryDirectory() as tmp:
            GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 1200, 1200).savev(
                str(Path(tmp) / "a.png"), "png", [], [])
            data = (Path(tmp) / "a.png").read_bytes()
        fetched = self.fetching(data)
        v = self.view("![chat](https://exemple.org/c.png)")
        pic = next(w for w in walk(v) if isinstance(w, Gtk.Picture))
        self.wait(lambda: pic.get_paintable() is not None)
        self.assertEqual(fetched, ["https://exemple.org/c.png"])
        self.assertEqual(pic.get_size_request(), (400, 400))           # limitée à 600 × 400
        link = next(w for w in walk(v) if isinstance(w, Gtk.Label))
        self.assertFalse(link.get_visible())
        self.view("![chat](https://exemple.org/c.png)")                 # ensuite : depuis le cache
        self.assertEqual(len(fetched), 1)

    def test_remote_image_failure_and_refused_schemes(self):
        self.fetching(None)
        v = self.view("![chat](https://exemple.org/c.png)")
        pic = next(w for w in walk(v) if isinstance(w, Gtk.Picture))
        self.wait(lambda: not pic.get_visible())
        link = next(w for w in walk(v) if isinstance(w, Gtk.Label))
        self.assertTrue(link.get_visible())
        self.assertIn(">chat<", link.get_label())
        for src in ("http://exemple.org/c.png", "data:image/png;base64,AAAA"):
            v = self.view(f"![x]({src})")
            self.assertFalse([w for w in walk(v) if isinstance(w, Gtk.Picture)], src)

    def test_local_image_is_a_picture(self):
        from gi.repository import GdkPixbuf
        with tempfile.TemporaryDirectory() as tmp:
            GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 800, 100).savev(
                str(Path(tmp) / "a.png"), "png", [], [])
            v = self.view("![x](a.png)", base_dir=tmp)
            pics = [w for w in walk(v) if isinstance(w, Gtk.Picture)]
            self.assertEqual(len(pics), 1)
            self.assertLessEqual(pics[0].get_size_request()[0], 600)

    # -- chat riche (docs/chat-riche.md) ------------------------------------------------------

    def test_ccs_choice_sends_once(self):
        sent = []
        v = self.view('```ccs\n{"type":"choix","titre":"Que faire ?","options":["Oui",'
                      '{"label":"Voir","message":"Montre les détails"}]}\n```', on_send=sent.append)
        self.assertFalse([w for w in walk(v) if isinstance(w, GtkSource.View)])
        buttons = [w for w in walk(v) if isinstance(w, Gtk.Button)]
        self.assertEqual([b.get_label() for b in buttons], ["Oui", "Voir"])
        buttons[1].emit("clicked")
        self.assertEqual(sent, ["Montre les détails"])
        self.assertFalse(any(b.get_sensitive() for b in buttons))
        labels = [w.get_label() for w in walk(v) if isinstance(w, Gtk.Label)]
        self.assertIn("Que faire ?", labels)

    def test_ccs_cards(self):
        import ccs_app.gui.markdown_view as mv
        sent, fetched = [], []
        old = mv._fetch
        mv._fetch = lambda url: fetched.append(url)      # pas de réseau dans les tests
        try:
            spec = ('{"type":"cartes","items":[{"titre":"Vélo","image":"https://ex.com/v.jpg",'
                    '"prix":"45 000 FCFA","lien":"https://ex.com/v","description":"Bon état",'
                    '"actions":[{"label":"Plus","message":"Plus sur le vélo"},{"label":"Site","lien":"https://ex.com"}]},'
                    '{"titre":"Mauvais","lien":"javascript:alert(1)"},{"pas":"de titre"}]}')
            v = self.view(f"```ccs\n{spec}\n```", on_send=sent.append)
            cards = [w for w in walk(v) if w.has_css_class("ccs-rich-card")]
            self.assertEqual(len(cards), 2)
            labels = [w.get_label() for w in walk(cards[0]) if isinstance(w, Gtk.Label)]
            self.assertIn('<b><a href="https://ex.com/v">Vélo</a></b>', labels)
            self.assertIn("<b>45 000 FCFA</b>", labels)
            self.assertEqual(len([w for w in walk(cards[0]) if isinstance(w, Gtk.Picture)]), 1)
            bad = [w.get_label() for w in walk(cards[1]) if isinstance(w, Gtk.Label)]
            self.assertNotIn("href", " ".join(bad))
            plus = next(w for w in walk(cards[0]) if isinstance(w, Gtk.Button) and w.get_label() == "Plus")
            plus.emit("clicked")
            self.assertEqual(sent, ["Plus sur le vélo"])
        finally:
            mv._fetch = old

    def test_invalid_blocks_stay_code(self):
        for body in ('{"type":"formulaire","champs":["pas un objet"]}', "{pas du json", '{"type":"inconnu"}'):
            v = self.view(f"```ccs\n{body}\n```")
            self.assertEqual(len([w for w in walk(v) if isinstance(w, GtkSource.View)]), 1, body)

    def test_ccs_form_sends_once(self):
        sent = []
        spec = ('{"type":"formulaire","titre":"Recherche","envoyer":"Chercher","champs":['
                '{"nom":"prix","label":"Prix max","type":"nombre"},'
                '{"nom":"ville","label":"Ville","type":"liste","options":["Lomé","Kara"],"valeur":"Kara"},'
                '{"nom":"note","label":"Note","type":"texte","valeur":"","aide":"facultatif"}]}')
        v = self.view(f"```ccs\n{spec}\n```", on_send=sent.append)
        self.assertFalse([w for w in walk(v) if isinstance(w, GtkSource.View)])
        entries = [w for w in walk(v) if isinstance(w, Gtk.Entry)]
        drop = next(w for w in walk(v) if isinstance(w, Gtk.DropDown))
        self.assertEqual(drop.get_selected(), 1)
        self.assertEqual(entries[1].get_placeholder_text(), "facultatif")
        entries[0].set_text("50000")
        button = next(w for w in walk(v) if isinstance(w, Gtk.Button) and w.get_label() == "Chercher")
        button.emit("clicked")
        self.assertEqual(sent, ["Recherche\n- Prix max : 50000\n- Ville : Kara"])
        self.assertFalse(button.get_sensitive() or entries[0].get_sensitive() or drop.get_sensitive())
        entries[0].emit("activate")                                   # une seule fois
        self.assertEqual(len(sent), 1)

    def test_ccs_form_inactive_without_on_send(self):
        v = self.view('```ccs\n{"type":"formulaire","champs":[{"nom":"a"}]}\n```')
        self.assertTrue(v.get_first_child().has_css_class("ccs-rich-form"))
        self.assertFalse(any(w.get_sensitive() for w in walk(v) if isinstance(w, (Gtk.Button, Gtk.Entry))))

    def test_local_media_get_a_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "son.ogg").write_bytes(b"")
            (Path(tmp) / "clip.mp4").write_bytes(b"")
            v = self.view("Écoute `son.ogg` et [la vidéo](clip.mp4), pas [ça](http://ex.com/a.mp3).\n\n"
                          "![démo](clip.mp4)", base_dir=tmp)
            videos = [w for w in walk(v) if isinstance(w, Gtk.Video)]
            self.assertEqual(len(videos), 3)
            self.assertTrue(videos[0].has_css_class("ccs-rich-audio"))

    def test_remote_media_play_on_click(self):
        url = "https://exemple.invalid/a.mp3"
        v = self.view(f"Écoute [ça]({url}).\n\n![clip](https://exemple.invalid/c.webm)")
        self.assertFalse([w for w in walk(v) if isinstance(w, Gtk.Video)])   # rien de chargé
        boxes = [w for w in walk(v) if w.has_css_class("ccs-rich-remote")]
        self.assertEqual(len(boxes), 2)
        button = next(w for w in walk(boxes[0]) if isinstance(w, Gtk.Button))
        button.emit("clicked")
        video = next(w for w in walk(boxes[0]) if isinstance(w, Gtk.Video))
        self.assertTrue(video.has_css_class("ccs-rich-audio"))
        self.assertEqual(video.get_file().get_uri(), url)
        self.assertFalse([w for w in walk(boxes[0]) if isinstance(w, Gtk.Button) and w is button])
        video.get_media_stream() and video.get_media_stream().pause()

    def test_set_text_replaces_content(self):
        v = self.view("a\n\nb")
        self.assertEqual(len(children(v)), 2)
        v.set_text("seul")
        self.assertEqual(len(children(v)), 1)
        v.set_text("")
        self.assertEqual(len(children(v)), 0)

    def test_link_calls_on_link(self):
        got = []
        v = self.view("[l](https://x.org)", on_link=got.append)
        label = next(w for w in walk(v) if isinstance(w, Gtk.Label))
        self.assertTrue(label.emit("activate-link", "https://x.org"))
        self.assertEqual(got, ["https://x.org"])


if __name__ == "__main__":
    unittest.main()


class StableEndTest(unittest.TestCase):
    """Partie terminée d'un texte en cours d'écriture (sans GTK)."""

    def test_cut_after_last_blank_line_outside_code(self):
        from ccs_app.gui.markdown_view import stable_end
        self.assertEqual(stable_end("para en cours"), 0)
        text = "# Titre\n\npremier\n\nsecond en cours"
        self.assertEqual(text[:stable_end(text)], "# Titre\n\npremier\n\n")
        code = "intro\n\n```py\nx = 1\n\ny = 2\n"          # bloc de code encore ouvert
        self.assertEqual(code[:stable_end(code)], "intro\n\n")
        closed = code + "```\n\nfin"
        self.assertEqual(closed[:stable_end(closed)], code + "```\n\n")


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class StreamingTest(unittest.TestCase):
    def test_streaming_keeps_finished_blocks_and_ends_like_a_full_render(self):
        from ccs_app.gui.markdown_view import MarkdownView
        text = "# Titre\n\nUn **paragraphe**.\n\n- a\n- b\n\n```py\nprint(1)\n```\n\nFin du texte."
        v = MarkdownView("")
        first = None
        for n in range(1, len(text) + 1, 7):
            v.set_text_streaming(text[:n])
            if first is None and v._stable:              # le titre est terminé : il ne bouge plus
                first = children(v)[0]
        v.set_text_streaming(text)
        self.assertIs(children(v)[0], first)               # le titre n'a jamais été refait
        streamed = len(children(v))
        self.assertEqual(len(v._buffers), 1)               # pas de tampons de code accumulés
        full = MarkdownView(text)
        self.assertEqual(streamed, len(children(full)))
        v.set_text(text)                                   # rendu exact final
        self.assertEqual(len(children(v)), len(children(full)))

