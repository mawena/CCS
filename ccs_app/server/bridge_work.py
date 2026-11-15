"""Travail dans le chat, côté pont (phase 14 au web) : messages enregistrés, commande `!`,
commandes `/`, changements de la session (copies de Claude Code) et retour en arrière.
Rempli par le lot « chat » ; chaque chemin passe par `bridge_data.safe_path`."""


class WorkApi:
    def __init__(self, bridge):
        self.bridge = bridge
        bridge.add_handlers({})
