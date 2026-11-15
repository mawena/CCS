"""Réponses du téléphone aux autorisations : jeton à usage unique, expiration, notification,
écoute. Aucun vrai réseau : `urlopen` est toujours un faux."""

import io
import logging
import threading
import unittest

from ccs_app import phone, phone_reply, settings
from tests.helpers import HomeTestCase

CFG = {"enabled": True, "server": "https://ntfy.example.org", "topic": "ccs-canal-principal-123"}
REPLY = "ccs-reponses-secretes-456"


class RepliesTest(unittest.TestCase):
    def test_verify_once(self):
        r = phone_reply.Replies()
        token = r.issue("req_1", now=1000.0)
        self.assertEqual(r.verify(f"allow req_1 {token}", now=1010.0), ("req_1", "allow"))
        self.assertIsNone(r.verify(f"allow req_1 {token}", now=1011.0))      # déjà servi
        token = r.issue("req_2", now=1000.0)
        self.assertEqual(r.verify(f"deny req_2 {token}", now=1001.0), ("req_2", "deny"))

    def test_verify_expired(self):
        r = phone_reply.Replies()
        token = r.issue("req_1", now=1000.0)
        self.assertIsNone(r.verify(f"allow req_1 {token}", now=1000.0 + phone_reply.TOKEN_TTL + 1))
        token = r.issue("req_2", now=1000.0)
        self.assertEqual(r.verify(f"allow req_2 {token}", now=1000.0 + phone_reply.TOKEN_TTL - 1),
                         ("req_2", "allow"))

    def test_verify_unknown_token(self):
        r = phone_reply.Replies()
        token = r.issue("req_1", now=1000.0)
        for body in ("allow req_1 mauvais-jeton", f"allow req_9 {token}", f"peut-etre req_1 {token}",
                     "allow req_1", "", "n'importe quoi du tout ici"):
            self.assertIsNone(r.verify(body, now=1001.0), body)
        # un refus ne brûle pas le jeton : le vrai téléphone peut encore répondre
        self.assertEqual(r.verify(f"allow req_1 {token}", now=1002.0), ("req_1", "allow"))

    def test_refusals_are_logged_without_the_token(self):
        r = phone_reply.Replies()
        token = r.issue("req_1", now=1000.0)
        with self.assertLogs("ccs.phone", level=logging.WARNING) as logs:
            r.verify("allow req_1 faux-jeton-secret", now=1001.0)
            r.verify(f"allow req_1 {token}", now=1000.0 + phone_reply.TOKEN_TTL + 5)
        text = "\n".join(logs.output)
        self.assertNotIn("faux-jeton-secret", text)
        self.assertNotIn(token, text)
        self.assertEqual(len(logs.output), 2)

    def test_settled_on_pc_ignored(self):
        r = phone_reply.Replies()
        token = r.issue("req_1", now=1000.0)
        r.settle("req_1")                                     # réglée sur le PC
        self.assertIsNone(r.verify(f"allow req_1 {token}", now=1001.0))
        self.assertFalse(r.pending())

    def test_pending_tracks_open_requests(self):
        r = phone_reply.Replies()
        self.assertFalse(r.pending())
        t = r.issue("a", now=1.0)
        self.assertTrue(r.pending())
        r.verify(f"allow a {t}", now=2.0)
        self.assertFalse(r.pending())


class ActionsTest(unittest.TestCase):
    def test_actions_header_format(self):
        header = phone_reply.actions_header(CFG, REPLY, "req_1", "tok-en_1")
        self.assertEqual(
            header,
            "http, Autoriser, https://ntfy.example.org/ccs-reponses-secretes-456, method=POST, "
            "body=allow req_1 tok-en_1, clear=true; "
            "http, Refuser, https://ntfy.example.org/ccs-reponses-secretes-456, method=POST, "
            "body=deny req_1 tok-en_1, clear=true")

    def test_message_hides_content_by_default(self):
        msg = phone_reply.permission_message("Bash", "monprojet", "rm -rf /secret/dossier", False)
        self.assertEqual(msg.title, "Commande dans monprojet")
        self.assertEqual(msg.body, "Réponds depuis la notification ou sur le PC")
        self.assertNotIn("secret", msg.title + msg.body)

    def test_message_shows_content_when_enabled(self):
        msg = phone_reply.permission_message("Edit", "monprojet", "/home/u/monprojet/a.py", True)
        self.assertEqual(msg.title, "Modification de fichier dans monprojet")
        self.assertEqual(msg.body, "/home/u/monprojet/a.py")

    def test_kinds(self):
        title = lambda k: phone_reply.permission_message(k, "p", "d", False).title   # noqa: E731
        self.assertEqual(title("Read"), "Lecture dans p")
        self.assertEqual(title("Grep"), "Lecture dans p")
        self.assertEqual(title("WebFetch"), "Autre action dans p")
        self.assertEqual(title("Commande"), "Commande dans p")

    def test_request_carries_the_actions_header(self):
        msg = phone_reply.permission_message("Bash", "p", "ls", False)
        req = phone.build_request(CFG, msg, actions="http, Autoriser, https://x/y")
        self.assertEqual(req.get_header("Actions"), "http, Autoriser, https://x/y")
        self.assertIsNone(phone.build_request(CFG, msg).get_header("Actions"))


class ReplyTopicTest(HomeTestCase):
    def test_reply_topic_is_created_once_and_kept(self):
        cfg = settings.load_settings()
        self.assertEqual(cfg["phone"]["reply_topic"], "")
        topic = phone_reply.reply_topic(cfg)
        self.assertTrue(phone.valid_topic(topic))
        self.assertTrue(topic.startswith("ccs-"))
        self.assertEqual(settings.load_settings()["phone"]["reply_topic"], topic)   # enregistré
        self.assertEqual(phone_reply.reply_topic(settings.load_settings()), topic)  # puis réutilisé


class FakeStream(io.BytesIO):
    pass


class ListenerTest(unittest.TestCase):
    def test_listener_calls_on_body(self):
        got, urls = [], []
        seen = threading.Event()

        def urlopen(req, timeout=None):
            urls.append(req.full_url if hasattr(req, "full_url") else req)
            return FakeStream(b'{"event":"open","topic":"x"}\n'
                              b'{"event":"keepalive"}\n'
                              b'{"event":"message","message":"allow req_1 tok"}\n'
                              b'pas du json\n'
                              b'{"event":"message","message":"deny req_2 tok2"}\n')

        def on_body(body):
            got.append(body)
            if len(got) == 2:
                seen.set()
        listener = phone_reply.Listener(CFG, REPLY, on_body, urlopen=urlopen)
        listener.start()
        self.assertTrue(seen.wait(5))
        listener.stop()
        self.assertEqual(got[:2], ["allow req_1 tok", "deny req_2 tok2"])
        self.assertTrue(urls[0].startswith(f"https://ntfy.example.org/{REPLY}/json?since="))

    def test_listener_stops_promptly(self):
        started = threading.Event()

        def urlopen(req, timeout=None):
            started.set()
            raise OSError("serveur injoignable")
        listener = phone_reply.Listener(CFG, REPLY, lambda b: None, urlopen=urlopen)
        listener.start()
        self.assertTrue(started.wait(3))
        listener.stop()
        listener.join(3)
        self.assertFalse(listener.alive())


if __name__ == "__main__":
    unittest.main()
