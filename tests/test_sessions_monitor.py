"""Le pont bureau surveille le dossier des sessions même s'il apparaît après le démarrage."""

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import desktop

try:
    from gi.repository import Gio  # noqa: F401
except ImportError:  # pragma: no cover
    Gio = None


@unittest.skipIf(Gio is None, "GLib/Gio indisponibles")
class SessionsMonitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / ".claude" / "sessions"  # ni le dossier ni son parent n'existent
        self.calls = 0
        self.lock = threading.Lock()
        patch = mock.patch.object(desktop, "DEBOUNCE_MS", 30)
        patch.start()
        self.addCleanup(patch.stop)
        self.bridge = desktop.Bridge(lambda *a: None, self.on_changed, self.path)
        self.bridge.watch_s = 0.05
        self.bridge.start()
        self.addCleanup(self.bridge.stop)

    def on_changed(self):
        with self.lock:
            self.calls += 1

    def count(self):
        with self.lock:
            return self.calls

    def wait_for(self, predicate, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def settle(self):
        time.sleep(0.4)

    def test_monitor_installed_when_directory_appears_later(self):
        self.settle()
        self.assertEqual(self.count(), 0)
        self.path.mkdir(parents=True)
        self.assertTrue(self.wait_for(lambda: self.count() >= 1))  # rattrapage à l'apparition
        self.settle()
        before = self.count()
        (self.path / "123.json").write_text("{}")
        self.assertTrue(self.wait_for(lambda: self.count() > before))

    def test_monitor_follows_deletion_then_recreation(self):
        self.settle()
        self.path.mkdir(parents=True)
        self.assertTrue(self.wait_for(lambda: self.count() >= 1))
        self.settle()
        shutil.rmtree(self.path)
        self.settle()
        before = self.count()
        self.path.mkdir()
        self.assertTrue(self.wait_for(lambda: self.count() > before))
        self.settle()
        before = self.count()
        (self.path / "456.json").write_text("{}")
        self.assertTrue(self.wait_for(lambda: self.count() > before))


if __name__ == "__main__":
    unittest.main()
