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

    def test_values_follow_the_client(self):
        """Rôles : anciens pour un ancien client, nouveaux depuis un ancien pont ; rien n'est
        modifié en place (les données d'un événement sont partagées entre les connexions)."""
        old, new = rpc.Connection.__new__(rpc.Connection), rpc.Connection.__new__(rpc.Connection)
        old.peer, new.peer = {}, {"protocol": 1}
        msgs = {"messages": [{"role": "user", "text": "a"}, {"role": "assistant", "text": "b"},
                             {"role": "tool", "text": ""}, {"role": "note", "text": "c"}]}
        self.assertIs(protocol.downgrade_result(new, "conversations.messages", msgs), msgs)
        down = protocol.downgrade_result(old, "conversations.messages", msgs)
        self.assertEqual([m["role"] for m in down["messages"]], ["utilisateur", "assistant", "outil", "note"])
        self.assertEqual(msgs["messages"][0]["role"], "user")
        up = protocol.upgrade_result("conversations.messages", down)
        self.assertEqual([m["role"] for m in up["messages"]], ["user", "assistant", "tool", "note"])

        entry = {"tags": ["x"], "role": "user", "excerpt": "e", "ts": 1.0}
        tags = {"messages": {"u-1": entry}, "known": ["x"]}
        self.assertEqual(protocol.downgrade_result(old, "chat.tags", tags)["messages"]["u-1"]["role"], "utilisateur")
        self.assertEqual(protocol.downgrade_result(old, "chat.tag", {"entry": entry})["entry"]["role"], "utilisateur")
        self.assertEqual(protocol.downgrade_result(old, "chat.tag", {"entry": None}), {"entry": None})
        self.assertEqual(entry["role"], "user")
        old_entry = dict(entry, role="utilisateur")
        self.assertEqual(protocol.upgrade_result("chat.tags", {"messages": {"u": old_entry}})["messages"]["u"]["role"], "user")
        self.assertEqual(protocol.upgrade_result("chat.tag", {"entry": old_entry})["entry"]["role"], "user")

        event = {"session_id": "s", "msg_id": "u-1", "entry": entry}
        self.assertIs(protocol.event_data(new, "chat.tags", event), event)
        self.assertEqual(protocol.event_data(old, "chat.tags", event)["entry"]["role"], "utilisateur")
        self.assertEqual(protocol.upgrade_event("chat.tags", {"entry": old_entry})["entry"]["role"], "user")
        self.assertEqual(protocol.to_legacy("chat.tag", {"role": "user"})[1], {"role": "utilisateur"})
        self.assertEqual(protocol.to_legacy("chat.tag", {"role": "assistant"})[1], {"role": "assistant"})

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
        self.bridge.add_handlers({"trash.restore": self._restore, "conversations.messages": self._messages})
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

    async def test_old_client_gets_old_roles(self):
        """Par le socket : la réponse est adaptée à la version déclarée par le client."""
        old, _r = await self.client()
        new, _r = await self.client(protocol=1)
        self.assertEqual((await old.call("conversations.messages"))["messages"][0]["role"], "utilisateur")
        self.assertEqual((await new.call("conversations.messages"))["messages"][0]["role"], "user")

    async def _messages(self, _conn, _params):
        return {"messages": [{"role": "user", "text": "a"}]}

    async def test_old_cache_is_removed(self):
        old = self.home / ".cache" / "ccs" / "distant-en-cours"
        (old / "x").mkdir(parents=True)
        bridge.remove_old_cache()
        self.assertFalse(old.exists())
        self.assertTrue(old.parent.is_dir())
        bridge.remove_old_cache()   # rien à faire la deuxième fois


if __name__ == "__main__":
    unittest.main()
