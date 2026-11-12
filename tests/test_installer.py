"""Mise à jour en un clic : aucun réseau, aucun pkexec, aucune installation réelle."""

import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from ccs_app import installer
from ccs_app.installer import InstallError

V = "0.7.0"
BASE = f"https://github.com/mawena/CCS/releases/download/v{V}/"
DEB = f"ccs_{V}_all.deb"
CONTENT = b"faux paquet debian"
SUM = hashlib.sha256(CONTENT).hexdigest()
SUMS = f"{SUM}  {DEB}\n{'0' * 64}  autre.txt\n"
RELEASE = {
    "tag_name": f"v{V}", "name": "CCS 0.7.0", "body": "## Ajouté\n- **Mise à jour** en un clic",
    "html_url": f"https://github.com/mawena/CCS/releases/tag/v{V}", "draft": False,
    "prerelease": False,
    "assets": [{"name": DEB, "browser_download_url": BASE + DEB},
               {"name": "SHA256SUMS", "browser_download_url": BASE + "SHA256SUMS"}],
}


class FakeResponse(io.BytesIO):
    def __init__(self, data, length=True):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))} if length else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Net:
    """Opener simulé : {url: octets}, journal des requêtes."""

    def __init__(self, files):
        self.files = files
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append((req.full_url, req.get_header("User-agent")))
        data = self.files.get(req.full_url)
        if data is None:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return FakeResponse(data)


def good_net(content=CONTENT, sums=SUMS):
    return Net({BASE + DEB: content, BASE + "SHA256SUMS": sums.encode(),
                installer.API_RELEASES + "/latest": json.dumps(RELEASE).encode()})


class Runner:
    """`run` simulé : dpkg-deb et pkexec ; journal des commandes."""

    def __init__(self, pkg="ccs", version=V, pkexec=(0, "")):
        self.pkg, self.version, self.pkexec = pkg, version, pkexec
        self.cmds = []

    def __call__(self, cmd):
        self.cmds.append(list(cmd))
        if cmd[0] == "dpkg-deb":
            return 0, f"Package: {self.pkg}\nVersion: {self.version}\n"
        if cmd[0] == "dpkg":
            return 0, "ccs: /usr/lib/ccs/ccs_app/installer.py\n"
        return self.pkexec


class UrlTests(unittest.TestCase):
    def test_liste_blanche(self):
        self.assertTrue(installer.allowed_url(BASE + DEB, V))
        self.assertTrue(installer.allowed_url(installer.API_ASSET_PREFIX + "12345"))
        for bad in (f"http://github.com/mawena/CCS/releases/download/v{V}/{DEB}",
                    f"https://github.com/autre/CCS/releases/download/v{V}/{DEB}",
                    f"https://github.com/mawena/CCS/releases/download/v0.6.0/{DEB}",
                    f"https://github.com.evil.io/mawena/CCS/releases/download/v{V}/{DEB}",
                    BASE + "../x.deb", BASE + DEB + "?x=1", BASE + "a/b", BASE,
                    installer.API_ASSET_PREFIX + "12/../x",
                    "https://api.github.com/repos/autre/CCS/releases/assets/1",
                    "file:///etc/passwd", None, 3):
            self.assertFalse(installer.allowed_url(bad, V), bad)
        self.assertFalse(installer.allowed_url(BASE + DEB, None))

    def test_redirections(self):
        self.assertTrue(installer.allowed_redirect("https://objects.githubusercontent.com/x?y=1"))
        self.assertTrue(installer.allowed_redirect("https://release-assets.githubusercontent.com/x"))
        for bad in ("http://objects.githubusercontent.com/x", "https://evil.io/x",
                    "https://objects.githubusercontent.com.evil.io/x",
                    "https://objects.githubusercontent.com:8443/x"):
            self.assertFalse(installer.allowed_redirect(bad), bad)

    def test_gestionnaire_de_redirection(self):
        h = installer._Redirects()
        req = urllib.request.Request(BASE + DEB)
        ok = h.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/z")
        self.assertEqual(ok.full_url, "https://objects.githubusercontent.com/z")
        with self.assertRaises(urllib.error.URLError):
            h.redirect_request(req, None, 302, "Found", {}, "https://evil.io/z")

    def test_telechargement_refuse_url_hors_liste(self):
        net = Net({})
        with tempfile.TemporaryDirectory() as d, self.assertRaises(InstallError):
            installer.download("https://evil.io/x.deb", os.path.join(d, "x"), 100, net)
        self.assertEqual(net.calls, [])


class PlanTests(unittest.TestCase):
    def test_choix_des_pieces_jointes(self):
        p = installer.plan_from_release(RELEASE)
        self.assertEqual((p.version, p.deb_name, p.deb_url, p.sums_url),
                         (V, DEB, BASE + DEB, BASE + "SHA256SUMS"))
        self.assertIn("Mise à jour", p.notes)

    def test_url_api_acceptee(self):
        r = json.loads(json.dumps(RELEASE))
        r["assets"][0] = {"name": DEB, "url": installer.API_ASSET_PREFIX + "42",
                          "browser_download_url": "https://evil.io/x"}
        self.assertEqual(installer.plan_from_release(r).deb_url, installer.API_ASSET_PREFIX + "42")

    def test_pieces_manquantes_ou_hostiles(self):
        r = dict(RELEASE, assets=RELEASE["assets"][:1])
        with self.assertRaises(InstallError):
            installer.plan_from_release(r)
        r = dict(RELEASE, assets=[RELEASE["assets"][0],
                                  {"name": "SHA256SUMS", "browser_download_url": "https://evil.io/S"}])
        with self.assertRaisesRegex(InstallError, "refusée"):
            installer.plan_from_release(r)
        r = dict(RELEASE, assets=[{"name": "ccs_9.9.9_all.deb", "browser_download_url": BASE + DEB},
                                  RELEASE["assets"][1]])
        with self.assertRaises(InstallError):
            installer.plan_from_release(r)
        for bad in ({}, {"tag_name": "x"}, dict(RELEASE, draft=True), dict(RELEASE, assets=None)):
            with self.assertRaises(InstallError):
                installer.plan_from_release(bad)

    def test_fetch_plan_latest_et_tag(self):
        net = good_net()
        p = installer.fetch_plan(opener=net)
        self.assertEqual(p.version, V)
        self.assertEqual(net.calls[0], (installer.API_RELEASES + "/latest", "ccs"))
        net.files[installer.API_RELEASES + f"/tags/v{V}"] = json.dumps(RELEASE).encode()
        installer.fetch_plan(V, opener=net)
        self.assertEqual(net.calls[1][0], installer.API_RELEASES + f"/tags/v{V}")
        with self.assertRaises(InstallError):
            installer.fetch_plan("n'importe/quoi", opener=net)

    def test_erreurs_reseau(self):
        with self.assertRaisesRegex(InstallError, "HTTP 404"):
            installer.fetch_plan(opener=Net({}))

        def boom(req, timeout=None):
            raise urllib.error.URLError("hors ligne")
        with self.assertRaisesRegex(InstallError, "hors ligne"):
            installer.fetch_plan(opener=boom)
        with self.assertRaisesRegex(InstallError, "illisible"):
            installer.fetch_plan(opener=Net({installer.API_RELEASES + "/latest": b"pas du json"}))


class VerificationTests(unittest.TestCase):
    def test_parse_sums(self):
        self.assertEqual(installer.parse_sums(f"{SUM}  a.deb\n{SUM.upper()} *b.deb\nbruit\n"),
                         {"a.deb": SUM, "b.deb": SUM})

    def test_somme(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, DEB)
            Path(p).write_bytes(CONTENT)
            installer.verify_sum(p, SUMS, DEB)
            with self.assertRaisesRegex(InstallError, "ne correspond pas"):
                installer.verify_sum(p, f"{'1' * 64}  {DEB}", DEB)
            with self.assertRaisesRegex(InstallError, "ne contient pas"):
                installer.verify_sum(p, f"{SUM}  autre.deb", DEB)

    def test_controle_du_paquet(self):
        installer.check_package("x.deb", V, "0.6.1", Runner())
        for run, msg in ((Runner(pkg="autre"), "pas « ccs »"), (Runner(version="0.7.1"), "0.7.1"),
                         (lambda c: (2, ""), "lisible")):
            with self.assertRaisesRegex(InstallError, msg):
                installer.check_package("x.deb", V, "0.6.1", run)
        with self.assertRaisesRegex(InstallError, "plus récente"):
            installer.check_package("x.deb", V, V, Runner())
        with self.assertRaises(InstallError):
            installer.check_package("x.deb", V, "0.8.0", Runner())

    def test_copie_de_developpement(self):
        self.assertTrue(installer.is_package_install(Runner()))
        self.assertFalse(installer.is_package_install(lambda c: (1, "dpkg-query: introuvable")))
        self.assertFalse(installer.is_package_install(lambda c: (None, "")))

    def test_commande_d_installation(self):
        cmd = installer.install_command("rel/ccs.deb")
        self.assertEqual(cmd[:4], ["pkexec", "apt-get", "install", "-y"])
        self.assertTrue(os.path.isabs(cmd[4]))
        self.assertEqual(installer.manual_command("/tmp/a b/ccs.deb"), "sudo apt install '/tmp/a b/ccs.deb'")


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.plan = installer.plan_from_release(RELEASE)

    def leftovers(self):
        return os.listdir(self.root.name)

    def go(self, net=None, run=None, progress=None, current="0.6.1"):
        return installer.install(self.plan, current, net or good_net(), run or Runner(),
                                 progress, tmp_root=self.root.name)

    def test_succes(self):
        run, steps = Runner(), []
        r = self.go(run=run, progress=lambda p, f: steps.append(p))
        self.assertTrue(r.ok)
        self.assertEqual(r.version, V)
        self.assertEqual(run.cmds[-1][:4], ["pkexec", "apt-get", "install", "-y"])
        self.assertTrue(run.cmds[-1][4].endswith(DEB))
        self.assertEqual(sorted(set(steps), key=steps.index), ["download", "verify", "install"])
        self.assertEqual(self.leftovers(), [])

    def test_dossier_prive(self):
        modes = []
        run = Runner()

        def spy(cmd):
            if cmd[0] == "pkexec":
                d = os.path.dirname(cmd[4])
                modes.append((os.stat(d).st_mode & 0o777, os.stat(cmd[4]).st_mode & 0o777))
            return run(cmd)
        self.go(run=spy)
        self.assertEqual(modes, [(0o700, 0o600)])

    def test_somme_fausse_rien_installe(self):
        run = Runner()
        with self.assertRaisesRegex(InstallError, "ne correspond pas"):
            self.go(net=good_net(content=b"autre chose"), run=run)
        self.assertFalse([c for c in run.cmds if c[0] == "pkexec"])
        self.assertEqual(self.leftovers(), [])

    def test_paquet_incorrect_rien_installe(self):
        for run in (Runner(pkg="autre"), Runner(version="0.6.9")):
            with self.assertRaises(InstallError):
                self.go(run=run)
            self.assertFalse([c for c in run.cmds if c[0] == "pkexec"])
        self.assertEqual(self.leftovers(), [])

    def test_deja_a_jour(self):
        net = good_net()
        r = self.go(net=net, current=V)
        self.assertEqual(net.calls, [])
        self.assertIn("à jour", r.message)

    def test_echec_reseau_nettoye(self):
        with self.assertRaises(InstallError):
            self.go(net=Net({BASE + "SHA256SUMS": SUMS.encode()}))
        self.assertEqual(self.leftovers(), [])

    def test_taille_excessive(self):
        with mock.patch.object(installer, "MAX_DEB", 5), self.assertRaisesRegex(InstallError, "volumineux"):
            self.go()
        self.assertEqual(self.leftovers(), [])

    def test_telechargement_tronque(self):
        class Short(Net):
            def __call__(self, req, timeout=None):
                r = super().__call__(req, timeout)
                if req.full_url.endswith(".deb"):
                    r.headers["Content-Length"] = str(len(CONTENT) + 10)
                return r
        n = good_net()
        short = Short(n.files)
        with self.assertRaisesRegex(InstallError, "incomplet"):
            self.go(net=short)
        self.assertEqual(self.leftovers(), [])

    def test_pkexec_absent_repli_et_paquet_conserve(self):
        with self.assertRaises(InstallError) as cm:
            self.go(run=Runner(pkexec=(None, "")))
        self.assertTrue(cm.exception.fallback.startswith("sudo apt install "))
        deb = cm.exception.fallback.split(" ", 3)[-1].strip("'")
        self.assertTrue(os.path.exists(deb))
        installer.shutil.rmtree(os.path.dirname(deb))

    def test_pkexec_refuse(self):
        for code in (126, 127):
            with self.assertRaises(InstallError) as cm:
                self.go(run=Runner(pkexec=(code, "")))
            self.assertIn("rien n'a été installé", str(cm.exception))
            self.assertIsNotNone(cm.exception.fallback)
            installer.shutil.rmtree(os.path.dirname(cm.exception.fallback.split(" ", 3)[-1].strip("'")))

    def test_apt_echoue_nettoye(self):
        with self.assertRaisesRegex(InstallError, "code 100"):
            self.go(run=Runner(pkexec=(100, "E: dépendance manquante\n")))
        self.assertEqual(self.leftovers(), [])

    def test_user_agent(self):
        net = good_net()
        self.go(net=net)
        self.assertTrue(all(ua == "ccs" for _, ua in net.calls))


class CommandTests(unittest.TestCase):
    def test_a_jour(self):
        code, text = installer.command([], good_net(), Runner(), lambda *_: None, current=V)
        self.assertEqual((code, "à jour" in text), (0, True))

    def test_verifier(self):
        run = Runner()
        code, text = installer.command(["--verifier"], good_net(), run, lambda *_: None, current="0.6.1")
        self.assertEqual(code, 0)
        self.assertIn(V, text)
        self.assertFalse([c for c in run.cmds if c[0] == "pkexec"])

    def test_installation(self):
        lines, run = [], Runner()
        with mock.patch.object(installer.tempfile, "mkdtemp", wraps=installer.tempfile.mkdtemp):
            code, text = installer.command([], good_net(), run, lines.append, current="0.6.1")
        self.assertEqual(code, 0)
        self.assertIn("installé", text)
        self.assertEqual(len(lines), 3)

    def test_usage_et_dev(self):
        self.assertEqual(installer.command(["--bof"], Net({}), Runner())[0], 2)
        self.assertEqual(installer.command(["-h"], Net({}), Runner())[0], 0)
        code, text = installer.command([], Net({}), lambda c: (1, ""))
        self.assertEqual((code, text), (1, "Copie de développement : mise à jour par git."))

    def test_erreur_avec_repli(self):
        code, text = installer.command([], good_net(), Runner(pkexec=(127, "")), lambda *_: None,
                                       current="0.6.1")
        self.assertEqual(code, 1)
        self.assertIn("sudo apt install", text)
        installer.shutil.rmtree(os.path.dirname(text.split("sudo apt install ")[1].strip().strip("'")))

    def test_erreur_reseau(self):
        code, text = installer.command([], Net({}), Runner(), lambda *_: None)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 404", text)


class NotesTests(unittest.TestCase):
    def test_texte_lisible(self):
        md = "## Ajouté\r\n\r\n\r\n- **Mise à jour** en un [clic](https://x.y)\n- `ccs maj`\n\n---\n"
        self.assertEqual(installer.plain_notes(md),
                         "Ajouté\n\n• Mise à jour en un clic (https://x.y)\n• ccs maj")
        self.assertEqual(installer.plain_notes(None), "")


if __name__ == "__main__":
    unittest.main()


class CodeStampTest(unittest.TestCase):
    """Empreinte du code installé : change quand un nouveau paquet remplace les fichiers."""

    def test_stamp_changes_when_code_is_replaced(self):
        import tempfile as _tf
        from pathlib import Path as _P
        root = _P(_tf.mkdtemp(prefix="ccs-stamp-"))
        self.addCleanup(__import__("shutil").rmtree, root, True)
        (root / "gui").mkdir()
        (root / "a.py").write_text("x = 1\n")
        (root / "gui" / "b.py").write_text("y = 2\n")
        first = installer.code_stamp(root)
        self.assertIsNotNone(first)
        self.assertEqual(installer.code_stamp(root), first)          # rien n'a bougé
        os.utime(root / "gui" / "b.py", (1_900_000_000, 1_900_000_000))
        self.assertNotEqual(installer.code_stamp(root), first)       # nouveau paquet installé
        self.assertIsNone(installer.code_stamp(root / "absent"))
