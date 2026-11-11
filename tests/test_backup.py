"""Sauvegarde chiffrée : vrai gpg, mais trousseau (GNUPGHOME) temporaire et phrase de passe
d'essai par le point d'injection `_TEST_GPG` ; dossier de comptes temporaire ; raccourcis
simulés. Jamais les vraies données ni le vrai trousseau."""

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import backup, core, shortcuts as sc
from tests.helpers import HomeTestCase, oauth_for, write
from tests.test_shortcuts import gnome

PHRASE = "phrase d'essai"
HAS_GPG = shutil.which("gpg") is not None


class GpgCase(HomeTestCase):
    """Trousseau temporaire + sécurité des raccourcis."""

    phrase = PHRASE

    def setUp(self):
        super().setUp()
        self.gnupg = tempfile.mkdtemp(prefix="gpg-", dir="/tmp")
        os.chmod(self.gnupg, 0o700)
        self._set_phrase(self.phrase)
        self.addCleanup(self._cleanup_gpg)
        for p in (mock.patch.object(sc, "default_backend",
                                    side_effect=AssertionError("vrais réglages GNOME interdits en test")),
                  mock.patch.object(sc, "command_for", side_effect=lambda a: "/usr/bin/" + sc.action(a).display),
                  mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"})):
            p.start()
            self.addCleanup(p.stop)
        self.sc = gnome()
        self.out = tempfile.mkdtemp(prefix="ccs-bak-", dir=self.tmp)

    def _set_phrase(self, phrase):
        backup._TEST_GPG = {"home": self.gnupg, "passphrase": phrase}

    def _cleanup_gpg(self):
        backup._TEST_GPG = None
        subprocess.run(["gpgconf", "--homedir", self.gnupg, "--kill", "gpg-agent"], capture_output=True)
        shutil.rmtree(self.gnupg, ignore_errors=True)

    def fill_store(self):
        write(self.store / "settings.json", {"auto_switch": {"enabled": False}})
        write(self.store / "projects.json", {"version": 1, "projects": {}})
        write(self.store / "budgets.json", {"version": 1, "budgets": {}})
        # À ne jamais sauvegarder
        write(self.store / "state.json", {"x": 1})
        write(self.store / "pause.json", {"x": 1})
        write(self.store / "history.db", "binaire")
        write(self.store / "perso" / "usage.json", {"cache": 1})
        write(self.store / "limits" / "abc.json", {"x": 1})
        write(self.store / "conversations-cache.json", {"x": 1})
        write(self.store / ".lock", "")

    def dest(self, name="b.gpg"):
        return Path(self.out) / name


class CollectTest(GpgCase):
    def test_what_is_included_and_excluded(self):
        self.fill_store()
        sc.install("suivant", "<Super><Alt>x", backend=self.sc)
        entries = backup.collect(self.sc)
        self.assertEqual(sorted(entries), [
            "profils/perso/account.json", "profils/perso/oauth.json",
            "profils/pro/account.json", "profils/pro/oauth.json",
            "raccourcis.json", "reglages/budgets.json", "reglages/projects.json",
            "reglages/settings.json"])
        self.assertEqual(json.loads(entries["raccourcis.json"]), {"actions": {"suivant": "<Super><Alt>x"}})
        self.assertIn(b"RT-perso", entries["profils/perso/oauth.json"])  # jetons compris

    def test_incomplete_profile_and_foreign_names_are_skipped(self):
        write(self.store / "orphelin" / "oauth.json", oauth_for("perso"))   # sans account.json
        (self.store / "a b").mkdir()
        write(self.store / "a b" / "oauth.json", {})
        write(self.store / "a b" / "account.json", {})
        names = {n.split("/")[1] for n in backup.collect(self.sc) if n.startswith("profils/")}
        self.assertEqual(names, {"perso", "pro"})

    def test_no_shortcuts_when_unsupported(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
            self.assertNotIn("raccourcis.json", backup.collect(self.sc))

    def test_default_name_is_dated(self):
        noon = time.mktime((2026, 11, 11, 12, 0, 0, 0, 0, -1))
        self.assertEqual(backup.default_name(noon), "ccs-sauvegarde-2026-11-11.gpg")
        self.assertTrue(backup.default_name().endswith(".gpg"))


@unittest.skipUnless(HAS_GPG, "gpg absent")
class RoundTripTest(GpgCase):
    def test_create_encrypts_with_aes256_and_is_private(self):
        self.fill_store()
        dest = self.dest()
        c = backup.create(dest, backend=self.sc)
        self.assertEqual(c.profiles, ["perso", "pro"])
        self.assertEqual(oct(dest.stat().st_mode & 0o777), "0o600")
        raw = dest.read_bytes()
        self.assertNotIn(b"RT-perso", raw)
        self.assertNotIn(b"ustar", raw)
        info = subprocess.run(["gpg", "--batch", "--list-packets", str(dest)], capture_output=True,
                              env={**os.environ, "GNUPGHOME": self.gnupg}).stdout.decode()
        self.assertIn("cipher 9", info)  # AES256
        self.assertEqual([p.name for p in Path(self.out).iterdir()], ["b.gpg"])  # pas de reste

    def test_refuses_to_overwrite(self):
        dest = self.dest()
        dest.write_text("déjà là")
        with self.assertRaisesRegex(backup.BackupError, "existe déjà"):
            backup.create(dest, backend=self.sc)
        self.assertEqual(dest.read_text(), "déjà là")

    def test_open_lists_without_tokens(self):
        self.fill_store()
        sc.install("pause", backend=self.sc)
        dest = self.dest()
        backup.create(dest, backend=self.sc)
        b = backup.open_backup(dest)
        self.assertEqual(b.contents.profiles, ["perso", "pro"])
        self.assertEqual(b.contents.files, ["budgets.json", "projects.json", "settings.json"])
        self.assertEqual(list(b.contents.shortcuts), ["pause"])
        text = backup.describe(b.contents)
        self.assertIn("perso, pro", text)
        self.assertNotIn("RT-", text)
        self.assertNotIn("AT-", text)

    def test_restore_into_empty_store_keeps_active_account_and_credentials(self):
        self.fill_store()
        sc.install("suivant", "<Super><Alt>x", backend=self.sc)
        dest = self.dest()
        backup.create(dest, backend=self.sc)
        shutil.rmtree(self.store)
        creds = core.paths().creds
        before = creds.read_bytes(), core.paths().global_json.read_bytes()
        other = gnome()
        r = backup.restore(dest, backend=other)
        self.assertEqual(r.profiles, ["perso", "pro"])
        self.assertEqual(r.overwritten, [])
        self.assertEqual(r.shortcuts, ["suivant"])
        self.assertEqual(sc.status(other).item("suivant").binding, "<Super><Alt>x")
        self.assertEqual(json.loads((self.store / "pro" / "oauth.json").read_text())["claudeAiOauth"]["refreshToken"],
                         "RT-pro")
        self.assertTrue((self.store / "budgets.json").exists())
        for p in (self.store / "perso" / "oauth.json", self.store / "settings.json"):
            self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
        self.assertFalse((self.store / "state.json").exists())
        self.assertEqual((creds.read_bytes(), core.paths().global_json.read_bytes()), before)
        self.assertEqual(core.active_profile_name(), "perso")
        self.assertEqual([p.name for p in (self.store / "perso").iterdir() if p.name.endswith(".tmp")
                          or p.name.startswith("oauth.json.")], [])

    def test_confirmation_before_overwriting(self):
        self.fill_store()
        dest = self.dest()
        backup.create(dest, backend=self.sc)
        write(self.store / "pro" / "oauth.json", {"claudeAiOauth": {"refreshToken": "autre"}})
        b = backup.open_backup(dest)
        self.assertEqual(b.conflicts(), ["pro"])      # perso et réglages identiques : pas écrasés
        asked = []
        with self.assertRaisesRegex(backup.BackupError, "annulée"):
            b.restore(confirm=lambda over: asked.append(over) or False, backend=self.sc)
        self.assertEqual(asked, [["pro"]])
        self.assertIn("autre", (self.store / "pro" / "oauth.json").read_text())   # intact
        with self.assertRaises(backup.BackupError):    # ni rappel ni --oui : refus
            b.restore(backend=self.sc)
        r = b.restore(confirm=lambda over: True, backend=self.sc)
        self.assertEqual(r.overwritten, ["pro"])
        self.assertIn("RT-pro", (self.store / "pro" / "oauth.json").read_text())

    def test_assume_yes_skips_the_question(self):
        self.fill_store()
        dest = self.dest()
        backup.create(dest, backend=self.sc)
        write(self.store / "settings.json", {"auto_switch": {"enabled": True}})
        r = backup.restore(dest, assume_yes=True, backend=self.sc)
        self.assertEqual(r.overwritten, ["settings.json"])
        self.assertEqual(json.loads((self.store / "settings.json").read_text()), {"auto_switch": {"enabled": False}})

    def test_unsupported_desktop_notes_the_shortcuts(self):
        sc.install("suivant", backend=self.sc)
        dest = self.dest()
        backup.create(dest, backend=self.sc)
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}):
            r = backup.restore(dest, assume_yes=True, backend=gnome())
        self.assertEqual(r.shortcuts, [])
        self.assertIn("bureau non pris en charge", r.note)


@unittest.skipUnless(HAS_GPG, "gpg absent")
class ErrorsTest(GpgCase):
    def test_wrong_passphrase(self):
        dest = self.dest()
        backup.create(dest, backend=self.sc)
        self._set_phrase("mauvaise")
        with self.assertRaisesRegex(backup.BackupError, "Mauvaise phrase de passe"):
            backup.open_backup(dest)

    def test_not_a_backup(self):
        dest = self.dest("x.gpg")
        dest.write_text("n'importe quoi")
        with self.assertRaisesRegex(backup.BackupError, "illisible"):
            backup.open_backup(dest)

    def test_truncated_file(self):
        dest = self.dest()
        backup.create(dest, backend=self.sc)
        dest.write_bytes(dest.read_bytes()[:40])
        with self.assertRaises(backup.BackupError):
            backup.open_backup(dest)

    def test_missing_file(self):
        with self.assertRaisesRegex(backup.BackupError, "introuvable"):
            backup.open_backup(self.dest("absent.gpg"))

    def test_gpg_missing(self):
        backup._TEST_GPG = None
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(backup.BackupError, "gpg est introuvable"):
                backup.create(self.dest(), backend=self.sc)
        self.assertEqual(list(Path(self.out).iterdir()), [])

    def test_cancelled_pinentry(self):
        r = subprocess.CompletedProcess([], 2, b"", b"[GNUPG:] ERROR pkdecrypt 83886179\ngpg: annul\n")
        with mock.patch("subprocess.run", return_value=r):
            backup._TEST_GPG = None
            with self.assertRaisesRegex(backup.BackupError, "annulée"):
                backup.create(self.dest(), backend=self.sc)

    def test_nothing_to_back_up(self):
        shutil.rmtree(self.store)
        with self.assertRaisesRegex(backup.BackupError, "Rien à sauvegarder"):
            backup.create(self.dest(), backend=self.sc)

    def test_missing_directory(self):
        with self.assertRaisesRegex(backup.BackupError, "n'existe pas"):
            backup.create(Path(self.out) / "nul" / "b.gpg", backend=self.sc)


class ParseTest(GpgCase):
    """Archives malveillantes ou abîmées : jamais d'extraction hors du dossier de comptes."""

    def tar(self, members, manifest=True):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            items = dict(members)
            if manifest:
                items[backup.MANIFEST] = json.dumps({"format": 1})
            for name, content in items.items():
                data = content.encode() if isinstance(content, str) else content
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                t.addfile(ti, io.BytesIO(data))
        return buf.getvalue()

    def test_path_traversal_refused(self):
        for name in ("../evil.json", "profils/../x/oauth.json", "/etc/passwd", "profils/a/b/oauth.json",
                     "reglages/state.json", "profils/.../oauth.json/x"):
            with self.subTest(name=name), self.assertRaisesRegex(backup.BackupError, "invalide"):
                backup._parse(self.tar({name: "{}"}))

    def test_link_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            ti = tarfile.TarInfo("profils/a/oauth.json")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            t.addfile(ti)
        with self.assertRaisesRegex(backup.BackupError, "invalide"):
            backup._parse(buf.getvalue())

    def test_dot_names_are_refused_as_profile(self):
        # « . » et « .. » correspondent à l'expression de nom : refusés explicitement
        for name in (".", ".."):
            members = {f"profils/{name}/oauth.json": "{}", f"profils/{name}/account.json": "{}"}
            with self.subTest(name=name), self.assertRaises(backup.BackupError):
                backup._parse(self.tar(members))

    def test_no_manifest_bad_format_bad_json_incomplete(self):
        with self.assertRaisesRegex(backup.BackupError, "manifeste"):
            backup._parse(self.tar({}, manifest=False))
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            data = b'{"format": 99}'
            ti = tarfile.TarInfo(backup.MANIFEST)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        with self.assertRaisesRegex(backup.BackupError, "format inconnu"):
            backup._parse(buf.getvalue())
        with self.assertRaisesRegex(backup.BackupError, "JSON"):
            backup._parse(self.tar({"reglages/settings.json": "pas du json"}))
        with self.assertRaisesRegex(backup.BackupError, "incomplet"):
            backup._parse(self.tar({"profils/a/oauth.json": "{}"}))
        with self.assertRaisesRegex(backup.BackupError, "abîmée"):
            backup._parse(b"pas un tar" * 100)

    def test_too_big(self):
        with mock.patch.object(backup, "MAX_MEMBER", 10):
            with self.assertRaisesRegex(backup.BackupError, "trop gros"):
                backup._parse(self.tar({"reglages/settings.json": json.dumps({"a": "x" * 50})}))

    def test_unknown_shortcut_actions_are_dropped(self):
        manifest = {"format": 1}
        entries = {"raccourcis.json": json.dumps({"actions": {"suivant": "<Super>x", "inconnue": "<Super>y",
                                                              "pause": 3}}).encode()}
        self.assertEqual(backup._contents(entries, manifest).shortcuts, {"suivant": "<Super>x"})


@unittest.skipUnless(HAS_GPG, "gpg absent")
class CommandTest(GpgCase):
    def run_cmd(self, *args, **kw):
        out, err = io.StringIO(), io.StringIO()
        code = backup.command(list(args), out=out, err=err, backend=self.sc, **kw)
        return code, out.getvalue(), err.getvalue()

    def test_save_default_name_in_cwd_then_restore(self):
        self.fill_store()
        cwd = os.getcwd()
        os.chdir(self.out)
        self.addCleanup(os.chdir, cwd)
        code, out, err = self.run_cmd("sauvegarde")
        self.assertEqual((code, err), (0, ""))
        files = list(Path(self.out).glob("ccs-sauvegarde-*.gpg"))
        self.assertEqual(len(files), 1)
        self.assertIn("perso, pro", out)
        self.assertNotIn("RT-", out)
        code, out, err = self.run_cmd("restaurer", str(files[0]), "--oui")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Le compte actif n'a pas changé", out)

    def test_restore_asks_unless_yes(self):
        self.fill_store()
        dest = self.dest()
        self.assertEqual(self.run_cmd("sauvegarde", str(dest))[0], 0)
        write(self.store / "pro" / "account.json", {"accountUuid": "z"})
        code, _out, err = self.run_cmd("restaurer", str(dest), confirm=lambda over: False)
        self.assertEqual(code, 1)
        self.assertIn("annulée", err)
        code, out, _err = self.run_cmd("restaurer", str(dest), confirm=lambda over: "pro" in over)
        self.assertEqual(code, 0)
        self.assertIn("écrasé : pro", out)

    def test_errors_give_exit_code_1(self):
        code, _out, err = self.run_cmd("restaurer", str(self.dest("absent.gpg")), "--oui")
        self.assertEqual(code, 1)
        self.assertIn("introuvable", err)

    def test_usage_errors(self):
        for args in (("restaurer",), ("restaurer", "a", "b"), ("sauvegarde", "--oui"), ("sauvegarde", "--x"),
                     ("sauvegarde", "a", "b")):
            with self.subTest(args=args):
                code, _o, err = self.run_cmd(*args)
                self.assertEqual(code, 2)
                self.assertIn("usage", err)


class NoSecretInProcessTest(GpgCase):
    def test_passphrase_never_in_argv_or_environment(self):
        seen = {}

        def fake(cmd, **kw):
            seen.update(cmd=cmd, env=kw["env"])
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        with mock.patch("subprocess.run", side_effect=fake):
            backup._TEST_GPG = None
            backup._run_gpg(["--symmetric"], b"x")
        self.assertNotIn("--passphrase", " ".join(seen["cmd"]))
        self.assertFalse(any("PASS" in k.upper() and k not in os.environ for k in seen["env"]))
        self.assertNotIn("--batch", seen["cmd"])  # production : pinentry, pas de mode batch


if __name__ == "__main__":
    unittest.main()
