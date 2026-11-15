"""Paquets Debian : ccs (cœur), ccs-bureau (interface GTK), ccs-serveur (services du serveur)."""

import re
import unittest
from pathlib import Path

DEB = Path(__file__).resolve().parent.parent / "debian"
GUI_DEPS = ("python3-gi-cairo", "gir1.2-gtk-4.0", "gir1.2-adw-1", "gir1.2-vte-3.91", "gir1.2-gtksource-5",
            "gir1.2-gtk-3.0", "gir1.2-ayatanaappindicator3-0.1")


def stanzas():
    out = {}
    for block in (DEB / "control").read_text(encoding="utf-8").split("\n\n"):
        fields, key = {}, None
        for line in block.splitlines():
            if line.startswith((" ", "\t")) and key:
                fields[key] += " " + line.strip()
            elif ":" in line:
                key, _, value = line.partition(":")
                fields[key] = value.strip()
        if "Package" in fields:
            out[fields["Package"]] = fields
    return out


def unit(name):
    text = (DEB / name).read_text(encoding="utf-8")
    return dict(re.findall(r"^([A-Za-z]+)=(.*)$", text, flags=re.M)), text


class PackagingTest(unittest.TestCase):
    def test_control_three_packages(self):
        s = stanzas()
        self.assertEqual(set(s), {"ccs", "ccs-bureau", "ccs-serveur", "ccs-all"})
        self.assertIn("ccs-bureau", s["ccs"]["Recommends"])
        self.assertIn("ccs (= ${binary:Version})", s["ccs-bureau"]["Depends"])
        self.assertIn("ccs (<< 0.11.0)", s["ccs-bureau"]["Replaces"])
        self.assertIn("ccs (<< 0.11.0)", s["ccs-bureau"]["Breaks"])
        for dep in ("ccs (= ${binary:Version})", "python3-aiohttp", "python3-pyotp", "python3-qrcode", "libpam0g"):
            self.assertIn(dep, s["ccs-serveur"]["Depends"])
        self.assertIn("python3-urwid", s["ccs"]["Depends"])

    def test_all_metapackage(self):
        s = stanzas()["ccs-all"]
        for pkg in ("ccs", "ccs-bureau", "ccs-serveur"):
            self.assertIn(f"{pkg} (= ${{binary:Version}})", s["Depends"])
        self.assertEqual(s["Section"], "metapackages")
        self.assertIn("ccs-all", (DEB.parent / "scripts" / "build-deb.sh").read_text())

    def test_gui_deps_only_in_bureau(self):
        s = stanzas()
        for dep in GUI_DEPS[1:]:
            self.assertNotIn(dep, s["ccs"]["Depends"], dep)
            self.assertNotIn(dep, s["ccs-serveur"]["Depends"], dep)
            self.assertIn(dep.split(" ")[0], s["ccs-bureau"]["Depends"], dep)

    def test_install_files_split(self):
        core = (DEB / "ccs.install").read_text()
        gui = (DEB / "ccs-bureau.install").read_text()
        server = (DEB / "ccs-serveur.install").read_text()
        self.assertIn("ccs_app/server", core)
        self.assertNotIn("ccs_app/gui", core)
        self.assertIn("ccs_app/gui", gui)
        self.assertIn("ccs_app/web", server)
        self.assertIn("etc/pam.d", server)
        self.assertFalse((DEB / "install").exists())

    def test_units_hardening(self):
        auth, _ = unit("ccs-serveur.ccs-auth.service")
        self.assertEqual(auth["User"], "root")
        self.assertEqual(auth["ExecStart"], "/usr/bin/claude-accounts auth-serve")
        self.assertEqual(auth["RuntimeDirectory"], "ccs")
        self.assertEqual(auth["StateDirectory"], "ccs")
        self.assertEqual(auth["ProtectSystem"], "strict")
        self.assertIn("/var/lib/ccs", auth["ReadWritePaths"])
        web, _ = unit("ccs-serveur.ccs-web.service")
        self.assertEqual((web["User"], web["Group"]), ("ccs-web", "ccs-web"))
        for key, value in (("NoNewPrivileges", "yes"), ("ProtectSystem", "strict"), ("ProtectHome", "yes"),
                           ("PrivateTmp", "yes")):
            self.assertEqual(web[key], value, key)
        self.assertEqual(web["ExecStart"], "/usr/bin/claude-accounts web-serve")
        bridge, _ = unit("ccs-serveur.ccs-bridge@.service")
        self.assertEqual(bridge["User"], "%i")
        self.assertIn("bridge --socket /run/ccs/bridge/%i/bridge.sock", bridge["ExecStart"])

    def test_pam_file(self):
        text = (DEB / "pam" / "ccs").read_text()
        self.assertIn("@include common-auth", text)
        self.assertIn("@include common-account", text)

    def test_postinst_never_installs_claude_as_root(self):
        text = (DEB / "ccs.postinst").read_text()
        lines = [l for l in text.splitlines() if "install.sh" in l]
        self.assertTrue(lines)
        for l in lines:
            self.assertIn("runuser", l)
        self.assertIn('[ "$U" != root ]', text)
        self.assertIn("#DEBHELPER#", text)

    def test_server_postinst_creates_user_and_group(self):
        text = (DEB / "ccs-serveur.postinst").read_text()
        self.assertIn("addgroup --system ccs", text)
        self.assertIn("adduser --system", text)
        self.assertIn("ccs-web", text)
        self.assertIn("/etc/ccs/web.json", text)

    def test_debhelper_token_once_on_its_own_line(self):
        """debhelper remplace chaque « #DEBHELPER# », même dans un commentaire : un second bloc
        démarrait ccs-auth avant la création du groupe ccs-web (socket resté en root:root)."""
        scripts = [p for p in DEB.iterdir() if p.suffix in (".preinst", ".postinst", ".prerm", ".postrm")]
        self.assertTrue(scripts)
        for p in scripts:
            hits = [l for l in p.read_text(encoding="utf-8").splitlines() if "#DEBHELPER#" in l]
            self.assertEqual(hits, ["#DEBHELPER#"], p.name)

    def test_server_services_start_after_web_user_exists(self):
        text = (DEB / "ccs-serveur.postinst").read_text(encoding="utf-8")
        self.assertLess(text.index("adduser --system"), text.index("#DEBHELPER#"))


if __name__ == "__main__":
    unittest.main()
