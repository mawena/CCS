"""Fiche « où j'en étais » : lecture du journal (normal ou archivé), texte, commande."""

import io
import json
import os
import time
from unittest import mock

from ccs_app import archive, conversations, fiche, sessions
from ccs_app.store import Store
from tests.helpers import HomeTestCase

CWD = "/home/u/Work/App"
DAY = 86400


def ts(minute):
    return f"2026-11-04T10:{minute:02d}:00.000Z"


def user(text, minute, **extra):
    return {"type": "user", "cwd": CWD, "timestamp": ts(minute), "gitBranch": "feature/x", "uuid": f"u{minute}",
            "origin": {"kind": "human"}, "message": {"role": "user", "content": text}, **extra}


def tool_result(minute, content="résultat secret"):
    return {"type": "user", "cwd": CWD, "timestamp": ts(minute), "uuid": f"r{minute}",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": content}]}}


def assistant(blocks, minute):
    return {"type": "assistant", "cwd": CWD, "timestamp": ts(minute), "uuid": f"a{minute}",
            "message": {"id": f"m{minute}", "role": "assistant", "model": "claude-opus-5-5", "content": blocks}}


def text(t):
    return {"type": "text", "text": t}


def tool(name, **inp):
    return {"type": "tool_use", "id": "t", "name": name, "input": inp}


ROWS = [
    user("première demande", 0),
    assistant([text("d'accord"), tool("Write", file_path=f"{CWD}/a.py", content="x")], 1),
    tool_result(2),
    assistant([tool("Edit", file_path=f"{CWD}/b.py", old_string="a", new_string="b"),
               tool("Read", file_path=f"{CWD}/lu.py"),
               tool("TodoWrite", todos=[{"content": "vieille tâche", "status": "pending"}])], 3),
    user("ajoute la validation des champs", 4),
    assistant([tool("Edit", file_path=f"{CWD}/a.py", old_string="x", new_string="y"),
               tool("MultiEdit", file_path=f"{CWD}/c.py", edits=[]),
               tool("NotebookEdit", notebook_path=f"{CWD}/n.ipynb"),
               tool("TodoWrite", todos=[{"content": "écrire le test", "status": "completed"},
                                        {"content": "brancher la vue", "status": "in_progress"},
                                        {"content": "documenter", "status": "pending"}])], 5),
    tool_result(6),
    user("<system-reminder>ne pas afficher</system-reminder>", 7, isMeta=True),
    user("[Request interrupted by user]", 8),
    assistant([text("Les champs sont validés.\nIl reste la vue à brancher.")], 9),
]


class FicheTestCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.home / ".local" / "share")})
        patch.start()
        self.addCleanup(patch.stop)
        self.app = self.home / "Work" / "App"
        self.app.mkdir(parents=True)

    def journal(self, sid="s1", rows=ROWS, age_days=3):
        p = self.home / ".claude" / "projects" / sessions.project_slug(str(self.app)) / f"{sid}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in rows) + '{"type":"user","message":{"cont')
        when = time.time() - age_days * DAY
        os.utime(p, (when, when))
        return p

    def build(self, p, **kw):
        return fiche.build(conversations.from_journal(p), **kw)


class BuildTest(FicheTestCase):
    def test_content(self):
        f = self.build(self.journal(), with_account=False)
        self.assertEqual(f.last_request, "ajoute la validation des champs")
        self.assertEqual(f.last_reply, "Les champs sont validés. Il reste la vue à brancher.")
        # modifiés seulement (pas Read), le plus récemment touché en dernier, sans doublon
        self.assertEqual(f.files, [f"{CWD}/b.py", f"{CWD}/a.py", f"{CWD}/c.py", f"{CWD}/n.ipynb"])
        self.assertEqual(f.todos, [("completed", "écrire le test"), ("in_progress", "brancher la vue"),
                                   ("pending", "documenter")])
        self.assertEqual(f.branch, "feature/x")
        self.assertEqual(f.cwd, CWD)
        self.assertEqual(f.project, "App")
        self.assertEqual(f.when, fiche.preview._ts(ts(9)))
        self.assertFalse(f.archived)

    def test_tool_results_are_never_the_request(self):
        f = self.build(self.journal(rows=[user("seule demande", 0), tool_result(1, "SORTIE D'OUTIL"),
                                          assistant([text("ok")], 2)]), with_account=False)
        self.assertEqual(f.last_request, "seule demande")

    def test_conversation_with_only_a_request(self):
        f = self.build(self.journal(rows=[user("bonjour", 0)]), with_account=False)
        self.assertEqual((f.last_reply, f.files, f.todos), ("", [], []))

    def test_sidechain_and_synthetic_ignored(self):
        rows = [user("vraie demande", 0),
                {**user("demande de sous-agent", 1), "isSidechain": True},
                assistant([text("réponse réelle")], 2),
                {**assistant([], 3), "message": {"id": "z", "role": "assistant", "model": "<synthetic>",
                                                 "content": [text("No response requested.")]}}]
        f = self.build(self.journal(rows=rows), with_account=False)
        self.assertEqual((f.last_request, f.last_reply), ("vraie demande", "réponse réelle"))

    def test_long_texts_are_cut(self):
        f = self.build(self.journal(rows=[user("m" * 5000, 0), assistant([text("r" * 5000)], 1)]),
                       with_account=False)
        self.assertLessEqual(len(f.last_request), fiche.REQUEST_MAX)
        self.assertLessEqual(len(f.last_reply), fiche.REPLY_MAX)
        self.assertTrue(f.last_reply.endswith("…"))

    def test_account_from_switch_journal(self):
        p = self.journal()
        store = Store(self.store / "history.db")
        when = fiche.preview._ts(ts(9))
        store.add_event(when - 3600, "switch", "pro", {"mode": "manual"})
        store.add_event(when + 3600, "switch", "perso", {"mode": "manual"})
        self.assertEqual(self.build(p, store=store).account, "pro")

    def test_account_unknown_without_events(self):
        p = self.journal()
        self.assertIsNone(self.build(p, store=Store(self.store / "history.db")).account)

    def test_account_failure_is_silent(self):
        broken = mock.Mock()
        broken.active_periods.side_effect = RuntimeError("base cassée")
        self.assertIsNone(fiche.account_at(1000.0, broken))

    def test_archived_conversation(self):
        p = self.journal(age_days=5)
        archive.archive_pass(time.time())
        p.unlink()
        c = conversations.scan()[0]
        self.assertTrue(c.archived)
        f = fiche.build(c, with_account=False)
        self.assertTrue(f.archived)
        self.assertEqual(f.last_request, "ajoute la validation des champs")
        self.assertFalse(p.exists())


class TextTest(FicheTestCase):
    def test_format_text(self):
        f = self.build(self.journal(), with_account=False)
        f.account = "pro"
        out = fiche.format_text(f)
        for part in ("ajoute la validation des champs", "Les champs sont validés.", "feature/x",
                     "Compte actif alors : pro", "Fichiers modifiés (4)", "  b.py", "  n.ipynb",
                     "Liste de tâches (1/3)", "[x] écrire le test", "[~] brancher la vue", "[ ] documenter"):
            self.assertIn(part, out)
        self.assertNotIn("résultat secret", out)

    def test_format_text_minimal(self):
        out = fiche.format_text(fiche.Fiche(session_id="abcd"))
        self.assertIn("abcd", out)
        self.assertIn("(aucune)", out)
        self.assertNotIn("Fichiers modifiés", out)

    def test_many_files_are_summarised(self):
        out = fiche.format_text(fiche.Fiche(cwd=CWD, files=[f"{CWD}/f{i}.py" for i in range(20)]))
        self.assertIn("Fichiers modifiés (20)", out)
        self.assertIn("8 de plus avant", out)
        self.assertIn("f19.py", out)


class CommandTest(FicheTestCase):
    def run_command(self, args):
        out, err = io.StringIO(), io.StringIO()
        code = fiche.command(args, out=out, err=err, store=Store(self.store / "history.db"))
        return code, out.getvalue(), err.getvalue()

    def test_ok(self):
        self.journal("abcd1234")
        code, out, err = self.run_command(["abcd"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("ajoute la validation des champs", out)

    def test_archived_ok(self):
        p = self.journal("abcd1234", age_days=5)
        archive.archive_pass(time.time())
        p.unlink()
        code, out, _ = self.run_command(["abcd1234"])
        self.assertEqual(code, 0)
        self.assertIn("archivée", out)

    def test_unknown_and_usage(self):
        code, _out, err = self.run_command(["zzzzzz"])
        self.assertEqual(code, 1)
        self.assertIn("aucune conversation", err)
        self.assertEqual(self.run_command(["ab"])[0], 1)
        for bad in ([], ["a", "b"], ["--x"]):
            code, _out, err = self.run_command(bad)
            self.assertEqual(code, 2)
            self.assertIn("usage", err)
