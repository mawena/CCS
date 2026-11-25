"""Version web : oreille de Jarvis (jarvis-ear.js, phase 36) — adresse d'appairage, rééchantillonnage
en 16 kHz, trames de son, voix PCM, appairage et refus avec un faux WebSocket, exécutés dans node."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccs_app.server import web

WEB = Path(web.WEB_DIR)
NODE = shutil.which("node")
FP = "A" * 42 + "Q"

PRELUDE = r"""
import { installDom } from "./web_dom.mjs";
installDom();
const print = process.stdout.write.bind(process.stdout);
globalThis.location = { protocol: "https:", host: "ccs.example" };
const sockets = [];
globalThis.WebSocket = class {
  static OPEN = 1;
  constructor(url) { this.url = url; this.sent = []; this.readyState = 0; sockets.push(this);
    setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0); }
  send(d) { this.sent.push(typeof d === "string" ? JSON.parse(d) : d); globalThis.brain?.(this, this.sent.at(-1)); }
  reply(m) { this.onmessage?.({ data: JSON.stringify(m) }); }
  close(code = 1000, reason = "") { this.readyState = 3; this.onclose?.({ code, reason }); }
};
const j = await import("./jarvis-ear.js");
let out = null;
"""


def run(body):
    tmp = Path(tempfile.mkdtemp(prefix="ccs-webjarvis-"))
    try:
        for p in WEB.glob("*.js"):
            shutil.copy(p, tmp / p.name)
        shutil.copy(Path(__file__).with_name("web_dom.mjs"), tmp / "web_dom.mjs")
        (tmp / "package.json").write_text('{"type": "module"}')
        script = tmp / "scenario.mjs"
        script.write_text(PRELUDE + body + "\nprint(JSON.stringify(out) + '\\n'); process.exit(0);\n", encoding="utf-8")
        r = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60, cwd=tmp)
        if r.returncode:
            raise AssertionError(r.stderr[-1500:])
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node absent")
class JarvisWebTest(unittest.TestCase):
    def test_pairing_uri(self):
        out = run(f"""
const ok = j.parsePairingUri(" jarvis://pair?v=1&id=abc&h=192.168.1.20&p=7341&fp={FP}&c=482913 ");
const errs = [];
for (const bad of ["https://x", "jarvis://pair?v=2&id=a&h=&p=1&fp={FP}&c=482913",
  "jarvis://pair?v=1&id=a&h=&p=1&fp=court&c=482913", "jarvis://pair?v=1&id=a&h=&p=1&fp={FP}&c=12",
  "jarvis://pair?v=1&v=1&id=a&h=&p=1&fp={FP}&c=482913"]) {{
  try {{ j.parsePairingUri(bad); errs.push(null); }} catch (e) {{ errs.push(e.message); }}
}}
out = {{ ok, errs }};
""")
        self.assertEqual(out["ok"], {"brainId": "abc", "port": 7341, "fingerprint": FP, "code": "482913"})
        self.assertTrue(all(out["errs"]), out["errs"])
        self.assertIn("jarvis://pair", out["errs"][0])

    def test_resampler_frames_and_pcm(self):
        out = run(r"""
const r = new j.Resampler(48000);
let n = 0, first = null;
for (let k = 0; k < 10; k++) {
  const s = r.push(new Float32Array(480).fill(0.5));
  n += s.length; first ??= s[0];
}
const frame = new Uint8Array(j.micFrame(0x01020304, Int16Array.from([1, -1, 32767])));
const pcm = Array.from(j.decodePcm(btoa(String.fromCharCode(0, 0, 0xe8, 0x03, 0x18, 0xfc))));
out = { n, first, frame: Array.from(frame), pcm };
""")
        self.assertEqual(out["n"], 1600)            # 100 ms à 48 kHz → 1 600 échantillons à 16 kHz
        self.assertEqual(out["first"], 16384)
        self.assertEqual(out["frame"], [1, 4, 3, 2, 1, 1, 0, 255, 255, 255, 127])
        self.assertEqual(out["pcm"], [0, 1000, -1000])

    def test_pair_saves_the_token_and_hello_reuses_it(self):
        out = run(f"""
globalThis.brain = (ws, m) => {{
  if (m.type === "pair") setTimeout(() => {{ ws.reply({{ type: "paired", ear_id: "e1", token: "t1", brain_id: "b", brain_name: "Maison" }}); ws.close(); }}, 0);
  if (m.type === "hello") setTimeout(() => ws.reply({{ type: "welcome", version: 1, brain_name: "Maison" }}), 0);
}};
const p = await j.pair({{ code: "482913", fingerprint: "{FP}", name: "essai" }});
const stored = j.loadPairing();
const ear = new j.Ear(stored);
await ear.connect();
out = {{ p, stored, urls: sockets.map((s) => s.url), sent: sockets.map((s) => s.sent[0]) }};
""")
        self.assertEqual(out["stored"]["token"], "t1")
        self.assertEqual(out["stored"]["fingerprint"], FP)
        self.assertEqual(out["urls"][0], f"wss://ccs.example/api/jarvis/oreille?fp={FP}")
        self.assertEqual(out["sent"][0], {"type": "pair", "version": 1, "code": "482913", "name": "essai",
                                          "platform": "web"})
        self.assertEqual(out["sent"][1], {"type": "hello", "version": 1, "ear_id": "e1", "token": "t1"})

    def test_relay_error_and_rejection_are_readable(self):
        out = run(f"""
const msgs = [];
globalThis.brain = (ws, m) => setTimeout(() => {{
  if (m.code === "000000") ws.reply({{ type: "rejected", reason: {{ kind: "wrong_code", attempts_left: 2 }} }});
  else {{ ws.reply({{ type: "relay_error", message: "Jarvis est injoignable (lp-home:7341) : hors ligne." }}); ws.close(4011, "x"); }}
}}, 0);
for (const code of ["000000", "111111"]) {{
  try {{ await j.pair({{ code, fingerprint: "{FP}" }}); }} catch (e) {{ msgs.push(e.message); }}
}}
out = {{ msgs, stored: j.loadPairing() }};
""")
        self.assertEqual(out["msgs"][0], "Code d'appairage faux. Essais restants : 2.")
        self.assertIn("injoignable", out["msgs"][1])
        self.assertIsNone(out["stored"])

    def test_page_shows_pairing_then_the_button(self):
        out = run(f"""
const {{ mountJarvis }} = await import("./jarvis.js");
const calls = [];
const api = {{ call: async (m, p) => {{ calls.push(m); return {{ machine: "lp-home", port: 7341, fingerprint: "", fingerprint_short: "" }}; }} }};
const root = document.createElement("div");
let stop = mountJarvis(root, api);
const before = root.textContent;
stop();
localStorage.setItem("ccs.jarvis", JSON.stringify({{ earId: "e1", token: "t1", fingerprint: "{FP}", brainName: "Maison" }}));
const root2 = document.createElement("div");
stop = mountJarvis(root2, api);
const after = root2.textContent;
stop();
out = {{ before, after, calls }};
""")
        self.assertIn("Appairer ce navigateur", out["before"])
        self.assertIn("Parler à Jarvis", out["after"])
        self.assertIn("Maison", out["after"])
        self.assertIn("jarvis.settings", out["calls"])

    def test_page_is_wired(self):
        views = (WEB / "views.js").read_text(encoding="utf-8")
        self.assertIn("jarvis: {", views)
        page = (WEB / "jarvis.js").read_text(encoding="utf-8")
        self.assertIn('"jarvis.settings"', page)
        ear = (WEB / "jarvis-ear.js").read_text(encoding="utf-8")
        self.assertIn('score: 2.0', ear)
        self.assertIn('"/jarvis-worklet.js"', ear)


if __name__ == "__main__":
    unittest.main()
