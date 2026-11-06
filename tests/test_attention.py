import unittest
from datetime import datetime, timedelta, timezone

from ccs_app import attention, doctor
from ccs_app.sessions import Session
from ccs_app.terminal import TabState

NOW = datetime(2026, 11, 6, 10, 0).astimezone()


def sess(pid, sid="", state="idle"):
    return Session(pid, sid, f"s-{pid}", "/w/App", "App", state, None, 0.0, 0.0, "interactive", "cli")


class PauseHeaderTest(unittest.TestCase):
    def info(self, until):
        return {"since": (NOW - timedelta(minutes=5)).isoformat(),
                "until": until.isoformat() if until else None, "label": "ignoré"}

    def test_no_pause(self):
        self.assertIsNone(attention.pause_header(None, NOW))
        self.assertIsNone(attention.pause_header({}, NOW))

    def test_until_today(self):
        label, tooltip = attention.pause_header(self.info(NOW.replace(hour=14)), NOW)
        self.assertEqual(label, "Auto ⏸ jusqu'à 14:00")
        self.assertIn("en pause jusqu'à 14:00", tooltip)
        self.assertIn("Reprendre", tooltip)

    def test_until_tomorrow_and_manual(self):
        label, _ = attention.pause_header(self.info(NOW.replace(hour=8) + timedelta(days=1)), NOW)
        self.assertEqual(label, "Auto ⏸ jusqu'à demain 08:00")
        label, tooltip = attention.pause_header(self.info(None), NOW)
        self.assertEqual(label, "Auto ⏸ en pause")
        self.assertIn("jusqu'à reprise manuelle", tooltip)

    def test_label_is_recomputed_not_copied(self):
        # Le libellé de state.json date du dernier relevé : l'heure seule fait foi.
        label, _ = attention.pause_header(self.info(NOW.replace(hour=11) + timedelta(days=1)),
                                          NOW + timedelta(days=1))
        self.assertEqual(label, "Auto ⏸ jusqu'à 11:00")

    def test_expired_or_unreadable_pause(self):
        self.assertIsNone(attention.pause_header(self.info(NOW - timedelta(minutes=1)), NOW))
        self.assertIsNone(attention.pause_header({"since": "?", "until": "pas une date"}, NOW))
        self.assertIsNone(attention.pause_header("en pause", NOW))


class UpdateBannerTest(unittest.TestCase):
    def test_newer_release(self):
        update = {"version": "0.5.0", "url": "https://github.com/mawena/CCS/releases/tag/v0.5.0", "name": "v0.5.0"}
        self.assertEqual(attention.update_banner(update, "0.4.0"),
                         ("CCS 0.5.0 est disponible", "https://github.com/mawena/CCS/releases/tag/v0.5.0"))

    def test_nothing_new(self):
        self.assertIsNone(attention.update_banner(None, "0.4.0"))
        self.assertIsNone(attention.update_banner({}, "0.4.0"))
        # Paquet déjà mis à jour, état du service pas encore relu.
        self.assertIsNone(attention.update_banner({"version": "0.4.0", "url": "https://github.com/mawena/CCS/"},
                                                  "0.4.0"))
        self.assertIsNone(attention.update_banner({"version": "n'importe", "url": "https://github.com/mawena/CCS/"},
                                                  "0.4.0"))

    def test_link_limited_to_the_project(self):
        for url in ("https://evil.example/CCS", "https://github.com/mawena/CCS.evil/", "javascript:alert(1)",
                    "https://github.com/mawena/CCS/ x", None, 42):
            title, link = attention.update_banner({"version": "0.5.0", "url": url}, "0.4.0")
            self.assertEqual(link, "https://github.com/mawena/CCS/releases/tag/v0.5.0", url)


class DoctorBannerTest(unittest.TestCase):
    def check(self, nom, statut):
        return doctor.Check(nom, statut, "")

    def test_only_errors_count(self):
        self.assertIsNone(attention.doctor_banner([]))
        self.assertIsNone(attention.doctor_banner([self.check("Relevés", doctor.AVERTISSEMENT),
                                                   self.check("Comptes", doctor.OK)]))

    def test_one_or_several_errors(self):
        one = [self.check("Service ccs-daemon", doctor.ERREUR), self.check("Comptes", doctor.AVERTISSEMENT)]
        self.assertEqual(attention.doctor_banner(one), "Un problème a été détecté : Service ccs-daemon")
        two = one + [self.check("Commande claude", doctor.ERREUR)]
        self.assertEqual(attention.doctor_banner(two), "2 problèmes ont été détectés")


class WaitingTest(unittest.TestCase):
    def test_count(self):
        self.assertEqual(attention.waiting_count([]), 0)
        found = [sess(1, state="waiting"), sess(2, state="busy"), sess(3, state="waiting"), sess(4)]
        self.assertEqual(attention.waiting_count(found), 2)


class SessionRefTest(unittest.TestCase):
    SID = "3f2a9c1e-0000-4000-8000-000000000001"

    def test_round_trip(self):
        self.assertEqual(attention.session_ref(sess(4242, self.SID)), f"4242:{self.SID}")
        self.assertEqual(attention.session_ref(sess(4242)), "4242")
        self.assertEqual(attention.parse_session_ref(f"4242:{self.SID}"), (4242, self.SID))
        self.assertEqual(attention.parse_session_ref("4242"), (4242, None))
        self.assertEqual(attention.parse_session_ref(self.SID), (None, self.SID))
        self.assertEqual(attention.parse_session_ref(f" {self.SID} "), (None, self.SID))

    def test_garbage(self):
        for bad in ("", None, "0", "-3", ":", "12:", "abc def", "12:--x", "x" * 200, "../../etc", 42):
            self.assertEqual(attention.parse_session_ref(bad), (None, None), bad)

    def test_match_session_prefers_pid(self):
        found = [sess(1, "a"), sess(2, self.SID), sess(3, "b")]
        self.assertIs(attention.match_session(found, 3, self.SID), found[2])  # /clear : nouvel identifiant
        self.assertIs(attention.match_session(found, 99, self.SID), found[1])  # repris ailleurs
        self.assertIs(attention.match_session(found, None, "a"), found[0])
        self.assertIsNone(attention.match_session(found, 99, "zzz"))
        self.assertIsNone(attention.match_session(found, None, None))


class FocusTargetTest(unittest.TestCase):
    def tabs(self):
        return [TabState("shell", "/w", "bash", pid=10, running=True),
                TabState("claude", "/w/App", "App", session_id="sid-a", pid=11, running=True),
                TabState("claude", "/w/B", "B", session_id="sid-b", pid=None, running=False)]

    def test_tab_by_pid_or_conversation(self):
        tabs = self.tabs()
        self.assertEqual(attention.focus_target("11:autre", tabs), ("onglet", tabs[1]))  # /clear
        self.assertEqual(attention.focus_target("sid-a", tabs), ("onglet", tabs[1]))
        self.assertEqual(attention.focus_target("sid-b", tabs), ("onglet", tabs[2]))

    def test_pid_known_but_not_in_a_tab(self):
        # Même conversation qu'un onglet arrêté, mais reprise ailleurs : la session vit hors de
        # l'application.
        self.assertEqual(attention.focus_target("99:sid-b", self.tabs()), ("sessions", 99, "sid-b"))

    def test_shell_tab_is_never_a_session(self):
        self.assertEqual(attention.focus_target("10", self.tabs()), ("sessions", 10, None))

    def test_otherwise_sessions_page(self):
        self.assertEqual(attention.focus_target("77:sid-z", self.tabs()), ("sessions", 77, "sid-z"))
        self.assertEqual(attention.focus_target("77:sid-z", []), ("sessions", 77, "sid-z"))

    def test_invalid_reference(self):
        self.assertIsNone(attention.focus_target("n'importe quoi", self.tabs()))


if __name__ == "__main__":
    unittest.main()
