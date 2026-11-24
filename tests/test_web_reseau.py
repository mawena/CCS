"""Onglet Réseau de la version web (reseau.js), dans node avec le faux DOM de tests/web_dom.mjs."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccs_app.server import web

WEB = Path(web.WEB_DIR)
NODE = shutil.which("node")

PRELUDE = r"""
import { installDom, settle } from "./web_dom.mjs";
installDom();
const R = await import("./reseau.js");
let out = null;
"""


def run(body):
    tmp = Path(tempfile.mkdtemp(prefix="ccs-webnet-"))
    try:
        for p in WEB.glob("*.js"):
            shutil.copy(p, tmp / p.name)
        shutil.copy(Path(__file__).with_name("web_dom.mjs"), tmp / "web_dom.mjs")
        (tmp / "package.json").write_text('{"type": "module"}')
        script = tmp / "scenario.mjs"
        script.write_text(PRELUDE + body + "\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
        r = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60, cwd=tmp)
        if r.returncode:
            raise AssertionError(r.stderr[-1500:])
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node absent")
class ReseauWebTest(unittest.TestCase):
    def test_formats(self):
        out = run(r"""
out = {
  lan: R.addrKind("192.168.0.12:41641"), pub: R.addrKind("84.46.246.202:41641"),
  mesh: R.addrKind("100.64.0.2:41641"), v6: R.addrKind("[2a02:c207::1]:41641"),
  b: R.bytes(1536), kind: [R.deviceKind({os: "iOS", name: "iphone"}), R.deviceKind({os: "android", name: "x"}),
    R.deviceKind({os: "linux", name: "mawena-cloud"}), R.deviceKind({os: "linux", name: "pc-bureau"})],
  sum: R.summary({ self: {name: "a"}, peers: [{path: "lan", online: true}, {path: "relay", online: true}, {path: "offline", online: false}] }),
};
""")
        self.assertEqual(out["lan"]["kind"], "lan")
        self.assertEqual(out["pub"]["kind"], "public")
        self.assertEqual(out["mesh"]["kind"], "mesh")
        self.assertEqual(out["v6"], {"ip": "2a02:c207::1", "kind": "v6"})
        self.assertEqual(out["b"], "1,5 Ko")
        self.assertEqual(out["kind"], ["apple", "phone", "server", "desktop"])
        self.assertEqual(out["sum"], {"total": 4, "online": 3, "lan": 1, "direct": 0, "relay": 1})

    def test_page(self):
        out = run(r"""
const calls = [];
const status = { url: "https://network.mawena.cloud", domain: "mesh.mawena.cloud", installed: true, server: true,
  state: "Running", self: { name: "mawena-cloud", os: "linux", ips: ["100.64.0.1"], online: true, path: "self", addrs: [] },
  peers: [{ name: "pc-bureau", os: "linux", ips: ["100.64.0.2"], online: true, path: "lan",
            endpoint: "192.168.0.10:41641", addrs: ["192.168.0.10:41641", "41.1.2.3:41641"], rx: 2048, tx: 10 }],
  nodes: [{ name: "pixel", host: "pixel", ips: ["100.64.0.3"], online: false }] };
const api = { call: async (m, p) => { calls.push(m); if (m === "network.ping") return { ok: true, path: "lan", via: "192.168.0.10:41641", ms: 3 }; return status; } };
const root = document.createElement("div");
const stop = R.mountReseau(root, api);
await settle();
const cards = [...root.querySelectorAll(".net-card")];
const ping = cards[1].querySelector(".net-actions button");
ping.click();
await settle();
out = { calls, cards: cards.length, names: [...root.querySelectorAll(".net-card h3")].map((n) => n.textContent),
  text: root.textContent, tabs: root.querySelectorAll(".net-tab").length };
stop();
""")
        self.assertEqual(out["cards"], 3)
        self.assertEqual(out["names"], ["mawena-cloud", "pc-bureau", "pixel"])
        self.assertIn("network.ping", out["calls"])
        self.assertIn("3 ms", out["text"])
        self.assertIn("Réseau local", out["text"])
        self.assertEqual(out["tabs"], 3)

    def test_refresh_keeps_add_tab(self):
        # Le rafraîchissement ne doit ni ramener l'onglet sur « PC Linux » ni effacer la ligne générée.
        out = run(r"""
const status = { url: "https://network.mawena.cloud", installed: true, server: true, state: "Running",
  self: { name: "mawena-cloud", os: "linux", ips: ["100.64.0.1"], online: true, path: "self", addrs: [] }, peers: [], nodes: [] };
const api = { call: async (m) => m === "network.key" ? { linux: ["echo inscrire"] } : status };
const root = document.createElement("div");
const stop = R.mountReseau(root, api);
await settle();
root.querySelector(".net-tab-body .primary").click();
await settle();
const line = root.querySelector(".net-code") !== null;
root.querySelectorAll(".net-tab")[1].click();
document.dispatchEvent(new Event("visibilitychange"));
await settle();
out = { line, selected: [...root.querySelectorAll(".net-tab")].map((b) => b.getAttribute("aria-selected")) };
stop();
""")
        self.assertTrue(out["line"])
        self.assertEqual(out["selected"], ["false", "true", "false"])


if __name__ == "__main__":
    unittest.main()


SON_PRELUDE = r"""
import { installDom, settle } from "./web_dom.mjs";
installDom();
const S = await import("./son.js");
const R = await import("./reseau.js");
let out = null;
"""


@unittest.skipUnless(NODE, "node absent")
class SonTest(unittest.TestCase):
    def run_son(self, body):
        global PRELUDE
        old, PRELUDE = PRELUDE, SON_PRELUDE
        try:
            return run(body)
        finally:
            PRELUDE = old

    def test_choix_et_envoi(self):
        out = self.run_son(r"""
const devices = [
  { device: "iphone", label: "iPhone de Charles", ip: "100.64.0.4", play: true, capture: true, system: "ios" },
  { device: "pc-bureau", label: "PC du bureau", ip: "100.64.0.2", play: true, capture: true, system: "linux" },
  { device: "web", label: "Web", ip: "100.64.0.9", play: false, capture: false, system: "web" },
];
const calls = [];
const api = { call: async (m, p) => { calls.push([m, p]); return m === "audio.list"
  ? { devices, streams: [{ stream: "a1", source: "iphone", target: "pc-bureau" }] } : { stream: "a2" }; } };
const son = S.createSon(api, R.icon);
document.body.append(son.box);
const stop = son.start();
await settle();
const text = son.box.textContent;
const send = [...son.box.querySelectorAll("button")].find((b) => b.textContent.includes("Envoyer"));
send.click();
await settle();
stop();
out = { text, abilities: S.abilities(devices[2]), outs: S.choices(devices).outputs.length,
        sent: calls.find((c) => c[0] === "audio.send") };
""")
        self.assertIn("iPhone de Charles → PC du bureau", out["text"])
        self.assertIn("joue · capte", out["text"])
        self.assertEqual(out["abilities"], "—")
        self.assertEqual(out["outs"], 2)
        self.assertEqual(out["sent"][1], {"source": "iphone", "target": "pc-bureau"})

    def test_lecteurs(self):
        out = self.run_son(r"""
const vlc = { id: "vlc", name: "VLC", status: "Playing", title: "Titre", artist: "Artiste",
              volume: 40, can_seek: true, can_next: true, can_prev: false, can_play: true, can_pause: true };
const devices = [
  { device: "pc-bureau", label: "PC du bureau", ip: "100.64.0.2", play: true, capture: true, system: "linux", players: [vlc] },
  { device: "iphone", label: "iPhone", ip: "100.64.0.4", play: true, capture: false, system: "ios" },
];
const calls = [];
const api = { call: async (m, p) => { calls.push([m, p]); return m === "audio.list" ? { devices, streams: [] } : { ok: true }; } };
const root = document.createElement("div");
document.body.append(root);
// Comme app.js : le 3e argument est le contexte de la vue, pas une fonction pour les icônes.
const stop = S.mountSon(root, api, { user: "charles", banner: null, sub: null });
await settle();
const text = root.textContent;
const buttons = [...root.querySelectorAll("button")];
const by = (t) => buttons.find((b) => b.getAttribute("title") === t);
by("Pause").click();
by("Avancer de 10 s").click();
await settle();
const vol = root.querySelector("input");
vol.value = "70";
vol.dispatchEvent(new Event("change"));
await settle();
stop();
out = { text, prevDisabled: !!by("Précédent").disabled, ctl: calls.filter((c) => c[0] === "audio.control").map((c) => c[1]),
        sections: [...root.querySelectorAll("h2")].map((h) => h.textContent) };
""")
        self.assertIn("Artiste — Titre", out["text"])
        self.assertIn("PC du bureau", out["text"])
        self.assertEqual(out["sections"], ["Son partagé", "Lecteurs"])
        self.assertTrue(out["prevDisabled"])
        self.assertEqual(out["ctl"], [
            {"device": "pc-bureau", "player": "vlc", "command": "toggle"},
            {"device": "pc-bureau", "player": "vlc", "command": "seek", "value": 10},
            {"device": "pc-bureau", "player": "vlc", "command": "volume", "value": 70}])
