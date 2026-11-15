#!/usr/bin/env python3
"""Essai local de la version web (développement seulement, jamais installé).

Lance dans un seul processus : un ccs-auth dont le « PAM » accepte l'utilisateur courant avec
le mot de passe `essai`, un pont en mode local, et ccs-web sur http://127.0.0.1:8421.
`--connecte` : chaque requête porte une session déjà ouverte (pour les captures d'écran).
Le code TOTP courant est affiché toutes les 30 s.
"""

import argparse
import asyncio
import getpass
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("CCS_SERVER_ROOT", tempfile.mkdtemp(prefix="ccs-web-essai-"))

import pyotp  # noqa: E402
from aiohttp import web as aioweb  # noqa: E402

from ccs_app.server import auth, bridge, paths, rpc, totp, web  # noqa: E402
from ccs_app.server.tokens import TokenStore  # noqa: E402

PORT = 8421
FAKE = False


async def main(connected):
    user = getpass.getuser()
    loop = asyncio.get_running_loop()
    bridges = {}

    async def start_bridge(u):
        chat = None
        if FAKE:
            tests = Path(__file__).resolve().parent.parent / "tests"
            chat = {"claude": str(tests / "fake_claude.py"), "environ": {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "FAKE_CLAUDE_DELAY_MS": "40",
                "FAKE_CLAUDE_SCENARIO": str(tests / "fixtures" / "chat" / "permissions-allow-toujours.jsonl")}}
        # même assemblage que le service ccs-bridge@ (bridge.build), seul le faux claude change
        b = bridge.build(u, paths.bridge_key(u).read_bytes(), start_daemon=False, install_claude=False,
                         chat=chat)
        await b.start(paths.bridge_socket(u))
        bridges[u] = b

    tokens = TokenStore(paths.sessions_file())
    svc = auth.AuthService(tokens, pam_check=lambda u, p: (u, p) == (user, "essai"),
                           allowed=lambda u: u == user, host="127.0.0.1",
                           spawn_bridge=lambda u: asyncio.run_coroutine_threadsafe(start_bridge(u), loop).result(5),
                           refuse_delay=0, chown=lambda *_: None)
    server = rpc.RpcServer(svc.handlers())
    await server.start_unix(paths.auth_socket(), 0o600)
    app = web.make_app(web.AuthClient(), web.BridgeConnector(),
                       {"listen": f"127.0.0.1:{PORT}", "origin": f"http://127.0.0.1:{PORT}"})
    if connected:
        session = tokens.new_session(user)

        @aioweb.middleware
        async def inject(request, handler):
            if "ccs_session" not in request.cookies:
                headers = request.headers.copy()
                headers["Cookie"] = f"ccs_session={session}"
                request = request.clone(headers=headers)
            return await handler(request)
        app.middlewares.append(inject)
    runner = aioweb.AppRunner(app, access_log=None)
    await runner.setup()
    await aioweb.TCPSite(runner, "127.0.0.1", PORT).start()
    print(f"Version web d'essai : http://127.0.0.1:{PORT}  (utilisateur {user}, mot de passe « essai »)", flush=True)
    while True:
        secret = totp.load(user)
        if secret:
            print("code :", pyotp.TOTP(secret).now(), flush=True)
        await asyncio.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--connecte", action="store_true")
    parser.add_argument("--faux-claude", action="store_true", help="faux claude des tests (aucun quota)")
    parser.add_argument("--port", type=int, default=PORT, help="port d'écoute (plusieurs essais en même temps)")
    args = parser.parse_args()
    FAKE = args.faux_claude
    PORT = args.port
    asyncio.run(main(args.connecte))
