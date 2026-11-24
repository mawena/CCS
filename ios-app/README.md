# CCS pour iPhone

CCS, c'est Claude Code partout : sur tous tes appareils, toutes tes machines et tous tes comptes.
Cette appli met dans l'iPhone les sessions de tes PC et de ton serveur (chat, fichiers, Git,
terminal, vocal), le réseau maillé, le calcul réparti, les commandes root à valider et les
comptes Claude Code qui travaillent comme un seul.

Application iPhone native (Swift + SwiftUI, iOS 17) de CCS. Elle parle directement à l'API du
serveur (par défaut https://ccs.mawena.cloud) : WebSocket `/api/ws?protocol=1` (protocole 1 du pont) pour la RPC et les
événements, routes HTTP pour la connexion. Même périmètre que l'appli Android
(`android-app/`, qui sert de référence).

- **Connexion** : appairage (mot de passe + code TOTP) ou Portier ; jeton d'appareil gardé dans
  le trousseau, révocable dans Réglages → Appareils.
- **Accueil** : comptes (jauges, bascule), pause, bilan de santé, analyse, tâches de nuit,
  « Ajouter un compte Claude » (`ccs add` dans un terminal).
- **Sessions et projets** : chats en cours, projets, historique, nouvelle session, corbeille.
- **Chat** : fil en direct (markdown, code, outils, diffs, sous-agents), autorisations et
  questions, pièces jointes, citation, options, `/clear`, étiquettes, recherche, coût ;
  changements de la session, feuille de route, messages enregistrés.
- **Vocal** : bouton micro de la saisie (dictée fr-FR, résultats en direct, arrêt après ~2 s de
  silence ; le texte s'ajoute sans être envoyé) ; « Lire » dans le menu d'une réponse de Claude
  (voix française, markdown retiré) ; réglage « Lire les réponses à voix haute » (Réglages → Voix).
- **Parler à Jarvis** (Plus → Parler à Jarvis, raccourci « Parler à Jarvis » de l'appli
  Raccourcis / Siri / bouton Action, lien `ccs://jarvis`) : l'assistant vocal de la maison, par le
  relais du serveur CCS (`/api/jarvis/oreille`, même jeton que l'appli). Appairage une fois :
  scanner le QR code de `jarvis pair` avec l'appareil photo (lien `jarvis://pair?…`, qui ouvre
  CCS), coller l'adresse, ou saisir code et empreinte ; jeton et identifiant d'oreille dans le
  trousseau. Puis un bouton : maintenir pour parler (fin au relâché), ou toucher une fois (fin au
  silence) ; micro `AVAudioEngine` rééchantillonné en 16 kHz, texte et voix de la réponse,
  écoute relancée seule si Jarvis pose une question. Le raccourci ouvre l'écran déjà en écoute.
- **Fichiers** et **Git** : navigation, lecture colorée (Git dans l'écran d'un projet, plus d'onglet Git en bas), édition, envoi et téléchargement ;
  état, diff, indexation par morceau, commit, journal, pull/push. L'onglet Fichiers parcourt
  tous les appareils : barre défilante « Serveur CCS » puis chaque PC de `machines.list`
  (grisé avec « hors ligne » ou « ni réseau maillé ni tunnel » s'il est injoignable). Un autre
  appareil que la machine pilotée a sa propre connexion (`/api/ws?protocol=1&machine=<id>`),
  sans changer la machine pilotée, fermée en quittant l'onglet ; le dernier appareil choisi est
  gardé ; « <nom> injoignable : … » avec Réessayer si la connexion échoue.
- **Terminal** (Plus → Terminaux, bouton du projet, menu du chat) : émulateur SwiftTerm
  (couleurs, écran alternatif, curseur application), barre de touches (Échap, Tab, Ctrl et Alt
  collants, flèches, symboles, Début/Fin, pages), coller, copier tout, taille du texte ; les
  terminaux du serveur (ouverts depuis le web) se reprennent, et se rattachent après une coupure.
- **Machine pilotée** (bouton des Sessions, Plus, bandeau « Machine pilotée : … ») : le PC
  ou toute machine du relais Ricochet joignable par le tunnel ; toute l'appli la suit (sessions,
  fichiers, Git, terminal, notifications). Retour à « Ce serveur » d'un toucher.
- **Réseau** (onglet) : le réseau maillé (carte, fiche de chaque appareil, ping, renommer,
  retirer, ajout d'un PC ou d'un téléphone) et le calcul réparti au même endroit : chaque fiche
  qui est une machine de calcul porte sa charge, sa mémoire, ses outils, ses places et sa limite ;
  les machines joignables seulement par Ricochet ont leur fiche « Par Ricochet ». Travaux
  `ccs remote` en cours, à venir et finis, journal en direct, « Arrêter », « Lancer une
  commande » (maintenant, cette nuit ou à une heure), secours Ricochet (réglages du relais).
- **Son partagé** (Plus → Son, phase 42, `docs/audio.md`) : tant que l'appli est connectée,
  l'iPhone s'annonce au pont toutes les 30 s (`audio.announce`, nom du pair du réseau maillé qui
  porte son adresse 100.64.x) comme sortie et comme source. Sortie : écoute UDP 4010, RTP/Opus,
  trames de 10 ou 20 ms, tampon de gigue adaptatif 20-150 ms (départ 30 ms), tampon matériel de
  5 ms, lecture `AVAudioEngine`, continue en arrière-plan (mode audio). **Rester à l'écoute**
  (interrupteur de l'écran Son, désactivé par défaut) : récepteur UDP toujours ouvert sur le port
  annoncé et session audio qui joue du silence, pour que l'appli en arrière-plan ne soit pas
  suspendue ; tout paquet RTP reçu est joué tout de suite, même si l'ordre « receive » a été raté.
  Reprise après un appel ou une autre appli audio. Coûte un peu de batterie.
  Source : extension de diffusion ReplayKit `Diffusion` (dans `CCS.app/PlugIns`) qui encode le
  son des applis en Opus 96 kb/s ; la cible lui est passée par le groupe d'applis
  `group.<bundle id>` (seul droit demandé, créé par SideStore). Écran Son : flux en cours avec
  « Arrêter », « Envoyer le son de cet iPhone vers… », envoi d'une source vers une sortie.
- **Mot de passe root** : quand la machine pilotée demande le mot de passe root (`ccs root`,
  `sudo -A` de Claude), une feuille s'ouvre au premier plan avec la commande, « Envoyer »,
  « Refuser » ou « Plus tard » ; le mot de passe n'est jamais gardé sur le téléphone (il l'est
  1 h en mémoire sur la machine). Bandeau « Root gardé, X min » avec « Oublier », avis à chaque
  commande lancée en root. `ccs://root` rouvre la demande.
- **Liens de fichiers** : dans le chat, les chemins cités par Claude (`chemin:ligne`) et les
  fichiers des diffs s'ouvrent d'un toucher.
- **Notifications locales** : fin de tour, autorisation ou question en attente, rappel d'une
  attente longue (réglage `alerts.waiting_reminder` du serveur) ; « Autoriser » / « Refuser »
  depuis la notification, toucher pour ouvrir le chat. Aucune pour le chat affiché.
- **Partage vers un chat** : depuis la feuille de partage d'iOS, « Ouvrir dans CCS » (fichiers
  de tout type) ; pour du texte ou un lien, un raccourci qui ouvre
  `ccs://partager?texte=<texte encodé>`. Les fichiers partent dans le dossier du projet (sans
  rien écraser), puis le chat s'ouvre avec le texte et les fichiers cités dans la saisie : rien
  n'est envoyé à Claude sans relecture.

## Limites (identifiant Apple gratuit)

- L'appli est signée par SideStore pour 7 jours : la rafraîchir dans SideStore avant (SideStore
  le fait en arrière-plan si LocalDevVPN est connecté).
- Pas de notifications push (APNs réservé au compte payant) : les notifications ne partent que
  tant que l'appli est ouverte, ou une trentaine de secondes après son passage en arrière-plan.
- Pas d'extension de partage (elle demanderait un deuxième identifiant d'appli et un groupe
  d'applis) : d'où « Ouvrir dans CCS » et le lien `ccs://partager`.

## Installation avec SideStore

1. SideStore installé sur l'iPhone (par exemple avec iloader depuis un PC), LocalDevVPN connecté.
2. Ouvrir dans Safari le lien de l'`.ipa` (`CCS-<version>.ipa` de la release GitHub), puis
   « Ouvrir dans SideStore » ; ou dans SideStore : My Apps → « + » → choisir le fichier.
3. Mises à jour : ajouter la source SideStore
   `https://raw.githubusercontent.com/mawena/CCS/main/ios-app/sidestore.json` (Sources → « + ») ;
   chaque release y ajoute sa version.

## Construction (sans Mac)

Le projet Xcode est décrit par XcodeGen (`project.yml`) et construit sur **Codemagic**
(`codemagic.yaml` à la racine du dépôt, workflow `ios-natif`) : projet généré, tests XCTest sur
simulateur, archive Release non signée, `CCS.ipa` en artefact. Un push sur `feature/ios-*`,
`develop` ou un tag `v*` qui touche `ios-app/` lance une construction ; sinon par l'API :

```sh
curl -H "x-auth-token: $JETON" -H 'Content-Type: application/json' \
  -d '{"appId":"<app>","workflowId":"ios-natif","branch":"develop"}' https://api.codemagic.io/builds
```

Sur un Mac : `brew install xcodegen && cd ios-app && xcodegen generate && open CCS.xcodeproj`.

Dépendance : [SwiftTerm](https://github.com/migueldeicaza/SwiftTerm) 1.10.1 (Swift Package Manager).

## Structure

```
ios-app/
├── project.yml           projet XcodeGen (cibles CCS et CCSTests, paquet SwiftTerm)
├── sidestore.json        source SideStore (versions publiées)
├── CCS/
│   ├── CCSApp.swift      point d'entrée, cycle de vie, liens ouverts
│   ├── Donnees/          adresse, trousseau, préférences
│   ├── Reseau/           client WebSocket, codec RPC, JSON, modèles des réponses
│   ├── Logique/          logique sans UI (fil du chat, markdown, diff, git, veilleur, partage…)
│   ├── Notif/            veille des chats et notifications locales
│   ├── Terminal/         sessions SwiftTerm, liste et écran des terminaux
│   ├── Partage/          feuille « Partager vers CCS »
│   ├── Jarvis/           oreille de Jarvis : lien du relais, micro et voix, écran, raccourci (App Intent)
│   └── UI/               écrans SwiftUI (accueil, sessions, chat, fichiers, git, réglages…)
└── CCSTests/             tests XCTest de la logique
```

## Licence

Celle du dépôt CCS (voir le `README.md` à la racine).
