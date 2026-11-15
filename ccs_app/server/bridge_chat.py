"""Chats du pont : un `ChatSession` (moteur du chat) par conversation ouverte, qui vit dans le pont (il survit aux
déconnexions). Chaque événement est numéroté et gardé (2000 par chat) : un appareil qui revient
demande ce qu'il a manqué depuis son dernier numéro ; tous les appareils attachés reçoivent les
mêmes événements."""

import asyncio
import base64
import binascii
import collections
import dataclasses
import itertools
import os

from .. import chat_options, markdown_render
from ..chat_engine import ChatSession
from . import events, rpc

BUFFER = 2000
BUSY = ("starting", "busy", "permission")


class _Chat:
    def __init__(self, chat_id, cwd):
        self.chat_id = chat_id
        self.cwd = cwd
        self.engine = None
        self.buf = collections.deque(maxlen=BUFFER)
        self.seq = 0
        self.conns = set()


def _options(raw):
    raw = raw if isinstance(raw, dict) else {}
    names = {f.name for f in dataclasses.fields(chat_options.ChatOptions)}
    return chat_options.ChatOptions(**{k: v for k, v in raw.items() if k in names})


class ChatHub:
    def __init__(self, bridge, claude=None, environ=None):
        self.bridge = bridge
        self.claude = claude
        self.environ = environ
        self.chats = {}
        self._ids = itertools.count(1)
        self._loop = None
        bridge.busy_checks.append(self.busy)
        bridge.close_hooks.append(self._forget)
        bridge.add_handlers({
            "chat.open": self.open, "chat.list": self.list, "chat.attach": self.attach,
            "chat.send": self.send, "chat.answer": self.answer, "chat.questions": self.questions,
            "chat.interrupt": self.interrupt, "chat.options": self.options,
            "chat.close": self.close, "chat.render": self.render,
        })

    # ---- état ------------------------------------------------------------------------

    def busy(self):
        return any(c.engine is not None and c.engine.state in BUSY for c in self.chats.values())

    def _forget(self, conn):
        for chat in self.chats.values():
            chat.conns.discard(conn)

    def _get(self, params):
        chat = self.chats.get(params.get("chat_id"))
        if chat is None:
            raise rpc.RpcError("introuvable", "Chat inconnu ou fermé.")
        return chat

    def _record(self, chat, ev):
        if chat.chat_id not in self.chats:
            return
        chat.seq += 1
        item = {"seq": chat.seq, "event": events.to_json(ev)}
        chat.buf.append(item)
        for conn in list(chat.conns):
            if not conn.closed:
                asyncio.ensure_future(conn.push("chat.event", {"chat_id": chat.chat_id, **item}))

    def _on_event(self, chat):
        def handler(ev):          # appelé par le fil de lecture du moteur
            if self._loop is not None and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._record, chat, ev)
        return handler

    # ---- méthodes --------------------------------------------------------------------

    async def open(self, conn, params):
        self._loop = asyncio.get_running_loop()
        cwd, session_id = params.get("cwd"), params.get("session_id")
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or not os.path.isdir(cwd):
            raise rpc.RpcError("invalide", "Dossier du projet introuvable.")
        if session_id:
            for chat in self.chats.values():
                if chat.engine.session_id == session_id:
                    chat.conns.add(conn)
                    return {"chat_id": chat.chat_id, "seq": chat.seq}
        chat = _Chat(f"c{next(self._ids)}", cwd)
        chat.engine = ChatSession(cwd, session_id=session_id or None,
                                  options=_options(params.get("options")),
                                  on_event=self._on_event(chat), claude=self.claude,
                                  environ=self.environ)
        chat.conns.add(conn)
        self.chats[chat.chat_id] = chat
        return {"chat_id": chat.chat_id, "seq": 0}

    async def list(self, _conn, _params):
        return {"chats": [{"chat_id": c.chat_id, "cwd": c.cwd, "session_id": c.engine.session_id,
                           "state": c.engine.state, "seq": c.seq} for c in self.chats.values()]}

    async def attach(self, conn, params):
        chat = self._get(params)
        since = params.get("since") if isinstance(params.get("since"), int) else 0
        chat.conns.add(conn)
        return {"events": [i for i in chat.buf if i["seq"] > since], "seq": chat.seq,
                "state": chat.engine.state, "session_id": chat.engine.session_id}

    async def send(self, _conn, params):
        chat = self._get(params)
        text = params.get("text")
        if not isinstance(text, str):
            raise rpc.RpcError("invalide", "Message manquant.")
        images = []
        for img in params.get("images") or ():
            try:
                images.append((str(img["media_type"]), base64.b64decode(img["data"], validate=True)))
            except (KeyError, TypeError, binascii.Error):
                raise rpc.RpcError("invalide", "Image illisible.") from None
        ok = await asyncio.to_thread(chat.engine.send, text, images)
        return {"ok": bool(ok)}

    async def answer(self, _conn, params):
        chat = self._get(params)
        rid, decision = params.get("request_id"), params.get("decision")
        if not isinstance(rid, str) or decision not in ("allow", "always", "deny"):
            raise rpc.RpcError("invalide", "Réponse invalide.")
        await asyncio.to_thread(chat.engine.answer, rid, decision, str(params.get("message") or ""))
        self._record(chat, events.PermissionSettled(rid, decision))
        return {}

    async def questions(self, _conn, params):
        chat = self._get(params)
        await asyncio.to_thread(chat.engine.answer_questions, str(params.get("request_id")),
                                params.get("answers") or {})
        self._record(chat, events.PermissionSettled(str(params.get("request_id")), "answered"))
        return {}

    async def interrupt(self, _conn, params):
        await asyncio.to_thread(self._get(params).engine.interrupt)
        return {}

    async def options(self, _conn, params):
        chat = self._get(params)
        await asyncio.to_thread(chat.engine.set_options, _options(params.get("options")))
        return {}

    async def close(self, _conn, params):
        chat = self._get(params)
        del self.chats[chat.chat_id]
        await asyncio.to_thread(chat.engine.stop)
        return {}

    async def close_all(self):
        chats, self.chats = list(self.chats.values()), {}
        for chat in chats:
            await asyncio.to_thread(chat.engine.stop)

    async def render(self, _conn, params):
        text = params.get("markdown")
        if not isinstance(text, str):
            raise rpc.RpcError("invalide", "Texte manquant.")
        return {"html": markdown_render.to_html(text)}
