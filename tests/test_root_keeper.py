"""Gardien du mot de passe root : effacement, expiration, une seule demande, trois essais, socket
réservé au même uid, mot de passe jamais dans les journaux, `ccs-askpass` et `ccs root`.
Jamais de vrai sudo : la vérification est toujours un faux."""

import asyncio
import io
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from ccs_app import root_keeper as rk

GOOD = "Bon-Mot-De-Passe-42"


class Clock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t


def fake_verify(calls=None):
    def verify(secret):
        if calls is not None:
            calls.append(len(secret))
        return bytes(secret.view()) == GOOD.encode()
    return verify


class SecretTest(unittest.TestCase):
    def test_wipe_zeroes_and_masks(self):
        s = rk.Secret(b"abc")
        buf = s._buf
        self.assertEqual(repr(s), "<Secret masqué>")
        self.assertEqual(str(s), "<Secret masqué>")
        s.wipe()
        self.assertEqual(len(buf), 0)
        self.assertFalse(s)

    def test_wipe_with_view_still_zeroes(self):
        s = rk.Secret(b"abcdef")
        view = s.view()
        s.wipe()                              # vue encore ouverte : remise à zéro sans redimensionner
        self.assertEqual(bytes(view), b"\0" * 6)

    def test_to_secret_refuses_bad_values(self):
        for bad in (None, "", 12, "a\nb", "x" * (rk.MAX_PASSWORD + 1)):
            with self.assertRaises(rk.KeeperError) as cm:
                rk.to_secret(bad)
            self.assertNotIn("a\nb", str(cm.exception))
        self.assertEqual(bytes(rk.to_secret("été").view()), "été".encode())

    def test_not_picklable(self):
        import pickle
        with self.assertRaises(TypeError):
            pickle.dumps(rk.Secret(b"x"))


class KeeperTest(unittest.IsolatedAsyncioTestCase):
    def make(self, **kw):
        self.clock = Clock()
        self.events = []
        k = rk.Keeper(machine="vps", clock=self.clock, verify=kw.pop("verify", fake_verify()), **kw)
        k.listeners.append(lambda ev, data: self.events.append((ev, data)))
        return k

    def names(self):
        return [e for e, _ in self.events]

    async def test_expiration_wipes(self):
        k = self.make()
        k.store(rk.to_secret(GOOD))
        buf = k._secret._buf
        self.clock.t += rk.KEEP_S - 1
        self.assertTrue(k.kept())
        self.assertGreater(k.status()["remaining"], 0)
        self.clock.t += 1                     # expiration absolue : jamais prolongée par l'usage
        self.assertFalse(k.kept())
        self.assertEqual(len(buf), 0)
        self.assertEqual(self.events[-1], ("root.forgotten", {"machine": "vps", "reason": "expired"}))

    async def test_use_does_not_extend(self):
        k = self.make()
        k.store(rk.to_secret(GOOD))
        self.clock.t += 1800
        (await k.ask("ls")).wipe()
        self.clock.t += 1800
        self.assertFalse(k.kept())

    async def test_forget_and_close_wipe(self):
        k = self.make()
        k.store(rk.to_secret(GOOD))
        buf = k._secret._buf
        self.assertTrue(k.forget())
        self.assertEqual(len(buf), 0)
        self.assertFalse(k.forget())
        k.store(rk.to_secret(GOOD))
        buf = k._secret._buf
        k.close()
        self.assertEqual(len(buf), 0)
        self.assertEqual(self.events[-1][1]["reason"], "stop")

    async def test_kept_password_served_and_signalled(self):
        k = self.make()
        k.store(rk.to_secret(GOOD))
        got = await k.ask("apt update")
        self.assertEqual(bytes(got.view()), GOOD.encode())
        self.assertIsNot(got._buf, k._secret._buf)         # une copie, effaçable par l'appelant
        self.assertEqual(self.events, [("root.used", {"machine": "vps", "command": "apt update",
                                                      "at": self.clock.t})])
        self.assertNotIn("root.ask", self.names())

    async def test_single_request_at_a_time(self):
        k = self.make()
        first = asyncio.ensure_future(k.ask("apt update"))
        second = asyncio.ensure_future(k.ask("systemctl restart nginx"))
        await asyncio.sleep(0)
        asks = [d for e, d in self.events if e == "root.ask"]
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0]["command"], "apt update")
        self.assertEqual(asks[0]["machine"], "vps")
        self.assertEqual(k.status()["pending"]["id"], asks[0]["id"])
        self.assertEqual(await k.answer(asks[0]["id"], GOOD), {"ok": True})
        a, b = await first, await second
        self.assertEqual(bytes(a.view()), GOOD.encode())
        self.assertEqual(bytes(b.view()), GOOD.encode())
        self.assertIn(("root.resolved", {"id": asks[0]["id"], "ok": True}), self.events)
        used = [d["command"] for e, d in self.events if e == "root.used"]
        self.assertEqual(used, ["systemctl restart nginx"])    # la commande montrée ne l'est pas deux fois
        self.assertIsNone(k.status()["pending"])
        self.assertTrue(k.status()["kept"])

    async def test_three_tries(self):
        calls = []
        k = self.make(verify=fake_verify(calls))
        task = asyncio.ensure_future(k.ask("reboot"))
        await asyncio.sleep(0)
        rid = self.events[0][1]["id"]
        r1 = await k.answer(rid, "faux-1")
        self.assertFalse(r1["ok"])
        self.assertIn("1 sur 3", r1["error"])
        again = [d for e, d in self.events if e == "root.ask"]
        self.assertEqual(again[-1]["id"], rid)
        self.assertEqual(again[-1]["tries_left"], 2)
        self.assertIn("error", again[-1])
        await k.answer(rid, "faux-2")
        r3 = await k.answer(rid, "faux-3")
        self.assertFalse(r3["ok"])
        self.assertIsNone(await task)
        self.assertEqual(self.events[-1], ("root.resolved", {"id": rid, "ok": False}))
        self.assertEqual(len(calls), 3)
        with self.assertRaises(rk.KeeperError):          # demande close : plus de réponse
            await k.answer(rid, GOOD)
        self.assertFalse(k.kept())

    async def test_cancel(self):
        k = self.make()
        task = asyncio.ensure_future(k.ask("reboot"))
        await asyncio.sleep(0)
        rid = self.events[0][1]["id"]
        self.assertFalse((await k.answer(rid, cancel=True))["ok"])
        self.assertIsNone(await task)

    async def test_unknown_request(self):
        k = self.make()
        with self.assertRaises(rk.KeeperError) as cm:
            await k.answer("inconnu", GOOD)
        self.assertEqual(cm.exception.code, "introuvable")

    async def test_timeout(self):
        k = self.make(ask_timeout=0.05)
        self.assertIsNone(await k.ask("reboot"))
        self.assertEqual(self.events[-1][0], "root.resolved")
        self.assertFalse(self.events[-1][1]["ok"])
        self.assertIsNone(k.status()["pending"])

    async def test_forget_abandons_pending(self):
        k = self.make()
        task = asyncio.ensure_future(k.ask("reboot"))
        await asyncio.sleep(0)
        k.forget()
        self.assertIsNone(await task)

    async def test_password_never_logged_nor_in_events(self):
        k = self.make()
        with self.assertLogs("ccs", level=logging.DEBUG) as logs:
            task = asyncio.ensure_future(k.ask("apt update"))
            await asyncio.sleep(0)
            rid = self.events[0][1]["id"]
            await k.answer(rid, GOOD + "-faux")
            await k.answer(rid, GOOD)
            (await task).wipe()
            (await k.ask("ls")).wipe()
            logging.getLogger("ccs.root").info("fin")
            k.forget()
        text = "\n".join(logs.output)
        self.assertNotIn(GOOD, text)
        self.assertNotIn(GOOD, repr(self.events))
        self.assertNotIn(GOOD, repr(k.status()))


class VerifyTest(unittest.TestCase):
    def test_password_on_stdin_never_in_argv(self):
        seen = {}

        class Proc:
            def __init__(self, argv, **kw):
                seen["argv"], seen["kw"] = argv, kw
                self.stdin = io.BytesIO()
                self.stdin.close = lambda: seen.setdefault("stdin", self.stdin.getvalue())

            def wait(self, timeout=None):
                return 0 if seen["stdin"] == GOOD.encode() + b"\n" else 1

        self.assertTrue(rk.verify_password(rk.to_secret(GOOD), popen=Proc))
        self.assertEqual(seen["argv"][:3], ["sudo", "-k", "-S"])
        self.assertIn("-v", seen["argv"])
        self.assertNotIn(GOOD, " ".join(seen["argv"]))
        self.assertNotIn("SUDO_ASKPASS", seen["kw"]["env"])
        self.assertTrue(seen["kw"]["start_new_session"])
        seen.clear()
        self.assertFalse(rk.verify_password(rk.to_secret("faux"), popen=Proc))

    def test_sudo_missing_or_stuck(self):
        def missing(*_a, **_k):
            raise FileNotFoundError("sudo")
        self.assertFalse(rk.verify_password(rk.to_secret(GOOD), popen=missing))

        class Stuck:
            def __init__(self, *_a, **_k):
                self.stdin = io.BytesIO()
                self.killed = False

            def wait(self, timeout=None):
                if timeout is not None and not self.killed:
                    raise subprocess.TimeoutExpired("sudo", timeout)
                return -9

            def kill(self):
                self.killed = True
        self.assertFalse(rk.verify_password(rk.to_secret(GOOD), popen=Stuck))


class SudoCommandTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(rk.sudo_command(["sudo", "-A", "apt", "install", "x"]), "apt install x")
        self.assertEqual(rk.sudo_command(["/usr/bin/sudo", "-k", "-A", "--", "ls", "-l"]), "ls -l")
        self.assertEqual(rk.sudo_command(["sudo", "-u", "www-data", "-A", "id"]), "id")
        self.assertEqual(rk.sudo_command(["sudo", "-Au", "root", "id"]), "id")
        self.assertEqual(rk.sudo_command(["sudo", "-uroot", "id"]), "id")
        self.assertEqual(rk.sudo_command(["sudo", "--user", "root", "--", "id"]), "id")
        self.assertEqual(rk.sudo_command(["sudo", "-A", "-v"]), "sudo -A -v")
        self.assertIsNone(rk.sudo_command(["bash", "-c", "x"]))

    def test_clean_command(self):
        self.assertEqual(rk.clean_command("  a \n b  "), "a b")
        self.assertEqual(rk.clean_command(""), rk.UNKNOWN_COMMAND)
        self.assertEqual(len(rk.clean_command("x" * 2000)), rk.MAX_COMMAND)


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-root-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.events = []
        self.keeper = rk.Keeper(machine="vps", verify=fake_verify())
        self.keeper.listeners.append(lambda ev, data: self.events.append((ev, data)))

    async def serve(self, **kw):
        server = rk.KeeperServer(self.keeper, **kw)
        await server.start()
        self.addAsyncCleanup(server.close)
        return server

    async def test_paths_and_modes(self):
        server = await self.serve()
        self.assertEqual(server.path, os.path.join(self.tmp, "ccs", "root.sock"))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(server.path)).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(server.path).st_mode), 0o600)
        with self.assertRaises(rk.AlreadyServed):          # un seul gardien par utilisateur
            await rk.KeeperServer(rk.Keeper(machine="x")).start()

    async def test_ask_answer_through_socket(self):
        await self.serve()
        fetch = asyncio.ensure_future(asyncio.to_thread(rk.fetch_password, "apt update", 10))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if self.events:
                break
        rid = self.events[0][1]["id"]
        st = await rk.async_request("status")
        self.assertEqual(st["pending"]["id"], rid)
        res = await rk.async_request("answer", id=rid, password=GOOD)
        self.assertEqual(res, {"ok": True})
        secret = await fetch
        self.assertEqual(bytes(secret.view()), GOOD.encode())
        st = await asyncio.to_thread(rk.request, "status")
        self.assertTrue(st["kept"])
        self.assertNotIn(GOOD, repr(st))
        self.assertEqual(await asyncio.to_thread(rk.request, "forget"), {"ok": True, "had": True})
        self.assertFalse(self.keeper.kept())

    async def test_other_uid_refused(self):
        await self.serve(peer=lambda _sock: os.getuid() + 1)
        self.keeper.store(rk.to_secret(GOOD))
        with self.assertLogs("ccs.root", level=logging.WARNING) as logs:
            got = await asyncio.to_thread(rk.fetch_password, "ls", 5)
        self.assertIsNone(got)
        self.assertIn("refusée", "\n".join(logs.output))
        self.assertNotIn("root.used", [e for e, _ in self.events])

    async def test_watch_streams_events(self):
        await self.serve()
        r, w = await rk.async_open()
        w.write(b'{"op": "watch"}\n')
        await w.drain()
        await asyncio.sleep(0.05)
        self.keeper.store(rk.to_secret(GOOD))
        self.keeper.forget()
        line = await asyncio.wait_for(r.readline(), 2)
        self.assertIn(b"root.forgotten", line)
        w.close()


class AskpassTest(unittest.TestCase):
    def test_writes_password_then_newline(self):
        out = io.BytesIO()
        out.flush = lambda: None
        code = rk.askpass_main(out=out, fetch=lambda _c: rk.to_secret(GOOD), ensure=lambda: True)
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), GOOD.encode() + b"\n")

    def test_failure_writes_nothing(self):
        for fetch in (lambda _c: None,):
            out = io.BytesIO()
            self.assertEqual(rk.askpass_main(out=out, fetch=fetch, ensure=lambda: True), 1)
            self.assertEqual(out.getvalue(), b"")

        def unreachable(_c):
            raise FileNotFoundError("socket")
        out = io.BytesIO()
        self.assertEqual(rk.askpass_main(out=out, fetch=unreachable, ensure=lambda: False), 1)
        self.assertEqual(out.getvalue(), b"")

    def test_launches_bridge_when_missing(self):
        calls = []

        def fetch(_c):
            calls.append("fetch")
            if len(calls) == 1:
                raise ConnectionRefusedError()
            return rk.to_secret(GOOD)
        out = io.BytesIO()
        out.flush = lambda: None
        self.assertEqual(rk.askpass_main(out=out, fetch=fetch, ensure=lambda: calls.append("pont") or True), 0)
        self.assertEqual(calls, ["fetch", "pont", "fetch"])


class CommandTest(unittest.TestCase):
    def test_run_returns_command_code(self):
        seen = {}

        def call(argv, env):
            seen["argv"], seen["env"] = argv, env
            return 7
        with mock.patch.object(rk, "askpass_path", return_value="/usr/bin/ccs-askpass"):
            code = rk.command(["--", "apt", "install", "x y"], ensure=lambda: True, call=call)
        self.assertEqual(code, 7)
        self.assertEqual(seen["argv"], ["sudo", "-k", "-A", "--", "apt", "install", "x y"])
        self.assertEqual(seen["env"]["SUDO_ASKPASS"], "/usr/bin/ccs-askpass")
        self.assertEqual(seen["env"]["CCS_ROOT_COMMAND"], "apt install 'x y'")

    def test_run_without_bridge(self):
        with mock.patch.object(rk, "askpass_path", return_value="/x"), \
                mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(rk.command(["--", "ls"], ensure=lambda: False, call=None), 1)

    def test_status_and_forget(self):
        st = {"machine": "vps", "kept": True, "remaining": 1500, "pending": None}
        with mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(rk.command(["etat"], req=lambda op: st), 0)
            self.assertEqual(rk.command(["oublier"], req=lambda op: {"ok": True, "had": True}), 0)
        text = out.getvalue()
        self.assertIn("gardé en mémoire sur vps : encore 25 min", text)
        self.assertIn("Mot de passe root effacé.", text)

        def down(_op):
            raise FileNotFoundError()
        with mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(rk.command(["état"], req=down), 0)
        self.assertIn("ne tourne pas", out.getvalue())

    def test_unknown_action(self):
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(rk.command(["ls"]), 2)

    def test_cli_delegates(self):
        from ccs_app import cli
        with mock.patch.object(rk, "command", return_value=0) as cmd:
            self.assertEqual(cli.main(["root", "--", "ls", "-l"]), 0)
        cmd.assert_called_once_with(["--", "ls", "-l"])
        self.assertIn("root", cli.command_names())


class AskpassPathTest(unittest.TestCase):
    def test_repo_sibling(self):
        path = rk.askpass_path()
        self.assertTrue(path.endswith("bin/ccs-askpass"))
        self.assertTrue(os.access(path, os.X_OK))


if __name__ == "__main__":
    unittest.main()


class RicochetIdTest(unittest.TestCase):
    def test_local_machine_id(self):
        from ccs_app import root_keeper as rk
        class M:
            def __init__(self, id, local):
                self.id, self.local = id, local
        self.assertEqual(rk.ricochet_id(lambda: [M("pc-bureau", False), M("mawena-cloud", True)]),
                         "mawena-cloud")

    def test_no_ricochet(self):
        from ccs_app import root_keeper as rk
        def boom():
            raise OSError("relais injoignable")
        self.assertIsNone(rk.ricochet_id(boom))
