"""Serveurs CCS connus du bureau et de ccs tui : appairage, fichier 0600, jamais de mot de passe."""

import json
import os
import stat

from ccs_app.remote import servers
from tests.helpers import HomeTestCase


class ServersTest(HomeTestCase):
    def test_servers_file_mode(self):
        servers.save([servers.Server("vps", "https://ccs.mawena.cloud", "alice", "APP-1")])
        p = servers.path()
        self.assertEqual(p, self.store / "serveurs.json")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(servers.load()[0].url, "https://ccs.mawena.cloud")

    def test_add_replaces_and_remove(self):
        servers.add(servers.Server("vps", "https://a", "alice", "T1"))
        servers.add(servers.Server("vps", "https://b", "alice", "T2"))
        self.assertEqual([(s.name, s.url) for s in servers.load()], [("vps", "https://b")])
        self.assertTrue(servers.remove("vps"))
        self.assertFalse(servers.remove("vps"))

    def test_corrupt_file_is_empty(self):
        servers.path().parent.mkdir(parents=True, exist_ok=True)
        servers.path().write_text("{pas du json")
        self.assertEqual(servers.load(), [])

    def test_pair_saves_token_not_password(self):
        sent = []

        def post(url, body):
            sent.append((url, body))
            return {"status": "ok", "user": "alice", "token": "APP-1"}
        r = servers.pair("https://ccs.mawena.cloud/", "alice", "secret-mdp", "123456", "PC du bureau", post=post)
        self.assertIsInstance(r, servers.Server)
        self.assertEqual(sent[0][0], "https://ccs.mawena.cloud/api/pair")
        self.assertEqual(sent[0][1]["name"], "PC du bureau")
        text = servers.path().read_text()
        self.assertIn("APP-1", text)
        self.assertNotIn("secret-mdp", text)
        self.assertEqual(servers.load()[0].name, "ccs.mawena.cloud")

    def test_pair_enroll_then_finish(self):
        def post(url, body):
            if url.endswith("/api/pair"):
                return {"status": "enroll", "pending": "P", "secret": "S", "qr_svg": "<svg/>"}
            self.assertEqual(body, {"pending": "P", "code": "654321"})
            return {"status": "ok", "user": "alice", "token": "APP-2"}
        r = servers.pair("https://h", "alice", "pw", "", "PC", post=post)
        self.assertEqual(r["status"], "enroll")
        s = servers.finish_enroll("https://h", "alice", "P", "654321", "PC", post=post)
        self.assertEqual(s.token, "APP-2")

    def test_pair_refused_saves_nothing(self):
        r = servers.pair("https://h", "alice", "pw", "1", "PC",
                         post=lambda u, b: {"status": "refused", "message": "non"})
        self.assertEqual(r["status"], "refused")
        self.assertEqual(servers.load(), [])

    def test_https_required_except_localhost(self):
        with self.assertRaises(ValueError):
            servers.normalize_url("http://ccs.mawena.cloud")
        self.assertEqual(servers.normalize_url("ccs.mawena.cloud"), "https://ccs.mawena.cloud")
        self.assertEqual(servers.normalize_url("http://127.0.0.1:8421/"), "http://127.0.0.1:8421")


class CliTest(HomeTestCase):
    def test_cli_add_list_remove(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        from ccs_app import cli
        answers = iter(["alice", "123456"])

        def post(url, body):
            if not body.get("code"):
                return {"status": "code"}
            return {"status": "ok", "user": "alice", "token": "APP-9"}
        with mock.patch("builtins.input", lambda *_: next(answers)), \
                mock.patch("getpass.getpass", lambda *_: "mdp"), \
                mock.patch.object(servers, "_post", post), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["serveur", "ajouter", "ccs.mawena.cloud", "--nom", "PC"]), 0)
        self.assertIn("appairé", out.getvalue())
        self.assertEqual(servers.load()[0].token, "APP-9")
        with redirect_stdout(io.StringIO()) as out:
            cli.main(["serveur", "liste"])
        self.assertIn("ccs.mawena.cloud", out.getvalue())
        self.assertNotIn("APP-9", out.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["serveur", "retirer", "ccs.mawena.cloud"]), 0)
        self.assertEqual(servers.load(), [])
