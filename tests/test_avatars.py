"""Avatars des auteurs : adresse de l'image, cache sur disque, aucun vrai réseau."""

import hashlib
import io
import os
import time
import urllib.error

from ccs_app import avatars
from tests.helpers import HomeTestCase

PNG = b"\x89PNG\r\n\x1a\nimage"


class FakeOpen:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, req, timeout=None):
        self.calls.append(req.full_url if hasattr(req, "full_url") else req)
        if isinstance(self.result, Exception):
            raise self.result
        return io.BytesIO(self.result)


class AvatarTest(HomeTestCase):
    def test_url_github_noreply_with_id(self):
        self.assertEqual(avatars.url_for("12345+mawena@users.noreply.github.com"),
                         "https://avatars.githubusercontent.com/u/12345?s=64")
        self.assertEqual(avatars.url_for("mawena@users.noreply.github.com", size=32),
                         "https://github.com/mawena.png?size=32")

    def test_url_gravatar_md5(self):
        md5 = hashlib.md5(b"test@example.org").hexdigest()
        self.assertEqual(avatars.url_for("  Test@Example.org "),
                         f"https://www.gravatar.com/avatar/{md5}?s=64&d=404")

    def test_initials(self):
        self.assertEqual(avatars.initials("charles gamligo"), "CG")
        self.assertEqual(avatars.initials("mawena"), "M")
        self.assertEqual(avatars.initials("  "), "?")
        self.assertEqual(avatars.initials("jean pierre marie"), "JP")

    def test_cache_path_in_store(self):
        p = avatars.cache_path("test@example.org")
        self.assertEqual(p.parent, self.store / "avatars")
        self.assertEqual(p.suffix, ".png")

    def test_fetch_caches(self):
        opener = FakeOpen(PNG)
        p = avatars.fetch("test@example.org", urlopen=opener)
        self.assertEqual(p.read_bytes(), PNG)
        self.assertEqual(avatars.fetch("test@example.org", urlopen=FakeOpen(RuntimeError("réseau"))), p)
        self.assertEqual(len(opener.calls), 1)

    def test_fetch_404_remembered(self):
        err = urllib.error.HTTPError("u", 404, "absent", {}, None)
        self.assertIsNone(avatars.fetch("x@example.org", urlopen=FakeOpen(err)))
        again = FakeOpen(PNG)
        self.assertIsNone(avatars.fetch("x@example.org", urlopen=again))
        self.assertEqual(again.calls, [])
        none = avatars.cache_path("x@example.org").with_suffix(".none")
        old = time.time() - 8 * 86400
        os.utime(none, (old, old))
        self.assertIsNotNone(avatars.fetch("x@example.org", urlopen=again))

    def test_fetch_network_error_is_none(self):
        self.assertIsNone(avatars.fetch("y@example.org", urlopen=FakeOpen(OSError("hors ligne"))))
        self.assertFalse(avatars.cache_path("y@example.org").with_suffix(".none").exists())

    def test_fetch_empty_email(self):
        self.assertIsNone(avatars.fetch("", urlopen=FakeOpen(PNG)))
