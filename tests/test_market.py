"""Market (phase 45) : lecture des cartes et des annonces sur fixtures, choix de la fenêtre du
vendeur (jamais Messenger), défilement simulé, refus net sans tunnel par pc-bureau, session en
600, client WebSocket et CDP (faux Chrome), dossier du chat et commandes `ccs market`."""

import argparse
import base64
import hashlib
import io
import json
import os
import socket
import stat
import struct
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from ccs_app import market, market_cli

FIX = Path(__file__).parent / "fixtures" / "market"
CARDS = json.loads((FIX / "cartes.json").read_text(encoding="utf-8"))
COOKIES = [{"name": "c_user", "value": "123", "domain": ".facebook.com", "path": "/", "expires": -1},
           {"name": "xs", "value": "secret", "domain": ".facebook.com", "path": "/", "expires": 4e9},
           {"name": "other", "value": "x", "domain": ".example.com", "path": "/"}]


class Env(unittest.TestCase):
    """HOME isolé : config, données et cache de CCS dans un dossier jetable."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ccs-market-test-")
        env = {"HOME": self.tmp, "XDG_CONFIG_HOME": f"{self.tmp}/.config",
               "XDG_DATA_HOME": f"{self.tmp}/.local/share", "XDG_CACHE_HOME": f"{self.tmp}/.cache"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        os.environ.pop("CCS_MARKET_CHROME", None)
        self.cfg = market.config()


class ParsingTest(unittest.TestCase):
    def test_prices(self):
        self.assertEqual(market.parse_price("22 000 CFA"), 22000)
        self.assertEqual(market.parse_price("7 000 CFA"), 7000)
        self.assertEqual(market.parse_price("150 000 FCFA"), 150000)
        self.assertEqual(market.parse_price("Gratuit"), 0)
        self.assertIsNone(market.parse_price("Cudy AC1200"))

    def test_cards(self):
        cards = [market.parse_card(c["href"], c["text"]) for c in CARDS]
        self.assertIsNone(cards[-1])                        # pas une annonce
        cudy = cards[0]
        self.assertEqual((cudy.id, cudy.price, cudy.title, cudy.city),
                         ("2421778705023492", 22000, "Cudy AC1200 dual band", "Lomé, Maritime"))
        self.assertEqual(cudy.url, "https://www.facebook.com/marketplace/item/2421778705023492/")
        self.assertEqual((cards[1].price, cards[1].title), (25000, "Cudy WR1300"))  # « Annonce récente » ôtée
        self.assertEqual((cards[2].price, cards[2].old_price, cards[2].title), (18000, 22000, "MikroTik hAP lite"))
        self.assertEqual(cards[3].price, 7000)
        self.assertEqual(cards[4].price, 0)
        text = market.format_cards(cards[:3])
        self.assertIn("22 000 CFA | Cudy AC1200 dual band | Lomé, Maritime | "
                      "https://www.facebook.com/marketplace/item/2421778705023492/", text)
        self.assertIn("18 000 CFA (avant 22 000 CFA) | MikroTik", text)

    def test_item(self):
        it = market.parse_item((FIX / "annonce.txt").read_text(encoding="utf-8"), "u")
        self.assertEqual(it["title"], "Cudy AC1200 dual band")
        self.assertEqual((it["price"], it["place"], it["condition"]), (22000, "Lomé", "Neuf"))
        self.assertIn("WireGuard", it["description"])
        self.assertNotIn("traduction", it["description"])
        self.assertNotIn("approximatif", it["description"])
        self.assertEqual(it["seller"], "Mozich Trompa")
        self.assertIn("État : Neuf", market.format_item(it))

    def test_item_condition_on_same_line(self):
        it = market.parse_item("Titre\n10 000 CFA\nDétails\nÉtat : D'occasion - bon état\nRAS\n"
                               "Informations vendeur\nAma", "u")
        self.assertEqual((it["condition"], it["description"], it["seller"]),
                         ("D'occasion - bon état", "RAS", "Ama"))

    def test_urls(self):
        self.assertEqual(market.item_url("https://web.facebook.com/marketplace/item/2421778705023492/?x=1"),
                         "https://www.facebook.com/marketplace/item/2421778705023492/")
        self.assertEqual(market.seller_url("100058059515617"),
                         "https://www.facebook.com/marketplace/profile/100058059515617/")
        for bad in ("https://evil.example/marketplace/item/1234567/", "", "item/12"):
            with self.assertRaises(market.MarketError):
                market.item_url(bad)
        with self.assertRaises(market.MarketError):
            market.seller_url("https://www.facebook.com/messages/t/123456789")
        u = market.search_url("routeur wireguard", "lome", 5000, 30000)
        self.assertTrue(u.startswith("https://www.facebook.com/marketplace/lome/search?query=routeur+wireguard"))
        self.assertIn("minPrice=5000", u)
        self.assertIn("maxPrice=30000", u)
        with self.assertRaises(market.MarketError):
            market.search_url("x", "../login")

    def test_login_page(self):
        self.assertTrue(market.is_login({"url": "https://www.facebook.com/login/?next=x"}))
        self.assertTrue(market.is_login({"url": "https://www.facebook.com/checkpoint/1/"}))
        self.assertTrue(market.is_login({"url": "https://www.facebook.com/marketplace/", "login_text": True, "items": 0}))
        self.assertFalse(market.is_login({"url": "https://www.facebook.com/marketplace/", "login_text": True, "items": 12}))


class DialogTest(unittest.TestCase):
    def test_never_messenger(self):
        # La liste des discussions vient en premier et contient même un lien d'annonce partagé.
        dialogs = [{"index": 0, "items": 3, "messenger": True},
                   {"index": 1, "items": 40, "messenger": False}]
        self.assertEqual(market.choose_dialog(dialogs), 1)
        self.assertIsNone(market.choose_dialog([{"index": 0, "items": 9, "messenger": True}]))
        self.assertIsNone(market.choose_dialog([{"index": 0, "items": 0, "messenger": False}]))
        self.assertIsNone(market.choose_dialog([]))

    def test_scripts_never_read_messenger(self):
        # Le script des fenêtres ne renvoie que des nombres et des drapeaux ; ceux des cartes et du
        # texte d'une fenêtre refusent une fenêtre Messenger ; celui de l'annonce l'écarte.
        self.assertNotIn("innerText", market.JS_DIALOGS)
        self.assertIn("messenger(root)", market.js_cards(1))
        self.assertIn("!messenger(d)", market.JS_ITEM)
        self.assertNotIn("document.body.innerText", market.JS_ITEM)


class AccumulateTest(unittest.TestCase):
    @staticmethod
    def batches(n_total, step, window):
        """Liste virtualisée : chaque défilement montre `window` cartes, `step` plus loin."""
        state = {"top": 0}

        def fetch():
            top = state["top"]
            state["top"] = min(top + step, max(n_total - window, 0))
            return [{"href": f"/marketplace/item/{100000 + i}/", "text": f"{1000 + i} CFA\nArticle {i}\nLomé"}
                    for i in range(top, min(top + window, n_total))]
        return fetch

    def test_union_until_patience(self):
        pauses = []
        cards = market.accumulate(self.batches(512, 8, 24), limit=600, patience=5,
                                  pause=lambda: pauses.append(1))
        self.assertEqual(len(cards), 512)
        self.assertEqual(len({c.id for c in cards}), 512)
        self.assertEqual(cards[0].title, "Article 0")
        # après la dernière nouveauté : 5 tours vides, puis arrêt
        self.assertLess(len(pauses), 512 // 8 + 6)

    def test_limit_and_rounds(self):
        self.assertEqual(len(market.accumulate(self.batches(512, 8, 24), limit=50)), 50)
        self.assertEqual(len(market.accumulate(self.batches(512, 8, 24), limit=600, max_rounds=3)), 40)


class SessionTest(Env):
    def test_saved_600_facebook_only(self):
        n = market.save_session(COOKIES, "UA")
        path = market.session_path()
        self.assertEqual(n, 2)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        data = market.load_session()
        self.assertEqual({c["name"] for c in data["cookies"]}, {"c_user", "xs"})
        self.assertEqual(data["user_agent"], "UA")
        self.assertTrue(market.logged_in(data["cookies"]))

    def test_expired_or_missing(self):
        self.assertFalse(market.logged_in(COOKIES[:1]))
        self.assertFalse(market.logged_in([dict(COOKIES[0]), dict(COOKIES[1], expires=10)]))
        with self.assertRaises(market.SessionError) as e:
            market.require_session()
        self.assertIn("ccs market login", str(e.exception))


class FakeProc:
    def __init__(self, alive=True):
        self.code = None if alive else 255
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def kill(self):
        self.code = -9

    def wait(self, _t=None):
        return self.code


class TunnelTest(Env):
    def test_argv(self):
        t = market.Tunnel(self.cfg)
        argv = t.argv()
        self.assertEqual(argv[0], "ssh")
        for opt in ("HostName=100.64.0.2", "HostKeyAlias=ricochet-pc-bureau", "BatchMode=yes",
                    "ExitOnForwardFailure=yes"):
            self.assertIn(opt, argv)
        self.assertEqual(argv[-4:], ["-D", f"127.0.0.1:{t.port}", "-N", "pc-bureau"])
        t2 = market.Tunnel(self.cfg, forward=9222)
        self.assertIn(f"127.0.0.1:{t2.port}:127.0.0.1:9222", t2.argv())

    def test_refuses_when_pc_bureau_is_down(self):
        procs = []

        def popen(argv, **_kw):
            procs.append(FakeProc(alive=False))       # ssh échoue aussitôt
            return procs[-1]
        with self.assertRaises(market.TunnelError) as e:
            with market.Tunnel(self.cfg, popen=popen):
                pass
        self.assertIn("rien n'a été envoyé à Facebook", str(e.exception))

    def test_run_sends_nothing_without_tunnel(self):
        market.save_session(COOKIES, "UA")
        browser = mock.Mock(side_effect=AssertionError("Chrome ne doit pas démarrer"))

        class DeadTunnel:
            def __init__(self, cfg):
                pass

            def __enter__(self):
                raise market.TunnelError("pc-bureau ne répond pas : rien n'a été envoyé à Facebook.")

            def __exit__(self, *_):
                pass
        with self.assertRaises(market.TunnelError):
            market.run(lambda fb: None, self.cfg, tunnel=DeadTunnel, browser=browser)
        browser.assert_not_called()

    def test_exit_must_not_be_the_vps(self):
        ok = market.check_exit(1, self.cfg, lookup=lambda p: "156.38.73.89" if p else "84.46.246.202")
        self.assertEqual(ok, "156.38.73.89")
        for seen, direct in (("84.46.246.202", None), ("5.6.7.8", "5.6.7.8"), (None, "1.2.3.4")):
            with self.assertRaises(market.TunnelError):
                market.check_exit(1, self.cfg, lookup=lambda p, s=seen, d=direct: s if p else d)

    def test_socks_client(self):
        # Faux serveur SOCKS5 : vérifie la poignée de main et le nom de domaine transmis.
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        seen = {}

        def serve():
            c, _ = srv.accept()
            seen["hello"] = c.recv(3)
            c.sendall(b"\x05\x00")
            head = c.recv(5)
            seen["host"] = c.recv(head[4]).decode()
            seen["port"] = struct.unpack(">H", c.recv(2))[0]
            c.sendall(b"\x05\x00\x00\x01" + bytes(4) + b"\x00\x00")
            c.close()
        th = threading.Thread(target=serve)
        th.start()
        s = market.socks_connect(srv.getsockname()[1], "api.ipify.org")
        s.close()
        th.join(5)
        srv.close()
        self.assertEqual(seen, {"hello": b"\x05\x01\x00", "host": "api.ipify.org", "port": 443})


class WsServer:
    """Faux point CDP : WebSocket côté serveur, répond `{"id", "result": {"echo": method}}`."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.th = threading.Thread(target=self.serve, daemon=True)
        self.th.start()

    def serve(self):
        c, _ = self.srv.accept()
        head = b""
        while b"\r\n\r\n" not in head:
            head += c.recv(1)
        key = [ln.split(b": ")[1] for ln in head.split(b"\r\n") if ln.lower().startswith(b"sec-websocket-key")][0]
        acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  b"Sec-WebSocket-Accept: " + acc + b"\r\n\r\n")
        while True:
            b0, b1 = c.recv(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", c.recv(2))[0]
            mask = c.recv(4)
            data = b""
            while len(data) < n:
                data += c.recv(n - len(data))
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if b0 & 0x0F == 0x8:
                break
            msg = json.loads(data)
            # un événement d'abord (ignoré par Cdp), une grosse réponse en deux fragments ensuite
            ev = json.dumps({"method": "Page.loadEventFired", "params": {}}).encode()
            c.sendall(bytes([0x81, len(ev)]) + ev)
            out = json.dumps({"id": msg["id"], "result": {"echo": msg["method"], "pad": "x" * 70000}}).encode()
            half = len(out) // 2
            for fin, part in ((0x01, out[:half]), (0x80, out[half:])):
                c.sendall(bytes([fin, 127]) + struct.pack(">Q", len(part)) + part)
        c.close()
        self.srv.close()


class CdpTest(unittest.TestCase):
    def test_websocket_and_cdp(self):
        srv = WsServer()
        cdp = market.Cdp(market.WebSocket(f"ws://127.0.0.1:{srv.port}/devtools/page/1"))
        self.assertEqual(cdp.call("Network.enable")["echo"], "Network.enable")
        self.assertEqual(cdp.call("Page.enable")["echo"], "Page.enable")
        cdp.close()
        srv.th.join(5)

    def test_only_local(self):
        with self.assertRaises(market.MarketError):
            market.WebSocket("ws://example.com/devtools")


class FakeCdp:
    """Faux Chrome : rend des réponses selon la méthode et le script évalué."""

    def __init__(self, pages):
        self.pages = pages            # url → {"state": {...}, "dialogs": [...], "cards": {scope: fetch}, ...}
        self.url = None
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "Page.navigate":
            self.url = params["url"]
        if method == "Network.getAllCookies":
            return {"cookies": COOKIES}
        return {}

    def evaluate(self, expr):
        page = self.pages[self.url]
        if expr == market.JS_STATE:
            return {"url": self.url, "ready": "complete", **page.get("state", {})}
        if expr == market.JS_DIALOGS:
            return page["dialogs"]
        if expr == market.JS_ITEM:
            return page["item"]
        if "innerText || '').split" in expr:
            return page["head"]
        for scope, fetch in page.get("cards", {}).items():
            if expr == market.js_cards(scope):
                return fetch()
        raise AssertionError("script inattendu")


class FacebookTest(Env):
    def fb(self, pages):
        self.cdp = FakeCdp(pages)
        self.sleeps = []
        return market.Facebook(self.cdp, self.cfg, sleep=self.sleeps.append, uniform=lambda a, b: a)

    def test_setup_blocks_images_and_sets_cookies(self):
        fb = self.fb({})
        fb.setup({"cookies": COOKIES[:2]})
        methods = dict(self.cdp.calls)
        self.assertIn("*.jpg*", methods["Network.setBlockedURLs"]["urls"])
        sent = methods["Network.setCookies"]["cookies"]
        self.assertEqual([c["name"] for c in sent], ["c_user", "xs"])
        self.assertNotIn("expires", sent[0])          # cookie de session : pas d'échéance

    def test_search(self):
        url = market.search_url("routeur", "lome", None, 30000)
        fb = self.fb({url: {"cards": {"main": lambda: CARDS}}})
        cards = fb.search("routeur", max_price=30000)
        self.assertEqual(len(cards), 5)
        self.assertIn(6.0, self.sleeps)                # pause « humaine » après la page

    def test_seller_reads_only_the_seller_dialog(self):
        url = market.seller_url("100058059515617")
        fetch = AccumulateTest.batches(120, 10, 30)
        fb = self.fb({url: {"dialogs": [{"index": 0, "items": 2, "messenger": True},
                                        {"index": 1, "items": 30, "messenger": False}],
                            "head": ["Fermer", "Mozich Trompa", "Lomé"],
                            "cards": {1: fetch, 0: lambda: self.fail("Messenger lu")}}})
        res = fb.seller("https://www.facebook.com/marketplace/profile/100058059515617/")
        self.assertEqual(res["name"], "Mozich Trompa")
        self.assertEqual(len(res["items"]), 120)

    def test_seller_without_dialog(self):
        url = market.seller_url("100058059515617")
        fb = self.fb({url: {"dialogs": [{"index": 0, "items": 5, "messenger": True}]}})
        with self.assertRaises(market.MarketError):
            fb.seller("100058059515617")

    def test_item(self):
        url = market.item_url("2421778705023492")
        fb = self.fb({url: {"item": {"text": (FIX / "annonce.txt").read_text(encoding="utf-8"),
                                     "seller_url": "/marketplace/profile/100058059515617/?ref=x"}}})
        it = fb.item(url)
        self.assertEqual((it["price"], it["seller"]), (22000, "Mozich Trompa"))
        self.assertEqual(it["seller_url"], "https://www.facebook.com/marketplace/profile/100058059515617/")

    def test_expired_session(self):
        url = market.item_url("2421778705023492")
        fb = self.fb({url: {"state": {"url": "https://www.facebook.com/login/?next=x"}}})
        with self.assertRaises(market.SessionError) as e:
            fb.item(url)
        self.assertIn("ccs market login", str(e.exception))

    def test_run_refreshes_cookies(self):
        market.save_session(COOKIES[:2], "UA pc-bureau")
        url = market.item_url("2421778705023492")
        cdp = FakeCdp({url: {"item": {"text": "T\n1 000 CFA", "seller_url": ""}}})
        seen = {}

        class T:
            def __init__(self, cfg):
                self.port = 4242

            def __enter__(self):
                return self

            def __exit__(self, *_):
                seen["tunnel_closed"] = True

        class B:
            def __init__(self, cfg, port, ua):
                seen["browser"] = (port, ua)

            def __enter__(self):
                return cdp

            def __exit__(self, *_):
                seen["browser_closed"] = True
        with mock.patch.object(market.time, "sleep"):
            it = market.run(lambda fb: fb.item(url), self.cfg, tunnel=T, browser=B,
                            exit_check=lambda port, cfg: "156.38.73.89")
        self.assertEqual(it["title"], "T")
        self.assertEqual(seen, {"browser": (4242, "UA pc-bureau"), "tunnel_closed": True,
                                "browser_closed": True})
        self.assertEqual(stat.S_IMODE(market.session_path().stat().st_mode), 0o600)


class ChromeTest(Env):
    def test_find_playwright(self):
        base = Path(self.tmp) / ".cache" / "ms-playwright"
        for v in ("1200", "1248"):
            p = base / f"chromium_headless_shell-{v}" / "chrome-headless-shell-linux64" / "chrome-headless-shell"
            p.parent.mkdir(parents=True)
            p.write_text("")
            p.chmod(0o755)
        with mock.patch.object(market.shutil, "which", return_value=None):
            found = market.find_chrome(self.cfg, home=self.tmp)
        self.assertIn("1248", found)

    def test_argv(self):
        argv = market.chrome_argv("/x/chrome-headless-shell", "/tmp/p", 4242, "UA")
        self.assertIn("--proxy-server=socks5://127.0.0.1:4242", argv)
        self.assertIn("--blink-settings=imagesEnabled=false", argv)
        self.assertIn("--user-agent=UA", argv)
        self.assertIn("--no-sandbox", argv)
        self.assertTrue(any(a.startswith("--host-resolver-rules=MAP * ~NOTFOUND") for a in argv))
        self.assertNotIn("--headless=new", argv)
        self.assertIn("--headless=new", market.chrome_argv("/usr/bin/chromium", "/p", 1, ""))


class LoginTest(Env):
    def test_login_exports_cookies(self):
        class Proc:
            returncode, stdout = 0, "OK\n"

        class T:
            def __init__(self, cfg, forward=None):
                self.port = 5555
                assert forward == 9222

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass
        answers = [{"cookies": COOKIES[:1]}, {"cookies": COOKIES}]
        cdp = mock.Mock()
        cdp.call.side_effect = lambda m, p=None: answers.pop(0) if m == "Storage.getCookies" else {}
        out = []
        ran = {}

        def run_cmd(argv, **kw):
            ran["argv"], ran["input"] = argv, kw["input"]
            return Proc()
        n = market.login(self.cfg, out=out.append, run_cmd=run_cmd, tunnel=T,
                         connect=lambda port: (cdp, {"User-Agent": "Mozilla/5.0 Chrome/142"}), sleep=lambda s: None)
        self.assertEqual(n, 2)
        self.assertEqual(ran["argv"][-3:], ["pc-bureau", "bash", "-s"])
        self.assertIn("--remote-debugging-address=127.0.0.1", ran["input"])
        self.assertEqual(market.load_session()["user_agent"], "Mozilla/5.0 Chrome/142")
        self.assertIn(mock.call("Browser.close"), cdp.call.call_args_list)
        self.assertFalse(any("secret" in line for line in out))       # aucun cookie affiché

    def test_login_without_graphical_session(self):
        class Proc:
            returncode, stdout = 3, "PAS_DE_SESSION\n"
        with self.assertRaises(market.MarketError) as e:
            market.login(self.cfg, out=lambda s: None, run_cmd=lambda *a, **k: Proc())
        self.assertIn("session graphique", str(e.exception))

    def test_login_pc_bureau_down(self):
        class Proc:
            returncode, stdout = 255, ""
        with self.assertRaises(market.TunnelError):
            market.login(self.cfg, out=lambda s: None, run_cmd=lambda *a, **k: Proc())


class WorkspaceTest(Env):
    def test_workspace(self):
        d = market.workspace()
        self.assertEqual(d, Path(self.tmp) / ".local" / "share" / "ccs" / "market")
        md = (d / "CLAUDE.md").read_text(encoding="utf-8")
        for word in ("ccs market search", "ccs market seller", "ccs market item", "classement", "CFA",
                     "WebSearch", "Messenger", "ccs market login", "ccs chat clear"):
            self.assertIn(word, md)
        allow = json.loads((d / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        self.assertIn("Bash(ccs market:*)", allow)
        self.assertIsNone(market.latest_session(d))


class CliTest(Env):
    def test_commands_and_codes(self):
        fake = mock.Mock(wraps=market)
        fake.MarketError, fake.TunnelError, fake.SessionError = (market.MarketError, market.TunnelError,
                                                                 market.SessionError)
        args = argparse.Namespace(action="search", query="routeur", city=None, min=None, max=None,
                                  limit=None, json=False)
        cards = [market.parse_card(c["href"], c["text"]) for c in CARDS[:2]]
        fake.run = lambda action, log=None: action(mock.Mock(search=lambda *a: cards))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(market_cli.cmd_market(args, fake), 0)
        self.assertIn("22 000 CFA | Cudy AC1200", out.getvalue())

        def down(*_a, **_k):
            raise market.TunnelError("pc-bureau ne répond pas")
        fake.run = down
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(market_cli.cmd_market(args, fake), 2)
        self.assertIn("pc-bureau", err.getvalue())
        args.action = "chercher"                                     # ancien nom français
        with redirect_stderr(io.StringIO()):
            self.assertEqual(market_cli.cmd_market(args, fake), 2)

    def test_parser(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        from ccs_app import cli
        market_cli.add_parser(sub, cli._command, cli._action)
        a = parser.parse_args(["market", "search", "routeur wireguard", "--max", "30000", "--city", "lome"])
        self.assertEqual((market_cli.ALIASES.get(a.action, a.action), a.query, a.max, a.city),
                         ("search", "routeur wireguard", 30000, "lome"))
        a = parser.parse_args(["market", "vendeur", "100058059515617", "--json"])
        self.assertEqual((market_cli.ALIASES.get(a.action, a.action), a.json), ("seller", True))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["market"])


if __name__ == "__main__":
    unittest.main()
