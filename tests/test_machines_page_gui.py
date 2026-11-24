"""Réglages → Machines (bureau) : machines, travaux, arrêt confirmé, journal rechargé, lancement
et réglages du relais, contre un faux moteur (aucun réseau). Sous Xvfb."""

import os
import unittest

from tests.helpers import HomeTestCase, gui_ready

GTK = gui_ready()
if GTK:
    from ccs_app.gui import machines_page
    from ccs_app.gui.machines_page import MachinesPage


def sync_runner(work, done):
    try:
        result, error = work(), None
    except Exception as e:  # noqa: BLE001
        result, error = None, e
    done(result, error)


G = 2 ** 30


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.overview_value = {"configured": True, "message": "", "machines": [
            {"id": "vps", "name": "VPS", "online": True, "local": True, "cores": 6, "load": 1.2,
             "mem_used": 4 * G, "mem_total": 11 * G, "tunnel": True, "tools": ["python3"],
             "limit": 2, "running": 0, "waiting": 0},
            {"id": "pc-bureau", "name": "PC du bureau", "online": True, "local": False, "cores": 14, "load": 7.0,
             "mem_used": 8 * G, "mem_total": 32 * G, "tunnel": True, "tools": ["flutter", "gradle"],
             "limit": 2, "running": 1, "waiting": 1},
            {"id": "portable", "name": "Portable", "online": False, "local": False, "cores": 0, "load": 0,
             "mem_used": 0, "mem_total": 0, "tunnel": True, "tools": [], "limit": 3, "running": 0, "waiting": 0}]}
        self.jobs_value = [
            {"id": "a1", "text": "flutter build apk", "cwd": "/tmp", "machine": "pc-bureau", "state": "running",
             "code": None, "created": 900.0, "started": 925.0, "ended": None, "why": ""},
            {"id": "b2", "text": "make test", "cwd": "/tmp", "machine": None, "state": "waiting", "code": None,
             "created": 990.0, "started": None, "ended": None, "why": "en attente d'une place sur pc-bureau (2/2)"},
            {"id": "c3", "text": "make deb", "cwd": "/tmp", "machine": "pc-bureau", "state": "failed", "code": 2,
             "created": 100.0, "started": 200.0, "ended": 210.0, "why": ""}]

    def overview(self):
        self.calls.append(("overview",))
        return self.overview_value

    def jobs(self):
        self.calls.append(("jobs",))
        return self.jobs_value

    def stop(self, job_id):
        self.calls.append(("stop", job_id))
        return True

    def log(self, job_id):
        self.calls.append(("log", job_id))
        return "ligne 1\nligne 2"

    def start(self, command, cwd, machine=None, when=""):
        self.calls.append(("start", command, cwd, machine, when))
        return "d4"

    def settings(self):
        self.calls.append(("settings",))
        return {"relay": "https://ricochet.exemple", "token_set": True, "path": "/x/client.toml",
                "default_limit": 2, "limits": {}}

    def configure(self, relay=None, token=None):
        self.calls.append(("configure", relay, token))

    def set_limit(self, machine_id, limite):
        self.calls.append(("limit", machine_id, limite))

    def add(self, machine_id, name=None, user=None, full=False):
        self.calls.append(("add", machine_id, name, user, full))
        return {"id": machine_id, "command": "curl -fsSL https://r/rejoindre/x | sudo sh", "expires_s": 900}


@unittest.skipUnless(GTK, "affichage graphique requis (CCS_GUI_TESTS=1 sous xvfb-run)")
class MachinesPageTest(HomeTestCase):
    def make(self):
        self.backend = FakeBackend()
        self.toasts = []
        return MachinesPage(toast=self.toasts.append, runner=sync_runner, backend=self.backend,
                            default_cwd="/tmp")

    def test_shows_machines_and_jobs(self):
        p = self.make()
        rows = p._machine_rows
        self.assertEqual([r.get_title() for r in rows], ["VPS (ce serveur)", "PC du bureau", "Portable"])
        sub = rows[1].get_subtitle()
        self.assertIn("charge 0,50/cœur (14 cœurs)", sub)
        self.assertIn("mémoire 8,0/32 Go", sub)
        self.assertIn("places 1/2, 1 en attente", sub)
        self.assertIn("flutter, gradle", sub)
        self.assertIn("hors ligne", rows[2].get_subtitle())
        self.assertEqual(rows[2].limit.get_value_as_int(), 3)
        jobs = p._job_rows
        self.assertEqual([r.get_title() for r in jobs], ["flutter build apk", "make test", "make deb"])
        self.assertIn("en attente d'une place sur pc-bureau (2/2)", jobs[1].get_subtitle())
        self.assertIn("code 2", jobs[2].get_subtitle())
        self.assertTrue(hasattr(jobs[0], "stop") and hasattr(jobs[1], "stop"))
        self.assertFalse(hasattr(jobs[2], "stop"))            # fini : pas de bouton Arrêter
        self.assertEqual(p._targets, [None, "vps", "pc-bureau"])  # hors ligne : pas proposé

    def test_engine_errors_are_shown_not_raised(self):
        self.backend = FakeBackend()
        self.backend.overview = lambda: (_ for _ in ()).throw(RuntimeError("relais injoignable"))
        p = MachinesPage(runner=sync_runner, backend=self.backend)
        self.assertEqual(p.machines_group.get_description(), "relais injoignable")
        self.assertEqual(len(p._job_rows), 3)

    def test_stop_is_confirmed(self):
        p = self.make()
        p.ask_stop(p.jobs[0])
        p.last_alert.emit("response", "cancel")
        self.assertNotIn(("stop", "a1"), self.backend.calls)
        p.ask_stop(p.jobs[0])
        p.last_alert.emit("response", "stop")
        self.assertIn(("stop", "a1"), self.backend.calls)
        self.assertIn("Travail arrêté", self.toasts)

    def test_log_reloads_until_closed(self):
        p = self.make()
        d = p.open_log(p.jobs[0])
        buf = d.view.get_buffer()
        self.assertEqual(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False), "ligne 1\nligne 2")
        self.assertIsNotNone(d.timer["timer"])
        d.emit("closed")
        self.assertIsNone(d.timer["timer"])
        self.assertEqual(self.backend.calls.count(("log", "a1")), 1)

    def test_launch_sends_the_whole_line(self):
        p = self.make()
        p.submit()
        self.assertEqual(p.f_error.get_text(), "Écris la commande à lancer.")
        p.f_command.set_text("flutter build apk --target 'lib/main dev.dart'")
        p.f_target.set_selected(2)
        p.f_when.set_selected(1)
        p.submit()
        self.assertIn(("start", ["flutter build apk --target 'lib/main dev.dart'"], "/tmp", "pc-bureau", "nuit"),
                      self.backend.calls)
        self.assertEqual(p.f_command.get_text(), "")
        p.f_command.set_text("make")
        p.f_when.set_selected(2)
        self.assertTrue(p.f_time.get_visible())
        p.f_time.set_text("22:30")
        p.f_folder.set_text("/dossier/absent")
        p.submit()
        self.assertEqual(p.f_error.get_text(), "Ce dossier n'existe pas.")
        p.f_folder.set_text("/tmp")
        p.f_target.set_selected(0)
        p.submit()
        self.assertEqual(self.backend.calls[-3][0:5], ("start", ["make"], "/tmp", None, "22:30"))

    def test_limit_and_relay_settings(self):
        p = self.make()
        p._machine_rows[1].limit.set_value(4)
        self.assertIn(("limit", "pc-bureau", 4), self.backend.calls)
        self.assertEqual(p.f_token.get_text(), "")
        self.assertEqual(p.token_row.get_subtitle(), "Jeton enregistré")
        self.assertEqual(p.f_relay.get_text(), "https://ricochet.exemple")
        p.save_relay()
        self.assertIn("Rien à changer", self.toasts)
        p.f_token.set_text("secret-123")
        p.save_relay()
        self.assertIn(("configure", None, "secret-123"), self.backend.calls)
        self.assertEqual(p.f_token.get_text(), "")

    def test_refresh_follows_visibility(self):
        p = self.make()
        p.start_refresh()
        self.assertIsNotNone(p._timer)
        p.stop_refresh()
        self.assertIsNone(p._timer)
        self.assertEqual(machines_page.REFRESH_S, 5)

    def test_add_pc_gives_the_command(self):
        page = self.make()
        page.submit_add()
        self.assertTrue(page.a_error.get_visible())          # identifiant et compte requis
        page.a_id.set_text("pc-salon")
        page.a_user.set_text("charles")
        page.a_full.set_active(True)
        page.submit_add()
        self.assertIn(("add", "pc-salon", None, "charles", True), self.backend.calls)
        self.assertTrue(page.a_result.get_visible())
        self.assertIn("rejoindre", page.a_result.get_text())
        self.assertTrue(page.a_copy.get_visible())

    def test_prefs_dialog_proposes_selected_project(self):
        from ccs_app.gui.prefs_dialog import current_project

        class Sessions:
            selected = "/tmp"

        class Window:
            sessions = Sessions()
        self.assertEqual(current_project(Window()), "/tmp")
        Window.sessions.selected = None
        self.assertEqual(current_project(Window()), os.path.expanduser("~"))


if __name__ == "__main__":
    unittest.main()
