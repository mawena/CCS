"""Jarvis aux commandes du réseau (`bridge_pilot`) : vue d'ensemble, noms approchés, sous-agents
et sessions arrêtés avec confirmation, lancement d'une session sur une autre machine.

Deux ponts dans le même processus : « vps » (celui où Jarvis est branché) et « pc » (une autre
machine), joint par un faux lien qui appelle directement ses méthodes (le vrai lien ssh est
couvert par `test_server_bridge_machines`)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccs_app import chat_options, distant, distant_jobs, sessions
from ccs_app.server import bridge, bridge_chat, bridge_pilot, rpc
from tests.helpers import make_home


class FakeEngine:
    def __init__(self, state="busy", session_id="", pid=None):
        self.state, self.session_id, self.pid = state, session_id, pid
        self.stopped_tasks, self.stopped = [], False
        self.options = chat_options.ChatOptions()

    def stop_task(self, task_id):
        self.stopped_tasks.append(task_id)
        return True

    def stop(self, grace_s=5):
        self.stopped = True
        self.state = "stopped"


class FakeConn:
    def __init__(self):
        self.peer = {"ok": True}
        self.closed = False
        self.pushed = []

    async def push(self, name, data):
        self.pushed.append((name, data))


class FakeClient:
    def __init__(self, far, calls, old=False):
        self.far, self.calls, self.old = far, calls, old

    async def call(self, method, **params):
        self.calls.append((method, params))
        if self.old and method.startswith("jarvis."):
            raise rpc.RpcError("introuvable", f"Méthode inconnue : {method}")
        handler = self.far.handlers().get(method)
        return await handler(FakeConn(), params)


class FakeLink:
    def __init__(self, client):
        self.client = client

    async def close(self):
        pass


class FakeMachines:
    """À la place de `MachinesApi` : `connect` rend un lien vers le pont « pc »."""

    def __init__(self, test):
        self.test = test
        self._fetch = lambda: []

    async def connect(self, mid, timeout=None):
        if mid not in self.test.reachable:
            raise rpc.RpcError("introuvable", f"{mid} injoignable : délai dépassé")
        return None, FakeLink(FakeClient(self.test.far, self.test.calls, self.test.old_far)), {}


def tool_use(tool_id, description, background=True):
    from ccs_app import chat_protocol as proto
    return proto.ToolUse(tool_id, "Agent", {"description": description, "subagent_type": "Explore",
                                            "run_in_background": background})


def task_started(tool_id, task_id):
    from ccs_app import chat_protocol as proto
    return proto.Unknown({"type": "system", "subtype": "task_started", "task_id": task_id,
                          "tool_use_id": tool_id})


class PilotTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccs-pilot-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = make_home(str(self.tmp))
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.calls, self.reachable, self.old_far = [], {"pc"}, False
        self.machines = [
            {"id": "vps", "name": "Serveur CCS", "online": True, "local": True, "running": 0, "waiting": 0},
            {"id": "pc", "name": "lp-work", "online": True, "local": False, "running": 1, "waiting": 0},
            {"id": "lp-home", "name": "lp-home", "online": False, "local": False},
        ]
        over = mock.patch.object(distant, "machines_overview",
                                 side_effect=lambda fetch=None: {"machines": [dict(m) for m in self.machines]})
        over.start()
        self.addCleanup(over.stop)
        jobs = mock.patch.object(distant_jobs, "list_jobs", return_value=[
            {"id": "abc123", "text": "make test", "machine": "pc", "state": "running", "created": 1},
            {"id": "def456", "text": "make deb", "machine": "pc", "state": "done", "code": 0}])
        jobs.start()
        self.addCleanup(jobs.stop)
        # projets des deux machines
        for name in ("GliGli", "Sonde", "CCS"):
            (self.home / "Work" / name).mkdir(parents=True)

        # « pc » : un chat GliGli avec deux sous-agents de fond en cours et un fini
        self.far = bridge.Bridge("bob", None, local=True, start_daemon=False, install_claude=False)
        self.far_hub = bridge_chat.ChatHub(self.far)
        self.far_engine = FakeEngine("busy", "s-gli", 4242)
        chat = self.add_chat(self.far_hub, "cf-1", self.home / "Work" / "GliGli", self.far_engine)
        for ev in (tool_use("t0", "Ancien", background=False), tool_use("t1", "Lire le code"),
                   task_started("t1", "a1"), tool_use("t2", "Écrire les tests"),
                   task_started("t2", "a2")):
            chat.agents.feed(ev)
        from ccs_app import chat_protocol as proto
        chat.agents.feed(proto.ToolResult("t0", "fini"))
        self.far_terminal = []
        self.far_pilot = bridge_pilot.PilotApi(self.far, None, self.far_hub,
                                               list_terminal=lambda: self.far_terminal)
        self.far_pilot._local_projects = lambda: [
            {"name": "GliGli", "cwd": str(self.home / "Work" / "GliGli")},
            {"name": "Sonde", "cwd": str(self.home / "Work" / "Sonde")}]

        # « vps » : un chat Sonde au repos, et une session de terminal « Élan »
        self.near = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        self.near_hub = bridge_chat.ChatHub(self.near)
        self.near_engine = FakeEngine("idle", "s-sonde", 5151)
        self.add_chat(self.near_hub, "cn-1", self.home / "Work" / "Sonde", self.near_engine)
        self.terminal = [sessions.Session(
            pid=777, session_id="s-elan", name="Élan", cwd=str(self.home / "Work" / "CCS"),
            project="CCS", state="waiting", waiting_for=None, started_at=5.0, state_since=5.0,
            kind="interactive", entrypoint="cli", proc_start="99")]
        self.terminated = []
        self.pilot = bridge_pilot.PilotApi(
            self.near, FakeMachines(self), self.near_hub, list_terminal=lambda: self.terminal,
            terminate=lambda pid, start=None: self.terminated.append((pid, start)) or True)
        self.pilot._local_projects = lambda: [{"name": "CCS", "cwd": str(self.home / "Work" / "CCS")},
                                              {"name": "Sonde", "cwd": str(self.home / "Work" / "Sonde")}]
        self.addAsyncCleanup(self.near_hub.close_all)
        self.addAsyncCleanup(self.far_hub.close_all)

    @staticmethod
    def add_chat(hub, chat_id, cwd, engine):
        chat = bridge_chat._Chat(chat_id, str(cwd))
        chat.engine = engine
        hub.chats[chat_id] = chat
        return chat

    async def call(self, method, **params):
        return await self.near.handlers()[method](FakeConn(), params)

    # ---- lecture -------------------------------------------------------------------------

    async def test_state_covers_the_whole_network(self):
        res = await self.call("jarvis.state")
        by_name = {s["name"]: s for s in res["sessions"]}
        self.assertEqual(set(by_name), {"Sonde", "Élan", "GliGli"})
        gli = by_name["GliGli"]
        self.assertEqual((gli["machine"], gli["machine_name"], gli["kind"]), ("pc", "lp-work", "chat"))
        self.assertEqual(gli["state"], "working")
        self.assertEqual(gli["state_label"], "au travail")
        # seulement les sous-agents en cours dans la vue d'ensemble
        self.assertEqual([a["description"] for a in gli["subagents"]], ["Lire le code", "Écrire les tests"])
        self.assertEqual(gli["subagents_running"], 2)
        self.assertEqual(by_name["Élan"]["kind"], "terminal")
        self.assertFalse(by_name["Élan"]["subagents_stoppable"])
        self.assertEqual(by_name["Sonde"]["machine"], "vps")
        self.assertEqual([m["id"] for m in res["machines"]], ["vps", "pc", "lp-home"])
        self.assertEqual(res["errors"], [])                       # hors ligne : pas une erreur
        self.assertEqual([j["id"] for j in res["jobs"]], ["abc123", "def456"])
        self.assertEqual(res["jobs"][0]["state_label"], "en cours")
        self.assertIn("2 machines en ligne sur 3", res["summary"])
        self.assertIn("3 sessions (1 au travail, 1 en attente de réponse)", res["summary"])
        self.assertIn("2 sous-agents en cours", res["summary"])
        self.assertIn("1 travail distant actif", res["summary"])

    async def test_unreachable_machine_is_reported(self):
        self.reachable = set()
        res = await self.call("jarvis.state")
        self.assertEqual(res["errors"], [{"machine": "pc", "message": "pc injoignable : délai dépassé"}])
        self.assertEqual({s["machine"] for s in res["sessions"]}, {"vps"})

    async def test_sessions_of_one_machine_by_approximate_name(self):
        res = await self.call("jarvis.sessions", machine="LP Work")
        self.assertEqual([s["name"] for s in res["sessions"]], ["GliGli"])
        self.assertEqual(len(res["sessions"][0]["subagents"]), 3)
        with self.assertRaises(rpc.RpcError) as e:
            await self.call("jarvis.sessions", machine="imprimante")
        self.assertEqual(e.exception.code, "introuvable")

    async def test_subagents_in_launch_order(self):
        res = await self.call("jarvis.subagents", session="la session gli gli")
        self.assertEqual(res["session"]["name"], "GliGli")
        self.assertNotIn("subagents", res["session"])
        items = res["subagents"]
        self.assertEqual([(a["index"], a["active_index"], a["state"]) for a in items],
                         [(1, None, "done"), (2, 1, "running"), (3, 2, "running")])

    async def test_accents_and_case_do_not_matter(self):
        res = await self.call("jarvis.subagents", session="ELAN")
        self.assertEqual(res["session"]["name"], "Élan")

    async def test_unknown_and_ambiguous_sessions(self):
        with self.assertRaises(rpc.RpcError) as e:
            await self.call("jarvis.subagents", session="Zorglub")
        self.assertEqual(e.exception.code, "introuvable")
        self.assertIn("GliGli (lp-work)", e.exception.message)
        self.add_chat(self.near_hub, "cn-2", self.home / "Work" / "GliGli", FakeEngine("idle", "s-g2"))
        with self.assertRaises(rpc.RpcError) as e:
            await self.call("jarvis.subagents", session="GliGli")
        self.assertEqual(e.exception.code, "conflit")
        res = await self.call("jarvis.subagents", session="GliGli", machine="pc")
        self.assertEqual(res["session"]["machine"], "pc")

    async def test_old_far_bridge_gives_its_chats(self):
        self.old_far = True
        res = await self.call("jarvis.sessions", machine="pc")
        self.assertEqual([s["chat_id"] for s in res["sessions"]], ["cf-1"])
        self.assertEqual(res["sessions"][0]["subagents"], [])

    # ---- arrêter un sous-agent -----------------------------------------------------------

    async def test_stop_subagent_asks_first(self):
        res = await self.call("jarvis.stop_subagent", session="GliGli", index="premier")
        self.assertFalse(res["done"])
        self.assertTrue(res["confirm_needed"])
        self.assertEqual(res["target"]["subagent"]["description"], "Lire le code")
        self.assertEqual(res["target"]["machine"], "pc")
        self.assertEqual(res["question"],
                         "Arrêter le sous-agent 1 « Lire le code » de la session GliGli sur lp-work ?")
        self.assertEqual(self.far_engine.stopped_tasks, [])

    async def test_stop_subagent_confirmed_goes_to_the_right_machine(self):
        res = await self.call("jarvis.stop_subagent", session="gligli", index=1, confirme=True)
        self.assertTrue(res["done"])
        self.assertEqual(self.far_engine.stopped_tasks, ["a1"])
        self.assertIn(("jarvis.stop_subagent", {"local": True, "chat_id": "cf-1", "tool_id": "t1",
                                                "confirme": True}), self.calls)
        await self.call("jarvis.stop_subagent", session="gligli", index="dernier", confirme=True)
        self.assertEqual(self.far_engine.stopped_tasks, ["a1", "a2"])

    async def test_stop_subagent_needs_a_rank_when_several_run(self):
        with self.assertRaises(rpc.RpcError) as e:
            await self.call("jarvis.stop_subagent", session="GliGli")
        self.assertEqual(e.exception.code, "conflit")
        self.assertIn("1. Lire le code; 2. Écrire les tests", e.exception.message)
        with self.assertRaises(rpc.RpcError) as e:
            await self.call("jarvis.stop_subagent", session="GliGli", index=3)
        self.assertEqual(e.exception.code, "introuvable")
        with self.assertRaises(rpc.RpcError) as e:
            await self.call("jarvis.stop_subagent", session="GliGli", index="vingtième")
        self.assertEqual(e.exception.code, "invalide")

    async def test_stop_subagent_by_tool_id(self):
        res = await self.call("jarvis.stop_subagent", session="GliGli", tool_id="t2")
        self.assertEqual(res["target"]["subagent"]["active_index"], 2)

    async def test_terminal_session_subagent_cannot_be_stopped_alone(self):
        folder = self.home / ".claude" / "projects" / sessions.project_slug(self.terminal[0].cwd) \
            / "s-elan" / "subagents"
        folder.mkdir(parents=True)
        (folder.parent.parent / "s-elan.jsonl").write_text("")
        (folder / "agent-z1.meta.json").write_text(
            '{"description": "Fouille", "toolUseId": "tz", "finished": false}')
        res = await self.call("jarvis.subagents", session="Élan")
        self.assertEqual(res["subagents"][0]["task_id"], "z1")
        with self.assertRaises(rpc.RpcError) as e:
            await self.call("jarvis.stop_subagent", session="Élan", confirme=True)
        self.assertEqual(e.exception.code, "refuse")

    # ---- sessions --------------------------------------------------------------------------

    async def test_stop_local_chat_session(self):
        res = await self.call("jarvis.stop_session", session="sonde")
        self.assertFalse(res["done"])
        self.assertEqual(res["question"], "Arrêter la session Sonde sur Serveur CCS (au repos) ?")
        self.assertIn("cn-1", self.near_hub.chats)
        res = await self.call("jarvis.stop_session", session="sonde", confirme=True)
        self.assertTrue(res["done"])
        self.assertNotIn("cn-1", self.near_hub.chats)
        self.assertTrue(self.near_engine.stopped)

    async def test_stop_terminal_session(self):
        await self.call("jarvis.stop_session", session="elan", confirme=True)
        self.assertEqual(self.terminated, [(777, "99")])

    async def test_stop_far_session_mentions_running_subagents(self):
        res = await self.call("jarvis.stop_session", session="GliGli")
        self.assertIn("avec 2 sous-agent(s) en cours", res["question"])
        await self.call("jarvis.stop_session", session="GliGli", confirm=True)
        self.assertNotIn("cf-1", self.far_hub.chats)

    async def test_start_session_on_the_machine_that_has_the_project(self):
        res = await self.call("jarvis.start_session", project="gli gli")
        self.assertEqual((res["machine"], res["project"], res["done"]), ("pc", "GliGli", True))
        self.assertIn(res["chat_id"], self.far_hub.chats)
        self.assertEqual(self.far_hub.chats[res["chat_id"]].conns, set())

    async def test_start_session_ambiguous_project_asks_the_machine(self):
        with self.assertRaises(rpc.RpcError) as e:
            await self.call("jarvis.start_session", project="Sonde")
        self.assertEqual(e.exception.code, "conflit")
        self.assertIn("Sur quelle machine", e.exception.message)
        res = await self.call("jarvis.start_session", project="Sonde", machine="serveur ccs")
        self.assertEqual(res["machine"], "vps")
        self.assertIn(res["chat_id"], self.near_hub.chats)

    async def test_start_session_sends_the_first_message(self):
        sent = []

        async def fake_send(_conn, params):
            sent.append(params)
            return {"ok": True}
        with mock.patch.object(self.near_hub, "send", fake_send):
            res = await self.call("jarvis.start_session", project="CCS", message="Fais le point")
        self.assertTrue(res["sent"])
        self.assertEqual(sent[0]["text"], "Fais le point")


class WordsTest(unittest.TestCase):
    def test_fold_and_score(self):
        self.assertEqual(bridge_pilot.fold("La session Gli-Gli"), "gli gli")
        self.assertEqual(bridge_pilot.fold("Élan"), "elan")
        self.assertEqual(bridge_pilot.score("gligli", "GliGli"), 100)
        self.assertEqual(bridge_pilot.score("gli", "GliGli"), 85)
        self.assertGreater(bridge_pilot.score("gligly", "GliGli"), 0)
        self.assertEqual(bridge_pilot.score("sonde", "GliGli"), 0)

    def test_ordinals(self):
        self.assertEqual(bridge_pilot.ordinal("Première"), 1)
        self.assertEqual(bridge_pilot.ordinal("deuxième"), 2)
        self.assertEqual(bridge_pilot.ordinal("dernier"), -1)
        self.assertEqual(bridge_pilot.ordinal(3), 3)
        self.assertIsNone(bridge_pilot.ordinal(None))
        for bad in (0, True, "plusieurs"):
            with self.assertRaises(rpc.RpcError):
                bridge_pilot.ordinal(bad)
        self.assertEqual(bridge_pilot.pick(["a", "b", "c"], -1), "c")
        self.assertIsNone(bridge_pilot.pick(["a"], 2))


if __name__ == "__main__":
    unittest.main()
