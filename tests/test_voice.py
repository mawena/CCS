"""Vocal au bureau (ccs_app/voice.py, phase 35) : texte lu, commandes d'enregistrement, lecteur."""

import os
import tempfile
import unittest
from unittest import mock

from ccs_app import voice


class SpeechTextTest(unittest.TestCase):
    def test_strips_markdown_like_web(self):
        out = voice.speech_text("# Titre\n\nVoici **gras** et `x = 1`.\n\n```py\nprint(1)\n```\n"
                                "- [le site](https://a.b/c) ici\n> cité")
        self.assertNotIn("print", out)
        self.assertNotIn("**", out)
        self.assertNotIn("https", out)
        self.assertNotIn("#", out)
        self.assertIn("bloc de code", out)
        self.assertIn("Voici gras et x = 1.", out)
        self.assertIn("le site ici", out)
        self.assertIn("cité", out)

    def test_empty(self):
        self.assertEqual(voice.speech_text(None), "")
        self.assertEqual(voice.speech_text("```\ncode seul\n```"), "bloc de code.")

    def test_bare_url_and_table(self):
        out = voice.speech_text("Voir https://exemple.fr/x\n\n| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertIn("Voir lien", out)
        self.assertNotIn("---", out)
        self.assertIn("1 , 2", out)


class RecorderCommandTest(unittest.TestCase):
    def _which(self, present):
        return lambda name: f"/usr/bin/{name}" if name in present else None

    def test_prefers_pipewire_then_pulse_then_alsa(self):
        with mock.patch("shutil.which", self._which({"pw-record", "parecord", "arecord"})):
            self.assertEqual(voice.recorder_command("a.wav")[0], "pw-record")
        with mock.patch("shutil.which", self._which({"parecord", "arecord"})):
            self.assertEqual(voice.recorder_command("a.wav")[0], "parecord")
        with mock.patch("shutil.which", self._which({"arecord"})):
            self.assertEqual(voice.recorder_command("a.wav")[:2], ["arecord", "-q"])
        with mock.patch("shutil.which", self._which(set())):
            self.assertIsNone(voice.recorder_command("a.wav"))

    def test_can_dictate_needs_whisper_and_recorder(self):
        with mock.patch.object(voice, "whisper_installed", return_value=False):
            self.assertFalse(voice.can_dictate())
        with mock.patch.object(voice, "whisper_installed", return_value=True), \
                mock.patch("shutil.which", self._which({"arecord"})):
            self.assertTrue(voice.can_dictate())

    def test_recorder_without_tool_raises_and_cleans(self):
        r = voice.Recorder()
        with mock.patch.object(voice, "recorder_command", return_value=None):
            with self.assertRaises(RuntimeError):
                r.start()
        self.assertIsNone(r.path)

    def test_recorder_drops_empty_file(self):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        r = voice.Recorder()
        r.path = path
        r._proc = mock.Mock(poll=mock.Mock(return_value=0))
        self.assertIsNone(r.stop())
        self.assertFalse(os.path.exists(path))


class SpeakerTest(unittest.TestCase):
    def test_speak_feeds_cleaned_text_and_stop_cancels(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = lambda *a, **k: None
        ended = []
        with mock.patch.object(voice, "can_speak", return_value=True), \
                mock.patch("subprocess.Popen", return_value=proc) as popen, \
                mock.patch("subprocess.run") as run, \
                mock.patch("threading.Thread") as thread:
            sp = voice.Speaker()
            self.assertTrue(sp.speak("**Bonjour** `x`", key="m1", on_end=lambda: ended.append(1)))
            self.assertEqual(popen.call_args.args[0][:4], ["spd-say", "-w", "-l", "fr"])
            proc.stdin.write.assert_called_once_with("Bonjour x")
            self.assertEqual(sp.key, "m1")
            self.assertTrue(sp.speaking())
            sp.stop()
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], ["spd-say", "-C"])
            proc.terminate.assert_called_once()
            self.assertIsNone(sp.key)
            thread.return_value.start.assert_called_once()

    def test_nothing_to_say(self):
        with mock.patch.object(voice, "can_speak", return_value=True), mock.patch("subprocess.Popen") as popen:
            self.assertFalse(voice.Speaker().speak("   "))
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
