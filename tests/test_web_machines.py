"""Version web : choix de la machine pilotée (api.js, machines.js), exécuté dans node avec le
faux DOM de tests/web_dom.mjs et un faux WebSocket."""

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
const win = installDom();
globalThis.location = { protocol: "https:", host: "ccs.exemple" };
const sockets = [];
class FakeWS {
  static OPEN = 1;
  constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
  send(m) { this.sent.push(JSON.parse(m)); }
  close() { this.readyState = 3; this.onclose?.({ code: 1000 }); }
  open() { this.readyState = 1; this.onopen?.(); }
  reply(id, result) { this.onmessage?.({ data: JSON.stringify({ id, result }) }); }
}
globalThis.WebSocket = FakeWS;
globalThis.fetch = async () => ({ ok: true, json: async () => ({ user: "alice" }) });
const { Api } = await import("./api.js");
const { machineSheet, pickMachine, machineName } = await import("./machines.js");
let out = null;
"""


def run(body):
    tmp = Path(tempfile.mkdtemp(prefix="ccs-webmach-"))
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
class MachineWebTest(unittest.TestCase):
    def test_switching_machine_reconnects_with_the_machine_and_rejects_old_calls(self):
        out = run(r"""
const api = new Api();
const seen = [];
api.on("machine", (m) => seen.push(m));
api.connect(); sockets[0].open();
const old = api.call("chat.list").catch((e) => "rejeté:" + e.code);
pickMachine(api, "pc-bureau", "PC du bureau");
sockets[1].open();
const fresh = api.call("chat.list");
sockets[1].reply(sockets[1].sent[0].id, { chats: [1] });
out = { urls: sockets.map((s) => s.url), old: await old, fresh: await fresh,
        seen: [...seen], stored: localStorage.getItem("ccs.machine"), name: machineName(api),
        again: new Api().machine };
pickMachine(api, "", "");
out.back = sockets[2].url; out.nameBack = machineName(api);
""")
        self.assertEqual(out["urls"], ["wss://ccs.exemple/api/ws",
                                       "wss://ccs.exemple/api/ws?machine=pc-bureau"])
        self.assertEqual(out["old"], "rejeté:hors_ligne")
        self.assertEqual(out["fresh"], {"chats": [1]})
        self.assertEqual(out["seen"], ["pc-bureau"])
        self.assertEqual(out["stored"], "pc-bureau")
        self.assertEqual(out["name"], "PC du bureau")
        self.assertEqual(out["again"], "pc-bureau")          # gardé après un rechargement
        self.assertEqual(out["back"], "wss://ccs.exemple/api/ws")
        self.assertEqual(out["nameBack"], "Ce serveur")

    def test_machine_down_is_reported_with_its_reason(self):
        out = run(r"""
const api = new Api();
api.machine = "pc-bureau";
const got = [];
api.on("machine-down", (d) => got.push(d));
api.on("offline", () => got.push("offline"));
api.connect(); sockets[0].onclose({ code: 4010, reason: "pc-bureau est hors ligne." });
api.close();
out = got;
""")
        self.assertEqual(out, [{"machine": "pc-bureau", "reason": "pc-bureau est hors ligne."}])

    def test_sheet_lists_other_machines_and_picks_one(self):
        out = run(r"""
const api = { machine: "", async call(m) {
  return { machines: [
    { id: "vps", name: "VPS", online: true, local: true, tunnel: true },
    { id: "pc-bureau", name: "PC du bureau", online: true, local: false, tunnel: true, cores: 14, load: 1.9 },
    { id: "portable", name: "Portable", online: false, local: false, tunnel: true }] }; } };
let picked = null;
const dlg = machineSheet(api, (id, name) => { picked = [id, name]; });
await settle();
const items = dlg.querySelectorAll(".machine-item");
out = { labels: items.map((b) => b.textContent), disabled: items.map((b) => b.hasAttribute("disabled")) };
items[1].click();
out.picked = picked; out.closed = !dlg.open;
out.cached = JSON.parse(localStorage.getItem("ccs.machines")).map((m) => m.id);
""")
        self.assertEqual(len(out["labels"]), 3)                # ce serveur, pc-bureau, portable
        self.assertIn("Ce serveur", out["labels"][0])
        self.assertIn("charge 1.9 sur 14 cœurs", out["labels"][1])
        self.assertIn("hors ligne", out["labels"][2])
        self.assertEqual(out["disabled"], [False, False, True])
        self.assertEqual(out["picked"], ["pc-bureau", "PC du bureau"])
        self.assertTrue(out["closed"])
        self.assertEqual(out["cached"], ["pc-bureau", "portable"])


if __name__ == "__main__":
    unittest.main()
