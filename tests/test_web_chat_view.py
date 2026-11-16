"""Chat web exécuté dans node avec un faux DOM (tests/web_dom.mjs) : il n'y a pas de navigateur
sur la machine qui construit les paquets. Fil, envoi, et répondre en citant un message."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccs_app import chat_quote as quote
from ccs_app.server import web

WEB = Path(web.WEB_DIR)
NODE = shutil.which("node")
_COPY = None

PRELUDE = r"""
import { installDom, settle } from "./web_dom.mjs";
const win = installDom();
const { ChatView } = await import("./chat.js");
const calls = [];
const handlers = new Map();
let history = [];
const api = {
  on(name, fn) { handlers.set(name, fn); return () => handlers.delete(name); },
  async call(method, params) {
    calls.push([method, params]);
    switch (method) {
      case "chat.attach": return { seq: 0, events: [], state: "idle", session_id: "s1", options: { model: "", effort: "", rights: "manual" } };
      case "chat.render": if (api.failRender) throw new Error("coupure"); return { html: params.markdown };
      case "chat.send": if (api.failSend) throw new Error("coupure"); return { ok: true, uuid: params.uuid };
      case "chat.tags": return { messages: api.tagMap || {}, known: ["important", "à revoir"] };
      case "chat.tag": return { entry: params.tags.length ? { tags: params.tags, role: params.role, excerpt: params.text, ts: 1 } : null };
      case "work.commands": return { commands: [], context: { enabled: true, threshold_tokens: 150000 } };
      case "work.files": return { files: [] };
      case "conversation.messages": return { messages: history };
      default: return {};
    }
  },
};
const sent = () => calls.filter((c) => c[0] === "chat.send").map((c) => c[1]);
const root = document.createElement("div");
document.body.append(root);
const open = (opts = {}) => new ChatView(root, api, { chatId: "c1", cwd: "/p", title: "Essai", ...opts });
const shape = (view) => view.thread.children.map((n) => `${n.className} | ${n.textContent}`);
const msgs = (view) => view.thread.querySelectorAll(".msg");
const act = (msg, key = "reply") => msg.querySelectorAll(".msg-act").find((b) => b.dataset.act === key);
const type = (view, text) => { view.input.value = text; view.input.dispatchEvent(new win.Event("input")); };
const submit = async (view) => { view.form.querySelector("button.send").click(); await settle(); };
const live = async (view, ...events) => { let n = view.seq; for (const event of events) view.receive({ seq: ++n, event }); await settle(); };
let out = null;
"""


def _copy():
    global _COPY
    if _COPY is None:
        _COPY = Path(tempfile.mkdtemp(prefix="ccs-webview-"))
        for p in WEB.glob("*.js"):
            shutil.copy(p, _COPY / p.name)
        shutil.copy(Path(__file__).with_name("web_dom.mjs"), _COPY / "web_dom.mjs")
        (_COPY / "package.json").write_text('{"type": "module"}')
    return _COPY


def tearDownModule():
    if _COPY is not None:
        shutil.rmtree(_COPY, ignore_errors=True)


def run(body):
    """Exécute `body` après le prélude (vue `open()`, faux pont `api`, `calls`) ; renvoie `out`."""
    script = _copy() / "scenario.mjs"
    script.write_text(PRELUDE + body + "\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    r = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60, cwd=_copy())
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE, "node absent")
class ThreadTest(unittest.TestCase):
    def test_messages_and_send(self):
        out = run("""
const view = open();
await settle();
await live(view, { type: "UserSent", text: "Bonjour", images: 0, nonce: "x" },
                 { type: "TextDelta", msg_id: "m1", index: 0, text: "Sal" },
                 { type: "AssistantText", msg_id: "m1", text: "Salut **toi**" });
type(view, "Ma réponse");
await submit(view);
out = { shape: shape(view), sent: sent(), input: view.input.value, raw: msgs(view).map((m) => [m.author, m.raw]) };
""")
        self.assertEqual(out["shape"], ["msg user | Bonjour", "msg claude | Salut **toi**", "msg user | Ma réponse"])
        self.assertEqual(out["raw"], [["moi", "Bonjour"], ["claude", "Salut **toi**"], ["moi", "Ma réponse"]])
        self.assertEqual(len(out["sent"]), 1)
        self.assertEqual({k: out["sent"][0][k] for k in ("chat_id", "text", "shown", "images")},
                         {"chat_id": "c1", "text": "Ma réponse", "shown": "Ma réponse", "images": []})
        self.assertEqual(out["input"], "")

    def test_thread_follows_the_bottom_until_the_user_goes_up(self):
        out = run("""
const view = open();
await settle();
const t = view.thread;
const at = (top, height = 1000) => { t.scrollHeight = height; t.clientHeight = 400; t.scrollTop = top; t.dispatchEvent(new win.Event("scroll")); return view.follow; };
out = {};
out.bottom = at(600);
out.grew = at(600, 1500);                 // le fil a grandi sans geste : on suit toujours
view.restick();
out.back = t.scrollTop;
out.up = at(300, 1500);                   // l'utilisateur remonte : on lâche
view.restick();
out.left = t.scrollTop;
const btn = view.node.querySelector(".to-bottom");
out.button = [view.node.querySelector(".thread-wrap").contains(btn), btn.hidden];   // remonté : le bouton s'offre
btn.click();
out.button.push(btn.hidden && view.follow && t.scrollTop === 1500);                 // un appui ramène en bas
at(300, 1500);
out.down = at(500, 1500);                 // il redescend sans atteindre le bas : toujours lâché
out.end = at(1090, 1500);                 // revenu en bas : on suit de nouveau
t.dispatchEvent(Object.assign(new win.Event("wheel"), { deltaY: -3 }));
out.wheel = view.follow;
view.toBottom();
t.dispatchEvent(new win.Event("touchstart"));
t.scrollTop = 1000; view.restick();
out.touching = t.scrollTop;               // doigt posé : on ne tire pas le fil
t.dispatchEvent(new win.Event("touchend"));
view.restick();
out.released = t.scrollTop;
""")
        self.assertEqual(out.pop("button"), [True, False, True])
        self.assertEqual(out, {"bottom": True, "grew": True, "back": 1500, "up": False, "left": 300,
                               "down": False, "end": True, "wheel": False, "touching": 1000,
                               "released": 1500})

    def test_search_does_not_see_the_action_buttons(self):
        """Les boutons d'un message n'ont pas de texte : « répondre » ne trouve que les vrais messages."""
        out = run("""
const view = open();
await settle();
await live(view, { type: "UserSent", text: "Bonjour", images: 0, nonce: "x" },
                 { type: "AssistantText", msg_id: "m1", text: "Je vais répondre" });
out = { texts: msgs(view).map((m) => m.textContent), labels: msgs(view).map((m) => act(m).getAttribute("aria-label")) };
""")
        self.assertEqual(out["texts"], ["Bonjour", "Je vais répondre"])
        self.assertEqual(out["labels"], ["Répondre", "Répondre"])


@unittest.skipUnless(NODE, "node absent")
class ReplyTest(unittest.TestCase):
    """Répondre en citant un message."""

    START = """
const view = open();
await settle();
await live(view, { type: "UserSent", text: "Ajoute un bouton", images: 0, nonce: "x" },
                 { type: "AssistantText", msg_id: "m1", text: "Deux options :\\n\\n- A\\n- B" });
const [mine, claude] = msgs(view);
"""

    def test_reply_to_claude(self):
        out = run(self.START + """
act(claude).click();
const bar = { hidden: view.quoteBar.hidden, text: view.quoteBar.textContent, author: view.quoteBar.querySelector(".quote-bar-text").dataset.author,
              focused: document.activeElement === view.input };
type(view, "Prends la B");
await submit(view);
const bubble = msgs(view)[2];
out = { bar, sent: sent()[0], after: { hidden: view.quoteBar.hidden, quote: view.quote, input: view.input.value },
        quoted: bubble.querySelector(".quoted").dataset, quotedText: bubble.querySelector(".quoted-text").textContent,
        bubble: bubble.textContent, raw: bubble.raw };
""")
        composed = quote.compose("claude", "Deux options :\n\n- A\n- B", "Prends la B")
        self.assertEqual(out["bar"], {"hidden": False, "text": "Deux options : - A - B×", "author": "Réponse à Claude", "focused": True})
        self.assertEqual(out["sent"]["text"], composed)
        self.assertEqual(out["sent"]["shown"], composed)
        self.assertEqual(out["after"], {"hidden": True, "quote": None, "input": ""})
        self.assertEqual(out["quoted"], {"author": "Claude", "key": "claude"})
        self.assertEqual(out["quotedText"], "Deux options :\n\n- A\n- B")
        self.assertEqual(out["bubble"], "Deux options :\n\n- A\n- BPrends la B")
        self.assertEqual(out["raw"], composed)

    def test_reply_to_my_own_message_and_cancel(self):
        out = run(self.START + """
act(mine).click();
const first = { author: view.quoteBar.querySelector(".quote-bar-text").dataset.author, quote: view.quote };
view.quoteBar.querySelector("button").click();
const cancelled = { hidden: view.quoteBar.hidden, quote: view.quote };
act(mine).click();
view.input.dispatchEvent(new win.Event("keydown", { key: "Escape" }));
const escaped = view.quote;
type(view, "sans citation");
await submit(view);
out = { first, cancelled, escaped, sent: sent()[0].text };
""")
        self.assertEqual(out["first"], {"author": "Réponse à ton message", "quote": {"author": "moi", "text": "Ajoute un bouton"}})
        self.assertEqual(out["cancelled"], {"hidden": True, "quote": None})
        self.assertIsNone(out["escaped"])
        self.assertEqual(out["sent"], "sans citation")

    def test_selected_passage_is_quoted_alone(self):
        out = run(self.START + """
win.setSelection("- B", claude.content);
act(claude).dispatchEvent(new win.Event("pointerdown"));
win.setSelection("", null);                       // le clic défait la sélection : elle a été relevée à l'appui
act(claude).click();
const picked = view.quote;
win.setSelection("ailleurs", mine.content);        // sélection dans un autre message : ignorée
act(claude).click();
out = { picked, other: view.quote };
""")
        self.assertEqual(out["picked"], {"author": "claude", "text": "- B"})
        self.assertEqual(out["other"], {"author": "claude", "text": "Deux options :\n\n- A\n- B"})

    def test_long_message_is_cut_and_reply_to_a_reply_skips_its_quote(self):
        out = run("""
const view = open();
await settle();
await live(view, { type: "AssistantText", msg_id: "m1", text: "mot ".repeat(600) },
                 { type: "UserSent", text: "> **Claude :**\\n> A ou B ?\\n\\nLa B", images: 0, nonce: "x" });
const [claude, mine] = msgs(view);
act(claude).click();
const long = view.quote.text;
act(mine).click();
out = { long: [long.length, long.slice(-7)], nested: view.quote };
""")
        self.assertEqual(out["long"], [len(quote.excerpt("mot " * 600)), "mot […]"])
        self.assertEqual(out["nested"], {"author": "moi", "text": "La B"})

    def test_shell_notes_go_after_the_quote(self):
        out = run(self.START + """
view.shellNotes.push("J'ai lancé `ls` :\\n```\\na\\n```\\n\\n");
act(claude).click();
type(view, "Et maintenant ?");
await submit(view);
out = sent()[0];
""")
        self.assertEqual(out["text"], quote.compose("claude", "Deux options :\n\n- A\n- B",
                                                    "J'ai lancé `ls` :\n```\na\n```\n\nEt maintenant ?"))
        self.assertEqual(out["shown"], quote.compose("claude", "Deux options :\n\n- A\n- B", "Et maintenant ?"))

    def test_quote_is_kept_when_the_send_fails_and_without_text(self):
        out = run(self.START + """
act(claude).click();
await submit(view);                                // rien de tapé : rien ne part
const empty = sent().length;
api.failSend = true;
type(view, "essai");
await submit(view);
const failed = { quote: view.quote, input: view.input.value, bubbles: msgs(view).length };
api.failSend = false;
await submit(view);
out = { empty, failed, sentText: sent().at(-1).text, quote: view.quote };
""")
        self.assertEqual(out["empty"], 0)
        self.assertEqual(out["failed"], {"quote": {"author": "claude", "text": "Deux options :\n\n- A\n- B"}, "input": "essai", "bubbles": 2})
        self.assertEqual(out["sentText"], quote.compose("claude", "Deux options :\n\n- A\n- B", "essai"))
        self.assertIsNone(out["quote"])

    def test_quote_survives_a_reload_like_the_draft(self):
        out = run(self.START + """
act(claude).click();
view.destroy();
const again = open();
await settle();
const kept = { quote: again.quote, hidden: again.quoteBar.hidden };
again.clearQuote();
again.destroy();
const third = open();
await settle();
localStorage.setItem(third.quoteKey, "{pas du json");
third.loadQuote();
out = { kept, third: third.quote };
""")
        self.assertEqual(out["kept"], {"quote": {"author": "claude", "text": "Deux options :\n\n- A\n- B"}, "hidden": False})
        self.assertIsNone(out["third"])

    def test_history_and_other_devices_show_the_quote(self):
        out = run("""
history = [{ role: "assistant", text: "A ou B ?", msg_id: "m0" },
           { role: "utilisateur", text: "> **Claude :**\\n> A ou B ?\\n\\nLa B" }];
const view = open({ history: "/j.jsonl" });
await settle();
await live(view, { type: "UserSent", text: "> **Moi :**\\n> La B\\n\\nNon, la A", images: 0, nonce: "autre-appareil" });
const [old, reply, other] = msgs(view);
act(old).click();
out = { reply: [reply.querySelector(".quoted").dataset.author, reply.querySelector(".quoted-text").textContent, reply.textContent],
        other: [other.querySelector(".quoted").dataset.author, other.textContent], quoteFromHistory: view.quote };
""")
        self.assertEqual(out["reply"], ["Claude", "A ou B ?", "A ou B ?La B"])
        self.assertEqual(out["other"], ["Toi", "La BNon, la A"])
        self.assertEqual(out["quoteFromHistory"], {"author": "claude", "text": "A ou B ?"})

    def test_touch_shows_the_actions_and_a_click_unfolds_the_quote(self):
        out = run(self.START + """
mine.content.click();                              // à la souris : un clic ne change rien (survol)
const mouse = mine.classList.contains("picked");
win.media.add("(hover: none)");                    // écran tactile
mine.content.click();
const first = [mine.classList.contains("picked"), claude.classList.contains("picked")];
const shown = mine.querySelector(".msg-actions").scrolledIntoView;   // amenée à l'écran (dernier message)
claude.content.click();
const second = [mine.classList.contains("picked"), claude.classList.contains("picked")];
act(claude).click();                               // « Répondre » : la rangée se referme
const third = claude.classList.contains("picked");
type(view, "ok");
await submit(view);
const quoted = msgs(view)[2].querySelector(".quoted");
quoted.querySelector(".quoted-text").click();
claude.content.click();
claude.content.click();                            // toucher de nouveau referme la rangée
out = { mouse, first, shown, second, third, open: quoted.classList.contains("open"), picked: msgs(view)[2].classList.contains("picked"),
        closed: claude.classList.contains("picked") };
""")
        self.assertEqual(out, {"mouse": False, "first": [True, False], "shown": 1, "second": [False, True], "third": False,
                               "open": True, "picked": False, "closed": False})

    def test_touch_selection_opens_the_actions_of_its_message(self):
        out = run(self.START + """
const fire = () => document.dispatchEvent(new win.Event("selectionchange"));
win.setSelection("- B", claude.content.firstChild);
fire();
const mouse = claude.classList.contains("picked");  // à la souris : rien, le survol suffit
win.media.add("(hover: none)");
fire();
const touch = [mine.classList.contains("picked"), claude.classList.contains("picked")];
act(claude).dispatchEvent(new win.Event("pointerdown"));
win.setSelection("", null);
fire();                                             // sélection défaite : la rangée reste ouverte
act(claude).click();
view.destroy();
fire();                                             // plus d'écoute après la fermeture du chat
out = { mouse, touch, quote: view.quote };
""")
        self.assertEqual(out, {"mouse": False, "touch": [False, True], "quote": {"author": "claude", "text": "- B"}})

    def test_quoted_answer_of_claude_is_rendered_and_mine_stays_as_typed(self):
        """Une réponse de Claude citée est du Markdown (rendu par le pont) ; un message de
        l'utilisateur cité reste tel quel, comme dans sa bulle."""
        out = run("""
const view = open();
await settle();
await live(view, { type: "UserSent", text: "> **Claude :**\\n> **A** ou B ?\\n\\nLa B", images: 0, nonce: "x" },
                 { type: "UserSent", text: "> **Moi :**\\n> ligne 1\\n> ligne 2\\n\\nsuite", images: 0, nonce: "y" });
const [toClaude, toMe] = msgs(view).map((m) => m.querySelector(".quoted-text"));
const asked = calls.filter((c) => c[0] === "chat.render").map((c) => c[1].markdown);
api.failRender = true;                              // pont coupé : le texte tel quel reste affiché
await live(view, { type: "UserSent", text: "> **Claude :**\\n> *C* ?\\n\\nOui", images: 0, nonce: "z" });
const plain = msgs(view)[2].querySelector(".quoted-text");
out = { claude: [toClaude.classList.contains("rendered"), toClaude.children.map((n) => n.tagName), toClaude.textContent],
        mine: [toMe.classList.contains("rendered"), toMe.children.length, toMe.textContent], asked,
        plain: [plain.classList.contains("rendered"), plain.children.length, plain.textContent] };
""")
        self.assertEqual(out["claude"], [True, ["P"], "**A** ou B ?"])
        self.assertEqual(out["mine"], [False, 0, "ligne 1\nligne 2"])
        self.assertEqual(out["asked"], ["**A** ou B ?"])
        self.assertEqual(out["plain"], [False, 0, "*C* ?"])

    def test_link_in_a_quote_opens_without_unfolding_it(self):
        out = run("""
const view = open();
await settle();
await live(view, { type: "UserSent", text: "> **Claude :**\\n> Voir [la doc](https://exemple.fr)\\n\\nMerci", images: 0, nonce: "x" });
const quoted = msgs(view)[0].querySelector(".quoted");
const link = document.createElement("a");          // le faux DOM n'analyse pas le HTML rendu
quoted.querySelector(".quoted-text").append(link);
link.click();
const afterLink = quoted.classList.contains("open");
quoted.querySelector(".quoted-text").click();
out = { afterLink, afterText: quoted.classList.contains("open") };
""")
        self.assertEqual(out, {"afterLink": False, "afterText": True})


@unittest.skipUnless(NODE, "node absent")
class TagsTest(unittest.TestCase):
    """Étiquettes sur les messages : identifiant stable, feuille « Étiqueter », pastilles, volet."""

    def test_sent_message_has_an_uuid_and_claude_its_msg_id(self):
        out = run("""
const view = open({ sessionId: "s1" });
await settle();
await live(view, { type: "UserSent", text: "D'ailleurs", images: 0, nonce: "x", uuid: "u-autre" },
                 { type: "AssistantText", msg_id: "msg_1", text: "Oui" });
type(view, "Bonjour");
await submit(view);
out = { ids: msgs(view).map((m) => m.msgId), uuid: sent()[0].uuid };
""")
        self.assertRegex(out["uuid"], r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        self.assertEqual(out["ids"], ["u-autre", "msg_1", out["uuid"]])

    def test_tag_a_message_then_remove(self):
        out = run("""
const view = open({ sessionId: "s1" });
await settle();
await live(view, { type: "AssistantText", msg_id: "msg_1", text: "Réponse **utile**" });
const claude = msgs(view)[0];
act(claude, "tag").click();
await settle();
const dlg = document.body.querySelector("dialog.tag-sheet");
const suggestions = dlg.querySelectorAll(".tag-suggest .tag-chip").map((b) => b.textContent);
const input = dlg.querySelector("input");
input.value = "Important, à revoir ,important";
dlg.querySelectorAll("button").find((b) => b.textContent === "Valider").click();
await settle();
const tagCall = calls.find((c) => c[0] === "chat.tag")[1];
const chips = claude.querySelectorAll(".msg-tags .tag-chip").map((b) => b.textContent);
const order = claude.children.map((c) => c.className);
// retrait annoncé par un autre appareil
handlers.get("chat.tags")({ session_id: "s1", msg_id: "msg_1", entry: null });
out = { suggestions, tagCall, chips, order, after: claude.querySelectorAll(".tag-chip").length,
        sheetGone: !document.body.querySelector("dialog.tag-sheet") };
""")
        self.assertEqual(out["suggestions"], ["+ important", "+ à revoir"])
        self.assertEqual(out["tagCall"], {"session_id": "s1", "msg_id": "msg_1", "tags": ["Important", "à revoir"],
                                          "text": "Réponse **utile**", "role": "assistant"})
        self.assertEqual(out["chips"], ["Important", "à revoir"])
        self.assertEqual(out["order"], ["md", "msg-tags", "msg-actions"])
        self.assertEqual(out["after"], 0)
        self.assertTrue(out["sheetGone"])

    def test_history_tags_panel_and_jump(self):
        out = run("""
api.tagMap = { "u-1": { tags: ["important"], role: "utilisateur", excerpt: "Ajoute un bouton", ts: 2 },
               "msg_1": { tags: ["important", "doc"], role: "assistant", excerpt: "Voilà", ts: 1 } };
history = [{ role: "utilisateur", text: "Ajoute un bouton", uuid: "u-1" },
           { role: "assistant", text: "Voilà", msg_id: "msg_1" }];
const view = open({ sessionId: "s1", history: { path: "/j.jsonl", loaded: 0, full: false } });
await settle();
view.startHistory(0);
await settle();
const chips = msgs(view).map((m) => m.querySelectorAll(".tag-chip").map((b) => b.textContent));
msgs(view)[0].querySelector(".tag-chip").click();
await settle();
const panel = view.drawer.querySelector(".tags-panel");
const groups = panel.querySelectorAll(".tag-group").map((g) => [g.querySelector("strong").textContent, g.open,
  g.querySelectorAll(".tag-item").map((b) => b.textContent)]);
panel.querySelectorAll(".tag-item")[0].click();
await settle();
const target = msgs(view)[1];
out = { chips, kind: view.drawer.dataset.kind, hidden: view.drawer.hidden, groups,
        jumped: target.scrolledIntoView || 0, flash: target.classList.contains("flash") };
""")
        self.assertEqual(out["chips"], [["important"], ["important", "doc"]])
        self.assertEqual((out["kind"], out["hidden"]), ("tags", False))
        self.assertEqual(out["groups"], [["doc", False, ["ClaudeVoilà"]],
                                         ["important", True, ["ClaudeVoilà", "MoiAjoute un bouton"]]])
        self.assertEqual((out["jumped"], out["flash"]), (1, True))

    def test_no_session_yet_no_tagging(self):
        out = run("""
api.call = (orig => async (m, p) => m === "chat.attach" ? { seq: 0, events: [], state: "idle", options: {} } : orig(m, p))(api.call);
const view = open();
await settle();
await live(view, { type: "AssistantText", msg_id: "msg_1", text: "Oui" });
act(msgs(view)[0], "tag").click();
await settle();
out = { sheet: Boolean(document.body.querySelector("dialog.tag-sheet")), tagsCalls: calls.filter((c) => c[0] === "chat.tags").length };
""")
        self.assertEqual(out, {"sheet": False, "tagsCalls": 0})


@unittest.skipUnless(NODE, "node absent")
class ConversationPreviewTest(unittest.TestCase):
    def test_preview_shows_the_quote_apart(self):
        out = run("""
history = [{ role: "assistant", text: "A ou B ?" },
           { role: "utilisateur", text: "> **Claude :**\\n> A ou B ?\\n\\nLa B" },
           { role: "utilisateur", text: "sans citation" }];
const { convRow } = await import("./sessions-conv.js");
const conv = { session_id: "s1", path: "/j.jsonl", cwd: "/p", title: "Titre", updated_at: 0, folder_exists: true };
const row = convRow(conv, { api, opened: new Set(), resume() {}, changed() {} });
document.body.append(row);
row.querySelector(".conv-more").click();
document.body.querySelectorAll("dialog button").find((b) => b.textContent === "Aperçu").click();
await settle();
const pv = document.body.querySelectorAll(".pv");
out = pv.map((n) => [n.className, n.querySelector(".quoted")?.dataset.author || null, n.querySelector(".pv-text").textContent]);
""")
        self.assertEqual(out, [["pv claude", None, "A ou B ?"], ["pv user", "Claude", "A ou B ?La B"],
                               ["pv user", None, "sans citation"]])


@unittest.skipUnless(NODE, "node absent")
class StaticTest(unittest.TestCase):
    def test_new_modules_are_cached_by_the_service_worker(self):
        sw = (WEB / "sw.js").read_text()
        for name in ("/chat-message.js", "/chat-quote.js", "/chat-tags.js"):
            self.assertIn(f'"{name}"', sw)

    def test_action_labels_come_from_the_stylesheet(self):
        css = (WEB / "chat.css").read_text()
        self.assertIn(".msg-act::after { content: attr(data-label); }", css)
        self.assertIn(".quoted::before { content: attr(data-author);", css)


if __name__ == "__main__":
    unittest.main()
