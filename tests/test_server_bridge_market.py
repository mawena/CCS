"""Market dans le pont (`bridge_market`) : `market.workspace` prépare le dossier du chat Market et
renvoie son chemin, où la feuille « Nouvelle session » ouvre un chat."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        self.api = bridge_market.MarketApi(self.bridge)
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

    async def test_workspace(self):
        c = await self.client()
        r = await c.call("market.workspace")
        ws = self.home / ".local" / "share" / "ccs" / "market"
        self.assertEqual(r["cwd"], str(ws))
        self.assertTrue((ws / "CLAUDE.md").is_file())
        self.assertTrue((ws / ".claude" / "settings.json").is_file())

    async def test_new_session_in_workspace(self):
        c = await self.client()
        cwd = (await c.call("market.workspace"))["cwd"]
        r = await c.call("chat.open", cwd=cwd)          # la feuille « Nouvelle session » ouvre un chat ordinaire
        self.assertEqual(r["cwd"], cwd)


if __name__ == "__main__":
    unittest.main()
