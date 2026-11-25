import json
import subprocess
import unittest

from ccs_app import network


def fake(stdout="", code=0, stderr=""):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        out = stdout(argv) if callable(stdout) else stdout
        return subprocess.CompletedProcess(argv, code, out, stderr)
    run.calls = calls
    return run


STATUS = {
    "BackendState": "Running",
    "Self": {"DNSName": "srv-mawena-cloud.mesh.mawena.cloud.", "HostName": "srv-mawena-cloud", "OS": "linux",
             "TailscaleIPs": ["100.64.0.1"], "Online": True},
    "Peer": {
        "a": {"DNSName": "laptop.mesh.mawena.cloud.", "OS": "linux", "TailscaleIPs": ["100.64.0.2"],
              "Online": True, "CurAddr": "192.168.1.20:41641", "Relay": "mawena"},
        "b": {"DNSName": "pixel.mesh.mawena.cloud.", "OS": "android", "TailscaleIPs": ["100.64.0.3"],
              "Online": True, "CurAddr": "", "Relay": "mawena"},
        "c": {"DNSName": "iphone.mesh.mawena.cloud.", "OS": "iOS", "TailscaleIPs": ["100.64.0.4"],
              "Online": True, "CurAddr": "[2a01:e0a::1]:41641"},
        "d": {"DNSName": "lp-work.mesh.mawena.cloud.", "OS": "linux", "Online": False},
    },
}


class PathTest(unittest.TestCase):
    def test_chemins(self):
        st = network.parse_status(STATUS)
        self.assertEqual(st["self"]["name"], "srv-mawena-cloud")
        self.assertEqual([(p["name"], p["path"]) for p in st["peers"]],
                         [("laptop", "lan"), ("iphone", "direct"), ("pixel", "relay"),
                          ("lp-work", "offline")])

    def test_plage_maillee_pas_locale(self):
        self.assertFalse(network.is_local(network._host("100.64.0.9:41641")))
        self.assertTrue(network.is_local(network._host("10.0.0.2:41641")))
        self.assertTrue(network.is_local(network._host("[fe80::1]:41641")))
        self.assertFalse(network.is_local(network._host("84.46.246.202:41641")))

    def test_status_et_description(self):
        st = network.status(run=fake(json.dumps(STATUS)))
        lines = network.describe(st)
        self.assertIn("cet appareil", lines[0])
        self.assertIn("réseau local (192.168.1.20:41641)", lines[1])

    def test_arrete(self):
        st = network.parse_status({"BackendState": "NeedsLogin"})
        self.assertIn("NeedsLogin", network.describe(st)[0])


class KeyTest(unittest.TestCase):
    def test_cle_cree_utilisateur(self):
        def out(argv):
            if argv[1:3] == ["users", "list"]:
                return "[]"
            if argv[1:3] == ["users", "create"]:
                return '{"id": 1, "name": "charles"}'
            return '{"key": "abc123"}'
        run = fake(out)
        self.assertEqual(network.auth_key(run=run), "abc123")
        self.assertEqual(run.calls[-1][:6], ["headscale", "preauthkeys", "create", "--user", "1",
                                             "--expiration"])

    def test_erreur(self):
        with self.assertRaises(network.NetworkError):
            network.auth_key(run=fake("", code=1, stderr="refusé"))

    def test_lignes(self):
        lines = network.join_lines("k", "pc-x")
        self.assertIn("--login-server https://network.mawena.cloud --authkey k", lines[1])
        self.assertTrue(lines[1].endswith("--hostname pc-x"))


class DisplayTest(unittest.TestCase):
    def test_addr_kind_like_the_web(self):
        self.assertEqual(network.addr_kind("192.168.1.20:41641"), ("192.168.1.20", "lan"))
        self.assertEqual(network.addr_kind("1.2.3.4:41641"), ("1.2.3.4", "public"))
        self.assertEqual(network.addr_kind("[2a02::1]:41641"), ("2a02::1", "v6"))
        self.assertEqual(network.addr_kind("[fe80::1]:41641"), ("fe80::1", "lan"))
        self.assertEqual(network.addr_kind("100.64.0.3:41641"), ("100.64.0.3", "mesh"))

    def test_kind_summary_bytes(self):
        self.assertEqual(network.device_kind({"os": "iOS", "name": "iphone-14-pro"}), "apple")
        self.assertEqual(network.device_kind({"os": "android", "name": "pixel-4-xl"}), "phone")
        self.assertEqual(network.device_kind({"os": "linux", "name": "srv-mawena-cloud"}), "server")
        self.assertEqual(network.device_kind({"os": "linux", "name": "lp-home"}), "laptop")
        st = {"self": {"name": "vps"}, "peers": [{"online": True, "path": "direct"},
                                                 {"online": False, "path": "offline"}]}
        self.assertEqual(network.summary(st), {"total": 3, "online": 2, "lan": 0, "direct": 1, "relay": 0})
        self.assertEqual([network.human_bytes(n) for n in (500, 1536, 300 * 2 ** 30)],
                         ["500 o", "1,5 Ko", "300 Go"])

    def test_overview_without_tailscale_nor_headscale(self):
        from unittest import mock
        with mock.patch("shutil.which", return_value=None):
            st = network.overview()
        self.assertFalse(st["installed"])
        self.assertFalse(st["server"])
        self.assertEqual(st["peers"], [])


if __name__ == "__main__":
    unittest.main()
