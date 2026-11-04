import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from ccs_app import conversations as conv
from ccs_app import sessions
from tests.helpers import HomeTestCase

NOW = time.time()
TS = "2026-11-04T10:00:00.000Z"


def line(d):
    return json.dumps(d, separators=(",", ":"))  # format de Claude Code


def prompt(text, cwd, entrypoint="cli", branch="main", **extra):
    return {"type": "user", "message": {"role": "user", "content": text}, "cwd": cwd,
            "entrypoint": entrypoint, "gitBranch": branch, "timestamp": TS, "sessionId": "x", **extra}


class ConversationsTestCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.home / "Work" / "App"
        self.app.mkdir(parents=True)

    def journal(self, cwd, sid, rows, mtime=None, raw_tail=""):
        p = self.home / ".claude" / "projects" / sessions.project_slug(str(cwd)) / f"{sid}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(line(r) + "\n" for r in rows) + raw_tail)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def append(self, path, rows, raw_tail=""):
        with open(path, "a") as f:
            f.write("".join(line(r) + "\n" for r in rows) + raw_tail)


class ScanTest(ConversationsTestCase):
    def test_title_priority_and_fields(self):
        cwd = str(self.app)
        vscode_prompt = {"type": "user", "cwd": cwd, "entrypoint": "claude-vscode", "gitBranch": "dev",
                         "timestamp": TS, "message": {"role": "user", "content": [
                             {"type": "text", "text": "<ide_opened_file>a.py</ide_opened_file>"},
                             {"type": "text", "text": "corrige le calcul\ndes intérêts"}]}}
        self.journal(cwd, "s-vscode", [
            {"type": "attachment", "cwd": cwd, "entrypoint": "claude-vscode", "timestamp": TS},
            vscode_prompt,
            {"type": "user", "isMeta": True, "message": {"content": "Base directory for this skill"}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "ai-title", "aiTitle": "Premier titre"},
            prompt("ajoute un test", cwd, branch="feature/x"),
            {"type": "ai-title", "aiTitle": "Calcul des intérêts"},
        ])
        self.journal(cwd, "s-custom", [prompt("bonjour", cwd), {"type": "ai-title", "aiTitle": "Auto"},
                                       {"type": "custom-title", "customTitle": "Mon titre"}])
        self.journal(cwd, "s-prompt", [prompt("<command-name>/clear</command-name>", cwd),
                                       prompt("explique   le\nmodule", cwd)])
        found = {c.session_id: c for c in conv.scan()}
        c = found["s-vscode"]
        self.assertEqual(c.title, "Calcul des intérêts")
        self.assertEqual((c.prompts, c.first_prompt, c.last_prompt),
                         (2, "corrige le calcul des intérêts", "ajoute un test"))
        self.assertEqual((c.origin, c.origin_label, c.git_branch, c.project), ("vscode", "VS Code",
                                                                              "feature/x", "App"))
        self.assertTrue(c.folder_exists)
        self.assertIsNotNone(c.started_at)
        self.assertEqual(found["s-custom"].title, "Mon titre")
        self.assertEqual(found["s-custom"].origin, "terminal")
        self.assertEqual(found["s-prompt"].title, "explique le module")

    def test_prompt_mentioning_title_type_is_counted(self):
        self.journal(self.app, "s1", [prompt('cherche "ai-title" et "custom-title" dans les logs', str(self.app))])
        [c] = conv.scan()
        self.assertEqual(c.prompts, 1)
        self.assertIn("ai-title", c.title)

    def test_spaced_json_is_read(self):
        p = self.home / ".claude" / "projects" / sessions.project_slug(str(self.app)) / "s1.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(prompt("bonjour", str(self.app))) + "\n")
        self.assertEqual([c.title for c in conv.scan()], ["bonjour"])

    def test_skips_empty_conversations_subagents_and_garbage(self):
        cwd = str(self.app)
        self.journal(cwd, "vide", [{"type": "attachment", "cwd": cwd}])
        self.journal(cwd, "ok", [prompt("bonjour", cwd)], raw_tail="{pas du json\n")
        sub = self.home / ".claude" / "projects" / sessions.project_slug(cwd) / "ok" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-1.jsonl").write_text(line(prompt("tâche de sous-agent", cwd)) + "\n")
        self.assertEqual([c.session_id for c in conv.scan()], ["ok"])

    def test_sorted_newest_first(self):
        self.journal(self.app, "vieux", [prompt("a", str(self.app))], mtime=NOW - 7200)
        self.journal(self.app, "neuf", [prompt("b", str(self.app))], mtime=NOW - 60)
        self.assertEqual([c.session_id for c in conv.scan()], ["neuf", "vieux"])

    def test_missing_projects_dir(self):
        self.assertEqual(conv.scan(), [])


class IncrementalTest(ConversationsTestCase):
    def test_reads_only_appended_lines_and_waits_for_partial_line(self):
        cwd = str(self.app)
        p = self.journal(cwd, "s1", [prompt("un", cwd)], raw_tail=line(prompt("deux", cwd)))
        [c] = conv.scan()
        self.assertEqual(c.prompts, 1)  # la ligne sans fin de ligne n'est pas encore lue
        offset = conv._load_cache()[str(p)]["offset"]
        self.assertEqual(offset, len(line(prompt("un", cwd))) + 1)
        self.append(p, [], raw_tail="\n" + line({"type": "ai-title", "aiTitle": "Titre"}) + "\n")
        os.utime(p, (NOW + 5, NOW + 5))
        seen = []
        real = conv._apply
        with mock.patch.object(conv, "_apply", side_effect=lambda e, raw: (seen.append(raw), real(e, raw))):
            [c] = conv.scan()
        self.assertEqual((c.prompts, c.title, c.last_prompt), (2, "Titre", "deux"))
        self.assertEqual(len(seen), 2)  # seulement les deux lignes nouvelles

    def test_cache_hit_does_not_reread(self):
        self.journal(self.app, "s1", [prompt("un", str(self.app))])
        conv.scan()
        with mock.patch.object(conv, "read_entry", side_effect=AssertionError("relu")):
            self.assertEqual(len(conv.scan()), 1)

    def test_rewritten_shorter_file_is_reparsed(self):
        cwd = str(self.app)
        p = self.journal(cwd, "s1", [prompt("un", cwd), prompt("deux", cwd), prompt("trois", cwd)])
        conv.scan()
        self.journal(cwd, "s1", [prompt("autre", cwd)])
        os.utime(p, (NOW + 5, NOW + 5))
        [c] = conv.scan()
        self.assertEqual((c.prompts, c.title), (1, "autre"))

    def test_corrupt_cache_is_ignored(self):
        self.journal(self.app, "s1", [prompt("un", str(self.app))])
        conv.cache_path().parent.mkdir(parents=True, exist_ok=True)
        conv.cache_path().write_text("{cassé")
        self.assertEqual(len(conv.scan()), 1)


def make(sid, title="t", cwd="/x/App", origin="terminal", updated=NOW, exists=True, **kw):
    return conv.Conversation(session_id=sid, path=f"/p/{sid}.jsonl", cwd=cwd, title=title,
                             first_prompt=kw.get("first", ""), last_prompt=kw.get("last", ""),
                             prompts=1, started_at=None, updated_at=updated, origin=origin,
                             git_branch=kw.get("branch", ""), size=1, folder_exists=exists)


class SearchTest(ConversationsTestCase):
    def test_words_accents_case_and_filters(self):
        convs = [make("a", "Calcul des intérêts", first="corrige le prêt", origin="vscode"),
                 make("b", "Export CSV", cwd="/x/Report", branch="feature/csv"),
                 make("c", "Interets composés", cwd="/x/Report")]
        self.assertEqual([c.session_id for c in conv.search(convs, "INTERETS")], ["a", "c"])
        self.assertEqual([c.session_id for c in conv.search(convs, "interets pret")], ["a"])
        self.assertEqual([c.session_id for c in conv.search(convs, "csv")], ["b"])
        self.assertEqual([c.session_id for c in conv.search(convs, "", project="/x/Report")], ["b", "c"])
        self.assertEqual([c.session_id for c in conv.search(convs, "", origin="vscode")], ["a"])
        self.assertEqual(len(conv.search(convs, "  ")), 3)
        self.assertEqual(conv.projects(convs), [("/x/App", 1), ("/x/Report", 2)])

    def test_group_by_day(self):
        now = datetime(2026, 11, 4, 15, 0).timestamp()
        at = lambda **d: (datetime(2026, 11, 4, 15, 0) - timedelta(**d)).timestamp()  # noqa: E731
        convs = [make("a", updated=at(hours=1)), make("b", updated=at(hours=20)),
                 make("c", updated=at(days=3)), make("d", updated=at(days=12)), make("e", updated=at(days=90))]
        groups = conv.group_by_day(convs, now)
        self.assertEqual([(g, [c.session_id for c in cs]) for g, cs in groups],
                         [("Aujourd'hui", ["a"]), ("Hier", ["b"]), ("7 derniers jours", ["c"]),
                          ("30 derniers jours", ["d"]), ("Plus ancien", ["e"])])

    def test_find(self):
        convs = [make("4f3a2b1c-aaaa"), make("4f3a9999-bbbb"), make("77aa0000-cccc")]
        self.assertEqual(conv.find(convs, "77aa").session_id, "77aa0000-cccc")
        self.assertEqual(conv.find(convs, "4f3a2b1c-aaaa").session_id, "4f3a2b1c-aaaa")
        for ref, msg in (("4f3", "4 caractères"), ("4f3a", "2 conversations"), ("zzzz", "aucune")):
            with self.assertRaisesRegex(LookupError, msg):
                conv.find(convs, ref)

    def test_ago(self):
        self.assertEqual(conv.ago(NOW - 30, NOW), "à l'instant")
        self.assertEqual(conv.ago(NOW - 300, NOW), "il y a 5 min")
        self.assertEqual(conv.ago(NOW - 3 * 3600, NOW), "il y a 3 h")
        self.assertEqual(conv.ago(NOW - 86400 * 1.5, NOW), "hier")
        self.assertEqual(conv.ago(NOW - 86400 * 4, NOW), "il y a 4 j")


class ResumeTest(ConversationsTestCase):
    def test_problems(self):
        c = make("s1", cwd=str(self.app))
        self.assertIsNone(conv.resume_problem(c, set()))
        self.assertIn("déjà ouverte", conv.resume_problem(c, {"s1"}))
        self.assertIn("introuvable", conv.resume_problem(make("s2", cwd="/nulle/part", exists=False)))

    def test_command_and_url(self):
        c = make("abc-123", cwd="/home/u/Mon Projet")
        self.assertEqual(conv.resume_command(c), "cd '/home/u/Mon Projet' && claude --resume abc-123")
        self.assertEqual(conv.vscode_url(c), "vscode://anthropic.claude-code/open?session=abc-123")

    def test_terminal_uses_existing_launcher(self):
        with mock.patch.object(sessions, "open_terminal") as term:
            conv.resume_terminal(make("s1", cwd="/x"))
        term.assert_called_once_with("/x", resume="s1")

    def test_vscode_opens_folder_then_url(self):
        c = make("s1", cwd="/x/App")
        with mock.patch.object(conv.shutil, "which", return_value="/usr/bin/code"), \
                mock.patch.object(conv.subprocess, "run") as run, mock.patch.object(conv.time, "sleep"):
            conv.resume_vscode(c, wait=True)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [["/usr/bin/code", "/x/App"],
                          ["/usr/bin/code", "--open-url", "vscode://anthropic.claude-code/open?session=s1"]])

    def test_vscode_missing(self):
        with mock.patch.object(conv.shutil, "which", return_value=None):
            with self.assertRaises(FileNotFoundError):
                conv.resume_vscode(make("s1"), wait=True)
            self.assertEqual(conv.preferred_target(make("s1", origin="vscode")), "terminal")
        with mock.patch.object(conv.shutil, "which", return_value="/usr/bin/code"):
            self.assertEqual(conv.preferred_target(make("s1", origin="vscode")), "vscode")
            self.assertEqual(conv.preferred_target(make("s1", origin="terminal")), "terminal")

    def test_open_ids(self):
        s = sessions.Session(1, "s1", "n", "/x", "x", "busy", None, NOW, NOW, "interactive", "cli")
        with mock.patch.object(sessions, "list_sessions", return_value=[s]):
            self.assertEqual(conv.open_ids(), {"s1"})


class RelocateTest(ConversationsTestCase):
    def test_moved_project_suggested_relocated_and_deduplicated(self):
        old = str(self.home / "Work" / "Ancien" / "App")  # n'existe plus
        new = str(self.app)
        orig = self.journal(old, "s-old", [prompt("vieille tâche", old)], mtime=NOW - 3600)
        self.journal(new, "s-new", [prompt("tâche récente", new)], mtime=NOW - 60)
        convs = conv.scan()
        moved = next(c for c in convs if c.session_id == "s-old")
        self.assertFalse(moved.folder_exists)
        self.assertEqual(conv.suggest_folder(moved, convs), new)

        relocated = conv.relocate(moved, new)
        self.assertEqual((relocated.cwd, relocated.folder_exists), (new, True))
        copy = Path(relocated.path)
        self.assertEqual(copy.parent.name, sessions.project_slug(new))
        self.assertTrue(orig.exists() and copy.exists())
        self.assertEqual(copy.read_bytes(), orig.read_bytes())

        convs = conv.scan()
        self.assertEqual(sorted(c.session_id for c in convs), ["s-new", "s-old"])
        again = next(c for c in convs if c.session_id == "s-old")
        self.assertEqual((again.cwd, again.folder_exists, again.path), (new, True, str(copy)))

        copy.write_text("déjà repris\n")  # une copie existante n'est jamais écrasée
        conv.relocate(moved, new)
        self.assertEqual(copy.read_text(), "déjà repris\n")

    def test_no_suggestion_when_ambiguous_or_present(self):
        a = make("a", cwd="/old/App", exists=False)
        convs = [a, make("b", cwd="/w1/App"), make("c", cwd="/w2/App")]
        self.assertIsNone(conv.suggest_folder(a, convs))
        self.assertIsNone(conv.suggest_folder(make("d", cwd="/w1/App"), convs))

    def test_relocate_to_missing_folder(self):
        with self.assertRaises(FileNotFoundError):
            conv.relocate(make("s1"), str(self.home / "absent"))


class SuggestOnDiskTest(ConversationsTestCase):
    def test_found_in_home_when_history_does_not_know_it(self):
        (self.home / "Work" / "perso" / "Proj").mkdir(parents=True)
        (self.home / "Work" / "perso" / "node_modules" / "Lib").mkdir(parents=True)
        (self.home / ".cache" / "Lib").mkdir(parents=True)
        lost = make("a", cwd=str(self.home / "Work" / "Old" / "Proj"), exists=False)
        lib = make("b", cwd=str(self.home / "Work" / "Old" / "Lib"), exists=False)
        self.assertEqual(conv.suggest_folders([lost, lib]), {"a": str(self.home / "Work" / "perso" / "Proj")})

    def test_ambiguous_on_disk(self):
        for parent in ("perso", "pro"):
            (self.home / "Work" / parent / "Proj").mkdir(parents=True)
        lost = make("a", cwd=str(self.home / "Work" / "Old" / "Proj"), exists=False)
        self.assertIsNone(conv.suggest_folder(lost, [lost]))


class CliTest(ConversationsTestCase):
    def run_cli(self, *argv):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from ccs_app import cli
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch.object(sessions, "list_sessions", return_value=[]):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        super().setUp()
        cwd = str(self.app)
        self.journal(cwd, "aaaa1111-x", [prompt("export CSV des prêts", cwd)], mtime=NOW - 60)
        self.journal(cwd, "bbbb2222-y", [prompt("corrige le menu", cwd, entrypoint="claude-vscode")],
                     mtime=NOW - 120)
        old = str(self.home / "Work" / "Old" / "Ailleurs")
        self.journal(old, "cccc3333-z", [prompt("vieux projet", old)], mtime=NOW - 9 * 86400)

    def test_list_search_filters_and_json(self):
        code, out, _ = self.run_cli("conversations")
        self.assertEqual(code, 0)
        self.assertIn("Aujourd'hui", out)
        self.assertIn("aaaa1111  ", out)
        self.assertIn("dossier introuvable", out)
        self.assertIn("3 conversation(s)", out)
        _, out, _ = self.run_cli("conversations", "PRETS")
        self.assertIn("export CSV", out)
        self.assertNotIn("corrige le menu", out)
        _, out, _ = self.run_cli("conversations", "--vscode", "--json")
        self.assertEqual([c["session_id"] for c in json.loads(out)], ["bbbb2222-y"])
        self.assertEqual(json.loads(out)[0]["project"], "App")
        code, _, err = self.run_cli("conversations", "-p", "Inconnu")
        self.assertEqual(code, 1)
        self.assertIn("Aucun projet", err)

    def test_resume_print_dir_and_errors(self):
        code, out, _ = self.run_cli("resume", "aaaa", "--print")
        self.assertEqual((code, out.strip()), (0, f"cd {self.app} && claude --resume aaaa1111-x"))
        code, _, err = self.run_cli("resume", "zzzz", "--print")
        self.assertEqual(code, 1)
        self.assertIn("aucune conversation", err)
        code, _, err = self.run_cli("resume", "cccc", "--print")
        self.assertEqual(code, 1)
        self.assertIn("--dir", err)
        code, out, _ = self.run_cli("resume", "cccc", "--print", "--dir", str(self.app))
        self.assertEqual((code, out.strip()), (0, f"cd {self.app} && claude --resume cccc3333-z"))
        code, out, _ = self.run_cli("conversations", "vieux")
        self.assertNotIn("introuvable", out)  # la copie dans App est désormais l'exemplaire montré

    def test_resume_refuses_open_conversation(self):
        from ccs_app import cli
        with mock.patch.object(conv, "open_ids", return_value={"aaaa1111-x"}):
            import io
            from contextlib import redirect_stderr
            err = io.StringIO()
            with redirect_stderr(err):
                code = cli.main(["resume", "aaaa", "--print"])
        self.assertEqual(code, 1)
        self.assertIn("déjà ouverte", err.getvalue())

    def test_resume_here_execs_claude_in_folder(self):
        with mock.patch("os.chdir") as chdir, mock.patch("os.execvp") as execvp, \
                mock.patch.object(sessions, "_claude_bin", return_value="/bin/claude"):
            self.run_cli("resume", "aaaa")
        chdir.assert_called_once_with(str(self.app))
        execvp.assert_called_once_with("/bin/claude", ["/bin/claude", "--resume", "aaaa1111-x"])

    def test_old_print_option_still_works(self):
        from ccs_app import cli
        with mock.patch.object(cli, "cmd_print", return_value=0) as cmd:
            cli.main(["--print"])
        cmd.assert_called_once()
