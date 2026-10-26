# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[SemVer](https://semver.org/lang/fr/).

## [0.1.0] — 2026-10-26

Première version.

### Ajouté

- `ccs` : profils multi-comptes Claude Code (`save`, `add`, `<nom>`, `next`,
  `rename`, `rm`, `current`), bascule atomique qui préserve jetons MCP et
  réglages, resauvegarde du jeton renouvelé avant chaque bascule.
- Usage de tous les comptes sans reconnexion (session 5 h, semaine), avec
  renouvellement des jetons des comptes inactifs.
- Prévisions : fin de session estimée, rythme hebdomadaire, budget par jour,
  capacité restante tous comptes confondus.
- Meilleur compte expliqué et `ccs best`.
- Bascule automatique avant la coupure (seuil 98 %, projection), reprise par les
  sessions Claude Code ouvertes à leur requête suivante ; garde-fous anti
  va-et-vient.
- Alertes bureau : seuils 80 % / 95 %, fin imminente, bascule, épuisement,
  réinitialisation, avance hebdomadaire, connexion expirée.
- Warm-up planifiable par compte pour démarrer la fenêtre de 5 h plus tôt.
- Analyse des journaux locaux par projet, modèle, heure et compte, avec conseils
  (`ccs analyze`).
- Application « Comptes Claude » (GTK 4 / libadwaita) : Comptes, Historique,
  Analyse, Réglages.
- Indicateur de la barre du haut (AyatanaAppIndicator).
- Service systemd utilisateur `ccs-daemon`.
- Commandes `ccs status`, `ccs usage`, `ccs auto on|off`, `ccs gui`.
- Paquet Debian, pages de manuel, documentation.
