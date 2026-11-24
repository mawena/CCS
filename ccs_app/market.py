"""Market : chercher sur Facebook Marketplace au Togo (phase 45).

L'onglet Market de CCS est un chat Claude dédié (dossier `~/.local/share/ccs/market/`, voir
`workspace()`) ; Claude y appelle les commandes `ccs market search|seller|item|status|login`
(`market_cli`), qui pilotent ici un Chrome sans interface.

Chemin des requêtes : **toujours par pc-bureau, par le réseau maillé**. Chaque commande ouvre
`ssh -D 127.0.0.1:<port> -N pc-bureau` (adresse 100.64.0.2), vérifie que l'adresse de sortie vue
par Internet n'est pas celle du VPS, puis lance Chrome avec `--proxy-server=socks5://…`. Pas de
repli direct : si pc-bureau ne répond pas, rien n'est envoyé à Facebook (`TunnelError`).

Session Facebook : le compte personnel de Charles. `login` ouvre Google Chrome sur l'écran de
pc-bureau (profil dédié, port de débogage local), attend la connexion, puis exporte les cookies
par CDP (ceux de Chrome Linux sont chiffrés par le trousseau : copier le profil ne marche pas).
Ils sont gardés dans `~/.config/ccs/market/session.json` (600), jamais affichés ni journalisés,
puis réinjectés à chaque commande (`Network.setCookies`) et remis à jour à la fin.

Vie privée : la liste des discussions Messenger est elle aussi un `div[role="dialog"]` ; on ne
prend jamais « le premier dialogue » (`choose_dialog`), on ne lit ni ne garde rien de Messenger.

Rythme humain : 6 à 8 s après chaque page, 1,5 à 3 s entre deux défilements, peu de pages par
question ; images bloquées ; Chrome est fermé après chaque commande (RAM du VPS).
"""

import base64
import dataclasses
import glob
import json
import os
import random
import re
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import core

FB = "https://www.facebook.com"
DEFAULTS = {
    "host": "pc-bureau",                 # hôte ssh de pc-bureau
    "hostname": "100.64.0.2",            # son adresse dans le réseau maillé
    "host_key_alias": "ricochet-pc-bureau",
    "vps_ip": "84.46.246.202",           # adresse publique du VPS : jamais vue par Facebook
    "city": "lome",                      # ville de la recherche Marketplace
    "chrome": "",                        # Chrome du VPS (vide : navigateurs de Playwright)
    "remote_chrome": "google-chrome",    # Chrome de pc-bureau (connexion)
    "remote_port": 9222,
    "page_delay": [6.0, 8.0],            # pause après une page (s)
    "scroll_delay": [1.5, 3.0],          # pause entre deux défilements (s)
    "search_rounds": 4,                  # défilements au plus pour une recherche
    "search_limit": 60,                  # annonces gardées au plus pour une recherche
    "seller_limit": 600,                 # annonces gardées au plus pour un vendeur
    "seller_rounds": 200,
    "patience": 5,                       # défilements sans nouveauté avant d'arrêter
    # Ubuntu 24.04 interdit les espaces de noms aux programmes sans profil AppArmor : le bac à
    # sable de Chrome ne démarre pas (comme Playwright, on s'en passe ; true si un profil existe)
    "sandbox": False,
}
IP_SERVICES = (("api.ipify.org", "/"), ("ifconfig.me", "/ip"))
BLOCKED = ["*.jpg*", "*.jpeg*", "*.png*", "*.webp*", "*.gif*", "*.mp4*", "*.m4a*",
           "*scontent*.fbcdn.net/*", "*video*.fbcdn.net/*"]
LOGIN_WAIT_S = 600


class MarketError(Exception):
    """Erreur montrée telle quelle (message en français, sans secret)."""


class TunnelError(MarketError):
    pass


class SessionError(MarketError):
    pass


def config_dir():
    return core.ccs_dir("config") / "market"


def config():
    """Réglages : DEFAULTS, surchargés par `~/.config/ccs/market/config.json` (facultatif)."""
    cfg = dict(DEFAULTS)
    raw = core.load_json(config_dir() / "config.json")
    for k, v in raw.items():
        if k in cfg and (type(v) is type(cfg[k]) or (isinstance(cfg[k], float) and isinstance(v, int))):
            cfg[k] = v
    if os.environ.get("CCS_MARKET_CHROME"):
        cfg["chrome"] = os.environ["CCS_MARKET_CHROME"]
    return cfg


# ---------------------------------------------------------------- session (cookies)

def session_path():
    return config_dir() / "session.json"


def _facebook_cookie(c):
    dom = str(c.get("domain") or "").lstrip(".").lower()
    return dom == "facebook.com" or dom.endswith(".facebook.com")


def save_session(cookies, user_agent, path=None):
    """Cookies de Facebook seulement, fichier 600 dans un dossier 700, écrit d'un coup."""
    path = Path(path or session_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    keep = ("name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite")
    data = {"user_agent": user_agent or "", "saved_at": int(time.time()),
            "cookies": [{k: c[k] for k in keep if k in c} for c in cookies if _facebook_cookie(c)]}
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return len(data["cookies"])


def load_session(path=None):
    data = core.load_json(path or session_path())
    return data if isinstance(data.get("cookies"), list) else None


def logged_in(cookies, now=None):
    """Session utilisable : `c_user` et `xs` présents et pas expirés."""
    now = time.time() if now is None else now
    names = {c.get("name") for c in cookies or ()
             if _facebook_cookie(c) and (not c.get("expires") or c["expires"] <= 0 or c["expires"] > now)}
    return {"c_user", "xs"} <= names


def require_session():
    s = load_session()
    if not s or not logged_in(s["cookies"]):
        raise SessionError("Pas de session Facebook (ou session expirée) : lance `ccs market login` "
                           "et connecte-toi dans le Chrome qui s'ouvre sur pc-bureau.")
    return s


# ---------------------------------------------------------------- ssh vers pc-bureau

def ssh_base(cfg):
    opts = {"HostName": cfg["hostname"], "HostKeyAlias": cfg["host_key_alias"],
            "BatchMode": "yes", "ConnectTimeout": "10", "ExitOnForwardFailure": "yes",
            "ServerAliveInterval": "15", "ControlMaster": "no", "ControlPath": "none",
            "LogLevel": "ERROR"}
    return ["ssh", *[x for k, v in opts.items() for x in ("-o", f"{k}={v}")]]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def is_this_machine(addr):
    """Vrai si `addr` est une adresse de cette machine (on tourne sur pc-bureau lui-même)."""
    try:
        with socket.socket(socket.AF_INET6 if ":" in addr else socket.AF_INET) as s:
            s.bind((addr, 0))
            return True
    except OSError:
        return False


class Tunnel:
    """`ssh -D` (SOCKS) ou `ssh -L` vers pc-bureau, fermé à la sortie du bloc `with`."""

    def __init__(self, cfg, forward=None, popen=subprocess.Popen, timeout=20):
        self.cfg = cfg
        self.port = free_port()
        self.forward = forward             # None : SOCKS (-D) ; port distant : -L
        self.popen = popen
        self.timeout = timeout
        self.proc = None

    def argv(self):
        spec = (["-D", f"127.0.0.1:{self.port}"] if self.forward is None
                else ["-L", f"127.0.0.1:{self.port}:127.0.0.1:{self.forward}"])
        return [*ssh_base(self.cfg), *spec, "-N", self.cfg["host"]]

    def __enter__(self):
        self.proc = self.popen(self.argv(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                break
            if _port_open(self.port):
                return self
            time.sleep(0.3)
        self.close()
        raise TunnelError(f"pc-bureau ne répond pas par le réseau maillé ({self.cfg['hostname']}) : "
                          "rien n'a été envoyé à Facebook. Vérifie que pc-bureau est allumé et "
                          "que Tailscale y tourne (`tailscale ping pc-bureau`), puis réessaie.")

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        self.proc = None

    def __exit__(self, *_):
        self.close()


def _http_get(sock, host, path):
    ctx = ssl.create_default_context()
    with ctx.wrap_socket(sock, server_hostname=host) as s:
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: curl/8.5.0\r\n"
                  "Accept: text/plain\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while len(data) < 65536:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    if b" 200 " not in head.split(b"\r\n", 1)[0]:
        raise OSError("réponse inattendue")
    return body.decode("ascii", "replace").strip()


def socks_connect(port, host, dport=443, timeout=15):
    """Connexion TCP à `host:dport` par le SOCKS5 local (nom résolu par pc-bureau)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            raise OSError("SOCKS refusé")
        name = host.encode()
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack(">H", dport))
        rep = s.recv(4)
        if len(rep) < 4 or rep[1] != 0:
            raise OSError("SOCKS : connexion refusée")
        skip = {1: 4, 4: 16}.get(rep[3])
        skip = skip if skip is not None else s.recv(1)[0]
        s.recv(skip + 2)
        return s
    except Exception:
        s.close()
        raise


_IP = re.compile(r"^[0-9a-fA-F.:]{3,45}$")


def public_ip(port=None, services=IP_SERVICES):
    """Adresse publique vue d'Internet : par le SOCKS `port`, ou en direct (None). None si
    aucun service ne répond."""
    for host, path in services:
        try:
            sock = socks_connect(port, host) if port else socket.create_connection((host, 443), timeout=10)
            ip = _http_get(sock, host, path)
            if _IP.match(ip):
                return ip
        except OSError:
            continue
    return None


def check_exit(port, cfg, lookup=public_ip):
    """L'adresse de sortie du tunnel doit être celle de pc-bureau : ni celle du VPS, ni
    inconnue. Renvoie l'adresse vue."""
    seen = lookup(port)
    if not seen:
        raise TunnelError("Impossible de vérifier l'adresse de sortie par pc-bureau : rien n'a été "
                          "envoyé à Facebook.")
    direct = lookup(None)
    if seen in {cfg["vps_ip"], direct}:
        raise TunnelError(f"La sortie par le tunnel donne l'adresse du VPS ({seen}), pas celle de "
                          "pc-bureau : rien n'a été envoyé à Facebook.")
    return seen


# ---------------------------------------------------------------- WebSocket et CDP

class WebSocket:
    """Client WebSocket minimal (RFC 6455, texte seulement, sans extension) : CDP ne demande pas
    plus, et le paquet `websockets` n'est pas une dépendance de CCS."""

    def __init__(self, url, timeout=30):
        u = urllib.parse.urlsplit(url)
        if u.scheme != "ws" or u.hostname not in ("127.0.0.1", "localhost"):
            raise MarketError("CDP : seulement ws:// en local")
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (f"?{u.query}" if u.query else "")
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise MarketError("CDP : poignée de main refusée")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise MarketError("CDP : poignée de main refusée")
        self.buf = b""

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise MarketError("CDP : connexion fermée")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, opcode, payload):
        n = len(payload)
        head = bytes([0x80 | opcode])
        head += (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n)
                 if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, text):
        self._frame(0x1, text.encode())

    def recv(self):
        parts = []
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            op = b0 & 0x0F
            if op == 0x8:
                raise MarketError("CDP : connexion fermée")
            if op == 0x9:
                self._frame(0xA, data)
                continue
            if op in (0x0, 0x1, 0x2):
                parts.append(data)
                if b0 & 0x80:
                    return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self._frame(0x8, b"")
        except OSError:
            pass
        self.sock.close()


class Cdp:
    """Appels CDP (`call`) sur un transport qui a `send(text)` et `recv() → text`."""

    def __init__(self, ws):
        self.ws = ws
        self.ids = 0

    def call(self, method, params=None):
        self.ids += 1
        mid = self.ids
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise MarketError(f"CDP {method} : {msg['error'].get('message', 'erreur')}")
                return msg.get("result") or {}

    def evaluate(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True})
        if r.get("exceptionDetails"):
            raise MarketError("Lecture de la page impossible (script refusé).")
        return (r.get("result") or {}).get("value")

    def close(self):
        self.ws.close()


def http_json(port, path, timeout=5):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------- Chrome du VPS

def find_chrome(cfg=None, home=None):
    """Chrome sans interface : réglage `chrome`, sinon navigateurs de Playwright (le plus
    récent, la version « headless shell » d'abord), sinon chromium / google-chrome du système."""
    cfg = cfg or config()
    if cfg.get("chrome"):
        return cfg["chrome"] if os.access(cfg["chrome"], os.X_OK) else None
    base = Path(home or Path.home()) / ".cache" / "ms-playwright"

    def ver(p):
        m = re.search(r"-(\d+)/", p)
        return int(m.group(1)) if m else 0
    for pattern in ("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
                    "chromium-*/chrome-linux*/chrome"):
        found = sorted(glob.glob(str(base / pattern)), key=ver, reverse=True)
        found = [p for p in found if os.access(p, os.X_OK)]
        if found:
            return found[0]
    for name in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def chrome_argv(binary, profile, proxy_port, user_agent, sandbox=False):
    argv = [binary, f"--user-data-dir={profile}", "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            f"--proxy-server=socks5://127.0.0.1:{proxy_port}",
            # rien ne se résout ni ne sort en dehors du proxy (pas de fuite DNS par le VPS)
            "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
            "--blink-settings=imagesEnabled=false", "--disable-blink-features=AutomationControlled",
            "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--disable-dev-shm-usage",
            "--disable-extensions", "--disable-background-networking", "--disable-sync",
            "--mute-audio", "--lang=fr-FR", "--window-size=1366,900"]
    if not sandbox:
        argv.append("--no-sandbox")
    if user_agent:
        argv.append(f"--user-agent={user_agent}")
    if "headless-shell" not in os.path.basename(binary):
        argv.append("--headless=new")
    argv.append("about:blank")
    return argv


class Browser:
    """Chrome sans interface, profil jetable, fermé (et profil effacé) à la sortie du `with`."""

    def __init__(self, cfg, proxy_port, user_agent, popen=subprocess.Popen, timeout=30):
        self.cfg, self.proxy_port, self.user_agent = cfg, proxy_port, user_agent
        self.popen, self.timeout = popen, timeout
        self.proc = self.profile = self.cdp = None

    def __enter__(self):
        binary = find_chrome(self.cfg)
        if not binary:
            raise MarketError("Chrome introuvable sur cette machine (navigateurs de Playwright dans "
                              "~/.cache/ms-playwright, ou réglage « chrome » de "
                              "~/.config/ccs/market/config.json).")
        self.profile = tempfile.mkdtemp(prefix="ccs-market-")
        self.proc = self.popen(chrome_argv(binary, self.profile, self.proxy_port, self.user_agent,
                                           self.cfg.get("sandbox", False)),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            port = self._devtools_port()
            pages = [t for t in http_json(port, "/json/list") if t.get("type") == "page"]
            if not pages:
                raise MarketError("Chrome n'a pas ouvert de page.")
            self.cdp = Cdp(WebSocket(pages[0]["webSocketDebuggerUrl"], timeout=60))
        except BaseException:
            self.close()
            raise
        return self.cdp

    def _devtools_port(self):
        f = Path(self.profile) / "DevToolsActivePort"
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                break
            try:
                return int(f.read_text().split()[0])
            except (OSError, ValueError, IndexError):
                time.sleep(0.2)
        raise MarketError("Chrome ne démarre pas sur cette machine.")

    def close(self):
        if self.cdp is not None:
            try:
                self.cdp.call("Browser.close")
            except (MarketError, OSError, ValueError):
                pass
            try:
                self.cdp.close()
            except OSError:
                pass
            self.cdp = None
        if self.proc is not None:
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(5)
            self.proc = None
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = None

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------- adresses

_ITEM = re.compile(r"^https?://(?:www\.|m\.|web\.)?facebook\.com/marketplace/item/(\d+)")
_PROFILE = re.compile(r"^https?://(?:www\.|m\.|web\.)?facebook\.com/marketplace/profile/(\d+)")


def _ref(ref, regex):
    ref = (ref or "").strip()
    if re.fullmatch(r"\d{5,25}", ref):
        return ref
    m = regex.match(ref)
    return m.group(1) if m else None


def item_url(ref):
    """Adresse canonique d'une annonce (lien ou numéro) ; MarketError sinon."""
    n = _ref(ref, _ITEM)
    if not n:
        raise MarketError("Lien d'annonce attendu : https://www.facebook.com/marketplace/item/<numéro>/")
    return f"{FB}/marketplace/item/{n}/"


def seller_url(ref):
    n = _ref(ref, _PROFILE)
    if not n:
        raise MarketError("Lien de vendeur attendu : https://www.facebook.com/marketplace/profile/<numéro>/")
    return f"{FB}/marketplace/profile/{n}/"


def search_url(query, city="lome", min_price=None, max_price=None):
    if not re.fullmatch(r"[a-z0-9-]{2,40}|\d{5,25}", city or ""):
        raise MarketError("Ville invalide (ex. lome, kara, ou le numéro de la ville Marketplace).")
    q = {"query": query.strip()}
    if min_price is not None:
        q["minPrice"] = int(min_price)
    if max_price is not None:
        q["maxPrice"] = int(max_price)
    q["exact"] = "false"
    return f"{FB}/marketplace/{city}/search?{urllib.parse.urlencode(q)}"


# ---------------------------------------------------------------- lecture des pages

_PRICE = re.compile(r"^(?:(\d[\d\s  .]*)\s*(?:F\s*CFA|FCFA|CFA|XOF|F)|Gratuit|Free)$", re.I)
NOISE = {"annonce récente", "juste mis en vente", "nouveau", "nouvelle annonce", "sponsorisé",
         "baisse de prix", "vendu", "en attente", "just listed"}


def parse_price(text):
    """« 22 000 CFA » → 22000 ; « Gratuit » → 0 ; autre → None."""
    m = _PRICE.match((text or "").strip())
    if not m:
        return None
    return int(re.sub(r"\D", "", m.group(1))) if m.group(1) else 0


@dataclasses.dataclass
class Card:
    id: str
    url: str
    price: int = None
    price_text: str = ""
    title: str = ""
    city: str = ""
    old_price: int = None


def parse_card(href, text):
    """Carte d'annonce (lien + texte de la vignette : `prix | [ancien prix] | titre | ville`)."""
    m = re.search(r"/marketplace/item/(\d+)", href or "")
    if not m:
        return None
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    lines = [ln for ln in lines if ln.lower() not in NOISE]
    card = Card(id=m.group(1), url=f"{FB}/marketplace/item/{m.group(1)}/")
    rest = []
    for ln in lines:
        p = parse_price(ln)
        if p is not None and not rest:
            if card.price is None:
                card.price, card.price_text = p, ln
            elif card.old_price is None:
                card.old_price = p
            continue
        rest.append(ln)
    if rest:
        card.title = rest[0]
    if len(rest) > 1:
        card.city = rest[1]
    return card


SECTION_ENDS = ("Informations vendeur", "Informations sur le vendeur", "Infos sur le vendeur",
                "Seller information")
DETAIL_LABELS = ("Détails", "Details")
APPROX = ("L'emplacement est approximatif", "Location is approximate")
SKIP_SELLER = {"Détails du vendeur", "Seller details", "Suivre", "Envoyer un message"}


def parse_item(text, url=""):
    """Page d'annonce (texte de la zone de l'annonce) → titre, prix, lieu, état, description,
    vendeur. Les métas `og:` sont vides : tout vient du texte."""
    lines = [ln.strip() for ln in (text or "").split("\n")]
    lines = [ln for ln in lines if ln]
    out = {"url": url, "title": "", "price": None, "price_text": "", "place": "", "condition": "",
           "description": "", "seller": ""}
    for i, ln in enumerate(lines):
        p = parse_price(ln)
        if p is not None and i > 0:
            out["price"], out["price_text"] = p, ln
            out["title"] = lines[i - 1]
            break
    for ln in lines:
        m = re.match(r"^(?:Mis en vente|Publié|Listed)\b.*?\b(?:à|in)\s+(.+)$", ln)
        if m:
            out["place"] = m.group(1)
            break
    start = next((i for i, ln in enumerate(lines) if ln in DETAIL_LABELS), None)
    end = next((i for i, ln in enumerate(lines) if ln in SECTION_ENDS), None)
    if start is not None:
        details = lines[start + 1:end if end is not None and end > start else len(lines)]
        desc = []
        k = 0
        while k < len(details):
            ln = details[k]
            m = re.match(r"^(État|Condition)\s*:?\s*(.*)$", ln)
            if m and not out["condition"]:
                if m.group(2):
                    out["condition"] = m.group(2)
                elif k + 1 < len(details):
                    out["condition"] = details[k + 1]
                    k += 1
            elif k + 1 < len(details) and details[k + 1] in APPROX:
                k += 1                      # lieu de la carte, déjà donné par « Mis en vente … à »
            elif ln not in ("Voir la traduction", "Voir plus", "Voir moins", "See more"):
                desc.append(ln)
            k += 1
        out["description"] = "\n".join(desc)
    if end is not None:
        out["seller"] = next((ln for ln in lines[end + 1:] if ln not in SKIP_SELLER), "")
    return out


def is_login(state):
    """La page est celle de connexion (ou un point de contrôle) : session expirée."""
    url = (state or {}).get("url") or ""
    if re.search(r"facebook\.com/(login|checkpoint|recover)|/login\.php", url):
        return True
    return bool(state.get("login_text")) and not state.get("items")


def choose_dialog(dialogs):
    """Fenêtre du vendeur parmi les `div[role="dialog"]` de la page : jamais Messenger (la liste
    des discussions est aussi un dialogue), une qui contient des annonces ; la plus fournie.
    Renvoie son indice, ou None."""
    ok = [d for d in dialogs or () if not d.get("messenger") and (d.get("items") or 0) > 0]
    return max(ok, key=lambda d: d["items"])["index"] if ok else None


def accumulate(fetch, limit, patience=5, max_rounds=200, pause=lambda: None):
    """Union des cartes de `fetch()` (une lecture + un défilement) jusqu'à `patience` tours sans
    nouveauté, `limit` annonces ou `max_rounds` tours. Ordre de première apparition."""
    seen = {}
    idle = 0
    for n in range(max_rounds):
        new = 0
        for raw in fetch() or ():
            card = parse_card(raw.get("href"), raw.get("text"))
            if card and card.id not in seen:
                seen[card.id] = card
                new += 1
        if len(seen) >= limit:
            break
        idle = 0 if new else idle + 1
        if idle >= patience or n == max_rounds - 1:
            break
        pause()
    return list(seen.values())[:limit]


# Scripts lus dans la page. Ils ne renvoient jamais de texte de Messenger : `dialogs` ne donne que
# des nombres et des drapeaux, les autres lisent la zone principale ou une fenêtre choisie.
JS_MESSENGER = ('(d) => !!d.querySelector(\'a[href*="/messages/"], a[href*="messenger.com"], '
                '[aria-label*="Messenger"], [aria-label="Discussions"], [aria-label="Chats"]\')')
JS_STATE = """(() => { const t = document.body ? document.body.innerText.slice(0, 4000) : "";
  return { url: location.href, ready: document.readyState,
    login_text: /Connexion ou inscription|Se connecter à Facebook|Log in to Facebook|Log into Facebook|Mot de passe oublié/.test(t),
    items: document.querySelectorAll('a[href*="/marketplace/item/"]').length }; })()"""
JS_DIALOGS = f"""(() => {{ const messenger = {JS_MESSENGER};
  return [...document.querySelectorAll('div[role="dialog"]')].map((d, index) => ({{ index,
    items: d.querySelectorAll('a[href*="/marketplace/item/"]').length, messenger: messenger(d) }})); }})()"""


def js_cards(scope, scroll=True):
    """Cartes (`href`, `text`) de la zone `scope` (« main » ou numéro de dialogue), puis défilement."""
    pick = ('document.querySelector(\'div[role="main"]\')' if scope == "main"
            else f'document.querySelectorAll(\'div[role="dialog"]\')[{int(scope)}]')
    return f"""(() => {{ const messenger = {JS_MESSENGER}; const root = {pick};
  if (!root || ({'false' if scope == 'main' else 'messenger(root)'})) return [];
  const links = [...root.querySelectorAll('a[href*="/marketplace/item/"]')];
  const out = links.map((a) => ({{ href: a.getAttribute('href'), text: (a.innerText || '').slice(0, 400) }}));
  if ({'true' if scroll else 'false'} && links.length) {{
    links[links.length - 1].scrollIntoView({{ block: 'end' }});
    for (const el of [root, ...root.querySelectorAll('div')]) {{
      if (el.scrollHeight > el.clientHeight + 20 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) el.scrollTop = el.scrollHeight;
    }}
    window.scrollTo(0, document.body.scrollHeight);
  }}
  return out; }})()"""


def js_dialog_head(index):
    """Premières lignes d'une fenêtre (déjà vérifiée : pas Messenger), pour le nom du vendeur."""
    return f"""(() => {{ const d = document.querySelectorAll('div[role="dialog"]')[{int(index)}];
  return d ? (d.innerText || '').split('\\n').map((s) => s.trim()).filter(Boolean).slice(0, 8) : []; }})()"""


JS_ITEM = f"""(() => {{ const messenger = {JS_MESSENGER};
  const zones = [document.querySelector('div[role="main"]'),
    ...[...document.querySelectorAll('div[role="dialog"]')].filter((d) => !messenger(d))].filter(Boolean);
  const zone = zones.find((z) => /\\n(Détails|Details)\\n/.test(z.innerText || '')) || zones[0];
  const prof = zone ? zone.querySelector('a[href*="/marketplace/profile/"]') : null;
  return {{ text: zone ? (zone.innerText || '').slice(0, 20000) : '',
    seller_url: prof ? prof.getAttribute('href') : '' }}; }})()"""

HEAD_SKIP = {"Fermer", "Close", "Marketplace", "Suivre", "Envoyer un message", "Partager"}


class Facebook:
    """Lecture de Marketplace dans un Chrome déjà lancé (`cdp`)."""

    def __init__(self, cdp, cfg, sleep=time.sleep, uniform=random.uniform):
        self.cdp, self.cfg, self.sleep, self.uniform = cdp, cfg, sleep, uniform

    def _pause(self, key):
        lo, hi = self.cfg[key]
        self.sleep(self.uniform(lo, hi))

    def setup(self, session):
        self.cdp.call("Network.enable")
        self.cdp.call("Network.setBlockedURLs", {"urls": BLOCKED})
        cookies = []
        for c in session["cookies"]:
            c = {k: c[k] for k in ("name", "value", "domain", "path", "expires", "httpOnly",
                                   "secure", "sameSite") if k in c and c[k] not in (None, "")}
            if isinstance(c.get("expires"), (int, float)) and c["expires"] <= 0:
                c.pop("expires")
            cookies.append(c)
        self.cdp.call("Network.setCookies", {"cookies": cookies})

    def goto(self, url):
        self.cdp.call("Page.enable")
        self.cdp.call("Page.navigate", {"url": url})
        state = {}
        for _ in range(60):
            self.sleep(0.5)
            state = self.cdp.evaluate(JS_STATE) or {}
            if state.get("ready") == "complete":
                break
        self._pause("page_delay")
        state = self.cdp.evaluate(JS_STATE) or state
        if is_login(state):
            raise SessionError("Facebook demande de se reconnecter (session expirée ou point de "
                               "contrôle) : lance `ccs market login` puis repose la question.")
        return state

    def cookies(self):
        return [c for c in self.cdp.call("Network.getAllCookies").get("cookies", [])
                if _facebook_cookie(c)]

    def search(self, query, city=None, min_price=None, max_price=None, limit=None):
        self.goto(search_url(query, city or self.cfg["city"], min_price, max_price))
        return accumulate(lambda: self.cdp.evaluate(js_cards("main")),
                          limit or self.cfg["search_limit"], patience=2,
                          max_rounds=self.cfg["search_rounds"],
                          pause=lambda: self._pause("scroll_delay"))

    def seller(self, url, limit=None):
        self.goto(seller_url(url))
        index = None
        for _ in range(4):
            index = choose_dialog(self.cdp.evaluate(JS_DIALOGS))
            if index is not None:
                break
            self.sleep(2)
        if index is None:
            raise MarketError("Fenêtre du vendeur introuvable sur la page (aucune annonce "
                              "visible) : vérifie le lien du vendeur.")
        head = self.cdp.evaluate(js_dialog_head(index)) or []
        name = next((ln for ln in head if ln not in HEAD_SKIP and parse_price(ln) is None), "")
        cards = accumulate(lambda: self.cdp.evaluate(js_cards(index)),
                           limit or self.cfg["seller_limit"], patience=self.cfg["patience"],
                           max_rounds=self.cfg["seller_rounds"],
                           pause=lambda: self._pause("scroll_delay"))
        return {"name": name, "url": seller_url(url), "items": cards}

    def item(self, url):
        url = item_url(url)
        self.goto(url)
        raw = self.cdp.evaluate(JS_ITEM) or {}
        out = parse_item(raw.get("text", ""), url)
        m = re.search(r"/marketplace/profile/(\d+)", raw.get("seller_url") or "")
        out["seller_url"] = f"{FB}/marketplace/profile/{m.group(1)}/" if m else ""
        return out


# ---------------------------------------------------------------- commandes

def run(action, cfg=None, tunnel=Tunnel, browser=Browser, exit_check=check_exit, log=None):
    """Tunnel → vérification de la sortie → Chrome → `action(Facebook)` → cookies remis à jour.
    Tout est fermé à la fin, quoi qu'il arrive."""
    cfg = cfg or config()
    session = require_session()
    with tunnel(cfg) as t:
        ip = exit_check(t.port, cfg)
        if log:
            log(f"Sortie par pc-bureau ({ip}).")
        with browser(cfg, t.port, session.get("user_agent")) as cdp:
            fb = Facebook(cdp, cfg)
            fb.setup(session)
            result = action(fb)
            try:
                fresh = fb.cookies()
                if logged_in(fresh):
                    save_session(fresh, session.get("user_agent"))
            except (MarketError, OSError):
                pass
            return result


def fmt_price(card):
    if card.price is None:
        return card.price_text or "?"
    return "Gratuit" if card.price == 0 else f"{card.price:,} CFA".replace(",", " ")


def format_cards(cards):
    lines = []
    for c in cards:
        old = f" (avant {c.old_price:,} CFA)".replace(",", " ") if c.old_price else ""
        lines.append(f"{fmt_price(c)}{old} | {c.title or '?'} | {c.city or '?'} | {c.url}")
    return "\n".join(lines)


def format_item(it):
    rows = [("Titre", it["title"]), ("Prix", it["price_text"]), ("Lieu", it["place"]),
            ("État", it["condition"]), ("Vendeur", it["seller"]), ("Page du vendeur", it.get("seller_url")),
            ("Lien", it["url"])]
    out = [f"{k} : {v}" for k, v in rows if v]
    if it["description"]:
        out += ["Description :", it["description"]]
    return "\n".join(out)


def status(cfg=None, tunnel=Tunnel, lookup=public_ip):
    """État lisible : session, Chrome, tunnel par pc-bureau et adresse de sortie."""
    cfg = cfg or config()
    lines = []
    s = load_session()
    if s and logged_in(s["cookies"]):
        when = time.strftime("%d/%m/%Y %H:%M", time.localtime(s.get("saved_at") or 0))
        lines.append(f"Session Facebook : présente (mise à jour le {when}).")
    else:
        lines.append("Session Facebook : absente ou expirée → `ccs market login`.")
    chrome = find_chrome(cfg)
    lines.append(f"Chrome : {chrome or 'introuvable'}")
    ok = bool(chrome and s and logged_in(s["cookies"]))
    try:
        with tunnel(cfg) as t:
            ip = check_exit(t.port, cfg, lookup)
        lines.append(f"Tunnel par pc-bureau ({cfg['hostname']}) : ouvert, sortie {ip}.")
    except TunnelError as e:
        lines.append(f"Tunnel par pc-bureau : {e}")
        ok = False
    return ok, "\n".join(lines)


LOGIN_SCRIPT = r"""
uid=$(id -u); export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
eval "$(systemctl --user show-environment 2>/dev/null | grep -E '^(DISPLAY|WAYLAND_DISPLAY|XAUTHORITY|DBUS_SESSION_BUS_ADDRESS)=' | sed 's/^/export /')"
if [ -z "$DISPLAY$WAYLAND_DISPLAY" ]; then
  [ -S "$XDG_RUNTIME_DIR/wayland-0" ] && export WAYLAND_DISPLAY=wayland-0
  [ -e /tmp/.X11-unix/X0 ] && export DISPLAY=:0
fi
[ -n "$DISPLAY$WAYLAND_DISPLAY" ] || { echo PAS_DE_SESSION; exit 3; }
command -v "$CHROME" >/dev/null || { echo PAS_DE_CHROME; exit 4; }
nohup "$CHROME" --user-data-dir="$HOME/.config/ccs-market-chrome" --remote-debugging-port="$PORT" \
  --remote-debugging-address=127.0.0.1 --no-first-run --no-default-browser-check --new-window \
  "https://www.facebook.com/login/" >/dev/null 2>&1 &
echo OK
"""


def login(cfg=None, wait_s=LOGIN_WAIT_S, out=print, run_cmd=subprocess.run, tunnel=Tunnel,
          connect=None, sleep=time.sleep):
    """Ouvre Chrome sur l'écran de pc-bureau (profil dédié), attend la connexion de Charles,
    exporte les cookies par CDP (tunnel `ssh -L`), les garde en 600 puis referme ce Chrome."""
    cfg = cfg or config()
    if is_this_machine(cfg["hostname"]):
        raise MarketError("`ccs market login` se lance depuis le VPS (ou le chat web), pas sur "
                          "pc-bureau : c'est le VPS qui garde la session Facebook. Chrome "
                          "s'ouvrira quand même ici, sur ton écran.")
    script = f"CHROME={cfg['remote_chrome']!s}; PORT={int(cfg['remote_port'])}\n" + LOGIN_SCRIPT
    try:
        r = run_cmd([*ssh_base(cfg), cfg["host"], "bash", "-s"], input=script, text=True,
                    capture_output=True, timeout=40)
    except subprocess.TimeoutExpired:
        r = None
    if r is None or r.returncode == 255:
        raise TunnelError(f"pc-bureau ne répond pas par le réseau maillé ({cfg['hostname']}).")
    said = (r.stdout or "").strip()
    if "PAS_DE_SESSION" in said:
        raise MarketError("Pas de session graphique ouverte sur pc-bureau : ouvre ta session, "
                          "puis relance `ccs market login`.")
    if "PAS_DE_CHROME" in said:
        raise MarketError(f"{cfg['remote_chrome']} n'est pas installé sur pc-bureau.")
    if "OK" not in said:
        raise MarketError("Chrome ne s'est pas lancé sur pc-bureau.")
    out("Chrome est ouvert sur l'écran de pc-bureau : connecte-toi à Facebook "
        f"(j'attends {wait_s // 60} min au plus).")
    connect = connect or _connect_browser
    with tunnel(cfg, forward=int(cfg["remote_port"])) as t:
        cdp, version = None, None
        for _ in range(60):
            try:
                cdp, version = connect(t.port)
                break
            except (OSError, ValueError, MarketError):
                sleep(1)
        if cdp is None:
            raise MarketError("Impossible de joindre le Chrome de pc-bureau (port de débogage).")
        try:
            end = time.monotonic() + wait_s
            while True:
                cookies = cdp.call("Storage.getCookies").get("cookies", [])
                if logged_in(cookies):
                    break
                if time.monotonic() > end:
                    raise SessionError("Pas de connexion à Facebook dans le temps imparti : relance "
                                       "`ccs market login` quand tu es devant pc-bureau.")
                sleep(5)
            n = save_session(cookies, version.get("User-Agent", ""))
            try:
                cdp.call("Browser.close")
            except (MarketError, OSError):
                pass
        finally:
            try:
                cdp.close()
            except OSError:
                pass
    out(f"Connecté : session gardée ({n} cookies, fichier privé). Chrome de pc-bureau refermé.")
    return n


def _connect_browser(port):
    version = http_json(port, "/json/version")
    u = urllib.parse.urlsplit(version["webSocketDebuggerUrl"])
    return Cdp(WebSocket(f"ws://127.0.0.1:{port}{u.path}", timeout=30)), version


# ---------------------------------------------------------------- chat Market

CLAUDE_MD = """# Market : Facebook Marketplace au Togo

Tu es **Market**, l'assistant d'achat de Charles. Il te pose une question (« le routeur le moins
cher compatible WireGuard à Lomé ») ou te donne le lien d'un vendeur ; tu cherches sur Facebook
Marketplace au Togo et tu réponds **dans ce chat seulement** (pas de surveillance, pas d'alerte).

## Outils (par Bash)
- `ccs market search "<mots>" [--min N] [--max N] [--city lome]` : annonces d'une recherche,
  une par ligne : `prix | titre | ville | lien`. Essaie 1 à 3 formulations (français, marque,
  modèle) ; pas plus sans raison.
- `ccs market seller <lien ou numéro>` : toutes les annonces d'un vendeur (boutique).
- `ccs market item <lien>` : détails d'une annonce (état, description, vendeur). Seulement pour
  les meilleures candidates (5 au plus).
- `ccs market status` : session Facebook, Chrome, tunnel par pc-bureau.
- Ajoute `--json` pour une sortie JSON.
- WebSearch / WebFetch : vérifier les caractéristiques des modèles (compatibilité, version
  matérielle, avis), jamais pour Facebook.

Chaque commande prend du temps (rythme humain, quelques secondes par page) : n'en lance qu'une à
la fois et évite les pages inutiles.

## Réponse
1. Un **classement** (meilleur rapport qualité-prix d'abord) : prix en CFA, titre, lieu, **lien
   de l'annonce**, et en une ou deux lignes pourquoi (caractéristiques vérifiées, état, limites).
2. Les alternatives écartées et la raison (incompatible, trop cher, instable…).
3. Ce qui reste à vérifier avec le vendeur (version matérielle, garantie, état réel).
Réponses courtes et lisibles sur un téléphone.

## Règles
- Si une commande dit que **pc-bureau ne répond pas**, dis-le simplement et arrête : rien ne
  doit passer par un autre chemin.
- Si la **session Facebook a expiré**, dis à Charles de lancer `ccs market login` (Chrome s'ouvre
  sur l'écran de pc-bureau, il s'y connecte) ; tu peux la lancer toi-même s'il te le demande.
- Ne lis jamais Messenger, ne contacte aucun vendeur, ne publie rien.
- Conversation trop longue : `ccs chat clear` à la fin d'une réponse quand Charles change de sujet.
"""

CLAUDE_SETTINGS = {"permissions": {"allow": ["Bash(ccs market:*)", "WebSearch", "WebFetch"]}}


def workspace_dir():
    return core.ccs_dir("data") / "market"


def workspace(path=None):
    """Dossier du chat Market, créé ou remis à jour (CLAUDE.md, droits des outils)."""
    d = Path(path or workspace_dir())
    (d / ".claude").mkdir(parents=True, exist_ok=True)
    for f, text in ((d / "CLAUDE.md", CLAUDE_MD),
                    (d / ".claude" / "settings.json", json.dumps(CLAUDE_SETTINGS, indent=2) + "\n")):
        try:
            same = f.read_text(encoding="utf-8") == text
        except OSError:
            same = False
        if not same:
            f.write_text(text, encoding="utf-8")
    return d


def transcript(cwd, session_id):
    from . import sessions
    return sessions.transcript_path(str(cwd), session_id)


def latest_session(path=None):
    """Dernière conversation du chat Market (identifiant), ou None."""
    from . import sessions
    convs = sessions.recent_conversations(str(Path(path or workspace_dir())), limit=1)
    return convs[0].session_id if convs else None
