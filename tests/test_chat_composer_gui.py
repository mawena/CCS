"""Zone de saisie : messages enregistrés (complétion de `/` et menu ☆). Sous Xvfb."""

import unittest

from tests.helpers import gui_ready

GTK = gui_ready()
if GTK:
    from gi.repository import GLib, Gtk
    from ccs_app.gui.chat_composer import Composer
    from ccs_app.saved_messages import Saved


def spin(ms=100):
    ctx = GLib.MainContext.default()
    end = GLib.get_monotonic_time() + ms * 1000
    while GLib.get_monotonic_time() < end:
        while ctx.iteration(False):
            pass


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class SavedInComposerTest(unittest.TestCase):
    def setUp(self):
        self.c = Composer()
        self.win = Gtk.Window()
        self.win.set_child(self.c)
        self.win.present()
        self.addCleanup(self.win.destroy)
        self.saved = [Saved("revue", "Fais une revue du code.\nSois précis.", "global"),
                      Saved("merci", "Merci beaucoup !", "projet")]

    def rows(self):
        out, row = [], self.c.choices.get_row_at_index(0)
        while row is not None:
            out.append(row)
            row = self.c.choices.get_row_at_index(len(out))
        return out

    def test_slash_lists_saved(self):
        self.c.set_commands([("help", "aide"), ("revue-pr", "revue de PR")])
        self.c.set_saved(self.saved)
        self.c.set_text("/rev")
        spin()
        rows = self.rows()
        self.assertEqual([r.kind for r in rows], ["saved", "command"])    # « Mes messages » d'abord
        self.assertEqual(rows[0].insert_text, "Fais une revue du code.\nSois précis.")
        self.assertIsNotNone(rows[0].get_header())                        # en-tête « Mes messages »
        self.c._accept(rows[0])
        self.assertEqual(self.c.text, "Fais une revue du code.\nSois précis.")

    def test_slash_lists_saved_without_commands(self):
        self.c.set_saved(self.saved)
        self.c.set_text("/")
        spin()
        self.assertEqual(len(self.rows()), 2)

    def test_star_menu_inserts(self):
        self.c.set_saved(self.saved)
        self.c.set_text("Avant : ")
        self.c.saved_buttons["merci"].emit("clicked")
        self.assertEqual(self.c.text, "Avant : Merci beaucoup !")

    def test_add_edit_delete_emit_changes(self):
        changes = []
        self.c.connect("saved-changed", lambda _c, items: changes.append([(s.name, s.scope) for s in items]))
        self.c.add_saved("a", "A", "global")
        self.c.update_saved("a", "b", "B", "projet")
        self.c.delete_saved("b")
        self.assertEqual(changes, [[("a", "global")], [("b", "projet")], []])
        self.assertFalse(self.c.add_saved("  ", "vide"))

    def test_star_menu_without_messages(self):
        self.assertEqual(self.c.saved_buttons, {})


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class QuoteInComposerTest(unittest.TestCase):
    """Message cité au-dessus de la saisie (« Répondre » sur un message du fil)."""

    def setUp(self):
        self.c = Composer()
        self.win = Gtk.Window()
        self.win.set_child(self.c)
        self.win.present()
        self.addCleanup(self.win.destroy)
        self.sent = []
        self.c.connect("send", lambda c, text, images: self.sent.append((text, c.sent_quote)))

    def test_bar_shows_the_quoted_message(self):
        self.assertFalse(self.c.quote_bar.get_visible())
        self.c.set_quote("claude", "Deux options :\n\n- A\n- B")
        self.assertTrue(self.c.quote_bar.get_visible())
        self.assertEqual(self.c.quote_title.get_label(), "Réponse à Claude")
        self.assertEqual(self.c.quote_label.get_label(), "Deux options : - A - B")
        self.c.set_quote("moi", "x")
        self.assertEqual(self.c.quote_title.get_label(), "Réponse à ton message")

    def test_submit_hands_the_quote_to_the_tab_and_clears_it(self):
        self.c.set_quote("claude", "A ou B ?")
        self.c.set_text("La B")
        self.assertTrue(self.c.submit())
        self.assertEqual(self.sent, [("La B", ("claude", "A ou B ?"))])
        self.assertIsNone(self.c.quote)
        self.assertIsNone(self.c.sent_quote)                       # seulement pendant le signal
        self.assertFalse(self.c.quote_bar.get_visible())

    def test_quote_alone_is_not_sent(self):
        self.c.set_quote("claude", "A ou B ?")
        self.assertFalse(self.c.submit())
        self.assertEqual(self.c.quote, ("claude", "A ou B ?"))

    def test_cancel_button_and_escape(self):
        from gi.repository import Gdk
        self.c.set_quote("claude", "A ou B ?")
        self.c.quote_cancel.emit("clicked")
        self.assertIsNone(self.c.quote)
        self.c.set_quote("claude", "A ou B ?")
        self.c.busy = True
        stops = []
        self.c.connect("stop", lambda *_: stops.append(1))
        self.assertTrue(self.c._on_key(None, Gdk.KEY_Escape, 0, 0))    # d'abord la citation
        self.assertEqual((self.c.quote, stops), (None, []))
        self.assertTrue(self.c._on_key(None, Gdk.KEY_Escape, 0, 0))    # puis l'arrêt de Claude
        self.assertEqual(stops, [1])

    def test_restore_brings_the_quote_back(self):
        self.c.restore("texte", (), ("moi", "message cité"))
        self.assertEqual((self.c.text, self.c.quote), ("texte", ("moi", "message cité")))
        self.assertTrue(self.c.quote_bar.get_visible())
        self.c.clear()
        self.assertIsNone(self.c.quote)
