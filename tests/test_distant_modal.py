import io
import json
import subprocess
import tarfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from ccs_app import cli, distant, distant_jobs, distant_modal
from tests.helpers import HomeTestCase, write


class FakePopen:
    """Faux lanceur : écrit le statut (et l'archive rapportée) comme modal_runner.py."""

    def __init__(self, status, produced=None):
        self.status, self.produced, self.argv, self.params = status, produced or {}, None, None
        self.returncode = 0

    def __call__(self, argv, **kw):
        self.argv = argv
        self.params = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        with tarfile.open(self.params["archive"]) as tar:
            self.sent = sorted(tar.getnames())
        if self.produced:
            work = Path(self.params["out"]).with_name("produit")
            with tarfile.open(self.params["out"], "w:gz") as tar:
                for name, text in self.produced.items():
                    write(work / name, text)
                    tar.add(str(work / name), arcname=name)
        Path(self.params["status"]).write_text(json.dumps(self.status), encoding="utf-8")
        return self

    def wait(self, timeout=None):
        return 0


class ModalTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.py = self.home / "modal-py"
        write(self.py, "#!/bin/sh\n")
        self.py.chmod(0o755)
        write(self.home / ".modal.toml", "[x]\n")
        self.proj = self.home / "projet"
        write(self.proj / "a.py", "print(1)\n")
        write(self.proj / "sous" / "b.txt", "b\n")
        write(self.proj / "secret.env", "x\n")
        write(self.proj / ".gitignore", "secret.env\n")
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)
        self.overrides = distant.Overrides({"modal": {"modal_python": str(self.py)}})

    def test_noms_et_cartes(self):
        self.assertTrue(distant_modal.is_modal("modal"))
        self.assertTrue(distant_modal.is_modal("modal:H100"))
        self.assertFalse(distant_modal.is_modal("lp-work"))
        self.assertFalse(distant_modal.is_modal(None))
        self.assertEqual(distant_modal.split("modal:H100"), "H100")
        self.assertIsNone(distant_modal.split("modal"))
        self.assertEqual(distant_modal.normalize_gpu("h100"), "H100")
        self.assertEqual(distant_modal.normalize_gpu("a100-80gb:2"), "A100-80GB:2")
        self.assertEqual(distant_modal.normalize_gpu("best"), distant_modal.BEST_GPU)
        self.assertIsNone(distant_modal.normalize_gpu("cpu"))
        self.assertIsNone(distant_modal.normalize_gpu(None))
        with self.assertRaises(distant_modal.ModalError):
            distant_modal.normalize_gpu("z9")
        with self.assertRaises(distant_modal.ModalError):
            distant_modal.normalize_gpu("T4:9")

    def test_pret_seulement_avec_python_et_jeton(self):
        conf = distant_modal.settings(self.overrides)
        self.assertTrue(distant_modal.configured(conf))
        (self.home / ".modal.toml").unlink()
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("MODAL_TOKEN_ID", None)
            self.assertFalse(distant_modal.configured(conf))
            self.assertIsNone(distant_modal.overview(self.overrides))

    def test_fichiers_envoyes_sans_les_ignores(self):
        files = distant_modal.project_files(self.proj)
        self.assertEqual(sorted(files), [".gitignore", "a.py", "sous/b.txt"])
        files = distant_modal.project_files(self.proj, include=["secret.env"], cwd=self.proj)
        self.assertIn("secret.env", files)
        with self.assertRaises(distant_modal.ModalError):
            distant_modal.project_files(self.proj, include=["../dehors"], cwd=self.proj)

    def test_lancement_et_rapatriement(self):
        fake = FakePopen({"code": 0, "error": "", "fetched": ["out/r.txt"]},
                         produced={"out/r.txt": "résultat\n"})
        said = []
        code, why = distant_modal.run_job(["python3", "a.py"], "h100", self.proj, Path("sous"),
                                          self.overrides, fetch=["out/r.txt"],
                                          cwd=self.proj / "sous", say=said.append, popen=fake)
        self.assertEqual((code, why), (0, ""))
        self.assertEqual(fake.argv[0], str(self.py))
        self.assertEqual(fake.params["gpu"], "H100")
        self.assertEqual(fake.params["rel"], "sous")
        self.assertEqual(fake.params["command"], "python3 a.py")
        self.assertNotIn("secret.env", fake.sent)
        self.assertEqual((self.proj / "sous" / "out" / "r.txt").read_text(), "résultat\n")
        self.assertIn("out/r.txt rapatrié", said)

    def test_carte_par_defaut_et_echec(self):
        self.overrides["modal"]["gpu"] = "L4"
        fake = FakePopen({"code": 3, "error": "", "fetched": []})
        code, why = distant_modal.run_job(["false"], None, self.proj, Path("."), self.overrides,
                                          fetch=["x"], say=lambda t: None, popen=fake)
        self.assertEqual(fake.params["gpu"], "L4")
        self.assertEqual((code, why), (3, "la commande a renvoyé 3"))

    def test_rien_a_rapatrier(self):
        fake = FakePopen({"code": 0, "error": "", "fetched": []})
        code, why = distant_modal.run_job(["true"], None, self.proj, Path("."), self.overrides,
                                          fetch=["absent"], say=lambda t: None, popen=fake)
        self.assertEqual((code, why), (1, "absent : rien à rapatrier"))

    def test_erreur_modal(self):
        fake = FakePopen({"code": None, "error": "AuthError : jeton refusé", "fetched": []})
        with self.assertRaisesRegex(distant_modal.ModalError, "jeton refusé"):
            distant_modal.run_job(["true"], None, self.proj, Path("."), self.overrides,
                                  say=lambda t: None, popen=fake)

    def test_ccs_remote_run_gpu(self):
        write(distant.overrides_path(), f'[machines.modal]\nmodal_python = "{self.py}"\n')
        fake = FakePopen({"code": 0, "error": "", "fetched": []})
        real = distant_modal.run_job
        with mock.patch.object(distant_modal, "run_job",
                               lambda *a, **k: real(*a, **{**k, "popen": fake})), \
                mock.patch("os.getcwd", return_value=str(self.proj)), \
                redirect_stderr(io.StringIO()):
            code = cli.main(["remote", "run", "--gpu", "a100", "--", "nvidia-smi"])
        self.assertEqual(code, 0)
        self.assertEqual(fake.params["gpu"], "A100")
        job = distant_jobs.list_jobs()[0]
        self.assertEqual((job["machine"], job["state"]), ("modal", "done"))

    def test_gpu_refuse_avec_une_autre_machine(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli.main(["remote", "run", "--gpu", "T4", "--machine", "lp-work", "--", "x"])
        self.assertEqual(code, 1)
        self.assertIn("Modal", err.getvalue())

    def test_liste_des_machines(self):
        lines = distant.describe([], self.overrides, probe=False)
        self.assertTrue(lines and lines[-1].startswith("modal"))
