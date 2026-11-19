"""Relais d'une connexion du pont vers le pont CCS d'une autre machine.

Le programme distant (`REMOTE`) tourne pour de vrai, en local, à la place de `ssh` ; le pont de
« l'autre machine » est un vrai pont local dans un dossier temporaire."""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import distant
from ccs_app.server import bridge, bridge_machines, rpc
from tests.helpers import make_home
from tests.test_server_bridge import KEY, ticket


def machine(mid, online=True, host="ailleurs", ports=(22,)):
    return distant.Machine(id=mid, name=mid.upper(), online=online, host=host, ports=list(ports),
                           cores=8, load=1.0)


class MachinesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccs-mach-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(str(self.tmp))
        env = mock.patch.dict(os.environ, {"HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        conf = mock.patch.object(distant, "configured", return_value=True)
        conf.start()
        self.addCleanup(conf.stop)
        # pont de « l'autre machine » : un pont local, dans son XDG_RUNTIME_DIR
        self.runtime = self.tmp / "run"
        (self.runtime / "ccs").mkdir(parents=True)
        self.far = bridge.Bridge("bob", None, local=True, start_daemon=False, install_claude=False)
        self.far.add_handlers({"echo": self._echo, "machines.list": self._far_list})
        await self.far.start(self.runtime / "ccs" / "bridge.sock")
        self.addAsyncCleanup(self.far.stop)
        # pont du serveur, avec l'API des machines
        self.machines = [machine("pc"), machine("vps", host=os.uname().nodename),
                         machine("eteint", online=False)]
        self.spawned = []
        self.near = bridge.Bridge("alice", KEY, start_daemon=False, install_claude=False)
        self.api = bridge_machines.MachinesApi(self.near, fetch=lambda: self.machines,
                                               spawn=self._spawn)
        self.sock = self.tmp / "near.sock"
        await self.near.start(self.sock)
        self.addAsyncCleanup(self.near.stop)

    async def _echo(self, conn, params):
        if params.get("push"):
            await conn.push("chat.event", {"from": "far"})
        return {"user": "bob", "params": params}

    async def _far_list(self, _conn, _params):
        return {"machines": ["ne doit pas servir"]}

    async def _spawn(self, m, script=None):
        env = dict(os.environ, XDG_RUNTIME_DIR=str(self.runtime))
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script or bridge_machines.REMOTE, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=rpc.MAX_LINE + 1)
        self.spawned.append(proc)
        return proc

    async def client(self):
        c = rpc.RpcClient()
        await c.connect_unix(self.sock)
        self.addAsyncCleanup(c.close)
        t, h = ticket()
        await c.call("hello", ticket=t, session_hash=h)
        return c

    async def test_list_shows_the_machines(self):
        c = await self.client()
        r = await c.call("machines.list")
        ids = {m["id"]: m for m in r["machines"]}
        self.assertEqual(set(ids), {"pc", "vps", "eteint"})
        self.assertTrue(ids["vps"]["local"])
        self.assertFalse(ids["eteint"]["online"])
        self.assertEqual(ids["pc"]["name"], "PC")

    async def test_list_adds_known_tools(self):
        distant._save_inventory({"pc": {"path": "/usr/bin", "outils": {"flutter": "/f", "go": ""},
                                        "quand": 123}})
        c = await self.client()
        ids = {m["id"]: m for m in (await c.call("machines.list"))["machines"]}
        self.assertEqual(ids["pc"]["tools"], ["flutter"])
        self.assertEqual(ids["pc"]["tools_at"], 123)
        self.assertEqual(ids["eteint"]["tools"], [])

    async def test_tools_probes_the_machine(self):
        seen = []

        def probe(m, overrides, refresh=False):
            seen.append((m.id, refresh))
            return {"path": "/usr/bin", "outils": {"cargo": "/c", "node": ""}, "quand": 9}
        c = await self.client()
        with mock.patch.object(distant, "inventory", probe):
            r = await c.call("machines.tools", machine="pc")
            self.assertEqual(r, {"tools": ["cargo"], "tools_at": 9})
            self.assertEqual(seen, [("pc", True)])
            for bad in ("eteint", "inconnue", "../x"):
                with self.assertRaises(rpc.RpcError):
                    await c.call("machines.tools", machine=bad)

    async def test_running_and_stop(self):
        records = [{"pid": 4242, "machine": "pc", "commande": "flutter build apk", "debut": 1}]
        killed = []
        c = await self.client()
        with mock.patch.object(distant, "running", lambda alive=None: records), \
                mock.patch.object(distant.os, "kill", lambda pid, sig: killed.append((pid, sig))):
            self.assertEqual((await c.call("machines.running"))["running"], records)
            self.assertEqual(await c.call("machines.stop", pid=4242), {"ok": True})
            self.assertEqual(killed, [(4242, distant.signal.SIGTERM)])
            for bad in (4243, "4242", True, 1):
                with self.assertRaises(rpc.RpcError):
                    await c.call("machines.stop", pid=bad)
        self.assertEqual(len(killed), 1)

    async def test_settings_never_return_the_token(self):
        c = await self.client()
        r = await c.call("machines.configure", relais="https://relais.test/", jeton="secret")
        self.assertEqual(r["settings"]["relais"], "https://relais.test")
        self.assertIs(r["settings"]["jeton"], True)
        self.assertNotIn("secret", str(await c.call("machines.settings")))
        for bad in ({"relais": "ftp://x"}, {"relais": 3}, {"relais": "https://x", "jeton": 5}):
            with self.assertRaises(rpc.RpcError):
                await c.call("machines.configure", **bad)

    async def test_list_without_ricochet_says_why(self):
        with mock.patch.object(distant, "configured", return_value=False):
            c = await self.client()
            r = await c.call("machines.list")
        self.assertEqual(r["machines"], [])
        self.assertIn("Calcul réparti", r["message"])

    async def test_attach_relays_calls_and_events(self):
        c = await self.client()
        events = []
        c.on_event = lambda n, d: events.append((n, d))
        r = await c.call("machine.attach", machine="pc")
        self.assertEqual(r, {"machine": "pc", "name": "PC"})
        r = await c.call("echo", a=1, push=True)
        self.assertEqual(r, {"user": "bob", "params": {"a": 1, "push": True}})
        for _ in range(100):
            if events:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(events, [("chat.event", {"from": "far"})])
        # la liste des machines reste celle du serveur, pas celle de l'autre machine
        r = await c.call("machines.list")
        self.assertIn("pc", {m["id"] for m in r["machines"]})
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("machine.attach", machine="pc")
        self.assertEqual(e.exception.code, "conflit")

    async def test_large_reply_goes_through(self):
        c = await self.client()
        await c.call("machine.attach", machine="pc")
        big = "x" * 500_000
        r = await c.call("echo", big=big)
        self.assertEqual(len(r["params"]["big"]), 500_000)

    async def test_closing_the_connection_ends_ssh(self):
        c = await self.client()
        await c.call("machine.attach", machine="pc")
        await c.close()
        proc = self.spawned[0]
        await asyncio.wait_for(proc.wait(), 10)
        self.assertEqual(self.api.links, {})

    async def test_far_side_dropping_closes_the_connection(self):
        c = await self.client()
        await c.call("machine.attach", machine="pc")
        self.spawned[0].kill()
        await asyncio.wait_for(c.wait_closed(), 10)

    async def test_refusals(self):
        c = await self.client()
        for mid, word in (("inconnue", "inconnue"), ("vps", "ce serveur"), ("eteint", "hors ligne"),
                          ("../x", "invalide")):
            with self.assertRaises(rpc.RpcError) as e:
                await c.call("machine.attach", machine=mid)
            self.assertIn(word, e.exception.message.lower())
        self.assertEqual(self.spawned, [])

    async def test_unreachable_far_bridge_gives_the_reason(self):
        self.api._spawn = lambda m: self._spawn(m, "import sys; sys.exit('ssh: connexion refusée')")
        c = await self.client()
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("machine.attach", machine="pc")
        self.assertIn("connexion refusée", e.exception.message)
        self.assertEqual(self.api.links, {})

    async def test_attach_needs_hello(self):
        c = rpc.RpcClient()
        await c.connect_unix(self.sock)
        self.addAsyncCleanup(c.close)
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("machine.attach", machine="pc")
        self.assertEqual(e.exception.code, "refuse")

    def test_remote_command_is_quoted_python(self):
        cmd = bridge_machines.remote_command()
        self.assertTrue(cmd.startswith("exec python3 -c '"))
        compile(bridge_machines.REMOTE, "remote", "exec")


if __name__ == "__main__":
    unittest.main()
