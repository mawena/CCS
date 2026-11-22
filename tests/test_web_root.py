"""Version web : mot de passe root demandé aux appareils (root.js, phase 34), exécuté dans node
avec le faux DOM de tests/web_dom.mjs, un faux WebSocket et une horloge réglable."""

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
globalThis.location = { protocol: "https:", host: "ccs.exemple", hash: "" };
// tout ce qui passe par la console est relevé : le mot de passe ne doit jamais y être
const logs = [];
for (const k of ["log", "info", "warn", "error", "debug"]) console[k] = (...a) => logs.push(a.map(String).join(" "));
const print = process.stdout.write.bind(process.stdout);
const sockets = [];
class FakeWS {
  static OPEN = 1;
  constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
  send(m) { this.sent.push(JSON.parse(m)); }
  close() { this.readyState = 3; this.onclose?.({ code: 1000 }); }
  open() { this.readyState = 1; this.onopen?.(); }
  reply(id, result) { this.onmessage?.({ data: JSON.stringify({ id, result }) }); }
  fail(id, code, message) { this.onmessage?.({ data: JSON.stringify({ id, error: { code, message } }) }); }
  push(event, data) { this.onmessage?.({ data: JSON.stringify({ event, data }) }); }
  last(method) { return [...this.sent].reverse().find((m) => m.method === method); }
  calls(method) { return this.sent.filter((m) => m.method === method).length; }
}
globalThis.WebSocket = FakeWS;
globalThis.fetch = async () => ({ ok: true, json: async () => ({ user: "alice" }) });
const { Api } = await import("./api.js");
const { pickMachine } = await import("./machines.js");
const root = await import("./root.js");
let clock = 1_000_000_000_000;
const now = () => clock;
const sec = (ms) => (clock + ms) / 1000;
const dlg = () => document.querySelector("dialog.root-sheet");
const toasts = () => document.querySelectorAll(".toast").map((t) => t.textContent);
const shell = document.createElement("div"); shell.id = "shell";
const view = document.createElement("section"); view.id = "view"; shell.append(view);
document.body.append(shell);
let out = null;
"""


def run(body):
    tmp = Path(tempfile.mkdtemp(prefix="ccs-webroot-"))
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
class RootWebTest(unittest.TestCase):
    def test_ask_answer_wrong_then_right_password(self):
        out = run(r"""
const api = new Api();
const watch = new root.RootWatch(api, { now, tick: 1e9 }).start();
api.connect(); const ws = sockets[0]; ws.open();
ws.reply(ws.last("root.status").id, { machine: "mawena-cloud", kept: false, pending: null });
await settle();
out = { before: Boolean(dlg()) };
ws.push("root.ask", { id: "r1", machine: "mawena-cloud", command: "apt update", expires_at: sec(300000), tries_left: 3 });
const d = dlg(), input = d.querySelector("input");
out.open = d.open;
out.title = d.querySelector("h2").textContent;
out.command = d.querySelector(".root-command").textContent;
out.input = { type: input.getAttribute("type"), auto: input.getAttribute("autocomplete") };
out.info = d.querySelector(".root-info").textContent;
input.value = "mauvais-secret";
d.querySelector("button.primary").click();
out.cleared = input.value;
const a1 = ws.last("root.answer");
out.sent1 = a1.params;
out.sending = d.querySelector(".root-info").textContent;
ws.reply(a1.id, { ok: false, error: "Mot de passe refusé (essai 1 sur 3)." });
ws.push("root.ask", { id: "r1", machine: "mawena-cloud", command: "apt update", expires_at: sec(290000),
                      tries_left: 1, error: "Mot de passe refusé (essai 2 sur 3)." });
await settle();
out.same = dlg() === d;
out.error = d.querySelector(".root-error").textContent;
out.info2 = d.querySelector(".root-info").textContent;
input.value = "bon-secret";
d.querySelector("form").dispatchEvent(new win.Event("submit"));
const a2 = ws.last("root.answer");
ws.reply(a2.id, { ok: true });
await settle();
out.closed = !dlg();
out.statusAgain = ws.calls("root.status");
const stored = JSON.stringify([...localStorage.map, ...sessionStorage.map]) + location.hash + logs.join("|");
out.leak = stored.includes("secret");
watch.stop();
""")
        self.assertFalse(out["before"])
        self.assertTrue(out["open"])
        self.assertEqual(out["title"], "mawena-cloud demande le mot de passe root")
        self.assertEqual(out["command"], "apt update")
        self.assertEqual(out["input"], {"type": "password", "auto": "off"})
        self.assertEqual(out["info"], "3 essais restants. Expire dans 5:00.")
        self.assertEqual(out["cleared"], "")                      # champ vidé dès l'envoi
        self.assertEqual(out["sent1"], {"id": "r1", "password": "mauvais-secret"})
        self.assertEqual(out["sending"], "Vérification…")
        self.assertTrue(out["same"])
        self.assertEqual(out["error"], "Mot de passe refusé (essai 2 sur 3).")
        self.assertEqual(out["info2"], "Dernier essai. Expire dans 4:50.")
        self.assertTrue(out["closed"])
        self.assertEqual(out["statusAgain"], 2)                   # durée de la garde relue
        self.assertFalse(out["leak"])

    def test_refuse_resolved_elsewhere_expiry_and_errors(self):
        out = run(r"""
const api = new Api();
const watch = new root.RootWatch(api, { now, tick: 1e9 }).start();
api.connect(); const ws = sockets[0]; ws.open();
const ask = (id) => ws.push("root.ask", { id, machine: "pc-bureau", command: "", expires_at: sec(300000), tries_left: 3 });
out = {};
ask("a");
out.noCommand = dlg().querySelector(".root-command").hidden;
dlg().querySelector("button:not(.primary)").click();        // Refuser
const c = ws.last("root.answer");
out.cancel = c.params;
ws.reply(c.id, { ok: false });
await settle();
out.refused = !dlg();
ask("b");
ws.push("root.resolved", { id: "autre", ok: true });
out.otherId = Boolean(dlg());
ws.push("root.resolved", { id: "b", ok: true });             // réglée sur un autre appareil
out.resolved = !dlg();
ask("c");
const d = dlg();
d.dispatchEvent(new win.Event("cancel"));
out.escapeKept = d.open && Boolean(dlg());
d.querySelector("input").value = "x";
d.querySelector("button.primary").click();
ws.fail(ws.last("root.answer").id, "conflit", "occupé");
await settle();
out.conflict = d.querySelector(".root-error").textContent;
d.querySelector("input").value = "x";
d.querySelector("button.primary").click();
ws.fail(ws.last("root.answer").id, "introuvable", "plus là");
await settle();
out.gone = !dlg();
ask("e");
clock += 301000; watch.tick();
out.expired = !dlg();
ask("f");
ws.readyState = 3;                                           // hors ligne : rien n'attend dans la file
const n = ws.calls("root.answer");
dlg().querySelector("input").value = "x";
dlg().querySelector("button.primary").click();
out.offline = [ws.calls("root.answer") - n, api.queue.length, dlg().querySelector(".root-error").textContent];
watch.stop();
out.stopped = !dlg();
""")
        self.assertTrue(out["noCommand"])
        self.assertEqual(out["cancel"], {"id": "a", "cancel": True})
        self.assertTrue(out["refused"])
        self.assertTrue(out["otherId"])
        self.assertTrue(out["resolved"])
        self.assertTrue(out["escapeKept"])                        # Échap ne ferme pas la demande
        self.assertEqual(out["conflict"], "Un autre appareil a répondu : vérification en cours.")
        self.assertTrue(out["gone"])
        self.assertTrue(out["expired"])
        self.assertEqual(out["offline"], [0, 0, "Connexion perdue : réessaie une fois reconnecté."])
        self.assertTrue(out["stopped"])

    def test_status_on_connect_kept_bar_forget_and_notices(self):
        out = run(r"""
const api = new Api();
const watch = new root.RootWatch(api, { now, tick: 1e9 }).start();
api.connect(); const ws = sockets[0]; ws.open();
ws.reply(ws.last("root.status").id, { machine: "mawena-cloud", kept: true, remaining: 2500, expires_at: sec(2500000),
  pending: { id: "p1", machine: "mawena-cloud", command: "ccs root -- ls", expires_at: sec(120000), tries_left: 2 } });
await settle();
const bar = document.querySelector(".root-bar");
out = { pending: dlg()?.querySelector(".root-info").textContent, inShell: bar.parentNode === shell,
        beforeView: shell.childNodes.indexOf(bar) < shell.childNodes.indexOf(view),
        bar: bar.querySelector(".root-bar-text").textContent };
ws.push("root.resolved", { id: "p1", ok: true });
ws.push("root.used", { machine: "mawena-cloud", command: "apt upgrade", at: sec(0) });
await settle();
out.used = toasts().some((t) => t.includes("mawena-cloud a lancé en root : apt upgrade"));
ws.reply(ws.last("root.status").id, { machine: "mawena-cloud", kept: true, remaining: 3000, pending: null });
await settle();
out.bar2 = bar.querySelector(".root-bar-text").textContent;
bar.querySelector("button").click();                        // Oublier
const f = ws.last("root.forget");
ws.push("root.forgotten", { machine: "mawena-cloud", reason: "forget" });
ws.reply(f.id, { had: true });
await settle();
out.forgot = [Boolean(f), bar.hidden, toasts().filter((t) => t.includes("effacé") || t.includes("oublié")).length];
ws.push("root.forgotten", { machine: "mawena-cloud", reason: "expired" });
await settle();
out.noTwice = toasts().filter((t) => t.includes("1 h passée")).length;
watch.refresh();
ws.reply(ws.last("root.status").id, { machine: "mawena-cloud", kept: true, remaining: 60, pending: null });
await settle();
ws.push("root.forgotten", { machine: "mawena-cloud", reason: "revoke" });
await settle();
out.revoked = [bar.hidden, toasts().some((t) => t.includes("Mot de passe root révoqué."))];
watch.stop();
""")
        self.assertEqual(out["pending"], "2 essais restants. Expire dans 2:00.")
        self.assertTrue(out["inShell"])
        self.assertTrue(out["beforeView"])
        self.assertEqual(out["bar"], "Root gardé sur mawena-cloud, 42 min")
        self.assertTrue(out["used"])
        self.assertEqual(out["bar2"], "Root gardé sur mawena-cloud, 50 min")
        self.assertEqual(out["forgot"], [True, True, 1])          # un seul avis pour « Oublier »
        self.assertEqual(out["noTwice"], 0)                       # rien n'était gardé
        self.assertEqual(out["revoked"], [True, True])

    def test_popup_follows_the_piloted_machine(self):
        out = run(r"""
const api = new Api();
const watch = new root.RootWatch(api, { now, tick: 1e9 }).start();
api.connect(); const ws0 = sockets[0]; ws0.open();
const stale = ws0.last("root.status");
ws0.push("root.ask", { id: "s1", machine: "mawena-cloud", command: "ls", expires_at: sec(300000), tries_left: 3 });
out = { local: Boolean(dlg()) };
pickMachine(api, "pc-bureau", "PC du bureau");
out.closedOnSwitch = !dlg();
const ws1 = sockets[1]; ws1.open();
out.beforeReady = ws1.calls("root.status");                 // le tunnel n'est pas encore prêt
ws1.push("machines.ready", { machine: "pc-bureau", name: "PC du bureau" });
const st = ws1.last("root.status");
ws1.reply(st.id, { machine: "pc-bureau", kept: false,
  pending: { id: "b1", machine: "pc-bureau", command: "systemctl restart x", expires_at: sec(200000), tries_left: 3 } });
await settle();
out.remote = dlg()?.querySelector("h2").textContent;
dlg().querySelector("input").value = "pw";
dlg().querySelector("button.primary").click();
out.answerOn = ws1.last("root.answer")?.params.id;
out.urls = sockets.map((s) => s.url.split("?")[1]);
watch.stop();
""")
        self.assertTrue(out["local"])
        self.assertTrue(out["closedOnSwitch"])
        self.assertEqual(out["beforeReady"], 0)
        self.assertEqual(out["remote"], "pc-bureau demande le mot de passe root")
        self.assertEqual(out["answerOn"], "b1")
        self.assertEqual(out["urls"], ["protocol=1", "protocol=1&machine=pc-bureau"])

    def test_texts_and_deadlines(self):
        out = run(r"""
const t = 1_000_000_000_000;
out = {
  near: root.deadline(t / 1000 + 120, t, root.ASK_MS) - t,
  skewed: root.deadline(t / 1000 + 9999, t, root.ASK_MS) - t,
  past: root.deadline(t / 1000 - 5, t, root.ASK_MS) - t,
  none: root.deadline(undefined, t, root.KEEP_MS) - t,
  min: [root.minutes(0), root.minutes(1), root.minutes(60000), root.minutes(60001)],
  clock: root.clock(65000),
  tries: [root.triesText(0), root.triesText(1), root.triesText(3)],
  kept: [root.keptText("", 61000), root.keptText("pc-bureau", 3600000)],
  used: root.usedText({ machine: "", command: "" }),
  noId: root.readAsk({ machine: "x" }, t),
};
""")
        self.assertEqual(out["near"], 120000)
        self.assertEqual(out["skewed"], 300000)                   # horloges décalées : 5 min
        self.assertEqual(out["past"], 300000)
        self.assertEqual(out["none"], 3600000)
        self.assertEqual(out["min"], [0, 1, 1, 2])
        self.assertEqual(out["clock"], "1:05")
        self.assertEqual(out["tries"], ["", "Dernier essai.", "3 essais restants."])
        self.assertEqual(out["kept"], ["Root gardé, 2 min", "Root gardé sur pc-bureau, 60 min"])
        self.assertEqual(out["used"], "La machine a lancé une commande root.")
        self.assertIsNone(out["noId"])


if __name__ == "__main__":
    unittest.main()
