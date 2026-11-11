"""Commandes de la phase 11 : tache, budget, fiche, sauvegarde, restaurer, telephone,
sessions (mémoire, contexte lourd), resume d'une conversation archivée."""

import io
import time
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

from ccs_app import cli, context_alert, phone, session_memory
from tests.helpers import HomeTestCase, write


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TaskCliTest(HomeTestCase):
    def test_empty_list_and_aliases(self):
        for name in ("tache", "taches", "tasks"):
            with self.subTest(name=name):
                code, out, _ = run(name)
                self.assertEqual(code, 0)
                self.assertIn("Aucune tâche", out)

    def test_add_with_options_reaches_the_task_module(self):
        code, out, err = run("tache", "ajouter", "relire le code", "-C", str(self.home),
                             "--droits", "lecture", "--quand", "nuit")
        self.assertEqual(code, 0, err)
        self.assertIn("ajoutée", out)
        code, out, _ = run("tache")
        self.assertIn("relire le code", out)

    def test_usage_error_has_exit_code_2(self):
        code, _, err = run("tache", "annuler")
        self.assertEqual(code, 2)
        self.assertIn("usage", err)


class BudgetCliTest(HomeTestCase):
    def test_budget_is_delegated_with_the_settings(self):
        with mock.patch("ccs_app.budget.command", return_value=0) as cmd:
            self.assertEqual(run("budget", "/x", "aucun")[0], 0)
        self.assertEqual(cmd.call_args.args[0], ["/x", "aucun"])
        self.assertIn("budget", cmd.call_args.kwargs["settings"])

    def test_set_and_show(self):
        self.assertEqual(run("budget", str(self.home), "25")[0], 0)
        self.assertEqual(run("budget")[0], 0)

    def test_usage_error(self):
        self.assertEqual(run("budget", "a", "b", "c")[0], 2)


class FicheBackupCliTest(HomeTestCase):
    def test_fiche_needs_an_identifier(self):
        code, _, err = run("fiche")
        self.assertEqual(code, 2)
        self.assertIn("usage : ccs fiche", err)

    def test_fiche_unknown_conversation(self):
        code, _, err = run("fiche", "zzzz")
        self.assertEqual(code, 1)
        self.assertIn("Erreur", err)

    def test_backup_commands_are_delegated(self):
        with mock.patch("ccs_app.backup.command", return_value=0) as cmd:
            self.assertEqual(run("sauvegarde", "/tmp/x.gpg")[0], 0)
            self.assertEqual(run("backup")[0], 0)
            self.assertEqual(run("restaurer", "/tmp/x.gpg", "--oui")[0], 0)
            self.assertEqual(run("restore", "/tmp/x.gpg")[0], 0)
        self.assertEqual([c.args[0] for c in cmd.call_args_list],
                         [["sauvegarde", "/tmp/x.gpg"], ["sauvegarde"],
                          ["restaurer", "/tmp/x.gpg", "--oui"], ["restaurer", "/tmp/x.gpg"]])

    def test_restore_without_a_file_is_a_usage_error(self):
        self.assertEqual(run("restaurer")[0], 2)

    def test_exit_code_is_forwarded(self):
        with mock.patch("ccs_app.backup.command", return_value=1):
            self.assertEqual(run("restaurer", "f")[0], 1)


class PhoneCliTest(HomeTestCase):
    def test_state_without_channel(self):
        for name in ("telephone", "phone"):
            code, out, _ = run(name)
            self.assertEqual(code, 0)
            self.assertIn("désactivées", out)
            self.assertIn("Canal   : aucun", out)

    def test_state_with_a_channel_shows_the_link(self):
        topic = phone.new_topic()
        write(self.store / "settings.json", {"phone": {"enabled": True, "topic": topic}})
        code, out, _ = run("telephone")
        self.assertEqual(code, 0)
        self.assertIn("activées", out)
        self.assertIn(f"https://ntfy.sh/{topic}", out)

    def test_test_message(self):
        with mock.patch.object(phone, "send_test", return_value=(True, "Message envoyé")) as st:
            code, out, _ = run("telephone", "essai")
        self.assertEqual((code, out.strip()), (0, "Message envoyé"))
        st.assert_called_once()

    def test_failed_test_message(self):
        with mock.patch.object(phone, "send_test", return_value=(False, "Envoi impossible (réseau).")):
            code, _, err = run("telephone", "essai")
        self.assertEqual(code, 1)
        self.assertIn("impossible", err)

    def test_unknown_argument(self):
        self.assertEqual(run("telephone", "zzz")[0], 2)


class SessionsMemoryCliTest(HomeTestCase):
    def session(self, state="waiting"):
        from ccs_app import sessions
        return sessions.Session(42, "sid", "gigit-cb", "/w/GiGit", "GiGit", state, "",
                                time.time() - 9000, time.time() - 30, "interactive", "cli")

    def test_ram_total_banner_and_heavy_context(self):
        from ccs_app import sessions
        usage = sessions.ConversationUsage(1_000_000, "opus", 10)
        snap = {42: session_memory.SessionMemory(42, int(1.5 * 1024 ** 3), 7500, True)}
        ctx = context_alert.Context(200_000, "claude-opus-4-5")
        with mock.patch.object(sessions, "list_sessions", return_value=[self.session()]), \
                mock.patch.object(sessions, "conversation_usage", return_value=usage), \
                mock.patch.object(session_memory, "snapshot", return_value=snap), \
                mock.patch.object(context_alert, "contexts_for", return_value={42: ctx}):
            code, out, _ = run("sessions")
        self.assertEqual(code, 0)
        self.assertIn("1,5 Go", out)
        self.assertIn("inactive depuis", out)
        self.assertIn("contexte lourd", out)
        self.assertIn("Mémoire des sessions : 1,5 Go au total.", out)
        self.assertIn("1 session inactive occupe 1,5 Go", out)

    def test_memory_errors_do_not_hide_the_sessions(self):
        from ccs_app import sessions
        usage = sessions.ConversationUsage(1000, "opus", 1)
        with mock.patch.object(sessions, "list_sessions", return_value=[self.session("busy")]), \
                mock.patch.object(sessions, "conversation_usage", return_value=usage), \
                mock.patch.object(session_memory, "snapshot", side_effect=OSError("proc")), \
                mock.patch.object(context_alert, "contexts_for", side_effect=OSError("x")):
            code, out, _ = run("sessions")
        self.assertEqual(code, 0)
        self.assertIn("(pid 42", out)
        self.assertNotIn("Mémoire des sessions", out)


class ResumeArchivedCliTest(HomeTestCase):
    def conv(self, archived):
        return SimpleNamespace(archived=archived, folder_exists=True, cwd=str(self.home), session_id="sid-1",
                               path="/archive/x.jsonl" if archived else "/p/x.jsonl", title="T", prompts=1,
                               project="P", origin_label="terminal", updated_at=time.time())

    def patched(self, found, **extra):
        from ccs_app import conversations as conv
        return (mock.patch.object(conv, "scan", return_value=[found]),
                mock.patch.object(conv, "find", return_value=found),
                mock.patch.object(conv, "open_ids", return_value=set()),
                mock.patch.object(conv, "ensure_conversation", **extra))

    def test_archived_conversation_is_restored_before_resuming(self):
        archived, restored = self.conv(True), self.conv(False)
        a, b, c, d = self.patched(archived, return_value=restored)
        with a, b, c, d as ensure:
            code, out, err = run("resume", "sid-", "--print")
        self.assertEqual(code, 0)
        ensure.assert_called_once_with(archived)
        self.assertIn("--resume sid-1", out)
        self.assertIn("restaurée", err)

    def test_live_conversation_is_not_restored(self):
        a, b, c, d = self.patched(self.conv(False))
        with a, b, c, d as ensure:
            self.assertEqual(run("resume", "sid-", "--print")[0], 0)
        ensure.assert_not_called()

    def test_restore_failure_is_reported(self):
        a, b, c, d = self.patched(self.conv(True), side_effect=FileNotFoundError("absente"))
        with a, b, c, d:
            code, _, err = run("resume", "sid-", "--print")
        self.assertEqual(code, 1)
        self.assertIn("restauration", err)

    def test_cost_is_read_through_the_archive_aware_function(self):
        from ccs_app import conversations as conv, costs
        with mock.patch.object(conv, "cost_for_path", return_value=costs.Cost.empty()) as cp:
            cli._cost_text(SimpleNamespace(path="/archive/x.jsonl"))
        cp.assert_called_once_with("/archive/x.jsonl")

    def test_lists_mark_archived_conversations(self):
        from ccs_app import conversations as conv
        c = self.conv(True)
        with mock.patch.object(conv, "scan", return_value=[c]), \
                mock.patch.object(conv, "search", return_value=[c]), \
                mock.patch.object(conv, "open_ids", return_value=set()), \
                mock.patch.object(conv, "suggest_folders", return_value={}), \
                mock.patch.object(conv, "group_by_day", return_value=[("Aujourd'hui", [c])]), \
                mock.patch.object(conv, "ago", return_value="à l'instant"):
            code, out, _ = run("conversations")
        self.assertEqual(code, 0)
        self.assertIn("archivée", out)
