"""Gestion des fichiers du web (files-manage.js, volet Fichiers) dans node avec le faux DOM."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccs_app.server import web

WEB = Path(web.WEB_DIR)
NODE = shutil.which("node")
_COPY = None

PRELUDE = r"""
import { installDom, settle } from "./web_dom.mjs";
const win = installDom();
const { FilesPanel } = await import("./files.js");
const m = await import("./files-manage.js");
const calls = [];
const store = new Map();                  // chemin → octets, comme le pont
const parts = new Map();
let entries = [{ name: "src", path: "src", dir: true, mark: "" }, { name: "a.txt", path: "a.txt", dir: false, mark: "" }];
const api = {
  async call(method, p) {
    calls.push([method, p]);
    switch (method) {
      case "files.list": return { entries: p.rel ? [] : entries, truncated: false };
      case "files.download": { const b = store.get(p.path); const d = b.subarray(p.offset, p.offset + m.CHUNK);
        return { size: b.length, data: m.toBase64(d), done: p.offset + d.length >= b.length }; }
      case "files.upload": { const key = `${p.dir}/${p.name}`;
        if (store.has(key) && !p.replace) throw Object.assign(new Error("existe déjà"), { code: "existe" });
        const old = p.offset ? parts.get(key) : new Uint8Array(0); const d = m.fromBase64(p.data);
        const all = new Uint8Array(old.length + d.length); all.set(old); all.set(d, old.length); parts.set(key, all);
        if (p.last) { store.set(key, all); parts.delete(key); } return { received: all.length, done: p.last }; }
      case "files.info": return { dir: false, count: 0, size: 3 };
      case "files.roots": return { home: "/home/u", roots: ["/home/u", "/srv"] };
      case "projects.add": return { cwd: p.cwd };
      case "machines.list": return { machines: [{ id: "vps", local: true, online: true },
        { id: "lp-work", name: "PC du bureau", online: true, mesh_ip: "100.64.0.2", tunnel: false },
        { id: "portable", name: "Portable", online: false }] };
      default: return {};
    }
  },
};
const named = (method) => calls.filter((c) => c[0] === method).map((c) => c[1]);
const sheet = () => document.querySelectorAll("dialog").at(-1);
const press = async (label) => { sheet().querySelectorAll("button").find((b) => b.textContent === label).click(); await settle(); };
const root = document.createElement("div");
document.body.append(root);
let out = null;
"""


def _copy():
    global _COPY
    if _COPY is None:
        _COPY = Path(tempfile.mkdtemp(prefix="ccs-webfiles-"))
        for p in WEB.glob("*.js"):
            shutil.copy(p, _COPY / p.name)
        shutil.copy(Path(__file__).with_name("web_dom.mjs"), _COPY / "web_dom.mjs")
        (_COPY / "package.json").write_text('{"type": "module"}')
    return _COPY


def tearDownModule():
    if _COPY is not None:
        shutil.rmtree(_COPY, ignore_errors=True)


def run(body):
    script = _copy() / "scenario.mjs"
    script.write_text(PRELUDE + body + "\nconsole.log(JSON.stringify(out));\nprocess.exit(0);\n", encoding="utf-8")
    r = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60, cwd=_copy())
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE, "node absent")
class FilesManageTest(unittest.TestCase):
    def test_transfer_round_trip_in_chunks(self):
        out = run("""
const data = new Uint8Array(m.CHUNK * 2 + 777);
for (let i = 0; i < data.length; i++) data[i] = (i * 31) % 251;
const seen = [];
await m.sendFile(api, "/p", "gros.bin", new Blob([data]), { progress: (n) => seen.push(n) });
const blob = await m.fetchFile(api, "/p/gros.bin");
const back = new Uint8Array(await blob.arrayBuffer());
const up = named("files.upload");
await m.sendFile(api, "/p", "vide", new Blob([]));
let big = null;
try { await m.sendFile(api, "/p", "x", { size: m.MAX_TRANSFER + 1 }); } catch (e) { big = e.message; }
out = { same: back.length === data.length && back.every((v, i) => v === data[i]), seen,
        offsets: up.map((u) => u.offset), last: up.map((u) => u.last), downloads: named("files.download").length,
        empty: store.get("/p/vide").length, big, sizes: [m.size(12), m.size(2048), m.size(3 * 1024 * 1024)] };
""")
        chunk = 1024 * 1024
        self.assertTrue(out["same"])
        self.assertEqual(out["seen"], [chunk, 2 * chunk, 2 * chunk + 777])
        self.assertEqual(out["offsets"], [0, chunk, 2 * chunk])
        self.assertEqual(out["last"], [False, False, True])
        self.assertEqual(out["downloads"], 3)
        self.assertEqual(out["empty"], 0)
        self.assertIn("200 Mo", out["big"])
        self.assertEqual(out["sizes"], ["12 o", "2 Ko", "3,0 Mo"])

    def test_panel_offers_tools_and_entry_actions(self):
        out = run("""
const panel = new FilesPanel(root, api, "/p");
await settle();
out = { tools: panel.tools.querySelectorAll("button").map((b) => b.textContent) };
const more = panel.tree.querySelectorAll(".tree-more");
out.more = more.map((b) => b.getAttribute("aria-label"));
const save = panel.tree.querySelectorAll(".tree-save");
out.save = save.map((b) => b.getAttribute("aria-label"));
store.set("/p/a.txt", new Uint8Array([1, 2, 3]));
save[0].click(); await settle();
out.direct = named("files.download").map((p) => p.path);
more[1].click(); await settle();
out.file = sheet().querySelectorAll(".menu-item").map((b) => b.textContent);
await press("Supprimer");                 // l'action du menu
out.ask = sheet().querySelector("h2").textContent;
await press("Supprimer");                 // la confirmation
out.deleted = named("files.delete");
out.lists = named("files.list").length;
more[0].click(); await settle();
out.dir = sheet().querySelectorAll(".menu-item").map((b) => b.textContent);
await press("Nouveau dossier ici");
sheet().querySelector("input").value = "docs";
await press("Créer");
out.mkdir = named("files.mkdir");
out.inside = named("files.list").at(-1);
out.left = document.querySelectorAll("dialog").length;
""")
        self.assertEqual(out["tools"], ["+ Fichier", "+ Dossier", "Envoyer", "Coller"])
        self.assertEqual(out["more"], ["Actions sur src", "Actions sur a.txt"])
        self.assertEqual(out["save"], ["Télécharger a.txt"])            # les fichiers seulement, pas les dossiers
        self.assertEqual(out["direct"], ["/p/a.txt"])
        self.assertEqual(out["file"], ["Télécharger", "Copier", "Couper", "Renommer", "Supprimer"])
        self.assertEqual(out["ask"], "Supprimer « a.txt » ?")
        self.assertEqual(out["deleted"], [{"path": "/p/a.txt", "root": "/p"}])
        self.assertEqual(out["lists"], 2)                              # le dossier touché est rechargé
        self.assertEqual(out["dir"][:3], ["Nouveau fichier ici", "Nouveau dossier ici", "Envoyer un fichier ici"])
        self.assertEqual(out["mkdir"], [{"dir": "/p/src", "name": "docs"}])
        self.assertEqual(out["inside"], {"root": "/p", "rel": "src"})   # c'est le dossier lui-même qu'on recharge
        self.assertEqual(out["left"], 0)

    def test_rename_and_cancel(self):
        out = run("""
const panel = new FilesPanel(root, api, "/p");
await settle();
const more = panel.tree.querySelectorAll(".tree-more");
more[1].click(); await settle();
await press("Renommer");
out = { value: sheet().querySelector("input").value };
sheet().querySelector("input").value = "b.txt";
await press("Renommer");
out.renamed = named("files.rename");
more[1].click(); await settle();
await press("Supprimer");
await press("Annuler");
out.deleted = named("files.delete").length;
""")
        self.assertEqual(out["value"], "a.txt")
        self.assertEqual(out["renamed"], [{"path": "/p/a.txt", "name": "b.txt", "root": "/p"}])
        self.assertEqual(out["deleted"], 0)

    def test_copy_cut_and_paste(self):
        out = run("""
const panel = new FilesPanel(root, api, "/p");
await settle();
const more = () => panel.tree.querySelectorAll(".tree-more");
out = { hidden: panel.pasteBtn.hidden };
more()[1].click(); await settle();
await press("Copier");
out.shown = [panel.pasteBtn.hidden, panel.pasteBtn.textContent];
more()[0].click(); await settle();
out.dir = sheet().querySelectorAll(".menu-item").map((b) => b.textContent);
await press("Coller « a.txt » ici");
panel.pasteBtn.click(); await settle();          // une copie se colle autant de fois qu'on veut
more()[1].click(); await settle();
await press("Couper");
more()[0].click(); await settle();
await press("Coller « a.txt » ici");
out.pasted = named("files.paste");
out.after = panel.pasteBtn.hidden;               // un déplacement vide le presse-papiers
""")
        self.assertTrue(out["hidden"])
        self.assertEqual(out["shown"], [False, "Coller « a.txt »"])
        self.assertIn("Coller « a.txt » ici", out["dir"])
        self.assertEqual(out["pasted"], [
            {"path": "/p/a.txt", "dir": "/p/src", "mode": "copy", "root": "/p"},
            {"path": "/p/a.txt", "dir": "/p", "mode": "copy", "root": "/p"},
            {"path": "/p/a.txt", "dir": "/p/src", "mode": "move", "root": "/p"}])
        self.assertTrue(out["after"])

    def test_browser_navigates_and_adds_projects(self):
        out = run("""
const { mountFiles } = await import("./files-browser.js");
globalThis.location = { hash: "" };
const view = mountFiles(root, api, { sub: "" });
await settle();
const crumbs = () => root.querySelector(".crumbs");
out = { first: named("files.list").at(-1), roots: crumbs().querySelectorAll("option").map((o) => o.textContent) };
root.querySelectorAll(".tree-more")[0].click(); await settle();
out.menu = sheet().querySelectorAll(".menu-item").map((b) => b.textContent);
await press("Ajouter aux projets de CCS");
out.added = named("projects.add");
root.querySelectorAll(".tree-more")[0].click(); await settle();
await press("Ouvrir ce dossier");
out.hash = location.hash;
view.route(encodeURIComponent("/home/u/src")); await settle();
out.inside = named("files.list").at(-1);
out.here = crumbs().querySelector(".here").textContent;
root.querySelector(".add-project").click(); await settle();
out.current = named("projects.add").at(-1);
view.route(encodeURIComponent("/etc")); await settle();       // hors des dossiers permis : retour au départ
out.refused = named("files.list").at(-1);
""")
        self.assertEqual(out["first"], {"root": "/home/u", "rel": ""})
        self.assertEqual(out["roots"], ["Personnel", "/srv"])
        self.assertEqual(out["menu"][3:5], ["Ouvrir ce dossier", "Ajouter aux projets de CCS"])
        self.assertEqual(out["added"], [{"cwd": "/home/u/src"}])
        self.assertEqual(out["hash"], "#/fichiers/%2Fhome%2Fu%2Fsrc")
        self.assertEqual(out["inside"], {"root": "/home/u/src", "rel": ""})
        self.assertEqual(out["here"], "src")
        self.assertEqual(out["current"], {"cwd": "/home/u/src"})
        self.assertEqual(out["refused"], {"root": "/home/u", "rel": ""})


    def test_browser_grid_view_enters_folders(self):
        out = run("""
const { mountFiles } = await import("./files-browser.js");
globalThis.location = { hash: "" };
const view = mountFiles(root, api, { sub: "" });
await settle();
out = { tilesBefore: root.querySelectorAll(".file-tile").length };
root.querySelector(".view-toggle").click(); await settle();
out.stored = localStorage.getItem("ccs.files.view");
out.tiles = root.querySelectorAll(".file-tile .tile-name").map((t) => t.textContent);
out.label = root.querySelector(".view-toggle").getAttribute("aria-label");
root.querySelector(".file-tile.dir .tile-main").click(); await settle();
out.hash = location.hash;
root.querySelectorAll(".file-tile .tile-main")[1].click(); await settle();
out.opened = Boolean(root.querySelector(".file-holder"));
""")
        self.assertEqual(out["tilesBefore"], 0)
        self.assertEqual(out["stored"], "grid")
        self.assertEqual(out["tiles"], ["src", "a.txt"])
        self.assertEqual(out["label"], "Afficher en liste")
        self.assertEqual(out["hash"], "#/fichiers/%2Fhome%2Fu%2Fsrc")
        self.assertTrue(out["opened"])

    def test_browser_opens_other_devices_of_the_mesh(self):
        out = run("""
const sockets = [];
globalThis.WebSocket = class {
  static OPEN = 1;
  constructor(url) { this.url = url; this.readyState = 0; sockets.push(this); setTimeout(() => { this.readyState = 1; this.onopen?.(); }); }
  send(raw) { const q = JSON.parse(raw); const result = q.method === "files.roots" ? { home: "/home/c", roots: ["/home/c"] }
    : { entries: [], truncated: false }; setTimeout(() => this.onmessage?.({ data: JSON.stringify({ id: q.id, result }) })); }
  close() { this.readyState = 3; }
};
globalThis.location = { hash: "", protocol: "https:", host: "ccs.exemple" };
const F = await import("./files-browser.js");
out = { parse: [F.parseSub("@lp-work/%2Fhome%2Fc%2Fx"), F.parseSub("%2Fsrv"), F.parseSub("")],
        addr: F.address("/home/c", "lp-work") };
const view = F.mountFiles(root, api, { sub: "" });
await settle();
out.devices = root.querySelectorAll(".file-device").map((b) => [b.textContent, b.getAttribute("disabled") !== null && b.getAttribute("disabled") !== "false"]);
view.route("@lp-work/" + encodeURIComponent("/home/c")); await settle(); await new Promise((r) => setTimeout(r, 20)); await settle();
out.url = sockets.map((s) => s.url);
out.selected = root.querySelectorAll(".file-device").map((b) => b.getAttribute("aria-selected"));
out.crumb = root.querySelector(".crumbs").textContent;
out.remembered = localStorage.getItem("ccs.files.device");
view.cleanup();
out.closed = sockets[0].readyState;
""")
        self.assertEqual(out["parse"], [{"device": "lp-work", "path": "/home/c/x"}, {"device": "", "path": "/srv"},
                                        {"device": "", "path": ""}])
        self.assertEqual(out["addr"], "#/fichiers/@lp-work/%2Fhome%2Fc")
        self.assertEqual(out["devices"], [["Serveur CCS", False], ["PC du bureau", False], ["Portablehors ligne", True]])
        self.assertEqual(out["url"], ["wss://ccs.exemple/api/ws?protocol=1&machine=lp-work"])
        self.assertEqual(out["selected"], ["false", "true", "false"])
        self.assertIn("Personnel", out["crumb"])
        self.assertEqual(out["remembered"], "lp-work")
        self.assertEqual(out["closed"], 3)

if __name__ == "__main__":
    unittest.main()
