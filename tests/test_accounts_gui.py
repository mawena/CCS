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




@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class FriendlyErrorTest(unittest.TestCase):
    """Les erreurs d'usage d'un compte sont dites en clair, jamais en JSON brut."""

    def test_rejected_token(self):
        from ccs_app.gui.accounts import friendly_error
        raw = ('HTTP 401 : {"type":"error","error":{"type":"authentication_error",'
               '"message":"Invalid bearer token"},"request_id":"req_011Cgy"}')
        text = friendly_error(raw)
        self.assertNotIn("{", text)
        self.assertIn("reconnecte", text)

    def test_other_http_errors(self):
        from ccs_app.gui.accounts import friendly_error
        self.assertIn("Trop de demandes", friendly_error("HTTP 429 : {}"))
        self.assertIn("ne répond pas", friendly_error("HTTP 503 : Service Unavailable"))
        msg = friendly_error('HTTP 400 : {"type":"error","error":{"message":"Bad thing"}}')
        self.assertIn("Bad thing", msg)
        self.assertNotIn("{", msg)

    def test_plain_text_kept_and_long_text_cut(self):
        from ccs_app.gui.accounts import friendly_error
        self.assertEqual(friendly_error("connexion expirée ou révoquée"), "connexion expirée ou révoquée")
        self.assertLessEqual(len(friendly_error("x" * 1000)), 161)


def three_accounts(now_iso):
    lim = lambda kind, label, pct: {"kind": kind, "label": label, "percent": pct, "resets_at": now_iso}
    return {"accounts": [
        {"name": "perso", "active": True, "plan": "max", "email": "a@x",
         "limits": [lim("session", "Session (5 h)", 64), lim("weekly_all", "Semaine · tous modèles", 41),
                    lim("weekly_opus", "Semaine · Opus", 22)]},
        {"name": "pro", "active": False, "plan": "max", "email": "b@y",
         "limits": [lim("session", "Session (5 h)", 8), lim("weekly_all", "Semaine · tous modèles", 77)]},
        {"name": "boulot", "active": False, "plan": "pro", "email": "c@z", "limits": []}]}


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class HomeAccountsLayoutTest(HomeTestCase):
    """Accueil : comptes côte à côte, deux jauges par carte, le reste dans « Détails »."""

    @classmethod
    def setUpClass(cls):
        Adw.init()

    def page(self, state):
        from ccs_app.gui.accounts import AccountsPage
        page = AccountsPage(FakeWindow())
        page.render(state, FakeStore())
        return page

    def test_accounts_in_a_grid_up_to_three_per_line(self):
        from datetime import datetime, timezone
        page = self.page(three_accounts(datetime.now(timezone.utc).isoformat()))
        self.assertIsInstance(page.grid, Gtk.FlowBox)
        n, child = 0, page.grid.get_first_child()
        while child is not None:
            n += 1
            child = child.get_next_sibling()
        self.assertEqual(n, 3)
        self.assertEqual(page.grid.get_max_children_per_line(), 3)

    def test_two_gauges_shown_others_in_details(self):
        from datetime import datetime, timezone
        page = self.page(three_accounts(datetime.now(timezone.utc).isoformat()))
        card = page.grid.get_first_child().get_child()
        shown = [w.get_label() for w in walk(card)
                 if isinstance(w, Gtk.Label) and w.has_css_class("ccs-gauge-label")]
        self.assertEqual(shown, ["Session (5 h)", "Semaine · tous modèles"])
        exp = [w for w in walk(card) if isinstance(w, Gtk.Expander)]
        self.assertEqual(len(exp), 1)
        exp[0].set_expanded(True)
        labels = [w.get_label() for w in walk(card) if isinstance(w, Gtk.Label)]
        self.assertIn("Semaine · Opus", labels)
        # ouvert : le reste ouvert au rendu suivant (le service relit l'état chaque minute)
        page.render(three_accounts(datetime.now(timezone.utc).isoformat()), FakeStore())
        card = page.grid.get_first_child().get_child()
        self.assertTrue([w for w in walk(card) if isinstance(w, Gtk.Expander)][0].get_expanded())

    def test_card_text_keeps_normal_color(self):
        from ccs_app.gui import style
        css = style.accounts_css(["perso"], {})
        rule = next(line for line in css.splitlines() if ".ccs-card" in line)
        self.assertIn("color: @card_fg_color", rule)


@unittest.skipUnless(GTK, "CCS_GUI_TESTS=1 et un affichage (Xvfb) requis")
class StatusLineTest(unittest.TestCase):
    """Une seule ligne d'état par carte : erreur, puis limite de session, puis semaine, puis « tient »."""

    def test_priority(self):
        from datetime import datetime, timedelta, timezone
        from ccs_app.gui.accounts import status_of
        now = datetime.now(timezone.utc)
        soon = (now + timedelta(minutes=40)).isoformat()
        limit = {"verdict": "limit", "eta": soon, "rate_per_min": 0.5, "minutes_before_reset": 20}
        week = {"verdict": "limit", "eta": (now + timedelta(days=1)).isoformat(), "rate_per_day": 19,
                "days_before_reset": 0.2}
        ok = {"verdict": "ok", "eta": None, "rate_per_min": 0.05, "minutes_before_reset": None}
        self.assertEqual(status_of({"error": "HTTP 401 : {}", "forecast": limit}, now)[1], "error")
        self.assertEqual(status_of({"forecast": limit, "weekly_forecast": week}, now)[1], "warning")
        self.assertIn("Limite estimée", status_of({"forecast": limit, "weekly_forecast": week}, now)[0])
        self.assertIn("Semaine", status_of({"forecast": ok, "weekly_forecast": week}, now)[0])
        self.assertEqual(status_of({"forecast": ok}, now)[1], "success")
        self.assertIsNone(status_of({}, now))


if __name__ == "__main__":
    unittest.main()
