import unittest

from ccs_app.server import bridge_audio, rpc


class FakeBridge:
    def __init__(self):
        self.handlers = {}
        self.tick_hooks = []
        self.events = []

    def add_handlers(self, h):
        self.handlers.update(h)

    async def broadcast(self, event, data):
        self.events.append((event, data))


class AudioApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000.0
        self.b = FakeBridge()
        self.api = bridge_audio.AudioApi(self.b, clock=lambda: self.now)

    async def call(self, method, **params):
        return await self.b.handlers[method](None, params)

    async def annonce(self, device, ip, play=True, capture=True, **kw):
        return await self.call("audio.announce", device=device, ip=ip, play=play, capture=capture, **kw)

    async def test_annonce_et_liste(self):
        r = await self.annonce("pc-bureau", "100.64.0.2", label="PC du bureau", system="linux")
        self.assertEqual(r["every"], 30)
        await self.annonce("iphone", "100.64.0.4", capture=False, system="ios")
        devs = (await self.call("audio.list"))["devices"]
        self.assertEqual([d["device"] for d in devs], ["iphone", "pc-bureau"])
        self.assertEqual(devs[1]["label"], "PC du bureau")
        self.assertEqual(devs[0]["port"], 4010)
        self.assertFalse(devs[0]["capture"])
        self.assertEqual(self.b.tick_hooks, [self.api.sweep])

    async def test_annonce_invalide(self):
        for params in ({"device": "x", "ip": "pas-une-ip"}, {"device": "../x", "ip": "100.64.0.2"},
                       {"device": "x", "ip": "100.64.0.2", "port": 80},
                       {"device": "x", "ip": "100.64.0.2", "port": True}):
            with self.assertRaises(rpc.RpcError):
                await self.call("audio.announce", **params)

    async def test_oubli_apres_90_s(self):
        await self.annonce("pixel", "100.64.0.3")
        self.now += 91
        self.assertEqual((await self.call("audio.list"))["devices"], [])

    async def test_envoi_previent_cible_puis_source(self):
        await self.annonce("pc-bureau", "100.64.0.2")
        await self.annonce("iphone", "100.64.0.4", port=4012)
        r = await self.call("audio.send", source="pc-bureau", target="iphone")
        self.assertEqual((r["ip"], r["port"], r["codec"]), ("100.64.0.4", 4012, "opus"))
        (e1, recv), (e2, emit) = self.b.events
        self.assertEqual((e1, recv["action"], recv["device"], recv["from_ip"]),
                         ("audio", "receive", "iphone", "100.64.0.2"))
        self.assertEqual((e2, emit["action"], emit["device"], emit["ip"], emit["port"]),
                         ("audio", "emit", "pc-bureau", "100.64.0.4", 4012))
        self.assertEqual(recv["stream"], emit["stream"])
        self.assertEqual(len((await self.call("audio.list"))["streams"]), 1)

    async def test_envoi_refuse(self):
        await self.annonce("iphone", "100.64.0.4", capture=False)
        await self.annonce("pixel", "100.64.0.3", play=False)
        with self.assertRaises(rpc.RpcError):
            await self.call("audio.send", source="iphone", target="pixel")      # iphone ne capte pas
        with self.assertRaises(rpc.RpcError):
            await self.call("audio.send", source="pixel", target="pixel")
        with self.assertRaises(rpc.RpcError) as ctx:
            await self.call("audio.send", source="pixel", target="absent")
        self.assertEqual(ctx.exception.code, "introuvable")

    async def test_un_flux_par_sortie(self):
        for d, ip in (("a", "100.64.0.2"), ("b", "100.64.0.3"), ("c", "100.64.0.4")):
            await self.annonce(d, ip)
        first = (await self.call("audio.send", source="a", target="c"))["stream"]
        await self.call("audio.send", source="b", target="c")
        stops = [e for _, e in self.b.events if e["action"] == "stop"]
        self.assertEqual([(s["stream"], s["reason"]) for s in stops], [(first, "remplacé")])
        self.assertEqual([s["source"] for s in (await self.call("audio.list"))["streams"]], ["b"])

    async def test_arret_par_flux_ou_appareil(self):
        await self.annonce("a", "100.64.0.2")
        await self.annonce("b", "100.64.0.3")
        sid = (await self.call("audio.send", source="a", target="b"))["stream"]
        self.assertEqual((await self.call("audio.stop", device="b"))["stopped"], [sid])
        with self.assertRaises(rpc.RpcError):
            await self.call("audio.stop", stream=sid)
        self.assertEqual(self.b.events[-1][1]["devices"], ["a", "b"])

    async def test_appareil_muet_arrete_ses_flux(self):
        await self.annonce("a", "100.64.0.2")
        await self.annonce("b", "100.64.0.3")
        await self.call("audio.send", source="a", target="b")
        self.now += 60
        await self.annonce("a", "100.64.0.2")
        self.now += 40
        await self.api.sweep()
        self.assertEqual(self.b.events[-1][1]["action"], "stop")
        self.assertEqual([d["device"] for d in (await self.call("audio.list"))["devices"]], ["a"])

    async def test_annonce_rend_les_flux_en_cours(self):
        await self.annonce("a", "100.64.0.2")
        await self.annonce("b", "100.64.0.3")
        await self.call("audio.send", source="a", target="b")
        self.assertEqual(len((await self.annonce("b", "100.64.0.3"))["streams"]), 1)

    async def test_oublier(self):
        await self.annonce("a", "100.64.0.2")
        await self.annonce("b", "100.64.0.3")
        await self.call("audio.send", source="a", target="b")
        await self.call("audio.forget", device="a")
        self.assertEqual((await self.call("audio.list"))["streams"], [])


if __name__ == "__main__":
    unittest.main()
