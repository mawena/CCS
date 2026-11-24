"""Version web, lot « sessions » : modules JS sains (CSP, pas d'alert ni de confirm), méthodes du
pont appelées qui existent, logique pure du terminal et de la liste (exécutée par node)."""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccs_app.server import web

WEB = Path(web.WEB_DIR)
SERVER = WEB.parent / "server"
MINE = ["sessions.js", "files.js", "files-manage.js", "roadmap.js", "terminal.js", "project.js", "sessions-conv.js", "sessions-new.js", "sessions-order.js"]
NODE = shutil.which("node")


def source(name):
    return (WEB / name).read_text(encoding="utf-8")


def bridge_methods():
    names = set()
    for p in SERVER.glob("bridge*.py"):
        names |= set(re.findall(r'"([a-z_]+\.[a-z_]+)":', p.read_text(encoding="utf-8")))
    return names


@unittest.skipUnless(NODE, "node absent")
class SessionsWebTest(unittest.TestCase):
    def test_empty_stage_centered_without_stretched_button(self):
        """Aucun chat ouvert : le message occupe la zone et reste centré ; la rangée de boutons ne
        s'étire pas sur toute la hauteur (bouton « Nouvelle session » géant)."""
        css = (WEB / "style.css").read_text()
        self.assertTrue(re.search(r"\.stage > \.state \{[^}]*flex: 1;", css), "état vide pas étendu")
        state = re.search(r"\n\.state \{([^}]*)\}", css).group(1)
        self.assertIn("align-content: center", state)

    def test_short_titles_aligned_left(self):
        """Ligne de projet ou de conversation (bouton en grille) : le `justify-content: center` des
        boutons ne centre pas un titre court ; une colonne pleine largeur, texte à gauche."""
        css = (WEB / "sessions.css").read_text()
        for sel in (".project-open-btn", ".conv-main"):
            rule = re.search(r"\n" + re.escape(sel) + r" \{([^}]*)\}", css).group(1)
            self.assertIn("grid-template-columns: minmax(0, 1fr)", rule, sel)

    def test_modules_parse(self):
        for name in MINE:
            r = subprocess.run([NODE, "--input-type=module", "--check"], input=source(name),
                               text=True, capture_output=True, timeout=30)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_no_alert_confirm_or_raw_html(self):
        for name in MINE:
            text = source(name)
            self.assertIsNone(re.search(r"(?<![\w.])(alert|confirm|prompt)\(", text), name)
            self.assertNotIn("innerHTML", text, name)
            self.assertNotIn("eval(", text, name)
            self.assertIsNone(re.search(r"""setAttribute\(\s*["']on""", text), name)
            self.assertIsNone(re.search(r"""\bstyle\s*:\s*["'`]""", text), name)

    def test_rpc_methods_exist(self):
        known = bridge_methods()
        used = set()
        for name in MINE:
            used |= set(re.findall(r'''call\(\s*["']([a-z_]+\.[a-z_]+)["']''', source(name)))
        self.assertTrue({"projects.folders", "projects.account", "files.image", "files.search",
                         "conversations.rename", "conversations.cost", "roadmap.prompt"} <= used)
        self.assertEqual(sorted(used - known), [])

    def test_new_session_options_and_project_route(self):
        text = source("sessions-new.js")
        for token in ("projects.folders", "accounts.switch", "localStorage", "chat.providers",
                      "form.default_rights", "form.dangerous", '"aria-label": "Effort"', "Terminal"):
            self.assertIn(token, text)
        # listes communes au bureau (chat_options.new_session_form), plus de copie en dur
        self.assertNotIn('"bypassPermissions"', text)
        self.assertNotIn('["opus", "Opus"]', text)
        self.assertIn('PROJECT_PREFIX = "projet/"', source("sessions.js"))

    def test_terminal_key_bar_has_required_keys(self):
        text = source("terminal.js")
        for key in ('"Échap"', '"Tab"', '"ctrl"', '"←"', '"|"', '"~"', '"/"', '"-"', "Coller", "Copier"):
            self.assertIn(key, text)
        self.assertNotIn(".catch(() => {})", text.split("send(data)")[1].split("type(data)")[0])

    def run_js(self, code):
        """Exécute `code` (module) à côté d'une copie des modules, déclarée « module » pour node."""
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("terminal.js", "dom.js", "sessions-order.js"):
                shutil.copy(WEB / name, Path(tmp) / name)
            (Path(tmp) / "package.json").write_text('{"type": "module"}')
            r = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True,
                               timeout=30, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_control_char(self):
        out = self.run_js('import { controlChar as c } from "./terminal.js";'
                          'console.log(JSON.stringify([c("c"), c("C"), c("["), c("?"), c("1"), c("ab"), c("\\x1b[A")]));')
        self.assertEqual(out, '["\\u0003","\\u0003","\\u001b","\x7f","1","ab","\\u001b[A"]')

    ORDER_JS = ('const store = {}; globalThis.localStorage = { getItem: (k) => store[k] ?? null,'
                ' setItem: (k, v) => { store[k] = String(v); } };'
                'const o = await import("./sessions-order.js");'
                'const e = [["c1", { title: "Zeta", cwd: "/a/proj-b", state: "idle", sessionId: "s1", activeAt: 1 }],'
                ' ["c2", { title: "alpha", cwd: "/a/proj-a", state: "permission", sessionId: "s2", activeAt: 3 }],'
                ' ["term-1", { title: "Terminal", cwd: "/a/proj-a", term: true, activeAt: 2 }]];'
                'const ids = (l) => l.map(([k]) => k).join(",");')

    def test_session_sort_modes(self):
        out = self.run_js(self.ORDER_JS + 'console.log([o.getMode(), ...["manuel", "recent", "nom", "projet", "etat"]'
                          '.map((m) => ids(o.sortEntries(e, m)))].join(" "));')
        self.assertEqual(out, "manuel c1,c2,term-1 c2,term-1,c1 c2,term-1,c1 c2,term-1,c1 c2,c1,term-1")

    def test_session_manual_order_kept_and_switches_mode(self):
        """Déplacer une session passe en ordre manuel et garde l'ordre ; une session rouverte
        (nouvel identifiant de chat, même conversation) retrouve sa place ; une nouvelle va à la fin."""
        out = self.run_js(self.ORDER_JS + 'o.setMode("nom");'
                          'const a = o.move(e, "term-1", { target: "c1" });'
                          'const b = o.move(a, "c1", { delta: 1 });'
                          'const reopened = [["c9", { ...e[1][1] }], ["c8", { title: "new" }], ...e.filter(([k]) => k !== "c2")];'
                          'console.log(ids(a), ids(b), o.getMode(), ids(o.sortEntries(reopened)));')
        self.assertEqual(out, "term-1,c1,c2 term-1,c2,c1 manuel term-1,c9,c1,c8")

    def test_sessions_page_uses_order(self):
        text = source("sessions.js")
        self.assertIn("sortEntries([...tabs])", text)
        self.assertIn('dragProps(chatId, "x")', text)
        self.assertIn('dragProps(id, "y")', text)
        self.assertIn('"/sessions-order.js"', source("sw.js"))


if __name__ == "__main__":
    unittest.main()


class ManageProjectsAndTrashTest(unittest.TestCase):
    def test_web_add_remove_project_and_trash(self):
        """Web (phase 15) : ajouter un projet (dossier existant ou nouveau, git init), le retirer
        de la liste, supprimer une conversation (corbeille 30 jours) et la restaurer."""
        js = (WEB / "sessions-manage.js").read_text(encoding="utf-8")
        for rpc_name in ("projects.add", "projects.remove", "conversations.trash",
                         "trash.list", "trash.restore"):
            self.assertIn(f'"{rpc_name}"', js)
        sessions = (WEB / "sessions.js").read_text(encoding="utf-8")
        self.assertIn("./sessions-manage.js", sessions)
        self.assertIn("Ajouter un projet", sessions)
        self.assertIn("Corbeille", sessions)
        conv = (WEB / "sessions-conv.js").read_text(encoding="utf-8")
        self.assertIn("ctx.trash", conv)
        self.assertIn("/sessions-manage.js", (WEB / "sw.js").read_text(encoding="utf-8"))
