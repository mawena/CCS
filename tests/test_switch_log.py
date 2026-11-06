import json
import os
import unittest
from datetime import datetime

from ccs_app import switch_log
from ccs_app.limit_events import LimitEvent
from ccs_app.store import Event, Store
from tests.helpers import HomeTestCase, write

# Heures locales : les regroupements par jour suivent le fuseau du poste.
NOW = datetime(2026, 11, 6, 15, 0).timestamp()


def at(day, hour, minute=0, second=0):
    return datetime(2026, 11, day, hour, minute, second).timestamp()


def sw(ts, profile, **detail):
    return Event(ts, "switch", profile, detail)


def err(ts, profile, **detail):
    return Event(ts, "error", profile, detail)


def alert(ts, key, profile="blocage"):
    return Event(ts, "alert", profile, {"key": key})


def warm(ts, profile, **detail):
    return Event(ts, "warmup", profile, detail)


def build(events, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("project_of", {"s1": "GiGit", "s2": "Autre", "s3": "Site"}.get)
    return switch_log.build(events, **kw)


def one(events, **kw):
    entries = build(events, **kw)
    assert len(entries) == 1, entries
    return entries[0]


class AutoSwitchReasonTest(unittest.TestCase):
    def test_threshold_switch_with_recorded_percent(self):
        e = one([sw(at(6, 14, 32), "pro", mode="auto", **{"from": "perso"}, percent=98.4,
                    threshold=98, reason="perso à 98 % → pro (au repos)")])
        self.assertEqual((e.kind, e.source, e.target, e.ok), ("auto", "perso", "pro", True))
        self.assertEqual(e.title, "perso → pro")
        self.assertEqual(e.reason, "Bascule automatique avant la coupure (perso à 98 %)")
        self.assertIn("au repos", e.detail)

    def test_old_event_percent_read_from_the_reason(self):
        e = one([sw(at(6, 14), "pro", mode="auto", reason="perso à 99 % → pro (semaine à 22 %)",
                    **{"from": "perso", "from_reset": None})])
        self.assertEqual(e.reason, "Bascule automatique avant la coupure (perso à 99 %)")

    def test_projection_explained(self):
        e = one([sw(at(6, 14), "pro", mode="auto", percent=96, threshold=98, projected=101.2,
                    **{"from": "perso"})])
        self.assertEqual(e.reason, "Bascule automatique avant la coupure (perso à 96 %, "
                                   "100 % prévu avant le prochain relevé)")

    def test_without_any_percent(self):
        e = one([sw(at(6, 14), "pro", mode="auto", **{"from": "perso"})])
        self.assertEqual(e.reason, "Bascule automatique avant la coupure")


class EarlySwitchReasonTest(unittest.TestCase):
    def test_structured_detail(self):
        e = one([sw(at(6, 10), "pro", mode="anticipee", lost=60, minutes=25, **{"from": "perso"})])
        self.assertEqual(e.kind, "anticipee")
        self.assertEqual(e.reason, "Bascule anticipée de l'orchestrateur : pro allait perdre 60 % "
                                   "de quota dans 25 min")

    def test_old_event_read_from_the_reason(self):
        e = one([sw(at(6, 10), "pro", mode="anticipee", reason="pro va perdre 45 % de quota dans 12 min",
                    **{"from": "perso"})])
        self.assertEqual(e.reason, "Bascule anticipée de l'orchestrateur : pro allait perdre 45 % "
                                   "de quota dans 12 min")

    def test_unknown_detail(self):
        e = one([sw(at(6, 10), "pro", mode="anticipee", **{"from": "perso"})])
        self.assertEqual(e.reason, "Bascule anticipée de l'orchestrateur (quota sur le point d'expirer)")


class BlockedSwitchTest(unittest.TestCase):
    def test_marker_gives_the_blocked_project(self):
        t = at(6, 11)
        markers = {"s1": LimitEvent("s1", t + 2, "perso", "pro", True, "switched")}
        e = one([alert(t, f"blocage:{t:.0f}"), sw(t, "pro", mode="blocage", **{"from": "perso"},
                                                  reason="perso bloqué → pro (au repos)")], markers=markers)
        self.assertEqual((e.kind, e.source, e.target), ("blocage", "perso", "pro"))
        self.assertEqual(e.reason, "Bascule après un blocage (limite atteinte dans GiGit)")
        self.assertEqual(e.projects, ("GiGit",))

    def test_other_sessions_blocked_at_the_same_time(self):
        t = at(6, 11)
        markers = {"s1": LimitEvent("s1", t + 2, "perso", "pro", True, "switched"),
                   "s2": LimitEvent("s2", t + 40, "perso", "pro", True, "already"),
                   "s3": LimitEvent("s3", t + 4000, "perso", "pro", True, "already")}  # trop tard
        e = one([sw(t, "pro", mode="blocage", **{"from": "perso"}),
                 alert(t + 40, "deja")], markers=markers)
        self.assertEqual(e.reason, "Bascule après un blocage (limite atteinte dans GiGit et Autre)")

    def test_without_marker(self):
        e = one([sw(at(6, 11), "pro", mode="blocage", **{"from": "perso"})], markers={})
        self.assertEqual(e.reason, "Bascule après un blocage (limite atteinte sur perso)")

    def test_marker_of_another_switch_ignored(self):
        t = at(6, 11)
        markers = {"s1": LimitEvent("s1", t + 2, "perso", "boulot", True, "switched")}
        e = one([sw(t, "pro", mode="blocage", **{"from": "perso"})], markers=markers)
        self.assertEqual(e.projects, ())

    def test_manual_detection_racing_the_hook_is_dropped(self):
        t = at(6, 11)
        entries = build([sw(t - 3, "pro", mode="manual"), sw(t, "pro", mode="blocage", **{"from": "perso"})],
                        previous="perso")
        self.assertEqual([e.kind for e in entries], ["blocage"])


class ManualSwitchTest(unittest.TestCase):
    def test_origin_unknown_and_source_from_previous_switch(self):
        entries = build([sw(at(6, 8), "perso", mode="initial"), sw(at(6, 9), "pro", mode="manual")])
        self.assertEqual(entries[0].title, "perso → pro")
        self.assertEqual(entries[0].kind, "manuelle")
        self.assertEqual(entries[0].reason, "Bascule manuelle (application, icône ou « ccs use »)")

    def test_previous_profile_before_the_period(self):
        e = one([sw(at(6, 9), "pro", mode="manual")], previous="perso")
        self.assertEqual(e.source, "perso")

    def test_origins(self):
        cases = {
            "notification": "Bascule manuelle depuis une notification",
            "application": "Bascule manuelle depuis l'application",
            "icone": "Bascule manuelle depuis l'icône",
            "ccs": "Bascule manuelle par la commande ccs",
            "raccourci": "Bascule manuelle par un raccourci clavier",
            "nouvelle-session": "Bascule pour une nouvelle session (compte choisi)",
            "inconnu": "Bascule manuelle (application, icône ou « ccs use »)",
        }
        for via, reason in cases.items():
            with self.subTest(via=via):
                e = one([sw(at(6, 9), "pro", mode="manual", via=via, **{"from": "perso"})])
                self.assertEqual(e.reason, reason)

    def test_project_origin(self):
        e = one([sw(at(6, 9), "pro", mode="manual", via="projet", project="/home/u/Work/GiGit",
                    **{"from": "perso"})])
        self.assertEqual(e.reason, "Bascule vers le compte du projet GiGit")

    def test_initial(self):
        e = one([sw(at(6, 8), "perso", mode="initial")])
        self.assertEqual((e.kind, e.title, e.source), ("initial", "perso", None))
        self.assertEqual(e.reason, "Début du suivi : perso était le compte actif")


class FailureTest(unittest.TestCase):
    def test_failed_early_switch(self):
        e = one([err(at(6, 10), "pro", op="auto_switch", message="jeton révoqué", mode="anticipee",
                     **{"from": "perso"})])
        self.assertEqual((e.kind, e.ok, e.title), ("echec", False, "perso → pro"))
        self.assertEqual(e.reason, "Échec de la bascule anticipée vers pro : jeton révoqué")

    def test_old_failure_without_mode(self):
        entries = build([sw(at(6, 8), "perso", mode="initial"),
                         err(at(6, 10), "pro", op="auto_switch", message="erreur")])
        self.assertEqual(entries[0].reason, "Échec de la bascule automatique vers pro : erreur")
        self.assertEqual(entries[0].source, "perso")

    def test_other_failures(self):
        cases = [({"op": "auto_switch", "mode": "blocage"}, "Échec de la bascule après un blocage vers pro"),
                 ({"op": "notification"}, "Échec de la bascule depuis une notification vers pro"),
                 ({"op": "manual", "via": "projet"}, "Échec de la bascule manuelle vers pro")]
        for detail, start in cases:
            with self.subTest(detail=detail):
                e = one([err(at(6, 10), "pro", message="non", **detail)])
                self.assertEqual(e.reason, start + " : non")

    def test_failure_without_message(self):
        e = one([err(at(6, 10), "pro", op="auto_switch")])
        self.assertEqual(e.reason, "Échec de la bascule automatique vers pro")

    def test_fetch_errors_are_not_switches(self):
        self.assertEqual(build([err(at(6, 10), "pro", op="fetch", message="HTTP 429")]), [])


class BlockedWithoutSwitchTest(unittest.TestCase):
    def test_paused(self):
        t = at(6, 12)
        markers = {"s1": LimitEvent("s1", t, "perso", None, False, "paused"),
                   "s2": LimitEvent("s2", t + 30, "perso", None, False, "paused")}
        e = one([alert(t, "pause")], markers=markers)
        self.assertEqual((e.kind, e.ok, e.title), ("limite", False, "perso"))
        self.assertEqual(e.reason, "Limite atteinte dans GiGit et Autre pendant une pause : pas de bascule")

    def test_exhausted(self):
        t = at(6, 12)
        markers = {"s1": LimitEvent("s1", t + 1, "perso", None, False, "exhausted")}
        e = one([alert(t, f"blocage:{t:.0f}")], markers=markers, previous="perso")
        self.assertEqual(e.reason, "Limite atteinte dans GiGit : aucun autre compte disponible")
        self.assertEqual(e.title, "perso")

    def test_exhausted_without_marker(self):
        e = one([alert(at(6, 12), "blocage:1")], previous="perso")
        self.assertEqual(e.reason, "Limite atteinte : aucun autre compte disponible")

    def test_failed_switch_after_a_block_is_one_entry(self):
        t = at(6, 12)
        entries = build([alert(t, f"blocage:{t:.0f}"),
                         err(t, "pro", op="auto_switch", mode="blocage", message="ko", **{"from": "perso"})])
        self.assertEqual([e.kind for e in entries], ["echec"])

    def test_other_alerts_ignored(self):
        self.assertEqual(build([alert(at(6, 12), "switch:1", profile=None),
                                alert(at(6, 12), "deja")]), [])


class WindowStartTest(unittest.TestCase):
    def test_orchestrator_start_placeholder_replaced_by_result(self):
        t = at(6, 7)
        e = one([warm(t, "pro", mode="orchestrateur", date="2026-11-06", time="07:00", ok=None,
                      message="en cours"),
                 warm(t, "pro", mode="orchestrateur", date="2026-11-06", time="07:00", ok=True, message="")])
        self.assertEqual((e.kind, e.title, e.ok), ("fenetre", "pro", True))
        self.assertEqual(e.reason, "Fenêtre de 5 h démarrée par l'orchestrateur")

    def test_slot_failure(self):
        e = one([warm(at(6, 7), "pro", date="2026-11-06", time="07:00", ok=None, message="en cours"),
                 warm(at(6, 7), "pro", mode="creneau", date="2026-11-06", time="07:00", ok=False,
                      message="délai dépassé")])
        self.assertFalse(e.ok)
        self.assertEqual(e.reason, "Warm-up de 07:00 impossible : délai dépassé")

    def test_slot_success_and_running(self):
        e = one([warm(at(6, 7), "pro", mode="creneau", date="2026-11-06", time="07:00", ok=True)])
        self.assertEqual(e.reason, "Warm-up de 07:00 : fenêtre de 5 h démarrée")
        e = one([warm(NOW - 30, "pro", mode="orchestrateur", date="2026-11-06", time="14:59", ok=None)])
        self.assertEqual(e.reason, "Démarrage de la fenêtre par l'orchestrateur en cours")
        e = one([warm(NOW - 3600, "pro", mode="orchestrateur", date="2026-11-06", time="14:00", ok=None)])
        self.assertEqual(e.reason, "Démarrage de la fenêtre par l'orchestrateur sans réponse")


class OrderAndGroupsTest(unittest.TestCase):
    def test_newest_first(self):
        entries = build([sw(at(5, 8), "perso", mode="initial"), sw(at(6, 9), "pro", mode="manual"),
                         sw(at(6, 14), "perso", mode="auto", percent=98)])
        self.assertEqual([e.target for e in entries], ["perso", "pro", "perso"])
        self.assertEqual(entries[0].source, "pro")

    def test_group_by_day(self):
        entries = build([sw(at(2, 8), "perso", mode="initial"), sw(at(5, 9), "pro", mode="manual"),
                         sw(at(6, 14), "perso", mode="manual"), sw(at(6, 9), "pro", mode="manual")])
        groups = switch_log.group_by_day(entries, now=NOW)
        self.assertEqual([label for label, _ in groups], ["Aujourd'hui", "Hier", "Lundi 2 novembre"])
        self.assertEqual([len(g) for _, g in groups], [2, 1, 1])

    def test_other_year_shown(self):
        ts = datetime(2025, 12, 31, 10, 0).timestamp()
        self.assertEqual(switch_log.day_label(ts, now=NOW), "Mercredi 31 décembre 2025")


class FormatTextTest(unittest.TestCase):
    def test_text(self):
        entries = build([sw(at(6, 8), "perso", mode="initial"),
                         sw(at(6, 14, 32), "pro", mode="auto", percent=98, **{"from": "perso"}),
                         err(at(6, 14, 40), "perso", op="notification", message="échec")])
        text = switch_log.format_text(entries, now=NOW)
        lines = text.splitlines()
        self.assertEqual(lines[0], "Aujourd'hui")
        self.assertRegex(lines[1], r"^  14:40  ✗ pro → perso +Échec de la bascule depuis une notification")
        self.assertRegex(lines[2], r"^  14:32    perso → pro +Bascule automatique avant la coupure \(perso à 98 %\)$")
        self.assertIn("08:00", lines[3])

    def test_empty(self):
        self.assertEqual(switch_log.format_text([], now=NOW), "Aucune bascule sur cette période.")


class StoreLoadTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.db = Store()

    def test_period_and_previous_profile(self):
        self.db.add_event(at(6, 15) - 20 * 86400, "switch", "perso", {"mode": "initial"})
        self.db.add_event(at(6, 9), "switch", "pro", {"mode": "manual"})
        self.db.add_event(at(6, 9), "alert", None, {"key": "switch:1"})
        entries = switch_log.load(self.db, days=7, now=NOW, markers={})
        self.assertEqual([(e.source, e.target) for e in entries], [("perso", "pro")])
        everything = switch_log.load(self.db, days=None, now=NOW, markers={})
        self.assertEqual([e.kind for e in everything], ["manuelle", "initial"])

    def test_markers_read_from_disk(self):
        t = at(6, 11)
        self.db.add_event(t, "switch", "pro", {"mode": "blocage", "from": "perso"})
        write(self.store / "limits" / "s9.json", {"session_id": "s9", "ts": t + 1, "from": "perso",
                                                  "to": "pro", "switched": True, "outcome": "switched"})
        cwd = str(self.home / "Work" / "GiGit")
        write(self.home / ".claude" / "projects" / "-x-GiGit" / "s9.jsonl",
              json.dumps({"type": "user", "cwd": cwd}) + "\n")
        e = switch_log.load(self.db, days=7, now=NOW)[0]
        self.assertEqual(e.reason, "Bascule après un blocage (limite atteinte dans GiGit)")

    def test_command(self):
        self.db.add_event(at(6, 9), "switch", "pro", {"mode": "manual", "from": "perso"})
        code, text = switch_log.command(days=7, now=NOW, store=self.db)
        self.assertEqual(code, 0)
        self.assertIn("perso → pro", text)
        self.assertEqual(switch_log.command(days=0, now=NOW, store=self.db)[0], 2)


class OriginNoteTest(HomeTestCase):
    def test_note_taken_once_by_the_service(self):
        self.assertTrue(switch_log.note_origin("pro", "projet", project="/w/GiGit", now=100.0))
        path = self.store / "switch-origin.json"
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertIsNone(switch_log.take_origin("perso", now=110.0))  # autre compte : gardée
        self.assertEqual(switch_log.take_origin("pro", now=110.0),
                         {"via": "projet", "project": "/w/GiGit"})
        self.assertFalse(path.exists())
        self.assertIsNone(switch_log.take_origin("pro", now=120.0))

    def test_stale_or_unreadable_note_ignored(self):
        switch_log.note_origin("pro", "application", now=100.0)
        self.assertIsNone(switch_log.take_origin("pro", now=100.0 + switch_log.ORIGIN_MAX_AGE_S + 1))
        self.assertFalse((self.store / "switch-origin.json").exists())
        write(self.store / "switch-origin.json", "{pas du json")
        self.assertIsNone(switch_log.take_origin("pro", now=100.0))

    def test_unknown_origin_refused(self):
        self.assertFalse(switch_log.note_origin("pro", "n'importe quoi", now=1.0))

    def test_note_never_raises(self):
        os.chmod(self.store, 0o500)
        try:
            self.assertFalse(switch_log.note_origin("pro", "application", now=1.0))
        finally:
            os.chmod(self.store, 0o700)

    def test_failure_recorded_for_the_journal(self):
        db = Store()
        switch_log.record_failure(db, "pro", "projet", "verrou occupé", source="perso", now=at(6, 9))
        e = switch_log.load(db, days=7, now=NOW, markers={})[0]
        self.assertEqual((e.kind, e.reason), ("echec", "Échec de la bascule manuelle vers pro : verrou occupé"))


if __name__ == "__main__":
    unittest.main()
