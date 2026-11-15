"""Sessions, appareils retenus et jetons d'application : seules les empreintes sont gardées."""

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from ccs_app.server import tokens
from ccs_app.server.tokens import TokenStore


class Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class TokensTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-tok-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = Path(self.tmp) / "var" / "sessions.json"
        self.clock = Clock()
        self.store = TokenStore(self.path, clock=self.clock)

    def test_session_idle_expiry(self):
        tok = self.store.new_session("alice")
        self.clock.t += tokens.IDLE - 10
        self.assertEqual(self.store.check_session(tok), "alice")      # prolonge l'activité
        self.clock.t += tokens.IDLE - 10
        self.assertEqual(self.store.check_session(tok), "alice")
        self.clock.t += tokens.IDLE + 1
        self.assertIsNone(self.store.check_session(tok))
        self.assertIsNone(self.store.check_session(tok))

    def test_session_max_age(self):
        tok = self.store.new_session("alice")
        for _ in range(20):
            self.clock.t += tokens.IDLE - 60
            self.store.check_session(tok)
        self.assertGreater(self.clock.t - 1_700_000_000.0, tokens.MAX_AGE)
        self.assertIsNone(self.store.check_session(tok))

    def test_end_session(self):
        tok = self.store.new_session("alice")
        self.store.end_session(tok)
        self.assertIsNone(self.store.check_session(tok))
        self.store.end_session("inconnu")

    def test_only_hashes_on_disk(self):
        toks = [self.store.new_session("alice"), self.store.new_device("alice"),
                self.store.new_app("alice", "PC du bureau")]
        text = self.path.read_text()
        for t in toks:
            self.assertGreaterEqual(len(t), 40)
            self.assertNotIn(t, text)
        self.assertIn(tokens.session_hash(toks[0]), text)

    def test_survives_reload(self):
        tok = self.store.new_session("alice")
        other = TokenStore(self.path, clock=self.clock)
        self.assertEqual(other.check_session(tok), "alice")

    def test_device_scoped_to_user(self):
        dev = self.store.new_device("alice")
        self.assertTrue(self.store.check_device(dev, "alice"))
        self.assertFalse(self.store.check_device(dev, "bob"))
        self.assertFalse(self.store.check_device("faux", "alice"))
        self.clock.t += tokens.DEVICE_AGE + 1
        self.assertFalse(self.store.check_device(dev, "alice"))

    def test_app_token_revoke(self):
        app = self.store.new_app("alice", "PC du bureau")
        self.assertEqual(self.store.check_app(app), "alice")
        self.clock.t += 365 * 86400
        self.assertEqual(self.store.check_app(app), "alice")          # pas d'expiration
        tid = next(t["id"] for t in self.store.list_tokens("alice") if t["kind"] == "app")
        self.assertFalse(self.store.revoke("bob", tid))
        self.assertTrue(self.store.revoke("alice", tid))
        self.assertIsNone(self.store.check_app(app))

    def test_kinds_do_not_mix(self):
        s = self.store.new_session("alice")
        a = self.store.new_app("alice", "x")
        self.assertIsNone(self.store.check_app(s))
        self.assertIsNone(self.store.check_session(a))
        self.assertFalse(self.store.check_device(s, "alice"))

    def test_list_never_shows_token(self):
        app = self.store.new_app("alice", "PC du bureau")
        self.store.new_session("alice")
        self.store.new_session("bob")
        items = self.store.list_tokens("alice")
        self.assertEqual(sorted(i["kind"] for i in items), ["app", "session"])
        for i in items:
            self.assertEqual(set(i), {"id", "kind", "name", "created", "last_used"})
            self.assertNotIn(app, str(i))
            self.assertEqual(len(i["id"]), 12)

    def test_file_mode_0600(self):
        self.store.new_session("alice")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_corrupt_file_is_empty_store(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{pas du json")
        store = TokenStore(self.path, clock=self.clock)
        self.assertIsNone(store.check_session("x"))
        tok = store.new_session("alice")
        self.assertEqual(store.check_session(tok), "alice")


if __name__ == "__main__":
    unittest.main()
