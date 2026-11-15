"""Pont : terminaux shell (pseudo-terminal), flux par événements."""

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app.server import bridge, bridge_term, rpc


class TermBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-bterm-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"HOME": self.tmp, "PS1": "$ ", "SHELL": "/bin/sh"})
        env.start()
        self.addCleanup(env.stop)
        sock = Path(self.tmp) / "b.sock"
        self.clock = [1_700_000_000.0]
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        self.hub = bridge_term.TermHub(self.bridge, shell="/bin/sh", clock=lambda: self.clock[0])
        await self.bridge.start(sock)
        self.addAsyncCleanup(self.bridge.stop)
        self.addAsyncCleanup(self.hub.close_all)
        self.c = rpc.RpcClient()
        self.out = []
        self.c.on_event = lambda name, data: self.out.append((name, data))
        await self.c.connect_unix(sock)
        self.addAsyncCleanup(self.c.close)
        await self.c.call("hello")

    def text(self, tid):
        return "".join(d["data"] for n, d in self.out if n == "term.output" and d["term_id"] == tid)

    async def wait(self, pred, timeout=10):
        for _ in range(int(timeout * 50)):
            if pred():
                return True
            await asyncio.sleep(0.02)
        return pred()

    async def test_echo_round_trip(self):
        tid = (await self.c.call("term.open", cwd=self.tmp, cols=80, rows=24))["term_id"]
        await self.c.call("term.input", term_id=tid, data="printf 'b%sjour\\n' on\n")
        self.assertTrue(await self.wait(lambda: "bonjour" in self.text(tid)), self.text(tid))
        await self.c.call("term.input", term_id=tid, data="pwd\n")
        self.assertTrue(await self.wait(lambda: self.tmp in self.text(tid)))

    async def test_open_expands_home(self):
        tid = (await self.c.call("term.open", cwd="~", cols=80, rows=24))["term_id"]
        await self.c.call("term.input", term_id=tid, data="pwd\n")
        self.assertTrue(await self.wait(lambda: self.tmp in self.text(tid)), self.text(tid))

    async def test_resize(self):
        tid = (await self.c.call("term.open", cwd=self.tmp, cols=80, rows=24))["term_id"]
        await self.c.call("term.resize", term_id=tid, cols=100, rows=40)
        await self.c.call("term.input", term_id=tid, data="stty size\n")
        self.assertTrue(await self.wait(lambda: "40 100" in self.text(tid)), self.text(tid))

    async def test_exit_event(self):
        tid = (await self.c.call("term.open", cwd=self.tmp, cols=80, rows=24))["term_id"]
        await self.c.call("term.input", term_id=tid, data="exit 3\n")
        self.assertTrue(await self.wait(lambda: any(n == "term.exit" for n, _ in self.out)))
        exit_ev = next(d for n, d in self.out if n == "term.exit")
        self.assertEqual((exit_ev["term_id"], exit_ev["code"]), (tid, 3))
        with self.assertRaises(rpc.RpcError):
            await self.c.call("term.input", term_id=tid, data="x")

    async def test_command_whitelist(self):
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("term.open", cwd=self.tmp, cols=80, rows=24, command="rm -rf /")
        self.assertEqual(cm.exception.code, "refuse")
        with self.assertRaises(rpc.RpcError):
            await self.c.call("term.open", cwd=self.tmp, cols=80, rows=24, command="ccs add", name="a b;x")
        self.assertEqual(bridge_term.command_argv("ccs add", "perso2")[-2:], ["add", "perso2"])

    async def test_attach_replays_recent_output(self):
        tid = (await self.c.call("term.open", cwd=self.tmp, cols=80, rows=24))["term_id"]
        await self.c.call("term.input", term_id=tid, data="echo trace-ancienne\n")
        self.assertTrue(await self.wait(lambda: "trace-ancienne" in self.text(tid)))
        r = await self.c.call("term.attach", term_id=tid)
        self.assertIn("trace-ancienne", r["output"])
        self.assertEqual([t["term_id"] for t in (await self.c.call("term.list"))["terms"]], [tid])

    async def test_list_gives_folder_and_name(self):
        tid = (await self.c.call("term.open", cwd=self.tmp, cols=80, rows=24))["term_id"]
        t = (await self.c.call("term.list"))["terms"][0]
        self.assertEqual((t["term_id"], t["cwd"]), (tid, self.tmp))
        self.assertTrue(t["name"])

    async def test_input_error_is_french(self):
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("term.input", term_id="t999", data="x")
        self.assertEqual(cm.exception.code, "introuvable")

    async def test_sweep_closes_abandoned_terms(self):
        tid = (await self.c.call("term.open", cwd=self.tmp, cols=80, rows=24))["term_id"]
        await self.c.close()
        await asyncio.sleep(0.05)
        self.clock[0] += bridge_term.ABANDON + 1
        await self.hub.sweep()
        self.assertNotIn(tid, self.hub.terms)


if __name__ == "__main__":
    unittest.main()
