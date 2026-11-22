"""Gérer projets et conversations depuis le bureau, sur « Ce poste » comme sur un serveur.

Les deux sources ont la même interface, `call(method, done, **params)` puis
`done(result, error)` dans l'interface : un serveur passe par son pont (`RemoteOps`) ; ce poste
appelle directement le code du pont (`LocalOps`), avec les mêmes contrôles (dossiers permis,
conversation qui tourne refusée), sans démarrer de pont local."""

import asyncio
import threading
import types

from ..server import protocol

# Méthodes de gestion permises (le reste du pont n'est pas exposé en local par ce biais).
METHODS = ("projects.add", "projects.remove", "projects.folders", "conversations.trash",
           "trash.list", "trash.restore")


class OpsError(Exception):
    def __init__(self, message, code="erreur"):
        super().__init__(message)
        self.message, self.code = message, code


class RemoteOps:
    """Serveur appairé : les méthodes passent par sa connexion (`remote.engine.connection`)."""

    def __init__(self, conn):
        self.conn = conn

    def call(self, method, done, **params):
        def answered(result, error):
            if error is not None and getattr(error, "code", "") == "introuvable" \
                    and str(getattr(error, "message", "")).startswith("Méthode inconnue"):
                # serveur d'avant la 1.0.0 : anciens noms (compatibilité 1.x, à retirer en 2.0)
                old, old_params = protocol.to_legacy(method, params)
                if old != method:
                    self.conn.call(old, callback=lambda r, e: done(
                        protocol.upgrade_result(method, r) if e is None else r, e), **old_params)
                    return
            done(result, error)
        self.conn.call(method, callback=answered, **params)


class LocalOps:
    """Ce poste : le code du pont (`server.bridge_data.DataApi`) appelé dans un fil à part."""

    def __init__(self, dispatch):
        self.dispatch = dispatch
        self._api = None

    def _handlers(self):
        if self._api is None:
            from ..server import bridge_data
            found = {}
            bridge = types.SimpleNamespace(add_handlers=found.update, hubs={})
            bridge_data.DataApi(bridge)
            self._api = found
        return self._api

    def call(self, method, done, **params):
        def run():
            result = error = None
            try:
                name, args = protocol.normalize(method, params)
                if name not in METHODS:
                    raise OpsError("Opération non permise sur ce poste.", "refuse")
                result = asyncio.run(self._handlers()[name](None, args))
            except Exception as e:  # noqa: BLE001 — erreur du pont (RpcError) ou imprévue : montrée
                error = e if hasattr(e, "message") else OpsError(str(e) or type(e).__name__)
            self.dispatch(done, result, error)
        threading.Thread(target=run, daemon=True).start()


def message(error):
    return getattr(error, "message", None) or str(error)
