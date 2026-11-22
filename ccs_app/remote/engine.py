"""Chat d'un serveur CCS dans l'application GTK : `RemoteChatEngine` a les méthodes et émet les
événements du moteur local (`chat_engine.ChatSession`), si bien que `ChatTab` ne voit pas la
différence. Une `RemoteConnection` par serveur (un seul WebSocket) distribue les événements aux
chats ouverts et les relance après une reconnexion.

Les chats locaux du bureau passent aussi par ici : `local_connection` les relie au pont local
(`ccs bridge --local`, lancé s'il ne tourne pas), celui que le web et les autres appareils
joignent par `machines.attach` ; ils y sont donc vus en direct. Sans pont (il ne démarre pas, ou
`CCS_CHAT_IN_PROCESS=1`), `local_connection` renvoie None et le bureau garde son moteur en
processus. Un chat local (`close_on_stop`) fermé dans le bureau est fermé dans le pont, sauf si
un autre appareil le suit encore (`chat.close {keep_if_shared}`) ; quitter le bureau le détache
seulement (`detach`)."""

import base64
import dataclasses
import os
import secrets
import threading
import time

from .. import chat_engine
from ..server import events
from . import client as remote_client

_CONNECTIONS = {}
LOCAL = ":local"            # clé de la connexion au pont local dans _CONNECTIONS
LOCAL_RETRY_S = 60          # pont local qui n'a pas démarré : nouvel essai après ce délai
_local_lock = threading.Lock()
_local_failed_at = None


LOOK_S = 5          # conversation reprise pas encore ouverte ailleurs : nouveau coup d'œil


class RemoteConnection:
    def __init__(self, sync, label, local=False):
        self.client = sync
        self.label = label
        self.local = local
        self.engines = {}
        self.listeners = set()
        self.tag_listeners = set()  # moteurs ouverts, même pas encore branchés sur un chat
        self.state = "online"
        sync.on_event = self._event
        sync.on_state = self._state

    def register(self, eng):
        self.engines[eng.chat_id] = eng

    def unregister(self, eng):
        if self.engines.get(eng.chat_id) is eng:
            del self.engines[eng.chat_id]

    def _event(self, name, data):
        if name == "chat.event":
            eng = self.engines.get(data.get("chat_id"))
            if eng is not None:
                eng.receive(data)
        elif name == "chat.tags":
            # étiquettes changées (ici ou sur un autre appareil) : les chats de cette conversation
            for eng in list(self.tag_listeners):
                if data.get("session_id") and eng.session_id == data.get("session_id"):
                    eng.tags_changed(data)

    def _state(self, state):
        self.state = state
        for fn in list(self.listeners):
            try:
                fn(state)
            except Exception:
                pass
        if state == "reconnected":
            for eng in list(self.engines.values()):
                eng.resync()

    def call(self, method, callback=None, **params):
        return self.client.call(method, callback=callback, **params)


def connection(server, dispatch):
    """Connexion (partagée) à un serveur appairé ; `dispatch` ramène les rappels dans l'interface."""
    conn = _CONNECTIONS.get(server.name)
    if conn is None:
        sync = remote_client.SyncBridgeClient(remote_client.WebTransport(server), dispatch)
        conn = RemoteConnection(sync, server.name)
        _CONNECTIONS[server.name] = conn
        sync.start()
    return conn


def local_connection(dispatch, transport=None, timeout=15):
    """Connexion (partagée) au pont local, le lance s'il ne répond pas ; None s'il ne démarre pas
    (nouvel essai après LOCAL_RETRY_S) ou si `CCS_CHAT_IN_PROCESS=1`. Bloque le temps du premier
    contact (lancement du pont, une seconde environ) ; au démarrage du bureau, c'est le plan de
    réouverture des onglets qui l'appelle, hors du fil de l'interface."""
    global _local_failed_at
    if os.environ.get("CCS_CHAT_IN_PROCESS") == "1":
        return None
    with _local_lock:
        conn = _CONNECTIONS.get(LOCAL)
        if conn is not None:
            return conn
        if _local_failed_at is not None and time.monotonic() - _local_failed_at < LOCAL_RETRY_S:
            return None
        sync = remote_client.SyncBridgeClient(transport or remote_client.LocalTransport(), dispatch)
        conn = RemoteConnection(sync, "local", local=True)
        sync.start()
        try:
            ok = sync._connected.result(timeout)
        except Exception:  # noqa: BLE001 — délai dépassé : traité comme un échec
            ok = False
        if not ok:
            try:
                sync.stop()
            except Exception:  # noqa: BLE001
                pass
            _local_failed_at = time.monotonic()
            return None
        _local_failed_at = None
        _CONNECTIONS[LOCAL] = conn
        return conn


def local_chats(timeout=5):
    """Chats du pont local (`chat.list`) si la connexion est déjà ouverte, sinon [] (sans lancer
    le pont). Hors du fil de l'interface."""
    conn = _CONNECTIONS.get(LOCAL)
    if conn is None:
        return []
    try:
        return conn.client.call_sync("chat.list", timeout=timeout).get("chats") or []
    except Exception:  # noqa: BLE001 — pont injoignable : rien à montrer
        return []


class RemoteChatEngine:
    def __init__(self, conn, cwd, session_id=None, options=None, on_event=None, chat_id=None,
                 close_on_stop=False):
        self.conn = conn
        self.cwd = str(cwd)
        self.session_id = session_id
        self.options = options or chat_engine.ChatOptions()
        self.on_event = on_event
        self.effort = self.options.effort
        self.state = "stopped"
        self.pid = None
        self.started_at = None
        self.last_activity = time.time()
        self.chat_id = None
        self.seq = 0
        self._opening = False
        self._then = []
        self._own = set()           # nonces de nos envois : leur écho du pont est ignoré
        self._stopped = False
        self.close_on_stop = close_on_stop   # chat local : fermé dans le pont avec l'onglet
        if hasattr(conn, "tag_listeners"):
            conn.tag_listeners.add(self)
        if chat_id:                 # rejoindre un chat qui tourne déjà : fil rejoué, puis direct
            self._join(chat_id)
        elif session_id:            # conversation reprise : la suivre si elle tourne (ou tournera) ailleurs
            self._look()

    def _look(self):
        if self.chat_id is None and not self._opening and not self._stopped:
            self.conn.call("chat.list", callback=self._listed)

    def _join(self, chat_id, seq=0):
        self.chat_id, self.seq = chat_id, seq
        self.started_at = time.time()
        self.conn.register(self)
        self.resync()

    def _listed(self, result, error):
        """Chat de cette conversation déjà ouvert sur le serveur (web, téléphone) : on s'y branche
        à partir de maintenant (l'historique est déjà lu dans le journal)."""
        if self.chat_id is not None or self._opening or self._stopped:
            return
        for c in (result or {}).get("chats") or [] if error is None else []:
            if c.get("session_id") == self.session_id:
                self._join(c["chat_id"], c.get("seq") or 0)
                return
        # Pas encore ouverte ailleurs : on regarde de nouveau un peu plus tard (le web peut l'ouvrir).
        timer = threading.Timer(LOOK_S, self._look)
        timer.daemon = True
        timer.start()

    # ---- ouverture et événements ---------------------------------------------------------

    def _emit(self, ev):
        if self.on_event:
            self.on_event(ev)

    def _open(self, then):
        if self.chat_id is not None:
            then()
            return
        self._then.append(then)
        if self._opening:
            return
        self._opening = True
        self.conn.call("chat.open", callback=self._opened, cwd=self.cwd, session_id=self.session_id,
                       options=dataclasses.asdict(self.options))

    def _opened(self, result, error):
        self._opening = False
        if error is not None:
            self._then.clear()
            where = "Pont local" if getattr(self.conn, "local", False) else f"Serveur {self.conn.label}"
            self._emit(chat_engine.ProcessExited(1, f"{where} : {getattr(error, 'message', error)}"))
            return
        if self._stopped:            # onglet fermé pendant l'ouverture : rien ne doit rester ouvert
            if self.close_on_stop:
                self.conn.call("chat.close", chat_id=result["chat_id"], keep_if_shared=True)
            return
        self.chat_id = result["chat_id"]
        self.pid = result.get("pid") or self.pid
        if self.session_id:          # conversation reprise : son historique est déjà lu (journal)
            self.seq = max(self.seq, result.get("seq") or 0)
        self.started_at = time.time()
        self.conn.register(self)
        self.resync()
        for fn in self._then:
            fn()
        self._then.clear()

    def resync(self):
        if self.chat_id is not None:
            self.conn.call("chat.attach", callback=self._attached, chat_id=self.chat_id, since=self.seq)

    def _attached(self, result, error):
        if error is None:
            self.pid = result.get("pid") or self.pid
            for item in result.get("events") or []:
                self.receive(item)
        elif getattr(error, "code", "") == "introuvable" and self.chat_id is not None:
            # Le pont a redémarré (mise à jour) : son chat a disparu. On se rebranche sur la
            # conversation (celle qu'un autre appareil a rouverte, ou une reprise).
            self.conn.unregister(self)
            self.chat_id, self.seq = None, 0
            self._open(lambda: None)

    def receive(self, item):
        seq = item.get("seq") or 0
        if seq and seq <= self.seq:
            return
        self.seq = max(self.seq, seq)
        ev = events.from_json(item.get("event") or {})
        if isinstance(ev, events.PermissionSettled):   # réglée ici ou ailleurs : la carte se fige
            self._emit(ev)
            return
        if isinstance(ev, chat_engine.UserSent) and ev.nonce in self._own:
            self._own.discard(ev.nonce)
            return
        if isinstance(ev, chat_engine.StateChanged):
            self.state = ev.state
            if ev.state in ("stopped", "suspended"):
                self.pid = None
        elif getattr(ev, "session_id", None) and type(ev).__name__ == "Init":
            self.session_id = ev.session_id
        self.last_activity = time.time()
        self._emit(ev)

    def _call(self, method, **params):
        if self.chat_id is None:
            return False
        self.conn.call(method, chat_id=self.chat_id, **params)
        return True

    # ---- étiquettes (RPC du pont, sans chat ouvert) --------------------------------------

    def load_tags(self, callback):
        """callback(messages, connues) : messages étiquetés de la conversation et étiquettes déjà
        utilisées ; ({}, []) si la conversation n'est pas encore connue ou en cas d'erreur."""
        if not self.session_id:
            callback({}, [])
            return
        self.conn.call("chat.tags", callback=lambda r, e: callback(
            *(((r or {}).get("messages") or {}, (r or {}).get("known") or []) if e is None else ({}, []))),
            session_id=self.session_id)

    def set_tags(self, msg_id, tags, text="", role="", callback=None):
        """Pose les étiquettes d'un message ; callback(entrée, erreur). Le pont diffuse aussi le
        changement (`chat.tags`), reçu ici comme sur les autres appareils."""
        if not self.session_id:
            if callback is not None:
                callback(None, "Conversation pas encore enregistrée.")
            return
        self.conn.call("chat.tag", callback=lambda r, e: callback and callback(
            (r or {}).get("entry") if e is None else None,
            None if e is None else getattr(e, "message", str(e))),
            session_id=self.session_id, msg_id=msg_id, tags=list(tags), text=text, role=role)

    def tags_changed(self, data):
        entry = data.get("entry")
        self._emit(chat_engine.TagsChanged(data.get("session_id") or "", str(data.get("msg_id") or ""),
                                           entry if isinstance(entry, dict) else None))

    # ---- interface du moteur local -------------------------------------------------------

    def send(self, text, images=(), uuid=None):
        payload = [{"media_type": mt, "data": base64.b64encode(data).decode("ascii")} for mt, data in images or ()]
        nonce = secrets.token_hex(8)
        self._own.add(nonce)
        params = {"text": text, "images": payload, "nonce": nonce, **({"uuid": uuid} if uuid else {})}
        self._open(lambda: self._send(params, retry=True))
        return True

    def _send(self, params, retry):
        """chat.send ; le chat a été fermé entre-temps (autre appareil, relance du pont) : il est
        rouvert sur la même conversation et le message repart, une fois."""
        if self.chat_id is None:
            return

        def done(_result, error):
            if error is None:
                return
            if retry and getattr(error, "code", "") == "introuvable" and not self._stopped:
                self.conn.unregister(self)
                self.chat_id, self.seq = None, 0
                self._open(lambda: self._send(params, retry=False))
                return
            self._own.discard(params["nonce"])
            self._emit(chat_engine.ProcessExited(1, f"Message non envoyé : {getattr(error, 'message', error)}"))
        self.conn.call("chat.send", callback=done, chat_id=self.chat_id, **params)

    def send_if_idle(self, text):
        """Envoi décidé par CCS, seulement si Claude est au repos (processus en vie) ; sinon faux."""
        if self.chat_id is None or self.state != "idle":
            return False
        return self.send(text)

    def answer(self, request_id, decision, message=""):
        return self._call("chat.answer", request_id=request_id, decision=decision, message=message)

    def answer_questions(self, request_id, answers):
        return self._call("chat.questions", request_id=request_id, answers=dict(answers))

    def interrupt(self):
        return self._call("chat.interrupt")

    def set_options(self, options):
        self.options = options
        self.effort = options.effort
        return self._call("chat.options", options=dataclasses.asdict(options))

    def request_context(self):
        return self._call("chat.context")

    def suspend_if_idle(self, _now, _idle_s):
        return False                # le pont gère la mise en veille de ses chats

    def background_finished(self, _tool_id):
        return None

    def stop(self, grace_s=5):
        """Fermer l'onglet ne coupe pas le chat d'un serveur : on se détache seulement. Un chat
        local (`close_on_stop`) est fermé dans le pont, sauf s'il est suivi ailleurs."""
        if self.close_on_stop and self.chat_id is not None and not self._stopped:
            self.conn.call("chat.close", chat_id=self.chat_id, keep_if_shared=True)
        self.detach()

    def detach(self):
        """Ne plus suivre le chat, qui continue dans le pont (fermeture de l'application)."""
        self._stopped = True
        self.conn.unregister(self)
        getattr(self.conn, "tag_listeners", set()).discard(self)
