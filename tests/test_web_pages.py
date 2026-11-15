"""Pages de la version web (Accueil, Réglages, Analyse, Git) : règles de forme vérifiées sans
navigateur (pas d'alert(), jauges accessibles, réglages connus du pont, thème, modules)."""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from ccs_app import settings
from ccs_app.server import web

WEB = Path(web.WEB_DIR)
MINE = ["home.js", "settings.js", "analysis.js", "git.js", "pages-util.js", "pages-health.js",
        "pages-tasks.js", "pages-phone.js"]


def text(name):
    return (WEB / name).read_text(encoding="utf-8")


class PagesTest(unittest.TestCase):
    def test_single_column_grids_never_widen(self):
        """Accueil : une carte de compte ne s'élargit pas jusqu'à sa ligne e-mail (sans retour à la
        ligne), ses barres et son bouton restent dans la carte, au téléphone comme au bureau."""
        css = (WEB / "style.css").read_text()
        rule = re.search(r"([^{}]*)\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\);\s*\}", css)
        self.assertIsNotNone(rule, "règle minmax(0, 1fr) absente")
        sels = {s.strip() for s in re.sub(r"/\*.*?\*/", "", rule.group(1), flags=re.S).split(",")}
        for s in (".view", ".account", ".gauge", ".section", ".stack", "details.details > div",
                  ".health-check"):
            self.assertIn(s, sels)

    def test_no_alert_confirm_or_prompt(self):
        for name in MINE:
            self.assertIsNone(re.search(r"(?<![.\w])(alert|confirm|prompt)\(", text(name)), name)

    def test_no_inline_handlers_or_inner_html(self):
        for name in MINE + ["pages.css"]:
            src = text(name)
            self.assertNotIn("innerHTML", src, name)
            self.assertNotIn("insertAdjacentHTML", src, name)
            self.assertNotIn("eval(", src, name)
            self.assertIsNone(re.search(r'\bon[a-z]+="', src), name)

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_js_syntax(self):
        for name in MINE:
            r = subprocess.run(["node", "--input-type=module", "--check"], input=text(name),
                               text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_every_import_resolves(self):
        for name in MINE:
            for ref in re.findall(r'from "\./([^"]+)"', text(name)):
                self.assertTrue((WEB / ref).is_file(), f"{name} → {ref}")

    def test_gauges_are_progressbars(self):
        src = text("home.js")
        for attr in ('role: "progressbar"', "aria-valuenow", "aria-valuemin", "aria-valuemax"):
            self.assertIn(attr, src)

    def test_home_uses_feedback_helpers(self):
        src = text("home.js")
        self.assertIn("confirmSheet(", src)
        self.assertIn("toast(", src)
        self.assertIn("accounts.cards", src)
        self.assertIn("skeleton", src)
        self.assertIn("Détails", src)
        self.assertIn("running", src.lower())     # prévient si des chats tournent

    def test_health_card_copy_button(self):
        src = text("pages-health.js")
        self.assertIn("doctor.run", src)
        self.assertIn("Copier", src)
        self.assertIn("Bilan de santé", src)

    def test_tasks_section_features(self):
        src = text("pages-tasks.js")
        for needle in ("tasks.list", "tasks.log", "tasks.add", "tasks.cancel", "tasks.remove",
                       "chat.open", "session_id", "#/sessions/", "confirmSheet("):
            self.assertIn(needle, src)

    def test_every_setting_path_exists_in_defaults(self):
        for name in ("settings.js", "pages-phone.js"):
            paths = re.findall(r'path: "([a-z_.]+)"', text(name))
            self.assertTrue(paths, name)
            for path in paths:
                node = settings.DEFAULTS
                for key in path.split("."):
                    self.assertIn(key, node, f"{name}: {path}")
                    node = node[key]

    def test_settings_cover_phone_and_git(self):
        src = text("settings.js") + text("pages-phone.js")
        for path in ("git.fetch_minutes", "phone.show_content", "phone.server", "phone.topic", "phone.enabled"):
            self.assertIn(f'"{path}"', src)
        for method in ("phone.test", "phone.qr", "phone.new_topic"):
            self.assertIn(method, src)
        self.assertIn("Enregistré.", text("pages-util.js"))

    def test_theme_kept_in_browser_and_css_overrides(self):
        src = text("settings.js")
        self.assertIn("localStorage", src)
        self.assertIn("dataset.theme", src)
        css = text("pages.css")
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn(':root[data-theme="light"]', css)

    def test_qr_is_an_image_source_not_html(self):
        src = text("pages-phone.js")
        self.assertIn('el("img", { src: r.image', src)

    def test_analysis_periods_and_empty_state(self):
        src = text("analysis.js")
        for days in ("[1,", "[7,", "[30,", "[90,"):
            self.assertIn(days, src)
        self.assertIn("Essayer 30 jours", src)

    def test_git_panel_contract(self):
        src = text("git.js")
        self.assertIn("export class GitPanel", src)
        self.assertIn("constructor(container, api, cwd)", src)
        self.assertIn("destroy()", src)
        for method in ("git.status", "git.diff", "git.stage", "git.unstage", "git.hunk", "git.commit",
                       "git.fetch", "git.pull", "git.push", "git.log"):
            self.assertIn(method, src)
        self.assertIn("Push forcé", src)
        self.assertIn("amend", src)

    def test_pages_css_has_dark_and_phone_first_rules(self):
        css = text("pages.css")
        self.assertIn(".diff-line.add", css)
        self.assertIn("@media (min-width: 720px)", css)


if __name__ == "__main__":
    unittest.main()
