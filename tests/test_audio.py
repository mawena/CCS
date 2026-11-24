import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from ccs_app import audio


class FakePw:
    def __init__(self):
        self.mods = {}
        self.states = {}
        self.created = []

    def sinks(self):
        return dict(self.states)

    def modules(self):
        return dict(self.mods)

    def create(self, device, label):
        self.created.append((device, label))
        self.mods[audio.sink_name(device)] = str(len(self.mods) + 1)

    def remove(self, sink):
        self.mods.pop(sink, None)

    def remove_all(self):
        self.mods.clear()


class FakeProc:
    def __init__(self, argv, **kw):
        self.argv = argv
        self.signals = []
        self.done = None

    def poll(self):
        return self.done

    def send_signal(self, sig):
        self.signals.append(sig)
        self.done = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.done = -9


class FakeClient:
    def __init__(self):
        self.calls = []
        self.online = True

    async def call(self, method, **params):
        self.calls.append((method, params))
        return {}


class ParseTest(unittest.TestCase):
    def test_sorties_et_modules(self):
        sinks = "52\tccs_audio_iphone\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n" \
                "40\talsa_output.pci\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
        self.assertEqual(audio.parse_sinks(sinks), {"ccs_audio_iphone": "RUNNING",
                                                     "alsa_output.pci": "SUSPENDED"})
        mods = "536870913\tmodule-null-sink\tsink_name=ccs_audio_iphone sink_properties=device.description=\"iPhone\"\n" \
               "536870914\tmodule-null-sink\tsink_name=autre\n12\tmodule-x\t\n"
        self.assertEqual(audio.parse_modules(mods), {"ccs_audio_iphone": "536870913"})

    def test_noms(self):
        self.assertEqual(audio.sink_name("pc-bureau.local"), "ccs_audio_pc_bureau_local")
        self.assertEqual(audio.clean_label('iPhone "de" Charles\n'), "iPhone de Charles")

    def test_identite(self):
        st = {"self": {"name": "pc-bureau", "ips": ["fd7a:115c::2", "100.64.0.2"]}}
        self.assertEqual(audio.identity(st), ("pc-bureau", "100.64.0.2"))
        with self.assertRaises(audio.AudioError):
            audio.identity({"self": {"name": "x", "ips": ["192.168.1.2"]}})

    def test_pipelines(self):
        r = audio.receiver_argv(4010)
        self.assertIn("port=4010", r)
        self.assertIn("rtpopusdepay", r)
        s = audio.sender_argv("ccs_audio_iphone.monitor", "100.64.0.4", 4010)
        self.assertIn("device=ccs_audio_iphone.monitor", s)
        self.assertIn("host=100.64.0.4", s)
        self.assertIn("frame-size=10", s)
        self.assertIn("audio-type=restricted-lowdelay", s)
        self.assertIn("buffer-time=20000", s)
        self.assertIn("latency-time=5000", s)
        self.assertIn("pt=96", s)
        self.assertIn("latency=40", r)
        self.assertIn("buffer-time=40000", r)
        self.assertIn("latency=80", audio.receiver_argv(4010, 80))

    def test_latence_reglable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audio.toml"
            p.write_text("active = true\nlatency_ms = 60\n", encoding="utf-8")
            self.assertEqual(audio.load_config(p)["latency_ms"], 60)
            p.write_text("latency_ms = 5\n", encoding="utf-8")
            self.assertNotIn("latency_ms", audio.load_config(p))
            audio.save_config({"active": True, "port": 4010, "label": "", "latency_ms": 80}, p)
            self.assertEqual(audio.load_config(p)["latency_ms"], 80)

    def test_resoudre(self):
        devs = [{"device": "iphone", "label": "iPhone de Charles"},
                {"device": "pixel", "label": "Pixel 8"}, {"device": "pc-bureau", "label": "PC"}]
        self.assertEqual(audio.resolve(devs, "Pixel"), "pixel")
        self.assertEqual(audio.resolve(devs, "charles"), "iphone")
        self.assertEqual(audio.resolve(devs, "ici", me="pc-bureau"), "pc-bureau")
        with self.assertRaises(audio.AudioError):
            audio.resolve(devs, "p")             # pixel et pc-bureau
        with self.assertRaises(audio.AudioError):
            audio.resolve(devs, "tablette")

    def test_reglages(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "audio.toml"
            self.assertEqual(audio.load_config(p), {"active": False, "port": 4010, "label": ""})
            audio.save_config({"active": True, "port": 4012, "label": 'PC "bureau"'}, p)
            self.assertEqual(audio.load_config(p), {"active": True, "port": 4012, "label": "PC bureau"})

    def test_transport_serveur_local(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("CCS_SERVER_ROOT")
            os.environ["CCS_SERVER_ROOT"] = d
            try:
                base = Path(d) / "run" / "ccs" / "bridge" / "alice"
                base.mkdir(parents=True)
                (base / "bridge.sock").touch()
                (base / "key").write_bytes(b"k" * 32)
                t = audio.server_transport("alice", servers=[])
                self.assertIsInstance(t, audio.ServerSocketTransport)
                p = t.hello_params()
                self.assertEqual(len(p["ticket"]), 64)
                with self.assertRaises(audio.AudioError):
                    audio.server_transport("bob", servers=[])
            finally:
                if old is None:
                    os.environ.pop("CCS_SERVER_ROOT")
                else:
                    os.environ["CCS_SERVER_ROOT"] = old


class AgentTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 0.0
        self.pw = FakePw()
        self.procs = []

        def popen(argv, **kw):
            p = FakeProc(argv)
            self.procs.append(p)
            return p
        self.agent = audio.Agent(None, "pc-bureau", "100.64.0.2", {"port": 4010, "label": ""},
                                 pipewire=self.pw, popen=popen, clock=lambda: self.now)
        self.agent.client = FakeClient()
        self.agent.devices = {"iphone": {"device": "iphone", "label": "iPhone", "play": True},
                              "web": {"device": "web", "label": "Web", "play": False}}

    def test_sorties_virtuelles(self):
        self.pw.mods["ccs_audio_parti"] = "9"
        self.agent.sync_sinks()
        self.assertEqual(self.pw.created, [("iphone", "iPhone")])
        self.assertEqual(set(self.pw.mods), {"ccs_audio_iphone"})

    def test_evenements(self):
        a = self.agent
        a.on_event("audio", {"action": "receive", "device": "iphone", "stream": "a1"})
        self.assertIsNone(a.receiver)                       # pas pour moi
        a.on_event("audio", {"action": "receive", "device": "pc-bureau", "stream": "a1", "from": "iphone"})
        self.assertEqual(a.receiver[0], "a1")
        self.assertIn("udpsrc", self.procs[-1].argv)
        a.on_event("audio", {"action": "emit", "device": "pc-bureau", "stream": "a2", "to": "iphone",
                             "ip": "100.64.0.4", "port": 4010})
        self.assertIn("device=@DEFAULT_MONITOR@", self.procs[-1].argv)
        a.on_event("audio", {"action": "stop", "stream": "a1", "devices": ["iphone", "pc-bureau"]})
        self.assertIsNone(a.receiver)
        self.assertIsNotNone(a.sender)
        self.assertTrue(self.procs[0].signals)              # récepteur arrêté proprement

    async def test_sortie_utilisee_lance_puis_arrete(self):
        a = self.agent
        self.pw.states["ccs_audio_iphone"] = "RUNNING"
        await a.watch_sinks()
        self.assertEqual(a.client.calls, [("audio.send", {"source": "pc-bureau", "target": "iphone"})])
        await a.watch_sinks()
        self.assertEqual(len(a.client.calls), 1)            # pas de nouvelle demande avant 5 s
        a.on_event("audio", {"action": "emit", "device": "pc-bureau", "stream": "a3", "to": "iphone",
                             "ip": "100.64.0.4", "port": 4010})
        self.assertIn("device=ccs_audio_iphone.monitor", self.procs[-1].argv)
        self.pw.states["ccs_audio_iphone"] = "IDLE"
        await a.watch_sinks()
        self.now += audio.IDLE_STOP_S
        await a.watch_sinks()
        self.assertIsNone(a.sender)
        self.assertEqual(a.client.calls[-1], ("audio.stop", {"stream": "a3"}))


if __name__ == "__main__":
    unittest.main()


class BoutEnBoutTest(unittest.IsolatedAsyncioTestCase):
    """Vrai pont (registre audio) sur un socket, l'agent Linux et un « iPhone » simulé."""

    async def test_iphone_envoie_vers_le_pc(self):
        from ccs_app.remote import client
        from ccs_app.server import bridge, bridge_audio
        with tempfile.TemporaryDirectory() as d:
            sock = os.path.join(d, "b.sock")
            b = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
            bridge_audio.AudioApi(b)
            await b.start(sock)
            procs = []

            def popen(argv, **kw):
                procs.append(FakeProc(argv))
                return procs[-1]
            agent = audio.Agent(client.LocalTransport(sock, spawn=None), "pc-bureau", "100.64.0.2",
                                {"port": 4010, "label": "PC"}, pipewire=FakePw(), popen=popen)
            task = asyncio.ensure_future(agent.run())
            phone = client.BridgeClient(client.LocalTransport(sock, spawn=None), retry_delays=())
            events = []
            phone.on_event = lambda e, data: events.append(data)
            await phone.connect()
            await phone.call("audio.announce", device="iphone", ip="100.64.0.4", play=True,
                             capture=True, system="ios", label="iPhone")
            for _ in range(50):
                await asyncio.sleep(0.05)
                if len((await phone.call("audio.list"))["devices"]) == 2:
                    break
            r = await phone.call("audio.send", source="iphone", target="pc-bureau")
            for _ in range(50):
                await asyncio.sleep(0.05)
                if agent.receiver:
                    break
            self.assertEqual(agent.receiver[0], r["stream"])
            self.assertIn("udpsrc", procs[-1].argv)
            self.assertEqual([e["action"] for e in events], ["receive", "emit"])
            await phone.call("audio.stop", stream=r["stream"])
            for _ in range(50):
                await asyncio.sleep(0.05)
                if agent.receiver is None:
                    break
            self.assertIsNone(agent.receiver)
            agent.stop()
            await task
            self.assertEqual([x["device"] for x in (await phone.call("audio.list"))["devices"]], ["iphone"])
            await phone.close()
            await b.stop()


class PipewireTest(unittest.TestCase):
    def test_nom_affiche_entier(self):
        import subprocess
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        audio.Pipewire(run).create("iphone", "iPhone de Charles")
        self.assertEqual(calls[0][-1], """sink_properties='device.description="iPhone de Charles"'""")


class AutresSystemesTest(unittest.TestCase):
    def test_systeme(self):
        self.assertEqual(audio.this_system("Darwin"), "macos")
        self.assertEqual(audio.this_system("Windows"), "windows")
        self.assertEqual(audio.this_system("FreeBSD"), "autre")

    def test_pipelines(self):
        self.assertIn("autoaudiosink", audio.receiver_argv(4010, system="windows"))
        self.assertIn("wasapi2src", audio.sender_argv(None, "100.64.0.4", 4010, "windows"))
        self.assertIn("device=73", audio.sender_argv(None, "100.64.0.4", 4010, "macos", device="73"))
        with self.assertRaises(audio.AudioError):
            audio.sender_argv(None, "100.64.0.4", 4010, "macos")
        self.assertEqual(audio.missing_tools(lambda t: None, "windows"), ["gst-launch-1.0"])

    def test_agent_mac_sans_bouclage(self):
        a = audio.Agent(None, "mac", "100.64.0.8", {"port": 4010, "label": ""}, system="macos",
                        popen=lambda argv, **kw: FakeProc(argv))
        self.assertIsNone(a.pw)
        ann = a.announcement()
        self.assertEqual((ann["system"], ann["play"], ann["capture"]), ("macos", True, False))
        a.devices = {"iphone": {"device": "iphone", "label": "iPhone", "play": True}}
        a.sync_sinks()                                   # rien à faire, pas d'erreur
        a.on_event("audio", {"action": "emit", "device": "mac", "stream": "a1", "to": "iphone",
                             "ip": "100.64.0.4", "port": 4010})
        self.assertIsNone(a.sender)                       # ne sait pas capter : ignoré
        a.on_event("audio", {"action": "receive", "device": "mac", "stream": "a2"})
        self.assertIn("autoaudiosink", a.receiver[1].argv)
