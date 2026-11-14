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

    def test_remote_image_not_loaded(self):
        v = self.view("![chat](https://exemple.org/c.png)")
        self.assertFalse([w for w in walk(v) if isinstance(w, Gtk.Picture)])
        labels = [w.get_label() for w in walk(v) if isinstance(w, Gtk.Label)]
        self.assertTrue(any("image distante : " in t and ">chat<" in t for t in labels))

    def test_local_image_is_a_picture(self):
        from gi.repository import GdkPixbuf
        with tempfile.TemporaryDirectory() as tmp:
            GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 800, 100).savev(
                str(Path(tmp) / "a.png"), "png", [], [])
            v = self.view("![x](a.png)", base_dir=tmp)
            pics = [w for w in walk(v) if isinstance(w, Gtk.Picture)]
            self.assertEqual(len(pics), 1)
            self.assertLessEqual(pics[0].get_size_request()[0], 600)

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

