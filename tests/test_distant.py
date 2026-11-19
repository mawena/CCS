import io
import json
import os
import shlex
import subprocess
import tempfile
import time
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from ccs_app import cli, distant
from tests.helpers import HomeTestCase, write

API = [
    {"id": "mawena-cloud", "nom": "VPS", "connectee": True,
     "info": {"nom_hote": "ici", "tunnels": [], "version_agent": "0.3.0"},
     "etat": {"nombre_coeurs": 6, "charge": [0.2, 0.1, 0.1],
              "memoire_utilisee": 4 << 30, "memoire_totale": 11 << 30}},
    {"id": "pc-bureau", "nom": None, "connectee": True,
     "info": {"nom_hote": "bureau", "tunnels": [22], "version_agent": "0.3.0"},
     "etat": {"nombre_coeurs": 16, "charge": [8.0, 1, 1],
              "memoire_utilisee": 8 << 30, "memoire_totale": 32 << 30}},
    {"id": "portable", "connectee": True,
     "info": {"nom_hote": "portable", "tunnels": [2222]},
     "etat": {"nombre_coeurs": 8, "charge": [0.8, 1, 1]}},
    {"id": "vieux", "connectee": False, "info": None, "etat": None},
]
PROBE = "bienvenue\nCCS_PATH=/home/c/flutter/bin:/usr/bin\nCCS_OUTIL=flutter=/home/c/flutter/bin/flutter\n"


class FakeRun:
    """Remplace subprocess.run : note les commandes, répond comme les machines."""

    def __init__(self, tools=None, codes=None):
        self.calls = []
        self.tools = tools or {"pc-bureau": PROBE, "portable": "CCS_PATH=/usr/bin\n"}
        self.codes = codes or {}

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if argv[0] == "rsync":
            return types.SimpleNamespace(returncode=self.codes.get("rsync", 0), stdout="", stderr="")
        host, command = argv[-2].split("@")[-1], argv[-1]
        if "CCS_PATH" in command:
            out = self.tools.get(host)
            if out is None:
                return types.SimpleNamespace(returncode=255, stdout="", stderr="Permission denied\n")
            return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
        if "type -P" in command:
            found = "cargo" in command and host == "portable"
            return types.SimpleNamespace(returncode=0 if found else 1,
                                         stdout="/usr/bin/cargo\n" if found else "", stderr="")
        return types.SimpleNamespace(returncode=self.codes.get("ssh", 0), stdout="", stderr="")

    def remote(self):
        return [(a[-2], a[-1]) for a in self.calls if a[0] == "ssh"]


def opener(payload=API):
    def open_(req, timeout=0):
        open_.request = req
        return io.BytesIO(json.dumps(payload).encode())
    return open_


class DistantCase(HomeTestCase):
    def setUp(self):
        super().setUp()
        write(self.home / ".config/ricochet/client.toml",
              'relais = "https://r.example/"\njeton = "secret"\n')
        for name, value in (("shutil.which", lambda n: "/usr/bin/" + n),
                            ("socket.gethostname", lambda: "ici")):
            p = mock.patch(f"ccs_app.distant.{name}", value)
            p.start()
            self.addCleanup(p.stop)
        self.project = self.home / "Work/appli"
        (self.project / "lib").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)

    def machines(self):
        return distant.parse_machines(API)


class TestSettings(DistantCase):
    def test_client_and_errors(self):
        self.assertEqual(distant.load_client(), {"relais": "https://r.example", "jeton": "secret"})
        self.assertTrue(distant.configured())
        self.assertIn("ccs distant lancer", distant.hint())
        distant.client_path().unlink()
        self.assertIsNone(distant.hint())
        with self.assertRaisesRegex(distant.DistantError, "client.toml"):
            distant.load_client()
        write(distant.client_path(), 'relais = "ws://r"\njeton = "x"\n')
        with self.assertRaises(distant.DistantError):
            distant.load_client()

    def test_fetch_machines_sends_the_token(self):
        o = opener()
        machines = distant.fetch_machines(opener=o)
        self.assertEqual(o.request.full_url, "https://r.example/api/machines")
        self.assertEqual(o.request.get_header("Authorization"), "Bearer secret")
        pc = machines[1]
        self.assertEqual((pc.id, pc.online, pc.ports, pc.cores, pc.load), ("pc-bureau", True, [22], 16, 8.0))
        self.assertTrue(machines[0].local)
        self.assertFalse(machines[3].online)

    def test_ssh_options_and_overrides(self):
        pc, portable = self.machines()[1:3]
        opts = distant.ssh_options(pc, {})
        self.assertIn(f"ProxyCommand=/usr/bin/ricochet-agent tunnel %h --port 22 --config {distant.client_path()}", opts)
        self.assertIn("HostKeyAlias=ricochet-pc-bureau", opts)
        self.assertIn("BatchMode=yes", opts)
        self.assertEqual(distant.ssh_port(portable, {}), 2222)
        write(distant.overrides_path(), '[machines.pc-bureau]\nutilisateur = "charles"\nport = 2244\n')
        over = distant.load_overrides()
        self.assertEqual(distant.target(pc, over), "charles@pc-bureau")
        self.assertEqual(distant.ssh_port(pc, over), 2244)
        self.assertEqual(distant.target(portable, over), "portable")
        with self.assertRaisesRegex(distant.DistantError, "tunnel"):
            distant.ssh_options(self.machines()[0], {})


class TestChoice(DistantCase):
    def test_inventory_is_parsed_and_cached(self):
        run = FakeRun()
        pc = self.machines()[1]
        inv = distant.inventory(pc, {}, run=run)
        self.assertEqual(inv["path"], "/home/c/flutter/bin:/usr/bin")
        self.assertEqual(inv["outils"], {"flutter": "/home/c/flutter/bin/flutter"})
        distant.inventory(pc, {}, run=run)
        self.assertEqual(len(run.calls), 1, "gardé une heure")
        distant.inventory(pc, {}, run=run, now=lambda: 1e12)
        self.assertEqual(len(run.calls), 2)

    def test_machine_with_the_tool_then_least_loaded(self):
        run = FakeRun()
        m, _ = distant.choose(self.machines(), {}, tool="flutter", run=run)
        self.assertEqual(m.id, "pc-bureau", "seule machine avec flutter, malgré sa charge")
        m, _ = distant.choose(self.machines(), {}, tool=None, run=run)
        self.assertEqual(m.id, "portable", "la moins chargée par cœur, hors cette machine")
        m, _ = distant.choose(self.machines(), {}, tool="cargo", run=run)
        self.assertEqual(m.id, "portable", "outil hors liste cherché à la demande")

    def test_refusals_say_why(self):
        run = FakeRun(tools={"portable": "CCS_PATH=/usr/bin\n"})
        with self.assertRaises(distant.DistantError) as ctx:
            distant.choose(self.machines(), {}, tool="flutter", run=run)
        text = str(ctx.exception)
        for part in ("avec flutter", "portable : pas de flutter", "pc-bureau : SSH refusé", "vieux : hors ligne",
                     "mawena-cloud : c'est cette machine"):
            self.assertIn(part, text)
        with self.assertRaisesRegex(distant.DistantError, "Machine inconnue : x"):
            distant.choose(self.machines(), {}, wanted="x", run=run)
        with self.assertRaisesRegex(distant.DistantError, "éteinte"):
            distant.choose(self.machines(), {}, wanted="vieux", run=run)

    def test_wanted_tool(self):
        self.assertEqual(distant.wanted_tool(["flutter", "build", "apk"]), "flutter")
        self.assertEqual(distant.wanted_tool(["cargo test && cargo build"]), "cargo")
        self.assertIsNone(distant.wanted_tool(["cd app && flutter build"]))
        self.assertIsNone(distant.wanted_tool(["./gradlew", "build"]))


class TestLaunch(DistantCase):
    def launch(self, run, command, **kw):
        said = []
        code = distant.launch(command, run=run, say=said.append, opener=opener(),
                              cwd=kw.pop("cwd", self.project), **kw)
        return code, said

    def test_sends_runs_and_fetches(self):
        run = FakeRun()
        (self.project / "app").mkdir()
        write(self.project / "app/.env", "X=1")
        code, said = self.launch(run, ["flutter", "build", "apk"], cwd=self.project / "app",
                                 fetch=["build/outputs"], include=[".env"])
        self.assertEqual(code, 0)
        root = distant.remote_dir(self.project.resolve())
        self.assertRegex(root, r"^\.cache/ccs-distant/appli-[0-9a-f]{8}$")
        send, fetch = [a for a in run.calls if a[0] == "rsync"]
        self.assertEqual(send[-2:], [f"{self.project.resolve()}/", f"pc-bureau:{root}/"])
        self.assertIn("--delete", send)
        self.assertIn("--exclude=/.git/", send)
        self.assertLess(send.index("--include=/app/.env"), send.index("--filter=:- .gitignore"))
        self.assertIn("--include=/app/", send)
        self.assertEqual(fetch[-2:], [f"pc-bureau:{root}/./app/build/outputs", f"{self.project.resolve()}/"])
        self.assertIn("-azR", fetch)
        host, command = run.remote()[-1]
        self.assertEqual(host, "pc-bureau")
        self.assertTrue(command.startswith("exec bash -c '"))
        self.assertTrue(command.endswith(f" ccs-distant {root}/app /home/c/flutter/bin:/usr/bin "
                                         "'flutter build apk'"))
        self.assertIn("pc-bureau", said[0])
        self.assertIn("build/outputs rapatrié", said[-1])

    def test_failure_keeps_the_exit_code_and_skips_fetch(self):
        run = FakeRun(codes={"ssh": 3})
        with self.assertRaisesRegex(distant.DistantError, "SSH refusé"):
            self.launch(run, ["flutter test"])
        # la commande échoue, pas la connexion : mkdir passe, la commande renvoie 3
        run = FakeRun()
        real = run.__call__

        def failing(argv, **kw):
            r = real(argv, **kw)
            if argv[0] == "ssh" and "exec bash -c" in argv[-1]:
                r.returncode = 3
            return r
        code, said = self.launch(failing, ["flutter test"], fetch=["build"])
        self.assertEqual(code, 3)
        self.assertFalse([a for a in run.calls if a[0] == "rsync" and "-azR" in a])
        self.assertIn("non rapatrié", said[-1])

    def test_fetch_and_include_stay_in_the_project(self):
        pc = self.machines()[1]
        root = self.project.resolve()
        with self.assertRaisesRegex(distant.DistantError, "hors du projet"):
            distant.fetch_argv(pc, {}, root, ".", "../ailleurs")
        self.assertEqual(distant.fetch_argv(pc, {}, root, "src", "../build/a.txt")[-2],
                         f"pc-bureau:{distant.remote_dir(root)}/./build/a.txt")
        with self.assertRaisesRegex(distant.DistantError, "hors du projet"):
            distant.include_rules(root, root, ["/etc/passwd"])
        (root / "secrets").mkdir()
        self.assertEqual(distant.include_rules(root, root, ["secrets"]), ["--include=/secrets/***"])
        self.assertNotIn("--exclude=/.git/", distant.send_argv(pc, {}, root, with_git=True))


class TestRemoteGuard(DistantCase):
    """Le garde distant, joué par un vrai bash comme le ferait sshd."""

    def start(self, line, tmp):
        work = Path(tmp) / "projet"
        work.mkdir()
        cmd = distant.remote_command(work, ".", {"path": os.environ["PATH"]}, [line])
        cmd = cmd.replace(shlex.quote(distant.remote_dir(work)), shlex.quote("projet"))
        env = dict(os.environ, HOME=tmp)
        return subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, env=env), work

    def test_exit_code_and_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, work = self.start("pwd; exit 4", tmp)
            out = p.stdout.read()  # entrée gardée ouverte, comme le fait ssh
            p.wait(timeout=10)
            p.stdin.close()
            p.stdout.close()
            self.assertEqual(p.returncode, 4)
            self.assertEqual(out.strip(), str(work))

    def test_closing_the_connection_stops_the_whole_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, work = self.start("sleep 30 & echo $! > enfant; sleep 30", tmp)
            deadline = time.monotonic() + 5
            while not (work / "enfant").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            child = int((work / "enfant").read_text())
            p.stdin.close()  # ce que fait ssh quand on l'interrompt
            p.wait(timeout=10)
            p.stdout.close()
            self.assertNotEqual(p.returncode, 0)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("le sous-processus distant tourne encore")

    def test_interrupt_is_reported(self):
        def interrupted(argv, **kw):
            if argv[0] == "ssh" and "setsid" in argv[-1]:
                raise KeyboardInterrupt
            return FakeRun()(argv, **kw)
        said = []
        code = distant.launch(["flutter test"], run=interrupted, say=said.append, opener=opener(),
                              cwd=self.project, fetch=["build"])
        self.assertEqual(code, 130)
        self.assertIn("interrompu", said[-1])


class TestCli(DistantCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_machines(self):
        with mock.patch("ccs_app.distant.urllib.request.urlopen", opener()), \
                mock.patch("ccs_app.distant.subprocess.run", FakeRun()):
            code, out, _ = self.run_cli("distant", "machines")
        self.assertEqual(code, 0)
        self.assertIn("mawena-cloud (VPS) : en ligne, charge 0.2 sur 6 cœurs, mémoire 4/11 Go — cette machine", out)
        self.assertIn("pc-bureau : en ligne, charge 8.0 sur 16 cœurs", out)
        self.assertIn("  outils : flutter", out)
        self.assertIn("vieux : hors ligne", out)

    def test_lancer_passes_everything_after_the_dashes(self):
        with mock.patch("ccs_app.distant.launch", return_value=7) as launch:
            code, _, _ = self.run_cli("distant", "lancer", "--machine", "pc-bureau", "--rapatrier", "build",
                                      "--", "flutter", "build", "apk", "--release")
        self.assertEqual(code, 7)
        launch.assert_called_once_with(["flutter", "build", "apk", "--release"], machine="pc-bureau", tool=None,
                                       fetch=["build"], include=[], with_git=False)

    def test_errors_are_plain(self):
        distant.client_path().unlink()
        code, _, err = self.run_cli("distant", "machines")
        self.assertEqual(code, 1)
        self.assertIn("Ricochet n'est pas réglé", err)


class TestChatHint(DistantCase):
    def test_chats_learn_about_the_other_machines(self):
        from ccs_app.chat_engine import ChatSession
        from ccs_app.chat_options import ChatOptions
        engine = ChatSession.__new__(ChatSession)
        engine._claude, engine.options, engine.session_id = "claude", ChatOptions(), None
        argv = engine._argv()
        self.assertEqual(argv[-2], "--append-system-prompt")
        self.assertIn("ccs distant lancer", argv[-1])
        distant.client_path().unlink()
        self.assertNotIn("--append-system-prompt", engine._argv())


if __name__ == "__main__":
    import unittest
    unittest.main()
