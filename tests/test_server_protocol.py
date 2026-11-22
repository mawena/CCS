"""Version du protocole du pont et table des anciens noms (compatibilité 1.x)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import __version__
from ccs_app.server import bridge, protocol, rpc
from tests.helpers import make_home
from tests.test_server_bridge import KEY, ticket


class TableTest(unittest.TestCase):
    def test_every_old_and_new_method_exists(self):
        """Chaque ancien nom mène à une méthode du pont complet, et plus aucun ancien nom n'y
        est enregistré."""
        handlers = bridge.build("alice", KEY, start_daemon=False, install_claude=False).handlers()
        for old, new in protocol.METHOD_ALIASES.items():
            self.assertIn(new, handlers, old)
            self.assertNotIn(old, handlers, old)
        for method in protocol.PARAM_ALIASES:
            self.assertIn(method, handlers)

    def test_normalize(self):
        self.assertEqual(protocol.normalize("machine.attach", {"machine": "pc"}),
                         ("machines.attach", {"machine": "pc"}))
        self.assertEqual(protocol.normalize("conversation.restore", {"tid": "t1"}),
                         ("trash.restore", {"trash_id": "t1"}))
        self.assertEqual(protocol.normalize("machines.limit", {"machine": "pc", "limite": 3}),
                         ("machines.limit", {"machine": "pc", "limit": 3}))
        self.assertEqual(protocol.normalize("machines.configure", {"relais": "https://r", "jeton": "j"}),
                         ("machines.configure", {"relay": "https://r", "token": "j"}))
        # le nouveau nom l'emporte s'il est donné aussi ; un nom nouveau passe tel quel
        self.assertEqual(protocol.normalize("machines.limit", {"limite": 1, "limit": 2})[1], {"limit": 2})
        params = {"chat_id": "c"}
        self.assertIs(protocol.normalize("chat.send", params)[1], params)

    def test_to_legacy_and_upgrade(self):
        self.assertEqual(protocol.to_legacy("trash.restore", {"trash_id": "t1"}),
                         ("conversation.restore", {"tid": "t1"}))
        self.assertEqual(protocol.to_legacy("chat.list", {}), ("chat.list", {}))
        r = protocol.upgrade_result("trash.list", {"items": [{"tid": "t1", "id": "s1"}]})
        self.assertEqual(r["items"][0], {"tid": "t1", "id": "s1", "trash_id": "t1", "session_id": "s1"})
        self.assertEqual(protocol.upgrade_result("conversations.trash", {"tid": "t"}),
                         {"tid": "t", "trash_id": "t"})

    def test_events_follow_the_client(self):
        old, new = rpc.Connection.__new__(rpc.Connection), rpc.Connection.__new__(rpc.Connection)
        old.peer, new.peer = {}, {"protocol": 1}
        self.assertEqual(protocol.event_for(old, "machines.ready"), "machine.ready")
        self.assertEqual(protocol.event_for(old, "shell.done"), "work.shell")
        self.assertEqual(protocol.event_for(new, "machine.ready"), "machines.ready")
        self.assertEqual(protocol.event_for(new, "chat.event"), "chat.event")

    def test_client_protocol(self):
        for value, n in ((None, 0), ("", 0), ("x", 0), ("-1", 0), ("1", 1), (2, 2)):
            self.assertEqual(protocol.client_protocol(value), n)


class SocketTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-proto-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.bridge = bridge.Bridge("alice", KEY, start_daemon=False, install_claude=False)
        self.bridge.add_handlers({"trash.restore": self._restore})
        self.sock = Path(self.tmp) / "b.sock"
        await self.bridge.start(self.sock)
        self.addAsyncCleanup(self.bridge.stop)

    async def _restore(self, _conn, params):
        return {"got": params}

    async def client(self, **extra):
        c = rpc.RpcClient()
        await c.connect_unix(self.sock)
        self.addAsyncCleanup(c.close)
        t, h = ticket()
        return c, await c.call("hello", ticket=t, session_hash=h, **extra)

    async def test_hello_gives_the_protocol(self):
        _c, r = await self.client(protocol=1)
        self.assertEqual(r, {"user": "alice", "protocol": protocol.PROTOCOL, "version": __version__})

    async def test_old_method_and_param_names_are_accepted(self):
        c, _r = await self.client()
        self.assertEqual(await c.call("conversation.restore", tid="t1"), {"got": {"trash_id": "t1"}})
        self.assertEqual(await c.call("trash.restore", trash_id="t2"), {"got": {"trash_id": "t2"}})

    async def test_old_cache_is_removed(self):
        old = self.home / ".cache" / "ccs" / "distant-en-cours"
        (old / "x").mkdir(parents=True)
        bridge.remove_old_cache()
        self.assertFalse(old.exists())
        self.assertTrue(old.parent.is_dir())
        bridge.remove_old_cache()   # rien à faire la deuxième fois


if __name__ == "__main__":
    unittest.main()
