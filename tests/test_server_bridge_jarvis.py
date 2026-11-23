"""Relais des oreilles de Jarvis dans le pont (`bridge_jarvis`, `jarvis_link`).

Le cerveau est un faux cerveau TLS local (`tests/jarvis_brain.py`) ; le tunnel est soit une
simple connexion TCP, soit un faux `ricochet-agent` (programme Python qui relie son entrée et sa
sortie au port demandé), pour vérifier aussi la vie du processus."""

import asyncio
import base64
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import settings
from ccs_app.server import bridge, bridge_jarvis, jarvis_link, rpc
from tests.helpers import make_home
from tests.jarvis_brain import FakeBrain
from tests.test_server_bridge import KEY, ticket

FAKE_AGENT = r'''
import socket, sys, threading
args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
if args[1] == "eteint":
    sys.stderr.write("erreur : la machine eteint est hors ligne\n")
    sys.exit(3)
s = socket.create_connection(("127.0.0.1", port))
def up():
    while True:
        b = sys.stdin.buffer.raw.read(65536)
        if not b:
            break
        s.sendall(b)
    s.shutdown(socket.SHUT_WR)
threading.Thread(target=up, daemon=True).start()
while True:
    b = s.recv(65536)
    if not b:
        break
    sys.stdout.buffer.write(b)
    sys.stdout.buffer.flush()
'''


def frame(utterance, samples):
    return bytes([1]) + struct.pack("<I", utterance) + struct.pack(f"<{len(samples)}h", *samples)


class JarvisBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccs-jarvis-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = make_home(str(self.tmp))
        env = mock.patch.dict(os.environ, {"HOME": str(home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.brain = FakeBrain(self.tmp)
        await self.brain.start()
        self.addAsyncCleanup(self.brain.stop)
        self.tunnels = []
        self.near = bridge.Bridge("alice", KEY, start_daemon=False, install_claude=False)
        self.api = bridge_jarvis.JarvisApi(self.near, tunnel=self._tunnel, timeout=5)
        self.sock = self.tmp / "near.sock"
        await self.near.start(self.sock)
        self.addAsyncCleanup(self.near.stop)

    async def _tunnel(self, machine, port):
        self.tunnels.append((machine, port))
        if machine == "eteint":
            raise jarvis_link.LinkError("la machine eteint est hors ligne")
        s = socket.create_connection(("127.0.0.1", self.brain.port))
        s.setblocking(False)
        return s, None

    async def client(self):
        c = rpc.RpcClient()
        await c.connect_unix(self.sock)
        self.addAsyncCleanup(c.close)
        t, h = ticket()
        await c.call("hello", ticket=t, session_hash=h)
        self.events = []
        c.on_event = lambda n, d: self.events.append((n, d))
        return c

    async def wait_for(self, check, what="événement"):
        for _ in range(250):
            if check():
                return
            await asyncio.sleep(0.02)
        self.fail(f"{what} attendu : {self.events}")

    def messages(self):
        return [json.loads(d["text"]) for n, d in self.events if n == "jarvis.message" and "text" in d]

    async def test_settings_defaults_and_configure(self):
        c = await self.client()
        r = await c.call("jarvis.settings")
        self.assertEqual((r["machine"], r["port"], r["fingerprint"]), ("laptop-maison", 7341, ""))
        r = await c.call("jarvis.configure", machine="pc-salon", port=7342)
        self.assertEqual((r["machine"], r["port"]), ("pc-salon", 7342))
        for bad in ({"machine": "../x"}, {"port": 0}, {"port": "7341"}):
            with self.assertRaises(rpc.RpcError) as e:
                await c.call("jarvis.configure", **bad)
            self.assertEqual(e.exception.code, "invalide")
        self.assertEqual(settings.load_settings()["jarvis"]["machine"], "pc-salon")
        self.assertTrue(bridge.Bridge.keeps_local("jarvis.open"))

    async def test_pairing_then_conversation_both_ways(self):
        c = await self.client()
        # appairage : empreinte donnée par l'adresse jarvis://pair, gardée ensuite
        r = await c.call("jarvis.open", fingerprint=self.brain.fingerprint,
                         first=json.dumps({"type": "pair", "version": 1, "code": "482913",
                                           "name": "web", "platform": "web"}))
        self.assertEqual(self.tunnels, [("laptop-maison", 7341)])
        self.assertRegex(r["fingerprint_short"], r"^[0-9A-F]{4}(-[0-9A-F]{4}){3}$")
        await self.wait_for(lambda: any(n == "jarvis.closed" for n, _ in self.events), "fermeture")
        self.assertEqual(self.messages()[0]["type"], "paired")
        self.assertEqual(settings.load_settings()["jarvis"]["fingerprint"], self.brain.fingerprint)
        self.assertEqual(self.api.links, {})
        # puis une phrase : hello sans empreinte (celle du réglage), wake, son, listen_end
        self.events.clear()
        await c.call("jarvis.open", first=json.dumps({"type": "hello", "version": 1, "ear_id": "e1",
                                                       "token": "jeton-oreille"}))
        await c.call("jarvis.send", text=json.dumps({"type": "wake", "utterance": 1, "score": 2.0,
                                                     "level_db": 0, "muted": False}))
        for _ in range(3):
            data = frame(1, [100] * 16000)
            await c.call("jarvis.send", binary=base64.b64encode(data).decode())
        await c.call("jarvis.send", text=json.dumps({"type": "listen_end", "utterance": 1, "muted": False,
                                                     "no_speech": False}))
        await self.wait_for(lambda: any(m["type"] == "response" for m in self.messages()), "réponse")
        types = [m["type"] for m in self.messages()]
        self.assertEqual(types, ["welcome", "elected", "response"])
        audio = self.messages()[-1]["response"]["audio"]
        self.assertEqual(struct.unpack("<4h", base64.b64decode(audio["pcm"])), (0, 1000, -1000, 0))
        self.assertEqual(self.brain.samples, 48000)
        kinds = [k for k, _ in self.brain.received]
        self.assertEqual(kinds[-5:], ["text", "binary", "binary", "binary", "text"])
        # binaire du cerveau vers l'oreille
        await c.call("jarvis.send", text=json.dumps({"type": "binary_back"}))
        await self.wait_for(lambda: any("binary" in d for n, d in self.events if n == "jarvis.message"))
        # fermeture par le cerveau, avec sa raison
        await c.call("jarvis.send", text=json.dumps({"type": "bye"}))
        await self.wait_for(lambda: any(n == "jarvis.closed" for n, _ in self.events), "fermeture")
        self.assertEqual([d for n, d in self.events if n == "jarvis.closed"], [{"reason": "au revoir"}])
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.send", text="{}")
        self.assertEqual(e.exception.code, "introuvable")

    async def test_wrong_fingerprint_refused_before_anything_is_sent(self):
        c = await self.client()
        other = base64.urlsafe_b64encode(b"\x01" * 32).rstrip(b"=").decode()
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.open", fingerprint=other, first='{"type":"hello"}')
        self.assertEqual(e.exception.code, "introuvable")
        self.assertIn("empreinte", e.exception.message)
        await asyncio.sleep(0.1)
        self.assertEqual(self.brain.received, [])
        self.assertEqual(settings.load_settings()["jarvis"]["fingerprint"], "")

    async def test_missing_or_bad_fingerprint_and_first_message(self):
        c = await self.client()
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.open", first='{"type":"hello"}')
        self.assertIn("jarvis pair", e.exception.message)
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.open", fingerprint="pas-une-empreinte", first='{"type":"hello"}')
        self.assertEqual(e.exception.code, "invalide")
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.open", fingerprint=self.brain.fingerprint)
        self.assertEqual(e.exception.code, "invalide")
        self.assertEqual(self.tunnels, [])

    async def test_unreachable_brain_says_so_at_once(self):
        c = await self.client()
        await c.call("jarvis.configure", machine="eteint")
        with self.assertRaises(rpc.RpcError) as e:
            await asyncio.wait_for(c.call("jarvis.open", fingerprint=self.brain.fingerprint,
                                          first='{"type":"hello"}'), 3)
        self.assertEqual(e.exception.code, "introuvable")
        self.assertIn("Jarvis est injoignable (eteint:7341)", e.exception.message)
        self.assertIn("hors ligne", e.exception.message)

    async def test_size_limits(self):
        c = await self.client()
        await c.call("jarvis.open", fingerprint=self.brain.fingerprint,
                     first=json.dumps({"type": "hello", "token": "jeton-oreille"}))
        too_big = frame(1, [0] * 16001)
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.send", binary=base64.b64encode(too_big).decode())
        self.assertEqual(e.exception.code, "trop_gros")
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.send", text="x" * (64 * 1024 + 1))
        self.assertEqual(e.exception.code, "trop_gros")
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.send", binary="@@pas du base64@@")
        self.assertEqual(e.exception.code, "invalide")
        with self.assertRaises(rpc.RpcError) as e:
            await c.call("jarvis.open", fingerprint=self.brain.fingerprint, first='{"type":"hello"}')
        self.assertEqual(e.exception.code, "conflit")
        # cerveau → oreille : un message de plus de 6 Mo coupe le lien
        await c.call("jarvis.send", text=json.dumps({"type": "big", "size": jarvis_link.MAX_INCOMING + 10}))
        await self.wait_for(lambda: any(n == "jarvis.closed" for n, _ in self.events), "fermeture")
        self.assertIn("trop gros", [d for n, d in self.events if n == "jarvis.closed"][0]["reason"])

    async def test_closing_the_connection_closes_the_brain_side(self):
        c = await self.client()
        await c.call("jarvis.open", fingerprint=self.brain.fingerprint,
                     first=json.dumps({"type": "hello", "token": "jeton-oreille"}))
        await self.wait_for(lambda: self.messages(), "welcome")
        await c.close()
        await self.wait_for(lambda: self.brain.closed == 1 and not self.api.links, "fermeture côté cerveau")


class TunnelProcessTest(unittest.IsolatedAsyncioTestCase):
    """Le vrai `open_tunnel`, avec un faux `ricochet-agent`."""

    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccs-jarvis-t-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.brain = FakeBrain(self.tmp)
        await self.brain.start()
        self.addAsyncCleanup(self.brain.stop)
        script = self.tmp / "faux_agent.py"
        script.write_text(FAKE_AGENT)
        self.agent = self.tmp / "ricochet-agent"
        self.agent.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
        self.agent.chmod(0o700)

    async def test_tunnel_relays_and_process_stops(self):
        fp = jarvis_link.parse_fingerprint(self.brain.fingerprint)
        sock, proc = await jarvis_link.open_tunnel("laptop-maison", self.brain.port,
                                                   agent=str(self.agent), config=self.tmp / "c.toml")
        ws = await jarvis_link.connect(sock, fp)
        await ws.send_text(json.dumps({"type": "hello", "token": "jeton-oreille"}))
        kind, data = await ws.recv()
        self.assertEqual((kind, json.loads(data)["type"]), ("text", "welcome"))
        link = bridge_jarvis.Link(ws, proc)
        await link.close()
        self.assertIsNotNone(proc.returncode)

    async def test_tunnel_error_is_reported(self):
        fp = jarvis_link.parse_fingerprint(self.brain.fingerprint)
        sock, proc = await jarvis_link.open_tunnel("eteint", self.brain.port,
                                                   agent=str(self.agent), config=self.tmp / "c.toml")
        with self.assertRaises(jarvis_link.LinkError):
            await asyncio.wait_for(jarvis_link.connect(sock, fp), 5)
        self.assertIn("hors ligne", await jarvis_link.process_error(proc))

    def test_fingerprint_helpers(self):
        raw = bytes(range(32))
        text = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        self.assertEqual(jarvis_link.parse_fingerprint(text), raw)
        self.assertEqual(jarvis_link.short_fingerprint(raw), "0001-0203-0405-0607")
        for bad in ("", "abc", text + "A", text[:-1] + "=", None, 12):
            self.assertIsNone(jarvis_link.parse_fingerprint(bad))


if __name__ == "__main__":
    unittest.main()


class MeshRouteTest(unittest.IsolatedAsyncioTestCase):
    """Réseau maillé d'abord (connexion directe), tunnel Ricochet en secours."""

    async def test_direct_connection_when_the_machine_is_in_the_mesh(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            got = await jarvis_link.open_mesh("laptop-maison", port, address="127.0.0.1")
            self.assertIsNotNone(got)
            sock, proc = got
            self.assertIsNone(proc)
            sock.close()
        finally:
            server.close()
            await server.wait_closed()

    async def test_nothing_when_absent_or_unreachable(self):
        with mock.patch("ccs_app.distant.mesh_address", lambda *a, **k: None):
            self.assertIsNone(await jarvis_link.open_mesh("laptop-maison", 7341))
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()                        # port fermé : connexion refusée
        self.assertIsNone(await jarvis_link.open_mesh("x", port, address="127.0.0.1"))

    async def test_route_falls_back_to_ricochet(self):
        calls = []

        async def ricochet(machine, port):
            calls.append((machine, port))
            return "tunnel"

        async def no_mesh(machine, port):
            return None

        with mock.patch.object(jarvis_link, "open_mesh", no_mesh), \
                mock.patch.object(bridge_jarvis.JarvisApi, "_ricochet", staticmethod(ricochet)):
            self.assertEqual(await bridge_jarvis.JarvisApi._route("laptop-maison", 7341), "tunnel")
        self.assertEqual(calls, [("laptop-maison", 7341)])

        async def mesh(machine, port):
            return ("direct", None)

        with mock.patch.object(jarvis_link, "open_mesh", mesh), \
                mock.patch.object(bridge_jarvis.JarvisApi, "_ricochet", staticmethod(ricochet)):
            self.assertEqual(await bridge_jarvis.JarvisApi._route("laptop-maison", 7341), ("direct", None))
        self.assertEqual(len(calls), 1)
