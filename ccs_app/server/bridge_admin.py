"""Accueil et réglages côté pont (version web) : détails des comptes, bilan de santé, téléphone
(essai, QR code), tâches de nuit (journal, reprise, suppression). Rempli par le lot « pages »."""


class AdminApi:
    def __init__(self, bridge):
        self.bridge = bridge
        bridge.add_handlers({})
