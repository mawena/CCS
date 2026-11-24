"""Onglet Market du pont (phase 45) : `market.open` prépare le dossier du chat Market (CLAUDE.md,
droits des outils), puis rejoint le chat Market déjà ouvert dans le pont ou reprend sa dernière
conversation (`chat.open`). La recherche elle-même passe par `ccs market …`, que Claude lance
dans ce chat."""

import asyncio
import os

from .. import market


class MarketApi:
    def __init__(self, bridge, chats, workspace=None):
        self.bridge = bridge
        self.chats = chats
        self._workspace = workspace or market.workspace_dir
        bridge.add_handlers({"market.open": self.open})

    async def open(self, conn, _params):
        def prepare():
            d = market.workspace(self._workspace())
            return str(d), market.latest_session(d)
        cwd, session_id = await asyncio.to_thread(prepare)
        real = os.path.realpath(cwd)
        for chat in self.chats.chats.values():
            if os.path.realpath(chat.cwd) == real:
                chat.conns.add(conn)
                return {"chat_id": chat.chat_id, "seq": chat.seq, "cwd": chat.cwd,
                        "state": chat.engine.state, "title": "Market",
                        "session_id": chat.engine.session_id,
                        "path": None if chat.engine.session_id is None else
                        str(market.transcript(chat.cwd, chat.engine.session_id))}
        r = await self.chats.open(conn, {"cwd": cwd, "session_id": session_id})
        return {**r, "title": "Market", "state": "idle" if session_id else "starting"}
