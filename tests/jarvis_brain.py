"""Faux cerveau de Jarvis pour les tests : WebSocket sur TLS 1.3, certificat auto-signé.

Il imite le protocole des oreilles (crates/jarvis-protocol) : `pair` → `paired` puis fermeture,
`hello` → `welcome`, `wake` + trames de son + `listen_end` → `response` avec la voix en PCM
base64, `status` → `status`. `bye` : fermeture avec une raison. Tout ce qu'il reçoit est noté."""

import base64
import datetime
import hashlib
import json
import ssl
import struct
from pathlib import Path

from aiohttp import WSMsgType, web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def make_cert(folder):
    """(certificat PEM, clé PEM, empreinte base64url du certificat DER)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "jarvis-brain")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    folder = Path(folder)
    cert_path, key_path = folder / "brain.pem", folder / "brain.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    der = cert.public_bytes(serialization.Encoding.DER)
    fp = base64.urlsafe_b64encode(hashlib.sha256(der).digest()).rstrip(b"=").decode()
    return cert_path, key_path, fp


class FakeBrain:
    def __init__(self, folder):
        self.cert, self.key, self.fingerprint = make_cert(folder)
        self.received = []                 # ("text", dict) ou ("binary", bytes)
        self.samples = 0
        self.closed = 0
        self.runner = None
        self.port = None

    async def start(self):
        app = web.Application()
        app.router.add_get("/", self.handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(self.cert, self.key)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0, ssl_context=ctx)
        await site.start()
        self.port = self.runner.addresses[0][1]

    async def stop(self):
        if self.runner is not None:
            await self.runner.cleanup()

    async def handler(self, request):
        ws = web.WebSocketResponse(max_msg_size=1024 * 1024)
        await ws.prepare(request)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    self.received.append(("binary", msg.data))
                    self.samples += (len(msg.data) - 5) // 2
                    continue
                if msg.type != WSMsgType.TEXT:
                    break
                m = json.loads(msg.data)
                self.received.append(("text", m))
                t = m.get("type")
                if t == "pair":
                    if m.get("code") != "482913":
                        await ws.send_json({"type": "rejected", "reason": {"kind": "wrong_code", "attempts_left": 2}})
                        await ws.close()
                        break
                    await ws.send_json({"type": "paired", "ear_id": "e1", "token": "jeton-oreille",
                                        "brain_id": "b1", "brain_name": "lp-home"})
                    await ws.close()
                    break
                if t == "hello":
                    if m.get("token") != "jeton-oreille":
                        await ws.send_json({"type": "rejected", "reason": {"kind": "bad_token"}})
                        await ws.close()
                        break
                    await ws.send_json({"type": "welcome", "version": 1, "brain_id": "b1",
                                        "brain_name": "lp-home",
                                        "status": {"mode": "local", "version": "0.5.0", "local_model": "x"}})
                elif t == "wake":
                    await ws.send_json({"type": "elected", "utterance": m["utterance"]})
                elif t == "listen_end":
                    pcm = struct.pack("<4h", 0, 1000, -1000, 0)
                    await ws.send_json({"type": "response", "utterance": m["utterance"], "response": {
                        "type": "heard", "text": "quelle heure est-il", "speech": "Il est midi.",
                        "ear_action": None,
                        "audio": {"pcm": base64.b64encode(pcm).decode(), "sample_rate": 22050}}})
                elif t == "big":
                    await ws.send_str(json.dumps({"type": "big", "data": "x" * m["size"]}))
                elif t == "binary_back":
                    await ws.send_bytes(b"\x02abc")
                elif t == "bye":
                    await ws.close(message=b"au revoir")
                    break
        finally:
            self.closed += 1
        return ws
