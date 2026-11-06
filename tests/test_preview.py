import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ccs_app import preview
from ccs_app.conversations import Conversation
from ccs_app.preview import ASSISTANT, NOTE, TOOL, USER, read_messages, to_markdown

CWD = "/home/u/Work/App"


def ts(minute):
    return f"2026-11-04T10:{minute:02d}:00.000Z"


def user(text, minute=0, **extra):
    return {"parentUuid": None, "type": "user", "cwd": CWD, "timestamp": ts(minute), "isSidechain": False,
            "origin": {"kind": "human"}, "uuid": f"u{minute}-{hash(str(text)) & 0xffff}",
            "message": {"role": "user", "content": text}, **extra}


def assistant(msg_id, blocks, minute=1, model="claude-opus-5-5", **extra):
    return {"parentUuid": "p", "type": "assistant", "cwd": CWD, "timestamp": ts(minute), "isSidechain": False,
            "uuid": f"a-{msg_id}-{len(json.dumps(blocks))}-{minute}",
            "message": {"id": msg_id, "role": "assistant", "model": model, "content": blocks,
                        "usage": {"input_tokens": 1, "output_tokens": 1}}, **extra}


def text(t):
    return {"type": "text", "text": t}


def tool_use(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def tool_result(tid, content, minute=2, is_error=False):
    return user([{"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": is_error}],
                minute=minute)


class PreviewTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="ccs-preview-"))
        self.addCleanup(shutil.rmtree, self.dir)

    def journal(self, rows, raw_tail=""):
        p = self.dir / "s1.jsonl"
        p.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows) + raw_tail)
        return p


class ReadMessagesTest(PreviewTestCase):
    def test_basic_exchange(self):
        p = self.journal([
            {"type": "permission-mode", "permissionMode": "default", "sessionId": "s1"},
            user("corrige le calcul", minute=0),
            assistant("m1", [{"type": "thinking", "thinking": "secret", "signature": "x"}]),
            assistant("m1", [text("Je regarde le fichier.")]),
            assistant("m1", [tool_use("t1", "Read", file_path=f"{CWD}/calc.py")]),
            tool_result("t1", "1\tdef f():\n2\t    return 1"),
            assistant("m2", [text("C'est corrigé.")], minute=3),
            {"type": "ai-title", "aiTitle": "Calcul", "sessionId": "s1"},
            {"parentUuid": "p", "type": "system", "subtype": "turn_duration", "durationMs": 10,
             "timestamp": ts(4), "isSidechain": False, "uuid": "sys1"},
        ])
        msgs = read_messages(p)
        self.assertEqual([m.role for m in msgs], [USER, ASSISTANT, TOOL, ASSISTANT])
        self.assertEqual(msgs[0].text, "corrige le calcul")
        self.assertEqual(msgs[1].text, "Je regarde le fichier.")
        self.assertEqual(msgs[2].tool.name, "Read")
        self.assertEqual(msgs[2].tool.target, f"{CWD}/calc.py")
        self.assertIn("return 1", msgs[2].tool.result)
        self.assertFalse(msgs[2].tool.is_error)
        self.assertEqual(msgs[3].text, "C'est corrigé.")
        self.assertIsNotNone(msgs[0].ts)
        self.assertNotIn("secret", json.dumps([m.text for m in msgs]))

    def test_text_blocks_of_one_answer_are_merged(self):
        p = self.journal([user("salut"), assistant("m1", [text("Première partie.")]),
                          assistant("m1", [text("Seconde partie.")])])
        msgs = read_messages(p)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[1].text, "Première partie.\n\nSeconde partie.")

    def test_duplicate_lines_are_ignored(self):
        row = assistant("m1", [text("Une fois.")])
        p = self.journal([user("salut"), row, row])
        self.assertEqual([m.text for m in read_messages(p)], ["salut", "Une fois."])

    def test_injected_meta_sidechain_and_non_human_messages_are_skipped(self):
        p = self.journal([
            user("Base directory for this skill: /x", isMeta=True),
            user("<local-command-stdout>ok</local-command-stdout>"),
            user("<task-notification>fini</task-notification>", origin={"kind": "task-notification"}),
            user("message d'un autre agent", origin={"kind": "peer"}),
            user("résumé…", isCompactSummary=True, isVisibleInTranscriptOnly=True),
            user("fil latéral", isSidechain=True),
            assistant("side", [text("réponse latérale")], isSidechain=True),
            assistant("syn", [text("No response requested.")], model="<synthetic>"),
            {"type": "api-request-blob", "hash": "h", "sessionId": "s1",
             "message": {"role": "user", "content": "copie de la requête"}},
            user("la vraie demande"),
        ])
        self.assertEqual([(m.role, m.text) for m in read_messages(p)], [(USER, "la vraie demande")])

    def test_vscode_context_and_system_reminders_are_removed(self):
        p = self.journal([user([text("<ide_opened_file>a.py</ide_opened_file>"),
                                text("explique ce module<system-reminder>rappel</system-reminder>")])])
        [m] = read_messages(p)
        self.assertEqual(m.text, "explique ce module")

    def test_wrapped_typed_text_is_kept(self):
        p = self.journal([user("<pasted_content>ligne 1\nligne 2</pasted_content>"),
                          user("<browser_instruction>ouvre la page</browser_instruction>", minute=1)])
        self.assertEqual([m.text for m in read_messages(p)], ["ligne 1\nligne 2", "ouvre la page"])

    def test_slash_command_and_interruption_and_image(self):
        p = self.journal([
            user("<command-name>/model</command-name>\n<command-message>model</command-message>\n"
                 "<command-args>opus</command-args>"),
            user([text("[Request interrupted by user]")], minute=1),
            user([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
                  text("[Image: original 100x100, displayed at 100x100]"), text("et ça ?")], minute=2),
        ])
        msgs = read_messages(p)
        self.assertEqual((msgs[0].role, msgs[0].text), (USER, "/model opus"))
        self.assertEqual(msgs[1].role, NOTE)
        self.assertIn("interromp", msgs[1].text.lower())
        self.assertEqual((msgs[2].role, msgs[2].text), (USER, "[image]\n\net ça ?"))

    def test_compaction_is_a_note(self):
        p = self.journal([user("a"), {"parentUuid": None, "type": "system", "subtype": "compact_boundary",
                                      "content": "Conversation compacted", "timestamp": ts(5),
                                      "isSidechain": False, "uuid": "c1"}, user("b", minute=6)])
        self.assertEqual([m.role for m in read_messages(p)], [USER, NOTE, USER])

    def test_tool_summaries(self):
        calls = [
            ("Bash", {"command": "pytest -q\necho fini", "description": "Lance les tests"}, "pytest -q"),
            ("Edit", {"file_path": "/w/a.py", "old_string": "x", "new_string": "y"}, "/w/a.py"),
            ("Grep", {"pattern": "TODO", "path": "/w"}, "TODO dans /w"),
            ("Glob", {"pattern": "**/*.py"}, "**/*.py"),
            ("WebFetch", {"url": "https://exemple.fr", "prompt": "résume"}, "https://exemple.fr"),
            ("WebSearch", {"query": "gtk4 file dialog"}, "gtk4 file dialog"),
            ("Agent", {"description": "Audit du code", "prompt": "long…"}, "Audit du code"),
            ("Skill", {"skill": "claude-api"}, "claude-api"),
            ("TodoWrite", {"todos": [{"content": "x"}]}, "liste de tâches"),
            ("mcp__rea__open_binary", {"path": "/bin/ls"}, "/bin/ls"),
            ("Inconnu", {}, ""),
        ]
        rows = [user("go")] + [assistant(f"m{i}", [tool_use(f"t{i}", n, **inp)]) for i, (n, inp, _) in enumerate(calls)]
        msgs = [m for m in read_messages(self.journal(rows)) if m.role == TOOL]
        self.assertEqual([m.tool.target for m in msgs], [want for _n, _i, want in calls])
        self.assertEqual(msgs[9].tool.label, "rea · open_binary")
        self.assertEqual(msgs[0].text, "Bash · pytest -q")

    def test_long_targets_and_results_are_shortened(self):
        p = self.journal([user("go"), assistant("m1", [tool_use("t1", "Bash", command="x" * 500)]),
                          tool_result("t1", [{"type": "text", "text": "y" * 10_000}], is_error=True)])
        tool = read_messages(p, max_result_chars=100)[1].tool
        self.assertLessEqual(len(tool.target), preview.TARGET_MAX)
        self.assertTrue(tool.target.endswith("…"))
        self.assertLessEqual(len(tool.result), 101)
        self.assertTrue(tool.is_error)

    def test_results_can_be_omitted(self):
        p = self.journal([user("go"), assistant("m1", [tool_use("t1", "Read", file_path="/a")]),
                          tool_result("t1", "contenu")])
        self.assertIsNone(read_messages(p, results=False)[1].tool.result)

    def test_corrupt_lines_and_partial_last_line(self):
        p = self.journal([user("un")], raw_tail='pas du json\n[1]\n"x"\n{"type":"user","message":{"content":"coup')
        self.assertEqual([m.text for m in read_messages(p)], ["un"])

    def test_limit_keeps_the_last_messages(self):
        rows = []
        for i in range(10):
            rows += [user(f"demande {i}", minute=i), assistant(f"m{i}", [text(f"réponse {i}")], minute=i)]
        msgs = read_messages(self.journal(rows), limit=3)
        self.assertEqual([m.text for m in msgs], ["réponse 8", "demande 9", "réponse 9"])

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            read_messages(self.dir / "absent.jsonl")


class MarkdownTest(PreviewTestCase):
    def conv(self):
        start = datetime(2026, 11, 4, 10, 0).timestamp()
        return Conversation(session_id="s1", path=str(self.dir / "s1.jsonl"), cwd=CWD, title="Calcul des intérêts",
                            first_prompt="corrige", last_prompt="merci", prompts=2, started_at=start,
                            updated_at=start + 3600, origin="terminal", git_branch="main", size=10)

    def test_markdown_document(self):
        p = self.journal([user("corrige le `calcul`"), assistant("m1", [text("Voici :\n\n```py\nx = 1\n```")]),
                          assistant("m1", [tool_use("t1", "Bash", command="echo `date`")]),
                          tool_result("t1", "mar. 4 nov.")])
        md = to_markdown(self.conv(), read_messages(p))
        self.assertTrue(md.startswith("# Calcul des intérêts\n"))
        self.assertIn("App", md)
        self.assertIn(CWD, md)
        self.assertIn("`main`", md)
        self.assertIn("04/11/2026", md)
        self.assertIn("`s1`", md)
        self.assertIn("## Toi", md)
        self.assertIn("## Claude", md)
        self.assertIn("corrige le `calcul`", md)
        self.assertIn("```py\nx = 1\n```", md)
        self.assertIn("- `Bash` : `` echo `date` ``", md)
        self.assertNotIn("mar. 4 nov.", md)  # résultats omis par défaut
        self.assertIn("mar. 4 nov.", to_markdown(self.conv(), read_messages(p), results=True))
        self.assertTrue(md.endswith("\n"))

    def test_markdown_from_dict_and_without_meta(self):
        md = to_markdown({"title": "Titre", "cwd": CWD}, [preview.Message(USER, "bonjour")])
        self.assertTrue(md.startswith("# Titre\n"))
        self.assertIn("bonjour", md)
        md = to_markdown(None, [])
        self.assertTrue(md.startswith("# Conversation\n"))
        self.assertIn("Aucun message", md)

    def test_markdown_for_conversation(self):
        self.journal([user("salut"), assistant("m1", [text("Bonjour !")])])
        md = preview.markdown_for(self.conv())
        self.assertIn("Bonjour !", md)
        dest = self.dir / "export" / "conv.md"
        preview.export_markdown(self.conv(), dest)
        self.assertEqual(dest.read_text(), md)

    def test_suggested_file_name(self):
        self.assertEqual(preview.suggested_filename(self.conv()), "calcul-des-interets.md")
        self.assertEqual(preview.suggested_filename({"title": "///"}), "conversation.md")


if __name__ == "__main__":
    unittest.main()
