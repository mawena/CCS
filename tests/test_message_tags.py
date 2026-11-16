"""Étiquettes sur les messages : nettoyage, stockage par conversation, regroupement."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from ccs_app import message_tags as mt


class MessageTagsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-tags-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"CCS_HOME": self.tmp})
        env.start()
        self.addCleanup(env.stop)

    def test_clean_and_parse(self):
        self.assertEqual(mt.parse(" important ,  à   revoir,, Important "), ["important", "à revoir"])
        self.assertEqual(mt.clean_tag("x" * 100), "x" * mt.MAX_TAG_CHARS)
        self.assertEqual(len(mt.clean_tags([f"t{i}" for i in range(30)])), mt.MAX_TAGS)
        self.assertEqual(mt.clean_tags("pas une liste"), [])
        self.assertEqual(mt.parse(None), [])

    def test_set_load_and_remove(self):
        self.assertEqual(mt.load("s1"), {})
        e = mt.set_tags("s1", "msg_1", ["important"], "Bonjour\n\nle monde", "assistant", clock=lambda: 5)
        self.assertEqual(e, {"tags": ["important"], "role": "assistant", "excerpt": "Bonjour le monde", "ts": 5.0})
        # nouvelles étiquettes sans texte : l'extrait, le rôle et l'heure restent
        e = mt.set_tags("s1", "msg_1", ["important", "à revoir"], clock=lambda: 9)
        self.assertEqual((e["excerpt"], e["role"], e["ts"]), ("Bonjour le monde", "assistant", 5.0))
        self.assertEqual(mt.load("s1")["msg_1"]["tags"], ["important", "à revoir"])
        self.assertIsNone(mt.set_tags("s1", "msg_1", []))
        self.assertEqual(mt.load("s1"), {})
        self.assertFalse(mt.path_of("s1").exists())

    def test_long_excerpt_is_shortened(self):
        e = mt.set_tags("s1", "u-1", ["x"], "mot " * 200, "utilisateur")
        self.assertLessEqual(len(e["excerpt"]), mt.EXCERPT_CHARS)
        self.assertTrue(e["excerpt"].endswith("…"))

    def test_invalid_ids_and_unreadable_file(self):
        with self.assertRaises(ValueError):
            mt.set_tags("../x", "m", ["a"])
        with self.assertRaises(ValueError):
            mt.set_tags("s1", "a/b", ["a"])
        mt.path_of("s2").parent.mkdir(parents=True, exist_ok=True)
        mt.path_of("s2").write_text("{pas du json")
        self.assertEqual(mt.load("s2"), {})
        mt.path_of("s2").write_text('{"messages": {"m": {"tags": []}, "../x": {"tags": ["a"]}, "ok": {"tags": ["a"], "role": "?"}}}')
        self.assertEqual(list(mt.load("s2")), ["ok"])
        self.assertEqual(mt.load("s2")["ok"]["role"], "")

    def test_by_tag_and_known(self):
        mt.set_tags("s1", "a", ["zèbre", "important"], "A", clock=lambda: 1)
        mt.set_tags("s1", "b", ["Important"], "B", clock=lambda: 2)
        mt.set_tags("s2", "c", ["important"], "C")
        groups = mt.by_tag(mt.load("s1"))
        self.assertEqual([(t, [m for m, _ in ms]) for t, ms in groups],
                         [("important", ["a", "b"]), ("zèbre", ["a"])])
        self.assertEqual(mt.known_tags(), ["important", "zèbre"])


if __name__ == "__main__":
    unittest.main()
