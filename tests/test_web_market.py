"""Version web : onglet Market (market.js, phase 45), exécuté dans node avec un faux DOM. L'onglet
ouvre le chat Market par `market.open` et y monte une vue de chat ; une erreur se montre avec
« Réessayer »."""

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
globalThis.location = { hash: "#/market" };
const { mountMarket } = await import("./market.js");
const calls = [];
const api = {
  fail: false,
  on() { return () => {}; },
  async call(method, params) {
    calls.push(method);
    if (method === "market.open") {
      if (api.fail) throw new Error("Pont injoignable.");
      return { chat_id: "c9", cwd: "/home/x/.local/share/ccs/market", title: "Market", seq: 0, state: "starting", session_id: null, path: null };
    }
    if (method === "chat.attach") return { seq: 0, events: [], state: "idle", options: { model: "", effort: "", rights: "manual" } };
    if (method === "work.commands") return { commands: [], context: {} };
    if (method === "work.files") return { files: [] };
    return {};
  },
};
const root = document.createElement("div");
document.body.append(root);
let out = null;
"""


def run(body):
    tmp = Path(tempfile.mkdtemp(prefix="ccs-webmarket-"))
    try:
        for p in WEB.glob("*.js"):
            shutil.copy(p, tmp / p.name)
        shutil.copy(Path(__file__).with_name("web_dom.mjs"), tmp / "web_dom.mjs")
        (tmp / "package.json").write_text('{"type": "module"}')
        script = tmp / "scenario.mjs"
        script.write_text(PRELUDE + body + "\nconsole.log(JSON.stringify(out)); process.exit(0);\n", encoding="utf-8")
        r = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60, cwd=tmp)
        if r.returncode:
            raise AssertionError(r.stderr[-1500:])
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class MarketStaticTest(unittest.TestCase):
    def test_tab_registered(self):
        views = (WEB / "views.js").read_text(encoding="utf-8")
        self.assertIn('market: { title: "Market"', views)
        self.assertIn("/market.js", (WEB / "sw.js").read_text(encoding="utf-8"))
        self.assertIn('"market.open"', (WEB / "market.js").read_text(encoding="utf-8"))


@unittest.skipUnless(NODE, "node absent")
class MarketWebTest(unittest.TestCase):
    def test_opens_the_market_chat(self):
        out = run("""
const cleanup = mountMarket(root, api);
await settle(); await settle();
out = { calls, chat: root.querySelectorAll(".chat").length, hint: root.textContent.includes("Facebook Marketplace") };
cleanup();
""")
        self.assertEqual(out["calls"][0], "market.open")
        self.assertIn("chat.attach", out["calls"])
        self.assertEqual(out["chat"], 1)
        self.assertTrue(out["hint"])

    def test_error_then_retry(self):
        out = run("""
api.fail = true;
mountMarket(root, api);
await settle(); await settle();
const err = root.textContent.includes("Pont injoignable.");
api.fail = false;
root.querySelectorAll("button").find((b) => b.textContent.includes("Réessayer")).click();
await settle(); await settle();
out = { err, chat: root.querySelectorAll(".chat").length };
""")
        self.assertTrue(out["err"])
        self.assertEqual(out["chat"], 1)


if __name__ == "__main__":
    unittest.main()
