"""Travaux du calcul réparti : registre, places par machine, file d'attente, départ la nuit,
arrêt, CLI et réglages du client Ricochet."""

import io
import json
import os
import stat
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from ccs_app import cli, distant, distant_jobs as jobs
from tests.helpers import write
from tests.test_distant import DistantCase, FakeRun, opener

ROOT = Path(__file__).resolve().parent.parent
NOON = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc).timestamp()


def sleeper():
    p = subprocess.Popen(["sleep", "30"])
    return p


REAL_MESH_JOIN = distant.mesh_join

class JobsCase(DistantCase):
    def setUp(self):
        super().setUp()
        tz = mock.patch.dict(os.environ, {"TZ": "UTC"})
        tz.start()
        self.addCleanup(tz.stop)
        self.procs = []
        self.addCleanup(self._kill)

    def _kill(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()

    def busy(self, machine, state="running"):
        """Un travail qui occupe une place sur `machine` (son processus est vivant)."""
        p = sleeper()
        self.procs.append(p)
        jid = jobs.create(["sleep", "30"], self.project, pid=p.pid)
        jobs.update(jid, state=state, machine=machine, started=time.time())
        return jid, p

    def launch(self, command, **kw):
        said = []
        code = distant.launch(command, run=kw.pop("run", FakeRun()), say=said.append,
                              opener=opener(), cwd=self.project, **kw)
        return code, said


class TestRegistry(JobsCase):
    def test_create_update_finish_and_order(self):
        a = jobs.create(["flutter", "build", "apk"], self.project, machine="lp-work", tool="flutter")
        b = jobs.create(["make test"], self.project)
        job = jobs.get(a)
        self.assertRegex(a, r"^[0-9a-f]{6}$")
        self.assertEqual(set(job), {"id", "command", "text", "cwd", "machine", "tool", "state", "code",
                                    "created", "started", "ended", "when", "not_before", "pid",
                                    "detached", "log", "why"})
        self.assertEqual((job["text"], job["state"], job["pid"], job["log"]),
                         ("flutter build apk", "waiting", os.getpid(), ""))
        self.assertEqual(jobs.get(b)["text"], "make test")
        jobs.finish(a, "done", 0)
        jobs.finish(a, "failed", 3)  # un travail fini le reste
        self.assertEqual((jobs.get(a)["state"], jobs.get(a)["code"]), ("done", 0))
        self.assertEqual([j["id"] for j in jobs.list_jobs()], [b, a], "actifs d'abord")
        self.assertIsNone(jobs.get("../x"))
        self.assertEqual(oct(stat.S_IMODE(jobs._path(a).stat().st_mode)), "0o600")

    def test_dead_process_is_shown_stopped(self):
        p = subprocess.Popen(["true"])
        p.wait()
        jid = jobs.create(["x"], self.project, pid=p.pid)
        self.assertEqual((jobs.get(jid)["state"], jobs.get(jid)["why"]), ("stopped", "processus disparu"))
        self.assertFalse(jobs.stop(jid))

    def test_old_french_states_on_disk_are_read(self):
        """Fichiers écrits avant la 1.0.0 : états français convertis à la lecture."""
        jid = jobs.create(["x"], self.project)
        path = jobs._path(jid)
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(state="échec", code=2)
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(jobs.get(jid)["state"], "failed")
        self.assertEqual(jobs.label("failed"), "échec")
        self.assertEqual(jobs.legacy_view(jobs.get(jid))["state"], "échec")
        jobs.update(jid, state="en cours")   # un ancien appelant
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "running")

    def test_old_finished_jobs_are_pruned(self):
        old = time.time() - 3 * 86400
        ids = []
        for i in range(35):
            jid = jobs.create(["x"], self.project, now=lambda: old + i)
            jobs.finish(jid, "done", 0, now=lambda: old + i)
            ids.append(jid)
        recent = jobs.create(["y"], self.project)
        jobs.finish(recent, "done", 0)
        jobs.create(["z"], self.project)  # nettoie en passant
        left = {p.stem for p in jobs.jobs_dir().glob("*.json")}
        self.assertEqual(len(left), 31, "30 finis + 1 actif")
        self.assertNotIn(ids[0], left)
        self.assertIn(recent, left)
        self.assertEqual(len(jobs.list_jobs()), 30)

    def test_read_log_tail(self):
        jid = jobs.create(["x"], self.project, detached=True)
        self.assertEqual(jobs.read_log(jid), "")
        Path(jobs.get(jid)["log"]).write_text("début\n" + "x" * 100 + "\nfin\n")
        self.assertEqual(jobs.read_log(jid, tail=4), "fin\n")
        self.assertTrue(jobs.read_log(jid).startswith("début"))
        self.assertEqual(jobs.read_log("../../etc/passwd"), "")


class TestSlots(JobsCase):
    def test_reserve_counts_running_jobs_of_the_machine(self):
        self.busy("lp-work")
        self.busy("lp-work", state="sending")
        self.busy("portable")
        jid = jobs.create(["x"], self.project)
        self.assertEqual(jobs.reserve(jid, "lp-work", 2), (False, 2))
        self.assertEqual(jobs.reserve(jid, "lp-work", 3), (True, 2))
        self.assertEqual((jobs.get(jid)["state"], jobs.get(jid)["machine"]), ("sending", "lp-work"))
        self.assertEqual(jobs.counts()["lp-work"], {"running": 3, "waiting": 0})

    def test_places_hold_between_processes(self):
        """Quatre processus pour deux places : jamais plus de deux à la fois."""
        script = ("import json, sys, time\n"
                  "from ccs_app import distant_jobs as j\n"
                  "jid = j.create(['x'], '/tmp')\n"
                  "while not j.reserve(jid, 'lp-work', 2)[0]:\n"
                  "    time.sleep(0.01)\n"
                  "t0 = time.time(); time.sleep(0.4); t1 = time.time()\n"
                  "j.finish(jid, 'fini', 0)\n"
                  "print(json.dumps([t0, t1]))\n")
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        procs = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True,
                                  env=env) for _ in range(4)]
        spans = [json.loads(p.communicate(timeout=30)[0]) for p in procs]
        most = max(sum(1 for s, e in spans if s <= t < e) for t, _ in spans)
        self.assertEqual(most, 2)
        self.assertEqual({j["state"] for j in jobs.list_jobs()}, {"done"})

    def test_launch_skips_a_full_machine(self):
        write(distant.overrides_path(), "[machines.portable]\nlimite = 1\n")
        self.busy("portable")
        code, said = self.launch(["./build.sh"])
        self.assertEqual(code, 0)
        self.assertIn("lp-work", said[0], "portable (la moins chargée) est pleine")

    def test_launch_waits_for_a_place_then_goes(self):
        write(distant.overrides_path(), "[machines.lp-work]\nlimite = 1\n")
        other, proc = self.busy("lp-work")
        states = []
        real_update = jobs.update

        def update(jid, **fields):
            if "state" in fields:
                states.append(fields["state"])
            return real_update(jid, **fields)

        def sleep(_):  # pendant l'attente, l'autre travail se termine
            jobs.finish(other, "done", 0)
        with mock.patch.object(jobs, "update", update):
            code, said = self.launch(["flutter", "build", "apk"], sleep=sleep)
        self.assertEqual(code, 0)
        self.assertIn("en attente d'une place sur lp-work (1/1)", said[0])
        self.assertEqual(states, ["waiting", "running"])
        job = jobs.list_jobs()[0]
        self.assertEqual((job["state"], job["code"], job["machine"]), ("done", 0, "lp-work"))
        self.assertIsNotNone(job["started"])

    def test_failure_and_errors_are_recorded(self):
        run = FakeRun()
        real = run.__call__

        def failing(argv, **kw):
            r = real(argv, **kw)
            if argv[0] == "ssh" and "exec bash -c" in argv[-1]:
                r.returncode = 3
            return r
        code, _ = self.launch(["flutter test"], run=failing)
        self.assertEqual(code, 3)
        job = jobs.list_jobs()[0]
        self.assertEqual((job["state"], job["code"], job["why"]), ("failed", 3, "la commande a renvoyé 3"))
        with self.assertRaises(distant.DistantError):
            self.launch(["x"], machine="vieux")
        self.assertEqual(jobs.list_jobs()[0]["state"], "failed")
        self.assertIn("vieux", jobs.list_jobs()[0]["why"])


class TestWhen(JobsCase):
    def test_schedule(self):
        self.assertEqual(distant.schedule("", NOON), (None, ""))
        at, why = distant.schedule("nuit", NOON)
        self.assertEqual(datetime.fromtimestamp(at, timezone.utc).strftime("%d %H:%M"), "19 23:00")
        self.assertEqual(why, "programmé pour la nuit, à 23:00")
        self.assertEqual(distant.schedule("nuit", NOON + 14 * 3600), (None, ""), "déjà la nuit")
        at, why = distant.schedule("08:30", NOON)
        self.assertEqual(datetime.fromtimestamp(at, timezone.utc).strftime("%d %H:%M"), "20 08:30")
        self.assertEqual(why, "programmé à 08:30")
        with self.assertRaisesRegex(distant.DistantError, "HH:MM"):
            distant.schedule("25:00", NOON)

    def test_night_follows_the_tasks_settings(self):
        from ccs_app import settings
        write(settings.settings_path(), {"tasks": {"night": {"start": "01:30", "end": "05:00"}}})
        at, why = distant.schedule("nuit", NOON)
        self.assertEqual(datetime.fromtimestamp(at, timezone.utc).strftime("%d %H:%M"), "20 01:30")
        self.assertIn("01:30", why)

    def test_launch_waits_for_the_night(self):
        clock = [NOON]
        seen = []

        def sleep(s):
            seen.append(jobs.list_jobs()[0]["state"])
            clock[0] += s
        code, said = self.launch(["flutter", "build"], when="nuit", now=lambda: clock[0], sleep=sleep)
        self.assertEqual(code, 0)
        self.assertIn("programmé pour la nuit, à 23:00", said[0])
        self.assertEqual(set(seen), {"scheduled"})
        self.assertGreaterEqual(clock[0], NOON + 11 * 3600)
        job = jobs.list_jobs()[0]
        self.assertEqual((job["state"], job["when"]), ("done", "nuit"))


class TestStop(JobsCase):
    def test_stop_a_waiting_job_in_another_process(self):
        p = sleeper()
        self.procs.append(p)
        jid = jobs.create(["x"], self.project, pid=p.pid)
        self.assertTrue(jobs.stop(jid))
        self.assertEqual(p.wait(timeout=5), -15)
        job = jobs.get(jid)
        self.assertEqual((job["state"], job["why"]), ("stopped", "arrêté avant le départ"))
        self.assertIsNotNone(job["ended"])
        self.assertFalse(jobs.stop(jid))
        self.assertFalse(jobs.stop("abcdef"))

    def test_stop_a_running_job_sends_sigterm(self):
        jid, p = self.busy("lp-work")
        self.assertTrue(jobs.stop(jid))
        self.assertEqual(p.wait(timeout=5), -15)
        self.assertEqual(jobs.get(jid)["state"], "stopped")

    def test_stopping_while_queued_ends_the_launch(self):
        write(distant.overrides_path(), "[machines.lp-work]\nlimite = 1\n")
        self.busy("lp-work")

        def sleep(_):
            mine = next(j for j in jobs.list_jobs() if j["text"] == "flutter build")
            jobs.stop(mine["id"])
        run = FakeRun()
        code, said = self.launch(["flutter", "build"], sleep=sleep, run=run)
        self.assertEqual(code, 130)
        self.assertFalse([a for a in run.calls if a[0] == "rsync"], "rien n'est parti")
        mine = next(j for j in jobs.list_jobs() if j["text"] == "flutter build")
        self.assertEqual(mine["state"], "stopped")

    def test_sigterm_during_the_command_stops_it(self):
        def interrupted(argv, **kw):
            if argv[0] == "ssh" and "setsid" in argv[-1]:
                raise KeyboardInterrupt
            return FakeRun()(argv, **kw)
        code, _ = self.launch(["flutter test"], run=interrupted)
        self.assertEqual(code, 130)
        self.assertEqual((jobs.list_jobs()[0]["state"], jobs.list_jobs()[0]["code"]), ("stopped", 130))


class TestDetached(JobsCase):
    def test_start_spawns_a_detached_runner(self):
        calls = []

        def popen(argv, **kw):
            calls.append((argv, kw))
            return mock.Mock(pid=4242)
        jid = jobs.start(["flutter", "build", "apk"], str(self.project), machine="lp-work",
                         when="nuit", popen=popen)
        argv, kw = calls[0]
        self.assertEqual(argv[3:], ["distant", "lancer", "--detache", "--travail", jid, "--machine",
                                    "lp-work", "--quand", "nuit", "--", "flutter", "build", "apk"])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(kw["cwd"], str(self.project))
        job = jobs.get(jid)
        self.assertEqual((job["pid"], job["detached"], job["when"]), (4242, True, "nuit"))
        self.assertTrue(job["log"].endswith(f"{jid}.log"))

    def test_real_detached_run_records_its_failure_in_the_log(self):
        write(distant.client_path(), 'relais = "http://127.0.0.1:9"\njeton = "secret"\n')
        jid = jobs.start(["echo", "bonjour"], str(self.project))
        deadline = time.monotonic() + 30
        while jobs.get(jid)["state"] in jobs.ACTIVE and time.monotonic() < deadline:
            time.sleep(0.1)
        job = jobs.get(jid)
        self.assertEqual(job["state"], "failed")
        self.assertIn("injoignable", job["why"])
        self.assertIn("injoignable", jobs.read_log(jid))
        self.assertNotIn("secret", jobs.read_log(jid))


class TestCli(JobsCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_travaux_journal_arreter(self):
        code, out, _ = self.run_cli("distant", "travaux")
        self.assertEqual((code, out.strip()), (0, "Aucun travail."))
        jid, p = self.busy("lp-work")
        done = jobs.create(["flutter", "test"], self.project, detached=True)
        jobs.finish(done, "échec", 1, "la commande a renvoyé 1")
        Path(jobs.get(done)["log"]).write_text("sortie\n")
        code, out, _ = self.run_cli("distant", "travaux")
        self.assertIn(jid, out)
        self.assertIn("en cours", out)
        self.assertIn("échec (1)", out)
        self.assertIn("la commande a renvoyé 1", out)
        self.assertLess(out.index(jid), out.index(done))
        self.assertEqual(self.run_cli("distant", "journal", done)[1], "sortie\n")
        self.assertIn("Pas de journal", self.run_cli("distant", "journal", jid)[1])
        self.assertEqual(self.run_cli("distant", "journal", "abcdef")[0], 1)
        code, out, _ = self.run_cli("distant", "arreter", jid)
        self.assertEqual(code, 0)
        self.assertEqual(p.wait(timeout=5), -15)
        self.assertEqual(self.run_cli("distant", "arreter", done)[0], 1)

    def test_lancer_detache_and_quand(self):
        with mock.patch.object(jobs, "start", return_value="abc123") as start:
            code, out, _ = self.run_cli("distant", "lancer", "--detache", "--quand", "nuit",
                                        "--outil", "flutter", "--", "flutter", "test")
        self.assertEqual(code, 0)
        self.assertIn("abc123", out)
        start.assert_called_once_with(["flutter", "test"], os.getcwd(), machine=None, when="nuit",
                                      tool="flutter", fetch=[], include=[], with_git=False)
        code, _, err = self.run_cli("distant", "lancer", "--quand", "midi", "--", "x")
        self.assertEqual(code, 1)
        self.assertIn("HH:MM", err)
        with mock.patch("ccs_app.distant.launch", return_value=0) as launch:
            self.run_cli("distant", "lancer", "--detache", "--travail", "abc123", "--", "x")
        self.assertEqual(launch.call_args.kwargs["job_id"], "abc123")
        self.assertTrue(launch.call_args.kwargs["detached"])

    def test_hint_mentions_parallel_and_night(self):
        self.assertIn("--when night", distant.HINT)
        self.assertIn("parallèle", distant.HINT)


class TestClientSettings(JobsCase):
    def test_settings_never_show_the_token(self):
        write(distant.overrides_path(), '[machines.lp-work]\nutilisateur = "c"\nlimite = 3\n'
                                        '[machines.portable]\nlimite = 99\n')
        s = distant.client_settings()
        new = {"relay": "https://r.example/", "token_set": True, "path": str(distant.client_path()),
               "default_limit": 2, "limits": {"lp-work": 3}, "operator_set": False}
        old = {"relais": "https://r.example/", "jeton_defini": True, "chemin": str(distant.client_path()),
               "limite_defaut": 2, "limites": {"lp-work": 3}}   # compatibilité 1.x
        self.assertEqual(s, {**new, **old})
        self.assertNotIn("secret", json.dumps(s))

    def test_save_client_keeps_the_missing_value_and_mode_600(self):
        distant.client_path().chmod(0o644)
        distant.save_client(relay="https://autre.example/")
        self.assertEqual(distant.load_client(), {"relais": "https://autre.example", "jeton": "secret"})
        self.assertEqual(stat.S_IMODE(distant.client_path().stat().st_mode), 0o600)
        distant.save_client(token="neuf")
        self.assertEqual(distant.load_client()["jeton"], "neuf")
        with self.assertRaises(distant.DistantError):
            distant.save_client(relay="ftp://x")
        with self.assertRaises(distant.DistantError):
            distant.save_client(token=" ")
        distant.client_path().unlink()
        distant.save_client(relay="https://r.example", token="j")
        self.assertEqual(stat.S_IMODE(distant.client_path().stat().st_mode), 0o600)

    def test_set_limit_keeps_the_rest(self):
        write(distant.overrides_path(), '[machines.lp-work]\nutilisateur = "charles"\nport = 2244\n')
        distant.set_limit("lp-work", 3)
        distant.set_limit("portable", 1)
        over = distant.load_overrides()
        self.assertEqual(over["lp-work"], {"user": "charles", "port": 2244, "limit": 3})
        self.assertEqual(distant.limit_for("portable", over), 1)
        self.assertEqual(distant.limit_for("autre", over), 2)
        for bad in (0, 9, "3", True):
            with self.assertRaises(distant.DistantError):
                distant.set_limit("lp-work", bad)
        with self.assertRaises(distant.DistantError):
            distant.set_limit("../x", 2)

    def test_overview(self):
        write(distant.overrides_path(), "[machines.lp-work]\nlimite = 3\n")
        distant.inventory(distant.parse_machines(distant_api())[1], {}, run=FakeRun())
        self.busy("lp-work")
        jobs.create(["x"], self.project, machine="lp-work")
        o = distant.machines_overview(fetch=lambda: distant.parse_machines(distant_api()))
        self.assertEqual((o["configured"], o["message"]), (True, ""))
        pc = next(m for m in o["machines"] if m["id"] == "lp-work")
        self.assertEqual((pc["tools"], pc["limit"], pc["running"], pc["waiting"], pc["tunnel"]),
                         (["flutter"], 3, 1, 1, True))
        self.assertEqual(o["machines"][0]["tools"], [])

        def boom():
            raise distant.DistantError("Relais Ricochet injoignable")
        o = distant.machines_overview(fetch=boom)
        self.assertEqual((o["machines"], o["message"]), ([], "Relais Ricochet injoignable"))
        with mock.patch.object(distant, "configured", return_value=False):
            self.assertIn("Calcul réparti", distant.machines_overview()["message"])


def distant_api():
    from tests.test_distant import API
    return API


if __name__ == "__main__":
    unittest.main()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestAddMachine(JobsCase):
    def setUp(self):
        super().setUp()
        write(distant.client_path(), 'relais = "https://r.example"\njeton = "secret"\n'
                                     'jeton_operateur = "operateur"\n')
        ssh = self.home / ".ssh"
        write(ssh / "id_rsa", "privée")
        write(ssh / "id_rsa.pub", "ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB moi@vps\n")
        self.requests = []
        # jamais de vraie clé Headscale pendant les tests, même sur le serveur du réseau
        p = mock.patch.object(distant, "mesh_join", lambda machine_id, key=None: None)
        p.start()
        self.addCleanup(p.stop)

    def opener(self, status=201, body=None):
        def open_(req, timeout=None):
            self.requests.append(req)
            if status != 201:
                raise distant.urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(b"non"))
            return FakeResponse(json.dumps(body or {"id": "pc-salon", "jeton": "j",
                                                    "lien": "/rejoindre/abc", "expire_s": 900}).encode())
        return open_

    def test_creates_the_machine_and_remembers_the_user(self):
        distant.set_limit("pc-salon", 5)
        r = distant.add_machine("pc-salon", name="Salon", user="charles", limit=3, opener=self.opener())
        self.assertEqual(r, {"id": "pc-salon", "command": "curl -fsSL https://r.example/rejoindre/abc | sudo sh",
                             "mesh": False, "full": False, "expires_s": 900})
        req = self.requests[0]
        self.assertEqual((req.full_url, req.get_method()), ("https://r.example/api/machines", "POST"))
        self.assertEqual(req.get_header("Authorization"), "Bearer operateur")
        self.assertEqual(json.loads(req.data), {"id": "pc-salon", "nom": "Salon", "utilisateur": "charles",
                                                "ports": [22], "cles_ssh": ["ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB moi@vps"]})
        self.assertEqual(distant.load_overrides()["pc-salon"], {"limit": 3, "user": "charles"})
        self.assertTrue(distant.client_settings()["operator_set"])

    def test_line_also_joins_the_mesh(self):
        r = distant.add_machine("PC_Salon", user="charles", opener=self.opener(),
                                mesh=lambda mid: REAL_MESH_JOIN(mid, key="cle123"))
        self.assertTrue(r["mesh"])
        self.assertTrue(r["command"].startswith("curl -fsSL https://r.example/rejoindre/abc | sudo sh && sudo sh -c "))
        self.assertIn("--authkey cle123", r["command"])
        self.assertIn("--hostname pc-salon", r["command"])
        self.assertEqual(distant.load_overrides()["PC_Salon"]["reseau"], "pc-salon")

    def test_full_line_installs_ccs_and_claude(self):
        r = distant.add_machine("pc", user="charles", opener=self.opener(), mesh=lambda mid: None, full=True)
        self.assertTrue(r["full"])
        self.assertTrue(r["command"].endswith(" && " + distant.FULL_INSTALL))
        self.assertIn("installer.sh | sudo sh -s -- ccs", r["command"])
        self.assertIn("claude.ai/install.sh | bash", r["command"])
        r = distant.add_machine("pc2", user="charles", opener=self.opener(), mesh=lambda mid: None)
        self.assertNotIn("claude.ai", r["command"])

    def test_refusals(self):
        for kw in ({"machine_id": "a.b", "user": "c"}, {"machine_id": "pc", "user": ""},
                   {"machine_id": "pc", "user": "Charles"}, {"machine_id": "pc", "user": "c", "limit": 9}):
            with self.assertRaises(distant.DistantError):
                distant.add_machine(opener=self.opener(), **kw)
        with self.assertRaisesRegex(distant.DistantError, "existe déjà"):
            distant.add_machine("pc", user="c", opener=self.opener(409))
        with self.assertRaisesRegex(distant.DistantError, "0.6.0"):
            distant.add_machine("pc", user="c", opener=self.opener(body={"id": "pc", "jeton": "j"}))
        write(distant.client_path(), 'relais = "https://r.example"\njeton = "secret"\n')
        with self.assertRaisesRegex(distant.DistantError, "jeton_operateur"):
            distant.add_machine("pc", user="c", opener=self.opener())
        self.assertEqual(distant.load_overrides(), {})

    def test_creates_a_key_when_there_is_none(self):
        for f in (self.home / ".ssh").iterdir():
            f.unlink()

        def keygen(argv, **kw):
            path = Path(argv[argv.index("-f") + 1])
            write(path, "privée")
            write(Path(str(path) + ".pub"), "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAInouvelle ccs@ici\n")
        distant.add_machine("pc", user="c", opener=self.opener(), run=keygen)
        self.assertEqual(json.loads(self.requests[0].data)["cles_ssh"],
                         ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAInouvelle ccs@ici"])

    def test_cli(self):
        out = io.StringIO()
        with mock.patch.object(distant, "add_machine", return_value={
                "id": "pc", "command": "curl -fsSL https://r/rejoindre/x | sudo sh", "expires_s": 900}) as add, \
                redirect_stdout(out):
            code = cli.main(["distant", "ajouter", "pc", "--utilisateur", "charles", "--limite", "2"])
        self.assertEqual(code, 0)
        add.assert_called_once_with("pc", name=None, user="charles", limit=2, full=False)
        self.assertIn("| sudo sh", out.getvalue())
        self.assertIn("15 min", out.getvalue())
