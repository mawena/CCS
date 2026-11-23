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
        script.write_text(PRELUDE + body + "\nconsole.log(JSON.stringify(out));\nprocess.exit(0);\n", encoding="utf-8")
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
        self.assertEqual(out["urls"], ["wss://ccs.exemple/api/ws?protocol=1",
                                       "wss://ccs.exemple/api/ws?protocol=1&machine=pc-bureau"])
        self.assertEqual(out["old"], "rejeté:hors_ligne")
        self.assertEqual(out["fresh"], {"chats": [1]})
        self.assertEqual(out["seen"], ["pc-bureau"])
        self.assertEqual(out["stored"], "pc-bureau")
        self.assertEqual(out["name"], "PC du bureau")
        self.assertEqual(out["again"], "pc-bureau")          # gardé après un rechargement
        self.assertEqual(out["back"], "wss://ccs.exemple/api/ws?protocol=1")
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


PAGE = r"""
const intervals = [];
const realSetInterval = globalThis.setInterval;
globalThis.setInterval = (fn, ms) => { intervals.push({ fn, ms, on: true }); return intervals.length; };
globalThis.clearInterval = (id) => { if (intervals[id - 1]) intervals[id - 1].on = false; };
const { mountReseau } = await import("./reseau.js");
const mountMachines = mountReseau;
const NET = { url: "https://network.mawena.cloud", domain: "mesh.mawena.cloud", installed: true, server: true, state: "Running",
  self: { name: "mawena-cloud", os: "linux", ips: ["100.64.0.1"], online: true, path: "self", addrs: [] },
  peers: [{ name: "lp-work", host: "lp-work", os: "linux", ips: ["100.64.0.2"], online: true, path: "lan", addrs: [] }],
  nodes: [] };
const MACHINES = { configured: true, message: "", machines: [
  { id: "vps", name: "VPS", online: true, local: true, cores: 6, load: 1.2, mem_used: 4 * 2 ** 30, mem_total: 11 * 2 ** 30,
    tunnel: true, tools: ["python3"], limit: 2, running: 0, waiting: 0 },
  { id: "pc-bureau", name: "PC du bureau", online: true, local: false, cores: 14, load: 7, mem_used: 2 ** 33, mem_total: 2 ** 35,
    tunnel: true, tools: ["flutter", "gradle"], limit: 2, running: 1, waiting: 1, mesh: "", mesh_ip: "100.64.0.2", host: "pc-bureau" },
  { id: "portable", name: "Portable", online: false, local: false, cores: 0, load: 0, mem_used: 0, mem_total: 0,
    tunnel: true, tools: [], limit: 3, running: 0, waiting: 0 }] };
const now = Date.now() / 1000;
const JOBS = { jobs: [
  { id: "a1", text: "flutter build apk", command: ["flutter", "build", "apk"], cwd: "/home/u/App", machine: "pc-bureau",
    state: "running", code: null, created: now - 100, started: now - 75, ended: null, why: "" },
  { id: "b2", text: "make test", command: ["make", "test"], cwd: "/home/u/App", machine: null,
    state: "waiting", code: null, created: now - 30, started: null, ended: null, why: "en attente d'une place sur pc-bureau (2/2)" },
  { id: "c3", text: "make deb", command: ["make", "deb"], cwd: "/home/u/App", machine: "pc-bureau",
    state: "failed", code: 2, created: now - 900, started: now - 800, ended: now - 790, why: "" }] };
const SETTINGS = { relay: "https://ricochet.exemple", token_set: true, path: "/home/u/.config/ricochet/client.toml",
  default_limit: 2, limits: { "pc-bureau": 3 } };
function fakeApi(machine = "") {
  const calls = [];
  return { machine, calls, on: () => () => {}, async call(m, p = {}) {
    calls.push([m, p]);
    if (m === "network.status") return NET;
    if (m === "machines.list") return MACHINES;
    if (m === "machines.jobs") return JOBS;
    if (m === "machines.settings") return SETTINGS;
    if (m === "machines.log") return { text: "ligne 1\nligne 2" };
    if (m === "files.roots") return { home: "/home/u", roots: ["/home/u"] };
    if (m === "projects.list") return { entries: [{ cwd: "/home/u/App", exists: true }] };
    if (m === "machines.start") return { id: "d4" };
    if (m === "machines.add") return { id: p.machine, command: "curl -fsSL https://r/rejoindre/x | sudo sh", expires_s: 900 };
    return { ok: true };
  } };
}
const root = document.createElement("div");
document.body.append(root);
const text = (sel) => root.querySelectorAll(sel).map((n) => n.textContent);
const button = (label, scope = root) => scope.querySelectorAll("button").find((b) => b.textContent === label);
"""


@unittest.skipUnless(NODE, "node absent")
class MachinesPageWebTest(unittest.TestCase):
    def test_lists_machines_with_load_places_tools_and_jobs(self):
        out = run(PAGE + r"""
const api = fakeApi();
const stop = mountMachines(root, api);
await settle();
out = { cards: text(".net-card"), blocks: root.querySelectorAll(".net-compute").length, jobs: text(".job"), h3: text(".stack h3"), note: text(".machines-note"),
        stops: root.querySelectorAll(".job").map((j) => Boolean(button("Arrêter", j))),
        targets: root.querySelectorAll('select[aria-label="Machine"] option').map((o) => o.textContent),
        intervals: intervals.map((i) => i.ms) };
// rechargement toutes les 5 s, seulement page visible, et plus après la sortie de la page
api.calls.length = 0;
document.hidden = true; intervals[0].fn(); await settle();
out.hiddenCalls = api.calls.length;
document.hidden = false; intervals[0].fn(); await settle();
out.visibleCalls = api.calls.map((c) => c[0]);
stop();
out.stopped = !intervals[0].on;
""")
        self.assertEqual(len(out["cards"]), 3)               # serveur, lp-work (= pc-bureau), portable (Ricochet seul)
        self.assertEqual(out["blocks"], 3)
        self.assertIn("Serveur CCS", out["cards"][0])
        self.assertIn("PC du bureau", out["cards"][1])          # rattaché par son adresse du réseau maillé
        self.assertIn("0,50/cœur", out["cards"][1])             # 7 sur 14 cœurs
        self.assertIn("8,0/32 Go", out["cards"][1])
        self.assertIn("flutter", out["cards"][1])
        self.assertIn("Places : 1/2 · 1 en attente", out["cards"][1])
        self.assertIn("Hors ligne", out["cards"][2])
        self.assertIn("outils pas encore inventoriés", out["cards"][2])
        self.assertEqual(out["h3"], ["En cours et à venir (2)", "Finis (1)"])
        self.assertIn("1 min 15 s", out["jobs"][0])
        self.assertIn("en attente d'une place sur pc-bureau (2/2)", out["jobs"][1])
        self.assertIn("code 2", out["jobs"][2])
        self.assertEqual(out["stops"], [True, True, False])
        self.assertEqual(out["note"], [])
        self.assertEqual(out["targets"], ["La moins chargée", "VPS", "PC du bureau", "Portable (hors ligne)"])
        self.assertEqual(out["intervals"], [5000])
        self.assertEqual(out["hiddenCalls"], 0)
        self.assertEqual(sorted(out["visibleCalls"]), ["machines.jobs", "machines.list"])
        self.assertTrue(out["stopped"])

    def test_note_when_driving_another_machine(self):
        out = run(PAGE + r"""
localStorage.setItem("ccs.machine.name", "PC du bureau");
const api = fakeApi("pc-bureau");
mountMachines(root, api);
await settle();
out = { note: text(".machines-note"), folder: root.querySelector('input[aria-label="Dossier"]').value,
        methods: [...new Set(api.calls.map((c) => c[0]))] };
""")
        self.assertEqual(len(out["note"]), 1)
        self.assertIn("vus depuis le serveur CCS", out["note"][0])
        self.assertEqual(out["folder"], "/home/u")              # tiré du chemin du relais, pas de files.roots
        self.assertNotIn("files.roots", out["methods"])         # relayé à la machine pilotée : pas utilisé
        self.assertNotIn("projects.list", out["methods"])

    def test_stop_asks_confirmation_then_calls_bridge(self):
        out = run(PAGE + r"""
const api = fakeApi();
mountMachines(root, api);
await settle();
button("Arrêter", root.querySelectorAll(".job")[0]).click();
await settle();
let dlg = document.body.querySelectorAll("dialog").pop();
out = { title: dlg.querySelector("h2").textContent };
button("Garder", dlg).click(); await settle();
out.afterCancel = api.calls.filter((c) => c[0] === "machines.stop").length;
button("Arrêter", root.querySelectorAll(".job")[0]).click(); await settle();
dlg = document.body.querySelectorAll("dialog").pop();
button("Arrêter", dlg).click(); await settle();
out.stop = api.calls.filter((c) => c[0] === "machines.stop").map((c) => c[1]);
""")
        self.assertEqual(out["title"], "Arrêter ce travail ?")
        self.assertEqual(out["afterCancel"], 0)
        self.assertEqual(out["stop"], [{"id": "a1"}])

    def test_log_sheet_reloads_while_open(self):
        out = run(PAGE + r"""
const api = fakeApi();
mountMachines(root, api);
await settle();
button("Journal", root.querySelectorAll(".job")[0]).click();
await settle();
const dlg = document.body.querySelectorAll("dialog").pop();
const logTimer = intervals.find((i) => i.ms === 3000);
out = { log: dlg.querySelector("pre").textContent };
logTimer.fn(); await settle();
out.calls = api.calls.filter((c) => c[0] === "machines.log").map((c) => c[1]);
button("Fermer", dlg).click();
out.stopped = !logTimer.on;
""")
        self.assertEqual(out["log"], "ligne 1\nligne 2")
        self.assertEqual(out["calls"], [{"id": "a1", "tail": 20000}] * 2)
        self.assertTrue(out["stopped"])

    def test_launch_form_defaults_to_last_project_and_sends_contract_params(self):
        out = run(PAGE + r"""
localStorage.setItem("ccs.project.last", JSON.stringify({ machine: "", cwd: "/home/u/App" }));
const api = fakeApi();
mountMachines(root, api);
await settle();
const q = (l) => root.querySelector(`[aria-label="${l}"]`);
out = { folder: q("Dossier").value };
button("Lancer").click(); await settle();
out.empty = root.querySelector("form .form-error").textContent;
q("Commande").value = "flutter build apk";
q("Quand").value = "nuit"; q("Quand").dispatchEvent(new Event("change"));
button("Lancer").click(); await settle();
q("Commande").value = "make";
q("Dossier").value = "~/Autre";
q("Machine").value = "pc-bureau";
q("Quand").value = "heure"; q("Quand").dispatchEvent(new Event("change"));
q("Heure").value = "22:30";
button("Lancer").click(); await settle();
out.starts = api.calls.filter((c) => c[0] === "machines.start").map((c) => c[1]);
""")
        self.assertEqual(out["folder"], "/home/u/App")
        self.assertEqual(out["empty"], "Écris la commande à lancer.")
        self.assertEqual(out["starts"], [
            {"command": "flutter build apk", "cwd": "/home/u/App", "when": "nuit"},
            {"command": "make", "cwd": "/home/u/Autre", "when": "22:30", "machine": "pc-bureau"}])

    def test_folder_falls_back_to_home_and_limit_is_saved(self):
        out = run(PAGE + r"""
localStorage.setItem("ccs.project.last", JSON.stringify({ machine: "pc-bureau", cwd: "/ailleurs" }));
const api = fakeApi();
mountMachines(root, api);
await settle();
const sel = root.querySelectorAll(".net-compute")[1].querySelector("select");
out = { folder: root.querySelector('[aria-label="Dossier"]').value, limit: sel.value };
sel.value = "3"; sel.dispatchEvent(new Event("change")); await settle();
out.calls = api.calls.filter((c) => c[0] === "machines.limit").map((c) => c[1]);
""")
        self.assertEqual(out["folder"], "/home/u")              # projet d'une autre machine : ignoré
        self.assertEqual(out["limit"], "2")
        self.assertEqual(out["calls"], [{"machine": "pc-bureau", "limit": 3}])

    def test_relay_settings_never_show_the_token(self):
        out = run(PAGE + r"""
const api = fakeApi();
mountMachines(root, api);
await settle();
const pw = root.querySelector('input[type="password"]');
const relay = pw.closest("form");
out = { pw: pw.value, status: relay.querySelector('[data-role="token-status"]').textContent,
        address: relay.querySelector('input[type="url"]').value };
pw.value = "secret-123";
button("Enregistrer", relay).click(); await settle();
out.calls = api.calls.filter((c) => c[0] === "machines.configure").map((c) => c[1]);
out.after = root.querySelector('input[type="password"]').value;
""")
        self.assertEqual(out["pw"], "")
        self.assertEqual(out["status"], "Jeton enregistré.")
        self.assertEqual(out["address"], "https://ricochet.exemple")
        self.assertEqual(out["calls"], [{"token": "secret-123"}])
        self.assertEqual(out["after"], "")

    def test_add_a_pc_needs_the_operator_token(self):
        out = run(PAGE + r"""
mountMachines(root, fakeApi());
await settle();
out = root.querySelectorAll("section").find((n) => n.getAttribute("aria-label") === "Ajouter un appareil").textContent;
""")
        self.assertIn("Créer la ligne d'inscription", out)    # sans jeton opérateur : clé du réseau maillé

    def test_add_a_pc_gives_the_command(self):
        out = run(PAGE + r"""
SETTINGS.operator_set = true;
const api = fakeApi();
mountMachines(root, api);
await settle();
const box = root.querySelectorAll("section").find((n) => n.getAttribute("aria-label") === "Ajouter un appareil");
const inputs = box.querySelectorAll("input");
inputs[0].value = "pc-salon"; inputs[1].value = "charles";
button("Créer le lien", box).click(); await settle();
out = { calls: api.calls.filter((c) => c[0] === "machines.add").map((c) => c[1]),
        pre: box.querySelector("pre").textContent, id: inputs[0].value };
""")
        self.assertEqual(out["calls"], [{"machine": "pc-salon", "user": "charles"}])
        self.assertEqual(out["pre"], "curl -fsSL https://r/rejoindre/x | sudo sh")
        self.assertEqual(out["id"], "")

    def test_old_page_now_lives_in_the_network_tab(self):
        views = (WEB / "views.js").read_text(encoding="utf-8")
        self.assertNotIn("machines:", views)
        self.assertIn('if (name === "machines") name = "reseau";', (WEB / "app.js").read_text(encoding="utf-8"))
        self.assertIn('"#/reseau"', (WEB / "machines.js").read_text(encoding="utf-8"))
        self.assertNotIn("#/machines", (WEB / "settings.js").read_text(encoding="utf-8"))
        self.assertIn("rememberProject(api, cwd)", (WEB / "sessions.js").read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
