"""Synchro des comptes Claude entre machines : l'agent réel sur deux HOME temporaires."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from ccs_app import account_sync


def _profile(home, name, uuid, expires, active=False):
    d = Path(home) / ".claude-accounts" / name
    d.mkdir(parents=True, exist_ok=True)
    acc = {"accountUuid": uuid, "organizationUuid": "org", "emailAddress": f"{name}@x"}
    (d / "account.json").write_text(json.dumps(acc))
    oauth = {"claudeAiOauth": {"accessToken": f"a-{name}-{expires}", "refreshToken": "r", "expiresAt": expires}}
    (d / "oauth.json").write_text(json.dumps(oauth))
    if active:
        cfg = Path(home) / ".claude"
        cfg.mkdir(exist_ok=True)
        (cfg / ".credentials.json").write_text(json.dumps(oauth))
        (Path(home) / ".claude.json").write_text(json.dumps({"oauthAccount": acc}))


def _runner(home):
    env = {k: v for k, v in os.environ.items() if k not in ("CCS_HOME", "CLAUDE_CONFIG_DIR")}
    env["HOME"] = str(home)

    def run(action, data=None, timeout=30):
        return subprocess.run(["python3", "-c", account_sync.AGENT, action], input=data,
                              capture_output=True, text=True, timeout=timeout, env=env)
    return run


def _expires(home, name):
    f = Path(home) / ".claude-accounts" / name / "oauth.json"
    return json.loads(f.read_text())["claudeAiOauth"]["expiresAt"]


class AccountSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Path(self.tmp.name) / "a"
        self.b = Path(self.tmp.name) / "b"
        self.a.mkdir()
        self.b.mkdir()
        self.calls = lambda only=None: ({"a": _runner(self.a), "b": _runner(self.b)}, [])

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_profile_and_fresher_token_cross_over(self):
        _profile(self.a, "un", "u1", 100, active=True)
        _profile(self.b, "un", "u1", 200)
        _profile(self.b, "deux", "u2", 50, active=True)
        res = account_sync.sync(runners_fn=self.calls)
        self.assertEqual(res["machines"], ["a", "b"])
        self.assertEqual(_expires(self.a, "un"), 200)          # jeton plus récent reçu
        self.assertEqual(_expires(self.a, "deux"), 50)         # nouveau profil reçu
        creds = json.loads((self.a / ".claude" / ".credentials.json").read_text())
        self.assertEqual(creds["claudeAiOauth"]["expiresAt"], 200)   # actif mis à jour
        again = account_sync.sync(runners_fn=self.calls)
        self.assertFalse(any(again["recu"].values()))

    def test_same_name_other_account_is_not_overwritten(self):
        _profile(self.a, "un", "u1", 100)
        _profile(self.b, "un", "autre", 900)
        account_sync.sync(runners_fn=self.calls)
        self.assertEqual(_expires(self.a, "un"), 100)
        self.assertEqual(_expires(self.b, "un"), 900)

    def test_removal_spreads_but_never_the_active_one(self):
        _profile(self.a, "un", "u1", 100)
        _profile(self.a, "deux", "u2", 100, active=True)
        _profile(self.b, "un", "u1", 100)
        _profile(self.b, "deux", "u2", 100)
        tombs = {"un": {"key": "u1|org", "at": time.time() + 5},
                 "deux": {"key": "u2|org", "at": time.time() + 5}}
        (self.b / ".claude-accounts" / ".supprimes.json").write_text(json.dumps(tombs))
        res = account_sync.sync(runners_fn=self.calls)
        self.assertFalse((self.a / ".claude-accounts" / "un").exists())
        self.assertFalse((self.b / ".claude-accounts" / "un").exists())
        self.assertTrue((self.a / ".claude-accounts" / "deux").exists())   # actif : gardé
        self.assertIn("-un", res["recu"]["a"])

    def test_readded_after_removal_comes_back(self):
        _profile(self.a, "un", "u1", 100)
        tombs = {"un": {"key": "u1|org", "at": time.time() - 3600}}
        (self.b / ".claude-accounts").mkdir(parents=True)
        (self.b / ".claude-accounts" / ".supprimes.json").write_text(json.dumps(tombs))
        account_sync.sync(runners_fn=self.calls)
        self.assertEqual(_expires(self.b, "un"), 100)

    def test_unreachable_machine_is_skipped(self):
        def broken(action, data=None, timeout=30):
            raise subprocess.TimeoutExpired("ssh", timeout)
        _profile(self.a, "un", "u1", 100)
        res = account_sync.sync(runners_fn=lambda only=None: ({"a": _runner(self.a), "x": broken}, []))
        self.assertEqual(res["machines"], ["a"])
        self.assertEqual(res["absentes"][0][0], "x")
        self.assertTrue(account_sync.describe(res))


if __name__ == "__main__":
    unittest.main()
