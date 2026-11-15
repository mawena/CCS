"""Messages enregistrés : communs (dossier de CCS) ou par projet (.ccs/messages.json)."""

import json
import unittest
from pathlib import Path

from ccs_app import saved_messages as sm
from ccs_app.saved_messages import Saved
from tests.helpers import HomeTestCase


class SavedMessagesTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.proj = Path(self.tmp) / "projet"
        self.proj.mkdir()

    def test_project_overrides_global(self):
        sm.save("global", [Saved("revue", "revue globale", "global"),
                           Saved("merci", "Merci !", "global")])
        sm.save("projet", [Saved("revue", "revue du projet", "projet")], str(self.proj))
        got = {s.name: s for s in sm.load(str(self.proj))}
        self.assertEqual(sorted(got), ["merci", "revue"])
        self.assertEqual((got["revue"].text, got["revue"].scope), ("revue du projet", "projet"))
        self.assertEqual(got["merci"].scope, "global")
        self.assertEqual([s.name for s in sm.load(None)], ["revue", "merci"])   # sans projet

    def test_bad_json_is_empty(self):
        sm.save("global", [Saved("a", "A", "global")])
        sm.global_path().write_text("{pas du json")
        self.assertEqual(sm.load(str(self.proj)), [])
        (self.proj / ".ccs").mkdir()
        (self.proj / ".ccs" / "messages.json").write_text(json.dumps({"pas": "une liste"}))
        self.assertEqual(sm.load(str(self.proj)), [])
        (self.proj / ".ccs" / "messages.json").write_text(json.dumps(
            [{"name": "ok", "text": "oui"}, {"name": 3}, "x", {"name": "", "text": "vide"}]))
        self.assertEqual([s.name for s in sm.load(str(self.proj))], ["ok"])

    def test_save_creates_dir(self):
        self.assertFalse((self.proj / ".ccs").exists())
        sm.save("projet", [Saved("x", "texte", "projet")], str(self.proj))
        data = json.loads((self.proj / ".ccs" / "messages.json").read_text())
        self.assertEqual(data, [{"name": "x", "text": "texte"}])
        self.assertEqual([p.name for p in (self.proj / ".ccs").iterdir()], ["messages.json"])


if __name__ == "__main__":
    unittest.main()
