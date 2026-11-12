import unittest

from tests.helpers import gui_ready

GTK = gui_ready()


@unittest.skipUnless(GTK, "affichage graphique indisponible")
class StyleGuiTest(unittest.TestCase):
    def test_color_scheme_maps_to_style_manager(self):
        from gi.repository import Adw
        from ccs_app.gui import style
        sm = Adw.StyleManager.get_default()
        for value, expected in (("sombre", Adw.ColorScheme.FORCE_DARK),
                                ("clair", Adw.ColorScheme.FORCE_LIGHT),
                                ("auto", Adw.ColorScheme.DEFAULT)):
            style.apply_color_scheme(value)
            self.assertEqual(sm.get_color_scheme(), expected)

    def test_account_class_is_css_safe(self):
        from ccs_app.gui import style
        for name in ("mawena.2", "Pro Perso", "é", "perso"):
            self.assertRegex(style.account_class(name), r"^ccs-account-[a-z0-9_-]+$")
        self.assertNotEqual(style.account_class("mawena.2"), style.account_class("mawena-2"))

    def test_css_has_no_parsing_error(self):
        from gi.repository import Gtk
        from ccs_app.gui import style
        errors = []
        for css in (style.BASE_CSS, style.accounts_css(["mawena.2", "pro"], {})):
            prov = Gtk.CssProvider()
            prov.connect("parsing-error", lambda _p, sec, err: errors.append(err.message))
            prov.load_from_data(css.encode())
        self.assertEqual(errors, [])

    def test_install_and_refresh_parse(self):
        from ccs_app.gui import style
        style.install()
        style.refresh_accounts(["mawena.2", "pro"], {"pro": "#112233"})
        self.assertIn("#112233", style.accounts_css(["pro"], {"pro": "#112233"}))


if __name__ == "__main__":
    unittest.main()
