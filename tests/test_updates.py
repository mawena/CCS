import http.client
import io
import json
import urllib.error
from unittest import mock

from ccs_app import updates
from ccs_app.settings import load_settings
from tests.helpers import HomeTestCase, write

T = 1_800_000_000.0  # instant de référence (secondes)
DAY = 86400

RELEASE = {"tag_name": "v0.5.0", "name": "CCS 0.5.0", "draft": False, "prerelease": False,
           "html_url": "https://github.com/mawena/CCS/releases/tag/v0.5.0"}


class NoNetwork(HomeTestCase):
    """Aucun appel réseau réel : urlopen échoue si un test l'atteint par erreur."""

    def setUp(self):
        super().setUp()
        guard = mock.patch("urllib.request.urlopen",
                           side_effect=AssertionError("appel réseau réel interdit dans les tests"))
        guard.start()
        self.addCleanup(guard.stop)
        self.settings = load_settings()
        self.sent = []

    def cache(self):
        return json.loads((self.store / "updates.json").read_text())


class VersionTest(NoNetwork):
    def test_parse(self):
        self.assertEqual(updates.parse_version("v0.5.0"), ((0, 5, 0), ()))
        self.assertEqual(updates.parse_version("1.2.3-rc.1+build.7"), ((1, 2, 3), ("rc", 1)))
        for bad in (None, "", "0.5", "v1.x.0", "1.2.3-", "1.2.3-a..b", 5):
            self.assertIsNone(updates.parse_version(bad), bad)

    def test_semver_precedence(self):
        ordered = ["0.4.0", "0.4.1", "0.10.0", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta",
                   "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
        for lo, hi in zip(ordered, ordered[1:]):
            self.assertEqual(updates.compare(lo, hi), -1, (lo, hi))
            self.assertEqual(updates.compare(hi, lo), 1, (hi, lo))
        self.assertEqual(updates.compare("v0.4.0", "0.4.0"), 0)
        self.assertEqual(updates.compare("1.0.0+a", "1.0.0+b"), 0)

    def test_is_newer(self):
        self.assertTrue(updates.is_newer("v0.5.0", "0.4.0"))
        self.assertFalse(updates.is_newer("0.4.0", "0.4.0"))
        self.assertFalse(updates.is_newer("0.3.9", "0.4.0"))
        self.assertFalse(updates.is_newer("n'importe quoi", "0.4.0"))
        self.assertFalse(updates.is_newer(None, "0.4.0"))


class ReleaseTest(NoNetwork):
    def test_parse_release(self):
        r = updates.parse_release(RELEASE)
        self.assertEqual((r.version, r.url), ("0.5.0", RELEASE["html_url"]))
        self.assertIsNone(updates.parse_release(dict(RELEASE, draft=True)))
        self.assertIsNone(updates.parse_release(dict(RELEASE, prerelease=True)))
        self.assertIsNone(updates.parse_release(dict(RELEASE, tag_name="dernière")))
        self.assertIsNone(updates.parse_release(["pas", "un", "objet"]))

    def test_only_links_to_the_project_page(self):
        r = updates.parse_release(dict(RELEASE, html_url="https://exemple.invalid/piege"))
        self.assertEqual(r.url, "https://github.com/mawena/CCS/releases/tag/v0.5.0")

    def opener(self, payload=None, error=None):
        calls = []

        def fake(req, timeout=None):
            calls.append((req, timeout))
            if error is not None:
                raise error
            return io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        return fake, calls

    def test_fetch_latest(self):
        fake, calls = self.opener(RELEASE)
        r = updates.fetch_latest(opener=fake)
        self.assertEqual(r.version, "0.5.0")
        req, timeout = calls[0]
        self.assertEqual(req.full_url, "https://api.github.com/repos/mawena/CCS/releases/latest")
        self.assertEqual(req.get_header("User-agent"), "ccs")
        self.assertIsNone(req.get_header("Authorization"))
        self.assertLessEqual(timeout, 10)

    def test_fetch_errors_are_never_fatal(self):
        cases = [
            (urllib.error.HTTPError(updates.RELEASES_URL, 403, "rate limited", {}, None), False),
            (urllib.error.HTTPError(updates.RELEASES_URL, 429, "too many", {}, None), False),
            (urllib.error.URLError("hors ligne"), True),
            (TimeoutError("délai"), True),
            (http.client.RemoteDisconnected("coupé"), True),
            (http.client.BadStatusLine("???"), True),
        ]
        for error, offline in cases:
            fake, _ = self.opener(error=error)
            with self.assertRaises(updates.FetchError) as ctx:
                updates.fetch_latest(opener=fake)
            self.assertEqual(ctx.exception.offline, offline, error)
        fake, _ = self.opener(b"{pas du json")
        with self.assertRaises(updates.FetchError):
            updates.fetch_latest(opener=fake)


class CheckTest(NoNetwork):
    def fetcher(self, *results):
        calls = []
        seq = list(results)

        def fetch():
            calls.append(1)
            r = seq.pop(0) if len(seq) > 1 else seq[0]
            if isinstance(r, Exception):
                raise r
            return updates.parse_release(r)
        return fetch, calls

    def test_at_most_one_check_per_day(self):
        fetch, calls = self.fetcher(RELEASE)
        updates.refresh(T, fetch)
        updates.refresh(T + 3600, fetch)
        updates.refresh(T + DAY - 1, fetch)
        self.assertEqual(len(calls), 1)
        updates.refresh(T + DAY, fetch)
        self.assertEqual(len(calls), 2)
        c = self.cache()
        self.assertEqual(c["latest"]["version"], "0.5.0")
        self.assertEqual(c["checked_at"], T + DAY)

    def test_rate_limit_waits_a_day_and_keeps_last_known_release(self):
        fetch, calls = self.fetcher(RELEASE, updates.FetchError("HTTP 403"))
        updates.refresh(T, fetch)
        updates.refresh(T + DAY, fetch)
        self.assertEqual(self.cache()["latest"]["version"], "0.5.0")
        self.assertEqual(self.cache()["error"], "HTTP 403")
        updates.refresh(T + DAY + 3 * 3600, fetch)
        self.assertEqual(len(calls), 2)

    def test_offline_retries_after_an_hour(self):
        fetch, calls = self.fetcher(updates.FetchError("réseau : hors ligne", offline=True))
        updates.refresh(T, fetch)
        updates.refresh(T + 1800, fetch)
        self.assertEqual(len(calls), 1)
        updates.refresh(T + 3600, fetch)
        self.assertEqual(len(calls), 2)

    def test_available_reads_the_cache_only(self):
        self.assertIsNone(updates.available("0.4.0"))
        write(self.store / "updates.json", {"checked_at": T, "latest": {
            "version": "0.5.0", "url": RELEASE["html_url"], "name": "CCS 0.5.0"}})
        self.assertEqual(updates.available("0.4.0").version, "0.5.0")
        self.assertIsNone(updates.available("0.5.0"))
        self.assertIsNone(updates.available("0.6.0"))

    def test_notified_once_per_version(self):
        fetch, calls = self.fetcher(RELEASE, RELEASE, dict(RELEASE, tag_name="v0.5.1"))
        first = updates.run(T, self.sent.append, self.settings, "0.4.0", fetch)
        self.assertEqual(first.title, "CCS 0.5.0 est disponible")
        self.assertIn(RELEASE["html_url"], first.body)
        self.assertIn("0.4.0", first.body)
        self.assertIsNone(updates.run(T + 60, self.sent.append, self.settings, "0.4.0", fetch))
        self.assertIsNone(updates.run(T + DAY, self.sent.append, self.settings, "0.4.0", fetch))
        newer = updates.run(T + 2 * DAY, self.sent.append, self.settings, "0.4.0", fetch)
        self.assertIn("0.5.1", newer.title)
        self.assertEqual([a.title for a in self.sent], ["CCS 0.5.0 est disponible",
                                                         "CCS 0.5.1 est disponible"])

    def test_nothing_when_up_to_date(self):
        fetch, _ = self.fetcher(RELEASE)
        self.assertIsNone(updates.run(T, self.sent.append, self.settings, "0.5.0", fetch))
        self.assertEqual(self.sent, [])

    def test_can_be_disabled(self):
        self.settings["updates"]["enabled"] = False
        fetch, calls = self.fetcher(RELEASE)
        self.assertIsNone(updates.run(T, self.sent.append, self.settings, "0.4.0", fetch))
        self.assertEqual((calls, self.sent), ([], []))

    def test_notifications_off_still_checks_but_stays_silent(self):
        self.settings["alerts"]["enabled"] = False
        fetch, calls = self.fetcher(RELEASE)
        self.assertIsNone(updates.run(T, self.sent.append, self.settings, "0.4.0", fetch))
        self.assertEqual((len(calls), self.sent), (1, []))
        # Notifications réactivées : l'annonce, jamais faite, arrive.
        self.settings["alerts"]["enabled"] = True
        self.assertIsNotNone(updates.run(T + 60, self.sent.append, self.settings, "0.4.0", fetch))

    def test_corrupted_cache_is_ignored(self):
        write(self.store / "updates.json", "{oups")
        fetch, calls = self.fetcher(RELEASE)
        self.assertIsNotNone(updates.run(T, self.sent.append, self.settings, "0.4.0", fetch))

    def test_hook_runs_the_network_part_in_a_thread(self):
        from datetime import datetime, timezone
        d = mock.Mock(notifier=self.sent.append)
        fetch, calls = self.fetcher(RELEASE)
        with mock.patch.object(updates, "fetch_latest", fetch), \
                mock.patch.object(updates, "__version__", "0.4.0"):
            t = updates.hook(d, [], self.settings, datetime.fromtimestamp(T, timezone.utc))
            self.assertIsNotNone(t)
            t.join(5)
            # Vérification faite : la suivante ne lance plus de fil (pas de réseau).
            self.assertIsNone(updates.hook(d, [], self.settings,
                                           datetime.fromtimestamp(T + 60, timezone.utc)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.sent), 1)
