"""Chat web : logique pure testée avec node (diff des modifications, chemins cités, complétion,
recherche) et contrôles statiques (appels au pont, règles de la CSP, aucun alert/confirm)."""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccs_app.server import bridge, web

WEB = Path(web.WEB_DIR)
CHAT_JS = sorted(WEB.glob("chat*.js"))
NODE = shutil.which("node")


_COPY = None


def _copy():
    """Copie des modules dans un dossier « type: module » (le dossier web n'a pas de package.json)."""
    global _COPY
    if _COPY is None:
        _COPY = Path(tempfile.mkdtemp(prefix="ccs-webjs-"))
        for p in WEB.glob("*.js"):
            shutil.copy(p, _COPY / p.name)
        (_COPY / "package.json").write_text('{"type": "module"}')
    return _COPY


def tearDownModule():
    if _COPY is not None:
        shutil.rmtree(_COPY, ignore_errors=True)


def node(module, expr):
    """Évalue `expr` (avec `m` = le module importé) dans node et renvoie le JSON affiché."""
    script = f"import * as m from {json.dumps((_copy() / module).as_uri())};\nconsole.log(JSON.stringify({expr}));"
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr[-600:])
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node absent")
class DiffTest(unittest.TestCase):
    def test_edit_trims_common_lines(self):
        r = node("chat-diff.js", 'm.lineDiff("a\\nb\\nc\\n", "a\\nB\\nc\\n")')
        self.assertEqual(r, [{"t": " ", "s": "a"}, {"t": "-", "s": "b"}, {"t": "+", "s": "B"}, {"t": " ", "s": "c"}])

    def test_write_is_all_added(self):
        r = node("chat-diff.js", 'm.lineDiff("", "x\\ny")')
        self.assertEqual([l["t"] for l in r], ["+", "+"])

    def test_edit_diffs_for_each_tool(self):
        r = node("chat-diff.js", 'm.editDiffs("Edit", {file_path: "/p/a.py", old_string: "x", new_string: "y"})')
        self.assertEqual(r[0]["path"], "/p/a.py")
        self.assertEqual([l["t"] for l in r[0]["lines"]], ["-", "+"])
        r = node("chat-diff.js", 'm.editDiffs("MultiEdit", {file_path: "/p/a.py", edits: [{old_string: "1", new_string: "2"}, {old_string: "3", new_string: "4"}]})')
        self.assertEqual(len([l for l in r[0]["lines"] if l["t"] != "@"]), 4)
        r = node("chat-diff.js", 'm.editDiffs("Write", {file_path: "/p/n.txt", content: "a\\nb"})')
        self.assertEqual([l["t"] for l in r[0]["lines"]], ["+", "+"])
        self.assertEqual(node("chat-diff.js", 'm.editDiffs("Bash", {command: "ls"})'), None)

    def test_counts(self):
        self.assertEqual(node("chat-diff.js", 'm.countLines([{t:"+",s:"a"},{t:"-",s:"b"},{t:" ",s:"c"},{t:"+",s:"d"}])'),
                         {"add": 2, "del": 1})

    def test_unified_text_parse(self):
        r = node("chat-diff.js", 'm.parseUnified("--- a/x\\n+++ b/x\\n@@ -1 +1 @@\\n-a\\n+b\\n c\\n")')
        self.assertEqual([l["t"] for l in r], ["@", "-", "+", " "])


@unittest.skipUnless(NODE, "node absent")
class LinksTest(unittest.TestCase):
    FILES = '["src/a.py", "README.md", "ccs_app/web/chat.js"]'

    def ref(self, text):
        return node("chat-links.js", f'm.parsePathRef({json.dumps(text)}, "/home/u/p", new Set({self.FILES}))')

    def test_relative_with_line(self):
        self.assertEqual(self.ref("src/a.py:42"), {"path": "src/a.py", "line": 42})
        self.assertEqual(self.ref("./README.md"), {"path": "README.md", "line": None})

    def test_absolute_inside_project(self):
        self.assertEqual(self.ref("/home/u/p/src/a.py:3:7"), {"path": "src/a.py", "line": 3})

    def test_unknown_or_outside_is_not_a_link(self):
        self.assertIsNone(self.ref("src/zz.py"))
        self.assertIsNone(self.ref("/etc/passwd"))
        self.assertIsNone(self.ref("pas un chemin"))
        self.assertIsNone(self.ref("../src/a.py"))

    def test_find_in_text(self):
        r = node("chat-links.js", f'm.findRefs("Voir src/a.py:10 et `x` puis ccs_app/web/chat.js, ok", "/home/u/p", new Set({self.FILES}))')
        self.assertEqual([(x["path"], x["line"]) for x in r], [("src/a.py", 10), ("ccs_app/web/chat.js", None)])
        self.assertEqual(r[0]["text"], "src/a.py:10")


@unittest.skipUnless(NODE, "node absent")
class CompleteTest(unittest.TestCase):
    def tok(self, text, cursor=None):
        cursor = len(text) if cursor is None else cursor
        return node("chat-complete.js", f'm.detectToken({json.dumps(text)}, {cursor})')

    def test_slash_only_at_start(self):
        self.assertEqual(self.tok("/com"), {"kind": "/", "query": "com", "start": 0, "end": 4})
        self.assertIsNone(self.tok("dis /com"))
        self.assertIsNone(self.tok("/compact et"))

    def test_at_token(self):
        self.assertEqual(self.tok("regarde @src/a"), {"kind": "@", "query": "src/a", "start": 8, "end": 14})
        self.assertEqual(self.tok("@")["query"], "")
        self.assertIsNone(self.tok("mail a@b.fr "))
        self.assertEqual(self.tok("@a et plus", 2)["query"], "a")

    def test_rank_files_prefers_basename_prefix(self):
        r = node("chat-complete.js", 'm.rankFiles(["lib/zchat.js", "chat.js", "docs/chat-notes.md"], "chat")')
        self.assertEqual(r[0], "chat.js")
        self.assertEqual(len(r), 3)

    def test_filter_commands(self):
        r = node("chat-complete.js", 'm.rankCommands([{name:"review"},{name:"compact"},{name:"init"}], "co").map(c => c.name)')
        self.assertEqual(r, ["compact"])
        r = node("chat-complete.js", 'm.rankCommands([{name:"xcompact"},{name:"compact"}], "com").map(c => c.name)')
        self.assertEqual(r, ["compact", "xcompact"])


@unittest.skipUnless(NODE, "node absent")
class SearchTest(unittest.TestCase):
    def test_fold(self):
        self.assertEqual(node("chat-search.js", 'm.fold("Éléphant À")'), "elephant a")

    def test_find_indexes(self):
        r = node("chat-search.js", 'm.findIndexes(["Un chat", "le CHIEN", "chât noir"], "chat")')
        self.assertEqual(r, [0, 2])
        self.assertEqual(node("chat-search.js", 'm.findIndexes(["a"], "  ")'), [])

    def test_step_wraps(self):
        self.assertEqual(node("chat-search.js", "[m.step(0, 3, 1), m.step(2, 3, 1), m.step(0, 3, -1), m.step(0, 0, 1)]"), [1, 0, 2, -1])


@unittest.skipUnless(NODE, "node absent")
class ContextAlertTest(unittest.TestCase):
    """Alerte de contexte lourd du chat web, et sa disparition quand le pont compacte tout seul."""
    CFG = '{enabled: true, threshold_tokens: 150000}'

    def alert(self, ev, heavy="false", cfg=None):
        return node("chat-context.js", f"m.contextAlert({ev}, {cfg or self.CFG}, {heavy})")

    def test_alert_once_when_crossing_the_threshold(self):
        self.assertEqual(self.alert("{total: 160000}"), {"heavy": True, "gain": 128000})
        self.assertEqual(self.alert("{total: 170000}", heavy="true"), {"heavy": True, "gain": None})
        self.assertEqual(self.alert("{total: 40000}", heavy="true"), {"heavy": False, "gain": None})
        self.assertEqual(self.alert("{total: 160000}", cfg="{enabled: false, threshold_tokens: 150000}"),
                         {"heavy": False, "gain": None})

    def test_no_alert_when_the_bridge_compacts_by_itself(self):
        self.assertEqual(self.alert("{total: 160000, auto_compact: true}"), {"heavy": False, "gain": None})
        # réglage coupé ensuite : l'alerte et son bouton reviennent à la mesure suivante
        self.assertEqual(self.alert("{total: 160000, auto_compact: false}"), {"heavy": True, "gain": 128000})

    def test_same_estimate_as_the_desktop(self):
        from ccs_app import context_alert
        self.assertEqual(node("chat-context.js", "m.COMPACT_KEEP"), context_alert.COMPACT_KEEP)
        self.assertEqual(self.alert("{total: 150001}")["gain"], context_alert.compact_gain(150001))

    def test_usage_summary_like_python(self):
        from ccs_app import token_use
        for u in ({"cache_read": 35952, "cache_write": 15423, "input": 4, "output": 403, "cost_usd": 0.0365},
                  {"cache_read": 0, "cache_write": 0, "input": 2500, "output": 1_234_567, "cost_usd": 0},
                  {"output": 12}):
            self.assertEqual(node("chat-context.js", f"m.usageSummary({json.dumps(u)})"), token_use.summary(u))
        self.assertEqual(node("chat-context.js", "m.usageSummary({})"), "")

    def test_context_level(self):
        self.assertEqual(node("chat-context.js", "[m.contextLevel(10000), m.contextLevel(80000), m.contextLevel(150000),"
                                                 " m.contextLevel(60000, 100000)]"), ["ok", "warn", "crit", "warn"])

    def test_cache_expired_wiring(self):
        chat = (WEB / "chat.js").read_text()
        self.assertIn('case "CacheExpired":', chat)
        self.assertIn('"ccs:new-chat"', chat)
        self.assertIn("this.cacheExpired && !(isSlashCommand(text)", chat)
        self.assertIn("this.cacheExpired = null;", chat[chat.index('case "TurnResult":'):])

    def test_chat_wiring(self):
        chat = (WEB / "chat.js").read_text()
        self.assertIn("contextAlert(ev, (await this.workInfo()).context, this.heavy)", chat)
        self.assertIn('case "Notice": this.notice(ev.text', chat)                  # note du pont
        local = chat[chat.index('case "LocalCommand":'):chat.index('case "TextDelta":')]
        self.assertIn("this.requestContext()", local)                             # jauge à jour après /compact
        self.assertIn('"context_alert.auto_compact"', (WEB / "settings.js").read_text())


class StaticChatTest(unittest.TestCase):
    def text(self):
        return {p.name: p.read_text(encoding="utf-8") for p in CHAT_JS}

    def test_every_rpc_called_exists(self):
        b = bridge.build("alice", None, local=True, start_daemon=False, install_claude=False)
        known = set(b._handlers)
        for name, text in self.text().items():
            for m in re.finditer(r'call\("((?:work|chat|files|conversation)\.[a-z_.]+)"', text):
                self.assertIn(m.group(1), known, f"{name} : {m.group(1)}")

    def test_no_alert_confirm_or_unsafe_html(self):
        for name, text in self.text().items():
            self.assertIsNone(re.search(r"(?<![\w.])(alert|confirm|prompt)\(", text), name)
            self.assertNotIn("innerHTML", text, name)
            self.assertNotIn("insertAdjacentHTML", text, name)
            self.assertNotIn("outerHTML", text, name)
            self.assertIsNone(re.search(r"""\bon[a-z]+\s*=\s*["']""", text), name)
            self.assertNotIn(".style.cssText", text, name)

    def test_header_buttons_have_labels(self):
        text = self.text()["chat.js"]
        for label in ("Fichiers", "Feuille de route", "Git", "Options", "Arrêter", "Plus"):
            self.assertIn(f'"{label}"', text, label)
        self.assertIn("GitPanel", text)
        self.assertIn("openFile", text)

    def test_input_attributes(self):
        text = self.text()["chat.js"]
        for attr in ("enterkeyhint", "autocapitalize", 'aria-label": "Motif du refus"', 'aria-label": "Autre réponse"'):
            self.assertIn(attr, text, attr)

    def test_draft_and_send_failure_keep_text(self):
        text = self.text()["chat.js"]
        self.assertIn("localStorage", text)
        # le champ n'est vidé qu'après la réponse du pont
        send = text[text.index("async deliver("):]
        self.assertLess(send.index('"chat.send"'), send.index('this.input.value = ""'))

    def test_escape_interrupts_only_when_empty(self):
        text = self.text()["chat.js"]
        i = text.index('e.key === "Escape"')
        self.assertIn("!this.input.value", text[i:i + 300])

    def test_new_modules_are_in_service_worker(self):
        sw = (WEB / "sw.js").read_text(encoding="utf-8")
        missing = [p.name for p in CHAT_JS if f'"/{p.name}"' not in sw]
        self.assertEqual(missing, [], "à ajouter à SHELL de sw.js (fichier d'un autre lot)")


if __name__ == "__main__":
    unittest.main()


def node_script(body):
    """Exécute `body` (module ES, console.log du résultat JSON) dans node et renvoie ce JSON."""
    r = subprocess.run([NODE, "--input-type=module", "-e", body.replace("@WEB@", _copy().as_uri())],
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr[-600:])
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node absent")
class RevueWebTest(unittest.TestCase):
    def test_queued_calls_survive_a_failed_attempt(self):
        """Un appel mis en file pendant une coupure n'est pas rejeté (il partirait quand même) ;
        seul un appel déjà envoyé l'est."""
        r = node_script("""
globalThis.location = { protocol: "https:", host: "x" };
class WS { static OPEN = 1; constructor() { this.readyState = 0; this.sent = []; WS.last = this; }
  send(m) { this.sent.push(m); } close() {} }
globalThis.WebSocket = WS;
const { Api } = await import("@WEB@/api.js");
const api = new Api();
api.connect();
const ws = WS.last;
const queued = api.call("a");                  // hors ligne : en file
let state = "pending";
queued.then(() => { state = "ok"; }, () => { state = "rejected"; });
ws.onclose();                                  // la tentative échoue
api.stopped = true;
await new Promise((r) => setTimeout(r, 10));
const keptInQueue = api.queue.length;
console.log(JSON.stringify({ state, keptInQueue }));
process.exit(0);
""")
        self.assertEqual(r, {"state": "pending", "keptInQueue": 1})

    def test_sent_call_is_rejected_on_close(self):
        r = node_script("""
globalThis.location = { protocol: "https:", host: "x" };
class WS { static OPEN = 1; constructor() { this.readyState = 0; this.sent = []; WS.last = this; }
  send(m) { this.sent.push(m); } close() {} }
globalThis.WebSocket = WS;
const { Api } = await import("@WEB@/api.js");
const api = new Api();
api.connect();
const ws = WS.last;
ws.readyState = 1;
ws.onopen();
let code = null;
const p = api.call("a").catch((e) => { code = e.code; });
ws.onclose();
api.stopped = true;
await p;
console.log(JSON.stringify({ code, sent: ws.sent.length }));
process.exit(0);
""")
        self.assertEqual(r, {"code": "hors_ligne", "sent": 1})

    def test_find_refs_without_lookbehind(self):
        src = (WEB / "chat-links.js").read_text()
        self.assertNotIn("(?<", src)
        r = node("chat-links.js", 'm.findRefs("voir (src/a.py:3) et x/src/a.py", "/p", new Set(["src/a.py"]))')
        self.assertEqual([(x["path"], x["line"], x["index"]) for x in r], [("src/a.py", 3, 6)])

    def test_restored_tab_history_stops_where_the_buffer_starts(self):
        """Onglet restauré : le journal n'est lu qu'après le rattachement, jusqu'à history_before
        (le reste vient du tampon du pont), et placé au-dessus du fil."""
        chat = (WEB / "chat.js").read_text()
        self.assertFalse("if (history) this.loadHistory(history);" in chat, "historique lu trop tôt")
        self.assertTrue("this.startHistory(r.history_before)" in chat, "history_before inutilisé")
        self.assertTrue("before: h.before" in chat, "before non transmis")
        load = chat[chat.index("async loadHistory("):chat.index("async loadFullHistory(")]
        self.assertTrue("insertBefore" in load and "this.append(" not in load, "historique pas au-dessus")

    def test_rewind_body_lists_skipped_files(self):
        plan = {"steps": [{"path": "/p/a.txt", "deleted": False, "user_edited": False, "sha256": "x"}],
                "skipped": ["/etc/hors"]}
        r = node("chat-changes.js", f"m.rewindBody({json.dumps(plan)}, '/p')")
        self.assertIn("a.txt", r)
        self.assertNotIn("/p/a.txt", r)
        self.assertIn("hors des dossiers permis", r)
        self.assertIn("/etc/hors", r)

    def test_roles_in_preview_and_state_fixes(self):
        conv = (WEB / "sessions-conv.js").read_text()
        self.assertIn('role === "user"', conv)
        chat = (WEB / "chat.js").read_text()
        self.assertIn("CYCLE_RIGHTS", chat)
        self.assertNotIn("RIGHTS.map(([v]) => v)", chat)
        self.assertIn('"chat.context"', chat)
        self.assertIn("introuvable", chat)
        self.assertIn("ccs-draft:${cwd}|${chatId}", chat)
        self.assertIn("done: want", (WEB / "roadmap.js").read_text())
        self.assertIn("header: h.header", (WEB / "git.js").read_text())
        self.assertIn("if (r.ok)", (WEB / "sw.js").read_text())


class WideScreenTest(unittest.TestCase):
    def test_thread_and_composer_share_centered_column(self):
        """Grand écran : le fil et la zone de saisie forment une même colonne centrée (pas de fil
        calé à gauche avec les messages de l'utilisateur tout à droite de l'écran)."""
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"--chat-column:\s*\d+px")
        col = r"padding-inline:\s*max\(\d+px,\s*calc\(\(100% - var\(--chat-column\)\) / 2\)\)"
        for sel in (".thread", ".composer"):
            rules = re.findall(r"(?:^|\n)([^{}\n]*)\{([^}]*)\}", css)
            hit = [body for head, body in rules
                   if sel in [s.strip() for s in head.split(",")] and re.search(col, body)]
            self.assertTrue(hit, f"{sel} : pas de colonne centrée")

    def test_radio_and_checkbox_keep_native_size(self):
        """Question à choix (web) : les boutons radio ne prennent pas le style des champs de
        texte (largeur 100 %, grands ronds, libellé repoussé à droite)."""
        css = (WEB / "style.css").read_text(encoding="utf-8")
        rule = re.search(r'\ninput\[type="checkbox"\], input\[type="radio"\] \{([^}]*)\}', css)
        self.assertTrue(rule, "pas de règle commune case à cocher / radio")
        for decl in ("width: 22px", "min-height: 0", "flex: none"):
            self.assertIn(decl, rule.group(1), decl)

    def test_consecutive_tools_grouped(self):
        """Fil (surtout au téléphone) : les actions qui se suivent forment une ligne repliable
        « N actions », aussi dans l'historique rechargé ; la recherche ouvre le groupe."""
        js = (WEB / "chat.js").read_text(encoding="utf-8")
        self.assertIn('class: "tool-group"', js)
        self.assertEqual(js.count("this.regroup();"), 2)
        self.assertIn('closest("details.tool-group")', (WEB / "chat-search.js").read_text(encoding="utf-8"))
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".tool-group-body", css)


class FollowAndCopyTest(unittest.TestCase):
    def setUp(self):
        self.js = (WEB / "chat.js").read_text(encoding="utf-8")

    def test_thread_follows_new_messages(self):
        """Web : le fil descend tout seul quand Claude écrit (texte rendu après coup compris),
        tant que l'utilisateur n'est pas remonté lire plus haut."""
        self.assertIn('t.addEventListener("scroll", () => this.scrolled()', self.js)
        render = re.search(r"\n  async render\(node, markdown\) \{(.*?)\n  \}\n", self.js, re.S)
        self.assertTrue(render)
        self.assertIn("this.follow", render.group(1))

    def test_working_indicator_above_composer(self):
        """Web : « Claude travaille… » en bas à gauche, au-dessus de la saisie, comme au bureau."""
        self.assertIn('class: "working"', self.js)
        css = (WEB / "chat.css").read_text(encoding="utf-8")
        self.assertIn(".working", css)

    def test_code_blocks_have_copy_button(self):
        """Web : chaque bloc de code des réponses a un bouton Copier."""
        self.assertIn('class: "copy-code', self.js)
        self.assertIn("clipboard", self.js)


class RoadmapOrderAndPanesTest(unittest.TestCase):
    def test_roadmap_phases_in_file_order(self):
        """Web : les phases dans l'ordre du fichier (comme au bureau), pas inversées."""
        js = (WEB / "roadmap.js").read_text(encoding="utf-8")
        self.assertNotIn(".reverse()", js)
        self.assertIn("for (const phase of r.phases)", js)

    def test_sections_resizable_and_hideable(self):
        """Web : la liste des sessions et le volet (Fichiers, Feuille de route, Git…) se
        redimensionnent à la souris (largeur gardée) ; la liste peut être masquée."""
        dom = (WEB / "dom.js").read_text(encoding="utf-8")
        self.assertIn("export function resizable", dom)
        self.assertIn("localStorage", dom)
        self.assertIn("resizable(this.drawer", (WEB / "chat.js").read_text(encoding="utf-8"))
        sessions = (WEB / "sessions.js").read_text(encoding="utf-8")
        self.assertIn("resizable(side", sessions)
        self.assertIn("side-hidden", sessions)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".resize-handle", css)
        self.assertIn(".side-hidden", css)

    def test_copy_button_in_header_not_over_code(self):
        """Web : le bouton Copier est dans une barre au-dessus du code (langue à gauche), jamais
        posé par-dessus une longue commande."""
        js = (WEB / "chat.js").read_text(encoding="utf-8")
        self.assertIn('class: "code-head"', js)
        css = (WEB / "chat.css").read_text(encoding="utf-8")
        self.assertNotIn("position: absolute; top: 4px; right: 4px", css)
        self.assertIn(".code-head", css)


class PhoneErgonomicsTest(unittest.TestCase):
    def test_plus_menu_opens_under_header(self):
        """Téléphone : le menu « Plus » se place sous l'en-tête du chat, pas sous tout le chat
        (hors de l'écran) : l'en-tête doit être le conteneur positionné du menu."""
        css = (WEB / "chat.css").read_text(encoding="utf-8")
        import re
        head = re.search(r"\.chat-head \{([^}]*)\}", css).group(1)
        self.assertIn("position: relative", head)

    def test_phone_single_header_and_light_composer(self):
        """Téléphone : une seule barre en haut (retour, titre, actions) au lieu de deux, une zone
        de saisie qui laisse la place au texte (bouton d'envoi en icône, boutons plus petits)."""
        js = (WEB / "chat.js").read_text(encoding="utf-8")
        self.assertIn('class: "flat back-chat phone-only"', js)
        self.assertIn("this.host?.back", js)
        self.assertIn("back: () =>", (WEB / "sessions.js").read_text(encoding="utf-8"))
        css = (WEB / "style.css").read_text(encoding="utf-8")
        phone = "".join(re.findall(r"@media \(max-width: 719px\) \{(.*?)\n\}", css, re.S))
        self.assertIn(".sessions.chat-tab .tabs-row { display: none; }", phone)
        self.assertIn(".send-label { display: none; }", phone)


@unittest.skipUnless(NODE, "node absent")
class QuoteTest(unittest.TestCase):
    """Répondre en citant : même format que le bureau (ccs_app/chat_quote.py)."""

    def test_same_result_as_python(self):
        from ccs_app import chat_quote as quote
        from tests.test_chat_quote import SAMPLES
        extra = [("claude", "mot " * 400, "x"), ("moi", "y" * 5000, ""), ("claude", "é😀 " * 600, "z")]
        for author, quoted, body in SAMPLES + extra:
            with self.subTest(quoted=quoted[:30]):
                args = ", ".join(json.dumps(v) for v in (author, quoted, body))
                r = node("chat-quote.js", f"(() => {{ const c = m.compose({args}); const s = m.split(c);"
                                          f" return [c, s, m.excerpt({json.dumps(quoted)}), m.sourceText(c)]; }})()")
                composed = quote.compose(author, quoted, body)
                s = quote.split(composed)
                self.assertEqual(r[0], composed)
                self.assertEqual(r[1], {"author": s.author, "text": s.text, "body": s.body})
                self.assertEqual(r[2], quote.excerpt(quoted))
                self.assertEqual(r[3], quote.source_text(composed))

    def test_plain_messages_have_no_quote(self):
        for text in ("Bonjour", "> une citation tapée\n\nsuite", "> **Claude :**", "> **Quelqu'un :**\n> x\n\ny", ""):
            with self.subTest(text=text):
                self.assertIsNone(node("chat-quote.js", f"m.split({json.dumps(text)})"))
        self.assertIsNone(node("chat-quote.js", "m.split(null)"))
        self.assertEqual(node("chat-quote.js", 'm.compose("claude", "  ", "réponse")'), "réponse")

    def test_constants_and_one_line(self):
        from ccs_app import chat_quote as quote
        self.assertEqual(node("chat-quote.js", "[m.QUOTE_MAX, m.SELECTION_MAX, m.CUT_MARK, m.LABELS, m.SHOWN]"),
                         [quote.QUOTE_MAX, quote.SELECTION_MAX, quote.CUT_MARK, quote.LABELS, quote.SHOWN])
        self.assertEqual(node("chat-quote.js", 'm.oneLine("a\\n\\n  b\\tc")'), quote.one_line("a\n\n  b\tc"))
        self.assertEqual(node("chat-quote.js", 'm.oneLine("x".repeat(200), 10)'), quote.one_line("x" * 200, 10))
