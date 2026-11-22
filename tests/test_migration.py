"""Migration des anciens noms (1.0.0) : fichiers renommés au premier usage, anciennes clés et
variables encore lues. Tout se passe dans un HOME temporaire."""

import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import (backup, chat_engine, core, distant, distant_jobs, message_tags, migrate,
                     project_accounts, quiet, settings)
from ccs_app.server import portier


class HomeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        for var in ("CCS_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                    "XDG_DATA_HOME"):
            os.environ.pop(var, None)
        self.addCleanup(self.tmp.cleanup)
        self.store = self.home / ".claude-accounts"

    def put(self, path, text="{}"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class RenamedTest(HomeCase):
    def test_old_file_is_renamed_when_new_is_missing(self):
        old = self.put(self.home / "a" / "vieux.json", '{"v": 1}')
        new = migrate.renamed(self.home / "b" / "neuf.json", old)
        self.assertEqual(new.read_text(), '{"v": 1}')
        self.assertFalse(old.exists())

    def test_new_file_wins_and_old_is_kept(self):
        old = self.put(self.home / "vieux.json", "ancien")
        new = self.put(self.home / "neuf.json", "nouveau")
        self.assertEqual(migrate.renamed(new, old).read_text(), "nouveau")
        self.assertEqual(old.read_text(), "ancien")

    def test_nothing_to_migrate(self):
        new = migrate.renamed(self.home / "neuf.json", self.home / "vieux.json")
        self.assertFalse(new.exists())
        self.assertFalse(new.parent.joinpath("vieux.json").exists())

    def test_folders_move_with_their_content(self):
        self.put(self.store / "etiquettes" / "s1.json")
        self.assertEqual(message_tags.folder(), self.store / "labels")
        self.assertTrue((self.store / "labels" / "s1.json").is_file())
        self.assertFalse((self.store / "etiquettes").exists())


class StoreFilesTest(HomeCase):
    def test_every_renamed_store_file(self):
        cases = [(quiet.held_path, "quiet_held.json", "quiet-held.json"),
                 (project_accounts.path, "projects.json", "project-accounts.json")]
        for fn, old, new in cases:
            self.put(self.store / old, json.dumps({"old": old}))
            self.assertEqual(fn(), self.store / new)
            self.assertEqual(json.loads((self.store / new).read_text()), {"old": old})
            self.assertFalse((self.store / old).exists())

    def test_project_accounts_are_read_from_the_old_file(self):
        self.put(self.store / "projects.json", json.dumps(
            {"version": 1, "projects": {"/home/u/App": {"profile": "pro"}}}))
        self.assertEqual(project_accounts.get("/home/u/App/src").profile, "pro")


class XdgTest(HomeCase):
    def test_defaults_under_home(self):
        self.assertEqual(core.ccs_dir("config"), self.home / ".config" / "ccs")
        self.assertEqual(core.ccs_dir("cache"), self.home / ".cache" / "ccs")
        self.assertEqual(core.ccs_dir("data"), self.home / ".local" / "share" / "ccs")

    def test_variables_are_respected_when_absolute(self):
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "XDG_CACHE_HOME": str(self.home / "c"),
               "XDG_DATA_HOME": "relatif"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(distant.client_path(), self.home / "cfg" / "ricochet" / "client.toml")
            self.assertEqual(distant.overrides_path(), self.home / "cfg" / "ccs" / "machines.toml")
            self.assertEqual(distant_jobs.jobs_dir(), self.home / "c" / "ccs" / "machines" / "jobs")
            self.assertEqual(chat_engine.clear_requests_dir(), self.home / "c" / "ccs" / "clear")
            self.assertEqual(core.ccs_dir("data"), self.home / ".local" / "share" / "ccs")


class MachinesTest(HomeCase):
    def test_old_toml_is_renamed_and_its_keys_read(self):
        self.put(self.home / ".config" / "ccs" / "distant.toml",
                 '[machines.pc]\nutilisateur = "charles"\nlimite = 3\n')
        over = distant.load_overrides()
        self.assertEqual(over["pc"], {"user": "charles", "limit": 3})
        self.assertEqual(distant.limit_for("pc", over), 3)
        self.assertTrue((self.home / ".config" / "ccs" / "machines.toml").is_file())
        distant.set_limit("pc", 2)
        text = distant.overrides_path().read_text()
        self.assertIn("limit = 2", text)
        self.assertNotIn("limite", text)

    def test_old_jobs_folder_and_inventory_are_renamed(self):
        cache = self.home / ".cache" / "ccs"
        self.put(cache / "distant" / "travaux" / "abc123.json")
        self.put(cache / "distant.json", '{"pc": {"quand": 1}}')
        self.assertTrue((distant_jobs.jobs_dir() / "abc123.json").is_file())
        self.assertEqual(distant._inventory_file(), cache / "machines.json")
        self.assertTrue((cache / "machines.json").is_file())

    def test_tool_lines_old_and_new(self):
        path, tools = distant.parse_inventory(
            "CCS_PATH=/usr/bin\nCCS_TOOL=flutter=/f/flutter\nCCS_OUTIL=cargo=/c/cargo\n")
        self.assertEqual((path, tools), ("/usr/bin", {"flutter": "/f/flutter", "cargo": "/c/cargo"}))


class KeysTest(HomeCase):
    def test_portier_old_keys(self):
        old = portier.parse({"portier": {"actif": True, "utilisateurs": ["a"], "url": "https://p",
                                         "deconnexion": "https://p/sortie"}})
        new = portier.parse({"portier": {"enabled": True, "users": ["a"], "url": "https://p",
                                         "logout": "https://p/sortie"}})
        self.assertEqual(old, new)
        self.assertTrue(new["enabled"])
        # la nouvelle clé l'emporte
        both = portier.parse({"portier": {"enabled": False, "actif": True, "users": ["a"]}})
        self.assertFalse(both["enabled"])

    def test_color_scheme_old_values(self):
        self.put(self.store / "settings.json", '{"appearance": {"color_scheme": "sombre"}}')
        self.assertEqual(settings.load_settings()["appearance"]["color_scheme"], "dark")
        self.assertEqual(settings.problems(), [])

    def test_clear_token_variable(self):
        self.assertEqual(chat_engine.CLEAR_TOKEN_VAR, "CCS_CHAT_TOKEN")
        from ccs_app import cli
        env = {"XDG_CACHE_HOME": str(self.home / "c"), chat_engine.CLEAR_TOKEN_VAR: "",
               chat_engine.OLD_CLEAR_TOKEN_VAR: "ab12"}
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(cli.main(["chat", "effacer"]), 0)
        self.assertTrue((self.home / "c" / "ccs" / "clear" / "ab12").exists())


class BackupFormat1Test(unittest.TestCase):
    def test_old_member_names_are_read(self):
        members = {backup.MANIFEST: json.dumps({"format": 1, "cree": "2026-11-01T10:00:00"}),
                   "profils/perso/oauth.json": "{}", "profils/perso/account.json": "{}",
                   "reglages/projects.json": "{}", "reglages/settings.json": "{}",
                   "raccourcis.json": json.dumps({"actions": {"pause": "<Super>p"}})}
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name, text in members.items():
                data = text.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        manifest, entries = backup._parse(buf.getvalue())
        self.assertEqual(sorted(entries), [
            "profiles/perso/account.json", "profiles/perso/oauth.json",
            "settings/project-accounts.json", "settings/settings.json", "shortcuts.json"])
        c = backup._contents(entries, manifest)
        self.assertEqual((c.created, c.profiles, c.files, c.shortcuts),
                         ("2026-11-01T10:00:00", ["perso"], ["project-accounts.json", "settings.json"],
                          {"pause": "<Super>p"}))


if __name__ == "__main__":
    unittest.main()
