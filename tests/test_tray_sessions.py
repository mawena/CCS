"""Sous-menu « Sessions » de l'indicateur : tri, libellés, ouverture (pur, sans GTK)."""
import unittest
from unittest import mock

from ccs_app import tray
from ccs_app.sessions import Session
from ccs_app.tray import label_for


def make(pid, state, since, project="Proj", sid="x", waiting_for=None, cwd=None):
    return Session(pid, sid, "n", cwd or f"/w/{project}", project, state, waiting_for,
                   1000.0, since, "interactive", "cli")


def limits(p):
    return {"active": "perso", "accounts": [
        {"name": "perso", "active": True, "limits": [{"kind": "session", "percent": p}]}]}


class SessionsMenuTest(unittest.TestCase):
    def test_sorted_waiting_first(self):
        a, b = make(1, "idle", 900.0), make(2, "busy", 950.0)
        c, d = make(3, "waiting", 990.0), make(4, "waiting", 800.0)
        self.assertEqual([s.pid for s in tray.sort_sessions([a, b, c, d])], [4, 3, 2, 1])

    def test_elapsed_label(self):
        self.assertEqual(tray.elapsed_label(30), "à l'instant")
        self.assertEqual(tray.elapsed_label(5 * 60), "depuis 5 min")
        self.assertEqual(tray.elapsed_label(3 * 3600 + 120), "depuis 3 h 02")
        self.assertEqual(tray.elapsed_label(2 * 86400 + 3600), "depuis 2 j")
        self.assertEqual(tray.elapsed_label(-5), "à l'instant")

    def test_entries(self):
        w = make(3, "waiting", 700.0, "GiGit", "abc", "permission")
        i = make(4, "idle", 100.0, "Autre", "def")
        titres = {"abc": "Corriger le tri"}
        e = tray.session_entries([i, w], lambda s: titres.get(s.session_id), 1000.0)
        self.assertEqual(e[0].label, "Corriger le tri — attend ta réponse (permission), depuis 5 min")
        self.assertEqual(e[0].ref, "3:abc")
        self.assertEqual(e[0].cwd, "/w/GiGit")
        self.assertEqual(e[1].label, "Autre — au repos, depuis 15 min")
        self.assertEqual(e[1].ref, "4:def")

    def test_title_error_falls_back_to_project(self):
        def boom(_):
            raise OSError("illisible")
        e = tray.session_entries([make(5, "busy", 990.0)], boom, 1000.0)
        self.assertEqual(e[0].label, "Proj — travaille, à l'instant")

    def test_root_label(self):
        w, i = make(3, "waiting", 700.0), make(4, "idle", 100.0)
        self.assertEqual(tray.sessions_root_label([i]), "Sessions (1)")
        self.assertEqual(tray.sessions_root_label([w, i]), "Sessions (1 attend ta réponse)")
        self.assertEqual(tray.sessions_root_label([w, make(6, "waiting", 1.0)]),
                         "Sessions (2 attendent ta réponse)")
        self.assertEqual(tray.sessions_root_label([]), "Sessions")

    def test_signature_follows_state_not_clock(self):
        a = make(3, "busy", 700.0)
        self.assertEqual(tray.sessions_signature([a]), tray.sessions_signature([make(3, "busy", 700.0)]))
        self.assertNotEqual(tray.sessions_signature([a]), tray.sessions_signature([make(3, "waiting", 700.0)]))

    def test_open_session_uses_desktop(self):
        with mock.patch("ccs_app.desktop.show_session", return_value="lancement") as m:
            self.assertTrue(tray.open_session("3:abc"))
        m.assert_called_once_with("3:abc")
        with mock.patch("ccs_app.desktop.show_session", return_value=None):
            self.assertFalse(tray.open_session("zzz"))
        with mock.patch("ccs_app.desktop.show_session", side_effect=RuntimeError):
            self.assertFalse(tray.open_session("3:abc"))

    def test_all_sessions_args(self):
        self.assertEqual(tray.ALL_SESSIONS_ARGS, ("gui", "--page", "sessions"))

    def test_label_shows_waiting(self):
        self.assertEqual(label_for(limits(32), waiting=2), "◔ 32 % · 💬 2")
        self.assertEqual(label_for(limits(32), waiting=0), "◔ 32 %")
        self.assertEqual(label_for({}, paused=True, waiting=1), "⏸ — · 💬 1")
