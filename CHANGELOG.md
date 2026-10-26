# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté

- Indicateur : icône anneau-jauge dessinée selon la session du compte actif
  (vert, orange, rouge), lisible même quand l'extension n'affiche pas le texte.
- Menu de l'indicateur enrichi : compte actif et âge des données, session (avec
  heure de fin) et semaine de chaque compte, réserve, erreurs, meilleur compte,
  prévision, prochaine recharge, capacité ; interrupteur Orchestrateur.

## [0.2.1] — 2026-10-26

### Corrigé

- Une fenêtre démarrée par l'orchestrateur est reconnue même à 0 % d'usage
  (l'API renvoie 0 % avec une heure de fin juste après un démarrage).
- Le décalage entre comptes se calcule à partir des démarrages réels : deux
  comptes au repos ne démarrent plus ensemble, l'écart de 5 h ÷ N se rétablit
  dans la journée.
- Une erreur passagère de l'API d'usage (429, 5xx, réseau) ne fait plus oublier
  un compte : ses dernières données restent valables 10 min et sa fenêtre
  compte pour l'écart. Après une 429, le compte n'est réinterrogé qu'au bout de
  5 min.
- Le service se relance de lui-même après une mise à jour du paquet (il gardait
  l'ancien code en mémoire).

## [0.2.0] — 2026-10-26

### Ajouté

- **Orchestrateur** (`ccs orch on|off`) : pendant une plage horaire réglable
  (8 h → 2 h par défaut), enchaîne les fenêtres de 5 h de chaque compte, les
  décale entre comptes (5 h ÷ N), bascule vers le quota qui va expirer et met en
  réserve un compte en avance sur sa semaine.
- Réveil précis du service aux fins de fenêtre et aux créneaux de démarrage.
- `ccs plan` et onglet **Planning** : frise des fenêtres en cours et prévues,
  recharges à venir.
- Groupe « Orchestrateur » dans les Réglages ; état de l'orchestrateur dans
  `ccs status`.

### Modifié

- Le meilleur compte place les comptes en réserve en dernier.
- Fenêtre plus large ; onglets en bas quand la fenêtre est étroite.
- README : cas d'usage « 2 ou 3 comptes Pro » et note sur les conditions
  d'utilisation d'Anthropic.

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
