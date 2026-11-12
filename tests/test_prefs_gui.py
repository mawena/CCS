"""Onglet Réglages : conseils, conseiller de formule, raccourcis clavier.

Widgets créés sans être affichés (affichage requis, sinon tests sautés). HOME isolé (profils
`perso` (Pro) et `pro` (Max sans palier)), réglages GNOME simulés : jamais ceux du bureau ;
rien du système (systemctl, service, D-Bus, intégration)."""

import json
import os
from datetime import datetime, timezone
import subprocess
import unittest
import warnings
from unittest import mock

from ccs_app import shortcuts as sc

from .helpers import HomeTestCase, write

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk, Pango
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


class FakeTerminals:
    available = False
    options = {"auto_resume": True, "reopen_at_start": False}


class FakeWindow:
    def __init__(self):
        self.toasts, self.auto = [], []
        self.terminals = FakeTerminals()

    def toast(self, text):
        self.toasts.append(text)

    def sync_auto_switch(self, enabled):
        self.auto.append(enabled)


def walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class PrefsPageTest(HomeTestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        super().setUp()
        from ccs_app.gui import prefs
        self.mod = prefs
        self.backend = sc.MemoryBackend.gnome()
        self.refreshes = []
        for p in (
                # Raccourcis : moteur en mémoire, jamais les vrais réglages GNOME.
                mock.patch.object(sc, "default_backend", return_value=self.backend),
                mock.patch.object(sc, "command_for", side_effect=lambda a: "/usr/bin/" + sc.action(a).display),
                mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}),
                # Rien du système : service, D-Bus, intégration, nouvelles versions.
                mock.patch.object(prefs, "systemctl",
                                  return_value=subprocess.CompletedProcess([], 0, "active\n", "")),
                mock.patch("ccs_app.daemon.request_refresh", side_effect=lambda: self.refreshes.append(1)),
                mock.patch("ccs_app.daemon.running_pid", return_value=None),
                mock.patch("ccs_app.tray.watcher_available", return_value=True),
                mock.patch("ccs_app.updates.available", return_value=None),
                mock.patch("ccs_app.archive.stats", return_value=(3, 5 * 1024 * 1024)),
                mock.patch("ccs_app.integration.status", return_value={"statusline": None, "hook": False})):
            p.start()
            self.addCleanup(p.stop)
        self.window = FakeWindow()

    # ---- outils ----------------------------------------------------------------------

    def page(self, settings=None):
        if settings is not None:
            write(self.store / "settings.json", settings)
        page = self.mod.PrefsPage(self.window)
        page.render()
        return page

    def rows(self, page):
        return {r.get_title(): r for r in walk(page) if isinstance(r, Adw.PreferencesRow)}

    def group(self, page, title):
        return next(g for g in page.groups if g.get_title() == title)

    def saved(self):
        return json.loads((self.store / "settings.json").read_text())

    def add_profile(self, name, plan):
        write(self.store / name / "oauth.json", {"claudeAiOauth": {"subscriptionType": plan}})
        write(self.store / name / "account.json", {"accountUuid": f"u-{name}", "emailAddress": f"{name}@x"})

    # ---- groupes -----------------------------------------------------------------------

    def test_prefs_color_scheme_saved(self):
        page = self.page()
        row = self.rows(page)["Thème"]
        row.set_selected(2)                       # Sombre
        self.assertEqual(self.saved()["appearance"]["color_scheme"], "sombre")
        self.assertEqual(Adw.StyleManager.get_default().get_color_scheme(), Adw.ColorScheme.FORCE_DARK)
        row.set_selected(0)
        self.assertEqual(self.saved()["appearance"]["color_scheme"], "auto")
        self.addCleanup(Adw.StyleManager.get_default().set_color_scheme, Adw.ColorScheme.DEFAULT)

    def test_prefs_account_color_saved(self):
        from gi.repository import Gdk
        self.add_profile("perso", "pro")
        page = self.page()
        self.assertIn("perso", page.color_buttons)
        rgba = Gdk.RGBA()
        rgba.parse("#112233")
        page.color_buttons["perso"].set_rgba(rgba)
        self.assertEqual(self.saved()["appearance"]["account_colors"], {"perso": "#112233"})

    def test_groups_and_order(self):
        page = self.page()
        titles = [g.get_title() for g in page.groups]
        for title in ("Conseils", "Conseiller de formule", "Raccourcis clavier"):
            self.assertIn(title, titles)
        self.assertLess(titles.index("Alertes"), titles.index("Conseils"))
        self.assertLess(titles.index("Intégration dans Claude Code"), titles.index("Raccourcis clavier"))
        self.assertLess(titles.index("Raccourcis clavier"), titles.index("Warm-up"))

    def test_phase_11_groups_after_the_shortcuts(self):
        from ccs_app.gui.backup_group import BackupGroup
        from ccs_app.gui.phone_group import PhoneGroup
        page = self.page()
        titles = [g.get_title() for g in page.groups]
        for title in ("Téléphone", "Sauvegarde", "Archive des conversations", "Sessions ouvertes",
                      "Tâches", "Budgets par projet"):
            self.assertIn(title, titles)
        self.assertLess(titles.index("Raccourcis clavier"), titles.index("Téléphone"))
        self.assertLess(titles.index("Téléphone"), titles.index("Sauvegarde"))
        self.assertLess(titles.index("Budgets par projet"), titles.index("Warm-up"))
        self.assertEqual(len([g for g in page.groups if isinstance(g, PhoneGroup)]), 1)
        self.assertEqual(len([g for g in page.groups if isinstance(g, BackupGroup)]), 1)
        page.render()  # recréés à chaque rendu, jamais en double
        self.assertEqual(len([g for g in walk(page) if isinstance(g, (PhoneGroup, BackupGroup))]), 2)

    def test_phone_group_writes_the_phone_section(self):
        page = self.page()
        phone_group = next(g for g in page.groups if g.get_title() == "Téléphone")
        phone_group.enabled.set_active(True)
        self.assertTrue(self.saved()["phone"]["enabled"])

    def test_phase_11_rows_work_without_their_sections(self):
        # settings.json sans archive, tâches, budget, sessions ni contexte : valeurs des modules.
        rows = self.rows(self.page())
        self.assertTrue(rows["Archiver les conversations"].get_active())
        self.assertEqual(rows["Archiver après (jours d'inactivité)"].get_value(), 1)
        self.assertEqual(rows["Supprimer l'archive après (jours)"].get_value(), 0)
        self.assertEqual(rows["Sessions inactives après (h)"].get_value(), 2)
        self.assertEqual(rows["Seuil du contexte lourd (tokens)"].get_value(), 150000)
        self.assertEqual(rows["Tentatives par tâche"].get_value(), 3)
        self.assertTrue(rows["Exécuter les tâches"].get_active())
        self.assertTrue(rows["Alertes de budget"].get_active())

    def test_archive_size_is_computed_in_a_thread(self):
        import time
        from gi.repository import GLib
        size = self.rows(self.page())["Taille de l'archive"]
        ctx = GLib.MainContext.default()
        for _ in range(300):
            while ctx.iteration(False):
                pass
            if size.get_subtitle() != "Calcul…":
                break
            time.sleep(0.01)
        self.assertEqual(size.get_subtitle(), "3 conversation(s), 5 Mo")

    def test_phase_11_rows_save_their_values(self):
        rows = self.rows(self.page())
        rows["Archiver les conversations"].set_active(False)
        rows["Archiver après (jours d'inactivité)"].set_value(4)
        rows["Supprimer l'archive après (jours)"].set_value(90)
        rows["Sessions inactives après (h)"].set_value(5)
        rows["Alerte de contexte lourd"].set_active(False)
        rows["Seuil du contexte lourd (tokens)"].set_value(200000)
        rows["Exécuter les tâches"].set_active(False)
        rows["Tentatives par tâche"].set_value(5)
        rows["Alertes de budget"].set_active(False)
        saved = self.saved()
        self.assertEqual(saved["archive"], {"enabled": False, "idle_days": 4, "max_age_days": 90})
        self.assertEqual(saved["sessions"]["idle_hours"], 5)
        self.assertEqual(saved["context_alert"], {"enabled": False, "threshold_tokens": 200000})
        self.assertFalse(saved["tasks"]["enabled"])
        self.assertEqual(saved["tasks"]["max_attempts"], 5)
        self.assertFalse(saved["budget"]["enabled"])

    def test_night_range_is_validated_and_saved(self):
        row = self.rows(self.page())["Plage de nuit"]
        entries = [w for w in walk(row) if isinstance(w, Gtk.Entry)]
        self.assertEqual([e.get_text() for e in entries], ["23:00", "07:00"])
        entries[0].set_text("22:30")
        self.assertEqual(self.saved()["tasks"]["night"], {"start": "22:30", "end": "07:00"})
        entries[1].set_text("25:00")  # invalide : refusé, signalé
        self.assertIn("error", entries[1].get_css_classes())
        self.assertEqual(self.saved()["tasks"]["night"]["end"], "07:00")

    def test_shortcuts_group_uses_the_injected_backend(self):
        from ccs_app.gui.shortcuts_group import ShortcutsGroup
        page = self.page()
        groups = [g for g in page.groups if isinstance(g, ShortcutsGroup)]
        self.assertEqual(len(groups), 1)
        self.assertIs(groups[0].backend, self.backend)
        self.assertEqual(list(groups[0].rows), list(sc.ACTION_IDS))
        self.assertEqual(self.backend.log, [])  # afficher n'écrit rien
        page.render()  # recréé à chaque rendu, jamais en double
        self.assertEqual(len([g for g in page.groups if isinstance(g, ShortcutsGroup)]), 1)
        self.assertEqual(len([g for g in walk(page) if isinstance(g, ShortcutsGroup)]), 1)

    def test_shortcut_toast_goes_to_the_window(self):
        page = self.page()
        g = self.group(page, "Raccourcis clavier")
        g.rows["pause"].switch.set_active(True)
        self.assertTrue(self.window.toasts)
        self.assertIn("Super+Alt+P", self.window.toasts[-1])

    def test_render_writes_nothing(self):
        self.add_profile("equipe", "team")
        page = self.page()
        page.render()
        self.assertFalse((self.store / "settings.json").exists())
        self.assertEqual(self.refreshes, [])

    # ---- conseils ------------------------------------------------------------------------

    def test_model_advice(self):
        page = self.page()
        rows = self.rows(page)
        switch = rows["Proposer un modèle moins cher près des limites"]
        spin = rows["Seuil du conseil (%)"]
        self.assertTrue(switch.get_active())
        self.assertEqual(spin.get_value(), 80)
        adj = spin.get_adjustment()
        self.assertEqual((adj.get_lower(), adj.get_upper()), (50, 99))
        self.assertIn("Sonnet", switch.get_subtitle())
        self.assertIn("→ sonnet ?", switch.get_subtitle())
        spin.set_value(90)
        self.assertEqual(self.saved()["alerts"]["model_advice_pct"], 90)
        switch.set_active(False)
        self.assertIs(self.saved()["alerts"]["model_advice"], False)
        self.assertFalse(spin.get_sensitive())
        switch.set_active(True)
        self.assertTrue(spin.get_sensitive())

    def test_weekly_report(self):
        page = self.page()
        rows = self.rows(page)
        switch, day, hour = rows["Bilan de la semaine"], rows["Jour du bilan"], rows["Heure du bilan"]
        self.assertTrue(switch.get_active())
        labels = [day.get_model().get_string(i) for i in range(day.get_model().get_n_items())]
        self.assertEqual(labels, ["Début de semaine des comptes", "Lundi", "Mardi", "Mercredi", "Jeudi",
                                  "Vendredi", "Samedi", "Dimanche"])
        self.assertEqual(day.get_selected(), 0)
        self.assertEqual(hour.get_value(), 9)
        adj = hour.get_adjustment()
        self.assertEqual((adj.get_lower(), adj.get_upper()), (0, 23))
        self.assertIn("jour fixe", hour.get_subtitle())
        day.set_selected(1)
        self.assertEqual(self.saved()["alerts"]["weekly_report_day"], 0)
        day.set_selected(7)
        self.assertEqual(self.saved()["alerts"]["weekly_report_day"], 6)
        day.set_selected(0)
        self.assertIsNone(self.saved()["alerts"]["weekly_report_day"])
        hour.set_value(18)
        self.assertEqual(self.saved()["alerts"]["weekly_report_hour"], 18)
        switch.set_active(False)
        self.assertIs(self.saved()["alerts"]["weekly_report"], False)
        self.assertFalse(day.get_sensitive())
        self.assertFalse(hour.get_sensitive())

    def test_monthly_report(self):
        page = self.page()
        rows = self.rows(page)
        switch, hour = rows["Rapport mensuel"], rows["Heure du rapport mensuel"]
        self.assertTrue(switch.get_active())
        self.assertEqual(hour.get_value(), 9)
        adj = hour.get_adjustment()
        self.assertEqual((adj.get_lower(), adj.get_upper()), (0, 23))
        hour.set_value(18)
        self.assertEqual(self.saved()["alerts"]["monthly_report_hour"], 18)
        switch.set_active(False)
        self.assertIs(self.saved()["alerts"]["monthly_report"], False)
        self.assertFalse(hour.get_sensitive())
        switch.set_active(True)
        self.assertTrue(hour.get_sensitive())

    def test_weekly_report_day_read_back(self):
        page = self.page({"alerts": {"weekly_report_day": 4, "weekly_report_hour": 7}})
        rows = self.rows(page)
        self.assertEqual(rows["Jour du bilan"].get_selected(), 5)  # vendredi
        self.assertEqual(rows["Heure du bilan"].get_value(), 7)

    def test_invalid_day_falls_back_to_accounts(self):
        page = self.page({"alerts": {"weekly_report_day": "lundi"}})
        self.assertEqual(self.rows(page)["Jour du bilan"].get_selected(), 0)

    # ---- ne pas déranger -------------------------------------------------------------------

    def buttons(self, page):
        return {b.get_label(): b for b in walk(page) if isinstance(b, Gtk.Button)}

    def test_quiet_group_after_alerts(self):
        page = self.page()
        titles = [g.get_title() for g in page.groups]
        self.assertEqual(titles.index("Ne pas déranger"), titles.index("Alertes") + 1)

    def test_quiet_settings_are_saved(self):
        page = self.page()
        rows = self.rows(page)
        self.assertFalse(rows["Plage de silence"].get_active())
        rows["Plage de silence"].set_active(True)
        self.assertTrue(self.saved()["alerts"]["quiet"]["enabled"])
        waiting = rows["Toujours prévenir quand une session attend ma réponse"]
        self.assertTrue(waiting.get_active())
        waiting.set_active(False)
        self.assertFalse(self.saved()["alerts"]["quiet"]["allow_waiting"])
        self.assertEqual(self.saved()["alerts"]["quiet"]["start"], "22:00")

    def test_quiet_hours_are_validated(self):
        page = self.page()
        entries = [e for e in walk(self.group(page, "Ne pas déranger"))
                   if isinstance(e, Gtk.Entry)]
        start, end = entries
        end.set_text("07:30")
        self.assertEqual(self.saved()["alerts"]["quiet"]["end"], "07:30")
        start.set_text("25:99")
        self.assertEqual(self.saved()["alerts"]["quiet"]["start"], "22:00")
        self.assertTrue(start.has_css_class("error"))

    def test_quiet_temporary_buttons(self):
        from ccs_app import quiet
        page = self.page()
        buttons = self.buttons(page)
        buttons["1 h"].emit("clicked")
        st = quiet.quiet_state(datetime.now(timezone.utc))
        self.assertEqual(st.source, "temporaire")
        self.assertTrue(self.refreshes)
        self.assertIn("Silence", self.window.toasts[-1])
        buttons["Reprendre"].emit("clicked")
        self.assertIsNone(quiet.quiet_state(datetime.now(timezone.utc)))

    # ---- conseiller de formule ---------------------------------------------------------------

    def test_advisor_numbers(self):
        page = self.page()
        rows = self.rows(page)
        for title, default, bounds, key, value in (
                ("Semaines analysées", 4, (1, 12), "weeks", 6),
                ("Marge de sécurité (%)", 20, (0, 100), "margin_pct", 35),
                ("Comptes au plus", 3, (1, 5), "max_accounts", 2)):
            row = rows[title]
            self.assertEqual(row.get_value(), default, title)
            adj = row.get_adjustment()
            self.assertEqual((adj.get_lower(), adj.get_upper()), bounds, title)
            row.set_value(value)
            self.assertEqual(self.saved()["advisor"][key], value, title)

    def plan_rows(self, page):
        return {t: r for t, r in self.rows(page).items() if isinstance(r, Adw.ComboRow) and t.startswith("Formule")}

    def test_plan_rows_only_for_unknown_uncertain_or_forced(self):
        self.add_profile("equipe", "team")
        page = self.page()
        rows = self.plan_rows(page)
        # perso : Pro détectée, pas de ligne ; pro : Max sans palier ; equipe : formule inconnue.
        self.assertEqual(sorted(rows), ["Formule de « equipe »", "Formule de « pro »"])
        model = rows["Formule de « pro »"].get_model()
        self.assertEqual([model.get_string(i) for i in range(model.get_n_items())],
                         ["Automatique", "Pro", "Max", "Ultra"])
        self.assertEqual(rows["Formule de « pro »"].get_selected(), 0)
        self.assertIn("Ultra", rows["Formule de « pro »"].get_subtitle())
        self.assertIn("team", rows["Formule de « equipe »"].get_subtitle())
        self.assertIn("ignoré", rows["Formule de « equipe »"].get_subtitle())

    def test_known_plan_with_tier_has_no_row(self):
        write(self.store / "pro" / "oauth.json", {"claudeAiOauth": {
            "subscriptionType": "max", "rateLimitTier": "default_claude_max_20x"}})
        self.assertEqual(self.plan_rows(self.page()), {})

    def test_forced_plan_saved_and_removed(self):
        self.add_profile("equipe", "team")
        page = self.page({"advisor": {"profile_plans": {"ancien": "pro"}}})
        row = self.plan_rows(page)["Formule de « equipe »"]
        row.set_selected(3)
        self.assertEqual(self.saved()["advisor"]["profile_plans"], {"ancien": "pro", "equipe": "max20"})
        self.assertIn("imposée", row.get_subtitle().lower())
        row.set_selected(2)
        self.assertEqual(self.saved()["advisor"]["profile_plans"], {"ancien": "pro", "equipe": "max5"})
        row.set_selected(0)
        self.assertEqual(self.saved()["advisor"]["profile_plans"], {"ancien": "pro"})

    def test_existing_override_shows_its_row(self):
        page = self.page({"advisor": {"profile_plans": {"perso": "max5"}}})
        row = self.plan_rows(page)["Formule de « perso »"]
        self.assertEqual(row.get_selected(), 2)
        self.assertIn("détectée : Pro", row.get_subtitle())
        row.set_selected(1)
        self.assertEqual(self.saved()["advisor"]["profile_plans"], {"perso": "pro"})

    def test_prices(self):
        page = self.page({"advisor": {"plan_prices": {"max20": 180}}})
        rows = self.rows(page)
        pro, mx, ultra = rows["Pro ($/mois)"], rows["Max ($/mois)"], rows["Ultra ($/mois)"]
        self.assertEqual((pro.get_value(), mx.get_value(), ultra.get_value()), (20, 100, 180))
        self.assertIn("Ultra 180 $", rows["Tarifs des formules"].get_subtitle())
        pro.set_value(17)
        self.assertEqual(self.saved()["advisor"]["plan_prices"], {"max20": 180, "pro": 17})
        pro.set_value(20)
        self.assertEqual(self.saved()["advisor"]["plan_prices"], {"max20": 180})
        ultra.set_value(200)
        self.assertEqual(self.saved()["advisor"]["plan_prices"], {})
        self.assertNotIn("personnalisés", rows["Tarifs des formules"].get_subtitle())

    def test_prices_subtitle_mentions_custom(self):
        rows = self.rows(self.page({"advisor": {"plan_prices": {"pro": 17}}}))
        self.assertIn("personnalisés", rows["Tarifs des formules"].get_subtitle())

    # ---- fenêtre étroite -------------------------------------------------------------------

    def rooted(self, page):
        """Page rattachée à une fenêtre jamais affichée (styles et listes comme à l'écran)."""
        from ccs_app.gui.common import install_css
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # CssProvider.load_from_data
            install_css()
        win = Gtk.Window(child=page)
        self.addCleanup(win.destroy)
        return page

    def test_plan_choice_never_abbreviated(self):
        self.add_profile("equipe", "team")
        page = self.rooted(self.page())
        row = self.plan_rows(page)["Formule de « equipe »"]
        shown = [w for w in walk(row) if isinstance(w, Gtk.Label) and w.get_label() == "Automatique"
                 and w.get_child_visible()]
        self.assertTrue(shown)
        self.assertTrue(all(w.get_ellipsize() == Pango.EllipsizeMode.NONE for w in shown))

    # ---- Chat et fichiers ----------------------------------------------

    def test_chat_files_settings_saved(self):
        page = self.page()
        rows = self.rows(page)
        spin = rows["Mettre en veille un chat inactif après (min)"]
        spin.set_value(45)
        self.assertEqual(self.saved()["chat"]["idle_suspend_min"], 45)
        spin.set_value(0)
        self.assertEqual(self.saved()["chat"]["idle_suspend_min"], 0)
        rows["Afficher les fichiers ignorés par git"].set_active(True)
        self.assertTrue(self.saved()["files"]["show_ignored"])
        rows["Disposition par défaut"].set_selected(0)
        self.assertEqual(self.saved()["files"]["layout"], "A")
        rows["Disposition par défaut"].set_selected(1)
        self.assertEqual(self.saved()["files"]["layout"], "B")
        rights = rows["Droits par défaut des nouveaux chats"]
        rights.set_selected(2)                    # Plan
        self.assertEqual(self.saved()["chat"]["rights"], "plan")

    def test_rights_everything_asks_confirmation(self):
        page = self.page()
        asked = []
        page.confirm_dangerous = lambda yes, no: asked.append((yes, no))
        rights = self.rows(page)["Droits par défaut des nouveaux chats"]
        rights.set_selected(3)                    # Tout autoriser
        self.assertEqual(len(asked), 1)
        self.assertEqual(page.s["chat"]["rights"], "manual")
        asked[0][1]()                             # refus : retour au choix précédent
        self.assertEqual(rights.get_selected(), 0)
        self.assertFalse(self.store.joinpath("settings.json").exists())
        rights.set_selected(3)
        asked[1][0]()                             # accepté
        self.assertEqual(self.saved()["chat"]["rights"], "bypassPermissions")

    def test_groups_fit_the_narrow_window(self):
        """360 px moins les marges de la page (2 × 12 px). Le groupe des raccourcis clavier
        (shortcuts_group.py) n'est pas mesuré ici."""
        from ccs_app.gui.shortcuts_group import ShortcutsGroup
        self.add_profile("equipe", "team")
        page = self.rooted(self.page({"advisor": {"profile_plans": {"perso": "max20"}},
                                      "warmup": {"pro": [{"days": [0, 1], "time": "07:00"}]}}))
        for g in page.groups:
            if not isinstance(g, ShortcutsGroup):
                self.assertLessEqual(g.measure(Gtk.Orientation.HORIZONTAL, -1)[0], 360 - 24, g.get_title())


if __name__ == "__main__":
    unittest.main()
