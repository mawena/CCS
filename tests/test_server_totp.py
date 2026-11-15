"""Codes TOTP : vérification, enregistrement du secret, QR code."""

import os
import shutil
import stat
import tempfile
import unittest
from unittest import mock

import pyotp

from ccs_app.server import paths, totp

NOW = 1_700_000_000


class TotpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-totp-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"CCS_SERVER_ROOT": self.tmp})
        env.start()
        self.addCleanup(env.stop)
        self.secret = totp.new_secret()

    def code(self, t):
        return pyotp.TOTP(self.secret).at(t)

    def test_verify_accepts_current_and_adjacent(self):
        for t in (NOW, NOW - 30, NOW + 30):
            self.assertTrue(totp.verify(self.secret, self.code(t), NOW), t)
        self.assertFalse(totp.verify(self.secret, self.code(NOW - 90), NOW))

    def test_verify_rejects_wrong_or_malformed(self):
        good = self.code(NOW)
        wrong = f"{(int(good) + 1) % 1_000_000:06d}"
        for bad in (wrong, "12345", "abcdef", " " + good, good + " ", "", None, 123456):
            self.assertFalse(totp.verify(self.secret, bad, NOW), repr(bad))

    def test_save_mode_and_reset(self):
        self.assertIsNone(totp.load("alice"))
        totp.save("alice", self.secret)
        self.assertEqual(totp.load("alice"), self.secret)
        f = paths.totp_file("alice")
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(f.parent).st_mode), 0o700)
        self.assertTrue(totp.reset("alice"))
        self.assertIsNone(totp.load("alice"))
        self.assertFalse(totp.reset("alice"))

    def test_bad_user_name_refused(self):
        with self.assertRaises(ValueError):
            totp.save("../root", self.secret)

    def test_qr_svg_is_svg(self):
        svg = totp.qr_svg(totp.uri("alice", self.secret, "ccs.mawena.cloud"))
        self.assertIn("<svg", svg)
        self.assertNotIn("<script", svg)

    def test_uri_contains_issuer(self):
        u = totp.uri("alice", self.secret, "ccs.mawena.cloud")
        self.assertTrue(u.startswith("otpauth://totp/"))
        self.assertIn("issuer=CCS", u)
        self.assertIn("alice%40ccs.mawena.cloud", u)


if __name__ == "__main__":
    unittest.main()
