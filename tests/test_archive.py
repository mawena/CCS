"""Archive des conversations : copie gzip, mise à jour, restauration, recherche, intégration
à l'historique, à l'aperçu et au coût. Tout se passe dans un HOME et un XDG_DATA_HOME
temporaires, avec de faux journaux."""

import gzip
import io
import json
import os
import shutil
import stat
import tarfile
import time
from pathlib import Path
from unittest import mock

from ccs_app import archive, conversations, preview, sessions
from tests.helpers import HomeTestCase

NOW = time.time()
DAY = 86400
TS = "2026-11-04T10:00:00.000Z"


def user(text, cwd):
    return {"type": "user", "message": {"role": "user", "content": text}, "cwd": cwd,
            "entrypoint": "cli", "gitBranch": "main", "timestamp": TS, "uuid": f"u-{text}"}


def reply(text, tokens=100):
    return {"type": "assistant", "timestamp": TS, "uuid": f"a-{text}",
            "message": {"id": f"m-{text}", "role": "assistant", "model": "claude-sonnet-5-5",
                        "content": [{"type": "text", "text": text}],
                        "usage": {"input_tokens": tokens, "output_tokens": 50}}}


class ArchiveTestCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.data = self.home / ".local" / "share"
        patch = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.data)})
        patch.start()
        self.addCleanup(patch.stop)
        self.app = self.home / "Work" / "App"
        self.app.mkdir(parents=True)
        self.slug = sessions.project_slug(str(self.app))

    def journal(self, sid, text="bonjour", age_days=5, cwd=None):
        cwd = str(cwd or self.app)
        p = self.home / ".claude" / "projects" / sessions.project_slug(cwd) / f"{sid}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in (user(text, cwd), reply("voici"))))
        when = NOW - age_days * DAY
        os.utime(p, (when, when))
        return p

    def subagent(self, journal, name="agent-1", text="sous-agent"):
        d = journal.with_suffix("") / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{name}.jsonl"
        f.write_text(json.dumps(reply(text)) + "\n")
        old = NOW - 5 * DAY
        os.utime(f, (old, old))
        os.utime(d, (old, old))
        return f


class PassTest(ArchiveTestCase):
    def test_archives_idle_conversation_with_private_permissions(self):
        p = self.journal("s1", "corrige le bug")
        res = archive.archive_pass(NOW)
        self.assertEqual(res.archived, ["s1"])
        root = archive.archive_dir()
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        gz = root / self.slug / "s1.jsonl.gz"
        self.assertEqual(stat.S_IMODE(gz.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(archive.index_path().stat().st_mode), 0o600)
        self.assertEqual(gzip.open(gz).read(), p.read_bytes())
        item = archive.items()[0]
        self.assertEqual((item["id"], item["cwd"], item["title"]), ("s1", str(self.app), "corrige le bug"))
        self.assertEqual(item["size"], p.stat().st_size)
        self.assertTrue(p.exists())   # l'original n'est jamais touché

    def test_recent_conversation_is_not_archived(self):
        self.journal("s1", age_days=0.2)
        self.assertEqual(archive.archive_pass(NOW).archived, [])
        self.assertEqual(archive.items(), [])

    def test_unchanged_is_skipped_and_modified_is_updated(self):
        p = self.journal("s1")
        archive.archive_pass(NOW)
        self.assertFalse(archive.archive_pass(NOW).changed)
        with open(p, "a") as f:
            f.write(json.dumps(reply("suite")) + "\n")
        old = NOW - 3 * DAY
        os.utime(p, (old, old))
        self.assertEqual(archive.archive_pass(NOW).updated, ["s1"])
        gz = archive.archive_dir() / self.slug / "s1.jsonl.gz"
        self.assertEqual(gzip.open(gz).read(), p.read_bytes())

    def test_sibling_directory_is_archived_and_change_detected(self):
        p = self.journal("s1")
        self.subagent(p)
        self.assertEqual(archive.archive_pass(NOW).archived, ["s1"])
        self.assertTrue((archive.archive_dir() / self.slug / "s1.dir.tar.gz").is_file())
        self.subagent(p, "agent-2")
        self.assertEqual(archive.archive_pass(NOW).updated, ["s1"])

    def test_limits_spread_over_several_passes_oldest_first(self):
        for i in range(5):
            self.journal(f"s{i}", age_days=10 - i)
        r1 = archive.archive_pass(NOW, max_files=2)
        self.assertEqual(r1.archived, ["s0", "s1"])
        self.assertEqual(r1.pending, 3)
        self.assertEqual(archive.archive_pass(NOW, max_files=2).archived, ["s2", "s3"])
        self.assertEqual(archive.archive_pass(NOW, max_files=2).archived, ["s4"])
        self.assertEqual(len(archive.items()), 5)

    def test_byte_limit(self):
        for i in range(3):
            self.journal(f"s{i}", age_days=10 - i)
        size = self.journal("s0", age_days=10).stat().st_size
        res = archive.archive_pass(NOW, max_bytes=size + 1)
        self.assertEqual(len(res.archived), 1)
        self.assertEqual(res.pending, 2)

    def test_single_oversized_file_still_goes_through(self):
        self.journal("big")
        self.assertEqual(archive.archive_pass(NOW, max_bytes=1).archived, ["big"])

    def test_file_changing_during_copy_is_retried(self):
        self.journal("s1")
        real = archive._gzip_copy

        def racing(src, dest):
            real(src, dest)
            with open(src, "a") as f:
                f.write("{}\n")
        with mock.patch.object(archive, "_gzip_copy", racing):
            res = archive.archive_pass(NOW)
        self.assertEqual((res.archived, res.pending), ([], 1))
        self.assertEqual(archive.items(), [])

    def test_unreadable_original_is_an_error_not_a_crash(self):
        self.journal("s1")
        with mock.patch.object(archive, "_gzip_copy", side_effect=OSError("disque plein")):
            res = archive.archive_pass(NOW)
        self.assertEqual(res.errors, [("s1", "disque plein")])
        self.assertEqual(archive.items(), [])

    def test_no_projects_dir(self):
        self.assertFalse(archive.archive_pass(NOW).changed)

    def test_corrupt_index_is_treated_as_empty(self):
        self.journal("s1")
        archive.archive_pass(NOW)
        archive.index_path().write_text("pas du json")
        self.assertEqual(archive.items(), [])
        self.assertEqual(archive.archive_pass(NOW).archived, ["s1"])


class TickAndPruneTest(ArchiveTestCase):
    def test_config_defaults_and_validation(self):
        self.assertEqual(archive.config(None), archive.DEFAULTS)
        cfg = archive.config({"archive": {"enabled": False, "idle_days": -3, "max_age_days": 30}})
        self.assertEqual(cfg, {"enabled": False, "idle_days": 1, "max_age_days": 30})

    def test_tick_respects_enabled(self):
        self.journal("s1")
        self.assertFalse(archive.tick(NOW, {"archive": {"enabled": False}}).changed)
        self.assertEqual(archive.items(), [])
        self.assertEqual(archive.tick(NOW, {}).archived, ["s1"])

    def test_tick_idle_days(self):
        self.journal("s1", age_days=5)
        self.assertEqual(archive.tick(NOW, {"archive": {"idle_days": 10}}).archived, [])

    def test_prune_by_age_and_zero_means_unlimited(self):
        self.journal("old", age_days=100)
        self.journal("new", age_days=5)
        archive.archive_pass(NOW)
        self.assertEqual(archive.prune(0, NOW), [])
        self.assertEqual(len(archive.items()), 2)
        self.assertEqual(archive.prune(30, NOW), ["old"])
        self.assertEqual([i["id"] for i in archive.items()], ["new"])
        self.assertFalse((archive.archive_dir() / self.slug / "old.jsonl.gz").exists())

    def test_tick_does_not_recopy_too_old(self):
        self.journal("old", age_days=100)
        res = archive.tick(NOW, {"archive": {"max_age_days": 30}})
        self.assertEqual((res.archived, res.pruned), ([], []))

    def test_size_and_stats(self):
        self.assertEqual(archive.stats(), (0, 0))
        self.journal("s1")
        archive.archive_pass(NOW)
        n, size = archive.stats()
        self.assertEqual(n, 1)
        self.assertGreater(size, 0)

    def test_remove(self):
        self.journal("s1")
        archive.archive_pass(NOW)
        self.assertEqual(archive.remove("s1"), 1)
        self.assertEqual(archive.remove("s1"), 0)
        self.assertEqual(archive.items(), [])


class RestoreTest(ArchiveTestCase):
    def test_restore_puts_files_back_with_fresh_mtime(self):
        p = self.journal("s1", "ajoute un test")
        sub = self.subagent(p)
        content, sub_content = p.read_bytes(), sub.read_bytes()
        archive.archive_pass(NOW)
        shutil.rmtree(p.with_suffix(""))
        p.unlink()
        before = time.time()
        self.assertEqual(archive.restore("s1"), p)
        self.assertEqual(p.read_bytes(), content)
        self.assertEqual(sub.read_bytes(), sub_content)
        self.assertGreaterEqual(p.stat().st_mtime, before - 1)
        self.assertGreaterEqual(sub.stat().st_mtime, before - 1)
        self.assertFalse(list(p.parent.glob("*.ccs-tmp")))
        # la copie archivée reste, et n'est pas recopiée telle quelle
        self.assertEqual(len(archive.items()), 1)
        self.assertFalse(archive.archive_pass(NOW + 5 * DAY).changed)

    def test_restore_never_overwrites_existing_journal(self):
        p = self.journal("s1")
        archive.archive_pass(NOW)
        p.write_text("modifié")
        archive.restore("s1")
        self.assertEqual(p.read_text(), "modifié")

    def test_restore_unknown(self):
        with self.assertRaises(FileNotFoundError):
            archive.restore("inconnu")

    def test_restore_missing_copy(self):
        p = self.journal("s1")
        archive.archive_pass(NOW)
        p.unlink()
        (archive.archive_dir() / self.slug / "s1.jsonl.gz").unlink()
        with self.assertRaises(FileNotFoundError):
            archive.restore("s1")

    def test_malicious_tar_is_refused(self):
        p = self.journal("s1")
        archive.archive_pass(NOW)
        item = archive.items()[0]
        with tarfile.open(archive._dir_file(item), "w:gz") as tar:
            info = tarfile.TarInfo("../evil")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        p.unlink()
        with self.assertRaises(ValueError):
            archive.restore("s1")
        self.assertFalse((p.parent.parent / "evil").exists())


class SearchTest(ArchiveTestCase):
    def test_search_words_without_accents(self):
        self.journal("s1", "Répare la facturation")
        self.journal("s2", "autre chose")
        archive.archive_pass(NOW)
        self.assertEqual([i["id"] for i in archive.search("REPARE facturation")], ["s1"])
        self.assertEqual(len(archive.search("")), 2)
        self.assertEqual(archive.search("introuvable"), [])
        self.assertEqual(archive.search("", project="/ailleurs"), [])


class HistoryIntegrationTest(ArchiveTestCase):
    def archived_conversation(self, sid="s1", text="migre la base"):
        """Conversation archivée puis effacée par Claude Code."""
        p = self.journal(sid, text)
        self.subagent(p)
        archive.archive_pass(NOW)
        shutil.rmtree(p.with_suffix(""))
        p.unlink()
        return p

    def test_scan_lists_archived_when_original_is_gone(self):
        self.journal("live", "vivante")
        self.archived_conversation()
        convs = {c.session_id: c for c in conversations.scan()}
        self.assertFalse(convs["live"].archived)
        c = convs["s1"]
        self.assertTrue(c.archived)
        self.assertEqual((c.title, c.cwd, c.git_branch, c.prompts), ("migre la base", str(self.app), "main", 1))
        self.assertTrue(c.folder_exists)
        self.assertNotIn("s1", {x.session_id for x in conversations.scan(archived=False)})

    def test_live_original_hides_archive_copy(self):
        self.journal("s1")
        archive.archive_pass(NOW)
        self.assertEqual([c.archived for c in conversations.scan()], [False])

    def test_search_finds_archived(self):
        self.archived_conversation()
        convs = conversations.scan()
        self.assertEqual(len(conversations.search(convs, "migre")), 1)
        self.assertEqual(len(conversations.search(convs, "archivée")), 1)
        self.assertEqual(len(conversations.search(convs, "autre")), 0)

    def test_ensure_available_restores_then_returns_path(self):
        p = self.archived_conversation()
        self.assertEqual(conversations.ensure_available("s1", str(self.app)), p)
        self.assertTrue(p.is_file())
        self.assertEqual(conversations.ensure_available("s1"), p)   # déjà en place
        self.assertFalse(conversations.scan()[0].archived)

    def test_ensure_available_unknown(self):
        with self.assertRaises(FileNotFoundError):
            conversations.ensure_available("rien")

    def test_ensure_conversation(self):
        self.archived_conversation()
        r = conversations.ensure_conversation(conversations.scan()[0])
        self.assertFalse(r.archived)
        self.assertTrue(Path(r.path).is_file())
        self.assertIs(conversations.ensure_conversation(r), r)

    def test_resume_terminal_restores_first(self):
        p = self.archived_conversation()
        c = conversations.scan()[0]
        with mock.patch.object(sessions, "open_terminal") as opened:
            conversations.resume_terminal(c)
        self.assertTrue(p.is_file())
        opened.assert_called_once()

    def test_relocate_archived_conversation(self):
        p = self.archived_conversation()
        new = self.home / "Work" / "Moved"
        new.mkdir()
        r = conversations.relocate(conversations.scan()[0], new)
        self.assertTrue(Path(r.path).is_file())
        self.assertFalse(r.archived)
        self.assertTrue(p.is_file())

    def test_from_journal_of_vanished_journal(self):
        p = self.archived_conversation()
        self.assertTrue(conversations.from_journal(p).archived)

    def test_preview_and_markdown_read_the_archive(self):
        self.archived_conversation(text="explique le schéma")
        c = conversations.scan()[0]
        msgs = preview.read_messages(c.path)
        self.assertEqual([m.role for m in msgs], [preview.USER, preview.ASSISTANT])
        self.assertIn("explique le schéma", preview.markdown_for(c))
        self.assertFalse(Path(c.path).exists())   # lecture sans restauration

    def test_preview_missing_everywhere(self):
        with self.assertRaises(FileNotFoundError):
            preview.read_messages(self.home / "nulle-part.jsonl")

    def test_cost_of_archived_includes_subagents(self):
        p = self.archived_conversation()
        c = conversations.scan()[0]
        cost = conversations.cost_for_path(c.path)
        self.assertEqual(cost.reponses, 2)   # réponse du journal + celle du sous-agent
        self.assertIs(conversations.cost_for_path(c.path), cost)   # mémorisé
        self.assertFalse(p.exists())

    def test_cost_of_live_journal(self):
        self.assertEqual(conversations.cost_for_path(self.journal("s1")).reponses, 1)
