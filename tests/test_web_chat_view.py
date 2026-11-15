"""Chat web exécuté dans node avec un faux DOM (tests/web_dom.mjs) : il n'y a pas de navigateur
sur la machine qui construit les paquets. Fil, envoi, et répondre en citant un message."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccs_app import quote
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
      case "chat.render": return { html: params.markdown };
      case "chat.send": if (api.failSend) throw new Error("coupure"); return { ok: true };
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
mine.content.click();
const first = [mine.classList.contains("picked"), claude.classList.contains("picked")];
claude.content.click();
const second = [mine.classList.contains("picked"), claude.classList.contains("picked")];
act(claude).click();                               // « Répondre » : la rangée se referme
const third = claude.classList.contains("picked");
type(view, "ok");
await submit(view);
const quoted = msgs(view)[2].querySelector(".quoted");
quoted.querySelector(".quoted-text").click();
out = { first, second, third, open: quoted.classList.contains("open"), picked: msgs(view)[2].classList.contains("picked") };
""")
        self.assertEqual(out, {"first": [True, False], "second": [False, True], "third": False, "open": True, "picked": False})


@unittest.skipUnless(NODE, "node absent")
class StaticTest(unittest.TestCase):
    def test_new_modules_are_cached_by_the_service_worker(self):
        sw = (WEB / "sw.js").read_text()
        for name in ("/chat-message.js", "/chat-quote.js"):
            self.assertIn(f'"{name}"', sw)

    def test_action_labels_come_from_the_stylesheet(self):
        css = (WEB / "chat.css").read_text()
        self.assertIn(".msg-act::after { content: attr(data-label); }", css)
        self.assertIn(".quoted::before { content: attr(data-author);", css)


if __name__ == "__main__":
    unittest.main()
