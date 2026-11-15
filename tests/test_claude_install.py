"""Installation de Claude Code par l'installeur officiel : jamais en root."""

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ccs_app import claude_install, doctor


class InstallTest(unittest.TestCase):
    def test_same_command_as_doctor(self):
        self.assertEqual(doctor.CLAUDE_INSTALL, claude_install.INSTALL)
        self.assertEqual(claude_install.INSTALL, "curl -fsSL https://claude.ai/install.sh | bash")

    def test_install_refuses_root(self):
        calls = []
        with mock.patch("os.geteuid", return_value=0):
            ok, text = claude_install.install(run=lambda *a, **k: calls.append(a))
        self.assertFalse(ok)
        self.assertIn("root", text)
        self.assertEqual(calls, [])

    def test_install_runs_official_command(self):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            return SimpleNamespace(returncode=0, stdout="Claude Code installé\n", stderr="")
        with mock.patch("os.geteuid", return_value=1000):
            ok, text = claude_install.install(run=run)
        self.assertTrue(ok)
        self.assertEqual(calls[0][0], ["sh", "-c", claude_install.INSTALL])
        self.assertEqual(calls[0][1]["timeout"], 600)
        self.assertIn("installé", text)

    def test_install_failure_and_timeout(self):
        import subprocess
        with mock.patch("os.geteuid", return_value=1000):
            ok, _ = claude_install.install(run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="réseau"))
            self.assertFalse(ok)

            def slow(*a, **k):
                raise subprocess.TimeoutExpired("sh", 600)
            ok, text = claude_install.install(run=slow)
            self.assertFalse(ok)

    def test_installed_finds_local_bin(self):
        tmp = tempfile.mkdtemp(prefix="ccs-ci-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertFalse(claude_install.installed(which=lambda _n: None, home=tmp))
        b = Path(tmp) / ".local" / "bin" / "claude"
        b.parent.mkdir(parents=True)
        b.write_text("#!/bin/sh\n")
        b.chmod(0o755)
        self.assertTrue(claude_install.installed(which=lambda _n: None, home=tmp))
        self.assertTrue(claude_install.installed(which=lambda _n: "/usr/bin/claude", home="/nulle/part"))


if __name__ == "__main__":
    unittest.main()
