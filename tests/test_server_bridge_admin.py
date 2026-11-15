"""Pont : cartes de comptes, bilan de santé, tâches de nuit et téléphone (version web)."""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ccs_app import core, daemon, doctor, phone, settings, tasks
from ccs_app.server import bridge, bridge_admin, rpc
from tests.helpers import make_home


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AdminBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-badmin-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = make_home(self.tmp)
        env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("CLAUDE_CONFIG_DIR", "CCS_HOME"):
            os.environ.pop(var, None)
        self.sent = []

        def urlopen(req, timeout=None):
            self.sent.append(req)
            return FakeResponse()
        self.urlopen = urlopen
        sock = Path(self.tmp) / "b.sock"
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False, install_claude=False)
        self.admin = bridge_admin.AdminApi(self.bridge, urlopen=lambda *a, **k: self.urlopen(*a, **k))
        await self.bridge.start(sock)
        self.addAsyncCleanup(self.bridge.stop)
        self.c = rpc.RpcClient()
        await self.c.connect_unix(sock)
        self.addAsyncCleanup(self.c.close)
        await self.c.call("hello")

    def write_state(self, accounts, **extra):
        core.atomic_write_json(daemon.state_path(), {"accounts": accounts, **extra})

    # ---- cartes de comptes -----------------------------------------------------------

    async def test_cards_main_limits_status_and_details(self):
        soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.write_state([{
            "name": "perso", "email": "a@x.com", "org": "Org", "plan": "pro", "active": True,
            "error": None, "fetched_at": 1.0,
            "limits": [{"kind": "session", "label": "Session", "percent": 40, "resets_at": soon},
                       {"kind": "weekly_all", "label": "Semaine", "percent": 10, "resets_at": soon},
                       {"kind": "weekly_opus", "label": "Opus", "percent": 5, "resets_at": soon}],
            "forecast": {"verdict": "ok", "eta": None, "rate_per_min": 0.5, "minutes_before_reset": None},
            "pace": {"ideal": 50, "margin": 12.0, "per_day_budget": 14.0, "days_left": 3.0},
        }], best={"name": "perso", "reason": "le plus de marge"})
        r = await self.c.call("accounts.cards")
        card = next(c for c in r["cards"] if c["name"] == "perso")
        self.assertEqual([g["label"] for g in card["main"]], ["Session", "Semaine"])
        self.assertEqual([g["label"] for g in card["others"]], ["Opus"])
        self.assertTrue(card["main"][0]["reset"].startswith("réinitialisation"))
        self.assertEqual(card["status"]["kind"], "success")
        self.assertTrue(any("12 pts de marge" in t for t in card["details"]))
        self.assertTrue(card["color"].startswith("#"))
        self.assertEqual(r["best"]["name"], "perso")

    async def test_cards_error_is_friendly_and_raw_kept(self):
        self.write_state([{"name": "pro", "email": "b@y.com", "plan": "max", "active": False,
                           "error": 'HTTP 401: {"error":{"type":"authentication_error"}}',
                           "fetched_at": None, "limits": []}])
        r = await self.c.call("accounts.cards")
        card = next(c for c in r["cards"] if c["name"] == "pro")
        self.assertEqual(card["status"]["kind"], "error")
        self.assertIn("reconnecte", card["status"]["text"])
        self.assertNotIn("authentication_error", card["status"]["text"])
        self.assertIn("authentication_error", card["error_raw"])

    async def test_cards_without_state_lists_profiles(self):
        r = await self.c.call("accounts.cards")
        self.assertEqual(sorted(c["name"] for c in r["cards"]), ["perso", "pro"])
        self.assertTrue(all(c["main"] == [] for c in r["cards"]))

    async def test_chats_running_count_for_switch_warning(self):
        r = await self.c.call("accounts.cards")
        self.assertEqual(r["running_chats"], 0)

    # ---- bilan de santé --------------------------------------------------------------

    async def test_doctor_errors_first_with_command(self):
        checks = [doctor.Check("A", doctor.OK, "bon"),
                  doctor.Check("B", doctor.AVERTISSEMENT, "bof", "ccs fix"),
                  doctor.Check("C", doctor.ERREUR, "mal", "ccs repair")]
        with mock.patch.object(doctor, "run_checks", return_value=checks):
            r = await self.c.call("doctor.run")
        self.assertEqual([c["nom"] for c in r["checks"]], ["C", "B", "A"])
        self.assertEqual(r["checks"][0]["commande"], "ccs repair")
        self.assertEqual(r["errors"], 1)
        self.assertEqual(r["warnings"], 1)
        self.assertEqual(r["summary"], "1 erreur, 1 avertissement.")

    # ---- tâches ----------------------------------------------------------------------

    def add_task(self, message="Fais ceci"):
        return tasks.add(message, str(self.home))

    async def test_task_log_reads_readable_lines(self):
        t = self.add_task()
        p = tasks.journal_path(t.id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join([
            json.dumps({"type": "ccs", "text": "démarrage"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Bonjour"}]}}),
            json.dumps({"type": "result", "result": "fini"}),
        ]) + "\n")
        r = await self.c.call("tasks.log", id=t.id)
        self.assertEqual(r["task"]["id"], t.id)
        self.assertEqual(r["lines"], ["— démarrage", "Bonjour", "✓ fini"])
        self.assertIn("when", r)

    async def test_task_log_keeps_only_the_end(self):
        t = self.add_task()
        p = tasks.journal_path(t.id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps({"type": "raw", "text": f"ligne {i}"}) + "\n" for i in range(1000)))
        r = await self.c.call("tasks.log", id=t.id)
        self.assertLessEqual(len(r["lines"]), bridge_admin.LOG_LINES)
        self.assertEqual(r["lines"][-1], "ligne 999")
        self.assertTrue(r["truncated"])

    async def test_task_log_without_journal_and_unknown(self):
        t = self.add_task()
        r = await self.c.call("tasks.log", id=t.id)
        self.assertEqual(r["lines"], [])
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("tasks.log", id="999")
        self.assertEqual(cm.exception.code, "introuvable")
        with self.assertRaises(rpc.RpcError):
            await self.c.call("tasks.log", id="../../x")

    async def test_task_remove_finished_only(self):
        t = self.add_task()
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("tasks.remove", id=t.id)
        self.assertEqual(cm.exception.code, "invalide")
        tasks.cancel(t.id)
        await self.c.call("tasks.remove", id=t.id)
        self.assertIsNone(tasks.get(t.id))
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("tasks.remove", id=t.id)
        self.assertEqual(cm.exception.code, "introuvable")

    # ---- téléphone -------------------------------------------------------------------

    def set_phone(self, **kw):
        s = settings.load_settings()
        s["phone"].update(kw)
        settings.save_settings(s)

    async def test_phone_test_sends_and_never_logs_topic(self):
        self.set_phone(server="https://ntfy.example", topic="ccs-secretsecret1")
        with self.assertNoLogs("ccs", level="INFO"):
            r = await self.c.call("phone.test")
        self.assertTrue(r["ok"])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0].full_url, "https://ntfy.example/ccs-secretsecret1")

    async def test_phone_test_failure_is_reported(self):
        self.set_phone(server="https://ntfy.example", topic="ccs-secretsecret1")

        def boom(req, timeout=None):
            raise OSError("réseau")
        self.urlopen = boom
        r = await self.c.call("phone.test")
        self.assertFalse(r["ok"])
        self.assertIn("Envoi impossible", r["message"])

    async def test_phone_test_without_channel(self):
        r = await self.c.call("phone.test")
        self.assertFalse(r["ok"])
        self.assertEqual(self.sent, [])

    async def test_phone_new_topic_saves_and_qr(self):
        r = await self.c.call("phone.new_topic")
        self.assertTrue(phone.valid_topic(r["topic"]))
        self.assertEqual(settings.load_settings()["phone"]["topic"], r["topic"])
        q = await self.c.call("phone.qr")
        self.assertTrue(q["url"].endswith("/" + r["topic"]))
        self.assertTrue(q["image"].startswith("data:image/svg+xml;base64,"))

    async def test_phone_qr_needs_channel(self):
        with self.assertRaises(rpc.RpcError) as cm:
            await self.c.call("phone.qr")
        self.assertEqual(cm.exception.code, "invalide")


if __name__ == "__main__":
    unittest.main()
