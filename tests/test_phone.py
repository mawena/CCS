"""Notifications sur le téléphone : messages sans contenu, filtres, ne pas déranger, envoi simulé.
Aucun vrai réseau : `urlopen` est toujours un faux."""

import json
import threading
import unittest
from datetime import datetime, timezone
from unittest import mock

from ccs_app import phone
from ccs_app.alerts import Alert
from tests.helpers import HomeTestCase

TOPIC = "ccs-abcdefghijklmnopqrstuvwx"
NOW = datetime(2026, 11, 11, 14, 0, tzinfo=timezone.utc)


def settings(**phone_over):
    cfg = {"enabled": True, "server": "https://ntfy.example.org/", "topic": TOPIC}
    cfg.update(phone_over)
    return {"phone": cfg, "alerts": {"quiet": {"enabled": False, "allow_waiting": True}}}


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeUrlopen:
    def __init__(self, status=200, error=None):
        self.calls, self.status, self.error = [], status, error

    def __call__(self, req, timeout=None):
        self.calls.append((req, timeout))
        if self.error:
            raise self.error
        return FakeResponse(self.status)


def waiting(title="App attend ta réponse", key="attente:42:1"):
    return Alert(key, title, "Session secrète — Voulez-vous lire /home/u/mot-de-passe.txt ?", 1)


class ConfigTest(unittest.TestCase):
    def test_defaults_and_invalid_values(self):
        cfg = phone.config({})
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["server"], "https://ntfy.sh")
        self.assertEqual(cfg["events"], phone.DEFAULTS["events"])
        bad = phone.config({"phone": {"enabled": "oui", "server": 3, "topic": None,
                                      "events": {"waiting": "non", "task": False}}})
        self.assertFalse(bad["enabled"])
        self.assertEqual(bad["server"], "https://ntfy.sh")
        self.assertEqual(bad["topic"], "")
        self.assertTrue(bad["events"]["waiting"])
        self.assertFalse(bad["events"]["task"])

    def test_new_topic_is_random_and_valid(self):
        a, b = phone.new_topic(), phone.new_topic()
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("ccs-") and phone.valid_topic(a))
        self.assertGreaterEqual(len(a), 24)

    def test_subscribe_url(self):
        self.assertEqual(phone.subscribe_url(phone.config(settings())), "https://ntfy.example.org/" + TOPIC)
        self.assertIsNone(phone.subscribe_url(phone.config(settings(topic=""))))
        self.assertIsNone(phone.subscribe_url(phone.config(settings(topic="a/b"))))
        self.assertIsNone(phone.subscribe_url(phone.config(settings(server="file:///etc"))))
        self.assertIsNone(phone.subscribe_url(phone.config(settings(server="ftp://x"))))


class MessageTest(unittest.TestCase):
    def test_waiting_has_project_and_state_only(self):
        m = phone.message_for(waiting())
        self.assertEqual(m.event, "waiting")
        self.assertEqual(m.body, "App attend ta réponse.")
        blob = f"{m.title} {m.body}"
        for secret in ("secrète", "mot-de-passe", "/home"):
            self.assertNotIn(secret, blob)

    def test_end_of_reply_says_finished(self):
        m = phone.message_for(Alert("fin:42:1", "App : Claude a fini de répondre", "secret", 0), project="App")
        self.assertEqual(m.event, "waiting")                       # même réglage que l'attente
        self.assertEqual(m.title, "Claude a fini de répondre")
        self.assertEqual(m.body, "App : Claude a fini de répondre.")
        self.assertNotIn("attend", f"{m.title} {m.body}")

    def test_reminder(self):
        m = phone.message_for(waiting("App attend toujours ta réponse", "rappel:42:1"))
        self.assertEqual(m.event, "waiting")
        self.assertIn("toujours", m.body)
        self.assertIn("App", m.body)

    def test_project_argument_wins_and_paths_are_shortened(self):
        m = phone.message_for(waiting(), project="/home/u/Work/Secret")
        self.assertIn("Secret", m.body)
        self.assertNotIn("/home", m.body)

    def test_task_finished_and_failed(self):
        ok = phone.message_for(Alert("tache:7:fini", "Tâche finie", "texte privé", 1), project="App")
        bad = phone.message_for(Alert("tache:7:echec", "Tâche échouée", "texte privé", 1), project="App")
        self.assertEqual((ok.event, ok.title), ("task", "Tâche finie"))
        self.assertEqual(bad.title, "Tâche échouée")
        self.assertNotIn("privé", ok.body + bad.body)
        self.assertGreater(bad.priority, ok.priority)

    def test_switch_and_exhausted_never_name_an_account(self):
        sw = phone.message_for(Alert("switch:1", "Bascule automatique vers pro-perso", "perso à 96 %", 1))
        ex = phone.message_for(Alert("exhausted:perso:1", "Comptes Claude presque épuisés", "perso, pro", 2))
        for m in (sw, ex):
            self.assertNotIn("perso", m.title + m.body)
            self.assertNotIn("pro", (m.title + m.body).replace("projet", ""))
        self.assertEqual((sw.event, ex.event), ("switch", "exhausted"))
        self.assertEqual(ex.priority, 5)

    def test_other_alerts_have_no_message(self):
        for key in ("session:1:2", "eta:perso:1", "reset:perso:1", "budget:/x:2026-11-09:80",
                    "weekly_report:2026-11-09", "pause_end:1", "refus:perso:1"):
            self.assertIsNone(phone.message_for(Alert(key, "t", "b", 1)), key)


class DecideTest(HomeTestCase):
    def test_disabled_missing_topic_and_filters(self):
        alert = waiting()
        self.assertEqual(phone.decide(alert, settings(enabled=False), NOW)[1], "désactivé")
        self.assertEqual(phone.decide(alert, settings(topic=""), NOW)[1], "canal manquant")
        self.assertEqual(phone.decide(Alert("session:1:2", "t", "b", 1), settings(), NOW)[1], "sans objet")
        off = settings(events={"waiting": False, "task": True, "switch": True, "exhausted": True})
        self.assertEqual(phone.decide(alert, off, NOW)[1], "événement coupé")
        msg, why = phone.decide(alert, settings(), NOW)
        self.assertEqual((msg.event, why), ("waiting", ""))

    def test_quiet_hours_hold_everything_but_waiting(self):
        s = settings()
        s["alerts"]["quiet"]["allow_waiting"] = True
        with mock.patch("ccs_app.quiet.should_hold",
                        side_effect=lambda a, now=None, settings=None: None if str(a.key).startswith("attente")
                        else "bascule"):
            self.assertIsNotNone(phone.decide(waiting(), s, NOW)[0])
            sw = Alert("switch:1", "x", "y", 1)
            self.assertEqual(phone.decide(sw, s, NOW), (None, "ne pas déranger"))

    def test_real_quiet_module_with_temporary_silence(self):
        from ccs_app import quiet
        quiet.set_quiet(None, NOW)   # silence jusqu'à reprise manuelle (fichier du HOME de test)
        s = settings()
        s["alerts"]["quiet"] = {"enabled": False, "allow_waiting": True, "start": "22:00", "end": "07:00",
                                "days": [0, 1, 2, 3, 4, 5, 6]}
        self.assertIsNotNone(phone.decide(waiting(), s, NOW)[0])
        self.assertEqual(phone.decide(Alert("switch:1", "x", "y", 1), s, NOW)[1], "ne pas déranger")
        s["alerts"]["quiet"]["allow_waiting"] = False
        self.assertEqual(phone.decide(waiting(), s, NOW)[1], "ne pas déranger")


class SendTest(HomeTestCase):
    def test_request_headers_body_and_timeout(self):
        fake = FakeUrlopen()
        phone.send(waiting(), settings(), NOW, urlopen=fake, run=lambda f: f())
        (req, timeout), = fake.calls
        self.assertEqual(req.full_url, "https://ntfy.example.org/" + TOPIC)
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.data.decode(), "App attend ta réponse.")
        self.assertEqual(req.get_header("Priority"), "4")
        self.assertTrue(req.get_header("Tags"))
        self.assertLessEqual(timeout, 10)
        # Titre accentué : en-tête ASCII (RFC 2047), jamais une exception d'encodage.
        title = req.get_header("Title")
        title.encode("ascii")
        self.assertTrue(title.startswith("=?UTF-8?B?"))

    def test_runs_in_a_thread(self):
        fake = FakeUrlopen()
        t = phone.send(waiting(), settings(), NOW, urlopen=fake)
        self.assertIsInstance(t, threading.Thread)
        t.join(5)
        self.assertEqual(len(fake.calls), 1)

    def test_nothing_sent_when_not_needed(self):
        fake = FakeUrlopen()
        self.assertIsNone(phone.send(waiting(), settings(enabled=False), NOW, urlopen=fake))
        self.assertIsNone(phone.send(Alert("session:1", "t", "b", 1), settings(), NOW, urlopen=fake))
        self.assertEqual(fake.calls, [])

    def test_failures_never_raise_and_never_log_the_topic(self):
        for fake in (FakeUrlopen(error=OSError("réseau coupé " + TOPIC)), FakeUrlopen(status=500),
                     FakeUrlopen(error=TimeoutError())):
            with self.assertLogs("ccs.phone", "WARNING") as logs:
                phone.send(waiting(), settings(), NOW, urlopen=fake, run=lambda f: f())
            self.assertNotIn(TOPIC, "\n".join(logs.output))
        self.assertEqual(phone.deliver(phone.config(settings(topic="")), phone.sample_message(),
                                       FakeUrlopen())[0], False)

    def test_send_test_works_even_when_disabled(self):
        fake = FakeUrlopen()
        ok, text = phone.send_test(settings(enabled=False), urlopen=fake)
        self.assertTrue(ok)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("téléphone", text)
        ok, text = phone.send_test(settings(topic=""), urlopen=fake)
        self.assertFalse(ok)
        self.assertEqual(len(fake.calls), 1)
        ok, text = phone.send_test(settings(), urlopen=FakeUrlopen(error=OSError("x")))
        self.assertFalse(ok)

    def test_default_urlopen_is_never_reached_in_tests(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("réseau interdit")) as m:
            phone.send(waiting(), settings(enabled=False), NOW, run=lambda f: f())
            self.assertFalse(m.called)

    def test_body_is_valid_json_free_text(self):
        fake = FakeUrlopen()
        phone.send(Alert("tache:1:echec", "Tâche échouée", "b", 1), settings(), NOW, project="App",
                   urlopen=fake, run=lambda f: f())
        with self.assertRaises(ValueError):
            json.loads(fake.calls[0][0].data)


if __name__ == "__main__":
    unittest.main()
