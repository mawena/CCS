import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from unittest import mock

from ccs_app import sessions
from ccs_app.sessions import Session
from tests.helpers import HomeTestCase, write

NOW = time.time()


def fiche(pid, name="app-1a", cwd="/home/u/Work/App", status="busy", started=NOW - 600,
          updated=NOW - 5, **extra):
    return {"pid": pid, "sessionId": f"sess-{pid}", "name": name, "cwd": cwd, "status": status,
            "startedAt": int(started * 1000), "updatedAt": int(updated * 1000),
            "statusUpdatedAt": int(updated * 1000), "kind": "interactive", "entrypoint": "cli",
            **extra}


class ListSessionsTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.dir = self.home / ".claude" / "sessions"
        # Un vrai processus « vivant » pour les fiches valides.
        self.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(self.proc.kill)
        alive = mock.patch.object(sessions, "_is_claude", side_effect=lambda pid: pid == self.proc.pid)
        alive.start()
        self.addCleanup(alive.stop)

    def test_lists_live_sessions_only(self):
        write(self.dir / f"{self.proc.pid}.json", fiche(self.proc.pid, status="waiting",
                                                        waitingFor="permission"))
        write(self.dir / "999999.json", fiche(999999))                 # processus mort
        write(self.dir / "123.json", "{cassé")                          # fiche invalide
        write(self.dir / f"{self.proc.pid}.abc.key", "secret")          # jamais lu
        found = sessions.list_sessions()
        self.assertEqual([s.pid for s in found], [self.proc.pid])
        s = found[0]
        self.assertEqual((s.project, s.state, s.waiting_for), ("App", "waiting", "permission"))
        self.assertEqual(s.session_id, f"sess-{self.proc.pid}")

    def test_state_mapping_and_home_project(self):
        write(self.dir / f"{self.proc.pid}.json", fiche(self.proc.pid, status="idle", cwd=str(self.home)))
        s = sessions.list_sessions()[0]
        self.assertEqual((s.state, s.project), ("idle", "~"))
        self.assertEqual(sessions.state_label(s), "au repos")

    def test_missing_dir(self):
        self.assertEqual(sessions.list_sessions(), [])


class ConversationTest(HomeTestCase):
    def transcript(self, cwd, sid, lines):
        slug = sessions.project_slug(cwd)
        p = self.home / ".claude" / "projects" / slug / f"{sid}.jsonl"
        write(p, "\n".join(json.dumps(l) for l in lines) + "\n")
        return p

    def test_project_slug(self):
        self.assertEqual(sessions.project_slug("/home/u/Work/My App (p"), "-home-u-Work-My-App--p")

    def test_conversation_usage(self):
        ts = datetime.now(timezone.utc).isoformat()
        self.transcript("/home/u/App", "s1", [
            {"type": "user", "message": {"role": "user", "content": "corrige le bug"}, "timestamp": ts},
            {"type": "assistant", "timestamp": ts, "cwd": "/home/u/App",
             "message": {"id": "m1", "model": "claude-opus-5-5",
                         "usage": {"input_tokens": 10, "output_tokens": 100,
                                   "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 5000}}},
        ])
        s = Session(1, "s1", "app", "/home/u/App", "App", "busy", None, NOW, NOW, "interactive", "cli")
        u = sessions.conversation_usage(s)
        self.assertAlmostEqual(u.weighted, 2010)
        self.assertEqual(u.model, "opus")
        self.assertEqual(u.messages, 1)

    def test_recent_conversations_with_titles(self):
        ts = datetime.now(timezone.utc).isoformat()
        old = self.transcript("/home/u/App", "old", [
            {"type": "user", "message": {"role": "user", "content": "ancienne tâche"}, "timestamp": ts}])
        os.utime(old, (NOW - 3600, NOW - 3600))
        self.transcript("/home/u/App", "new", [
            {"type": "user", "message": {"role": "user",
                                         "content": [{"type": "text", "text": "ajoute un export CSV\net plus"}]},
             "timestamp": ts}])
        convs = sessions.recent_conversations("/home/u/App")
        self.assertEqual([c.session_id for c in convs], ["new", "old"])
        self.assertEqual(convs[0].title, "ajoute un export CSV")


class TransitionsTest(HomeTestCase):
    def sess(self, pid, state, since):
        return Session(pid, f"s{pid}", f"app{pid}", "/x", f"P{pid}", state, None,
                       NOW - 3600, since, "interactive", "cli")

    def test_busy_to_idle_and_waiting(self):
        prev = {1: self.sess(1, "busy", NOW - 120), 2: self.sess(2, "busy", NOW - 300)}
        cur = [self.sess(1, "idle", NOW), self.sess(2, "waiting", NOW)]
        out = sessions.transitions(prev, cur, NOW)
        self.assertEqual([(s.pid, kind) for s, kind in out], [(1, "done"), (2, "waiting")])

    def test_short_busy_period_not_reported(self):
        prev = {1: self.sess(1, "busy", NOW - 20)}
        self.assertEqual(sessions.transitions(prev, [self.sess(1, "idle", NOW)], NOW), [])

    def test_new_or_unchanged_sessions_not_reported(self):
        prev = {1: self.sess(1, "idle", NOW - 600)}
        cur = [self.sess(1, "idle", NOW - 600), self.sess(2, "idle", NOW)]
        self.assertEqual(sessions.transitions(prev, cur, NOW), [])


class ActionsTest(HomeTestCase):
    def test_terminal_command(self):
        with mock.patch.object(sessions.shutil, "which", side_effect=lambda n, **k: f"/usr/bin/{n}"):
            cmd = sessions.terminal_command("/home/u/App", resume="abc")
        self.assertEqual(cmd[:2], ["/usr/bin/gnome-terminal", "--working-directory=/home/u/App"])
        self.assertIn("--resume abc", cmd[-1])
        with mock.patch.object(sessions.shutil, "which", side_effect=lambda n, **k: f"/usr/bin/{n}"):
            self.assertTrue(sessions.terminal_command("/home/u/App")[-1].endswith("claude"))

    def test_terminate_refuses_non_claude_pid(self):
        with mock.patch.object(sessions, "_is_claude", return_value=False), \
                mock.patch.object(sessions.os, "kill") as kill:
            self.assertFalse(sessions.terminate(4242))
        kill.assert_not_called()
