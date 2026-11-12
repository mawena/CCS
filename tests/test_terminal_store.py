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
          "extra_args": ["--model", "opus"], "queue": ["lance les tests"],
          "chat": {"model": None, "effort": None, "ultracode": False, "rights": None}}
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
                                   "extra_args": [], "queue": ["ok"],
                                   "chat": terminal_store.DEFAULT_CHAT})
        self.assertEqual(len(tabs), 2)
        self.assertIsNone(selected)  # hors des onglets gardés

    def test_corrupt_file(self):
        write(self.path(), "{pas du json")
        self.assertEqual(terminal_store.load_tabs(), ([], None))
        write(self.path(), {"tabs": {"kind": "shell"}, "selected": "1"})
        self.assertEqual(terminal_store.load_tabs(), ([], None))
        self.assertTrue(terminal_store.save_tabs([SHELL], 0))
        self.assertEqual(terminal_store.load_tabs(), ([SHELL], 0))


class ChatAndPanesTest(HomeTestCase):
    def path(self):
        return self.store / "terminals.json"

    def test_v1_file_reads_with_chat_defaults(self):
        write(self.path(), {"version": 1, "selected": 0, "options": {"auto_resume": False},
                            "tabs": [{"kind": "claude", "cwd": "/w/App", "title": "T",
                                      "session_id": "abc", "extra_args": ["--model", "opus"],
                                      "queue": ["a"]},
                                     {"kind": "shell", "cwd": "/w", "title": "S"}]})
        tabs, selected = terminal_store.load_tabs()
        self.assertEqual(selected, 0)
        self.assertEqual(tabs[0]["chat"], {"model": None, "effort": None, "ultracode": False,
                                           "rights": None})
        self.assertEqual((tabs[0]["session_id"], tabs[0]["extra_args"], tabs[0]["queue"]),
                         ("abc", ["--model", "opus"], ["a"]))
        self.assertNotIn("chat", tabs[1])
        self.assertFalse(terminal_store.load_options()["auto_resume"])
        self.assertEqual(terminal_store.load_panes(), terminal_store.DEFAULT_PANES)

    def test_chat_keeps_project_root_and_roadmap(self):
        rec = {"kind": "claude", "cwd": "/home/u", "title": "t", "session_id": "s1", "extra_args": [],
               "queue": [], "chat": {"model": None, "effort": None, "ultracode": False, "rights": None,
                                     "root": "/home/u/Work/App", "roadmap": "/home/u/Work/App/ROADMAP.md"}}
        terminal_store.save_tabs([rec], 0)
        tabs, _sel = terminal_store.load_tabs()
        self.assertEqual(tabs[0]["chat"]["root"], "/home/u/Work/App")
        self.assertEqual(tabs[0]["chat"]["roadmap"], "/home/u/Work/App/ROADMAP.md")
        rec["chat"]["root"] = "pas/absolu"                      # chemin relatif : écarté
        terminal_store.save_tabs([rec], 0)
        self.assertNotIn("root", terminal_store.load_tabs()[0][0]["chat"])

    def test_chat_options_round_trip(self):
        chat = {"model": "opus", "effort": "high", "ultracode": True, "rights": "plan"}
        tab = {**CLAUDE, "chat": chat}
        self.assertTrue(terminal_store.save_tabs([tab], 0))
        self.assertEqual(terminal_store.load_tabs(), ([tab], 0))
        self.assertEqual(json.loads(self.path().read_text())["version"], 2)

    def test_odd_chat_values_fall_back(self):
        write(self.path(), {"tabs": [{**CLAUDE, "chat": {"model": 3, "effort": "", "ultracode": "oui",
                                                         "rights": ["x"]}}]})
        self.assertEqual(terminal_store.load_tabs()[0][0]["chat"], terminal_store.DEFAULT_CHAT)

    def test_panes_round_trip_and_defaults(self):
        self.assertEqual(terminal_store.load_panes(),
                         {"A": {"tree": 240, "side": 460}, "B": {"tree": 240, "side": 460},
                          "tree_visible": True, "left": "fichiers"})
        panes = {"A": {"tree": 200, "side": 500}, "B": {"tree": 260, "side": 400},
                 "tree_visible": False, "left": "feuille"}
        self.assertTrue(terminal_store.save_panes(panes))
        self.assertEqual(terminal_store.load_panes(), panes)

    def test_odd_panes_fall_back_and_tabs_are_kept(self):
        terminal_store.save_tabs([CLAUDE], 0)
        write(self.path(), {**json.loads(self.path().read_text()),
                            "panes": {"A": {"tree": -5, "side": "x"}, "B": 3, "tree_visible": 1,
                                      "left": "autre"}})
        self.assertEqual(terminal_store.load_panes(), terminal_store.DEFAULT_PANES)
        terminal_store.save_panes({"left": "feuille"})
        self.assertEqual(terminal_store.load_tabs(), ([CLAUDE], 0))
