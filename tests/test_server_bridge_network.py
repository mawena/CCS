import json
import subprocess
import unittest

from ccs_app import network
from ccs_app.server import bridge_network, rpc
from tests.test_network import STATUS


class FakeBridge:
    def __init__(self):
        self.handlers = {}

    def add_handlers(self, h):
        self.handlers.update(h)


def runner(calls):
    def run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["tailscale", "status"]:
            out = json.dumps(STATUS)
        elif argv[:2] == ["tailscale", "ping"]:
            out = "pong from laptop (100.64.0.2) via DERP(mawena) in 40ms\npong from laptop (100.64.0.2) via 192.168.1.20:41641 in 3ms"
        elif argv[1:3] == ["nodes", "list"]:
            out = json.dumps([{"id": 7, "name": "laptop", "given_name": "laptop", "ip_addresses": ["100.64.0.2"], "online": True}])
        elif argv[1:3] == ["users", "list"]:
            out = '[{"id": 1, "name": "charles"}]'
        elif argv[1:3] == ["preauthkeys", "create"]:
            out = '{"key": "hskey-auth-x"}'
        elif argv[1:3] == ["auth", "register"]:
            out = '{"given_name": "pixel"}'
        else:
            out = "{}"
        return subprocess.CompletedProcess(argv, 0, out, "")
    return run


class NetworkApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.b = FakeBridge()
        self.api = bridge_network.NetworkApi(self.b, run=runner(self.calls))

    async def call(self, method, **params):
        return await self.b.handlers[method](None, params)

    async def test_status(self):
        st = await self.call("network.status")
        self.assertTrue(st["server"])
        self.assertEqual(st["self"]["name"], "srv-mawena-cloud")
        self.assertEqual(st["nodes"][0]["id"], 7)
        self.assertEqual(st["url"], network.SERVER_URL)

    async def test_ping_garde_le_dernier_chemin(self):
        r = await self.call("network.ping", name="laptop")
        self.assertEqual(r, {"ok": True, "path": "lan", "via": "192.168.1.20:41641", "ms": 3.0})

    async def test_cle(self):
        r = await self.call("network.key", name="pc-x")
        self.assertEqual(r["key"], "hskey-auth-x")
        self.assertIn("--hostname pc-x", r["linux"][1])
        with self.assertRaises(rpc.RpcError):
            await self.call("network.key", name="Pas Bon")

    async def test_renommer_retirer_valider(self):
        await self.call("network.rename", name="laptop", new="lp-home")
        self.assertIn(["headscale", "nodes", "rename", "--identifier", "7", "lp-home", "--output", "json"], self.calls)
        await self.call("network.remove", name="laptop")
        self.assertIn("delete", self.calls[-1])
        r = await self.call("network.register", key="https://network.mawena.cloud/register/hskey-authreq-abcdef123")
        self.assertEqual(r["name"], "pixel")
        self.assertIn("hskey-authreq-abcdef123", self.calls[-1])
        with self.assertRaises(rpc.RpcError):
            await self.call("network.rename", name="inconnu", new="x")
        with self.assertRaises(rpc.RpcError):
            await self.call("network.register", key="mauvaise clé !")


if __name__ == "__main__":
    unittest.main()
