"""Groupe « Sauvegarde » des Réglages : gpg et fichiers simulés ou temporaires, exécution
synchrone (`runner`). Widgets créés sans être affichés (affichage requis, sinon sautés)."""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import backup

from .test_backup import GpgCase, HAS_GPG

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    from tests.helpers import gui_ready
    GTK = gui_ready()
except (ImportError, ValueError):
    GTK = False


def sync(work, done):
    try:
        result, error = work(), None
    except Exception as e:  # noqa: BLE001
        result, error = None, e
    done(result, error)


@unittest.skipUnless(GTK, "GTK 4, libadwaita ou affichage absents")
class BackupGroupTest(GpgCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        super().setUp()
        from ccs_app.gui import backup_group
        self.mod = backup_group
        self.toasts = []
        self.g = self.group()
        p = mock.patch.object(Adw.AlertDialog, "present")
        self.present = p.start()
        self.addCleanup(p.stop)

    def group(self):
        return self.mod.BackupGroup(toast=self.toasts.append, runner=sync, backend=self.sc)

    def test_rows_exist(self):
        self.assertEqual(self.g.save_row.get_title(), "Sauvegarder…")
        self.assertEqual(self.g.restore_row.get_title(), "Restaurer…")

    @unittest.skipUnless(HAS_GPG, "gpg absent")
    def test_save_then_restore_with_confirmation(self):
        self.fill_store()
        dest = self.dest()
        self.g.start_save(str(dest))
        self.assertTrue(dest.exists())
        self.assertIn("2 profil(s)", self.toasts[-1])
        shutil.rmtree(self.store / "pro")
        (self.store / "perso" / "oauth.json").write_text("{}")
        self.g.start_restore(str(dest))
        d = self.g.dialog
        self.assertIsNotNone(d)
        self.present.assert_called_once()
        body = d.get_body()
        self.assertIn("Seront remplacés : perso", body)
        self.assertNotIn("RT-", body)
        self.assertFalse((self.store / "pro").exists())        # rien avant la confirmation
        d.emit("response", "restore")
        self.assertTrue((self.store / "pro" / "oauth.json").exists())
        self.assertIn("RT-perso", (self.store / "perso" / "oauth.json").read_text())
        self.assertIn("restaurée", self.toasts[-1])
        self.assertTrue(self.g.save_row.get_sensitive())

    @unittest.skipUnless(HAS_GPG, "gpg absent")
    def test_cancel_writes_nothing(self):
        self.fill_store()
        dest = self.dest()
        self.g.start_save(str(dest))
        (self.store / "perso" / "oauth.json").write_text("{}")
        self.g.start_restore(str(dest))
        self.g.dialog.emit("response", "cancel")
        self.assertEqual((self.store / "perso" / "oauth.json").read_text(), "{}")

    @unittest.skipUnless(HAS_GPG, "gpg absent")
    def test_wrong_passphrase_is_a_toast(self):
        dest = self.dest()
        self.g.start_save(str(dest))
        self._set_phrase("mauvaise")
        self.g.start_restore(str(dest))
        self.assertEqual(self.toasts[-1], "Mauvaise phrase de passe.")
        self.assertIsNone(self.g.dialog)
        self.assertTrue(self.g.restore_row.get_sensitive())

    def test_busy_while_gpg_runs_and_no_double_start(self):
        pending = []
        g = self.mod.BackupGroup(toast=self.toasts.append, runner=lambda w, d: pending.append((w, d)),
                                 backend=self.sc)
        with mock.patch.object(backup, "create") as create:
            g.start_save("/x/y.gpg")
            self.assertTrue(g.busy)
            self.assertFalse(g.save_row.get_sensitive())
            self.assertIn("phrase de passe", g.save_row.get_subtitle())
            g.start_save("/x/z.gpg")
            self.assertEqual(len(pending), 1)
            work, done = pending[0]
            create.return_value = backup.Contents(profiles=["a"], files=[])
            done(work(), None)
        self.assertFalse(g.busy)
        self.assertTrue(g.save_row.get_sensitive())

    def test_unexpected_error_message(self):
        with mock.patch.object(backup, "create", side_effect=OSError("disque plein")):
            self.g.start_save("/x/y.gpg")
        self.assertEqual(self.toasts[-1], "Sauvegarde impossible : disque plein")

    def test_threaded_runner_does_not_block(self):
        from gi.repository import GLib
        results = []
        self.mod._threaded(lambda: 42, lambda r, e: results.append((r, e)))
        ctx = GLib.MainContext.default()
        for _ in range(200):
            while ctx.iteration(False):
                pass
            if results:
                break
            import time
            time.sleep(0.01)
        self.assertEqual(results, [(42, None)])


if __name__ == "__main__":
    unittest.main()
