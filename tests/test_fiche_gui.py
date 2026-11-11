"""Encart « Où j'en étais » (widgets créés sans être affichés ; affichage requis, sinon sautés)."""

import unittest
from unittest import mock

from tests.helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


def labels(widget):
    out, child = [], widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label):
            out.append(child.get_label())
        out += labels(child)
        child = child.get_next_sibling()
    return out


@unittest.skipUnless(GTK, "affichage graphique requis")
class FicheViewTest(HomeTestCase):
    def view(self, **kw):
        from ccs_app.fiche import Fiche
        from ccs_app.gui.fiche_view import FicheView
        return FicheView(Fiche(session_id="s1", cwd="/x/App", when=1_700_000_000.0, **kw))

    def test_full_card(self):
        text = "\n".join(labels(self.view(
            last_request="ajoute un test", last_reply="fait", branch="main", account="pro", archived=True,
            files=[f"/x/App/f{i}.py" for i in range(9)],
            todos=[("completed", "un"), ("pending", "deux")])))
        for part in ("Où j'en étais", "Ta dernière demande", "ajoute un test", "Début de la dernière réponse",
                     "fait", "branche main", "compte pro", "archivée", "Fichiers modifiés (9)",
                     "et 3 autres", "Liste de tâches (1/2)", "[x] un", "[ ] deux"):
            self.assertIn(part, text)

    def test_minimal_card(self):
        text = "\n".join(labels(self.view(last_request="seulement ça")))
        self.assertIn("seulement ça", text)
        self.assertNotIn("Fichiers modifiés", text)
        self.assertNotIn("Liste de tâches", text)

    def test_preview_dialog_shows_card_and_archived_mention(self):
        from ccs_app import fiche as fiche_mod
        from ccs_app.conversations import Conversation
        from ccs_app.gui import preview_dialog
        conv = Conversation("s1", "/x/p/s1.jsonl", "/x/App", "Titre", "a", "b", 1, None, 0.0, "cli", "", 1,
                            archived=True)
        with mock.patch.object(preview_dialog.PreviewDialog, "load"):
            dlg = preview_dialog.PreviewDialog(conv)
        cost = mock.Mock(reponses=0)
        dlg.loaded(([], cost, fiche_mod.Fiche(last_request="où j'en suis")))
        self.assertIn("où j'en suis", "\n".join(labels(dlg.fiche_box)))
        self.assertIn("archivée", dlg.heading.get_subtitle())
        dlg.loaded(([], cost, None))
        self.assertEqual(labels(dlg.fiche_box), [])
