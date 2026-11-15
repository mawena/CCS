"""Version web : fichiers statiques sains (pas de script ni de style en ligne : la CSP les
bloquerait), tout fichier référencé existe, servis par ccs-web."""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from ccs_app.server import web

WEB = Path(web.WEB_DIR)
HTML = sorted(WEB.glob("*.html"))
JS = sorted(p for p in WEB.rglob("*.js") if "vendor" not in p.parts)


def referenced(path):
    """Fichiers locaux référencés par un .html (src, href) ou un module JS (import)."""
    text = path.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"#?]+)"', text) if path.suffix == ".html" else []
    refs += re.findall(r'''(?:from|import)\s*\(?\s*["'](\./[^"']+|/[^"']+)["']''', text)
    out = []
    for r in refs:
        if r.startswith(("http:", "https:", "data:", "mailto:")):
            continue
        out.append((WEB / r.lstrip("/")) if r.startswith("/") else (path.parent / r))
    return out


class StaticTest(unittest.TestCase):
    def test_no_inline_script_or_style(self):
        for p in HTML:
            text = p.read_text(encoding="utf-8")
            for m in re.finditer(r"<script\b([^>]*)>", text):
                self.assertIn("src=", m.group(1), p.name)
            self.assertIsNone(re.search(r"\son[a-z]+\s*=", text), p.name)
            self.assertNotIn("style=", text, p.name)
            self.assertNotIn("<style", text, p.name)

    def test_js_never_uses_inner_html_with_variables(self):
        for p in JS:
            text = p.read_text(encoding="utf-8")
            for m in re.finditer(r"\.innerHTML\s*=\s*([^;]+);", text):
                value = m.group(1).strip()
                self.assertTrue(value in ('""', "''") or value.startswith("sanitized("),
                                f"{p.name} : innerHTML = {value}")

    def test_all_referenced_files_exist(self):
        for p in HTML + JS:
            for ref in referenced(p):
                self.assertTrue(ref.is_file(), f"{p.name} → {ref}")

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_js_syntax(self):
        with tempfile.TemporaryDirectory() as tmp:
            for p in JS:
                copy = Path(tmp) / (p.stem + ".mjs")
                copy.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
                r = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{p.name} : {r.stderr[-400:]}")

    def test_manifest_valid_json(self):
        m = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(m["name"], "CCS")
        self.assertEqual(m["display"], "standalone")
        for icon in m["icons"]:
            self.assertTrue((WEB / icon["src"].lstrip("/")).is_file(), icon["src"])
        self.assertTrue(any(i["sizes"] == "512x512" for i in m["icons"]))

    def test_viewport_meta_present(self):
        text = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('name="viewport"', text)
        self.assertIn("width=device-width", text)
        self.assertIn('rel="manifest"', text)

    def test_views_registered(self):
        text = (WEB / "views.js").read_text(encoding="utf-8")
        for module in ("./home.js", "./analysis.js", "./settings.js"):
            self.assertIn(module, text)

    def test_chat_handles_every_event_type(self):
        from ccs_app.server import events
        text = (WEB / "chat.js").read_text(encoding="utf-8")
        for name in events.TYPES:
            self.assertIn(f'"{name}"', text, name)
        self.assertIn("./sessions.js", (WEB / "views.js").read_text(encoding="utf-8"))

    def test_vendor_checksums_match(self):
        import hashlib
        lines = (WEB / "vendor" / "LISEZMOI").read_text(encoding="utf-8").splitlines()
        sums = [l.split() for l in lines if re.match(r"^[0-9a-f]{64}  ", l)]
        self.assertEqual(len(sums), 3)
        for digest, name in sums:
            self.assertEqual(hashlib.sha256((WEB / "vendor" / name).read_bytes()).hexdigest(), digest, name)
        self.assertTrue((WEB / "vendor" / "xterm" / "LICENSE").is_file())

    def test_files_roadmap_terminal_wired(self):
        chat = (WEB / "chat.js").read_text(encoding="utf-8")
        sessions = (WEB / "sessions.js").read_text(encoding="utf-8")
        self.assertIn("./files.js", chat)
        self.assertIn("./roadmap.js", chat)
        self.assertIn("./terminal.js", sessions)
        self.assertIn("files.write", (WEB / "files.js").read_text(encoding="utf-8"))
        self.assertIn("roadmap.toggle", (WEB / "roadmap.js").read_text(encoding="utf-8"))
        self.assertIn("term.input", (WEB / "terminal.js").read_text(encoding="utf-8"))
        self.assertIn("ccs add", (WEB / "home.js").read_text(encoding="utf-8"))

    def test_sessions_can_open_any_folder(self):
        """Comme « Nouvelle session… » du bureau : un dossier encore sans conversation s'ouvre aussi
        (chat ou terminal) ; l'onglet prend le chemin réel renvoyé par le pont (~ développé)."""
        sessions = (WEB / "sessions.js").read_text(encoding="utf-8")
        self.assertIn('"aria-label": "Dossier de la session"',            # feuille « Nouvelle session »
                      (WEB / "sessions-new.js").read_text(encoding="utf-8"))
        self.assertIn("r.cwd", sessions)

    def test_feedback_helpers_replace_alert_and_confirm(self):
        """Socle de la phase 14 au web : toasts, carte de confirmation, chargement, états vides."""
        dom = (WEB / "dom.js").read_text(encoding="utf-8")
        for name in ("toast", "confirmSheet", "loading", "emptyState", "errorState"):
            self.assertIn(f"export function {name}(", dom)

    def test_one_stylesheet_per_area(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for css in ("style.css", "chat.css", "sessions.css", "pages.css"):
            self.assertTrue((WEB / css).is_file(), css)
            self.assertIn(f'href="/{css}"', html)

    def test_service_worker_caches_every_module(self):
        """Hors ligne, la charpente s'ouvre avec toutes ses pages (pas seulement l'accueil)."""
        sw = (WEB / "sw.js").read_text(encoding="utf-8")
        for p in sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.css")):
            if p.name != "sw.js":
                self.assertIn(f'"/{p.name}"', sw, p.name)

    def test_sub_routes_and_waiting_badge(self):
        """#/sessions/<chat> : le bouton Retour du téléphone ferme le chat ; pastille « attend ta réponse »."""
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("state.route(sub)", app)
        self.assertIn('c.state === "permission"', app)
        self.assertIn('aria-current", "page"', app)
        sessions = (WEB / "sessions.js").read_text(encoding="utf-8")
        self.assertIn("route: (sub)", sessions)
        self.assertIn('"chat-mode"', sessions)

    def test_hooks_between_areas(self):
        """Points d'accroche entre lots : Git dans le chat, fichier cité, envoi depuis la feuille de route."""
        self.assertIn("export class GitPanel", (WEB / "git.js").read_text(encoding="utf-8"))
        self.assertIn("openFile(path, { line = null } = {})", (WEB / "files.js").read_text(encoding="utf-8"))
        chat = (WEB / "chat.js").read_text(encoding="utf-8")
        self.assertIn("sendText(text)", chat)
        self.assertIn("send: (text) => this.sendText(text)", chat)

    def test_settings_page_lists_devices(self):
        text = (WEB / "settings.js").read_text(encoding="utf-8")
        self.assertIn("/api/tokens", text)
        self.assertIn("/api/revoke", text)

    def test_sanitizer_refuses_protocol_relative_links(self):
        text = (WEB / "dom.js").read_text(encoding="utf-8")
        self.assertIn("\\/(?!\\/)", text)

    def test_api_js_has_reconnect_and_attach(self):
        text = (WEB / "api.js").read_text(encoding="utf-8")
        self.assertIn("reconnect", text)
        self.assertIn("30000", text)                       # attente plafonnée à 30 s


class ServedTest(AioHTTPTestCase):
    async def get_application(self):
        return web.make_app(None, None, dict(web.DEFAULT_CONFIG))

    async def test_served_by_web_app(self):
        r = await self.client.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("text/html", r.headers["Content-Type"])
        for name in ("app.js", "api.js", "login.js", "style.css", "manifest.webmanifest", "sw.js"):
            r = await self.client.get("/" + name)
            self.assertEqual(r.status, 200, name)
        r = await self.client.get("/app.js")
        self.assertIn("javascript", r.headers["Content-Type"])
        r = await self.client.get("/../server/web.py")
        self.assertNotEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()


class InstallAppTest(unittest.TestCase):
    def test_install_offered_on_iphone_and_chrome(self):
        """Comme Outlook : la version web propose de s'installer (bouton Installer sur Chrome
        Android/ordinateur, marche à suivre Partager → « Sur l'écran d'accueil » sur iPhone,
        Safari comme Chrome), jamais une fois installée, et refusable."""
        js = (WEB / "install.js").read_text(encoding="utf-8")
        self.assertIn("beforeinstallprompt", js)
        self.assertIn("display-mode: standalone", js)
        self.assertIn("navigator.standalone", js)
        self.assertIn("iPhone|iPad|iPod", js)
        self.assertIn("localStorage", js)
        self.assertIn("./install.js", (WEB / "app.js").read_text(encoding="utf-8"))
        self.assertIn("/install.js", (WEB / "sw.js").read_text(encoding="utf-8"))
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('name="apple-mobile-web-app-capable"', html)
        self.assertIn('name="apple-mobile-web-app-title"', html)
