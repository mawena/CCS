"""Aides des tests de l'espace distant : un faux client RPC qui sert les vrais gestionnaires du pont
(fichiers, feuille de route, git, tâches) dans le même processus, sans réseau ni authentification."""

import asyncio
import json
import threading

from ccs_app.server import bridge, bridge_data, bridge_git, rpc


class InProcessClient:
    """`call_sync(method, timeout, **params)` comme `SyncBridgeClient`, servi par un pont local
    (sa boucle tourne dans un fil). Les paramètres et réponses passent par JSON, comme sur le
    fil. `calls` : les méthodes appelées ; `offline` : toute RPC échoue (ConnectionError)."""

    def __init__(self):
        self.bridge = bridge.Bridge("alice", None, local=True, start_daemon=False,
                                    install_claude=False)
        bridge_data.DataApi(self.bridge)
        bridge_git.GitApi(self.bridge)
        self.calls = []
        self.offline = False
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def call_sync(self, method, timeout=30, **params):
        self.calls.append(method)
        if self.offline or self.loop.is_closed() or not self.loop.is_running():
            raise ConnectionError("hors ligne")
        fn = self.bridge._handlers.get(method)
        if fn is None:
            raise rpc.RpcError("inconnu", f"Méthode inconnue : {method}")
        params = json.loads(json.dumps(params))
        fut = asyncio.run_coroutine_threadsafe(fn(None, params), self.loop)
        return json.loads(json.dumps(fut.result(timeout)))

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)
        self.loop.close()
