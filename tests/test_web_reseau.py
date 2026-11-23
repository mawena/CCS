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
