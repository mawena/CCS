"""Commande `!` : lancée par bash dans le dossier du projet, sortie bornée, arrêt par le groupe."""

import os
import tempfile
import threading
import time
import unittest

from ccs_app import shell_command as sc


def run(command, cwd=None, wait=15):
    done = threading.Event()
    got = []

    def finished(code, text, truncated):
        got.append((code, text, truncated))
        done.set()
    r = sc.ShellRun(command, cwd or tempfile.gettempdir())
    r.start(finished)
    if not done.wait(wait):
        r.stop()
        raise AssertionError("la commande ne finit pas")
    return got[0]


class ShellRunTest(unittest.TestCase):
    def test_run_output_and_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, text, truncated = run("echo bonjour; echo erreur >&2; pwd; exit 3", tmp)
        self.assertEqual(code, 3)
        self.assertIn("bonjour", text)
        self.assertIn("erreur", text)                       # sortie d'erreur fusionnée
        self.assertIn(os.path.basename(tmp), text)          # lancée dans le dossier du projet
        self.assertFalse(truncated)

    def test_run_truncates(self):
        code, text, truncated = run("python3 -c \"print('x' * 99999)\"")
        self.assertEqual(code, 0)
        self.assertEqual(len(text), sc.MAX_OUTPUT)
        self.assertTrue(truncated)

    def test_stop(self):
        done = threading.Event()
        got = []
        r = sc.ShellRun("sleep 60", tempfile.gettempdir())
        r.start(lambda code, text, truncated: (got.append(code), done.set()))
        time.sleep(0.3)
        start = time.monotonic()
        r.stop()
        self.assertTrue(done.wait(3))
        self.assertLess(time.monotonic() - start, 3)
        self.assertNotEqual(got[0], 0)

    def test_stop_kills_term_resistant_command(self):
        done = threading.Event()
        r = sc.ShellRun("trap '' TERM; sleep 60", tempfile.gettempdir())
        r.start(lambda *_a: done.set())
        time.sleep(0.4)
        r.stop()
        self.assertTrue(done.wait(5))                       # SIGKILL après 2 s

    def test_missing_directory_reports_error(self):
        code, text, _t = run("true", "/dossier/qui/n/existe/pas", wait=5)
        self.assertNotEqual(code, 0)
        self.assertTrue(text)


if __name__ == "__main__":
    unittest.main()
