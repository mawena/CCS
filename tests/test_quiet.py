"""Ne pas déranger : plages (minuit, jours, changement d'heure), silence temporaire,
retenue et exceptions, résumé unique, réveil du service, validation des réglages."""

import os
import stat
import time
from datetime import datetime, timedelta, timezone
from unittest import mock

from ccs_app import alerts, notify, quiet
from ccs_app.settings import DEFAULTS, load_settings, problems
from tests.helpers import HomeTestCase, write
from tests.test_daemon import NOW as DAEMON_NOW, DaemonBase, fake_http, per_account, usage

PARIS = "Europe/Paris"


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def paris(y, mo, d, h, mi=0):
    from zoneinfo import ZoneInfo
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(PARIS)).astimezone(timezone.utc)


def alert(key, title="t", urgency=1):
    return alerts.Alert(key, title, "corps", urgency)


def use_paris(case):
    """Fuseau du poste = Paris, aussi pour `astimezone()` sans argument (étiquettes)."""
    tz = mock.patch.dict(os.environ, {"TZ": PARIS})
    tz.start()
    time.tzset()

    def restore():
        tz.stop()
        time.tzset()
    case.addCleanup(restore)


class QuietBase(HomeTestCase):
    def setUp(self):
        super().setUp()
        use_paris(self)

    def conf(self, **quiet_cfg):
        cfg = {"enabled": True}
        cfg.update(quiet_cfg)
        write(self.store / "settings.json", {"alerts": {"quiet": cfg}})
        return load_settings()


class PlageTest(QuietBase):
    def test_off_by_default(self):
        self.assertFalse(DEFAULTS["alerts"]["quiet"]["enabled"])
        self.assertIsNone(quiet.quiet_state(paris(2026, 11, 9, 23)))

    def test_range_over_midnight(self):
        s = self.conf()
        for h, mi, on in ((21, 59, False), (22, 0, True), (23, 30, True), (0, 30, True),
                          (7, 59, True), (8, 0, False), (12, 0, False)):
            day = 10 if h < 22 else 9
            st = quiet.quiet_state(paris(2026, 11, day, h, mi), s)
            self.assertEqual(st is not None, on, (h, mi))
        st = quiet.quiet_state(paris(2026, 11, 9, 23), s)
        self.assertEqual((st.source, st.until), ("plage", paris(2026, 11, 10, 8)))

    def test_days_are_the_start_day(self):
        s = self.conf(days=[0])  # lundi seulement
        self.assertIsNotNone(quiet.quiet_state(paris(2026, 11, 9, 23), s))   # lundi soir
        self.assertIsNotNone(quiet.quiet_state(paris(2026, 11, 10, 3), s))   # nuit de lundi à mardi
        self.assertIsNone(quiet.quiet_state(paris(2026, 11, 10, 23), s))     # mardi soir
        self.assertIsNone(quiet.quiet_state(paris(2026, 11, 9, 3), s))       # nuit de dimanche

    def test_same_day_range(self):
        s = self.conf(start="12:00", end="14:00")
        self.assertIsNotNone(quiet.quiet_state(paris(2026, 11, 9, 13), s))
        self.assertIsNone(quiet.quiet_state(paris(2026, 11, 9, 14), s))

    def test_local_time_across_dst(self):
        # Passage à l'heure d'été (29/03/2026) : la nuit ne dure que 9 h réelles.
        s = self.conf()
        end = quiet.quiet_state(paris(2026, 3, 28, 23), s).until
        self.assertEqual(end, paris(2026, 3, 29, 8))
        self.assertEqual(end, utc(2026, 3, 29, 6))
        self.assertIsNotNone(quiet.quiet_state(utc(2026, 3, 29, 5, 59), s))
        self.assertIsNone(quiet.quiet_state(utc(2026, 3, 29, 6, 0), s))
        # Retour à l'heure d'hiver (25/10/2026) : la nuit dure 11 h.
        self.assertEqual(quiet.quiet_state(paris(2026, 10, 24, 23), s).until, utc(2026, 10, 25, 7))

    def test_disabled_range_is_ignored(self):
        s = self.conf(enabled=False)
        self.assertIsNone(quiet.quiet_state(paris(2026, 11, 9, 23), s))


class TemporaryTest(QuietBase):
    def test_choices(self):
        now = paris(2026, 11, 9, 14)
        self.assertEqual(quiet.until_for("1h", now), now + timedelta(hours=1))
        self.assertEqual(quiet.until_for("4h", now), now + timedelta(hours=4))

    def test_tomorrow_without_range_is_next_8am(self):
        self.assertEqual(quiet.until_for("demain", paris(2026, 11, 9, 14)), paris(2026, 11, 10, 8))
        self.assertEqual(quiet.until_for("demain", paris(2026, 11, 10, 2)), paris(2026, 11, 10, 8))

    def test_tomorrow_with_range_is_end_of_range(self):
        s = self.conf()
        self.assertEqual(quiet.until_for("demain", paris(2026, 11, 9, 23), s), paris(2026, 11, 10, 8))
        self.assertEqual(quiet.until_for("demain", paris(2026, 11, 9, 14), s), paris(2026, 11, 10, 8))

    def test_unknown_choice(self):
        with self.assertRaises(ValueError):
            quiet.until_for("jamais", utc(2026, 11, 9, 12))

    def test_set_state_and_auto_lift(self):
        now = utc(2026, 11, 9, 12)
        quiet.set_quiet(now + timedelta(hours=1), now)
        st = quiet.quiet_state(now)
        self.assertEqual((st.source, st.until), ("temporaire", now + timedelta(hours=1)))
        self.assertIsNone(quiet.quiet_state(now + timedelta(hours=1)))
        self.assertTrue(quiet.expire(now + timedelta(hours=1)))
        self.assertFalse(quiet.quiet_path().exists())

    def test_manual_has_no_end(self):
        now = utc(2026, 11, 9, 12)
        quiet.set_quiet(None, now)
        st = quiet.quiet_state(now + timedelta(days=30))
        self.assertIsNone(st.until)
        self.assertIsNone(quiet.next_wake(now))

    def test_clear(self):
        quiet.set_quiet(None)
        quiet.clear_quiet()
        quiet.clear_quiet()  # idempotent
        self.assertIsNone(quiet.quiet_state(datetime.now(timezone.utc)))

    def test_file_is_private_and_atomic(self):
        quiet.set_quiet(None, utc(2026, 11, 9, 12))
        self.assertEqual(stat.S_IMODE(os.stat(quiet.quiet_path()).st_mode), 0o600)
        self.assertEqual([p.name for p in self.store.iterdir() if p.name.startswith("quiet.json.")], [])

    def test_unreadable_file_means_no_quiet(self):
        quiet.quiet_path().parent.mkdir(parents=True, exist_ok=True)
        for text in ("{pas du json", "[]", '{"since": "x"}', '{"since": 1, "until": "y"}', ""):
            quiet.quiet_path().write_text(text)
            self.assertIsNone(quiet.quiet_state(utc(2026, 11, 9, 12)), text)

    def test_temporary_inside_range_keeps_the_later_end(self):
        s = self.conf()
        now = paris(2026, 11, 9, 23)
        quiet.set_quiet(now + timedelta(hours=1), now)
        st = quiet.quiet_state(now + timedelta(hours=2), s)  # la temporaire est échue, pas la plage
        self.assertEqual((st.source, st.until), ("plage", paris(2026, 11, 10, 8)))
        st = quiet.quiet_state(now, s)
        self.assertEqual(st.until, paris(2026, 11, 10, 8))

    def test_temporary_outside_range(self):
        s = self.conf()
        now = paris(2026, 11, 9, 14)
        quiet.set_quiet(now + timedelta(hours=1), now)
        self.assertEqual(quiet.quiet_state(now, s).source, "temporaire")
        self.assertIsNone(quiet.quiet_state(now + timedelta(hours=1), s))


class HoldTest(QuietBase):
    NIGHT = paris(2026, 11, 9, 23)
    DAY = paris(2026, 11, 9, 14)

    def test_nothing_held_outside_silence(self):
        s = self.conf()
        self.assertIsNone(quiet.should_hold(alert("session:1:2"), self.DAY, s))

    def test_held_during_range(self):
        s = self.conf()
        for key in ("session:1:2", "session95:perso:5", "eta:perso:1", "switch:12", "reset:perso:3",
                    "auth:perso:d", "update:1.0", "pause_end:3", "exhausted:perso:1", "refus:pro:9"):
            self.assertIsNotNone(quiet.should_hold(alert(key), self.NIGHT, s), key)

    def test_waiting_passes_when_allowed(self):
        s = self.conf(allow_waiting=True)
        self.assertIsNone(quiet.should_hold(alert("attente:1:2"), self.NIGHT, s))
        self.assertIsNone(quiet.should_hold(alert("rappel:1:2"), self.NIGHT, s))

    def test_waiting_held_when_not_allowed(self):
        s = self.conf(allow_waiting=False)
        self.assertEqual(quiet.should_hold(alert("attente:1:2"), self.NIGHT, s), "attente")
        self.assertEqual(quiet.should_hold(alert("rappel:1:2"), self.NIGHT, s), "attente")

    def test_waiting_follows_the_setting_in_temporary_silence_too(self):
        now = utc(2026, 11, 9, 12)
        quiet.set_quiet(None, now)
        s = self.conf(enabled=False)
        self.assertIsNone(quiet.should_hold(alert("attente:1:2"), now, s))
        s = self.conf(enabled=False, allow_waiting=False)
        self.assertIsNotNone(quiet.should_hold(alert("attente:1:2"), now, s))

    def test_critical_block_and_summary_always_pass(self):
        s = self.conf(allow_waiting=False)
        self.assertIsNone(quiet.should_hold(alert("blocage:5", urgency=2), self.NIGHT, s))
        self.assertIsNone(quiet.should_hold(alert("silence:5", urgency=0), self.NIGHT, s))

    def test_kinds(self):
        self.assertEqual({quiet.kind(alert(k)) for k in ("session:1:2",)}, {"terminee"})
        self.assertEqual({quiet.kind(alert(k)) for k in (
            "session80:p:1", "session95:p:1", "eta:p:1", "weekly_forecast:p:1", "weekly_ahead:p:1",
            "exhausted:p:1")}, {"seuil"})
        self.assertEqual(quiet.kind(alert("model_advice:x")), "autre")


class SendFilterTest(QuietBase):
    """notify.send : point de passage de toutes les notifications."""

    def setUp(self):
        super().setUp()
        self.sent = []
        p = mock.patch.object(notify, "_dbus_send",
                              side_effect=lambda a, transient=False: self.sent.append(a) or 42)
        p.start()
        self.addCleanup(p.stop)
        self.now = [paris(2026, 11, 9, 23)]
        n = mock.patch.object(quiet, "datetime", wraps=datetime)
        self.clock = n.start()
        self.addCleanup(n.stop)
        self.clock.now.side_effect = lambda tz=None: self.now[0]

    def test_sent_normally_without_silence(self):
        self.now[0] = paris(2026, 11, 9, 14)
        self.conf()
        self.assertEqual(notify.send(alert("session:1:2")), 42)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(quiet.held_counts(), {})

    def test_held_and_counted_during_silence(self):
        self.conf()
        self.assertIsNone(notify.send(alert("session:1:2")))
        self.assertIsNone(notify.send(alert("session:3:4")))
        self.assertIsNone(notify.send(alert("session95:perso:1")))
        self.assertEqual(self.sent, [])
        self.assertEqual(quiet.held_counts(), {"terminee": 2, "seuil": 1})

    def test_waiting_and_blocage_pass_during_silence(self):
        self.conf()
        notify.send(alert("attente:1:2"))
        notify.send(alert("blocage:9", urgency=2))
        self.assertEqual([a.key for a in self.sent], ["attente:1:2", "blocage:9"])

    def test_shortcut_notifications_are_never_held(self):
        self.conf()
        self.assertEqual(notify.message("Compte : perso"), 42)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(quiet.held_counts(), {})

    def test_failure_of_the_filter_notifies(self):
        self.conf()
        with mock.patch.object(quiet, "should_hold", side_effect=RuntimeError("boum")):
            self.assertEqual(notify.send(alert("session:1:2")), 42)

    def test_temporary_silence_holds(self):
        self.now[0] = paris(2026, 11, 9, 14)
        quiet.set_quiet(self.now[0] + timedelta(hours=1), self.now[0])
        self.assertIsNone(notify.send(alert("reset:perso:1")))
        self.assertEqual(quiet.held_counts(), {"reset": 1})


class SummaryTest(QuietBase):
    def test_text_and_plurals(self):
        self.assertEqual(quiet.summary_text({"terminee": 2, "seuil": 1}),
                         "Pendant le silence : 2 sessions terminées, 1 alerte de seuil.")
        self.assertEqual(quiet.summary_text({"auth": 1, "bascule": 3, "inconnu": 2}),
                         "Pendant le silence : 3 bascules automatiques, 1 connexion expirée, "
                         "2 autres notifications.")
        self.assertEqual(quiet.summary_text({}), "")

    def test_flush_sends_a_single_summary_once(self):
        s = self.conf()
        quiet.hold(alert("session:1:2"))
        quiet.hold(alert("session:3:4"))
        quiet.hold(alert("session80:perso:1"))
        out = []
        night = paris(2026, 11, 10, 3)
        self.assertIsNone(quiet.flush(night, out.append, s))  # encore en silence
        self.assertEqual(out, [])
        morning = paris(2026, 11, 10, 8, 1)
        a = quiet.flush(morning, out.append, s)
        self.assertEqual(out, [a])
        self.assertEqual(a.body, "Pendant le silence : 2 sessions terminées, 1 alerte de seuil.")
        self.assertEqual(a.urgency, 0)
        self.assertEqual(quiet.held_counts(), {})
        self.assertIsNone(quiet.flush(morning, out.append, s))  # une seule fois
        self.assertEqual(len(out), 1)

    def test_nothing_held_no_summary(self):
        out = []
        self.assertIsNone(quiet.flush(utc(2026, 11, 9, 12), out.append))
        self.assertEqual(out, [])

    def test_manual_lift_then_flush(self):
        now = utc(2026, 11, 9, 12)
        quiet.set_quiet(None, now)
        quiet.hold(alert("reset:perso:1"))
        out = []
        self.assertIsNone(quiet.flush(now, out.append))
        quiet.clear_quiet()
        self.assertIsNotNone(quiet.flush(now, out.append))


class CommandTest(QuietBase):
    NOW = paris(2026, 11, 9, 14)

    def test_status_without_silence(self):
        code, text = quiet.command([], self.NOW)
        self.assertEqual(code, 0)
        self.assertIn("Pas de silence", text)

    def test_set_and_status(self):
        code, text = quiet.command(["1h"], self.NOW)
        self.assertEqual(code, 0)
        self.assertIn("Silence jusqu'à", text)
        code, text = quiet.command(["status"], self.NOW)
        self.assertIn("silence temporaire", text)
        self.assertIn("jusqu'à", text)

    def test_tomorrow_label(self):
        _code, text = quiet.command(["demain"], self.NOW)
        self.assertIn("08:00", text)

    def test_off(self):
        quiet.command(["4h"], self.NOW)
        code, text = quiet.command(["off"], self.NOW)
        self.assertEqual(code, 0)
        self.assertIn("levé", text)
        self.assertIsNone(quiet.quiet_state(self.NOW))
        self.assertIn("Pas de silence en cours", quiet.command(["reprendre"], self.NOW)[1])

    def test_off_keeps_the_range(self):
        s = self.conf()
        night = paris(2026, 11, 9, 23)
        quiet.command(["1h"], night, s)
        code, text = quiet.command(["off"], night, s)
        self.assertEqual(code, 0)
        self.assertIn("la plage de silence continue", text)

    def test_usage(self):
        self.assertEqual(quiet.command(["jamais"], self.NOW)[0], 2)
        self.assertEqual(quiet.command(["1h", "4h"], self.NOW)[0], 2)

    def test_choices_labels(self):
        c = quiet.choices(self.NOW)
        self.assertEqual([k for k, _ in c], ["1h", "4h", "demain"])
        self.assertIn("demain 08:00", c[2][1])


class SettingsTest(QuietBase):
    def test_defaults(self):
        q = load_settings()["alerts"]["quiet"]
        self.assertEqual(q, {"enabled": False, "start": "22:00", "end": "08:00",
                             "days": [0, 1, 2, 3, 4, 5, 6], "allow_waiting": True})

    def test_invalid_keys_fall_back_one_by_one(self):
        write(self.store / "settings.json", {"alerts": {"quiet": {
            "enabled": "oui", "start": "25:00", "end": "07:30", "days": [9], "allow_waiting": 1}}})
        q = load_settings()["alerts"]["quiet"]
        self.assertEqual((q["enabled"], q["start"], q["end"], q["days"], q["allow_waiting"]),
                         (False, "22:00", "07:30", [0, 1, 2, 3, 4, 5, 6], True))
        self.assertEqual(problems(), ["alerts.quiet.allow_waiting", "alerts.quiet.days",
                                      "alerts.quiet.enabled", "alerts.quiet.start"])

    def test_not_a_dict(self):
        write(self.store / "settings.json", {"alerts": {"quiet": 3}})
        self.assertEqual(load_settings()["alerts"]["quiet"], DEFAULTS["alerts"]["quiet"])
        self.assertEqual(problems(), ["alerts.quiet"])


class DaemonQuietTest(DaemonBase):
    def setUp(self):
        super().setUp()
        use_paris(self)

    def tick(self, now, settings=None):
        with fake_http(per_account(perso=usage(30), pro=usage(5))):
            return self.d.tick(settings or self.settings, now)

    def test_state_json_quiet_key(self):
        self.tick(DAEMON_NOW)
        self.assertEqual(self.state()["quiet"], {"active": False, "until": None,
                                                 "source": None, "held": 0})
        until = DAEMON_NOW + timedelta(hours=1)
        quiet.set_quiet(until, DAEMON_NOW)
        quiet.hold(alert("session:1:2"))
        self.tick(DAEMON_NOW)
        q = self.state()["quiet"]
        self.assertEqual((q["active"], q["source"], q["held"]), (True, "temporaire", 1))
        self.assertEqual(datetime.fromisoformat(q["until"]), until)

    def test_state_json_range(self):
        s = write_quiet(self, {})
        night = paris(2026, 11, 9, 23)
        self.tick(night, s)
        q = self.state()["quiet"]
        self.assertEqual((q["active"], q["source"]), (True, "plage"))

    def test_wakes_at_end_of_silence(self):
        quiet.set_quiet(DAEMON_NOW + timedelta(seconds=90), DAEMON_NOW)
        delay = self.tick(DAEMON_NOW)
        self.assertLess(delay, 100)
        self.assertGreaterEqual(delay, 90)

    def test_summary_sent_when_silence_ends(self):
        quiet.set_quiet(DAEMON_NOW + timedelta(minutes=10), DAEMON_NOW)
        quiet.hold(alert("session:1:2"))
        quiet.hold(alert("session95:perso:1"))
        self.tick(DAEMON_NOW)
        self.assertFalse([a for a in self.sent if a.key.startswith("silence:")])
        self.tick(DAEMON_NOW + timedelta(minutes=11))
        summaries = [a for a in self.sent if a.key.startswith("silence:")]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].body,
                         "Pendant le silence : 1 session terminée, 1 alerte de seuil.")
        self.tick(DAEMON_NOW + timedelta(minutes=12))
        self.assertEqual(len([a for a in self.sent if a.key.startswith("silence:")]), 1)

    def test_waiting_session_alert_key(self):
        from ccs_app import sessions
        def make(state, since, waiting_for=None):
            return sessions.Session(11, "abc", "nom", "/x/proj", "proj", state, waiting_for,
                                    1.0, since, "interactive", "cli")
        s, w = make("busy", 1.0), make("waiting", DAEMON_NOW.timestamp(), "ok ?")
        self.d.prev_sessions = {11: s}
        with mock.patch.object(sessions, "list_sessions", return_value=[w]):
            self.d.on_sessions(self.settings, DAEMON_NOW)
        self.assertTrue(self.sent[0].key.startswith("attente:11:"))


def write_quiet(case, cfg):
    cfg = dict({"enabled": True}, **cfg)
    write(case.store / "settings.json", {"alerts": {"quiet": cfg}})
    return load_settings()
