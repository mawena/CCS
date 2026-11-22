"""Version web : vocal (voice.js, phase 35) — texte lu d'une réponse, réglage de lecture, dictée et
lecture avec une fausse reconnaissance et une fausse synthèse, exécutés dans node."""

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
import { installDom } from "./web_dom.mjs";
installDom();
const print = process.stdout.write.bind(process.stdout);
const spoken = [];
let cancelled = 0;
globalThis.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
globalThis.speechSynthesis = { getVoices: () => [{ lang: "fr-FR", localService: true, name: "Amélie" }],
  speak: (u) => spoken.push(u), cancel: () => { cancelled += 1; } };
const recs = [];
globalThis.webkitSpeechRecognition = class {
  constructor() { recs.push(this); this.started = false; }
  start() { this.started = true; }
  stop() { this.started = false; this.onend?.(); }
};
const v = await import("./voice.js");
let out = null;
"""


def run(body):
    tmp = Path(tempfile.mkdtemp(prefix="ccs-webvoix-"))
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
class VoiceWebTest(unittest.TestCase):
    def test_speech_text_strips_markdown(self):
        out = run(r"""
out = v.speechText("# Titre\n\nVoici **gras** et `x = 1`.\n\n```py\nprint(1)\n```\n- [le site](https://a.b/c) ici\n> cité");
""")
        self.assertNotIn("print", out)
        self.assertNotIn("**", out)
        self.assertNotIn("https", out)
        self.assertNotIn("#", out)
        self.assertIn("bloc de code", out)
        self.assertIn("Voici gras et x = 1.", out)
        self.assertIn("le site ici", out)
        self.assertIn("cité", out)

    def test_auto_read_setting_defaults_off_and_persists(self):
        out = run(r"""
const before = v.autoRead();
v.setAutoRead(true); const on = v.autoRead();
v.setAutoRead(false);
out = { before, on, after: v.autoRead(), dictate: v.canDictate(), speak: v.canSpeak() };
""")
        self.assertEqual(out, {"before": False, "on": True, "after": False, "dictate": True, "speak": True})

    def test_speak_splits_sentences_and_second_call_stops(self):
        out = run(r"""
let ended = 0;
v.speak("Première phrase. Deuxième phrase !", { key: "m1", onEnd: () => { ended += 1; } });
const n = spoken.length, lang = spoken[0].lang, key = v.speakingKey();
spoken.at(-1).onend();
const afterEnd = v.speakingKey();
v.speak("Encore.", { key: "m2", onEnd: () => { ended += 1; } });
v.stopSpeaking();
out = { n, lang, key, afterEnd, ended, stopped: v.speakingKey() };
""")
        self.assertEqual(out, {"n": 2, "lang": "fr-FR", "key": "m1", "afterEnd": None, "ended": 2, "stopped": None})

    def test_dictation_reports_text_then_error(self):
        out = run(r"""
const texts = []; const ends = [];
const stop = v.dictate({ onText: (t) => texts.push(t), onEnd: (e) => ends.push(e) });
const rec = recs[0];
rec.onresult({ results: [[{ transcript: "bonjour" }]] });
rec.onresult({ results: [[{ transcript: "bonjour" }], [{ transcript: " Claude" }]] });
stop();
const second = v.dictate({ onText: () => {}, onEnd: (e) => ends.push(e) });
recs[1].onerror({ error: "not-allowed" }); recs[1].onend();
out = { lang: rec.lang, texts, ends, msg: v.dictationError("not-allowed") };
""")
        self.assertEqual(out["lang"], "fr-FR")
        self.assertEqual(out["texts"], ["bonjour", "bonjour Claude"])
        self.assertEqual(out["ends"], [None, "not-allowed"])
        self.assertIn("Micro refusé", out["msg"])


if __name__ == "__main__":
    unittest.main()
