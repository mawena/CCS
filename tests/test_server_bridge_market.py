"""Onglet Market dans le pont (`bridge_market`, phase 45) : `market.open` prépare le dossier du
chat Market, ouvre le chat, puis le rejoint (même chat d'un appareil à l'autre) ; une ancienne
conversation est reprise."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import market, sessions
from ccs_app.server import bridge, bridge_chat, bridge_market, rpc
from tests.helpers import make_home

FAKE = str(Path(__file__).resolve().parent / "fake_claude.py")


class MarketBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-bmarket-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(home), "XDG_DATA_HOME": str(home / ".local" / "share"),
                                           "XDG_CONFIG_HOME": str(home / ".config")})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.home = home
        self.sock = Path(self.tmp) / "b.sock"
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        self.hub = bridge_chat.ChatHub(self.bridge, claude=FAKE, environ={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        self.api = bridge_market.MarketApi(self.bridge, self.hub)
        await self.bridge.start(self.sock)
        self.addAsyncCleanup(self.bridge.stop)
        self.addAsyncCleanup(self.hub.close_all)

    async def client(self):
        c = rpc.RpcClient()
        c.on_event = lambda name, data: None
        await c.connect_unix(self.sock)
        self.addAsyncCleanup(c.close)
        await c.call("hello")
        return c

    async def test_open_then_join(self):
        a, b = await self.client(), await self.client()
        r1 = await a.call("market.open")
        ws = self.home / ".local" / "share" / "ccs" / "market"
        self.assertEqual(r1["cwd"], str(ws))
        self.assertEqual(r1["title"], "Market")
        self.assertTrue((ws / "CLAUDE.md").is_file())
        r2 = await b.call("market.open")                     # autre appareil : le même chat
        self.assertEqual(r2["chat_id"], r1["chat_id"])
        self.assertEqual(len((await a.call("chat.list"))["chats"]), 1)

    async def test_resumes_last_conversation(self):
        ws = market.workspace()
        journal = sessions.transcript_path(str(ws), "abc-123")
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text('{"type":"user","message":{"role":"user","content":"routeur"}}\n')
        c = await self.client()
        r = await c.call("market.open")
        self.assertEqual(r["session_id"], "abc-123")
        self.assertEqual(r["state"], "idle")


if __name__ == "__main__":
    unittest.main()
