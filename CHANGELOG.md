# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté

- **Terminal intégré** : reprendre une conversation ou démarrer une session
  l'ouvre dans la fenêtre de l'application, dans un onglet de terminal (VTE),
  au lieu d'une fenêtre séparée.
  - Page **Terminaux**, visible tant qu'un onglet est ouvert : plusieurs
    sessions en onglets, titre de la conversation, activité (travaille, attend
    ta réponse, arrêtée), onglet en arrière-plan signalé quand il a fini.
  - Copier / coller Ctrl+Maj+C / Ctrl+Maj+V et clic droit, Ctrl+clic sur les
    liens, taille du texte (Ctrl+plus / moins / 0), 100 000 lignes de
    défilement arrière, police à chasse fixe du bureau, couleurs qui suivent
    le thème clair ou sombre.
  - Bandeau de fin avec **Reprendre** (même conversation) et **Fermer** ;
    confirmation avant de fermer un onglet ou la fenêtre quand une session
    tourne (« La conversation est enregistrée : tu pourras la reprendre. »).
  - Onglets Sessions et Conversations : reprise, nouvelle session et
    « Terminal ici » (shell) dans l'application, terminal externe dans les
    menus, **Afficher** pour une session déjà ouverte dans un onglet.
  - Sans `gir1.2-vte-3.91`, tout s'ouvre dans un terminal externe comme avant
    et l'onglet Sessions indique comment installer le terminal intégré.
- **Renommer une conversation**, comme `/rename` : « Renommer… » dans les
  onglets Sessions et Conversations et dans le menu d'un onglet du terminal,
  `ccs title <id> <titre>` / `claude-accounts title`. Une ligne de titre est
  ajoutée à la fin du journal (une seule écriture en mode ajout, le journal
  n'est jamais réécrit).
- `CCS_APP_ID` et `CCS_NO_VTE` documentés pour essayer une copie de
  développement.
- **Suite du terminal intégré** :
  - **reprise automatique après une limite** (avec `ccs integrate`) : quand
    une session d'un onglet est bloquée, le hook bascule et laisse un marqueur
    (`~/.claude-accounts/limits/`), puis la page Terminaux envoie « continue »
    une fois par limite, dès que Claude attend une nouvelle demande (jamais
    pendant une demande de permission), avec un bandeau. Gardes : au plus
    3 reprises par heure et par onglet, 2 min d'écart, rien si quelqu'un a
    tapé dans l'onglet depuis la limite ou si elle a plus de 15 min.
    Interrupteur « Reprise automatique après une limite » (activé par défaut)
    dans le menu « ⋮ » de la page Terminaux ;
  - **onglets rouverts** au redémarrage de l'application, avec leurs options
    et leurs messages en attente : bandeau « Rouvrir les N sessions de la
    dernière fois ? », ou réouverture directe avec l'interrupteur « Rouvrir
    les onglets au démarrage » ; dossier disparu ou conversation déjà ouverte
    sautés ; état dans `~/.claude-accounts/terminals.json` ;
  - **côte à côte** (Ctrl+Maj+E) : deux onglets dans une vue partagée
    redimensionnable, sans relancer les terminaux ;
  - **messages en attente** (Ctrl+Maj+M) : file « Envoyer quand Claude sera
    libre », modifiable et réordonnable, un message envoyé par tour quand
    Claude a fini ;
  - les options d'une nouvelle session (`--model`, `--permission-mode`) sont
    gardées par l'onglet pour Reprendre et la réouverture.
- **Mode pause** : bascule automatique et orchestrateur suspendus 1 h, 4 h,
  jusqu'à la prochaine plage horaire ou jusqu'à reprise manuelle ; levée
  automatique à l'échéance avec la notification « Pause terminée ». Pendant une
  pause, CCS ne change plus de compte tout seul, bascule après blocage (hook
  `StopFailure`) et reprise automatique du terminal comprises ; les bascules
  manuelles, alertes et warm-up continuent.
  - `ccs pause [1h|4h|demain|manuel|off|status]` / `claude-accounts pause` ;
    `ccs status` affiche la pause.
  - Menu de l'indicateur (« Mettre en pause », « Reprendre maintenant », ⏸
    devant le pourcentage), carte « Meilleur compte » de l'onglet Comptes,
    rappel dans l'onglet Planning et dans l'en-tête de la fenêtre, ⏸ dans la
    ligne d'état de Claude Code.
  - État dans `~/.claude-accounts/pause.json`.
- **Prévision de fin de semaine** par compte, au rythme moyen de la semaine :
  sur la carte du compte et dans le menu de l'indicateur. Alerte une fois par
  semaine quand la limite hebdomadaire sera atteinte dans 2 jours ou moins
  (réglages `alerts.weekly_forecast`, `alerts.weekly_forecast_days`).
- **Rappel des sessions en attente** : une notification unique quand une
  session attend ta réponse depuis plus de 10 min (`alerts.waiting_reminder`,
  `alerts.waiting_reminder_min`), même si les notifications de sessions sont
  coupées.
- **Nouvelle version** : vérification sur GitHub au plus une fois par jour,
  une seule notification par version, ligne dans l'indicateur, bandeau dans la
  fenêtre et lien dans Réglages (`updates.enabled`, cache
  `~/.claude-accounts/updates.json`).
- **Bilan de santé** : `ccs doctor` / `claude-accounts doctor` et « Bilan de
  santé… » dans le menu de l'application : service, relevés, versions,
  extension et indicateur, intégration, connexion de chaque compte, `claude`,
  `jq`, terminal intégré. Une commande à copier par problème (rien n'est
  exécuté) ; code de sortie 0 si tout va bien, 1 sinon ; bandeau au démarrage
  de l'application si un problème est détecté. Des jetons, seuls la présence
  et les dates d'expiration sont lues.
- **Aperçu d'une conversation** sans la reprendre (« Aperçu… » dans les
  onglets Conversations et Sessions, `ccs preview <id>` alias `ccs apercu`) :
  demandes, réponses, outils en une ligne ; copie et **export en Markdown**
  (`ccs export <id> [fichier.md]`). Journal lu en flux, même très gros.
- **Coût d'une conversation** : tokens consommés (sous-agents compris) et
  équivalent au tarif de l'API Anthropic en dollars (tarifs du 2026-10-06),
  affiché pour chaque conversation et en tête de l'aperçu. Un abonnement ne
  facture pas au token : le montant sert à comparer les conversations.
- **Nouvelle session…** : dialogue avec le dossier, le compte, le modèle
  (`--model`) et le mode de permissions (`--permission-mode`) ; ouverture dans
  le terminal intégré, bascule de compte si besoin (avec un avertissement : la
  bascule s'applique à toutes les sessions ouvertes) ; avertissement en rouge
  pour `bypassPermissions`.
- Notifications de session cliquables (ouverture de l'onglet de la session) et
  badge du nombre de sessions en attente sur l'onglet Sessions.

### Modifié

- L'onglet Sessions affiche les mêmes titres que l'onglet Conversations (titre
  donné, sinon titre automatique, sinon première demande) et ne propose plus
  de reprendre une conversation déjà ouverte ailleurs.
- Paquet : dépend de `gir1.2-vte-3.91`.
- L'alerte de fin de semaine prévue remplace l'alerte « semaine en avance sur
  le rythme », moins précise, quand elle part.
- L'indicateur se relance tout seul après une mise à jour du paquet, comme le
  service. Depuis la 0.4.0 ou avant, relance-le une fois à la main.
- Les dialogues de l'application demandent libadwaita 1.5 ou plus récent
  (Ubuntu 24.04 l'a).
- `~/.claude-accounts/state.json` : nouvelles clés `pause`, `update`,
  `auto_switch.paused`, `orchestrator.paused` et `accounts[].weekly_forecast`.

## [0.4.0] — 2026-11-04

### Ajouté

- **Historique des conversations** : toutes les conversations Claude Code du PC
  (terminal et VS Code), comme la liste des conversations passées de
  l'extension VS Code, tous projets confondus.
  - Onglet **Conversations** de l'application : recherche, filtres par projet
    et par origine, groupes par date, badge « ouverte », bouton « Tout
    l'historique » dans l'onglet Sessions.
  - `ccs conv` / `claude-accounts conversations` : liste, recherche, `--json`.
  - Reprise dans VS Code (fenêtre du projet puis lien
    `vscode://anthropic.claude-code/open?session=…`), dans un terminal ou dans
    le terminal courant (`ccs resume <id>`) ; copie de la commande.
  - Projets déplacés : dossier du même nom proposé, confirmation, copie du
    journal dans le nouveau dossier (`--dir` pour le choisir).
  - Titres : `/rename`, sinon titre automatique, sinon première demande ; le
    contexte ajouté par VS Code est ignoré.
  - Cache incrémental (`~/.claude-accounts/conversations-cache.json`) : seules
    les lignes ajoutées depuis la dernière lecture sont relues.

### Modifié

- Fenêtre plus large à l'ouverture (1180 px) ; sous 1350 px de large, les sept
  onglets passent dans la barre du bas pour que leurs titres restent entiers.

### Corrigé

- Une demande interrompue (« [Request interrupted by user… ») ne sert plus de
  titre dans l'onglet Sessions.
- `claude-accounts --print` n'est plus réécrit qu'en première position (il
  empêchait `resume … --print`).

## [0.3.2] — 2026-11-04

### Corrigé

- Orchestrateur : quand un compte a été ouvert avant le début de la plage
  horaire, le premier démarrage du matin part de son heure d'ouverture
  (ouvert à 07:10 → compte suivant à 09:40) au lieu d'une grille fixe calée
  sur le début de plage (10:30).
- `ccs next` saute les profils dont la connexion est perdue ; si aucun autre
  profil n'est utilisable, il s'arrête en nommant les profils à reconnecter.
- Les limites hebdomadaires par modèle s'affichent « Semaine · Fable » au lieu
  des données brutes renvoyées par l'API.

## [0.3.1] — 2026-11-04

### Corrigé

- En quittant un compte dont la connexion avait été perdue, `ccs` recopiait
  dans son profil les jetons vides laissés par Claude Code (une chaîne vide
  passait pour un jeton valide). La carte du compte affichait alors le message
  trompeur « aucun jeton enregistré pour ce profil ».
- `ccs use` refuse désormais d'installer un profil sans jeton, sans rien
  modifier.
- Le message devient « connexion perdue : reconnecte ce compte avec
  « ccs rm <nom> » puis « ccs add <nom> » », avec une alerte bureau.
- Un jeton renouvelé remplit la copie vide du profil actif.

## [0.3.0] — 2026-10-26

### Ajouté

- **Sessions Claude Code** : onglet Sessions, `ccs sessions`, sous-menu de
  l'icône — projet, état (travaille / attend ta réponse / au repos), durée,
  modèle, consommation ; terminal ou dossier du projet, terminer une session,
  reprendre une conversation récente, nouvelle session dans un projet récent.
- Notifications quand une session a terminé ou attend ta réponse (surveillance
  immédiate des fiches de session).
- **Intégration Claude Code** (`ccs integrate on|off|status`) : ligne d'état
  (compte, session, recharge, prévision, semaine) et bascule automatique quand
  une session est bloquée par la limite (hook `StopFailure`).
- Boutons « Basculer sur … » dans les alertes de seuil et de fin imminente.
- Icône de la barre du haut : jauge dessinée selon la session du compte actif
  (vert / orange / rouge) ; menu enrichi (âge des données, recharges, réserve,
  erreurs, prochaine recharge, capacité, interrupteur Orchestrateur, sessions).

### Corrigé

- Onglet Analyse : une valeur d'usage non numérique dans un journal ne bloque
  plus le calcul.

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
