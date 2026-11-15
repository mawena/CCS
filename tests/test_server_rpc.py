"""Protocole JSON par lignes sur socket Unix (serveur, client, événements, limites)."""

import asyncio
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app.server import paths, rpc


class RpcTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-rpc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sock = os.path.join(self.tmp, "s.sock")
        self.connections = []

        async def add(conn, params):
            return {"sum": params["a"] + params["b"]}

        async def refuse(conn, params):
            raise rpc.RpcError("refuse", "non")

        async def crash(conn, params):
            raise ZeroDivisionError("boum")

        async def ping_me(conn, params):
            await conn.push("ping", {"n": 1})
            return {}

        async def big(conn, params):
            return {"x": "a" * (rpc.MAX_LINE + 10)}

        async def big_event(conn, params):
            await conn.push("gros", {"x": "a" * (rpc.MAX_LINE + 10)})
            await conn.push("petit", {"n": 2})
            return {}

        self.server = rpc.RpcServer({"add": add, "refuse": refuse, "crash": crash, "ping_me": ping_me,
                                     "big": big, "big_event": big_event},
                                    on_connect=lambda c: self.connections.append(c))
        await self.server.start_unix(self.sock, 0o660)
        self.addAsyncCleanup(self.server.close)

    async def client(self):
        c = rpc.RpcClient()
        await c.connect_unix(self.sock)
        self.addAsyncCleanup(c.close)
        return c

    async def test_call_and_result(self):
        c = await self.client()
        self.assertEqual(await c.call("add", a=2, b=3), {"sum": 5})
        self.assertEqual(await c.call("add", a=1, b=1), {"sum": 2})

    async def test_unknown_method(self):
        c = await self.client()
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("nope")
        self.assertEqual(cm.exception.code, "introuvable")

    async def test_handler_rpc_error_is_returned(self):
        c = await self.client()
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("refuse")
        self.assertEqual((cm.exception.code, cm.exception.message), ("refuse", "non"))

    async def test_handler_crash_is_interne(self):
        c = await self.client()
        with self.assertLogs("ccs.rpc", "ERROR"):
            with self.assertRaises(rpc.RpcError) as cm:
                await c.call("crash")
        self.assertEqual(cm.exception.code, "interne")
        self.assertNotIn("boum", cm.exception.message)       # pas de détail interne au client
        self.assertEqual(await c.call("add", a=1, b=2), {"sum": 3})

    async def test_push_event_reaches_client(self):
        c = await self.client()
        got = []
        c.on_event = lambda name, data: got.append((name, data))
        await c.call("ping_me")
        for _ in range(50):
            if got:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(got, [("ping", {"n": 1})])
        self.assertEqual(len(self.connections), 1)

    async def test_line_too_long(self):
        reader, writer = await asyncio.open_unix_connection(self.sock, limit=rpc.MAX_LINE * 2)
        big = json.dumps({"id": 1, "method": "add", "params": {"x": "a" * (rpc.MAX_LINE + 10)}})
        writer.write(big.encode() + b"\n")
        await writer.drain()
        line = await reader.readline()
        self.assertEqual(json.loads(line)["error"]["code"], "trop_gros")
        self.assertEqual(await reader.read(), b"")             # connexion fermée
        writer.close()
        c = await self.client()                                # le serveur tient
        self.assertEqual(await c.call("add", a=1, b=1), {"sum": 2})

    async def test_too_big_result_fails_this_call_only(self):
        """C6 : une réponse plus grosse que MAX_LINE devient `trop_gros`, la connexion reste."""
        c = await self.client()
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("big")
        self.assertEqual(cm.exception.code, "trop_gros")
        self.assertTrue(c.connected)
        self.assertEqual(await c.call("add", a=1, b=2), {"sum": 3})

    async def test_too_big_event_is_dropped(self):
        c = await self.client()
        got = []
        c.on_event = lambda name, data: got.append(name)
        with self.assertLogs("ccs.rpc", "WARNING"):
            await c.call("big_event")
        for _ in range(50):
            if got:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(got, ["petit"])
        self.assertEqual(await c.call("add", a=1, b=1), {"sum": 2})

    async def test_too_big_request_refused_before_sending(self):
        c = await self.client()
        with self.assertRaises(rpc.RpcError) as cm:
            await c.call("add", a="a" * (rpc.MAX_LINE + 10), b="")
        self.assertEqual(cm.exception.code, "trop_gros")
        self.assertEqual(await c.call("add", a=2, b=2), {"sum": 4})

    async def test_wait_closed_returns_when_server_goes_away(self):
        c = await self.client()
        await c.call("add", a=0, b=0)
        waiting = asyncio.ensure_future(c.wait_closed())
        await asyncio.sleep(0.05)
        self.assertFalse(waiting.done())
        await self.server.close()
        await asyncio.wait_for(waiting, 5)
        self.assertFalse(c.connected)

    async def test_invalid_json_line(self):
        reader, writer = await asyncio.open_unix_connection(self.sock)
        writer.write(b"pas du json\n[1,2]\n")
        await writer.drain()
        self.assertEqual(json.loads(await reader.readline())["error"]["code"], "invalide")
        self.assertEqual(json.loads(await reader.readline())["error"]["code"], "invalide")
        writer.close()

    async def test_socket_mode(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.sock).st_mode), 0o660)

    async def test_closed_flag(self):
        c = await self.client()
        await c.call("add", a=0, b=0)
        await c.close()
        for _ in range(50):
            if self.connections[0].closed:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(self.connections[0].closed)


class PathsTest(unittest.TestCase):
    def test_paths_follow_env(self):
        with mock.patch.dict(os.environ, {"CCS_SERVER_ROOT": "/tmp/racine"}):
            self.assertEqual(paths.auth_socket(), Path("/tmp/racine/run/ccs/auth.sock"))
            self.assertEqual(paths.bridge_socket("alice"), Path("/tmp/racine/run/ccs/bridge/alice/bridge.sock"))
            self.assertEqual(paths.bridge_key("alice"), Path("/tmp/racine/run/ccs/bridge/alice/key"))
            self.assertEqual(paths.totp_file("alice"), Path("/tmp/racine/var/lib/ccs/totp/alice"))
            self.assertEqual(paths.sessions_file(), Path("/tmp/racine/var/lib/ccs/sessions.json"))
            self.assertEqual(paths.web_config(), Path("/tmp/racine/etc/ccs/web.json"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CCS_SERVER_ROOT", None)
            self.assertEqual(paths.auth_socket(), Path("/run/ccs/auth.sock"))

    def test_user_names_are_checked(self):
        for bad in ("../x", "a/b", "", ".", "x y"):
            with self.assertRaises(ValueError):
                paths.bridge_socket(bad)


if __name__ == "__main__":
    unittest.main()
