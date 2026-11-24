# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté

- **Chat riche** (web et bureau) :
  - images agrandissables d'un clic (web) ;
  - lecteurs pour les liens et chemins de sons et de vidéos ;
  - blocs `ccs` en JSON : `choix` (boutons qui envoient un message), `carte` et `cartes` (photo, prix, lien, actions), `formulaire` (web seulement).
  - Claude en est averti à chaque lancement. Format : `docs/chat-riche.md`.
- **Market** présente ses annonces en cartes et propose des choix pour la suite.

### Modifié

- **Market** n'est plus un onglet : c'est l'option « Market (Marketplace Facebook) » de la nouvelle session (web et bureau).
- **Onglets** : Jarvis passe avant Analyse ; Réglages reste en dernier.
- **Version web** : la CSP autorise les images https et les médias `'self' blob: https:`.

## [1.14.0] — 2026-11-24

### Corrigé

- **Nouvelle session au bureau** : la fenêtre des paramètres ne s'affichait pas dans la plupart
  des cas. Le bouton « Nouvelle session » d'un projet et « Nouvelle session » d'un chat au cache
  expiré ouvraient directement un chat, sans dialogue (seul « Avec des options… » du menu le
  montrait) ; lancé par `ccs appli --nouvelle-session`, le dialogue pouvait être présenté avant
  que la fenêtre n'apparaisse. Désormais, comme au web, tout nouveau chat passe par le dialogue,
  présenté seulement une fois la fenêtre affichée.

### Modifié

- **Dialogue « Nouvelle session » du bureau aligné sur le web** : mêmes champs dans le même
  ordre (dossier, compte, fournisseur, modèle, effort, droits), mêmes valeurs par défaut (droits
  des réglages `chat.rights`, « Demander » sinon) et mêmes boutons (Annuler, Terminal, Ouvrir un
  chat). Les listes viennent d'une source commune, `chat_options.new_session_form`, envoyée au
  web par `chat.providers` (fini les listes en dur dans `sessions-new.js`).

### Ajouté

- **Effort dans la Nouvelle session** (bureau et web) : niveau de réflexion choisi à
  l'ouverture (`--effort`), caché pour un autre fournisseur que Claude.

## [1.13.0] — 2026-11-24

### Ajouté

- **Fournisseurs de modèles** (phase 46) : faire tourner Claude Code chez OpenRouter ou DeepSeek
  (API compatibles Anthropic) pour des modèles ouverts moins filtrés ou moins chers. Choix du
  fournisseur et du modèle dans la Nouvelle session (bureau et web), les options du chat et les
  tâches (`--provider`) ; le libellé de l'onglet le montre. Clé lue par `apiKeyHelper` dans un
  fichier 600, jamais dans la ligne de commande ; fournisseur sans clé refusé avant le lancement.
  Préréglages vérifiés : DeepSeek V4.1 Flash par défaut chez OpenRouter, au moins cher
  (`deepseek/deepseek-v4.1-flash-1017:floor`), GLM 5.3, Grok 4.7, Kimi K3.1 Pro, Qwen3
  Coder Next… ; fournisseurs ajoutés dans `~/.config/ccs/providers.json`.
- `ccs provider list | show | models | key | test` (ancien nom `fournisseur` caché).
- Onglet **Market** (phase 45, web et bureau) : un chat Claude dédié qui cherche sur Facebook
  Marketplace au Togo et répond par un classement au meilleur rapport qualité-prix (prix en CFA,
  liens des annonces, raisons) ; on peut aussi lui donner le lien d'un vendeur. Le pont rouvre
  toujours le même chat (`market.open`).
- `ccs market search | seller | item | status | login` : Chrome sans interface du VPS, branché sur
  un tunnel `ssh -D` vers pc-bureau par le réseau maillé (adresse de sortie vérifiée, pas de repli
  direct), images bloquées, rythme humain, Chrome fermé après chaque commande ; Messenger jamais
  lu. Connexion une fois par `ccs market login` (Chrome sur l'écran de pc-bureau, cookies exportés
  par CDP et gardés en 600).

### Modifié

- Descriptions de CCS revues partout (README, site, paquets, page man, aide, appli web, dépôt
  GitHub) : CCS n'est plus seulement un outil multi-comptes, mais Claude Code partout — appareils,
  machines et comptes.

- Bureau, onglet Réseau au niveau du web (phase 44) : « Appareils » donne une fiche dépliable par
  appareil du réseau maillé (genre, en ligne ou non, chemin réel, adresse à copier, adresses
  publiées avec leur type, trafic, « Mesurer », « Renommer », « Retirer du réseau » confirmé), la
  machine de calcul Ricochet rattachée à sa fiche ; « Ajouter un appareil » (PC Linux par lien
  Ricochet ou clé jetable, Android, iPhone) ; sections dans l'ordre du web, « Secours Ricochet » en
  bas. Mêmes méthodes `network.*` que le web, par le pont du serveur CCS (repli sur ce PC s'il est
  injoignable).

## [1.12.0] — 2026-11-24

### Ajouté

- Son partagé sur le réseau maillé (phase 42) : chaque appareil CCS qui sait jouer du son est une
  sortie pour les autres, chaque appareil qui sait capter le sien est une source ; on envoie le son
  dans tous les sens (iPhone → pc-bureau, pc-bureau → Pixel…). Le serveur CCS ne fait que la mise
  en relation (`audio.announce`, `audio.list`, `audio.send`, `audio.stop`, `audio.forget`) ; le son
  passe en RTP/Opus, en UDP direct entre les adresses 100.64.x (port 4010). Protocole :
  `docs/audio.md`.
- Linux : `ccs audio list | send <source> <sortie> | stop | enable | disable |
  receive`, service utilisateur `ccs-audio` (désactivé par défaut). Chaque appareil distant
  apparaît comme une sortie PipeWire (« iPhone de Charles ») : la choisir dans les réglages du son
  lance l'envoi, ne plus s'en servir l'arrête après 10 s. GStreamer pour le son.
- macOS et Windows : le même agent (`ccs audio agent`) joue le son reçu ; source par BlackHole
  (macOS) ou `wasapi2src loopback=true` (Windows), sans sorties virtuelles. Non essayé.
- Android : écran Son (Plus → Son partagé), lecture en service au premier plan, envoi du son du
  téléphone par AudioPlaybackCapture (Android 10+, accord à chaque départ).
- iPhone : écran Son (Plus → Son), lecture en arrière-plan, envoi par une extension de diffusion
  ReplayKit « CCS » (contenus protégés muets). L'extension compte pour un App ID de plus sur le
  compte Apple gratuit.
- Web (Réseau → Son partagé) et bureau GTK (onglet Réseau) : appareils, flux en cours, « Envoyer le
  son » et « Arrêter ».

### Modifié

- **Toutes les commandes passent en anglais** (`ccs status`, `ccs remote run`, `ccs audio send`,
  `ccs chat clear`, `ccs task add`, `ccs backup`…), options comprises (`--when night`, `--detach`,
  `--name`, `--notify`…). Les noms français restent acceptés, sans paraître dans l'aide : rien ne
  casse dans les scripts, raccourcis ni services. README, manuel et aides suivent.

### Corrigé

- Tests : `test_terminals_gui` ne se chargeait plus (import manquant).
- Chat web : on voit enfin les sous-agents de fond travailler. La CLI ne passe que leur lancement
  et leur fin ; le pont lit leur transcription toutes les 3 s et envoie leurs étapes (textes,
  outils, résultats) dans leur vue, comme pour un sous-agent au premier plan.
- Chat web : après un rechargement de la page, une reprise de la conversation ou un `/compact`,
  les pastilles des sous-agents lancés avant reviennent (`agents` dans `chat.attach`) et leur vue
  se remplit depuis leur transcription (`chat.agent_log`). Ceux d'avant une reprise sont marqués
  arrêtés s'ils ne s'étaient pas finis.
- Jarvis : la liste des sous-agents d'un chat compte aussi ceux lancés avant sa reprise.

## [1.11.0] — 2026-11-24

### Ajouté

- « Ajouter un PC » : option « Installer aussi CCS et Claude Code » (`ccs distant ajouter
  --complet`, case dans le web, le bureau, Android et l'iPhone) ; la ligne à coller installe alors
  CCS (dépôt APT) et Claude Code après l'inscription.
- Bureau : section « Ajouter un PC » dans l'onglet Réseau.
- Bureau : `claude` lancé à la main dans un onglet shell et bloqué par une limite reçoit
  « continue » quand le compte change ou que la limite est levée (comme les terminaux du web).

## [1.10.0] — 2026-11-24

### Ajouté

- Bureau : trois nouveaux onglets, comme la version web. **Réseau** : appareils du réseau maillé
  (adresse, chemin, « Mesurer » par `tailscale ping`), puis machines, travaux distants, lancement
  d'une commande et secours Ricochet. **Fichiers** : arbre d'un dossier (personnel au départ,
  « Changer de dossier ») et éditeur. **Jarvis** : ouvre la page Jarvis du serveur CCS, ou mène
  aux Réglages s'il n'y a pas de serveur. `gui --page reseau|fichiers|jarvis`, Ctrl+1 à Ctrl+6.

### Modifié

- Bureau : la page Machines quitte les Réglages pour l'onglet Réseau.
- Feuille de route rangée : ce qui reste à faire en tête de `ROADMAP.md`, phases terminées dans
  `docs/ROADMAP-fait.md`.

## [1.9.0] — 2026-11-23

### Ajouté

- Bureau : menu principal → « Parler à Jarvis… », qui ouvre la page Jarvis de la version web du
  premier serveur CCS appairé.

## [1.8.1] — 2026-11-23

### Corrigé

- Appli iPhone : libellé du chemin Ricochet aligné sur Android (« Par Ricochet ») ; tests de la
  construction iOS de nouveau au vert.

## [1.8.0] — 2026-11-23

### Ajouté

- Jarvis pilote tout le réseau CCS par le pont : `jarvis.state` (vue d'ensemble lisible à voix
  haute), `jarvis.sessions`, `jarvis.subagents`, `jarvis.stop_subagent`, `jarvis.stop_session`
  (avec `confirme`, sinon la cible résolue et la question à poser), `jarvis.start_session` ;
  noms approchés (« la session GliGli ») et rangs (« le premier sous-agent ») ; protocole dans
  `docs/jarvis.md`. Les sous-agents des chats sont suivis et s'arrêtent un par un.
- Onglet Fichiers (web, Android, iPhone) : affichage en grille au choix (bouton Liste/Grille,
  choix mémorisé) ; toucher un dossier y entre, « ⋯ » ou appui long garde toutes les actions.

### Modifié

- Applis Android et iPhone : plus d'onglet Git en bas ; Git reste dans l'écran d'un projet.

### Corrigé

- iPhone : la 1.7.0 ne compilait pas (`switch` incomplet sur le chemin « Ricochet » de l'onglet Réseau).

## [1.7.0] — 2026-11-23

### Ajouté

- Onglet « Fichiers » : choix de l'appareil en haut (serveur CCS et chaque PC du réseau maillé où
  CCS est installé). Chaque appareil s'ouvre par sa propre connexion, relayée par le pont du
  serveur (SSH par le réseau maillé, Ricochet en secours), sans changer la machine pilotée.
  Adresse `#/fichiers/@<machine>/<chemin>`. Web, Android et iPhone.
- L'ancienne page « Machines » est fondue dans l'onglet « Réseau », sans information en double :
  charge, mémoire, outils, places et limite dans la fiche de chaque appareil ; sections Travaux,
  Lancer une commande et, repliée, Secours Ricochet ; l'ajout d'un PC par Ricochet devient
  l'onglet « PC Linux » de l'ajout d'appareil quand le jeton opérateur est réglé. `#/machines`
  mène à l'onglet Réseau. Web, Android et iPhone.
- `machines.list` donne `host`, `mesh` et `mesh_ip` pour rattacher une machine à sa fiche.

- Oreilles de Jarvis (assistant vocal, projet voisin) : page « Jarvis » de la version web, pour
  appairer le navigateur (adresse `jarvis://pair?…` de `jarvis pair`, ou code et empreinte) puis
  parler à Jarvis avec un bouton (maintenir, ou toucher puis se taire) ; le texte de la réponse
  s'affiche et la voix de Jarvis est jouée, même hors de la maison.
- ccs-web : point d'entrée `/api/jarvis/oreille` (session CCS exigée) qui relaie l'oreille vers
  le cerveau par le pont de l'utilisateur : tunnel Ricochet, TLS épinglé sur l'empreinte du
  cerveau, limites de taille, erreur immédiate si Jarvis est injoignable.
- Applis Android et iPhone : Plus → « Parler à Jarvis », sur le même relais (appairage par le QR
  code de `jarvis pair` scanné avec l'appareil photo, l'adresse collée ou code et empreinte ;
  jeton gardé chiffré / dans le trousseau ; bouton maintenir ou toucher, voix de la réponse,
  écoute relancée si Jarvis pose une question). Raccourci « Parler à Jarvis » (raccourci d'appli
  Android, App Intent iPhone) et lien `ccs://jarvis` qui ouvrent l'écran déjà en écoute.
- Pont : méthodes `jarvis.*` et réglages `jarvis.machine`, `jarvis.port` (par défaut
  `laptop-maison:7341`) et `jarvis.fingerprint`.
- Fichiers (web) : « Télécharger (.zip) » dans le menu ⋯ d'un dossier, pour le récupérer en entier
  (méthode `files.archive` du pont).

### Modifié

- Tout passe d'abord par le réseau maillé, Ricochet restant le secours : liste des machines
  (machines du réseau déclarées par `reseau` dans `machines.toml` même sans Ricochet),
  `ccs distant`, nom de machine de `ccs root`, et la connexion au cerveau de Jarvis (connexion
  directe sur son adresse 100.64.x, tunnel Ricochet si elle échoue).
- Ancien dépôt APT de GitHub Pages archivé (tag `archive/ancien-depot-apt`) : `make apt`, `scripts/publier-apt.sh` et `data/apt` retirés ; CCS se publie seulement dans le dépôt unique https://apt.mawena.cloud.

### Corrigé

- Onglet « Réseau » : la fiche du serveur s'appelait « Cet appareil » même vue depuis un
  téléphone ; elle s'appelle maintenant « Serveur CCS » (web, Android, iPhone).

## [1.6.0] — 2026-11-23

### Ajouté

- `ccs distant` passe par le réseau maillé quand la machine y est en ligne : SSH direct sur son
  adresse 100.64.x (réseau local quand c'est possible), le tunnel Ricochet restant le secours.
  Réglage `reseau` dans `machines.toml` ; `ccs distant machines` affiche le chemin.
- « Ajouter un PC » : la ligne à coller inscrit aussi le PC au réseau maillé.

## [1.5.1] — 2026-11-23

### Corrigé

- Onglet « Réseau » (web) : le rafraîchissement automatique ramenait l'ajout d'appareil sur
  « PC Linux » et effaçait la ligne d'inscription générée. La section n'est plus reconstruite.

## [1.5.0] — 2026-11-23

### Ajouté

- Onglet « Réseau » dans les applis Android et iPhone, à droite de Sessions, comme sur le web :
  carte du réseau maillé, fiche de chaque appareil (chemin, adresses publiées, trafic, ping réel,
  renommer, retirer), ajout d'un PC Linux ou d'un téléphone.

## [1.4.0] — 2026-11-23

### Ajouté

- Onglet « Réseau » de la version web, à droite de Sessions :
  - carte du réseau maillé, un trait par liaison coloré selon le chemin (réseau local, direct,
    relais du VPS) ;
  - fiche de chaque appareil : adresses publiées, trafic, ping réel (chemin et latence),
    renommer, retirer ;
  - ajout d'un appareil : ligne d'inscription pour un PC Linux (clé jetable), validation d'un
    téléphone connecté par l'appli Tailscale.
- Méthodes `network.status`, `network.ping`, `network.key`, `network.rename`, `network.remove`
  et `network.register` du pont, toujours traitées sur le serveur.

## [1.3.1] — 2026-11-23

### Modifié

- Mot de passe root gardé pour toujours : plus de bandeau « Root gardé » en haut des interfaces
  (web, bureau, TUI, Android, iPhone). Chaque commande root reste signalée avec « Révoquer » ;
  `ccs root etat` dit s'il est au coffre, `ccs root oublier` l'efface.

## [1.3.0] — 2026-11-23

### Ajouté

- `ccs reseau` : réseau maillé de tous les appareils (WireGuard, Headscale sur
  `network.mawena.cloud`) ; `etat` (chemin de chaque liaison : réseau local, direct par internet
  ou relais du VPS), `ping`, `cle` (clé d'inscription jetable), `serveur` (adresses publiées).

### Modifié

- Mot de passe root gardé pour toujours, chiffré sur le disque (AES-256-GCM, clé et chiffré
  séparés, liés à la machine et au compte), au lieu d'une heure en mémoire. Revérifié par `sudo`
  après un redémarrage ; « Révoquer » et `ccs root oublier` effacent le coffre. Nouvelle
  dépendance : `python3-cryptography`.

## [1.2.0] — 2026-11-22

### Ajouté

- Ajouter un PC au réseau de machines en une ligne : page Machines → « Ajouter un PC », ou
  `ccs distant ajouter <id> --utilisateur <compte>`. CCS déclare la machine dans Ricochet et
  donne `curl -fsSL https://<relais>/rejoindre/<code> | sudo sh` (lien à usage unique,
  15 min) : agent, serveur SSH, clé SSH de ce serveur, tunnel du port 22, terminal et
  fichiers, sans jeton à recopier. Demande Ricochet 0.6.0 et `jeton_operateur` dans
  `~/.config/ricochet/client.toml`.
- Pont : méthode `machines.add` ; `machines.settings` renvoie `operator_set`.

## [1.1.0] — 2026-11-22

### Ajouté

- Vocal sur toutes les interfaces (web, bureau, Android, iPhone) : bouton micro pour dicter
  un message dans la saisie, « Lire » sur chaque réponse de Claude, et réglage « Lire les
  réponses à voix haute » (lecture automatique à la fin du tour, désactivé par défaut).
- Bureau : dictée par Whisper en local (`faster-whisper`, facultatif), lecture par
  speech-dispatcher ; nouvelle clé de réglage `chat.read_aloud`.

## [1.0.2] — 2026-11-22

### Corrigé

- Web : « Nouveau chat » (projet, liste, onglet, feuille de route) ouvre la feuille des options
  (modèle, droits, compte) avec le dossier déjà rempli, au lieu d'ouvrir le chat directement.

## [1.0.1] — 2026-11-22

### Corrigé

- Web : le bandeau « Root gardé » ne fait plus défiler toute la page (sa hauteur est retirée
  de celle des sessions).

## [1.0.0] — 2026-11-22

Première version stable : les interfaces sont figées pour toute la 1.x (contrat dans
`docs/interfaces.md`). Les anciens noms restent acceptés jusqu'à la 2.0.

### Ajouté

- **Mot de passe root depuis les appareils** : `ccs root -- <commande>` lance `sudo` sans
  terminal. Si le mot de passe n'est pas connu, une fenêtre le demande sur tous les appareils
  connectés (web, bureau, TUI, Android, iPhone) et ntfy prévient sans rien révéler ; toucher
  l'avis ouvre la fenêtre de l'appli sur la bonne machine. Le premier qui répond l'emporte.
  Le mot de passe est vérifié par sudo puis gardé **en mémoire seulement** pendant une heure,
  jamais sur disque ni dans un journal. Chaque commande root est ensuite signalée, avec un
  bouton « Révoquer » ; `ccs root etat` et `ccs root oublier`. Les chats de CCS reçoivent
  `SUDO_ASKPASS` (`ccs-askpass`). Pont : `root.answer`, `root.status`, `root.forget`,
  événements `root.ask`, `root.resolved`, `root.used`, `root.forgotten`.

### Modifié

- **Commandes en français** : `liste`, `utiliser`, `suivant`, `ajouter`, `meilleur`, `appli`,
  `etat`, `silence`, `raccourcis`, `mise-a-jour`… et leurs options (`--jours`, `--projet`,
  `--nouvelle-session`…). Une seule table pour `ccs` et `claude-accounts` ; les anciens noms
  marchent encore mais sont cachés de l'aide. `meilleur` bascule par défaut (`--voir` pour
  seulement afficher). Les raccourcis clavier proposent les nouvelles commandes.
- **Pont et HTTP en anglais**, avec une version de protocole (`hello`, `/api/ws?protocol=1`) :
  `machines.attach`, `conversations.*`, `trash.*`, `saved.*`, `shell.*`, `rewind.*`,
  événements `machines.ready` et `shell.done`, états des travaux `waiting`… `stopped`,
  `/api/apptoken`, `/api/portier` (`enabled`, `login`). Un client sans version reçoit les
  anciens noms.
- **Fichiers et variables en anglais, migrés tout seuls** au premier usage : `servers.json`,
  `labels/`, `quiet-held.json`, `project-accounts.json`, `~/.config/ccs/machines.toml`,
  `color_scheme` `light|dark`, `web.json` (`portier.enabled`, `users`, `logout`),
  `CCS_CHAT_TOKEN`, `CCS_TOOL`. `XDG_CONFIG_HOME` et `XDG_CACHE_HOME` sont respectés.
  Sauvegardes au format 2 (le format 1 reste lisible).
- **Applis Android et iPhone** au protocole 1 : à mettre à jour avec le serveur.

### Corrigé

- **Chats du bureau visibles en direct partout** : ils tournent désormais dans le pont local,
  comme ceux du web. Les autres appareils ne les voient plus « arrêtés » ni en retard ; fermer
  un onglet ne coupe pas un chat suivi ailleurs, quitter l'appli ne coupe aucun chat. Le pont
  se relance seul après une mise à jour de CCS, dès que rien n'y tourne.

## [0.37.0] — 2026-11-21

### Ajouté

- **Ordre des sessions dans la version web** : menu de tri de « En cours » (ordre manuel,
  activité récente, nom, projet, état), glisser-déposer des lignes et des onglets, « Monter » /
  « Descendre » au menu (appui long au téléphone). L'ordre manuel est gardé dans le navigateur
  et la barre d'onglets suit le même ordre.
- **Tokens de chaque réponse** : sous chaque tour d'un chat, tokens lus et écrits dans le cache,
  produits, et coût (bureau, web, Android, iPhone, TUI). L'indicateur de contexte donne aussi
  les tokens et se colore (vert, orange à partir de la moitié du seuil, rouge au-delà).
- **Cache expiré** : quand le cache d'une conversation expire (5 min ou 1 h sans message) et
  que son contexte dépasse 20 000 tokens, une note le dit avec le coût de la relecture, et les
  boutons « Compacter » et « Nouvelle session » ; le prochain envoi demande confirmation.
- **Gros consommateurs** dans l'Analyse : conversations qui pèsent le plus, avec la cause
  probable (contexte long, cache souvent perdu, conversation très longue) et le conseil.
- Pont : `TurnResult.usage`, événement `CacheExpired`, `analysis.report` → `top`.

### Modifié

- Contexte lourd : seuil par défaut abaissé à **150 000 tokens**, et **compactage automatique
  activé par défaut** (un réglage déjà enregistré est gardé).

### Corrigé

- Bureau : un grand vide apparaissait sous les tableaux des réponses de Claude (la suite de la
  réponse semblait manquer) ; les cellules courtes ne passent plus à la ligne.

## [0.36.0] — 2026-11-21

### Ajouté

- **Relance après une limite, partout** : quand aucun autre compte n'est libre (ou pendant une
  pause), CCS calcule l'heure de levée de la limite (fin de la fenêtre de 5 h ou de la semaine, ou
  retour d'un autre compte sous les seuils), affiche « relance prévue à HH:MM », puis envoie
  « continue » à la levée, après avoir changé de compte si c'est un autre qui s'est libéré. Onglets
  du terminal et chats du bureau, chats du web, d'Android, de l'iPhone et de la TUI, `claude` lancé
  dans un terminal de la version web.
- Une seule bascule et une seule notification pour toutes les sessions bloquées en même temps ;
  un seul « continue » par session (au plus 3 par heure), aucun si tu as écrit entre-temps.
- Sessions hors de CCS : notification à la levée, ou relance en arrière-plan
  (`claude --resume … -p continue`) d'une conversation fermée.
- Réglage `limit_resume` (`enabled`, `outside`) dans les préférences du bureau, du web, d'Android
  et de l'iPhone. La notification de limite donne l'heure de relance prévue.
- TUI : notes du pont (relance, compactage) et messages envoyés par CCS affichés dans le fil.

### Modifié

- Les marqueurs de limite gardent le dossier de la conversation et l'heure de relance ; un marqueur
  dont la relance est prévue plus tard n'est plus effacé au bout de 24 h.

## [0.35.0] — 2026-11-20

### Ajouté

- **iPhone : machine pilotée**, comme sur Android : bouton dans Sessions et Plus, bandeau sur
  tous les écrans ; sessions, chats, fichiers, Git, terminal et notifications suivent la machine
  choisie (le PC du bureau par exemple, via le relais Ricochet).
- **iPhone : page « Machines et travaux distants »** (Plus) : machines, leurs outils et leurs
  places (limite réglable), travaux en cours, à venir et finis, journal en direct, arrêt, lancement
  d'une commande (maintenant, cette nuit ou à une heure), réglages du relais Ricochet.
- **iPhone : liens de fichiers dans le chat** : les chemins cités par Claude et les fichiers des
  diffs s'ouvrent d'un toucher.
- `.ipa` joint à la release (`CCS-0.35.0.ipa`) et ajouté à la source SideStore.

## [0.34.0] — 2026-11-19

### Ajouté

- **Onglets au clavier dans la version web** : Ctrl+Page préc. et Ctrl+Page suiv. passent à
  l'onglet précédent ou suivant (chats et terminaux, en boucle). Dans un onglet du navigateur,
  celui-ci garde souvent ces touches : elles marchent surtout dans CCS installé en application.
- `docs/interfaces.md` : inventaire des interfaces publiques (commandes, pont, routes HTTP,
  fichiers de configuration, variables d'environnement) et des points à revoir avant la 1.0.0.

## [0.33.0] — 2026-11-19

### Ajouté

- **Application iPhone native** (`ios-app/`, Swift + SwiftUI, iOS 17), même périmètre que
  l'appli Android : connexion (mot de passe + TOTP ou Portier, jeton dans le trousseau), comptes
  et accueil, sessions et projets, chat complet en direct, fichiers, Git, feuille de route,
  tâches de fond, réglages, terminal (SwiftTerm, barre de touches avec Ctrl et Alt collants),
  notifications locales (fin de tour, autorisation à donner depuis la notification, rappel
  d'attente) et partage vers un chat (« Ouvrir dans CCS », lien `ccs://partager`).
- `.ipa` non signé joint à la release (`CCS-0.33.0.ipa`), à installer avec SideStore (identifiant
  Apple gratuit) ; source SideStore `ios-app/sidestore.json` pour les mises à jour.
- Construction sans Mac sur Codemagic (`codemagic.yaml`, workflow `ios-natif`) : projet XcodeGen,
  tests XCTest sur simulateur, archive non signée.

## [0.32.0] — 2026-11-19

### Ajouté

- **Plusieurs travaux à la fois** : places par machine (`limite` dans `distant.toml`, 2 par
  défaut, réglable depuis la page), file d'attente quand toutes les machines sont pleines.
- **Travaux en arrière-plan et de nuit** : `ccs distant lancer --detache`, `--quand nuit|HH:MM` ;
  `ccs distant travaux`, `journal <id>`, `arreter <id>`. Claude est invité à envoyer les longues
  suites de tests la nuit, pour garder le VPS léger.
- Pont : `machines.jobs`, `machines.log`, `machines.start`, `machines.limit` ; `machines.list`
  donne aussi outils, limite et places prises.

### Modifié

- **Page « Machines » refaite** (web : Réglages → « Gérer les machines », ou la feuille « Machine
  pilotée » ; bureau : Réglages → Machines) : travaux en cours, en attente, programmés et finis
  avec « Journal » et « Arrêter », formulaire « Lancer une commande » (dossier, machine,
  maintenant / cette nuit / à une heure), places et limite par machine, réglages du relais.
- Le registre des commandes passe de `~/.cache/ccs/distant-en-cours/` à
  `~/.cache/ccs/distant/travaux/` (finis gardés 24 h, 30 au plus) ; `machines.running` et
  `machines.tools` du pont sont remplacés par `machines.jobs` et l'inventaire de `machines.list`.

## [0.31.0] — 2026-11-19

### Ajouté

- **Page « Machines » du calcul réparti.** Onglet Machines dans la version web, page Machines
  dans les Réglages du bureau : commandes `ccs distant lancer` en cours (machine, projet,
  durée) avec « Arrêter », confirmé, qui arrête aussi la commande distante ; machines du relais
  Ricochet (en ligne ou non, charge, mémoire, outils relevés, « Relever les outils ») ;
  réglages du client Ricochet (adresse du relais, jeton jamais réaffiché, `client.toml` en
  droits 600).
- `ccs distant lancer` note la commande en cours dans `~/.cache/ccs/distant-en-cours/` le temps
  qu'elle tourne.

## [0.30.0] — 2026-11-19

### Ajouté

- **Clic droit dans la version web.** Sur un onglet ou une ligne « En cours » : Renommer…,
  Nouveau chat ou Terminal dans ce projet, Ouvrir le projet, Copier le chemin, Fermer, Fermer
  les autres onglets (une seule confirmation). Sur un projet : Ouvrir, Nouveau chat, Terminal,
  Copier le chemin, Retirer de la liste. Sur une conversation : Reprendre, Aperçu, Renommer,
  Copier le chemin, Supprimer.

### Corrigé

- **Web : l'onglet ne suivait pas le renommage d'une conversation.** Le titre de l'onglet, de
  « En cours » et de l'en-tête du chat change aussitôt ; `chat.list` donne le titre du journal
  (`/rename` ou CCS, sinon le titre automatique de Claude Code), relu quand un chat redevient
  prêt : un nouveau chat prend son titre après la première réponse au lieu du nom du dossier.
- **Bureau : les boutons au survol d'une réponse** (Répondre, Étiqueter, Copier) étaient posés
  sur le texte et cachaient la fin de la première ligne ; ils ont maintenant leur colonne.

## [0.29.0] — 2026-11-19

### Ajouté

- **Piloter le PC depuis le web.** Bouton « Machine pilotée » dans la barre du haut : ce
  serveur ou une autre machine du relais Ricochet. Sur le PC, tout le web suit : sessions,
  chats (les mêmes qu'au bureau), fichiers, feuille de route, Git, terminal. Le pont du
  serveur relaie la connexion par `ssh` dans le tunnel Ricochet jusqu'au pont local du PC
  (`machines.list`, `machine.attach`, `/api/ws?machine=<id>`) ; machine injoignable : code
  4010 avec la raison, nouvel essai automatique.
- **Application Android 0.29.0 : même choix de machine** (puce dans Sessions, « Machine
  pilotée » dans Plus, bandeau sur tous les écrans) ; les notifications suivent la machine
  choisie. APK `ccs-0.29.0.apk` joint à la release.

## [0.28.0] — 2026-11-19

### Ajouté

- **Application Android native** (Kotlin + Jetpack Compose), à la place de la coquille web :
  accueil et comptes, sessions et projets, chat complet, fichiers, Git, feuille de route,
  tâches de nuit, changements et retour arrière, réglages, terminal ; notifications de fin de
  tour et d'attente (Autoriser / Refuser depuis la notification), partage Android vers un chat,
  raccourcis. Icône entière dans le lanceur. APK `ccs-0.28.0.apk` joint à la release.

## [0.27.0] — 2026-11-19

### Ajouté

- **Web : historique des sous-agents.** Un sous-agent fini quitte la barre au-dessus du fil ;
  le bouton « Terminés (n) » liste ceux qui ont fini (le plus récent en tête) et rouvre leur vue.
- **Serveur : `POST /api/app-token`**, jeton d'appareil durable pour l'application Android
  connectée par Portier (la session de Portier finit par expirer). Un jeton d'appareil ne peut
  pas en créer d'autre.
- **Serveur : liste et révocation des appareils avec le jeton d'appareil** (`/api/tokens`,
  `/api/revoke` acceptent `Authorization: Bearer`).

## [0.26.1] — 2026-11-19

### Corrigé

- **Application Android : la connexion par Portier reste dans l'application.** Les sites du même
  domaine que le serveur (`portier.mawena.cloud`) s'ouvrent dans la vue au lieu du navigateur,
  d'où la connexion ne revenait pas.

## [0.26.0] — 2026-11-19

### Ajouté

- **Effacement automatique en fin de sujet** (réglage `chat.auto_clear`, activé par défaut) :
  Claude lance `ccs chat effacer` quand un sujet est fini ; CCS envoie `/clear` dès la fin du
  tour (jamais pendant un sous-agent de fond). Le séparateur dit « Sujet terminé : Claude a
  effacé la conversation ». Case dans les réglages du web et du bureau.
- **`ccs chat effacer`** : la commande que Claude lance pour cela.
- **Web : « Recharger » quand le serveur change de version**, pour une page restée ouverte
  pendant une mise à jour.
- **Application Android** (`android-app/`, Flutter, paquet `com.mawena.ccs`) : coquille plein
  écran de la version web (adresse du serveur modifiable, envoi et téléchargement de fichiers,
  écran hors ligne). APK `ccs-0.26.0.apk` joint à la release GitHub.

### Corrigé

- **`/clear` (et toute commande `/…`) part seul** : après une commande `!` ou avec une
  citation, CCS les plaçait en tête du message, et Claude Code y voyait du texte ordinaire :
  rien n'était vidé. Citation et sorties `!` attendent maintenant le message suivant.

## [0.25.1] — 2026-11-19

### Corrigé

- **`ccs distant lancer` : interrompre arrête aussi la commande distante.** Avant, Ctrl+C ou
  l'arrêt de Claude coupait seulement `ssh`, et la commande continuait sur l'autre machine
  (sans terminal, elle ne reçoit aucun signal). Un garde y surveille maintenant la connexion :
  à sa fin, tout le groupe de processus reçoit TERM, puis KILL 5 s plus tard. Le lanceur
  distant passe aussi par `bash` quel que soit le shell de connexion de la machine.

## [0.25.0] — 2026-11-19

### Ajouté

- **Séparateur après `/clear`** (web et bureau) : une ligne « Nouvelle conversation — Claude ne
  voit plus les messages au-dessus » ; les anciens messages restent lisibles et citables, mais
  grisés. CCS lit l'événement `conversation_reset` de Claude Code ; le web le retrouve aussi
  après un rechargement de la page.

### Modifié

- **Chat web : les pastilles des sous-agents restent affichées**, avec ✓ quand ils ont fini,
  comme sur le bureau. Avant, la pastille disparaissait dès la fin du sous-agent, et la barre
  avec elle.

## [0.24.0] — 2026-11-17

### Modifié

- **Nouvelle présentation du gestionnaire de fichiers.**
  - **Web** : icône colorée par type de fichier (clair et sombre), arbre aéré avec lignes de
    rattachement et marques git en pastilles, fil d'Ariane défilant, barre d'outils à icônes
    (en tuiles au téléphone), en-tête du fichier ouvert avec actions à icônes, images sur
    damier, états vides soignés et « Télécharger » pour un fichier binaire ou trop gros.
  - **Bureau** : icônes symboliques par type, noms tronqués au milieu (l'extension reste
    visible), en-tête du dossier avec Tout replier, Actualiser, Copier le chemin et Ouvrir
    dans Fichiers, dossier vide en page d'état, en-tête du fichier avec Chercher et
    Enregistrer (actif seulement si le fichier est modifié).

## [0.23.2] — 2026-11-17

### Corrigé

- **Sessions affichées « Claude travaille » alors que Claude était au repos** (liste « En
  cours » du web, et le bureau). Les versions récentes de Claude Code envoient un signal
  `command_lifecycle` juste après la fin du tour ; CCS le prenait pour un retour au travail
  et ne repassait jamais au repos quand des messages envoyés pendant le tour y avaient été
  lus. Seuls les vrais signes de travail comptent désormais.
- **Sous-agents en arrière-plan restés « en cours » dans le chat web.** Claude Code annonce
  leur fin dans son flux (`system/task_notification`) ; CCS ne lisait que le message
  « <task-notification> », que la CLI ne renvoie pas toujours (pendant un tour, après un
  compactage). Les deux sont lus, sans doublon.

## [0.23.1] — 2026-11-17

### Corrigé

- **« Claude réfléchit… » restait affiché alors que plus rien ne tournait** (bureau, et
  même cause pour le web). Si l'on envoyait `/compact` puis un message pendant un tour,
  CCS croyait Claude au repos pendant le compactage : celui-ci dure plusieurs secondes sans
  autre signe que `status: compacting`, et le filet qui solde les messages lus en cours de
  tour le prenait pour la fin. Le tour de la question arrivait alors moteur « au repos »,
  et son `result` ne changeait plus l'état, si bien que rien n'éteignait l'indicateur ni le
  bouton ■. Le moteur suit maintenant le compactage, et repasse « occupé » dès que la CLI
  se remet au travail : l'indicateur s'éteint au dernier `result`. Pas de minuterie
  d'affichage. Tests : la séquence relevée sur la vraie CLI, rejouée dans le moteur et dans
  l'onglet de bureau.

## [0.23.0] — 2026-11-17

### Ajouté

- **Mode Portier pour la version web.** Derrière Portier (connexion unique et double facteur),
  la version web fait confiance à l'en-tête `X-Portier-Utilisateur` transmis par nginx : plus
  de page de connexion de CCS. Réglage dans `/etc/ccs/web.json`, clé `portier` (`actif`,
  `utilisateurs`, `url`, `deconnexion`), **désactivé par défaut**. L'en-tête n'est cru que
  depuis `127.0.0.1`/`::1` et pour un nom de la liste ; `ccs-auth` revérifie l'option et la
  liste avant d'ouvrir le pont. HTTP et WebSocket ; les jetons d'appareil restent prioritaires.
- « Déconnexion » renvoie vers Portier en mode Portier ; la page de connexion propose
  « Se connecter via Portier » (`<url>/connexion?retour=<adresse de CCS>`).

## [0.22.1] — 2026-11-17

### Corrigé

- `ccs distant machines` et `ccs distant lancer` répondaient « commande ou profil inconnu » :
  le lanceur `ccs` ne connaissait pas la commande (seule `claude-accounts distant` marchait).
  Elle figure maintenant dans l'aide et la page de manuel, et un test de bout en bout la couvre.

## [0.22.0] — 2026-11-17

### Ajouté

- **Sous-agents dans le chat web.** Comme sur le bureau, chaque sous-agent lancé par Claude a
  sa pastille au-dessus du fil et sa propre vue en lecture seule (ce qu'il lit, lance et
  répond). Sa carte dans le fil montre son état (au travail, en arrière-plan, terminé, arrêté),
  sa consigne et son résultat, avec un bouton « Voir » qui reste après la fin.

### Modifié

- Chat web : le travail d'un sous-agent n'apparaît plus dans le fil de la conversation (ses
  réponses s'y affichaient comme celles de Claude). On revient au fil quand on envoie un
  message ou qu'une autorisation arrive.

## [0.21.0] — 2026-11-17

### Ajouté

- **Calcul réparti : `ccs distant`.** CCS se sert des autres machines du réseau
  [Ricochet](https://github.com/mawena/Ricochet) (0.3.0 ou plus) pour les travaux lourds ou
  quand un outil manque ici (un build Flutter sur le PC de bureau, par exemple).
  - `ccs distant machines` : machines en ligne, charge, mémoire et outils trouvés (flutter,
    cargo, node, docker…), gardés une heure.
  - `ccs distant lancer [--machine m] -- <commande>` : choisit la machine qui a l'outil (la
    moins chargée d'abord), y copie le projet par `rsync` (seuls les fichiers changés
    repartent, sans ce que git ignore ni `.git`), lance la commande dans le même sous-dossier
    avec le `PATH` d'un terminal de la machine, affiche la sortie au fil de l'eau, renvoie le
    même code de retour. `--rapatrier <chemin>` rapporte les fichiers produits, `--inclure
    <chemin>` envoie un chemin que git ignore, `--avec-git` envoie aussi `.git`, `--outil`
    nomme l'outil nécessaire.
  - Les chats le savent : quand le calcul réparti est réglé sur la machine, Claude reçoit la
    consigne de passer par `ccs distant lancer` si un outil manque ou pour un travail lourd.
  - Réglages : `~/.config/ricochet/client.toml` (relais et jeton des tunnels) et, au besoin,
    `~/.config/ccs/distant.toml` (utilisateur et port SSH par machine). Le transport est un
    tunnel Ricochet vers le serveur SSH de la machine : c'est SSH qui décide qui entre.

## [0.20.1] — 2026-11-17

### Modifié

- **Passage au dépôt APT unique de mawena, <https://apt.mawena.cloud/>.** Le paquet `ccs` ne
  fournit plus sa source `/etc/apt/sources.list.d/ccs.sources` ni sa clé
  `/usr/share/keyrings/ccs.gpg` : il dépend de `mawena-depot`, qui installe la source et la clé
  du dépôt unique. Un simple `sudo apt update && sudo apt upgrade` fait passer une machine
  existante au nouveau dépôt ; l'ancienne source est retirée proprement (`rm_conffile`).
- Installation : `curl -fsSL https://apt.mawena.cloud/installer.sh | sudo sh -s -- ccs`
  (README, site, `installer.sh` du site qui lance désormais cet installateur). L'ancien dépôt
  `https://mawena.github.io/CCS/apt` reste en ligne jusqu'à mai 2027 et reçoit aussi
  `mawena-depot`.

## [0.20.0] — 2026-11-17

### Ajouté

- **Version web : onglet « Fichiers », un gestionnaire de fichiers**, à côté d'Accueil, Sessions,
  Analyse et Réglages. Il parcourt le dossier personnel et les dossiers web du serveur
  (`/var/www`, `/srv`) avec un fil d'Ariane, et permet d'y ouvrir, modifier, créer, envoyer,
  télécharger, renommer et supprimer, comme dans le volet Fichiers d'un projet.
- **Ajouter un dossier aux projets de CCS** depuis ce gestionnaire : bouton « Ajouter aux
  projets » pour le dossier ouvert, ou « Ajouter aux projets de CCS » dans le menu « ⋯ » d'un
  dossier ; le message de confirmation propose d'ouvrir le projet.
- **Copier, couper et coller** un fichier ou un dossier (menu « ⋯ », puis « Coller ici » sur le
  dossier de destination ou bouton « Coller » en haut), dans le gestionnaire comme dans le volet
  Fichiers d'un projet. Une copie dans le même dossier s'appelle « nom (copie) » ; une copie est
  limitée à 2 Go.

Le code de ces trois nouveautés était parti par erreur dans les paquets de la 0.19.3 (deux
sessions de travail dans le même dossier), sans réglage d'affichage, sans test web ni
documentation : la 0.20.0 les termine et les annonce.

## [0.19.3] — 2026-11-17

### Corrigé

- **Tests d'interface** adaptés au seuil de 300 000 tokens (la 0.19.2 ne passait pas la
  construction des paquets). Aucun changement pour l'utilisateur ; publiée à la place de la 0.19.2.

## [0.19.2] — 2026-11-16

### Modifié

- **Contexte lourd : seuil par défaut doublé, de 150 000 à 300 000 tokens.** L'alerte et le
  compactage automatique des chats se déclenchent deux fois moins souvent. Un seuil déjà réglé
  dans `settings.json` reste celui choisi.

## [0.19.1] — 2026-11-16

### Modifié

- **Web : bouton « ⤓ » sur chaque fichier de l'onglet Fichiers.** Le téléchargement se fait d'un
  seul appui, sans passer par le menu « ⋯ » (où il reste aussi).

### Corrigé

- Web : un message (toast) fermé à la main gardait son minuteur actif jusqu'au bout.

## [0.19.0] — 2026-11-16

### Ajouté

- **Web : gérer les fichiers du projet.** Dans le volet Fichiers, « + Fichier », « + Dossier » et
  « Envoyer » (depuis le téléphone ou le PC) à la racine ; le bouton « ⋯ » d'une entrée permet de
  renommer, supprimer, et, pour un dossier, d'y créer ou d'y envoyer un fichier.
- **Web : télécharger un fichier**, par le bouton « ⋯ » de l'arbre ou le bouton « ⤓ » du fichier
  ouvert. Transferts jusqu'à 200 Mo, par morceaux.
- Pont : nouveau module `bridge_files`. Une suppression demande confirmation et elle est
  définitive ; le dossier personnel, les racines permises et le projet ouvert sont protégés.

## [0.18.0] — 2026-11-16

### Ajouté

- **Chat web : bouton « Aller en bas »**. Quand tu es remonté lire dans le fil, un bouton rond
  apparaît en bas à droite ; un appui ramène au dernier message et le fil recommence à suivre
  la réponse. Il disparaît dès que tu es en bas.

## [0.17.1] — 2026-11-16

### Corrigé

- **Chat web : le fil ne descendait plus tout seul** pendant que la discussion continuait. Le
  suivi du bas se décrochait dès que la zone du fil changeait de taille (clavier du téléphone,
  liste des tâches, texte mis en forme après coup). Maintenant, seul un geste vers le haut
  l'arrête, et il reprend dès qu'on revient en bas ou qu'on envoie un message.

## [0.17.0] — 2026-11-16

### Ajouté

- **Étiquettes sur les messages** : pose un ou plusieurs mots-clés (« important », « à revoir »…)
  sur un message du chat, le tien ou celui de Claude, puis retrouve les messages par étiquette.
  Saisie séparée par des virgules, étiquettes déjà utilisées proposées, pastilles sous le
  message, volet « Étiquettes » qui ramène au message. Rangées par conversation sur la machine
  du chat et partagées entre appareils (poussée `chat.tags`).
  - **Bureau** : « Étiqueter… » au survol ou au clic droit ; volet par Ctrl+Maj+E ou « Messages
    étiquetés… » dans le menu de l'onglet ; chat local comme chat d'un serveur.
  - **Version web** : « Étiqueter » dans la rangée d'actions du message, volet « Étiquettes ».
- Chaque message envoyé porte maintenant un identifiant (uuid), repris dans le journal de
  Claude Code : le même message se retrouve en direct et à la relecture.

## [0.16.1] — 2026-11-16

### Corrigé

- **Bilan de santé lancé depuis la version web** : il annonçait à tort « le service tourne
  hors de systemd » alors que `ccs-daemon` était bien actif, et la commande proposée n'y
  changeait rien. Le pont du serveur n'avait pas accès au systemd de l'utilisateur ; le bilan
  le retrouve maintenant et, à défaut, vérifie que le processus est bien dans son unité.

## [0.16.0] — 2026-11-16

### Ajouté

- **Répondre en citant un message** : comme dans une messagerie, « Répondre » sur un message
  du chat (le tien ou celui de Claude) le cite au-dessus de la saisie ; Claude reçoit la
  citation avec ta réponse. Échap ou la croix annule.
  - **Bureau** : bouton « Répondre » au survol d'une réponse de Claude ou d'une de tes bulles,
    et entrée « Répondre » dans le menu du clic droit.
  - **Version web** : « Répondre » au survol à la souris ; au téléphone, toucher le message
    (ou y sélectionner du texte) ouvre la rangée « Répondre ».
  - **Citer un passage** : le texte sélectionné dans le message est seul cité (4 000
    caractères au plus) ; sans sélection, tout le message, raccourci au-delà de 1 200
    caractères.
  - **Dans le fil** : la bulle montre la citation à part, repliée (un clic la déplie), puis
    la réponse ; pareil sur les autres appareils et à la réouverture de la conversation.
  - Claude reçoit du Markdown ordinaire (citation en bloc, puis la réponse), lisible aussi
    dans le terminal de Claude Code.

### Modifié

- **Historique** : titre par défaut d'une conversation, « Dernière demande », fiche « où
  j'en étais » et « Revenir avant un message » montrent la réponse, sans la citation.

## [0.15.0] — 2026-11-16

### Ajouté

- **Compactage automatique des chats** : réglage « Compacter automatiquement », désactivé par
  défaut, sous l'alerte de contexte lourd (bureau et version web). Quand Claude a fini un tour
  et que le contexte dépasse le seuil du contexte lourd, CCS envoie `/compact` lui-même et
  l'écrit dans le fil (« Compactage automatique : contexte de N jetons »), à la place de
  l'alerte et de son bouton.
  - **Seulement entre deux tours** : jamais pendant que Claude travaille, ni quand une demande
    d'autorisation attend.
  - **Chats d'un serveur** (web, téléphone, chat distant du bureau) : le serveur compacte, avec
    son réglage, même sans appareil ouvert. **Chats locaux du bureau** : l'application compacte.
  - **Jamais deux fois de suite** : si le contexte reste au-dessus du seuil après le
    compactage, CCS le dit une fois et attend qu'il repasse dessous ; si le compactage
    n'aboutit pas (limite d'usage, arrêt), il réessaie après le prochain tour réussi.

### Modifié

- **Jauge du contexte** : elle se met à jour juste après `/compact` ou `/clear`, au bureau et
  dans la version web (avant, seulement à la fin du tour suivant).

### Corrigé

- **Bureau** : la note « Conversation compactée » ne s'affichait pas quand Claude Code ne
  donnait pas le nombre de jetons d'avant le compactage.

## [0.14.1] — 2026-11-16

### Corrigé

- **Bureau : un chat du serveur ne se mettait pas à jour en direct** quand on le suivait sans
  y écrire (conversation reprise pendant que le web ou le téléphone la fait tourner). L'onglet
  s'y branche maintenant dès l'ouverture, ou dès qu'un autre appareil l'ouvre, sans rejouer
  l'historique déjà affiché.

## [0.14.0] — 2026-11-16

### Ajouté

- **Bureau : page Sessions par machine.** Liste « Ce poste » puis chaque serveur appairé
  (remplace le bouton « Projets des serveurs »). Sur un serveur :
  - **En cours** : les chats qui tournent (téléphone, web, autre PC) ; « Rejoindre » rejoue le
    fil et le suit en direct, autorisations comprises (onglet déjà ouvert : affiché) ;
  - projets (Chat, Terminal, retirer), « + » pour en ajouter un, conversations récentes
    (Reprendre, Supprimer), corbeille du serveur ; état de connexion visible.
- **Bureau, sur ce poste aussi** : « Ajouter un projet » et « Corbeille » dans la barre,
  « Retirer de la liste… » (menu de « Nouvelle session »), « Supprimer… » (menu « ⋮ »),
  « Annuler » juste après une suppression. Mêmes contrôles que le pont.
- **Bureau : panneau de gauche des chats distants** (Fichiers, Feuille de route, Git), comme
  pour un chat local.

### Corrigé

- **Bureau : un chat distant restait figé après un redémarrage du serveur** (mise à jour) :
  il se rebranche maintenant seul sur sa conversation.
- **Bureau : une autorisation donnée depuis le web ou le téléphone** laissait la carte en
  attente dans le chat distant du bureau ; elle se fige maintenant (« depuis un autre appareil »).

## [0.13.0] — 2026-11-16

### Ajouté

- **Web : gérer projets et conversations.** Dans la liste des sessions :
  - « + Ajouter » à côté de Projets : dossier existant ou nouveau dossier (`git init` en option,
    `~` accepté) ;
  - « ✕ » sur un projet : retiré de la liste, sans rien effacer (il revient si une nouvelle
    conversation y démarre) ;
  - « Supprimer » dans le menu « ⋯ » d'une conversation : elle part à la corbeille de CCS
    (refusé si elle tourne encore), avec « Annuler » juste après ;
  - « 🗑 Corbeille » en bas de la liste : restaurer une conversation pendant 30 jours ; le
    service de fond efface ensuite les plus anciennes.
- Pont : `projects.add`, `projects.remove`, `conversation.trash`, `conversation.trash_list`,
  `conversation.restore`.

### Corrigé

- **Web sur téléphone : le bouton « Plus » d'un chat ne faisait rien.** Son menu s'ouvrait sous le
  bas de l'écran ; il s'affiche maintenant sous l'en-tête.

## [0.12.6] — 2026-11-15

### Corrigé

- **Web : installer CCS comme une application**, comme Outlook. Un bandeau le propose une fois
  connecté (« Plus tard » le cache 30 jours) et Réglages → Application le rappelle : bouton
  Installer sur Chrome (Android, ordinateur) ; sur iPhone, Safari comme Chrome, la marche à
  suivre (Partager ⬆ → « Sur l'écran d'accueil »). CCS s'ouvre ensuite en plein écran.

## [0.12.5] — 2026-11-15

### Corrigé

- **Web au téléphone, chat plus aéré** : une seule barre en haut (← retour, titre, Fichiers,
  Plus) au lieu de deux ; zone de saisie plus large (bouton d'envoi en icône ➤, boutons
  joindre et messages enregistrés plus petits, marge du bas de l'iPhone respectée) ; blocs de
  code plus serrés.

## [0.12.4] — 2026-11-15

### Corrigé

- **Web : bouton Copier des blocs de code** : placé dans une barre au-dessus du code, avec la
  langue à gauche et une icône ; il ne recouvre plus les longues commandes et affiche « Copié ».

## [0.12.3] — 2026-11-15

### Corrigé

- **Web : feuille de route dans l'ordre** : les phases suivent l'ordre du fichier, comme au
  bureau, et la phase en cours s'affiche à l'ouverture.
- **Web : sections redimensionnables et masquables** : la liste des sessions et le volet
  (Fichiers, Feuille de route, Git, Changements) s'élargissent en glissant leur bord droit
  (double-clic : taille par défaut, largeur gardée) ; le bouton ☰ masque ou réaffiche la liste.

## [0.12.2] — 2026-11-15

### Corrigé

- **Web : le fil suit les nouveaux messages** : il descend tout seul quand Claude répond, même
  pendant le rendu du texte, sauf si tu es remonté lire plus haut.
- **Web : « Claude travaille… »** affiché en bas à gauche, au-dessus de la zone de saisie,
  comme au bureau.
- **Web : bouton Copier** sur chaque bloc de code des réponses.

## [0.12.1] — 2026-11-15

### Corrigé

- **Changements de la session et retour en arrière** : fonctionnent avec Claude Code 2.1.3xx
  lancé par le pont. Les chemins relatifs des copies (`realParentDir`) sont résolus depuis le
  dossier du projet (plus depuis celui du pont), et la copie d'avant la première modification,
  présente sur disque mais jamais citée dans le journal, sert d'état « avant ».
- **Surveillance des sessions sans bus D-Bus** (serveur sans bureau) : le dossier des
  sessions est surveillé même quand le bus de session manque.
- **Messages entre appareils** : un message envoyé du téléphone, du web ou du bureau s'affiche
  sur tous les appareils qui suivent le chat ; un onglet rechargé garde aussi ses propres
  messages.
- **Web, questions à choix** : boutons radio à leur taille, libellés alignés à gauche.
- **Web, grand écran** : le fil et la zone de saisie forment une colonne centrée.
- **Web, téléphone** : les actions qui se suivent sont regroupées en une ligne repliable
  (« 7 actions · … ») ; cartes plus compactes. La recherche ouvre le groupe trouvé.

## [0.12.0] — 2026-11-15

### Ajouté

- **Page Git** (bureau), inspirée de GiGit : indexation par fichier, bloc et ligne, annulation,
  `.gitignore`, commit et amend avec message proposé, fetch (automatique, `git.fetch_minutes`),
  pull et push (le push forcé demande confirmation et refuse d'écraser un commit distant non
  vu), git flow, graphe des commits par pages, détail d'un commit, avatars des auteurs en cache.
  Trois dispositions (`git.layout` : A, B ou C). Réglages `git.layout`, `git.fetch_minutes`
  et `git.avatars`.
- **Faire une tâche** depuis la feuille de route : dans le chat ou dans la file de nuit ; le
  bandeau « Tâche finie ? » propose de cocher la case que Claude n'a pas cochée.
- **Changements de la session** : volet des fichiers modifiés par Claude (d'après les copies de
  Claude Code), annulation d'un fichier, retour à avant un message. `ccs doctor` contrôle le
  format de ces copies (ligne « Historique des fichiers »).
- **Chat** : recherche dans le fil (Ctrl+F), messages enregistrés (communs ou par projet),
  bouton « Compacter » dans l'alerte de contexte lourd, commande `!` lancée dans le dossier du
  projet.
- **Téléphone** : boutons Autoriser et Refuser dans la notification ntfy (réponses signées, à
  usage unique, valables 10 minutes) ; réglage « Montrer la commande » (`phone.show_content`,
  désactivé par défaut) ; canal de réponses `phone.reply_topic`.
- **Version web au niveau du bureau**, pensée pour le téléphone : messages brefs et cartes de
  confirmation, chat en plein écran, bouton Retour du téléphone, pastille « attend ta
  réponse » ; Sessions (« En cours », écran Projet, nouvelle session complète, conversations
  avec aperçu, renommage, coût) ; chat (options repliées, brouillon, diff des modifications,
  liens de fichiers, complétion `@` et `/`, messages enregistrés, Compacter, `!`, recherche,
  changements de la session) ; barre de touches du terminal ; fichiers (images, recherche,
  ouverture à une ligne) ; Accueil (rythme et prévision, bilan de santé, tâches de nuit) ;
  Réglages (tous les réglages, téléphone avec QR code et essai, thème) ; Analyse de 24 heures
  à 90 jours ; Git (état, diff, indexation par fichier et par bloc, commit, fetch, pull, push).
- Pont : modules `bridge_work`, `bridge_admin` et `bridge_git` (méthodes `work.*`,
  `doctor.run`, `tasks.log`, `phone.*`, `git.*`…) et méthodes de plus dans `bridge_data` et
  `bridge_term`.

### Corrigé

- **Web** : un onglet restauré n'affiche plus de messages en double (le journal s'arrête là où
  commence le tampon du pont) ; rouvrir une conversation déjà ouverte montre aussi ses anciens
  messages. Onglets recalés sur le pont après une reconnexion (arrêt, reprise, options réelles),
  appels sans doublon, Maj+Tab sans « Tout autoriser ».
- **Pont** : identifiants de chat et de terminal uniques d'un démarrage à l'autre ; une réponse
  trop grosse échoue seule, la connexion reste ; diffs et états Git plafonnés, `git.diff` reste
  dans le dépôt, l'indexation d'un bloc garde les octets exacts ; annuler un fichier ou revenir
  en arrière est refusé si le fichier a changé depuis l'affichage ou pendant que Claude
  travaille ; chat et terminal limités aux dossiers permis ; renommage limité aux journaux de
  Claude Code ; la commande `!` ne reste plus bloquée par un processus en arrière-plan.
- **Mise en page web** : les cartes de l'Accueil ne débordent plus, au téléphone comme sur grand
  écran ; la page Sessions sans chat ouvert n'affiche plus de bouton géant ; les titres courts
  des projets et conversations sont alignés à gauche.
- **Doctor** : l'indicateur renommé `ccs-tray` est reconnu (plus de fausse alerte « Indicateur
  non lancé »).
- **Git** : fetch, pull et push du serveur ne demandent jamais de mot de passe ; le bureau garde
  sa fenêtre de mot de passe pour pull et push.
- **Bureau** : un retour en arrière vers un message sans copie des fichiers est expliqué ; les
  messages enregistrés communs masqués par un projet sont gardés.
- **Chat** : les copies de fichiers de Claude Code sont activées (volet « Changements de la
  session » et retour en arrière).

## [0.11.0] — 2026-11-15

### Ajouté

- **CCS sur un serveur (VPS).** Nouveau paquet `ccs-serveur` : trois services (`ccs-auth`,
  `ccs-web`, `ccs-bridge@`) et une version web responsive pour le téléphone
  (`https://ccs.mawena.cloud`), avec chat, sessions, fichiers, feuille de route, analyse,
  terminaux et réglages. Connexion par les comptes Ubuntu du groupe `ccs` et double
  authentification (TOTP, QR code), appareil retenu 30 jours ; `sudo ccs totp reinitialiser`.
  « Nouvelle session » ouvre un chat ou un terminal dans n'importe quel dossier (`~/…`
  accepté), même sans conversation.
- `ccs tui` : CCS en plein écran dans le terminal, sur la machine ou sur un serveur
  (`--serveur`) ; `ccs serveur ajouter|liste|retirer` pour appairer un poste.
- Bureau connecté : Réglages → Serveurs CCS, projets et chats du serveur dans la page
  Sessions, terminal distant, reconnexion automatique.
- Quatre paquets : `ccs`, `ccs-bureau`, `ccs-serveur` et le métapaquet `ccs-all`. Claude Code
  est installé pour l'utilisateur qui installe, s'il manque. `ccs doctor` vérifie le serveur ;
  sans `ccs-bureau`, il ne vérifie plus l'interface graphique (dans une session graphique, il
  propose d'installer `ccs-bureau`).
- La mise à jour en un clic installe ensemble tous les paquets CCS présents (`ccs`,
  `ccs-bureau`, `ccs-serveur`, `ccs-all`) et n'en retire jamais aucun.

### Mise à jour depuis 0.10

- L'application graphique passe dans le paquet `ccs-bureau`. Sur un poste de bureau, mettre à
  jour par apt plutôt que par le bouton : `sudo apt update && sudo apt install ccs-all`.

### Sécurité

- Aucune partie exposée ne tourne en root : `ccs-web` est sans droits, `ccs-auth` ne fait que
  PAM, TOTP et sessions. Un ticket HMAC, dont la clé est gardée par root, est exigé par
  chaque pont : compromettre `ccs-web` seul ne suffit pas à piloter un compte.
- Cookies `HttpOnly`, `Secure`, `SameSite=Strict`, CSP stricte, `Origin` vérifié, fichiers
  limités au dossier personnel, `/var/www` et `/srv`, sessions de 12 h (7 jours au plus),
  5 essais par 15 minutes.

### Limites connues

- Dans le bureau, un chat distant n'a pas le panneau Fichiers / Feuille de route ; retirer un
  serveur du bureau ne révoque pas son jeton (à faire dans la version web).

## [0.10.2] — 2026-11-14

### Modifié

- **Longues sessions à mémoire bornée.** À la fin d'un tour, au-delà de 300 éléments dans le
  fil, les plus anciens sont retirés (il en reste 200) et la mémoire est rendue au système ;
  une ligne en tête du fil propose « Afficher », qui relit la conversation depuis son journal.
  Mesuré : 1000 réponses font plafonner la fenêtre vers 312 Mo au lieu de grimper sans fin.
- Liste Markdown courte rendue en un seul label : 4 fois moins de mémoire, 35 fois plus rapide
  à construire ; les éléments longs gardent leur retrait.

### Corrigé

- Les messages retirés du fil n'étaient jamais libérés : des gestionnaires de signal pointaient
  vers leur propre widget (cycle Python ↔ GTK). Ils sont maintenant libérés.
- Un fichier ouvert juste après un très gros fichier pouvait rester « en chargement » : la
  mise en page du gros texte passait avant la fin de sa lecture.

## [0.10.1] — 2026-11-14

### Modifié

- **Processus nommés CCS.** Dans top, ps, le Moniteur système et le journal, les processus
  s'appellent `ccs-gui`, `ccs-daemon` et `ccs-tray` (et `ccs` pour les autres commandes) au
  lieu de `claude-accounts` ou `python3` : nom posé dès le démarrage par `prctl`, ligne de
  commande par `python3-setproctitle` s'il est installé (recommandé), identifiant de journal
  `ccs-daemon` pour le service. La commande `claude-accounts` reste valable.

- **Accueil plus lisible.** Les comptes sont côte à côte (jusqu'à trois par ligne,
  un par ligne en fenêtre étroite) : on les compare d'un coup d'œil. Chaque carte
  garde ses deux jauges principales (session, semaine) et une seule ligne d'état
  (erreur, limite proche, limite de la semaine ou « tient ») ; les autres limites,
  le rythme, la courbe 24 h et l'heure du relevé passent dans « Détails », qui reste
  ouvert d'une actualisation à l'autre. Le texte des cartes garde la couleur normale :
  la couleur du compte reste sur le liseré, le nom et les jauges (aussi dans
  l'onglet Sessions et l'historique).
- Bandeau du haut en une ligne : sessions disponibles, meilleur compte avec
  « Utiliser <compte> », bouton « Pause » (l'explication passe en info-bulle).
- **Sous-agents terminés** : comme dans VS Code, un sous-agent qui a fini quitte la barre
  des pastilles (elle disparaît quand il ne reste que la conversation principale) ; sa
  carte dans le fil garde « Voir le sous-agent ». Un sous-agent d'arrière-plan est tenu
  pour fini à son avis de fin (lu dans le flux, sinon dans le journal de la conversation),
  et la mise en veille du chat redevient alors possible.
- **Chat plus proche de l'extension VS Code** : liste de tâches épinglée au-dessus de la
  saisie (en-tête « Tâches 1/3 · tâche en cours », dépliable, effacée au message suivant
  une fois finie) ; réponses de Claude en texte plein, sans bulle ; Maj+Tab passe aux
  droits suivants (Demander → Modifications acceptées → Plan) ; une autorisation se
  répond au clavier, saisie vide (1 Autoriser, 2 Toujours, 3 Refuser).
- Planning resserré : frise des fenêtres de 5 h et prochaines recharges dans une
  même carte, explications en info-bulles, « Meilleur moment » repliable avec sa
  conclusion dans l'en-tête, file de tâches vide en une ligne.

- **Interface plus légère et plus fluide.** Pendant que Claude écrit, seule la fin de la
  réponse est réaffichée (avant : toute la réponse en Markdown, toutes les 90 ms, ce qui
  figeait la fenêtre sur les longues réponses : environ 15 fois moins de travail mesuré), et
  les rendus s'espacent d'eux-mêmes quand ils coûtent. Le détail d'une action (commande,
  résultat) n'est construit qu'au dépliage : une carte prend 8 fois moins de mémoire.
  L'Accueil n'est plus reconstruit chaque minute quand il n'est pas affiché.

### Corrigé

- **Questions de Claude enfin affichées.** Quand Claude posait des questions à choix
  (outil AskUserQuestion), CCS ne les montrait pas et Claude recevait « The user did not
  answer the questions ». Le chat affiche maintenant une carte : chaque question avec ses
  choix (un seul ou plusieurs), « Autre… » pour répondre en texte libre, les touches 1, 2,
  3… et « Envoyer les réponses » ; « Répondre dans le chat » laisse Claude reposer la
  question par écrit.
- **Plus de « ? » quand Claude ne demande rien.** Une simple fin de réponse s'affichait
  comme une question (onglet, liste des sessions) : elle porte maintenant une coche « a fini
  de répondre » ; le point d'interrogation est réservé aux vraies demandes.
- **Sous-agents de fond qui restaient « en cours ».** Leur avis de fin, rangé dans le
  journal sous une autre forme quand Claude travaillait, n'était pas lu, et une balise
  citée ailleurs pouvait tromper la recherche : le journal est maintenant lu entrée par
  entrée.
- **Dossier d'une conversation reliée à son projet** (« Dossier du projet… ») : l'aperçu,
  l'archive, les projets récents de « Nouvelle session » et le journal des bascules
  donnaient encore l'ancien dossier (Bureau, dossier personnel), noté dans les lignes du
  journal copié ; ils donnent maintenant le projet. Le dossier d'un journal est aussi
  trouvé quand celui-ci commence par de longs instantanés.
- Une fenêtre ouverte par « Relancer » n'écrivait plus ses erreurs nulle part : elles vont
  de nouveau dans le journal du bureau.

## [0.10.0] — 2026-11-12

### Ajouté

- **Chat graphique.** Une session Claude de CCS est maintenant un chat, plus un
  terminal : tes messages en bulles, les réponses de Claude en Markdown mis en
  forme (titres, listes, tableaux, code coloré), qui arrivent au fil de l'eau.
  Chaque action de Claude (fichier lu ou modifié avec son `+12 −3`, commande,
  recherche, sous-agent) est une carte repliable, et sa liste de tâches
  s'affiche en cases à cocher. Le fil suit ce qui arrive tant que tu es en bas ; si tu
  lis plus haut, il ne bouge pas et un bouton « ↓ Nouveaux messages » te ramène en bas.
- **Fil de la réponse allégé** : les actions de Claude qui s'enchaînent sans texte
  entre elles forment un seul bloc discret (action en cours et compte pendant le
  travail, puis « 5 actions · 3 lectures, 1 modification (+12 −3), 1 commande »,
  replié tout seul ; un clic montre les cartes). Une erreur reste signalée dans
  l'en-tête. Autorisations, tâches, sous-agents et texte de Claude ne sont jamais
  regroupés.
- **Sous-agents visibles**, comme dans VS Code : quand Claude lance des sous-agents, une
  pastille par sous-agent apparaît en haut du chat (roue tant qu'il travaille, coche à la
  fin) ; un clic montre sa conversation (actions, résultats, texte), « Conversation
  principale » ramène au fil. La carte Sous-agent du fil a un bouton « Voir le sous-agent ».
- **Barre cliquable du chat** : modèle, effort (faible à max, les niveaux que le
  modèle n'accepte pas sont grisés), ultracode et droits (Demander,
  Modifications acceptées, Plan, Tout autoriser), avec le contexte utilisé et le
  compte à droite. Les choix sont gardés par onglet. La barre montre le mode de
  droits confirmé par Claude Code ; « Tout autoriser » marche en cours de session
  (Claude est lancé avec `--allow-dangerously-skip-permissions`, qui ne fait que le
  permettre), et un changement refusé en direct est appliqué en relançant la
  conversation au message suivant.
- **Autorisations dans le chat** : une demande de Claude devient une carte avec
  Autoriser, Toujours pour cette commande (la commande exacte est écrite dans le
  `.claude/settings.local.json` du projet, sans changer les droits de la session)
  et Refuser (motif facultatif). L'alerte « attend ta réponse » se déclenche.
  Une demande venue d'un sous-agent le dit. Une question de Claude Code que CCS ne
  connaît pas reçoit « non pris en charge » (avec un message dans le fil) au lieu de
  laisser Claude bloqué ; un chat qui a lancé des sous-agents en arrière-plan ne se
  met jamais en veille (la veille les couperait).
- **Fil de la réponse** : la ligne d'activité dit ce que fait Claude et depuis combien de
  temps (« Lecture de README.md… · 12 s ») ; chaque réponse finit par un bilan discret
  (« ✓ Terminé en 42 s · 0,12 $ éq. », coût de ce tour seulement) ; un bouton « Copier »
  apparaît au survol d'une réponse ; un long message collé est replié à 14 lignes
  (« Afficher tout »).
- **Fichiers joints** : bouton trombone à côté d'Envoyer (ou glisser-déposer depuis le
  gestionnaire de fichiers) ; une image devient une vignette, tout autre fichier une
  étiquette avec ✕, envoyée en référence `@chemin` que Claude lit.
- **Saisie du chat** : `@` propose les fichiers du projet, `/` les commandes de
  Claude Code, une image collée ou glissée s'ajoute au message, un fichier glissé
  depuis l'arbre insère `@chemin`. Le bouton Arrêter (ou Échap) interrompt Claude.
  Un message écrit pendant que Claude travaille part tout de suite (images comprises),
  marqué « envoyé pendant que Claude travaille » ; le chat ne reste jamais bloqué sur
  « Claude travaille », que la CLI le lise en cours de route ou juste après.
- **Mise en veille** : un chat resté 30 minutes au repos arrête son processus
  `claude` pour ménager la mémoire, puis le relance sur la même conversation au
  message suivant (réglage `chat.idle_suspend_min`, 0 = jamais). Un chat rouvert
  montre son historique sans lancer `claude`.
- **Ouvrir cette conversation dans un terminal** (menu de l'onglet) : sortie de
  secours pour les commandes interactives de Claude Code, avec « Revenir au chat ».
- **Panneau Fichiers** dans chaque onglet de session : arbre du projet avec les
  marques git (`M`, `A`, `?`, `D`), fichiers ouverts à côté du chat (coloration,
  numéros de ligne, recherche Ctrl+F, images), aperçu Markdown, édition et
  Ctrl+S, diff des modifications de Claude. Un fichier modifié par Claude se
  recharge ; si tu avais des changements non enregistrés, un bandeau te laisse
  choisir. Deux dispositions (B par défaut : arbre | chat | fichier ; A : arbre |
  fichier | chat), séparations réglables, Ctrl+B pour replier l'arbre.
- **Feuille de route** dans l'onglet de session : le `ROADMAP.md` du projet avec
  phases, barres de progression et cases cliquables (un clic coche la case dans
  le fichier, sans le réécrire). Sans `ROADMAP.md`, le bouton « Demander à Claude
  d'en créer une » écrit au chat.
- **La feuille de route suit le projet de la conversation** : une conversation lancée
  depuis ton dossier personnel ou le Bureau affiche la feuille de route du projet dès que
  Claude lit ou modifie son `ROADMAP.md` ; « Choisir une feuille de route… » en ouvre une
  autre ; « Demander à Claude d'en créer une » n'est proposé que dans un vrai projet
  (dépôt git). « Dossier du projet… » (menu de l'onglet) fait partir l'arbre et la
  feuille de route d'un autre dossier, et relie aussi une conversation arrêtée à ce
  dossier. Ces choix sont gardés à la réouverture.
- **Couleur par compte**, choisie automatiquement et modifiable (Réglages →
  Apparence), reprise sur les cartes, les jauges, les courbes et la barre du chat ;
  thème Automatique, Clair ou Sombre.
- **Bilan de santé** : la ligne « Chat graphique » vérifie `gir1.2-gtksource-5` et
  `python3-markdown-it`.

- **« CCS a été mis à jour »** : quand un nouveau paquet est installé alors que
  l'application est ouverte, un bandeau propose « Relancer » (nouvelle instance après
  la fermeture, avec la confirmation habituelle si des sessions tournent).

### Modifié

- **Navigation en trois onglets** : Accueil, Sessions (« Toutes les sessions », puis
  un onglet par chat et par shell), Analyse (analyse et historique). Les Réglages
  sont dans le menu ☰, en fenêtre à part (Ctrl+virgule). Ctrl+1 à Ctrl+3 changent
  d'onglet. Les anciens noms de `claude-accounts gui --page` (`comptes`, `planning`,
  `terminaux`, `historique`…) mènent au bon onglet, et `accueil` s'ajoute.
- **Accueil redessiné** : une seule colonne de même largeur, des titres de section
  (Comptes, Derniers événements, Planning), les derniers événements avant le
  planning. L'erreur d'un compte se lit en clair (« Connexion refusée par
  Anthropic : reconnecte ce compte ») au lieu de la réponse brute de l'API, gardée
  dans l'info-bulle.
- « Nouvelle session… », « Reprendre » et les sessions rouvertes au démarrage
  ouvrent un chat au lieu d'un terminal Claude. Les onglets enregistrés par la 0.9
  se rouvrent en chat, avec leur historique ; un onglet shell reste un shell.
- Le fichier `terminals.json` passe en version 2 (options du chat de chaque
  onglet, largeurs des volets) ; un fichier de la version 1 se lit sans perte.
- Nouveaux réglages, dans la fenêtre des Réglages : groupe « Chat et fichiers »
  (mise en veille d'un chat inactif, droits par défaut des nouveaux chats,
  fichiers ignorés par git, disposition A ou B), apparence (thème, couleur par
  compte). Clés de `settings.json` : `chat`, `files`, `appearance`.
- Dépendances : le paquet requiert maintenant `gir1.2-gtksource-5` (éditeur et
  coloration) et `python3-markdown-it` (rendu du Markdown).
- Documentation : README, guide d'utilisation, architecture (avec le protocole
  stream-json), pages man et site à jour ; le scénario de bout en bout vérifie
  les noms acceptés par `gui --page`.

## [0.9.0] — 2026-11-12

### Modifié

- L'application s'appelle désormais « CCS » partout (fenêtre, menu des
  applications, indicateur, notifications, raccourci « Ouvrir CCS ») au lieu de
  « Comptes Claude » ; les commandes (`ccs`, `claude-accounts`) et l'identifiant
  `io.ccs.ClaudeAccounts` ne changent pas. Un raccourci clavier installé sous
  l'ancien nom reste reconnu (par son chemin) et est renommé à la prochaine
  mise à jour des raccourcis.
- Tests : les tests graphiques ne tournent plus jamais sur le bureau réel. Ils
  demandent `CCS_GUI_TESTS=1` et un affichage joignable (`tests/helpers.gui_ready`),
  et `make unit` (donc `make deb`) les lance sous Xvfb quand `xvfb-run` est là ;
  sinon l'affichage est retiré et ils sont sautés.

## [0.8.1] — 2026-11-11

### Corrigé

- Archive des conversations : le premier passage du service échouait
  (`TypeError` : le service donnait l'heure en date au lieu de secondes), et
  rien n'était archivé. Un test fait maintenant passer le vrai module d'archive
  par le service.

## [0.8.0] — 2026-11-11

### Ajouté

- **File de tâches** (`ccs tache`, onglet Planning) : des messages que Claude
  exécute sans fenêtre, « dès qu'il y a du quota », « cette nuit » (meilleur
  créneau de la plage de nuit, 23:00 à 07:00 par défaut) ou à `HH:MM`. Droits
  `lecture`, `modifications` (défaut) ou `tout` (`bypassPermissions`, avec
  l'avertissement). Une tâche à la fois, par la file de Gagarine en priorité
  « fond » quand elle existe ; bascule avant le lancement (jamais en pause) ;
  après une limite, bascule puis reprise par `--resume` (3 tentatives) ;
  notification à la fin, durée et coût équivalent ; reprise dans un onglet.
  Fichiers `tasks.json` et `tasks/<id>.jsonl`.
- **Notifications sur le téléphone** par ntfy (`ccs telephone`, Réglages),
  désactivées par défaut : canal secret tiré au hasard, lien d'abonnement et QR
  code, bouton « Essayer » (`ccs telephone essai`). Événements : session qui
  attend, tâche finie ou échouée, bascule, comptes épuisés. Seuls le nom du
  projet et l'état sont envoyés ; « Ne pas déranger » s'applique aussi.
- **Archive des conversations** : copies gzip des conversations inchangées depuis
  1 jour dans `~/.local/share/ccs/archive`, avant que Claude Code ne les efface
  (30 jours). Elles restent dans l'onglet Sessions (« archivée ») avec recherche,
  aperçu, export et reprise. Réglages : interrupteur, délai, âge maximal ; taille
  dans `ccs doctor`.
- **Fiche « où j'en étais »** (`ccs fiche <id>`, encart de l'aperçu) : dernière
  demande, début de la dernière réponse, fichiers modifiés, liste de tâches,
  branche, compte. Lue dans le journal, sans appeler Claude.
- **Sauvegarde chiffrée** (`ccs sauvegarde`, `ccs restaurer`, Réglages) : profils
  (jetons chiffrés), réglages, comptes par projet, budgets et raccourcis, chiffrés
  par gpg (AES-256, phrase de passe saisie dans pinentry) ; restauration avec
  confirmation.
- **Mémoire des sessions** (`ccs sessions`, onglet Sessions) : RAM de chaque
  session et totale, sessions inactives depuis plus de 2 h (réglable), bandeau et
  bouton « Fermer » avec confirmation. Rien n'est jamais fermé automatiquement.
- **Alerte de contexte lourd** : une notification par session au-delà de
  150 000 tokens (réglable), avec le coût d'un message ; badge dans l'onglet
  Sessions et la ligne d'état.
- **Budget par projet** (`ccs budget`, onglet Analyse) : budget hebdomadaire en
  équivalent dollars, alertes à 80 % et 100 %, ne bloque jamais rien.
- `claude-accounts gui --task <id>` : ouvre l'onglet Planning sur une tâche ;
  c'est ce qu'utilise le clic sur la notification de fin de tâche quand
  l'application est fermée.
- Réglages `tasks`, `phone`, `archive`, `sessions`, `context_alert` et `budget`.
- Paquet : dépend de `gnupg` ; recommande `python3-qrcode` (QR code du téléphone),
  `gpg-agent` et `pinentry-gnome3` (phrase de passe de la sauvegarde).

### Modifié

- `ccs sessions` affiche aussi la RAM par session, le total, les sessions
  inactives et le contexte lourd.
- Guide d'utilisation, architecture et pages man : les huit fonctions.

## [0.7.1] — 2026-11-10

### Modifié

- README : l'installation par le dépôt APT est mise en avant dès l'en-tête,
  avec le lien du site <https://mawena.github.io/CCS/> ; section Installation
  réorganisée (dépôt APT recommandé, trois façons de faire la première
  installation, étapes après la première installation, mises à jour par apt,
  en un clic ou à la main) ; désinstallation par `apt purge` pour retirer aussi
  la source APT.
- Guide d'utilisation : lien du site et installation par apt en tête.

## [0.7.0] — 2026-11-10

### Ajouté

- **Dépôt APT signé** (<https://mawena.github.io/CCS/apt>) : le paquet ajoute sa
  source et sa clé, `apt upgrade` installe les nouvelles versions ; page
  d'accueil et installateur sur <https://mawena.github.io/CCS/>.
- **Mise à jour en un clic** : le bandeau « CCS x.y.z est disponible » a un
  bouton **Installer** (paquet installé par `dpkg`). Un dialogue montre les
  notes de la release, la progression (téléchargement, vérification,
  installation), **Voir sur GitHub**, puis **Redémarrer l'application**. Le
  paquet `ccs_<version>_all.deb` et `SHA256SUMS` ne sont téléchargés que
  depuis `github.com/mawena/CCS/releases/download/v<version>/…` (ou l'API des
  pièces jointes du dépôt ; redirections acceptées seulement vers
  `objects.githubusercontent.com` et `release-assets.githubusercontent.com`,
  en https), avec des limites de taille, dans un dossier temporaire 0700. La
  somme SHA-256 est vérifiée, puis `dpkg-deb -f` contrôle le paquet (`ccs`,
  version annoncée et plus récente) avant `pkexec apt-get install -y` (fenêtre
  de mot de passe). Sans `pkexec`, ou s'il est refusé, la commande
  `sudo apt install '<chemin>'` est proposée à copier. Une copie de
  développement est « mise à jour par git ». En ligne de commande :
  `ccs mise-a-jour [--verifier]` (alias `ccs maj`).
- **Ne pas déranger** : plage de silence (`alerts.quiet`, 22:00 à 08:00 par
  défaut, jours au choix, passage de minuit) et silence temporaire (1 h, 4 h,
  jusqu'à demain, reprendre). Les notifications retenues sont comptées et un
  seul résumé « Fin du silence » les récapitule. Ne sont jamais retenues :
  « attend ta réponse » (et son rappel, si `allow_waiting`), les sessions
  bloquées par une limite, le résumé et les retours des raccourcis. Groupe
  **Réglages → Ne pas déranger**, entrée « Ne pas déranger » du menu de
  l'icône (🔕 pendant un silence), raccourci clavier « Ne pas déranger 1 h »
  (Super+Alt+D, désactivé par défaut),
  `ccs silence [1h|4h|demain|off|reprendre|status]` (alias `ccs quiet`) ;
  `ccs status` affiche le silence.
- **Meilleur moment pour une grosse tâche** : carte de l'onglet Planning (durée
  1, 2, 3, 4, 6 ou 8 h, frise des 24 h) et `ccs moment [--duree 3h] [--sur 24h]`.
  Compte les fenêtres de 5 h disponibles pour chaque heure de départ (maintenant,
  puis tous les quarts d'heure), plafond hebdomadaire compris (estimation :
  une semaine pleine vaut environ 10 fenêtres), et propose jusqu'à 3
  alternatives espacées de 90 min.
- **Sessions dans le menu de l'icône** : sous-menu « Sessions (n) » (ou
  « Sessions (1 attend ta réponse) »), une entrée par session, celles qui
  attendent d'abord ; un clic ouvre la session dans l'application. « Toutes les
  sessions… » et « Terminal ou dossier d'une session ». L'indicateur affiche
  « · 💬 n » quand n sessions attendent.
- **Rapport mensuel** : carte de l'onglet Analyse (mois en cours et 11
  précédents), notification le 1er du mois (le 2 si le PC dormait) et
  `ccs mois [--precedent N]` : comptes, activité, tokens, équivalent API
  comparé aux formules payées, modèles, 10 premiers projets, évolution par
  rapport au mois précédent et tendance sur 3 à 6 mois. Réglages
  **Rapport mensuel** (`alerts.monthly_report`) et **Heure du rapport mensuel**
  (`alerts.monthly_report_hour`, 9).

### Modifié

- La clé d'une notification « attend ta réponse » devient
  `attente:<pid>:<horodatage>` (une clé par attente).
- `state.json` gagne la clé `quiet` (`active`, `until`, `source`, `held`).
- Le menu de l'icône propose « Installer CCS x.y.z… » quand une version est
  annoncée.

## [0.6.1] — 2026-11-09

### Corrigé

- **Réglages édités à la main** : une valeur invalide (mauvais type, hors
  bornes, heure « 25:00 », jour inconnu…) ou un `settings.json` illisible ne
  fait plus planter le service, l'application, la ligne de commande ni le hook.
  La clé fautive prend sa valeur par défaut, le fichier n'est jamais modifié, et
  `ccs doctor` (ligne « Réglages ») ainsi que le journal du service la signalent.
- **`ccs best`** (avec `--switch` ou `--notifier`) ne recommande plus et ne
  bascule plus vers un compte dont le dernier relevé est en erreur (connexion
  perdue, jeton refusé, relevé absent ou trop ancien) : la raison est affichée
  (« X ignoré : connexion perdue »), et un message clair s'affiche s'il ne reste
  aucun compte utilisable (code de sortie 1, aucune bascule).
- **Réveil précis** au début et à la fin de la plage horaire (marge de 2 s) :
  le premier démarrage de fenêtre du matin n'attend plus le relevé suivant.
- **Changement d'heure** : les plages horaires suivent l'heure locale réelle.
  Une borne entre 2 h et 3 h la nuit du passage à l'heure d'été est décalée à
  3 h ; à l'heure d'hiver, la première occurrence de l'heure doublée est
  retenue. Les durées de période et « Pause jusqu'à demain » sont justes ces
  nuits-là.
- **Sessions** : les notifications « a terminé » / « attend ta réponse »
  fonctionnent même si `~/.claude/sessions` est créé après le démarrage du
  service, ou supprimé puis recréé.

## [0.6.0] — 2026-11-07

### Ajouté

- **Conseiller de formule** : `ccs formule` (alias `ccs conseil`) et carte de
  l'onglet Analyse. Besoin mesuré sur les relevés des dernières semaines en
  unités Pro (semaine et fenêtres de 5 h simultanées, semaines bridées
  majorées), combinaison Pro / Max / Ultra la moins chère qui le couvre avec
  20 % de marge, raisonnement détaillé, économie ou surcoût par rapport à la
  formule actuelle et équivalent mensuel au tarif de l'API (journaux de ce
  PC). Prix relevés sur claude.com/pricing le 2026-11-06 (Pro 20 $/mois, 17 $
  en annuel ; Max 100 $ « 5x » ; Ultra 200 $, l'ancien Max 20x), signalés « à
  vérifier » après 120 jours. Formule de chaque compte détectée
  (`subscriptionType`, `rateLimitTier`). Réglages `advisor.weeks`,
  `advisor.margin_pct`, `advisor.plan_prices`, `advisor.profile_plans`,
  `advisor.max_accounts`, aussi dans le groupe « Conseiller de formule » des
  Réglages (semaines analysées 1–12, marge 0–100 %, comptes au plus 1–5,
  formule d'un compte quand la détection hésite, tarifs dans une ligne
  dépliable). Message d'attente pendant le calcul dans le terminal.
- **Conseil de modèle près des limites** : au-delà de 80 % (session ou
  semaine) avec un modèle cher, une notification par fenêtre de 5 h propose
  la famille moins chère (Fable → Opus → Sonnet → Haiku) et le gain en ordre
  de grandeur (« ×N », tarifs de l'API appliqués aux réponses des 30 dernières
  minutes) ; « → sonnet ? » dans la ligne d'état de Claude Code. Réglages
  `alerts.model_advice`, `alerts.model_advice_pct` (« Proposer un modèle
  moins cher près des limites », « Seuil du conseil (%) » 50–99, groupe
  « Conseils » des Réglages).
- **Bilan de la semaine** : `ccs semaine [--precedente N]` (N de 0 à 520), carte de l'onglet
  Analyse avec choix de la semaine et notification hebdomadaire (comptes,
  activité, tokens et équivalent API, modèles, projets, bascules et alertes,
  comparaison avec la semaine précédente). Semaine alignée sur la plupart des
  comptes ou sur un jour fixe : `alerts.weekly_report`,
  `alerts.weekly_report_day`, `alerts.weekly_report_hour` (« Bilan de la
  semaine », « Jour du bilan », « Heure du bilan », groupe « Conseils » des
  Réglages ; notifications envoyées seulement si les notifications sont
  activées).
- **Journal des bascules** : section de l'onglet Historique et
  `ccs journal [--jours N | --tout]`. Chaque bascule avec sa raison en clair
  (automatique avec le pourcentage, anticipée par l'orchestrateur, après un
  blocage avec le projet, manuelle et son origine), échecs, limites atteintes
  sans bascule et démarrages de fenêtre ; groupes par jour, filtre 7 jours /
  30 jours / tout. Origine d'une bascule manuelle : application, icône,
  notification, commande `ccs`, raccourci clavier, nouvelle session, compte du
  projet (`~/.claude-accounts/switch-origin.json`, écrite aussi par `ccs`
  lui-même ; variable `CCS_VIA`).
- **Compte par projet** : `ccs projet [<dossier>] [<compte>|aucun]` et
  « Compte de ce projet… » en tête d'un projet ; héritage par les
  sous-dossiers (`~/.claude-accounts/projects.json`). En ouvrant une session ou
  une conversation du projet depuis l'application, la bascule est proposée
  (Basculer et ouvrir / Ouvrir sans basculer / Annuler, « Ne plus demander
  pour ce projet ») ; « Nouvelle session » présélectionne le compte du projet.
  Rien n'est proposé pendant une pause.
- **Raccourcis clavier globaux** (bureau GNOME, même application fermée,
  désactivés par défaut) : ouvrir l'application (Super+Alt+C), sessions
  (Super+Alt+V), nouvelle session (Super+Alt+N), compte suivant (Super+Alt+B),
  meilleur compte (Super+Alt+M), pause 1 h (Super+Alt+P), reprendre
  (Super+Alt+R). Groupe « Raccourcis clavier » des Réglages (capture d'une
  combinaison, conflits signalés) et
  `ccs raccourcis [status|on|off [action…]|set <action> <raccourci>]` (alias
  `ccs shortcuts`). CCS n'écrit que ses propres raccourcis personnalisés et ne
  retire jamais les autres.
- **`--notifier`** pour `ccs <nom>`, `ccs use`, `ccs next`, `ccs best` et
  `ccs pause` : résultat aussi en notification passagère (« Bascule sur X »,
  « Déjà sur X », « Bascule impossible », « Aucun compte disponible »,
  « Pause jusqu'à 14:00 », « Pause levée », « Pause impossible ») ; c'est
  l'option des raccourcis de bascule et de pause, notés « raccourci » dans le
  journal.
- `claude-accounts notify [--] <titre> [<texte>]` : notification passagère
  (repli de `ccs` : `notify-send`).
- Menu de l'icône : « Journal des bascules » et « Bilan de la semaine », qui
  ouvrent l'application sur le bon onglet.
- `claude-accounts gui --page <onglet>` ouvre un onglet (`sessions`,
  `comptes`, `planning`, `historique`, `analyse`, `terminaux`, `reglages` ;
  accents et majuscules indifférents, code 2 pour un nom inconnu) et
  `claude-accounts gui --new-session` le dialogue « Nouvelle session » ; les
  deux se combinent avec `--session` et marchent aussi application ouverte.
- Réglages : nouveaux groupes « Conseils », « Conseiller de formule » et
  « Raccourcis clavier ». Ordre : Bascule automatique, Orchestrateur, Alertes,
  Conseils, Conseiller de formule, Intégration, Terminal intégré, Raccourcis
  clavier, Warm-up, Service.

### Modifié

- **Un seul onglet « Sessions »** réunit les sessions ouvertes et l'historique
  des conversations ; l'onglet Conversations disparaît. À gauche, les projets
  (« Tous les projets », point vert pour une session ouverte, bleu quand elle
  attend ta réponse, nombre de conversations, compte du projet, dossier
  introuvable) ; à droite, l'en-tête du projet (compte, « Compte de ce
  projet… », « Nouvelle session ▾ »), « Ouvertes maintenant » puis ses
  conversations groupées par date. Recherche et filtre d'origine communs,
  bouton « Nouvelle session… ». Toutes les actions sont conservées (reprise
  dans l'application, un terminal externe ou VS Code, aperçu, coût,
  renommage, projet déplacé, badge des sessions en attente). En fenêtre
  étroite, la liste des projets se replie (bouton ☰).
- Une notification de session ouvre son projet dans l'onglet Sessions, en
  retirant les filtres qui cacheraient la session.
- Les onglets passent en bas de la fenêtre sous 1100 sp de large (1220 sp avec
  la page Terminaux), au lieu de 1350 / 1540.
- La ligne d'état lit le contexte JSON envoyé par Claude Code (modèle de la
  session) sans jamais attendre un terminal, 2 s au plus.
- `ccs use <nom>` et `ccs <nom>` refusent les arguments en trop (usage, code 1).
- Les raccourcis de bascule et de pause activés avant `--notifier` sont
  signalés « à mettre à jour » (`ccs raccourcis status`, bouton « Mettre à
  jour les commandes ») ; ils ne sont jamais réécrits d'office. Dans les
  Réglages, le raccourci s'affiche en texte (« Super+Alt+B »).
- Fenêtre étroite : l'onglet Historique reste utilisable dès 252 px (légende
  repliée) ; le filtre d'origine de l'onglet Sessions s'abrège en « Toutes ».
- Événements `switch` et `error` de l'historique : nouveaux champs pour le
  journal (compte quitté, pourcentage et seuil, quota qui expire, origine
  d'une bascule manuelle, projet). Les anciens événements restent lisibles.
  L'origine d'une bascule lancée par l'application est notée dans
  `~/.claude-accounts/switch-origin.json`, lue puis retirée par le service.
- README : tableau des formules aux prix du 2026-11-06 (Ultra à 200 $, l'ancien
  Max 20×).

## [0.5.0] — 2026-11-06

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
  - `ccs pause [1h|4h|demain|manuel|off|status]` / `claude-accounts pause`
    (`status` par défaut, `reprendre` comme `off`, code 2 pour un choix
    inconnu).
  - Menu de l'indicateur (« Mettre en pause », « Reprendre maintenant », ⏸
    devant le pourcentage), carte « Meilleur compte » de l'onglet Comptes,
    rappel dans l'onglet Planning, ⏸ dans la ligne d'état de Claude Code.
  - En-tête de la fenêtre : « Auto ⏸ jusqu'à 14:00 », un clic propose
    « Reprendre maintenant ».
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
  une seule notification par version, ligne dans l'indicateur, bandeau « CCS
  x.y.z est disponible — Voir » dans la fenêtre (une fois par lancement, si la
  version est plus récente que l'installée) et lien dans Réglages
  (`updates.enabled`, cache `~/.claude-accounts/updates.json`).
- **Bilan de santé** : `ccs doctor` (alias `ccs bilan`),
  `claude-accounts doctor` et « Bilan de santé… » dans le menu ☰ de
  l'application : service, relevés, versions, extension et indicateur,
  intégration, connexion de chaque compte, `claude`, `jq`, terminal intégré.
  Une commande à copier par problème (rien n'est exécuté) ; code de sortie 0 si
  tout va bien, 1 au moindre avertissement. L'application fait le bilan 4 s
  après son ouverture et affiche un bandeau « Un problème a été détecté… — Voir
  le bilan » en cas d'erreur. Des jetons, seuls la présence et les dates
  d'expiration sont lues.
- **Aperçu d'une conversation** sans la reprendre : « Aperçu… » dans le menu
  des conversations (onglet Conversations, conversations récentes et sessions
  ouvertes de l'onglet Sessions) et `ccs preview <id>` (alias `ccs apercu`),
  Markdown sur la sortie avec le coût en en-tête : demandes, réponses, outils
  en une ligne ; copie et **export en Markdown** avec le coût. Journal lu en
  flux, même très gros.
- `ccs export <id> [fichier.md]` (alias `ccs exporter`) : `<titre>.md` dans le
  dossier courant par défaut, ou dans le dossier donné ; affiche le chemin
  écrit.
- **Coût d'une conversation** : tokens consommés (sous-agents compris) et
  équivalent au tarif de l'API Anthropic en dollars (tarifs du 2026-10-06),
  affiché dans chaque ligne des onglets Conversations et Sessions (calculé
  après l'affichage), sur la carte d'une session ouverte et en tête de
  l'aperçu et de l'export. Un abonnement ne facture pas au token : le montant
  sert à comparer les conversations.
- **Nouvelle session avec options** : dialogue avec le dossier, le compte, le
  modèle (`--model`) et le mode de permissions (`--permission-mode`), depuis le
  bouton « Nouvelle session… » de l'onglet Sessions, le menu ☰ ou « Avec des
  options… » dans le menu d'un projet. Bascule de compte d'abord si besoin
  (avertissement : elle s'applique à toutes les sessions ouvertes ; en cas
  d'échec, rien ne s'ouvre), puis ouverture dans le terminal intégré ;
  avertissement en rouge pour `bypassPermissions`.
- **Notifications de session cliquables** (« a terminé », « attend ta
  réponse », rappel ; clic ou bouton « Afficher ») : l'application s'ouvre sur
  l'onglet du terminal intégré de la session, sinon sur sa carte dans l'onglet
  Sessions ; elle est lancée si elle ne tourne pas.
- **Badge** du nombre de sessions qui attendent une réponse sur l'onglet
  Sessions.
- Réglages : groupe « Terminal intégré » avec les interrupteurs « Reprise
  automatique après une limite » et « Rouvrir les onglets au démarrage ».

### Modifié

- L'onglet Sessions affiche les mêmes titres que l'onglet Conversations (titre
  donné, sinon titre automatique, sinon première demande) et ne propose plus
  de reprendre une conversation déjà ouverte ailleurs.
- Paquet : dépend de `gir1.2-vte-3.91`.
- L'alerte de fin de semaine prévue remplace l'alerte « semaine en avance sur
  le rythme », moins précise, quand elle part.
- L'indicateur se relance tout seul après une mise à jour du paquet, comme le
  service. En venant de la 0.4.0 ou d'avant, relance-le une fois à la main.
- `ccs status` affiche la pause en cours.
- Paquet : libadwaita 1.5 au moins (`gir1.2-adw-1 (>= 1.5)`, Ubuntu 24.04 l'a).
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
