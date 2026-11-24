"""Sous-agents d'un chat : suivi en direct (événements du moteur), lecture sur le disque, fusion,
et demande d'arrêt d'un seul sous-agent (`stop_task`)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ccs_app import chat_engine, chat_protocol as proto, subagents


def launch(tool_id, description, background=False, parent=None):
    data = {"description": description, "prompt": "fais ceci", "subagent_type": "Explore"}
    if background:
        data["run_in_background"] = True
    return proto.ToolUse(tool_id, "Agent", data, parent)


def started(tool_id, task_id, backgrounded=None):
    raw = {"type": "system", "subtype": "task_started", "task_id": task_id, "tool_use_id": tool_id}
    if backgrounded is not None:
        raw["is_backgrounded"] = backgrounded
    return proto.Unknown(raw)


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.t = subagents.Subagents(clock=lambda: self.now)

    def test_launch_order_and_ranks(self):
        self.t.feed(launch("t1", "Chercher les appels"))
        self.now += 1
        self.t.feed(launch("t2", "Écrire les tests", background=True))
        self.t.feed(proto.ToolUse("x", "Bash", {"command": "ls"}))      # pas un sous-agent
        self.t.feed(proto.ToolResult("t1", "fini"))
        items = subagents.numbered(self.t.items())
        self.assertEqual([i["tool_id"] for i in items], ["t1", "t2"])
        self.assertEqual([i["index"] for i in items], [1, 2])
        self.assertEqual(items[0]["state"], "done")
        self.assertIsNone(items[0]["active_index"])
        self.assertEqual(items[1]["active_index"], 1)
        self.assertEqual(items[1]["type"], "Explore")
        self.assertEqual(items[0]["started"], 100.0)
        self.assertEqual(self.t.running(), 1)

    def test_background_ends_with_the_notice_not_the_result(self):
        self.t.feed(launch("t1", "Long travail"))
        self.t.feed(started("t1", "a123", backgrounded=True))
        self.t.feed(proto.ToolResult("t1", "Async agent launched successfully."))
        self.assertEqual(self.t.items()[0]["state"], "running")
        self.assertEqual(self.t.items()[0]["task_id"], "a123")
        self.t.feed(proto.TaskNotice("t1", "killed", "arrêté"))
        self.assertEqual(self.t.items()[0]["state"], "stopped")
        self.assertEqual(self.t.items()[0]["summary"], "arrêté")

    def test_async_result_marks_background_without_task_started(self):
        self.t.feed(launch("t1", "Ancienne CLI"))
        self.t.feed(proto.ToolResult("t1", "Async agent launched successfully. agentId: a9"))
        self.assertEqual(self.t.items()[0]["state"], "running")
        self.assertTrue(self.t.items()[0]["background"])

    def test_error_result_and_task_updates(self):
        self.t.feed(launch("t1", "Raté"))
        self.t.feed(proto.ToolResult("t1", "boum", is_error=True))
        self.t.feed(launch("t2", "Suivi", background=True))
        self.t.feed(started("t2", "b2"))
        self.t.feed(proto.Unknown({"type": "system", "subtype": "task_updated", "task_id": "b2",
                                   "patch": {"status": "completed"}}))
        self.assertEqual([i["state"] for i in self.t.items()], ["failed", "done"])

    def test_task_started_of_a_command_is_ignored(self):
        self.t.feed(started("cmd", "c1"))
        self.assertEqual(self.t.items(), [])

    def test_stopped_cli_ends_everything(self):
        self.t.feed(launch("t1", "A", background=True))
        self.t.feed(chat_engine.StateChanged("stopped"))
        self.assertEqual(self.t.items()[0]["state"], "stopped")

    def test_keeps_a_bounded_list(self):
        t = subagents.Subagents(keep=3)
        for n in range(5):
            t.feed(launch(f"t{n}", f"n{n}"))
            if n < 3:
                t.feed(proto.ToolResult(f"t{n}", "ok"))
        self.assertEqual([i["tool_id"] for i in t.items()], ["t2", "t3", "t4"])


class DiskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccs-sub-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.journal = self.tmp / "sess.jsonl"
        self.journal.write_text("")
        self.folder = self.tmp / "sess" / "subagents"
        self.folder.mkdir(parents=True)

    def agent(self, agent_id, tool_id, description, when, finished):
        (self.folder / f"agent-{agent_id}.meta.json").write_text(json.dumps({
            "agentType": "general-purpose", "description": description, "toolUseId": tool_id,
            "requestShape": "background", "finished": finished}))
        (self.folder / f"agent-{agent_id}.jsonl").write_text(
            json.dumps({"type": "user", "timestamp": when}) + "\n")

    def test_reads_in_launch_order(self):
        self.agent("bbb", "t2", "Deuxième", "2026-11-23T10:05:00Z", False)
        self.agent("aaa", "t1", "Premier", "2026-11-23T10:00:00.123Z", True)
        items = subagents.from_transcript(str(self.journal))
        self.assertEqual([i["description"] for i in items], ["Premier", "Deuxième"])
        self.assertEqual([i["task_id"] for i in items], ["aaa", "bbb"])
        self.assertEqual([i["state"] for i in items], ["done", "running"])
        self.assertTrue(items[0]["background"])

    def test_missing_folder_or_bad_meta(self):
        self.assertEqual(subagents.from_transcript(None), [])
        self.assertEqual(subagents.from_transcript(str(self.tmp / "autre.jsonl")), [])
        (self.folder / "agent-zz.meta.json").write_text("{pas du json")
        self.assertEqual(subagents.from_transcript(str(self.journal)), [])

    def test_merge_takes_task_id_from_disk(self):
        self.agent("aaa", "t1", "Premier", "2026-11-23T10:00:00Z", False)
        t = subagents.Subagents()
        t.feed(launch("t1", "Premier"))
        merged = subagents.merge(t.items(), subagents.from_transcript(str(self.journal)))
        self.assertEqual(merged[0]["task_id"], "aaa")
        self.assertEqual(len(subagents.merge([], subagents.from_transcript(str(self.journal)))), 1)

    def test_merge_adds_agents_launched_before_in_launch_order(self):
        """Lancés avant une reprise : le pont ne les a pas vus, le disque les rend quand même."""
        self.agent("aaa", "t1", "Avant", "2026-11-23T10:00:00Z", True)
        t = subagents.Subagents(clock=lambda: 4e9)
        t.feed(launch("t2", "Après"))
        merged = subagents.merge(t.items(), subagents.from_transcript(str(self.journal)))
        self.assertEqual([i["tool_id"] for i in merged], ["t1", "t2"])


def line(kind, content, msg_id="m1"):
    msg = {"role": kind, "content": content}
    if kind == "assistant":
        msg["id"] = msg_id
    return json.dumps({"type": kind, "isSidechain": True, "agentId": "aaa", "message": msg}) + "\n"


class LogTest(unittest.TestCase):
    """Étapes d'un sous-agent de fond, lues dans sa transcription."""

    agent = DiskTest.agent

    def setUp(self):
        DiskTest.setUp(self)
        self.agent("aaa", "t1", "Fond", "2026-11-23T10:00:00Z", False)
        self.log = self.folder / "agent-aaa.jsonl"

    def write(self, text):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(text)

    def item(self, state="running", task_id=""):
        return {"tool_id": "t1", "task_id": task_id, "background": True, "state": state}

    def test_steps_attached_to_the_launching_call(self):
        self.write(line("assistant", [{"type": "text", "text": "Je cherche."},
                                      {"type": "thinking", "thinking": "…"},
                                      {"type": "tool_use", "id": "u1", "name": "Grep", "input": {"pattern": "x"}}]))
        self.write(line("user", [{"type": "tool_result", "tool_use_id": "u1", "content": "trouvé"}]))
        evs = subagents.read_log(str(self.journal), self.item())
        self.assertEqual([type(e).__name__ for e in evs], ["AssistantText", "ToolUse", "ToolResult"])
        self.assertTrue(all(e.parent_id == "t1" for e in evs))
        self.assertEqual(evs[2].text, "trouvé")

    def test_found_by_task_id_or_meta(self):
        self.assertEqual(subagents.log_path(str(self.journal), self.item(task_id="aaa")), self.log)
        self.assertEqual(subagents.log_path(str(self.journal), self.item()), self.log)
        self.assertIsNone(subagents.log_path(str(self.journal), {"tool_id": "t9", "task_id": "../x"}))
        self.assertIsNone(subagents.log_path(None, self.item()))

    def test_tail_reads_only_new_complete_lines_then_lets_go(self):
        tails = subagents.Tails()
        journal = str(self.journal)
        self.assertTrue(tails.wants([self.item()]))
        self.assertEqual(tails.poll(journal, [self.item()]), [])       # rien que la consigne
        self.write(line("assistant", [{"type": "text", "text": "Un."}], "m1"))
        half = line("assistant", [{"type": "text", "text": "Deux."}], "m2")
        self.write(half[:20])                                          # ligne en cours d'écriture
        self.assertEqual([e.text for e in tails.poll(journal, [self.item()])], ["Un."])
        self.write(half[20:])
        self.assertEqual([e.text for e in tails.poll(journal, [self.item()])], ["Deux."])
        self.write(line("assistant", [{"type": "text", "text": "Fini."}], "m3"))
        done = self.item("done")
        self.assertEqual([e.text for e in tails.poll(journal, [done])], ["Fini."])   # lu jusqu'au bout
        self.assertFalse(tails.wants([done]))
        self.assertEqual(tails.poll(journal, [done]), [])

    def test_foreground_agents_are_not_tailed(self):
        """Au premier plan, la CLI passe déjà ses étapes dans le flux : pas de double."""
        tails = subagents.Tails()
        fg = dict(self.item(), background=False)
        self.assertFalse(tails.wants([fg]))
        self.write(line("assistant", [{"type": "text", "text": "Un."}]))
        self.assertEqual(tails.poll(str(self.journal), [fg]), [])

    def test_sidechain_ignores_other_entries(self):
        self.assertEqual(proto.sidechain_events({"type": "attachment"}, "t1"), [])
        self.assertEqual(proto.sidechain_events({"type": "user", "message": {"content": "consigne"}}, "t1"), [])
        self.assertEqual(proto.sidechain_events("x", "t1"), [])


class StopTaskTest(unittest.TestCase):
    def test_stop_task_writes_the_control_request(self):
        engine = chat_engine.ChatSession("/tmp")
        lines = []
        engine._write = lambda line: lines.append(line) or True
        self.assertTrue(engine.stop_task("a123"))
        msg = json.loads(lines[0])
        self.assertEqual(msg["type"], "control_request")
        self.assertEqual(msg["request"], {"subtype": "stop_task", "task_id": "a123"})
        self.assertFalse(engine.stop_task(""))


if __name__ == "__main__":
    unittest.main()
