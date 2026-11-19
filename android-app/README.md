# CCS pour Android

Application Android native (Kotlin + Jetpack Compose, Material 3) de CCS. Elle parle directement
à l'API du serveur (par défaut https://ccs.mawena.cloud) : WebSocket `/api/ws` pour la RPC et les
événements, routes HTTP pour la connexion. Elle remplace l'ancienne coquille Flutter (vue web),
avec le même identifiant `com.mawena.ccs` : elle s'installe par-dessus.

État : phase 25, tâches 1 à 9 de `ROADMAP.md`. Connexion, client WebSocket, navigation (Accueil,
Sessions, Fichiers, Git, Plus), notifications, partage vers CCS, raccourcis d'appli.

- **Accueil** : compte actif, meilleur compte et décision de la bascule automatique, cartes des
  comptes (jauges, statut, détails repliables, « Basculer sur ce compte » avec confirmation),
  Actualiser, pause de la bascule et de l'orchestrateur, bilan de santé (commande à copier),
  accès à l'**Analyse** (24 h, 7, 30, 90 jours : par projet, modèle, compte, heure). Relu chaque
  minute tant que l'écran est visible et à chaque reconnexion.
- **Sessions** : « En cours » (chats ouverts dans le pont, état en direct par `chat.event`),
  projets (ajouter, retirer de la liste, compte associé), conversations récentes avec coût,
  recherche, menu (Reprendre, Aperçu, Renommer, Supprimer avec « Annuler »), corbeille et
  restauration, **Nouvelle session** (dossier : récents, projets, dépôts git ; compte conseillé
  pour le dossier ; modèle ; droits). Écran **Projet** : compte, « Nouveau chat », conversations.
- **Chat** (comme `web/chat.js`) : toucher une conversation la reprend (`chat.open`) ; fil en direct
  numéroté (`chat.attach` depuis le dernier numéro après chaque reconnexion, carte « Reprendre la
  conversation » si le pont a redémarré), 200 derniers messages du journal puis « Messages plus
  anciens ». Markdown natif (titres, listes, cases, citations, tableaux, liens cliquables, blocs de
  code colorés avec « Copier »), outils repliables avec résultat, regroupés quand ils se suivent,
  diffs des modifications, sous-agents (carte + pastilles et leur vue), autorisations (Autoriser,
  Toujours, Refuser avec motif), questions de Claude, liste de tâches, état (au travail, réflexion,
  attente), Arrêter, séparateurs « Nouvelle conversation » / « Sujet terminé : Claude a effacé la
  conversation » (messages d'avant grisés). Saisie multi-ligne (brouillon gardé), commandes `/`
  envoyées seules avec complétion, commandes `!` dans le dossier du projet (sortie jointe au
  message suivant), images (sélecteur Android, réduites au-delà de 3,5 Mo), appui long sur un
  message : Répondre (citation), Citer un passage, Copier, Étiqueter ; volet Étiquettes ; recherche
  dans le fil (sans accents) ; options modèle / effort / droits ; contexte, alerte « Compacter »,
  coût de la conversation. Liste inversée : seul l'élément qui change se redessine, la vue est
  publiée au plus toutes les 40 ms pendant une réponse.

- **Fichiers** (comme `web/files*.js`) : onglet Fichiers sur les dossiers permis du serveur
  (Personnel, /var/www, /srv), onglet Fichiers de l'écran Projet et bouton Fichiers du chat. Un
  dossier à la fois (fil d'Ariane, retour : dossier parent), marques git, recherche par nom ;
  nouveau fichier ou dossier, envoi depuis le sélecteur d'Android (par morceaux de 1 Mo, 200 Mo au
  plus, « Remplacer ? » si le nom existe), télécharger vers Téléchargements, partager (feuille de
  partage d'Android), renommer, supprimer (confirmé, avec le nombre d'éléments), copier / couper /
  coller, ajouter aux projets. Fichier ouvert : code coloré numéroté (coloration du chat),
  Markdown rendu (« Aperçu »), images (zoom à deux doigts), retour à la ligne au choix, modifier et
  enregistrer (conflit signalé si le fichier a changé), départ confirmé s'il reste des
  modifications. Dans le chat, les chemins du projet cités par Claude (`chemin` ou `chemin:ligne`)
  et les chemins des diffs ouvrent le fichier (à la ligne).
- **Git** (comme `web/git.js`) : onglet Git (choix d'un projet), onglet Git de l'écran Projet et
  bouton Git du chat. Branche et suivi (↑ ↓), Fetch / Pull / Push confirmés (Push forcé à part),
  fichiers indexés, modifiés, non suivis, diff dépliable avec numéros (affichage du chat),
  indexer / désindexer par fichier, tout, ou par morceau ; commit (message proposé, amend
  confirmé) ; historique par pages de 50 et détail d'un commit (message, diff de chaque fichier) ;
  branches locales, distantes et tags.

- **Feuille de route** (comme `web/roadmap.js`) : onglet de l'écran Projet et volet du chat
  (menu ⋮). Phases avec progression (repliables ; celles qui ont une case vide ouvertes, la phase
  en cours à l'écran), cases à cocher (mises à jour sur place ; le pont refuse si la ligne a changé
  ailleurs : « Recharger »), « Faire… » sur une tâche : dans ce chat, dans un nouveau chat (le
  message part dès l'ouverture, une seule fois) ou cette nuit (tâche de fond).
- **Tâches de nuit** (comme `web/pages-tasks.js`) sur l'Accueil : filtres À venir, Finies,
  Échouées, Annulées ; journal d'une tâche relu toutes les 3 s tant qu'elle tourne ; Reprendre
  (ouvre la session dans un chat), Annuler, Supprimer (confirmés) ; Nouvelle tâche (dossier,
  message, quand : dès qu'il y a du quota, cette nuit ou à une heure ; droits ; modèle).
- **Travail du chat** (menu ⋮ du chat) : volet **Changements de la session** (comme
  `web/chat-changes.js`) : fichiers changés par Claude avec leur diff numéroté, « Ouvrir le
  fichier », « Annuler ce fichier », « Revenir ici » avant un message (liste des fichiers remis,
  confirmé ; empreintes envoyées pour que le pont refuse si un fichier a bougé). **Messages
  enregistrés** (icône marque-page de la saisie, comme `web/chat-saved.js`) : insérer, enregistrer
  le texte en cours (tous les projets ou ce projet), supprimer.
- **Réglages** (Plus > Réglages, comme `web/settings.js`) : thème de l'appli (automatique, clair,
  sombre ; propre au téléphone), serveur (changer d'adresse = se reconnecter), déconnexion ; tous
  les réglages du serveur, mêmes groupes et bornes que le web (dont l'effacement automatique
  `chat.auto_clear`), chacun enregistré seul (✓ ou Entrée pour les champs) ; **Téléphone (ntfy)**
  (comme `web/pages-phone.js`) : réglages, nouveau canal (confirmé), lien d'abonnement à ouvrir
  dans ntfy ou copier, essai ; **Appareils** (`/api/tokens`, révoquer par `/api/revoke`).
- **Terminal** (Plus > Terminaux, menu ⋮ du chat, icône de l'écran Projet ; comme
  `web/terminal.js`) : un shell du serveur (`term.*` de `bridge_term.py`) dans un émulateur
  VT100/xterm complet (celui de Termux : couleurs 256 et 24 bits, curseur, effacements, régions de
  défilement, écran alternatif, collage entre crochets, réponses au programme). Clavier du
  téléphone sans suggestions, touches physiques ; barre de touches : Échap, Tab, Ctrl et Alt
  collants, flèches (mode « application » respecté), `| ~ / - _ * & $`, Début, Fin, PgPréc,
  PgSuiv ; Coller, Copier tout le texte, taille du texte (menu ou deux doigts, gardée) ; historique
  au doigt (dans less, vim… le doigt envoie les flèches). Taille envoyée au pont (`term.resize`) à
  chaque changement (clavier ouvert, rotation). Plusieurs terminaux à la fois ; ils restent ouverts
  en changeant d'écran, se rattachent après une coupure (fin de la sortie réaffichée) et ceux
  ouverts ailleurs (version web) se reprennent depuis la liste. Fond sombre dans les deux thèmes.
  **Ajouter un compte** sur l'Accueil : `ccs add <nom>` dans un terminal, comme le web.

- **Notifications** (Plus > Réglages > Notifications, actives par défaut) : un chat qui finit son
  tour (retour au repos après un travail, pas après « Arrêter »), une autorisation ou une question
  de Claude. Canaux « Fin de tour » et « Attend ta réponse » ; titre de la conversation, toucher
  ouvre le chat ; **Autoriser** / **Refuser** dans la notification d'une autorisation
  (`chat.answer`). Rien pour le chat affiché à l'écran (ses notifications partent quand on
  l'ouvre) ; une demande réglée ailleurs retire la sienne. **Rappel unique** si la réponse se fait
  attendre, avec le réglage du serveur « Rappel d'attente » (`alerts.waiting_reminder_min`,
  10 min), comme le bureau. Mécanisme : service de premier plan (type `remoteMessaging`, sans
  limite de durée) qui garde le WebSocket en arrière-plan, notification discrète « CCS connecté »
  (canal « Connexion en arrière-plan », à importance minimale, masquable). Il rattache le
  WebSocket à tous les chats du pont (`chat.list` puis `chat.attach`, à chaque connexion ; chaque
  minute pour les chats ouverts ailleurs) ; pas de réveil programmé, Doze respecté (la reconnexion
  suit le réseau). Permission des notifications (Android 13+) demandée au premier chat ouvert, ou
  depuis les réglages. **ntfy** (page Téléphone du serveur) fait la même chose sans l'appli : les
  réglages le signalent s'il est actif, pour ne garder que l'un des deux.
- **Partage vers CCS** (feuille de partage d'Android : texte, images, fichiers, un ou plusieurs) :
  choisir un chat en cours ou « Nouveau chat… » (dossier). Le texte va dans la saisie, les images
  (PNG, JPEG, GIF, WebP ; 5 au plus) en pièces jointes, les autres fichiers sont envoyés dans le
  dossier du projet (`files.upload`, jamais d'écrasement : « nom (2).ext ») puis cités dans la
  saisie. Rien ne part à Claude avant qu'on envoie.
- **Raccourcis d'appli** (appui long sur l'icône) : « Nouveau chat » (feuille Nouvelle session) et
  « Sessions ».
- **Sous-agents** dans le chat : un sous-agent fini quitte la barre des pastilles (sauf celui qu'on
  regarde) ; « Terminés (n) » au bout de la barre liste les finis, le plus récent en tête, et
  rouvre leur vue (comme `tidyPills` de `web/chat.js`).

## Connexion

- **Appairage (recommandé)** : identifiant et mot de passe Ubuntu, puis code TOTP, envoyés à
  `/api/pair`. Première connexion : le secret TOTP s'affiche (copier, ou l'ouvrir dans l'appli
  d'authentification), puis le premier code part à `/api/enroll`. Le serveur rend un **jeton
  d'appareil**, envoyé ensuite en `Authorization: Bearer` ; il est gardé chiffré (AES-GCM, clé du
  Keystore d'Android, sauvegarde désactivée) et se révoque depuis la version web.
- **Portier** (si `/api/portier` le dit actif) : la page de Portier s'ouvre dans une vue web ;
  au retour sur le serveur, l'appli garde les cookies (chiffrés), puis demande un **jeton
  d'appareil** durable (`POST /api/app-token`, nom : le modèle du téléphone, « Pixel 4 XL ») et
  passe au Bearer ; les cookies restent envoyés à côté (ils servent à `/api/tokens` et
  `/api/revoke`). Si le serveur ne connaît pas encore la route (404), l'appli garde les cookies
  seuls ; une connexion Portier d'avant le jeton le demande une fois au démarrage.

Jeton révoqué ou session finie (401, ou fermeture 4001) : retour à l'écran de connexion. Sinon le
client se reconnecte seul (1 s, 2 s… 30 s ; tout de suite quand le réseau revient).

L'adresse du serveur se change sur l'écran de connexion (**Changer**).

## Construire

Le VPS n'a pas le SDK Android : on construit sur `pc-bureau` (SDK `~/Android`, JDK 17), depuis ce
dossier. `local.properties` (ignoré par git) est créé par la commande :

```sh
ccs distant lancer --machine pc-bureau --outil sh --rapatrier app/build/reports/tests -- sh -c \
  'export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64; echo "sdk.dir=$HOME/Android" > local.properties; ./gradlew testDebugUnitTest'
ccs distant lancer --machine pc-bureau --outil sh --rapatrier app/build/outputs/apk -- sh -c \
  'export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64; echo "sdk.dir=$HOME/Android" > local.properties; ./gradlew assembleRelease'
```

L'APK arrive dans `app/build/outputs/apk/release/app-release.apk`. L'émulateur de Termux vient de
JitPack (`https://jitpack.io`, limité au groupe `com.github.termux.termux-app`). Gradle est bridé
(`gradle.properties` : 2 Go, compilateur Kotlin dans le même processus) pour ne pas réveiller
Gagarine sur pc-bureau.

**Version** : `versionName` et `versionCode` dans `app/build.gradle.kts` ; le `versionCode` doit
toujours augmenter (32 aujourd'hui pour 0.28.0 ; l'appli Flutter 0.26.1 avait 27).

## Signature

La version de publication est signée avec la **clé de débogage** de la machine qui construit
(`~/.android/debug.keystore` de `pc-bureau`), comme l'ancienne appli : il faut toujours construire
sur `pc-bureau` pour installer une mise à jour par-dessus.

## Installer sur le téléphone

Depuis `pc-bureau` (débogage sans fil activé sur le téléphone) :

```sh
adb connect 10.228.2.44:5555
adb -s 10.228.2.44:5555 install -r app-release.apk
```

## Structure

- `app/src/main/java/com/mawena/ccs/`
  - `reseau/CodecRpc.kt` : format des trames du WebSocket (appel, réponse, erreur, événement).
  - `reseau/CcsClient.kt` : client WebSocket (OkHttp) : appels suspendus, événements en Flow,
    reconnexion, état observable.
  - `reseau/ApiHttp.kt`, `reseau/Modeles.kt` : routes HTTP (`/api/health`, `/api/pair`,
    `/api/enroll`, `/api/portier`, `/api/session`) et modèles kotlinx.serialization.
  - `donnees/` : adresse du serveur, coffre chiffré des identifiants, enregistrement dans
    Téléchargements (MediaStore).
  - `reseau/ModelesComptes.kt`, `reseau/ModelesSessions.kt` : réponses des RPC des comptes, du
    bilan, de l'analyse, des projets, conversations, chats et corbeille.
  - `logique/Format.kt` : textes et calculs sans Android (« il y a… », nombres courts, chemins,
    états des chats, dossiers proposés par « Nouvelle session »).
  - `donnees/Recents.kt` : derniers dossiers ouverts.
  - `reseau/ModelesFichiers.kt` : réponses de `files.*`, `work.files` et `git.*`.
  - `logique/Fichiers.kt` (chemins, fil d'Ariane, familles, tailles, morceaux), `LiensFichiers.kt`
    (chemins cités dans le chat), `Git.kt` (groupes de fichiers, suivi, diffs en lignes, refs).
  - `ui/Demandes.kt` : confirmations et saisies de nom attendues par une coroutine.
  - `ui/fichiers/` : `PanneauFichiers.kt`, `EcranFichier.kt` (lecture, édition, image),
    `EcransFichiers.kt` (onglet, projet), `Transferts.kt` (téléchargement, envoi, partage par
    FileProvider), `Commun.kt` (icônes, presse-papier des fichiers).
  - `ui/git/` : `PanneauGit.kt`, `EcransGit.kt` (onglet, projet, détail d'un commit).
  - `reseau/ModelesTravail.kt` : réponses de `roadmap.*`, `tasks.*`, `work.changes`,
    `work.rewind_*`, `work.saved.*`, `settings.*`, `phone.*`, `term.*` et de `/api/tokens`.
  - `logique/Travail.kt` (feuille de route, tâches de fond, diff unifié, retour arrière),
    `DefReglages.kt` (groupes, bornes et lecture des réglages du serveur), `Touches.kt` (Ctrl et
    Alt collants, flèches, taille du terminal).
  - `donnees/PrefsAppli.kt` : thème, taille du texte du terminal, notifications.
  - `logique/Veilleur.kt` : décision des notifications (fin de tour, attente, rappel, chat
    affiché), sans Android ; `logique/Partage.kt` : analyse d'un partage (texte, images, fichiers),
    noms libres, saisie composée.
  - `notif/` : `ServiceVeille.kt` (service de premier plan), `Veille.kt` (rattachement aux chats,
    file d'événements), `Notifs.kt` (canaux, notifications), `RecepteurActions.kt` (Autoriser /
    Refuser) ; `ui/FeuillePartage.kt` (choix du chat pour un partage), `ui/Notifications.kt`.
  - `ui/travail/` : `PanneauFeuilleDeRoute.kt`, `SectionTaches.kt`, `PanneauChangements.kt`,
    `FeuilleMessages.kt` ; `ui/reglages/EcranReglages.kt`.
  - `terminal/` : `SessionTerminal.kt` (un terminal du pont dans l'émulateur), `Terminaux.kt`
    (sessions, événements `term.output` / `term.exit`, rattachement, saisie dans l'ordre),
    `VueTerminal.kt` (dessin, clavier, gestes) ; `ui/terminal/` : écran d'un terminal (barre de
    touches) et liste.
  - `logique/` (chat) : `EvenementChat.kt` (événements du pont), `FilChat.kt` (fil : réception,
    sous-agents, regroupement), `Markdown.kt`, `Coloration.kt`, `Diff.kt`, `Citation.kt`,
    `Outils.kt`, `Envoi.kt` (commandes `/` et `!`, recherche, étiquettes, alerte de contexte).
  - `ui/` : thème CCS, navigation (`Destinations.kt`), composants communs (`Commun.kt`), écrans
    (connexion, Portier, accueil, bilan, analyse, sessions, projet, plus).
  - `ui/chat/` : `ModeleChat.kt` (ViewModel : RPC et événements du chat), `EcranChat.kt`,
    `ElementsChat.kt`, `MarkdownVue.kt`, `Saisie.kt` (saisie, options, images), `Feuilles.kt`.
- `app/src/main/res/` : icône adaptative (motif dans la zone sûre, fond uni, version monochrome),
  petite icône des notifications, raccourcis d'appli (`xml/raccourcis.xml`).
- `app/src/test/` : tests JVM (codec RPC, client contre un faux serveur, adresse, coffre, récents,
  lecture des réponses du pont, textes et filtres, événements et fil du chat, Markdown,
  coloration, diff, citation, envoi, chemins et liens de fichiers, réponses de `files.*` et `git.*`,
  feuille de route, tâches, diff unifié, réglages, touches, émulateur du terminal sur la JVM,
  `/api/app-token`, `/api/tokens` et `/api/revoke` contre un faux serveur, décision des
  notifications et rappel, analyse du partage, barre des sous-agents).

## Licence

Celle de CCS (voir `LICENSE` à la racine du dépôt).

L'émulateur du terminal vient des modules `terminal-emulator` et `terminal-view` de Termux
(<https://github.com/termux/termux-app>, version 0.118.0, par JitPack), sous **licence Apache 2.0**
(code issu d'Android-Terminal-Emulator de Jack Palevich ; le reste de Termux est sous GPLv3 et
n'est pas utilisé). L'appli s'en sert tel quel : `TerminalEmulator` pour l'analyse des séquences,
`TerminalRenderer` et `KeyHandler` pour le dessin et les touches.
