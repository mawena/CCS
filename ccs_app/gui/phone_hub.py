"""Autorisations depuis le téléphone, pour toute l'application : un seul `Replies` (jetons) et
un seul `Listener` (écoute du sujet de réponses) partagés par tous les chats.

Un chat qui reçoit une demande d'autorisation appelle `notify` ; la notification part avec ses
boutons « Autoriser » / « Refuser » ; une réponse vérifiée appelle `on_decision(décision)` dans
l'interface. L'écoute ne tourne que tant qu'une demande attend.
"""

import secrets
import threading
import time

from gi.repository import GLib

from .. import phone, phone_reply, settings

_hub = None


def get():
    """Le `PhoneHub` de l'application, ou None (aucune fenêtre : tests, ligne de commande)."""
    return _hub


def set_hub(hub):
    global _hub
    if _hub is not None and _hub is not hub:
        _hub.close()
    _hub = hub


def _in_interface(function):
    GLib.idle_add(lambda: (function(), False)[1])


class PhoneHub:
    def __init__(self, urlopen=None, run=None, dispatch=None, listener_factory=None, now=time.time):
        self.replies = phone_reply.Replies()
        self.listener = None
        self._urlopen = urlopen
        self._run = run                  # exécuteur de l'envoi (tests : appel direct)
        self._dispatch = dispatch or _in_interface
        self._listener_factory = listener_factory or phone_reply.Listener
        self._now = now
        self._lock = threading.Lock()
        self._handlers = {}              # identifiant de la demande → on_decision

    def notify(self, tool_name, project, detail, on_decision, loaded=None):
        """Envoie la demande au téléphone si les notifications et l'événement « attend ta
        réponse » sont actifs. Renvoie l'identifiant de la demande (pour `settle`), ou None."""
        s = loaded if loaded is not None else settings.load_settings()
        if not phone.ready(s):
            return None
        cfg = phone.config(s)
        if not cfg["events"].get("waiting", True):
            return None
        topic = phone_reply.reply_topic(s)
        pid = secrets.token_urlsafe(6)
        token = self.replies.issue(pid, self._now())
        with self._lock:
            self._handlers[pid] = on_decision
        msg = phone_reply.permission_message(tool_name, project, detail, cfg["show_content"])
        header = phone_reply.actions_header(cfg, topic, pid, token)

        def work():
            phone.deliver(cfg, msg, self._urlopen, actions=header)
        if self._run is not None:
            self._run(work)
        else:
            threading.Thread(target=work, name="ccs-telephone-permission", daemon=True).start()
        self._ensure_listener(cfg, topic)
        return pid

    def settle(self, pid):
        """La demande est réglée (sur le PC, annulée, chat fermé) : plus de réponse acceptée."""
        self.replies.settle(pid)
        with self._lock:
            self._handlers.pop(pid, None)
        self._stop_if_idle()

    def _ensure_listener(self, cfg, topic):
        with self._lock:
            if self.listener is None:
                self.listener = self._listener_factory(cfg, topic, self._on_body)
                self.listener.start()

    def _stop_if_idle(self):
        with self._lock:
            if self.listener is not None and not self.replies.pending():
                self.listener.stop()
                self.listener = None

    def _on_body(self, body):
        """Une réponse arrive (fil d'écoute) : vérifiée, elle part dans l'interface."""
        verified = self.replies.verify(body, self._now())
        if verified is None:
            return
        pid, decision = verified
        with self._lock:
            callback = self._handlers.pop(pid, None)
        if callback is not None:
            self._dispatch(lambda: callback(decision))
        self._stop_if_idle()

    def close(self):
        with self._lock:
            listener, self.listener = self.listener, None
            self._handlers.clear()
        if listener is not None:
            listener.stop()
