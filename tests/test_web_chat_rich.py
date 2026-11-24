"""Version web, chat riche (chat-rich.js) : blocs ```ccs (choix, formulaire, carte, cartes),
images agrandissables, lecteurs de sons et de vidéos, fichiers locaux lus par l'explorateur."""
import unittest

from ccs_app.server import web
from tests.test_web_sessions import NODE, WEB, run_dom

PRELUDE = """
import { el } from "./dom.js";
import { enrich, formMessage, mediaKind, parseBlock, resolveSrc } from "./chat-rich.js";
const sent = [], calls = [];
const api = { call: async (m, p) => { calls.push([m, p]);
  if (m === "files.download") return { size: 3, data: "YWJj", done: true };
  return {}; } };
const ctx = { api, cwd: "/ws/projet", send: (t) => sent.push(t) };
const block = (json) => el("div", {}, el("pre", {}, el("code", { class: "language-ccs" }, json)));
"""


@unittest.skipUnless(NODE, "node absent")
class ChatRichWebTest(unittest.TestCase):
    def run_js(self, body):
        return run_dom(PRELUDE + body)

    def test_parse_block(self):
        out = self.run_js("""
out = [parseBlock('{"type":"choix","options":["A"]}')?.type, parseBlock("{pas du json"),
  parseBlock('{"type":"inconnu"}'), parseBlock('{"type":"choix","options":[]}'), parseBlock("[1]"),
  parseBlock('{"type":"cartes","items":[{"titre":"X"}]}')?.type];
""")
        self.assertEqual(out, ["choix", None, None, None, None, "cartes"])

    def test_invalid_block_stays_code(self):
        out = self.run_js("""
const root = block('{"type":"inconnu"}');
enrich(root, ctx);
out = [root.querySelectorAll("pre > code").length, root.querySelectorAll(".rich").length];
""")
        self.assertEqual(out, [1, 0])

    def test_choice_sends_text_once(self):
        out = self.run_js("""
const root = block('{"type":"choix","titre":"Que faire ?","options":["Oui",{"label":"Voir","message":"Montre les détails"}]}');
enrich(root, ctx);
const btns = root.querySelectorAll(".rich-choices button");
btns[1].click(); btns[0].click();
out = { n: btns.length, sent, title: root.querySelector(".rich-title").textContent,
  disabled: btns.every((b) => b.disabled), pre: root.querySelectorAll("pre").length };
""")
        self.assertEqual(out, {"n": 2, "sent": ["Montre les détails"], "title": "Que faire ?",
                               "disabled": True, "pre": 0})

    def test_form_sends_readable_message(self):
        out = self.run_js("""
const spec = '{"type":"formulaire","titre":"Recherche","envoyer":"Chercher","champs":['
  + '{"nom":"prix","label":"Prix max","type":"nombre"},{"nom":"ville","label":"Ville","type":"liste","options":["Lomé","Kara"]},'
  + '{"nom":"note","label":"Note","type":"texte"}]}';
const root = block(spec);
enrich(root, ctx);
const form = root.querySelector("form.rich-form");
form.querySelector("input").value = "300";
form.querySelector("select").value = "Kara";
form.querySelector("button").click();
out = { sent, types: form.querySelectorAll("input").map((i) => i.getAttribute("type")),
  button: form.querySelector("button").textContent,
  plain: formMessage({ champs: [{ nom: "a", label: "A" }] }, { a: " x " }) };
""")
        self.assertEqual(out["sent"], ["Recherche\n- Prix max : 300\n- Ville : Kara"])
        self.assertEqual(out["types"], ["number", "text"])
        self.assertEqual(out["button"], "Chercher")
        self.assertEqual(out["plain"], "- A : x")

    def test_cards(self):
        out = self.run_js("""
const spec = JSON.stringify({ type: "cartes", items: [
  { titre: "Vélo", image: "https://ex.com/v.jpg", prix: "45 000 FCFA", description: "Bon état",
    lien: "https://ex.com/v", actions: [{ label: "Plus", message: "Plus sur le vélo" }, { label: "Site", lien: "https://ex.com" }] },
  { titre: "Mauvais lien", lien: "javascript:alert(1)" }, { pas: "de titre" }] });
const root = block(spec);
enrich(root, ctx);
const cards = root.querySelectorAll(".rich-card");
cards[0].querySelector("button").click();
out = { n: cards.length, img: cards[0].querySelector("img").getAttribute("src"),
  price: cards[0].querySelector(".rich-price").textContent,
  href: cards[0].querySelector("a").getAttribute("href"), target: cards[0].querySelector("a").getAttribute("target"),
  site: cards[0].querySelector("a.button").getAttribute("href"),
  badLinks: cards[1].querySelectorAll("a").length, sent };
""")
        self.assertEqual(out, {"n": 2, "img": "https://ex.com/v.jpg", "price": "45 000 FCFA",
                               "href": "https://ex.com/v", "target": "_blank", "site": "https://ex.com",
                               "badLinks": 0, "sent": ["Plus sur le vélo"]})

    def test_image_opens_lightbox(self):
        out = self.run_js("""
const root = el("p", {}, el("img", { src: "https://ex.com/a.png", alt: "Capture" }));
enrich(root, ctx);
const img = root.querySelector("img.rich-img");
img.click();
const dlg = document.body.querySelector("dialog.lightbox");
out = { src: img.getAttribute("src"), open: dlg.open, big: dlg.querySelector("img").getAttribute("src") };
dlg.click();
out.closed = !dlg.open;
""")
        self.assertEqual(out, {"src": "https://ex.com/a.png", "open": True, "big": "https://ex.com/a.png",
                               "closed": True})

    def test_local_image_read_by_explorer(self):
        out = self.run_js("""
const img = el("img", { alt: "x" }); img.dataset.path = "captures/../captures/a.png";
const root = el("p", {}, img);
enrich(root, ctx);
await settle(20);
const again = el("p", {}, el("img", { src: "/ws/projet/captures/a.png" }));
enrich(again, ctx);
await settle(20);
out = { src: root.querySelector("img").getAttribute("src").slice(0, 5),
  calls: calls.filter(([m]) => m === "files.download").map(([, p]) => p.path) };
""")
        # la seconde vue (même chemin) ne relit pas le fichier : le cache est dans ctx
        self.assertEqual(out, {"src": "blob:", "calls": ["/ws/projet/captures/a.png"]})

    def test_players(self):
        out = self.run_js("""
const root = el("div", {},
  el("p", {}, el("a", { href: "https://ex.com/son.mp3?x=1" }, "son")),
  el("p", {}, el("code", {}, "videos/demo.webm")),
  el("p", {}, el("a", { class: "file-link", dataset: { path: "/ws/projet/note.ogg" } }, "note.ogg")),
  el("p", {}, el("img", { src: "https://ex.com/clip.mp4", alt: "clip" })),
  el("p", {}, el("a", { href: "https://ex.com/page" }, "page")));
enrich(root, ctx);
enrich(root, ctx);   // un second passage n'ajoute pas de lecteur en double
await settle(20);
out = { audio: root.querySelectorAll("audio").length, video: root.querySelectorAll("video").length,
  first: root.querySelector("audio").getAttribute("src"),
  kinds: [mediaKind("a.MOV"), mediaKind("a.txt"), mediaKind("x.opus#t=3")],
  refused: [resolveSrc("javascript:alert(1)"), resolveSrc("http://ex.com/a.png"), resolveSrc("//ex.com/a")] };
""")
        self.assertEqual(out["audio"], 2)
        self.assertEqual(out["video"], 2)
        self.assertEqual(out["first"], "https://ex.com/son.mp3?x=1")
        self.assertEqual(out["kinds"], ["video", None, "audio"])
        self.assertEqual(out["refused"], [None, None, None])

    def test_wiring_and_csp(self):
        chat = (WEB / "chat.js").read_text(encoding="utf-8")
        self.assertIn('from "./chat-rich.js"', chat)
        self.assertIn("enrich(node,", chat)
        self.assertIn('"/chat-rich.js"', (WEB / "sw.js").read_text(encoding="utf-8"))
        self.assertIn("img-src 'self' data: blob: https:", web.CSP)
        self.assertIn("media-src 'self' blob: https:", web.CSP)
        self.assertNotIn("innerHTML", (WEB / "chat-rich.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
