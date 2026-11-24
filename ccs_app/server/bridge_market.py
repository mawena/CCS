"""Market dans le pont : `market.workspace` prépare le dossier du chat Market (CLAUDE.md, droits
des outils) et renvoie son chemin ; la feuille « Nouvelle session » y ouvre alors un chat
ordinaire (option « Market »). La recherche elle-même passe par `ccs market …`, que Claude lance
dans ce chat."""

import asyncio

from .. import market


class MarketApi:
    def __init__(self, bridge, workspace=None):
        self.bridge = bridge
        self._workspace = workspace or market.workspace_dir
        bridge.add_handlers({"market.workspace": self.workspace})

    async def workspace(self, _conn, _params):
        d = await asyncio.to_thread(market.workspace, self._workspace())
        return {"cwd": str(d)}
