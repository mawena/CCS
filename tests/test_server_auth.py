"""ccs-auth : mot de passe Ubuntu + groupe + code, inscription du code, sessions, tickets.
Aucun vrai PAM ni systemd : vérification, lancement des ponts et horloge sont injectés."""

import hashlib
import hmac
import logging
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pyotp

from ccs_app.server import auth, paths, rpc, totp
from ccs_app.server.tokens import TokenStore, session_hash

PASSWORDS = {"alice": "mot-de-passe-alice", "bob": "mot-de-passe-bob", "root": "racine"}
ALLOWED = {"alice"}
NOW = 1_700_000_000.0
REFUSED = {"status": "refused", "message": "Identifiant, mot de passe ou code incorrect"}


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


class AuthTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-auth-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"CCS_SERVER_ROOT": self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.clock = Clock()
        self.spawned = []
        self.chowned = []
        self.svc = auth.AuthService(
            TokenStore(paths.sessions_file(), clock=self.clock),
            pam_check=lambda u, p: PASSWORDS.get(u) == p,
            allowed=lambda u: u in ALLOWED,
            spawn_bridge=lambda u: self.spawned.append(u),
            clock=self.clock, refuse_delay=0,
            chown=lambda path, user: self.chowned.append((str(path), user)))

    def code(self, user="alice"):
        return pyotp.TOTP(totp.load(user)).at(self.clock.t)

    async def enrolled(self, user="alice"):
        r = await self.svc.login({"user": user, "password": PASSWORDS[user], "ip": "1.1.1.1"})
        self.assertEqual(r["status"], "enroll")
        code = pyotp.TOTP(r["secret"]).at(self.clock.t)
        r = await self.svc.enroll({"pending": r["pending"], "code": code, "ip": "1.1.1.1"})
        self.assertEqual(r["status"], "ok")
        return r

    async def test_first_login_enrolls_and_saves_secret_only_after_code(self):
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "ip": "1.1.1.1"})
        self.assertEqual(r["status"], "enroll")
        self.assertIn("<svg", r["qr_svg"])
        self.assertIsNone(totp.load("alice"))
        bad = await self.svc.enroll({"pending": r["pending"], "code": "000000", "ip": "1.1.1.1"})
        self.assertEqual(bad, REFUSED)
        self.assertIsNone(totp.load("alice"))
        ok = await self.svc.enroll({"pending": r["pending"], "code": pyotp.TOTP(r["secret"]).at(NOW),
                                    "ip": "1.1.1.1"})
        self.assertEqual(ok["status"], "ok")
        self.assertEqual(totp.load("alice"), r["secret"])
        self.assertEqual(self.spawned, ["alice"])

    async def test_pending_expires(self):
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "ip": "1.1.1.1"})
        self.clock.t += 601
        code = pyotp.TOTP(r["secret"]).at(self.clock.t)
        self.assertEqual(await self.svc.enroll({"pending": r["pending"], "code": code, "ip": "1"}), REFUSED)

    async def test_login_needs_code_then_ok(self):
        await self.enrolled()
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "ip": "1.1.1.1"})
        self.assertEqual(r, {"status": "code"})
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "code": self.code(),
                                  "ip": "1.1.1.1"})
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["user"], "alice")
        self.assertNotIn("device", r)
        self.assertEqual(self.svc.tokens.check_session(r["session"]), "alice")

    async def test_same_answer_for_every_refusal(self):
        await self.enrolled()
        cases = [
            {"user": "alice", "password": "faux", "code": self.code()},
            {"user": "personne", "password": "x", "code": "123456"},
            {"user": "bob", "password": PASSWORDS["bob"], "code": "123456"},       # hors groupe
            {"user": "root", "password": PASSWORDS["root"], "code": "123456"},
            {"user": "alice", "password": PASSWORDS["alice"], "code": "000000"},    # mauvais code
            {"user": "../etc", "password": "x"},
            {"user": "", "password": ""},
        ]
        for i, c in enumerate(cases):
            r = await self.svc.login({**c, "ip": f"10.0.0.{i}"})
            self.assertEqual(r, REFUSED, c["user"])

    async def test_blocked_after_five_failures(self):
        await self.enrolled()
        for i in range(5):
            await self.svc.login({"user": "alice", "password": "faux", "ip": f"10.0.0.{i}"})
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "code": self.code(),
                                  "ip": "10.9.9.9"})
        self.assertEqual(r["status"], "blocked")
        self.assertGreater(r["retry_after"], 0)
        self.clock.t += 901
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "code": self.code(),
                                  "ip": "10.9.9.9"})
        self.assertEqual(r["status"], "ok")

    async def test_ip_blocked_whatever_user(self):
        for i in range(5):
            await self.svc.login({"user": f"u{i}", "password": "x", "ip": "6.6.6.6"})
        await self.enrolled()
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "code": self.code(),
                                  "ip": "6.6.6.6"})
        self.assertEqual(r["status"], "blocked")

    async def test_device_skips_code_not_password(self):
        await self.enrolled()
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "code": self.code(),
                                  "remember": True, "ip": "1.1.1.1"})
        dev = r["device"]
        r = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"], "device": dev,
                                  "ip": "1.1.1.1"})
        self.assertEqual(r["status"], "ok")
        r = await self.svc.login({"user": "alice", "password": "faux", "device": dev, "ip": "1.1.1.1"})
        self.assertEqual(r, REFUSED)

    async def test_ticket_matches_bridge_key(self):
        r = await self.enrolled()
        key = paths.bridge_key("alice").read_bytes()
        self.assertEqual(len(key), 32)
        self.assertEqual(oct(paths.bridge_key("alice").stat().st_mode & 0o777), "0o600")
        self.assertIn((str(paths.bridge_key("alice")), "alice"), self.chowned)
        expected = hmac.new(key, session_hash(r["session"]).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(r["ticket"], expected)
        chk = await self.svc.check({"session": r["session"]})
        self.assertEqual(chk, {"user": "alice", "ticket": expected})

    async def test_planted_symlink_never_followed(self):
        """Le dossier du pont appartient à l'utilisateur : un lien posé à la place de la clé ne
        doit jamais faire écrire, changer les droits ou le propriétaire de sa cible."""
        r = await self.enrolled()
        victim = Path(self.tmp) / "fichier-de-root"
        victim.write_text("secret de root")
        os.chmod(victim, 0o640)
        key = paths.bridge_key("alice")
        good = key.read_bytes()
        key.unlink()
        os.symlink(victim, key)
        self.chowned.clear()
        chk = await self.svc.check({"session": r["session"]})
        self.assertEqual(victim.read_text(), "secret de root")
        self.assertEqual(oct(victim.stat().st_mode & 0o777), "0o640")
        self.assertNotIn(str(victim), [c[0] for c in self.chowned])
        self.assertFalse(key.is_symlink())
        self.assertEqual(key.read_bytes(), good)                 # la clé de référence n'a pas changé
        expected = hmac.new(good, session_hash(r["session"]).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(chk["ticket"], expected)

    async def test_pam_called_even_for_refused_accounts(self):
        seen = []
        self.svc.pam_check = lambda u, p: (seen.append(u), PASSWORDS.get(u) == p)[1]
        for user in ("personne", "bob", "root"):
            await self.svc.login({"user": user, "password": "x", "ip": "1"})
        self.assertEqual(seen, ["personne", "bob", "root"])     # même durée : pas d'indice

    async def test_check_restarts_missing_bridge(self):
        r = await self.enrolled()
        self.spawned.clear()
        await self.svc.check({"session": r["session"]})
        self.assertEqual(self.spawned, ["alice"])          # pas de socket : relancé
        paths.bridge_socket("alice").parent.mkdir(parents=True, exist_ok=True)
        paths.bridge_socket("alice").touch()
        await self.svc.check({"session": r["session"]})
        self.assertEqual(self.spawned, ["alice"])

    async def test_logout_ends_session(self):
        r = await self.enrolled()
        await self.svc.logout({"session": r["session"]})
        with self.assertRaises(rpc.RpcError) as cm:
            await self.svc.check({"session": r["session"]})
        self.assertEqual(cm.exception.code, "refuse")

    async def test_app_token_flow(self):
        r = await self.enrolled()
        app = (await self.svc.app_token({"session": r["session"], "name": "PC du bureau"}))["token"]
        chk = await self.svc.check_app({"token": app})
        self.assertEqual(chk["user"], "alice")
        items = (await self.svc.tokens_list({"session": r["session"]}))["tokens"]
        tid = next(t["id"] for t in items if t["kind"] == "app")
        self.assertEqual(await self.svc.revoke({"session": r["session"], "token_id": tid}), {"revoked": True})
        with self.assertRaises(rpc.RpcError):
            await self.svc.check_app({"token": app})

    async def test_pair_gives_app_token(self):
        await self.enrolled()
        r = await self.svc.pair({"user": "alice", "password": PASSWORDS["alice"], "code": self.code(),
                                 "name": "ccs tui", "ip": "1.1.1.1"})
        self.assertEqual(r["status"], "ok")
        self.assertEqual((await self.svc.check_app({"token": r["token"]}))["user"], "alice")
        self.assertNotIn("session", r)
        bad = await self.svc.pair({"user": "alice", "password": "faux", "code": self.code(), "name": "x",
                                   "ip": "1.1.1.2"})
        self.assertEqual(bad, REFUSED)

    async def test_pair_enroll_gives_app_token(self):
        r = await self.svc.pair({"user": "alice", "password": PASSWORDS["alice"], "name": "PC", "ip": "1"})
        self.assertEqual(r["status"], "enroll")
        ok = await self.svc.enroll({"pending": r["pending"], "code": pyotp.TOTP(r["secret"]).at(NOW),
                                    "ip": "1"})
        self.assertIn("token", ok)
        self.assertNotIn("session", ok)

    async def test_no_secret_in_logs(self):
        with self.assertLogs("ccs.auth", logging.DEBUG) as logs:
            r = await self.enrolled()
            await self.svc.login({"user": "alice", "password": "faux", "ip": "1.1.1.1"})
            ok = await self.svc.login({"user": "alice", "password": PASSWORDS["alice"],
                                       "code": self.code(), "remember": True, "ip": "1.1.1.1"})
        text = "\n".join(logs.output)
        for secret in (PASSWORDS["alice"], "faux", r["session"], ok["session"], ok["device"], ok["ticket"],
                       totp.load("alice"), self.code()):
            self.assertNotIn(secret, text)
        self.assertIn("alice", text)

    async def test_refuse_delay_applies(self):
        slept = []

        async def sleep(s):
            slept.append(s)
        self.svc.refuse_delay = 1.0
        self.svc.sleep = sleep
        await self.svc.login({"user": "alice", "password": "faux", "ip": "1"})
        self.assertTrue(slept and 0 < slept[0] <= 1.0)

    async def test_handlers_over_socket(self):
        server = rpc.RpcServer(self.svc.handlers())
        sock = Path(self.tmp) / "auth.sock"
        await server.start_unix(sock, 0o600)
        self.addAsyncCleanup(server.close)
        c = rpc.RpcClient()
        await c.connect_unix(sock)
        self.addAsyncCleanup(c.close)
        r = await c.call("login", user="alice", password=PASSWORDS["alice"], ip="1")
        self.assertEqual(r["status"], "enroll")


class ResetTest(unittest.TestCase):
    def test_cli_reset_requires_root(self):
        from ccs_app import cli
        with mock.patch("os.geteuid", return_value=1000):
            self.assertNotEqual(cli.main(["totp", "reinitialiser", "alice"]), 0)


if __name__ == "__main__":
    unittest.main()
