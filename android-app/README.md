# CCS pour Android

Application Android native (Kotlin + Jetpack Compose, Material 3) de CCS. Elle parle directement
à l'API du serveur (par défaut https://ccs.mawena.cloud) : WebSocket `/api/ws` pour la RPC et les
événements, routes HTTP pour la connexion. Elle remplace l'ancienne coquille Flutter (vue web),
avec le même identifiant `com.mawena.ccs` : elle s'installe par-dessus.

État : phase 25, tâches 1 à 4 de `ROADMAP.md`. Connexion, client WebSocket, navigation (Accueil,
Sessions, Fichiers, Git, Plus).

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

Fichiers et Git arrivent avec les tâches suivantes.

## Connexion

- **Appairage (recommandé)** : identifiant et mot de passe Ubuntu, puis code TOTP, envoyés à
  `/api/pair`. Première connexion : le secret TOTP s'affiche (copier, ou l'ouvrir dans l'appli
  d'authentification), puis le premier code part à `/api/enroll`. Le serveur rend un **jeton
  d'appareil**, envoyé ensuite en `Authorization: Bearer` ; il est gardé chiffré (AES-GCM, clé du
  Keystore d'Android, sauvegarde désactivée) et se révoque depuis la version web.
- **Portier** (si `/api/portier` le dit actif) : la page de Portier s'ouvre dans une vue web ;
  au retour sur le serveur, l'appli garde les cookies (chiffrés) et les envoie en `Cookie`. La
  session dure ce que dure celle de Portier.

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

L'APK arrive dans `app/build/outputs/apk/release/app-release.apk`. Gradle est bridé
(`gradle.properties` : 2 Go, compilateur Kotlin dans le même processus) pour ne pas réveiller
Gagarine sur pc-bureau.

**Version** : `versionName` et `versionCode` dans `app/build.gradle.kts` ; le `versionCode` doit
toujours augmenter (29 pour 0.27.0 ; l'appli Flutter 0.26.1 avait 27).

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
  - `logique/` (chat) : `EvenementChat.kt` (événements du pont), `FilChat.kt` (fil : réception,
    sous-agents, regroupement), `Markdown.kt`, `Coloration.kt`, `Diff.kt`, `Citation.kt`,
    `Outils.kt`, `Envoi.kt` (commandes `/` et `!`, recherche, étiquettes, alerte de contexte).
  - `ui/` : thème CCS, navigation (`Destinations.kt`), composants communs (`Commun.kt`), écrans
    (connexion, Portier, accueil, bilan, analyse, sessions, projet, plus).
  - `ui/chat/` : `ModeleChat.kt` (ViewModel : RPC et événements du chat), `EcranChat.kt`,
    `ElementsChat.kt`, `MarkdownVue.kt`, `Saisie.kt` (saisie, options, images), `Feuilles.kt`.
- `app/src/main/res/` : icône adaptative (motif dans la zone sûre, fond uni, version monochrome).
- `app/src/test/` : tests JVM (codec RPC, client contre un faux serveur, adresse, coffre, récents,
  lecture des réponses du pont, textes et filtres, événements et fil du chat, Markdown,
  coloration, diff, citation, envoi).

## Licence

Celle de CCS (voir `LICENSE` à la racine du dépôt).
