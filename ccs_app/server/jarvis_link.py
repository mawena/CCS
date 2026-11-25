"""Lien du pont vers le cerveau de Jarvis (projet voisin) : réseau maillé (tunnel Ricochet en
secours), TLS épinglé, WebSocket.

Le cerveau écoute en WebSocket sur TLS 1.3 (port 7341 de `lp-home` par défaut), avec un
certificat auto-signé : on ne vérifie ni nom ni autorité, seulement l'**empreinte** du certificat
(SHA-256 du certificat DER, en base64url sans remplissage, 43 caractères), donnée à l'appairage
par l'adresse `jarvis://pair?…&fp=…`. Le chemin du WebSocket est indifférent (`/`).

Le transport est `ricochet-agent tunnel <machine> --port <port> --config <client.toml>`, qui relie
son entrée et sa sortie au port de la machine : on lui donne un bout d'une paire de sockets et on
fait le TLS sur l'autre bout. Aucun port n'est ouvert sur ce serveur.

Le client WebSocket est écrit ici (RFC 6455, sans extension) : le paquet `websockets` n'est pas
une dépendance de CCS et `aiohttp` ne sait pas parler sur un socket déjà ouvert.
"""

import asyncio
import base64
import binascii
import hashlib
import hmac
import os
import re
import shutil
import socket
import ssl
import struct

# Cerveau → oreille : la réponse porte la voix de Jarvis en PCM base64 (une longue phrase à
# 22 050 Hz dépasse 1 Mo) ; on reste sous la ligne de 8 Mo du protocole des services.
MAX_INCOMING = 6 * 1024 * 1024
# Oreille → cerveau : messages JSON courts, et trames de son `0x01` + phrase u32 + 16 000
# échantillons i16 au plus (crates/jarvis-protocol/src/frame.rs).
MAX_TEXT_OUT = 64 * 1024
MAX_FRAME_SAMPLES = 16_000
MAX_BINARY_OUT = 5 + 2 * MAX_FRAME_SAMPLES
OPEN_TIMEOUT = 15
_FP = re.compile(r"^[A-Za-z0-9_-]{43}$")
_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class LinkError(Exception):
    """Cerveau injoignable ou lien rompu ; le message est lisible tel quel."""


def parse_fingerprint(text):
    """Empreinte en base64url sans remplissage (43 caractères) → 32 octets, ou None."""
    if not isinstance(text, str) or not _FP.match(text):
        return None
    try:
        raw = base64.urlsafe_b64decode(text + "=")
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 32 else None


def short_fingerprint(raw):
    """Forme courte à comparer à l'œil (comme `jarvis pair`) : `A1B2-C3D4-E5F6-0718`."""
    return "-".join(raw[i:i + 2].hex().upper() for i in range(0, 8, 2))


# ---- tunnel Ricochet ------------------------------------------------------------------------

async def open_tunnel(machine, port, agent=None, config=None):
    """(socket, processus) : `ricochet-agent tunnel` branché sur un bout d'une paire de sockets."""
    from .. import distant
    agent = agent or shutil.which("ricochet-agent")
    if not agent:
        raise LinkError("ricochet-agent n'est pas installé sur ce serveur")
    config = config or distant.client_path()
    ours, theirs = socket.socketpair()
    try:
        proc = await asyncio.create_subprocess_exec(
            agent, "tunnel", machine, "--port", str(port), "--config", str(config),
            stdin=theirs, stdout=theirs, stderr=asyncio.subprocess.PIPE)
    except OSError as e:
        ours.close()
        raise LinkError(f"ricochet-agent impossible à lancer : {e.strerror or e}") from None
    finally:
        theirs.close()
    return ours, proc


MESH_CONNECT_TIMEOUT = 4


async def open_mesh(machine, port, address=None, timeout=MESH_CONNECT_TIMEOUT):
    """(socket, None) : connexion directe par le réseau maillé, ou None si la machine n'y est pas
    en ligne ou ne répond pas (Ricochet prend alors le relais)."""
    from .. import distant
    if address is None:
        try:
            address = await asyncio.to_thread(
                distant.mesh_address, distant.Machine(id=machine), distant.load_overrides())
        except distant.DistantError:
            address = None
    if not address:
        return None
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        await asyncio.wait_for(loop.sock_connect(sock, (address, int(port))), timeout)
    except (OSError, asyncio.TimeoutError):
        sock.close()
        return None
    return sock, None


async def stop_process(proc):
    if proc is None or proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), 5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


async def process_error(proc):
    """Dernière ligne d'erreur du tunnel s'il s'est arrêté (sans attendre plus d'une seconde)."""
    if proc is None:
        return ""
    try:
        await asyncio.wait_for(proc.wait(), 1)
        err = (await asyncio.wait_for(proc.stderr.read(4096), 2)).decode("utf-8", "replace")
    except (asyncio.TimeoutError, AttributeError, ValueError):
        return ""
    lines = [x.strip() for x in err.strip().splitlines() if x.strip()]
    return lines[-1][:200] if lines else ""


# ---- WebSocket ------------------------------------------------------------------------------

def _mask(data, key):
    n = len(data)
    if not n:
        return b""
    k = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(k, "big")).to_bytes(n, "big")


class Socket:
    """WebSocket client ouvert (TLS épinglé déjà vérifié)."""

    def __init__(self, reader, writer, max_incoming=MAX_INCOMING):
        self.reader = reader
        self.writer = writer
        self.max_incoming = max_incoming
        self.closed = False
        self.close_reason = ""
        self._lock = asyncio.Lock()

    async def _frame(self, opcode, payload=b""):
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", n)
        key = os.urandom(4)
        async with self._lock:
            if self.closed and opcode != 0x8:
                raise LinkError("lien fermé")
            self.writer.write(head + key + _mask(payload, key))
            await self.writer.drain()

    async def send_text(self, text):
        await self._frame(0x1, text.encode("utf-8"))

    async def send_binary(self, data):
        await self._frame(0x2, bytes(data))

    async def _read_frame(self):
        b1, b2 = await self.reader.readexactly(2)
        fin, opcode, masked, n = b1 & 0x80, b1 & 0x0F, b2 & 0x80, b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", await self.reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", await self.reader.readexactly(8))[0]
        if n > self.max_incoming:
            raise LinkError("message du cerveau trop gros")
        key = await self.reader.readexactly(4) if masked else None
        payload = await self.reader.readexactly(n)
        return bool(fin), opcode, _mask(payload, key) if key else payload

    async def recv(self):
        """("text", str) ou ("binary", bytes) ; None quand le cerveau ferme."""
        parts, kind, size = [], None, 0
        try:
            while True:
                fin, opcode, payload = await self._read_frame()
                if opcode == 0x9:                       # ping du cerveau (toutes les 10 s)
                    await self._frame(0xA, payload[:125])
                    continue
                if opcode == 0xA:
                    continue
                if opcode == 0x8:
                    if len(payload) > 2:
                        self.close_reason = payload[2:].decode("utf-8", "replace")[:120]
                    await self.close()
                    return None
                if opcode in (0x1, 0x2):
                    if kind is not None:
                        raise LinkError("trame du cerveau invalide")
                    kind, parts, size = opcode, [], 0
                elif opcode != 0x0 or kind is None:
                    raise LinkError("trame du cerveau invalide")
                size += len(payload)
                if size > self.max_incoming:
                    raise LinkError("message du cerveau trop gros")
                parts.append(payload)
                if fin:
                    data = b"".join(parts)
                    if kind == 0x1:
                        return "text", data.decode("utf-8")
                    return "binary", data
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError, UnicodeDecodeError):
            self.closed = True
            return None

    async def close(self, code=1000):
        if not self.closed:
            try:
                await asyncio.wait_for(self._frame(0x8, struct.pack("!H", code)), 1)
            except (asyncio.TimeoutError, ConnectionError, ssl.SSLError, RuntimeError, LinkError):
                pass
            self.closed = True
        try:
            self.writer.close()
        except (ConnectionError, RuntimeError):
            pass


def tls_context():
    """TLS 1.3 sans vérification de nom ni d'autorité : la confiance vient de l'empreinte."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    return ctx


async def connect(sock, fingerprint, max_incoming=MAX_INCOMING):
    """TLS sur `sock`, empreinte vérifiée avant tout envoi, puis poignée de main WebSocket."""
    try:
        reader, writer = await asyncio.open_connection(
            sock=sock, ssl=tls_context(), server_hostname="jarvis", limit=64 * 1024)
    except (ssl.SSLError, ConnectionError, OSError) as e:
        sock.close()
        raise LinkError(f"connexion TLS impossible ({e.__class__.__name__})") from None
    der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True) or b""
    if not hmac.compare_digest(hashlib.sha256(der).digest(), fingerprint):
        writer.close()
        raise LinkError("le certificat du cerveau ne correspond pas à l'empreinte d'appairage "
                        "(cerveau réinstallé ? refais l'appairage)")
    key = base64.b64encode(os.urandom(16))
    writer.write(b"GET / HTTP/1.1\r\nHost: jarvis\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                 b"Sec-WebSocket-Key: " + key + b"\r\nSec-WebSocket-Version: 13\r\n\r\n")
    try:
        await writer.drain()
        head = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, ssl.SSLError):
        writer.close()
        raise LinkError("le cerveau a refusé le WebSocket") from None
    lines = head.decode("latin-1").split("\r\n")
    headers = {k.strip().lower(): v.strip() for k, _, v in (x.partition(":") for x in lines[1:] if x)}
    accept = base64.b64encode(hashlib.sha1(key + _GUID).digest()).decode()
    if " 101 " not in lines[0] + " " or headers.get("sec-websocket-accept") != accept:
        writer.close()
        raise LinkError("le cerveau a refusé le WebSocket")
    return Socket(reader, writer, max_incoming)
