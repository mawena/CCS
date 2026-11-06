import json
import os

from ccs_app import terminal_store
from tests.helpers import HomeTestCase, write


class OptionsTest(HomeTestCase):
    def path(self):
        return self.store / "terminals.json"

    def test_defaults_without_file(self):
        self.assertEqual(terminal_store.load_options(), {"auto_resume": True, "reopen_at_start": False})

    def test_save_and_load(self):
        terminal_store.save_options({"auto_resume": False, "reopen_at_start": True})
        self.assertEqual(terminal_store.load_options(), {"auto_resume": False, "reopen_at_start": True})
        data = json.loads(self.path().read_text())
        self.assertEqual(data["version"], terminal_store.VERSION)
        self.assertEqual(os.stat(self.path()).st_mode & 0o777, 0o600)

    def test_unknown_or_odd_values_fall_back_to_defaults(self):
        write(self.path(), {"options": {"auto_resume": "oui", "reopen_at_start": True, "autre": 1}})
        self.assertEqual(terminal_store.load_options(), {"auto_resume": True, "reopen_at_start": True})
        write(self.path(), {"options": [1]})
        self.assertEqual(terminal_store.load_options(), terminal_store.DEFAULT_OPTIONS)

    def test_corrupt_file_is_tolerated_and_replaced_on_save(self):
        write(self.path(), "{pas du json")
        self.assertEqual(terminal_store.load_options(), terminal_store.DEFAULT_OPTIONS)
        terminal_store.save_options({"auto_resume": False})
        self.assertEqual(terminal_store.load_options()["auto_resume"], False)
        write(self.path(), "[1, 2]")
        self.assertEqual(terminal_store.load_options(), terminal_store.DEFAULT_OPTIONS)

    def test_saving_options_keeps_the_rest_of_the_file(self):
        write(self.path(), {"version": 1, "tabs": [{"kind": "shell", "cwd": "/w", "title": "t"}]})
        terminal_store.save_options({"auto_resume": False})
        self.assertEqual(json.loads(self.path().read_text())["tabs"],
                         [{"kind": "shell", "cwd": "/w", "title": "t"}])

    def test_unwritable_store_does_not_raise(self):
        write(self.store / "terminals.json" / "x", "dossier à la place du fichier")
        self.assertFalse(terminal_store.save_options({"auto_resume": False}))


CLAUDE = {"kind": "claude", "cwd": "/w/App", "title": "Export CSV", "session_id": "0f3c-aa_1",
          "extra_args": ["--model", "opus"], "queue": ["lance les tests"]}
SHELL = {"kind": "shell", "cwd": "/w", "title": "Terminal · w", "session_id": None, "extra_args": [],
         "queue": []}


class TabsTest(HomeTestCase):
    def path(self):
        return self.store / "terminals.json"

    def test_nothing_saved(self):
        self.assertEqual(terminal_store.load_tabs(), ([], None))

    def test_save_and_load_keep_order_and_selection(self):
        self.assertTrue(terminal_store.save_tabs([SHELL, CLAUDE], 1))
        self.assertEqual(terminal_store.load_tabs(), ([SHELL, CLAUDE], 1))
        data = json.loads(self.path().read_text())
        self.assertEqual((data["version"], data["selected"]), (terminal_store.VERSION, 1))
        self.assertIn("saved_at", data)
        self.assertEqual(os.stat(self.path()).st_mode & 0o777, 0o600)

    def test_saving_tabs_keeps_options_and_the_reverse(self):
        terminal_store.save_options({"reopen_at_start": True})
        terminal_store.save_tabs([CLAUDE], 0)
        self.assertTrue(terminal_store.load_options()["reopen_at_start"])
        terminal_store.save_options({"auto_resume": False})
        self.assertEqual(terminal_store.load_tabs(), ([CLAUDE], 0))

    def test_odd_entries_are_skipped_and_fields_normalised(self):
        write(self.path(), {"selected": 7, "tabs": [
            CLAUDE, "texte", {"kind": "autre", "cwd": "/w"}, {"kind": "shell"},
            {"kind": "shell", "cwd": "relatif", "title": "x"},
            {"kind": "claude", "cwd": "/w/B", "session_id": "../../x", "extra_args": "--model",
             "queue": ["ok", 3, ""], "title": 5},
        ]})
        tabs, selected = terminal_store.load_tabs()
        self.assertEqual(tabs[0], CLAUDE)
        self.assertEqual(tabs[1], {"kind": "claude", "cwd": "/w/B", "title": "", "session_id": None,
                                   "extra_args": [], "queue": ["ok"]})
        self.assertEqual(len(tabs), 2)
        self.assertIsNone(selected)  # hors des onglets gardés

    def test_corrupt_file(self):
        write(self.path(), "{pas du json")
        self.assertEqual(terminal_store.load_tabs(), ([], None))
        write(self.path(), {"tabs": {"kind": "shell"}, "selected": "1"})
        self.assertEqual(terminal_store.load_tabs(), ([], None))
        self.assertTrue(terminal_store.save_tabs([SHELL], 0))
        self.assertEqual(terminal_store.load_tabs(), ([SHELL], 0))
