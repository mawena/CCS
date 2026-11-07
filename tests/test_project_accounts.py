import json
import os
import unittest

from ccs_app import project_accounts as pa
from ccs_app.project_accounts import Association
from tests.helpers import HomeTestCase, write

PROFILES = ("perso", "pro")


class StorageTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.home / "Work" / "App"
        (self.app / "src" / "lib").mkdir(parents=True)

    def test_set_get_and_file_format(self):
        a = pa.set(str(self.app), "pro")
        self.assertEqual(a, Association(str(self.app), "pro", True))
        self.assertEqual(pa.get(str(self.app)), a)
        path = self.store / "projects.json"
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(json.loads(path.read_text()),
                         {"version": 1, "projects": {str(self.app): {"profile": "pro", "ask": True}}})

    def test_subfolder_inherits_from_the_project(self):
        pa.set(str(self.app), "pro")
        self.assertEqual(pa.get(str(self.app / "src" / "lib")).cwd, str(self.app))
        self.assertIsNone(pa.get(str(self.home / "Work")))
        self.assertIsNone(pa.get(str(self.home / "Work" / "App2")))  # même début, autre dossier

    def test_nearest_project_wins(self):
        pa.set(str(self.home / "Work"), "perso")
        pa.set(str(self.app), "pro")
        self.assertEqual(pa.get(str(self.app / "src")).profile, "pro")
        self.assertEqual(pa.get(str(self.home / "Work" / "Autre")).profile, "perso")

    def test_root_folder(self):
        pa.set("/", "perso")
        self.assertEqual(pa.get(str(self.app)).cwd, "/")

    def test_paths_normalized(self):
        pa.set(str(self.app) + "/", "pro")
        self.assertEqual(pa.get("~/Work/App/src/../").cwd, str(self.app))
        self.assertEqual([a.cwd for a in pa.all()], [str(self.app)])

    def test_remove(self):
        pa.set(str(self.app), "pro")
        self.assertIsNone(pa.set(str(self.app), None))
        self.assertIsNone(pa.get(str(self.app)))
        self.assertEqual(pa.all(), [])
        self.assertIsNone(pa.set(str(self.app), None))  # rien à retirer : pas d'erreur

    def test_ask_kept_for_the_same_account_and_reset_for_another(self):
        pa.set(str(self.app), "pro")
        self.assertTrue(pa.set_ask(str(self.app), False))
        self.assertFalse(pa.set(str(self.app), "pro").ask)
        self.assertTrue(pa.set(str(self.app), "perso").ask)
        self.assertFalse(pa.set_ask(str(self.home / "Ailleurs"), False))  # aucune association

    def test_all_sorted(self):
        pa.set(str(self.app), "pro")
        pa.set(str(self.home / "Work" / "Autre"), "perso")
        self.assertEqual([a.cwd for a in pa.all()], [str(self.app), str(self.home / "Work" / "Autre")])

    def test_corrupted_or_foreign_file_tolerated_then_replaced(self):
        for content in ("{pas du json", "[1, 2]", json.dumps({"version": 99, "projects": {}})):
            with self.subTest(content=content):
                write(self.store / "projects.json", content)
                self.assertEqual(pa.all(), [])
                self.assertIsNone(pa.get(str(self.app)))
        pa.set(str(self.app), "pro")
        self.assertEqual(pa.get(str(self.app)).profile, "pro")

    def test_unexpected_entries_skipped(self):
        write(self.store / "projects.json", {"version": 1, "projects": {
            str(self.app): {"profile": "pro", "ask": "oui"},
            "relatif/dossier": {"profile": "pro"},
            "/x": {"profile": 3}, "/y": "pro", "/z": {"profile": "../etc"}}})
        self.assertEqual(pa.all(), [Association(str(self.app), "pro", True)])

    def test_invalid_account_name_refused(self):
        for bad in ("", "../x", "a b", "-x"):
            with self.assertRaises(ValueError, msg=bad):
                pa.set(str(self.app), bad)

    def test_write_failure_raises(self):
        os.chmod(self.store, 0o500)
        try:
            with self.assertRaises(OSError):
                pa.set(str(self.app), "pro")
        finally:
            os.chmod(self.store, 0o700)


class ProposalTest(unittest.TestCase):
    APP = Association("/w/App", "pro", True)

    def propose(self, cwd="/w/App/src", active="perso", paused=False, assocs=None):
        return pa.proposal(cwd, active, PROFILES, paused, [self.APP] if assocs is None else assocs)

    def test_project_on_another_account(self):
        self.assertEqual(self.propose(), self.APP)
        self.assertEqual(self.propose(active=None), self.APP)  # compte actif non enregistré

    def test_nothing_to_propose(self):
        self.assertIsNone(self.propose(cwd="/w/Autre"))
        self.assertIsNone(self.propose(active="pro"))
        self.assertIsNone(self.propose(assocs=[Association("/w/App", "pro", False)]))   # ne plus demander
        self.assertIsNone(self.propose(assocs=[Association("/w/App", "supprime", True)]))  # compte disparu
        self.assertIsNone(self.propose(paused=True))  # pause : pas de bascule proposée
        self.assertIsNone(self.propose(cwd=""))

    def test_preferred_account_for_a_new_session(self):
        prefer = pa.preferred_profile
        self.assertEqual(prefer("/w/App", PROFILES, False, [self.APP]), "pro")
        self.assertIsNone(prefer("/w/App", PROFILES, True, [self.APP]))
        self.assertIsNone(prefer("/w/App", PROFILES, False, [Association("/w/App", "pro", False)]))
        self.assertIsNone(prefer("/w/App", ("perso",), False, [self.APP]))
        self.assertIsNone(prefer("/w/Autre", PROFILES, False, [self.APP]))

    def test_origin_of_a_switch_from_a_new_session(self):
        self.assertEqual(pa.origin_for("/w/App/src", "pro", [self.APP]), "projet")
        self.assertIsNone(pa.origin_for("/w/App", "perso", [self.APP]))
        self.assertIsNone(pa.origin_for("/w/Autre", "pro", [self.APP]))
        self.assertIsNone(pa.origin_for("/w/App", None, [self.APP]))

    def test_question(self):
        self.assertEqual(pa.question(self.APP, "perso"),
                         ("Ce projet utilise le compte « pro »",
                          "Basculer ? Le compte actif est « perso ». "
                          "La bascule s'applique à toutes les sessions ouvertes."))
        self.assertEqual(pa.question(self.APP, None)[1],
                         "Basculer ? Le compte connecté n'est enregistré dans aucun profil. "
                         "La bascule s'applique à toutes les sessions ouvertes.")

    def test_card_text(self):
        text = pa.card_text
        self.assertEqual(text("/w/App", "perso", False, [self.APP]),
                         "Compte du projet : pro · bascule proposée à l'ouverture")
        self.assertEqual(text("/w/App/src", "pro", False, [self.APP], home="/h"),
                         "Compte du projet : pro (hérité de /w/App)")
        self.assertEqual(text("/w/App", "perso", True, [self.APP]),
                         "Compte du projet : pro · pas de bascule proposée pendant la pause")
        self.assertEqual(text("/w/App", "perso", False, [Association("/w/App", "pro", False)]),
                         "Compte du projet : pro · sans proposition de bascule")
        self.assertIsNone(text("/w/Autre", "perso", False, [self.APP]))

    def test_hint(self):
        hint = pa.hint
        self.assertEqual(hint("/w/App", PROFILES, False, [self.APP]), "Compte du projet : pro")
        self.assertEqual(hint("/w/App/src", PROFILES, False, [self.APP], home="/h"),
                         "Compte du projet : pro (hérité de /w/App)")
        self.assertEqual(hint("/w/App", PROFILES, True, [self.APP]),
                         "Compte du projet : pro — CCS en pause, rien n'est présélectionné")
        self.assertEqual(hint("/w/App", PROFILES, False, [Association("/w/App", "pro", False)]),
                         "Compte du projet : pro — sans proposition de bascule")
        self.assertEqual(hint("/w/App", ("perso",), False, [self.APP]),
                         "Compte du projet : pro — compte introuvable")
        self.assertIsNone(hint("/w/Autre", PROFILES, False, [self.APP]))


class TextTest(unittest.TestCase):
    def test_listing(self):
        text = pa.format_text([Association("/h/Work/App", "pro", True),
                               Association("/srv/site", "perso", False)], home="/h")
        self.assertEqual(text.splitlines(), ["~/Work/App  → pro",
                                             "/srv/site   → perso (sans proposition de bascule)"])
        self.assertEqual(pa.format_text([], home="/h"), "Aucun projet associé à un compte.")


class CommandTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.home / "Work" / "App"
        (self.app / "src").mkdir(parents=True)

    def run_cmd(self, *args, cwd=None):
        return pa.command(list(args), cwd=str(cwd or self.app), profiles=PROFILES)

    def test_set_show_and_remove(self):
        code, text = self.run_cmd(str(self.app), "pro")
        self.assertEqual((code, text), (0, "~/Work/App → pro : une session ouverte depuis l'application "
                                           "dans ce projet proposera de basculer sur pro."))
        self.assertEqual(pa.get(str(self.app)).profile, "pro")
        self.assertEqual(self.run_cmd(), (0, "~/Work/App  → pro"))
        self.assertEqual(self.run_cmd(str(self.app / "src")), (0, "~/Work/App/src → pro (hérité de ~/Work/App)"))
        self.assertEqual(self.run_cmd(str(self.app), "aucun"), (0, "~/Work/App n'est plus associé à un compte."))
        self.assertEqual(self.run_cmd(str(self.app), "aucun"), (0, "~/Work/App n'était associé à aucun compte."))
        self.assertEqual(self.run_cmd(str(self.app)),
                         (0, "Aucun compte associé à ~/Work/App : le compte actif sera utilisé."))

    def test_one_argument_is_an_account_for_the_current_folder(self):
        self.assertEqual(self.run_cmd("pro")[0], 0)
        self.assertEqual(pa.get(str(self.app)).profile, "pro")
        self.assertEqual(self.run_cmd("aucun")[0], 0)
        self.assertIsNone(pa.get(str(self.app)))

    def test_relative_folder(self):
        self.assertEqual(self.run_cmd(".", "pro", cwd=self.app / "src")[0], 0)
        self.assertEqual(pa.get(str(self.app / "src")).cwd, str(self.app / "src"))

    def test_errors(self):
        self.assertEqual(self.run_cmd(str(self.app), "inconnu"),
                         (1, "compte inconnu : inconnu (voir « ccs list »)"))
        self.assertEqual(self.run_cmd(str(self.home / "absent"), "pro"),
                         (1, "dossier introuvable : ~/absent"))
        self.assertEqual(self.run_cmd("ni-dossier-ni-compte")[0], 2)
        self.assertEqual(self.run_cmd("a", "b", "c"), (2, pa.USAGE))

    def test_unwritable_file(self):
        os.chmod(self.store, 0o500)
        try:
            code, text = self.run_cmd(str(self.app), "pro")
        finally:
            os.chmod(self.store, 0o700)
        self.assertEqual(code, 1)
        self.assertTrue(text.startswith("enregistrement impossible"))


if __name__ == "__main__":
    unittest.main()
