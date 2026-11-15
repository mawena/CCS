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


def alive(pid):
    """Le processus tourne (ni absent, ni zombie)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(") ", 1)[1][:1] != "Z"
    except OSError:
        return False


def wait_dead(pid, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


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

    def test_background_process_does_not_hold_the_result(self):
        """Constat 6 : un processus laissé en fond garde la sortie ouverte ; la main est rendue
        peu après la fin de bash, et il continue de tourner."""
        done = threading.Event()
        got = []
        r = sc.ShellRun("echo a; sleep 30 & echo $!", tempfile.gettempdir())
        start = time.monotonic()
        r.start(lambda code, text, truncated: (got.append((code, text)), done.set()))
        self.addCleanup(r.stop)
        self.assertTrue(done.wait(sc.AFTER_EXIT_S + 3), "la commande ne rend pas la main")
        self.assertLess(time.monotonic() - start, sc.AFTER_EXIT_S + 2)
        code, text = got[0]
        self.assertEqual(code, 0)
        first, pid = text.split()
        self.assertEqual(first, "a")
        self.assertTrue(alive(int(pid)))                    # le processus en fond vit encore

    def test_stop_after_bash_exit_kills_background(self):
        done = threading.Event()
        got = []
        r = sc.ShellRun("sleep 30 & echo $!", tempfile.gettempdir())
        r.start(lambda code, text, truncated: (got.append(text), done.set()))
        self.assertTrue(done.wait(sc.AFTER_EXIT_S + 3))
        pid = int(got[0].split()[0])
        self.assertTrue(alive(pid))
        r.stop()                                            # bash est fini : le groupe reste visé
        self.assertTrue(wait_dead(pid, sc.KILL_AFTER_S + 3))

    def test_missing_directory_reports_error(self):
        code, text, _t = run("true", "/dossier/qui/n/existe/pas", wait=5)
        self.assertNotEqual(code, 0)
        self.assertTrue(text)


if __name__ == "__main__":
    unittest.main()
