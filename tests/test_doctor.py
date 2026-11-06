import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from ccs_app import __version__, core, doctor
from ccs_app.doctor import AVERTISSEMENT, ERREUR, OK, Check, Probes, TokenInfo
from tests.helpers import HomeTestCase, write

NOW = 1_800_000_000.0


def profile(name, active=False):
    return core.Profile(name=name, email=f"{name}@x.com", org="", plan="pro", active=active)


def healthy(**over):
    """Sondes d'un poste en bonne santé ; chaque test en remplace une ou deux."""
    values = dict(
        systemctl=lambda *args: (0, "active\n"),
        daemon_pid=lambda: 4242,
        state=lambda: {"updated_at": NOW - 120, "accounts": [{"name": "perso", "error": None}]},
        now=lambda: NOW,
        package_version=lambda: __version__,
        process_code=lambda pid: doctor.ProcessCode("/usr/lib/ccs", __version__, NOW - 3600),
        code_stamp=lambda path: NOW - 7200,
        extensions=lambda: {"installed": True, "enabled": True},
        watcher=lambda: True,
        desktop=lambda: "ubuntu:GNOME",
        tray_running=lambda: True,
        integration=lambda: {"statusline": "ccs", "hook": True},
        profiles=lambda: [profile("perso", active=True)],
        token_info=lambda p: TokenInfo(True, None, NOW + 3600),
        claude_bin=lambda: "/home/u/.local/bin/claude",
        claude_version=lambda path: "2.1.319 (Claude Code)",
        vte=lambda: True,
        which=lambda name: f"/usr/bin/{name}",
        local_deb=lambda version: None,
    )
    values.update(over)
    return Probes(**values)


def by_name(checks):
    return {c.nom: c for c in checks}


class RunChecksTest(unittest.TestCase):
    def test_everything_ok(self):
        checks = doctor.run_checks(healthy())
        self.assertTrue(checks)
        bad = [(c.nom, c.statut, c.detail) for c in checks if c.statut != OK]
        self.assertEqual(bad, [])
        self.assertEqual(doctor.exit_code(checks), 0)
        names = [c.nom for c in checks]
        for expected in ("Service ccs-daemon", "Relevés", "Version installée", "Code du service",
                         "Extension AppIndicator", "Indicateur", "Intégration Claude Code",
                         "Compte perso", "Commande claude", "Terminal intégré"):
            self.assertIn(expected, names)

    def test_a_failing_probe_does_not_stop_the_others(self):
        def boom():
            raise RuntimeError("D-Bus indisponible")
        checks = by_name(doctor.run_checks(healthy(watcher=boom)))
        self.assertEqual(checks["Extension AppIndicator"].statut, AVERTISSEMENT)
        self.assertIn("D-Bus indisponible", checks["Extension AppIndicator"].detail)
        self.assertEqual(checks["Commande claude"].statut, OK)


class ServiceTest(unittest.TestCase):
    def test_stopped_service(self):
        p = healthy(systemctl=lambda *a: (3, "inactive\n"), daemon_pid=lambda: None)
        c = doctor.check_service(p)
        self.assertEqual(c.statut, ERREUR)
        self.assertEqual(c.commande, "systemctl --user enable --now ccs-daemon")

    def test_failed_service(self):
        p = healthy(systemctl=lambda *a: (3, "failed\n"), daemon_pid=lambda: None)
        c = doctor.check_service(p)
        self.assertEqual((c.statut, c.commande), (ERREUR, "systemctl --user restart ccs-daemon"))

    def test_daemon_running_outside_systemd(self):
        p = healthy(systemctl=lambda *a: (3, "inactive\n"), daemon_pid=lambda: 99)
        c = doctor.check_service(p)
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertIn("99", c.detail)

    def test_no_systemctl(self):
        p = healthy(systemctl=lambda *a: (None, ""), daemon_pid=lambda: None)
        self.assertEqual(doctor.check_service(p).statut, AVERTISSEMENT)

    def test_state_freshness(self):
        self.assertEqual(doctor.check_state(healthy()).statut, OK)
        old = healthy(state=lambda: {"updated_at": NOW - 3 * 3600})
        c = doctor.check_state(old)
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertIn("3 h", c.detail)
        self.assertEqual(c.commande, "systemctl --user restart ccs-daemon")
        none = healthy(state=lambda: {}, systemctl=lambda *a: (3, "inactive\n"), daemon_pid=lambda: None)
        c = doctor.check_state(none)
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertEqual(c.commande, "claude-accounts collect")


class VersionTest(unittest.TestCase):
    def test_package_older_than_this_code(self):
        p = healthy(package_version=lambda: "0.0.1", local_deb=lambda v: f"/repo/dist/ccs_{v}_all.deb")
        c = doctor.check_package(p)
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertIn("0.0.1", c.detail)
        self.assertIn(__version__, c.detail)
        self.assertEqual(c.commande, f"sudo apt install /repo/dist/ccs_{__version__}_all.deb")

    def test_debian_revision_is_ignored(self):
        self.assertEqual(doctor.check_package(healthy(package_version=lambda: f"{__version__}-1")).statut, OK)

    def test_package_not_installed(self):
        c = doctor.check_package(healthy(package_version=lambda: None))
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertIn("non installé", c.detail)

    def test_daemon_runs_other_version(self):
        p = healthy(process_code=lambda pid: doctor.ProcessCode("/usr/lib/ccs", "0.0.9", NOW - 60))
        c = doctor.check_daemon_code(p)
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertIn("0.0.9", c.detail)
        self.assertEqual(c.commande, "systemctl --user restart ccs-daemon")

    def test_daemon_runs_code_older_than_files(self):
        p = healthy(code_stamp=lambda path: NOW - 1800,
                    process_code=lambda pid: doctor.ProcessCode("/usr/lib/ccs", __version__, NOW - 7200))
        c = doctor.check_daemon_code(p)
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertEqual(c.commande, "systemctl --user restart ccs-daemon")

    def test_recent_update_is_left_to_the_daemon(self):
        # Le service redémarre seul quand le code change : pas d'alerte tout de suite.
        p = healthy(code_stamp=lambda path: NOW - 60,
                    process_code=lambda pid: doctor.ProcessCode("/usr/lib/ccs", __version__, NOW - 7200))
        self.assertEqual(doctor.check_daemon_code(p).statut, OK)

    def test_daemon_not_running(self):
        self.assertIsNone(doctor.check_daemon_code(healthy(daemon_pid=lambda: None)))


class DesktopTest(unittest.TestCase):
    def test_extension_disabled(self):
        p = healthy(watcher=lambda: False, extensions=lambda: {"installed": True, "enabled": False})
        c = doctor.check_extension(p)
        self.assertEqual(c.statut, ERREUR)
        self.assertEqual(c.commande, "gnome-extensions enable ubuntu-appindicators@ubuntu.com")

    def test_extension_missing(self):
        p = healthy(watcher=lambda: False, extensions=lambda: {"installed": False, "enabled": False})
        c = doctor.check_extension(p)
        self.assertEqual((c.statut, c.commande), (ERREUR, "sudo apt install gnome-shell-extension-appindicator"))

    def test_extension_enabled_but_not_loaded(self):
        p = healthy(watcher=lambda: False)
        c = doctor.check_extension(p)
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertIsNone(c.commande)

    def test_other_desktop(self):
        p = healthy(watcher=lambda: False, desktop=lambda: "KDE", extensions=lambda: None)
        self.assertEqual(doctor.check_extension(p).statut, AVERTISSEMENT)

    def test_tray(self):
        c = doctor.check_tray(healthy(tray_running=lambda: False))
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertIn("claude-accounts tray", c.commande)

    def test_vte(self):
        c = doctor.check_vte(healthy(vte=lambda: False))
        self.assertEqual((c.statut, c.commande), (AVERTISSEMENT, "sudo apt install gir1.2-vte-3.91"))


class IntegrationTest(unittest.TestCase):
    def test_states(self):
        c = doctor.check_integration(healthy(integration=lambda: {"statusline": None, "hook": False}))
        self.assertEqual((c.statut, c.commande), (AVERTISSEMENT, "ccs integrate on"))
        c = doctor.check_integration(healthy(integration=lambda: {"statusline": "autre", "hook": True}))
        self.assertEqual(c.statut, OK)
        self.assertIn("conservée", c.detail)
        c = doctor.check_integration(healthy(integration=lambda: {"statusline": "ccs", "hook": False}))
        self.assertEqual(c.statut, AVERTISSEMENT)


class ClaudeTest(unittest.TestCase):
    def test_claude_found(self):
        c = doctor.check_claude(healthy())
        self.assertEqual(c.statut, OK)
        self.assertIn("2.1.319", c.detail)

    def test_claude_missing(self):
        c = doctor.check_claude(healthy(claude_bin=lambda: None))
        self.assertEqual(c.statut, ERREUR)
        self.assertIsNotNone(c.commande)

    def test_jq_missing(self):
        c = doctor.check_tools(healthy(which=lambda name: None))
        self.assertEqual((c.statut, c.commande), (ERREUR, "sudo apt install jq"))


class ProfileChecksTest(unittest.TestCase):
    def test_lost_connection(self):
        p = healthy(profiles=lambda: [profile("perso", True), profile("pro")],
                    token_info=lambda pr: TokenInfo(pr.name == "perso", None, None))
        checks = by_name(doctor.check_profiles(p))
        self.assertEqual(checks["Compte perso"].statut, OK)
        self.assertEqual(checks["Compte pro"].statut, ERREUR)
        self.assertEqual(checks["Compte pro"].commande, "ccs rm pro && ccs add pro")

    def test_expired_and_soon_expired_refresh_token(self):
        p = healthy(profiles=lambda: [profile("a"), profile("b")],
                    token_info=lambda pr: TokenInfo(True, NOW - 10 if pr.name == "a" else NOW + 86400, None))
        checks = by_name(doctor.check_profiles(p))
        self.assertEqual(checks["Compte a"].statut, ERREUR)
        self.assertIn("expirée", checks["Compte a"].detail)
        self.assertEqual(checks["Compte b"].statut, AVERTISSEMENT)

    def test_revoked_according_to_last_collect(self):
        p = healthy(state=lambda: {"updated_at": NOW, "accounts": [
            {"name": "perso", "error": "connexion expirée ou révoquée : supprime ce profil puis rajoute le compte"}]})
        [c] = doctor.check_profiles(p)
        self.assertEqual(c.statut, ERREUR)
        self.assertEqual(c.commande, "ccs rm perso && ccs add perso")

    def test_other_collect_error_is_a_warning_without_secrets(self):
        p = healthy(state=lambda: {"updated_at": NOW, "accounts": [
            {"name": "perso", "error": "HTTP 500 : erreur sk-ant-oat01-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 côté serveur"}]})
        [c] = doctor.check_profiles(p)
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertNotIn("sk-ant-oat01-ABCDEF", c.detail)

    def test_rate_limit_is_not_a_problem(self):
        p = healthy(state=lambda: {"updated_at": NOW, "accounts": [{"name": "perso", "error": "HTTP 429 : trop"}]})
        [c] = doctor.check_profiles(p)
        self.assertEqual(c.statut, OK)

    def test_no_profile(self):
        [c] = doctor.check_profiles(healthy(profiles=lambda: []))
        self.assertEqual(c.statut, AVERTISSEMENT)
        self.assertIn("ccs save", c.detail)


class TokenInfoTest(HomeTestCase):
    def test_reads_only_presence_and_dates(self):
        info = doctor.token_info(profile("perso", active=True))
        self.assertTrue(info.present)
        self.assertIsNotNone(info.access_expires_at)
        self.assertEqual(set(vars(info)), {"present", "refresh_expires_at", "access_expires_at"})
        for value in vars(info).values():
            self.assertNotIsInstance(value, str)

    def test_active_profile_uses_live_credentials(self):
        # Copie du profil vidée, mais le fichier vivant (compte actif) est connecté.
        data = core.load_json(self.store / "perso" / "oauth.json")
        data["claudeAiOauth"]["refreshToken"] = ""
        write(self.store / "perso" / "oauth.json", data)
        self.assertTrue(doctor.token_info(profile("perso", active=True)).present)

    def test_lost_and_expiring(self):
        data = core.load_json(self.store / "pro" / "oauth.json")
        data["claudeAiOauth"]["refreshToken"] = ""
        write(self.store / "pro" / "oauth.json", data)
        self.assertFalse(doctor.token_info(profile("pro")).present)
        data["claudeAiOauth"]["refreshToken"] = "RT-pro"
        data["claudeAiOauth"]["refreshTokenExpiresAt"] = 1_700_000_000_000
        write(self.store / "pro" / "oauth.json", data)
        info = doctor.token_info(profile("pro"))
        self.assertTrue(info.present)
        self.assertEqual(info.refresh_expires_at, 1_700_000_000.0)

    def test_missing_or_corrupt_file(self):
        (self.store / "pro" / "oauth.json").write_text("{pas du json")
        self.assertFalse(doctor.token_info(profile("pro")).present)
        (self.store / "pro" / "oauth.json").unlink()
        self.assertFalse(doctor.token_info(profile("pro")).present)

    def test_tokens_never_appear_in_the_report(self):
        p = healthy(profiles=core.list_profiles, token_info=doctor.token_info, now=time.time)
        checks = doctor.run_checks(p)
        text = doctor.format_text(checks, couleur=False) + json.dumps([vars(c) for c in checks])
        for secret in ("AT-perso", "RT-perso", "AT-pro", "RT-pro"):
            self.assertNotIn(secret, text)


class ProcessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccs-doctor-"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_package_dir_of_launcher(self):
        repo = self.tmp / "repo"
        (repo / "ccs_app").mkdir(parents=True)
        (repo / "bin").mkdir()
        (repo / "bin" / "claude-accounts").write_text("#!/usr/bin/python3\n")
        self.assertEqual(doctor.package_dir(["/usr/bin/python3", str(repo / "bin" / "claude-accounts"), "daemon"]),
                         str(repo))
        self.assertEqual(doctor.package_dir(["/usr/bin/python3", "/usr/bin/claude-accounts", "daemon"]),
                         "/usr/lib/ccs")
        self.assertEqual(doctor.package_dir(["/usr/bin/python3", "-m", "ccs_app.cli", "daemon"], cwd=str(repo)),
                         str(repo))

    def test_read_version(self):
        (self.tmp / "ccs_app").mkdir()
        (self.tmp / "ccs_app" / "__init__.py").write_text('"""doc"""\n\n__version__ = "9.8.7"\n')
        self.assertEqual(doctor.read_version(str(self.tmp)), "9.8.7")
        self.assertIsNone(doctor.read_version(str(self.tmp / "absent")))

    def proc(self, pid, argv):
        d = self.tmp / "proc" / str(pid)
        d.mkdir(parents=True)
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")

    def test_tray_running(self):
        self.proc(10, ["/usr/bin/python3", "/usr/bin/claude-accounts", "daemon"])
        self.assertFalse(doctor.tray_running(proc=str(self.tmp / "proc")))
        self.proc(11, ["/usr/bin/python3", "/usr/bin/claude-accounts", "tray"])
        self.assertTrue(doctor.tray_running(proc=str(self.tmp / "proc")))

    def test_process_code(self):
        repo = self.tmp / "repo"
        (repo / "ccs_app").mkdir(parents=True)
        (repo / "ccs_app" / "__init__.py").write_text('__version__ = "1.2.3"\n')
        (repo / "bin").mkdir()
        (repo / "bin" / "claude-accounts").write_text("")
        self.proc(20, ["/usr/bin/python3", str(repo / "bin" / "claude-accounts"), "daemon"])
        code = doctor.process_code(20, proc=str(self.tmp / "proc"))
        self.assertEqual((code.path, code.version), (str(repo), "1.2.3"))
        self.assertIsNone(doctor.process_code(21, proc=str(self.tmp / "proc")))


class FormatTest(unittest.TestCase):
    def test_text_and_exit_code(self):
        checks = [Check("Service ccs-daemon", OK, "actif"),
                  Check("Compte pro", ERREUR, "connexion perdue", "ccs rm pro && ccs add pro"),
                  Check("Indicateur", AVERTISSEMENT, "non lancé")]
        text = doctor.format_text(checks, couleur=False)
        self.assertIn("✔ Service ccs-daemon", text)
        self.assertIn("✖ Compte pro", text)
        self.assertIn("⚠ Indicateur", text)
        self.assertIn("→ ccs rm pro && ccs add pro", text)
        self.assertIn("1 erreur, 1 avertissement", text)
        self.assertNotIn("\033[", text)
        self.assertIn("\033[", doctor.format_text(checks, couleur=True))
        self.assertEqual(doctor.exit_code(checks), 1)
        self.assertEqual(doctor.exit_code(checks[:1]), 0)
        self.assertIn("Tout va bien", doctor.format_text(checks[:1], couleur=False))

    def test_main_prints_and_returns_code(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            code = doctor.main(couleur=False, probes=healthy(vte=lambda: False))
        self.assertEqual(code, 1)
        self.assertIn("Terminal intégré", out.getvalue())


if __name__ == "__main__":
    unittest.main()
