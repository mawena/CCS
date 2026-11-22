"""Liste des conversations : écrans vides soignés (`Adw.StatusPage` avec un bouton utile)."""

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


class FakeTerminals:
    available = False


class FakeWindow:
    terminals = FakeTerminals()

    def __init__(self):
        self.new = 0

    def new_session(self):
        self.new += 1


class FakePage:
    opened, suggestions, assocs = set(), {}, []

    def __init__(self):
        self.window = FakeWindow()
        self.cleared = 0

    def clear_filters(self):
        self.cleared += 1


def status_pages(widget):
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Adw.StatusPage):
            yield child
        yield from status_pages(child)
        child = child.get_next_sibling()


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class ConversationListEmptyTest(HomeTestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def render(self, **kw):
        from ccs_app.gui.conversation_list import ConversationList
        page = FakePage()
        lst = ConversationList(page)
        lst.render([], 0, kw.get("filtering", False), False, False, kw.get("empty_all", False))
        return page, list(status_pages(lst.results))

    def test_empty_conversation_list_status_page(self):
        page, pages = self.render(empty_all=True)
        self.assertEqual([p.get_title() for p in pages], ["Aucune conversation"])
        pages[0].button.emit("clicked")
        self.assertEqual(page.window.new, 1)

    def test_filtered_empty_offers_to_clear_the_filter(self):
        page, pages = self.render(filtering=True)
        self.assertEqual([p.get_title() for p in pages], ["Aucun résultat"])
        pages[0].button.emit("clicked")
        self.assertEqual(page.cleared, 1)


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class BridgeConversationTest(unittest.TestCase):
    """Conversation qui tourne dans le pont local (ouverte du web) : rejointe dans un onglet,
    jamais reprise dans VS Code ni dans un terminal externe (deux processus la corrompraient)."""

    def test_bridge_conversation_can_be_joined_in_the_app_only(self):
        from types import SimpleNamespace
        from ccs_app.gui.conversation_list import ConversationList
        terms = SimpleNamespace(available=True)
        page = SimpleNamespace(opened={"s1", "s2"}, in_bridge={"s1"}, suggestions={})
        fake = SimpleNamespace(page=page, window=SimpleNamespace(terminals=terms))
        conv = SimpleNamespace(session_id="s1", folder_exists=True)
        self.assertIsNone(ConversationList.problem(fake, conv, target="terminal"))
        self.assertIsNotNone(ConversationList.problem(fake, conv, target="vscode"))
        self.assertIsNotNone(ConversationList.problem(fake, conv, target="external"))
        other = SimpleNamespace(session_id="s2", folder_exists=True)   # dans un terminal : bloquée
        self.assertIsNotNone(ConversationList.problem(fake, other, target="terminal"))
        terms.available = False                                      # pas de terminal intégré
        self.assertIsNotNone(ConversationList.problem(fake, conv, target="terminal"))


if __name__ == "__main__":
    unittest.main()
