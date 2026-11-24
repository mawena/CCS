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
        self.up = True

    def available(self):
        return self.up

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

    async def test_pipeline_mort_relance_puis_flux_arrete(self):
        a = self.agent
        a.on_event("audio", {"action": "receive", "device": "pc-bureau", "stream": "a5", "from": "iphone"})
        self.procs[-1].done = 1                             # gst-launch mort (sortie son partie…)
        await a.check_pipelines()
        self.assertEqual(len(self.procs), 2)                # relancé une fois
        self.assertEqual(a.receiver[0], "a5")
        self.assertIn("udpsrc", self.procs[-1].argv)
        self.assertEqual(a.client.calls, [])
        self.procs[-1].done = 1
        await a.check_pipelines()
        self.assertIsNone(a.receiver)                       # mort encore : flux arrêté au pont
        self.assertEqual(a.client.calls, [("audio.stop", {"stream": "a5"})])
        await a.check_pipelines()                           # plus rien à surveiller
        self.assertEqual(len(a.client.calls), 1)

    async def test_emetteur_mort_relance_vers_la_meme_cible(self):
        a = self.agent
        a.on_event("audio", {"action": "emit", "device": "pc-bureau", "stream": "a6", "to": "iphone",
                             "ip": "100.64.0.4", "port": 4010})
        self.procs[-1].done = 1
        await a.check_pipelines()
        self.assertEqual(a.sender[:2], ("a6", "iphone"))
        self.assertIn("host=100.64.0.4", self.procs[-1].argv)
        self.procs[-1].done = 1
        await a.check_pipelines()
        self.assertIsNone(a.sender)
        self.assertEqual(a.client.calls, [("audio.stop", {"stream": "a6"})])

    async def test_sans_serveur_de_son(self):
        a = self.agent
        self.pw.up = False
        self.assertFalse(a.detect_sound())
        ann = a.announcement()
        self.assertEqual((ann["play"], ann["capture"]), (False, False))
        a.sync_sinks()
        self.assertEqual(self.pw.created, [])               # pas de sorties virtuelles
        a.on_event("audio", {"action": "receive", "device": "pc-bureau", "stream": "a7"})
        a.on_event("audio", {"action": "emit", "device": "pc-bureau", "stream": "a8", "to": "iphone",
                             "ip": "100.64.0.4", "port": 4010})
        self.assertEqual((a.receiver, a.sender, self.procs), (None, None, []))
        self.pw.up = True                                   # PipeWire revenu (session ouverte)
        self.assertTrue(a.detect_sound())
        ann = a.announcement()
        self.assertEqual((ann["play"], ann["capture"]), (True, True))
        a.sync_sinks()
        self.assertEqual(self.pw.created, [("iphone", "iPhone")])

    async def test_annonce_relit_le_serveur_de_son(self):
        a = self.agent
        a.mpris = None
        self.pw.up = False
        seen = []

        class Client(FakeClient):
            async def call(self, method, **params):
                seen.append((method, params))
                return {"devices": [], "streams": []} if method == "audio.list" else {}
        a.client = Client()
        await a.announce()
        self.assertFalse(seen[0][1]["play"])


def faux_lecteur(nom="VLC", statut="Playing", volume=0.5, peut_avancer=True):
    root = {"Identity": nom}
    props = {"PlaybackStatus": statut, "Volume": volume, "Position": 12_000_000,
             "Metadata": {"xesam:title": "Titre", "xesam:artist": ["Artiste"], "mpris:length": 220_000_000},
             "CanPlay": True, "CanPause": True, "CanGoNext": True, "CanGoPrevious": False,
             "CanSeek": peut_avancer, "CanControl": True}
    return root, props


class FakeDbus:
    """Imite `_gio_call` : ListNames, GetAll, Get, Set et les méthodes du lecteur."""

    def __init__(self, lecteurs):
        self.lecteurs = lecteurs          # {nom de bus: (root, props)}
        self.appels = []

    def __call__(self, dest, path, iface, method, signature=None, args=()):
        self.appels.append((dest, method, tuple(args)))
        if method == "ListNames":
            return (["org.freedesktop.DBus", ":1.4", *self.lecteurs],)
        if dest not in self.lecteurs:
            raise audio.AudioError("lecteur parti")
        root, props = self.lecteurs[dest]
        if method == "GetAll":
            return (root if args[0] == audio.MPRIS_ROOT else props,)
        if method == "Get":
            return (props[args[1]],)
        return ()


class MprisTest(unittest.TestCase):
    def setUp(self):
        self.dbus = FakeDbus({"org.mpris.MediaPlayer2.vlc": faux_lecteur(),
                              "org.mpris.MediaPlayer2.firefox.instance_1_2":
                                  faux_lecteur("Firefox", "Paused", None, False)})
        self.m = audio.Mpris(call=self.dbus)

    def test_liste(self):
        ps = self.m.players()
        self.assertEqual(sorted(p["id"] for p in ps), ["firefox.instance_1_2", "vlc"])
        ps = sorted(ps, key=lambda p: p["id"] != "vlc")
        vlc = ps[0]
        self.assertEqual((vlc["name"], vlc["status"], vlc["title"], vlc["artist"]),
                         ("VLC", "Playing", "Titre", "Artiste"))
        self.assertEqual((vlc["position"], vlc["length"], vlc["volume"]), (12, 220, 50))
        self.assertFalse(vlc["can_prev"])
        self.assertIsNone(ps[1]["volume"])
        self.assertFalse(ps[1]["can_seek"])
        lignes = audio.describe_players(ps)
        self.assertTrue(any("VLC" in l and "0:12/3:40" in l for l in lignes))

    def test_lecteur_qui_plante_ignore(self):
        self.dbus.lecteurs["org.mpris.MediaPlayer2.mort"] = None
        real = self.dbus.__call__

        def call(dest, *a, **kw):
            if dest.endswith(".mort") and a[2] == "GetAll":
                raise audio.AudioError("ne répond pas")
            return real(dest, *a, **kw)
        self.assertEqual(len(audio.Mpris(call=call).players()), 2)

    def test_commandes(self):
        self.m.control("vlc", "toggle")
        self.m.control("vlc", "seek", "-10")
        self.m.control("vlc", "volume", 80)
        self.m.control("vlc", "volume", "+10")          # relatif : lit le volume (50) d'abord
        meth = [(m, a) for _, m, a in self.dbus.appels]
        self.assertEqual(meth[0], ("PlayPause", ()))
        self.assertEqual(meth[1], ("Seek", (-10_000_000,)))
        self.assertEqual(meth[2][0], "Set")
        self.assertAlmostEqual(meth[2][1][2][1], 0.8)
        self.assertEqual(meth[3][0], "Get")
        self.assertAlmostEqual(meth[4][1][2][1], 0.6)
        with self.assertRaises(audio.AudioError):
            self.m.control("vlc", "danse")

    def test_sans_bus(self):
        def call(*a, **kw):
            raise audio.AudioError("Pas de bus D-Bus de session")
        with self.assertRaises(audio.AudioError):
            audio.Mpris(call=call).players()


class ChoixLecteurTest(unittest.TestCase):
    def setUp(self):
        self.ps = [{"id": "vlc", "name": "VLC", "status": "Paused"},
                   {"id": "firefox.instance_1", "name": "Mozilla Firefox", "status": "Playing"},
                   {"id": "spotify", "name": "Spotify", "status": "Stopped"}]

    def ids(self, texte):
        return [p["id"] for p in audio.pick_players(self.ps, texte)]

    def test_choix(self):
        self.assertEqual(self.ids(None), ["firefox.instance_1"])     # celui qui joue
        self.assertEqual(self.ids("1"), ["vlc"])
        self.assertEqual(self.ids("vlc"), ["vlc"])
        self.assertEqual(self.ids("fire"), ["firefox.instance_1"])
        self.assertEqual(len(self.ids("toutes")), 3)
        for mauvais in ("4", "rien"):
            with self.assertRaises(audio.AudioError):
                self.ids(mauvais)
        with self.assertRaises(audio.AudioError):
            audio.pick_players([], None)

    def test_ambigu(self):
        self.ps[1]["status"] = "Paused"
        with self.assertRaises(audio.AudioError):
            self.ids(None)                         # deux en pause, aucun ne joue

    def test_analyse(self):
        self.assertEqual(audio.parse_control(["toggle"]), (None, "toggle", None))
        self.assertEqual(audio.parse_control(["vlc", "pause"]), ("vlc", "pause", None))
        self.assertEqual(audio.parse_control(["2", "seek", "-30"]), ("2", "seek", "-30"))
        self.assertEqual(audio.parse_control(["volume", "40"])[1:], ("volume", "40"))
        self.assertEqual(audio.parse_control(["suivant"])[1], "next")
        self.assertEqual(audio.parse_control(["vlc", "volume"]), ("vlc", "volume", None))
        for mauvais in (["vlc"], ["seek", "1", "2"]):
            with self.assertRaises(audio.AudioError):
                audio.parse_control(mauvais)

    def test_volume_et_saut(self):
        self.assertEqual(audio.volume_level("40", 10), 40)
        self.assertEqual(audio.volume_level("+20", 90), 100)
        self.assertEqual(audio.volume_level("-20", 10), 0)
        self.assertEqual(audio.seek_seconds(None), 10)
        self.assertEqual(audio.seek_seconds("-5"), -5)
        self.assertEqual(audio.volume_level("150"), 100)
        for mauvais in ("abc", None, "+5"):        # « +5 » sans volume actuel connu
            with self.assertRaises(audio.AudioError):
                audio.volume_level(mauvais)


class FakeMpris:
    def __init__(self):
        self.liste = [{"id": "vlc", "name": "VLC", "status": "Paused", "position": 3, "volume": 50}]
        self.ordres = []

    def players(self):
        return [dict(p) for p in self.liste]

    def control(self, pid, command, value=None, current=None):
        self.ordres.append((pid, command, value, current and current["volume"]))
        self.liste[0]["status"] = "Playing"


class AgentLecteursTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mpris = FakeMpris()
        self.agent = audio.Agent(None, "pc-bureau", "100.64.0.2", {"port": 4010, "label": ""},
                                 pipewire=FakePw(), popen=FakeProc, mpris=self.mpris)
        self.agent.client = FakeClient()

    def rapports(self):
        return [p for m, p in self.agent.client.calls if m == "audio.report"]

    async def test_rapport_seulement_si_change(self):
        a = self.agent
        await a.refresh_players()
        await a.refresh_players()
        self.assertEqual(len(self.rapports()), 1)
        self.mpris.liste[0]["position"] = 9        # la position seule ne compte pas
        await a.refresh_players()
        self.assertEqual(len(self.rapports()), 1)
        self.mpris.liste[0]["status"] = "Playing"
        await a.refresh_players()
        self.assertEqual(len(self.rapports()), 2)
        self.assertEqual(a.announcement()["players"][0]["status"], "Playing")

    async def test_commande_du_pont(self):
        a = self.agent
        await a.refresh_players()
        await a.control_player({"player": "vlc", "command": "volume", "value": "+10"})
        self.assertEqual(self.mpris.ordres, [("vlc", "volume", "+10", 50)])
        self.assertEqual(self.rapports()[-1]["players"][0]["status"], "Playing")
        await a.control_player({"player": None, "command": "play"})
        self.assertEqual(len(self.mpris.ordres), 1)

    async def test_evenement_pour_un_autre(self):
        self.agent.on_event("audio", {"action": "control", "device": "pixel", "player": "vlc",
                                      "command": "play"})
        await asyncio.sleep(0)
        self.assertEqual(self.mpris.ordres, [])


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


class EtatTest(unittest.TestCase):
    def run_ok(self, argv, **kw):
        import subprocess
        self.argvs.append(argv)
        if argv[:2] == ["systemctl", "--user"]:
            return subprocess.CompletedProcess(argv, 0, "active\n", "")
        if argv[:2] == ["pactl", "info"] and not self.up:
            return subprocess.CompletedProcess(argv, 1, "", "Connection refused")
        if argv[:2] == ["pactl", "list"]:
            out = "7\tmodule-null-sink\tsink_name=ccs_audio_iphone sink_properties=...\n" \
                if argv[-1] == "modules" else ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def setUp(self):
        self.argvs, self.up = [], True
        self.status = {"self": {"name": "pc-bureau", "ips": ["100.64.0.2"]}}

    def test_tout_va_bien(self):
        lines = audio.check({"active": True, "port": 4010, "label": "PC"}, which=lambda t: "/usr/bin/" + t,
                            system="linux", status=self.status, run=self.run_ok)
        text = "\n".join(lines)
        self.assertIn("actif (port UDP 4010, nom « PC »)", text)
        self.assertIn("pc-bureau (100.64.0.2)", text)
        self.assertIn("Serveur de son : présent", text)
        self.assertIn("ccs_audio_iphone", text)
        self.assertIn("ccs-audio.service : active", text)

    def test_serveur_sans_son(self):
        self.up = False
        lines = audio.check({"active": False, "port": 4010, "label": ""}, which=lambda t: None,
                            system="linux", status={}, run=self.run_ok)
        text = "\n".join(lines)
        self.assertIn("manque gst-launch-1.0, pactl", text)
        self.assertIn("Serveur de son : aucun", text)
        self.assertIn("pas dans le réseau maillé", text)
        self.assertFalse(any(a[0] == "systemctl" for a in self.argvs))   # inactif : pas demandé
        self.assertFalse(any(a[:2] == ["pactl", "info"] for a in self.argvs))  # pactl absent


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
