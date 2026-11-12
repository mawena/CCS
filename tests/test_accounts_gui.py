"""Onglet Comptes : cartes `.ccs-card` à la couleur du compte, gros chiffres, écran vide.

Widgets créés sans être affichés (affichage requis, sinon tests sautés). HOME isolé."""

import unittest

from .helpers import HomeTestCase

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


def walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


class FakeWindow:
    def toast(self, _text):
        pass


class FakeStore:
    def samples(self, *_a, **_k):
        return []


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class AccountsPageTest(HomeTestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def page(self, state):
        from ccs_app.gui.accounts import AccountsPage
        page = AccountsPage(FakeWindow())
        page.render(state, FakeStore())
        return page

    def test_accounts_card_uses_account_color(self):
        from ccs_app.gui import style
        state = {"accounts": [
            {"name": "perso", "active": True, "plan": "pro", "email": "a@x",
             "limits": [{"label": "Session", "kind": "session", "percent": 42.0, "resets_at": None}]},
            {"name": "pro", "active": False, "plan": "max", "email": "b@y", "limits": []}]}
        page = self.page(state)
        cards = [w for w in walk(page.list) if w.has_css_class("ccs-card")]
        for name in ("perso", "pro"):
            self.assertTrue(any(c.has_css_class(style.account_class(name)) for c in cards), name)
        self.assertNotEqual(style.account_class("perso"), style.account_class("pro"))
        numbers = [w.get_label() for w in walk(page.list)
                   if isinstance(w, Gtk.Label) and w.has_css_class("ccs-big-number")]
        self.assertIn("42 %", numbers)

    def test_no_account_shows_status_page(self):
        page = self.page({"accounts": []})
        pages = [w for w in walk(page.list) if isinstance(w, Adw.StatusPage)]
        self.assertEqual([p.get_title() for p in pages], ["Aucun profil"])


if __name__ == "__main__":
    unittest.main()
