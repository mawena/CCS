# Phase 12 (0.10.0) — CCS façon VS Code : chat, fichiers, feuille de route, nouveau design

Validée par Charles le 12/11/2026, partie par partie, sur maquettes (dispositions
« B » pour les fichiers, « B » pour le chat, « A et B » pour la feuille de route,
« B » pour la navigation), puis « tout est ok ». Ce document sert de contrat aux
sous-agents : comportement attendu, choix faits, choix laissés au constructeur.

Les choix marqués **[choix de Claude]** n'ont pas été discutés un par un avec
Charles : ils ont été annoncés comme propositions et Charles n'a rien objecté.

## Intention

Charles a utilisé l'extension Claude Code de VS Code et y a aimé :

- voir les fichiers du projet en interface graphique, lire leur contenu, voir un
  fichier Markdown en aperçu mis en forme (« la version design »), modifier les
  fichiers ;
- le chat graphique, surtout le moment où, d'un clic, il a changé de modèle, d'effort
  et activé l'ultracode.

Il veut cela dans CCS, en gardant GTK (pas d'Electron, pas d'application web), plus
une façon de suivre la feuille de route de ses projets et de voir leur évolution, et
un design général amélioré « le plus possible ». Le renommage de l'application en
« CCS » (demandé dans la même conversation) est déjà fait et publié en 0.9.0.

Réussite : Charles ouvre CCS, clique sur une session, et travaille avec Claude dans
un chat aussi agréable que celui de VS Code, avec ses fichiers et sa feuille de route
sous les yeux, sans jamais avoir besoin d'ouvrir VS Code pour ça.

## Buts

1. Nouvelle navigation : quatre onglets en haut (Accueil, Sessions, Projets, Analyse),
   Réglages dans le menu ☰.
2. Les sessions Claude de CCS deviennent un **chat graphique** (plus de terminal pour
   Claude), avec une barre cliquable : modèle, effort, ultracode, droits ; contexte
   et compte affichés.
3. Un **panneau Fichiers** dans chaque onglet de session : arbre, lecture, coloration,
   aperçu Markdown, édition, diff des modifications de Claude.
4. La **feuille de route** : dans l'onglet de session (panneau) et dans une page
   **Projets** (tous les projets, évolution dans le temps).
5. Un **design général** plus soigné, en GTK 4 / libadwaita uniquement.

## Non-buts

- CCS ne devient pas un éditeur de code complet : pas de débogueur, pas de terminal
  intégré dans le panneau fichiers, pas de recherche dans tout le projet, pas
  d'extensions, pas d'interface git au-delà des marques de l'arbre.
- Pas de réimplémentation des commandes interactives de Claude Code (`/config`,
  `/login`, menus de `/` en plein écran…) : une sortie de secours les couvre (voir
  « Ouvrir dans un terminal »).
- Pas de prise de contrôle des sessions lancées hors de CCS (dans un autre terminal) :
  elles restent affichées comme aujourd'hui.

## Anti-buts (ce qui serait un échec même si « ça marche »)

- Perdre une fonction existante des onglets Terminaux : file de messages, vue
  partagée en deux, réouverture des onglets au démarrage, bascule de compte et
  reprise quand une limite tombe, alertes « attend ta réponse » (bureau et
  téléphone), alerte de contexte lourd, compte par projet, options avancées de la
  nouvelle session.
- Écraser un fichier que Charles a modifié sans l'avoir enregistré, ou une
  modification de Claude, sans le prévenir.
- Faire grossir la mémoire du poste : il a 14 Go ; un chat ne doit pas coûter
  beaucoup plus qu'un onglet de terminal aujourd'hui (le processus `claude` compris).
- Une interface qui fige pendant une lecture de fichier, un calcul d'historique git
  ou un long message : tout ce qui est lent part dans un fil.
- Copier le contenu des conversations de Charles dans le code, les tests, les commits
  ou les rapports.

## Contraintes

- **Cible : Ubuntu 24.04 (noble)**, celle de Charles : GTK 4.14, libadwaita 1.5,
  PyGObject 3.48, Python 3.12. Pas de widget plus récent (pas d'`Adw.ToggleGroup`,
  d'`Adw.WrapBox`, d'`Adw.MultiLayoutView`… qui arrivent en 1.6/1.7) ; à défaut,
  repli testé.
- GTK 4 / libadwaita uniquement pour l'interface. **Pas de WebKit** pour le chat ni
  l'aperçu Markdown **[choix de Claude]** : rendu natif (mémoire, cohérence GTK).
  WebKitGTK est installé chez Charles mais n'est pas retenu.
- Nouvelles dépendances du paquet : `gir1.2-gtksource-5` (éditeur, coloration, diff ;
  `Depends`), `python3-markdown-it` (analyse du Markdown ; `Depends`).
  `python3-pygments` n'est pas nécessaire si GtkSourceView colore les blocs de code.
  Les mettre dans `debian/control`, le `README` et `ccs doctor`.
- Règles habituelles du projet : tout en français (textes, commits conventionnels,
  docstrings), git flow, commits sans attribution, **tout calcul par la file
  Gagarine** (`gagarine file "<nom>" <Go> <cœurs> -- <commande>`), tests graphiques
  uniquement sous Xvfb (`CCS_GUI_TESTS=1 xvfb-run -a`, ce que fait `make unit`),
  jamais de vrai `claude` avec un message dans les tests (faux binaire), aucune vraie
  notification, ne pas toucher à l'application ouverte de Charles, à son service ni à
  ses réglages GNOME, ne jamais lire `~/.claude-accounts`.

## 1. Navigation (onglets du haut)

| Onglet | Contenu | Pages d'aujourd'hui |
|---|---|---|
| **Accueil** | Cartes des comptes, file de tâches et meilleur moment, **[choix de Claude]** fil des derniers événements (bascules, tâches finies, alertes) | Comptes + Planning |
| **Sessions** | Onglet fixe « Toutes les sessions » (la page Sessions actuelle : projets, sessions ouvertes, conversations passées) puis un onglet par chat ouvert et par shell | Sessions + Terminaux |
| **Projets** | Toutes les feuilles de route et leur évolution (section 5) | nouveau |
| **Analyse** | Analyse et Historique (courbes, journal des bascules), avec un sélecteur en haut | Analyse + Historique |
| ☰ → **Réglages** | Fenêtre à part (`Adw.PreferencesDialog`) | Réglages |

- Les anciens noms de page restent acceptés partout où ils servent (`ccs gui --page
  comptes|planning|sessions|terminaux|historique|analyse|reglages`, `desktop.page_name`,
  menu de l'indicateur, raccourcis clavier, clic sur une notification, `--task`,
  `--session`, `--new-session`) et mènent au bon onglet et à la bonne sous-partie
  (ex. `--page planning --task <id>` → Accueil, tâche affichée ; `--page historique`
  → Analyse, partie Historique).
- Badge sur « Sessions » : nombre de chats qui attendent une réponse ou une
  autorisation (comme le badge Terminaux d'aujourd'hui).
- Le comportement en fenêtre étroite (barre du bas `Adw.ViewSwitcherBar`) est gardé.

## 2. Le chat (remplace l'onglet de terminal Claude)

### Ce que voit Charles

- Les messages de Charles en bulles à droite ; les réponses de Claude à gauche, en
  Markdown rendu (titres, listes, tableaux, code coloré, liens, citations).
- Chaque action de Claude devient une **carte repliable** : fichier lu, fichier
  modifié avec `+12 −3` (clic → le diff s'ouvre dans le panneau du fichier), commande
  lancée (commande et sortie repliée), recherche, sous-agent, outil MCP. Une action en
  cours montre une petite roue ; une action en échec est marquée.
- La **liste de tâches** de Claude (outil de tâches) s'affiche en cases à cocher qui
  se mettent à jour.
- Une **demande d'autorisation** devient une carte avec « Autoriser », « Toujours »
  (pour cette règle, comme le propose Claude Code) et « Refuser » (avec un motif
  facultatif). Le badge de l'onglet et l'alerte « attend ta réponse » se déclenchent.
- Le texte de Claude arrive au fil de l'eau (messages partiels), pas d'un bloc à la
  fin.
- **Zone de saisie** en bas : Entrée envoie, Maj+Entrée va à la ligne ; `@` propose
  les fichiers du projet (depuis le panneau Fichiers) ; `/` propose les commandes
  (celles que Claude Code annonce, plus les personnalisées et celles des plugins) ;
  coller ou glisser une image l'ajoute au message (vignette avec ✕) ; glisser un
  fichier de l'arbre insère sa référence `@chemin`.
- Bouton **Arrêter** pendant que Claude travaille (comme Échap dans le terminal).
- Un message écrit pendant que Claude travaille rejoint la **file de messages** (la
  fonction existante, gardée : bulles en attente, modifiables, réordonnables,
  supprimables, « envoyer maintenant ») et part quand Claude a fini.

### La barre cliquable (sous la zone de saisie)

- **Modèle** : liste des modèles proposés par Claude Code (alias Opus, Sonnet, Haiku,
  Fable et ceux annoncés par le CLI).
- **Effort** : faible, moyen, élevé, très élevé, max (`low`, `medium`, `high`,
  `xhigh`, `max`). Les niveaux qu'un modèle n'accepte pas (ex. `xhigh` sur Opus 4.6 /
  Sonnet 4.6) sont grisés.
- **Ultracode** : bouton à bascule. D'après la documentation, ce n'est pas un niveau
  d'effort mais un réglage de session (Claude orchestre des workflows pour les
  grosses tâches) : `/effort ultracode` l'active, `/effort ultracode off` le coupe,
  `--effort ultracode` le met au lancement (en `xhigh`). Grisé si le modèle n'accepte
  pas `xhigh` ou si les workflows sont désactivés. Pas de mot-clé ajouté aux messages.
- **Droits** : « Demander » (par défaut : une carte d'autorisation à chaque action
  qui le demande ; remplace « lecture seule », qui n'a plus lieu d'être avec les
  cartes) / modifications acceptées / plan / tout autoriser (avec le même
  avertissement que l'option avancée d'aujourd'hui), en reprenant `launch_options`
  **[choix de Claude]**. Si les cartes s'avèrent impossibles (repli de l'annexe),
  « Demander » redevient « Lecture seule ».
- À droite, non cliquables : **contexte utilisé** (pourcentage, couleur au-delà du
  seuil de l'alerte de contexte lourd) et **compte** (nom, couleur du compte, jauge
  courte).
- Un changement prend effet au prochain message. Si Claude Code ne sait pas le changer
  en direct, CCS relance le processus sur la même conversation (`--resume`) avant ce
  message, sans rien montrer d'autre qu'un court « Modèle changé ». Les valeurs
  choisies sont gardées par onglet et retrouvées à la réouverture.

### Comportements conservés des terminaux

- **Compte** : le chat tourne sous le compte que CCS aurait donné à un terminal
  (compte actif ou compte du projet), comme `terminal.claude_launch` aujourd'hui.
- **Limite atteinte** : même décision qu'aujourd'hui (`terminal.resume_decision`) ;
  bascule de compte, puis la conversation reprend sur l'autre compte avec un message
  « continue », dans la limite actuelle de reprises par heure. Un encart dans le chat
  dit ce qui s'est passé.
- **Réouverture au démarrage** : les chats ouverts sont proposés à la réouverture
  comme aujourd'hui. **[choix de Claude]** Un chat rouvert affiche l'historique de la
  conversation (lu dans son journal) sans lancer `claude` ; le processus ne démarre
  qu'au premier message envoyé. Même règle pour un chat ouvert depuis l'historique
  d'une conversation.
- **Vue partagée en deux** : deux chats côte à côte (raccourci actuel gardé).
- **Alertes** : « attend ta réponse » (fin de réponse ou demande d'autorisation),
  contexte lourd, budget : mêmes alertes qu'aujourd'hui, bureau et téléphone. CCS sait
  lui-même quand un chat attend : il ne dépend pas des hooks de Claude Code pour ses
  propres chats.
- **Nouvelle session** (dialogue, options avancées, raccourci clavier, menu de
  l'indicateur) : ouvre un chat.
- **Fermer un onglet** pendant que Claude travaille : même confirmation qu'aujourd'hui.

### Sortie de secours

- Menu de l'onglet : « Ouvrir cette conversation dans un terminal ». CCS arrête le
  processus du chat (après confirmation si Claude travaille) et ouvre un onglet shell
  (terminal VTE, comme aujourd'hui) qui lance `claude --resume <id>` sous le même
  compte. Quand ce terminal se ferme, « Revenir au chat » rouvre le chat sur la même
  conversation.
- Les onglets **shell** restent de vrais terminaux VTE.
- Si `gir1.2-vte-3.91` manque, la sortie de secours passe par le terminal externe
  (comportement actuel de repli).

### Sessions hors de CCS

Une session ouverte dans un autre terminal reste listée dans « Toutes les sessions »
avec ses informations actuelles (RAM, inactivité, contexte). **[choix de Claude]**
CCS ne la reprend pas tant qu'elle tourne : deux processus sur une même conversation
la corrompraient. Une fois fermée, « Reprendre » l'ouvre en chat.

### Protocole avec Claude Code

Le chat pilote `claude` en processus enfant, en JSON ligne par ligne sur stdin/stdout,
comme l'Agent SDK et l'extension VS Code. Le format exact (arguments, messages,
requêtes de contrôle pour l'interruption, le modèle, les droits, les autorisations)
est décrit dans l'annexe « Protocole », tirée de la documentation et du code public
du SDK.

- Le module qui parle à `claude` est **sans GTK** (`ccs_app/chat_engine.py` par
  exemple) : lancement, envoi, lecture des événements, état de la conversation. Il est
  testable avec un **faux `claude`** (script qui rejoue des événements enregistrés et
  répond aux requêtes de contrôle). Il réutilise ce que la file de tâches a déjà
  (`task_runner` : lecture du flux JSON, détection de limite, coût).
- Lecture de stdout dans un fil (ou `Gio.Subprocess` + `Gio.DataInputStream`
  asynchrone), jamais de lecture bloquante dans la boucle GTK.
- Tout événement inconnu est ignoré sans erreur (versions futures de Claude Code) ;
  un événement illisible est journalisé, pas affiché en vrac.
- Vérifier en vrai, une fois, avec un vrai message (et l'accord de Charles, puisque
  cela consomme du quota) : format réel, changement de modèle et d'effort, ultracode,
  détection de limite. Cela n'a jamais été vérifié en vrai pour la file de tâches non
  plus.

## 3. Le panneau Fichiers

- **Disposition** : deux dispositions, réglables par un bouton dans la barre de
  l'onglet, retenues globalement :
  - **B (par défaut)** : arbre à gauche | chat au centre | fichier à droite. Le
    panneau du fichier n'apparaît que lorsqu'un fichier est ouvert, et se ferme (✕).
  - **A** : arbre à gauche | fichier au centre | chat à droite (comme VS Code).
- **Redimensionnable** : chaque séparation se tire à la souris (`Gtk.Paned`) ; les
  largeurs sont retenues (par disposition). Ctrl+B replie ou rouvre l'arbre
  **[choix de Claude]**.
- **Arbre** : le dossier de la session ; dossiers chargés à l'ouverture (paresseux) ;
  mis à jour quand des fichiers changent (`Gio.FileMonitor`, regroupé) ; marques git
  `M`, `A`, `?`, `D` comme VS Code (une commande `git status --porcelain` par vague de
  changements, dans un fil) ; `.git`, `node_modules` et les fichiers ignorés par git
  masqués par défaut, avec un réglage pour les afficher ; menu du clic droit : ouvrir,
  copier le chemin, insérer `@chemin` dans le message, ouvrir avec l'application par
  défaut, afficher dans Fichiers.
- **Fichier ouvert** : onglets de fichiers ; GtkSourceView 5 (numéros de ligne,
  coloration selon le langage, thème clair ou sombre suivant l'application, recherche
  dans le fichier Ctrl+F, annuler/refaire) ; images affichées (`Gtk.Picture`) ;
  fichier binaire → « fichier binaire, non affiché » ; fichier de plus de 2 Mo →
  ouvert en lecture seule avec un bandeau **[choix de Claude]**.
- **Markdown** : bascule « Source / Aperçu » ; aperçu rendu nativement (titres,
  listes, cases à cocher, tableaux, code coloré, citations, liens cliquables, images
  locales et distantes non chargées par défaut **[choix de Claude]**) ; l'aperçu suit
  les modifications. Le même moteur de rendu sert au chat.
- **Édition** : Ctrl+S enregistre (écriture atomique, droits du fichier conservés) ;
  point « non enregistré » sur l'onglet ; fermer un fichier non enregistré demande
  confirmation.
- **Modifications par Claude** : un fichier ouvert et non modifié par Charles se
  recharge tout seul (et l'onglet clignote doucement). S'il a des changements non
  enregistrés, un bandeau propose « Garder les miens » / « Prendre la version sur le
  disque » / « Voir les différences » ; rien n'est écrasé sans choix.
- **Diff** : « voir le diff » sur une carte de modification ouvre, dans le panneau du
  fichier, un diff coloré (ajouts / suppressions) de cette modification, avec un
  bouton vers le fichier entier.

## 4. La feuille de route dans l'onglet de session (maquette A)

- Le panneau de gauche bascule entre « Fichiers » et « Feuille de route ».
- Lue dans `ROADMAP.md` à la racine du dossier de la session (à défaut, en remontant
  jusqu'à la racine du dépôt git).
- **Format** (celui des projets de Charles) : un titre `#` ; des phases en titres `##`
  (« Phase 12 — Titre (0.10.0) ✅ ») ; des tâches `- [ ]` / `- [x]`, éventuellement
  imbriquées ; du texte libre entre les deux. Les phases ne sont pas forcément dans
  l'ordre du fichier (chez CCS, les phases 4 et 9 sont à la fin). Version tirée des
  parenthèses du titre quand il y en a.
- Affichage : en-tête (projet, dernière version, nombre de phases finies) ; chaque
  phase avec sa barre de progression et `cochées/total` ; les phases non finies sont
  dépliées, les finies repliées **[choix de Claude]** ; tâches en cases à cocher.
- **Clic sur une case** : la coche (ou la décoche) dans `ROADMAP.md` en ne changeant
  que ce caractère ; si le fichier a changé depuis sa lecture, relire d'abord ; jamais
  de réécriture complète du fichier.
- Quand Claude coche une case (fichier modifié), la tâche s'allume brièvement.
- Sans `ROADMAP.md` : écran vide avec « Demander à Claude d'en créer une », qui envoie
  un message au chat de l'onglet **[choix de Claude]**.

## 5. La page Projets (maquette B)

- **Projets listés** **[choix de Claude]** : les dossiers où Charles a déjà ouvert une
  session Claude (connus par `conversations` / `sessions`) et qui ont un
  `ROADMAP.md`. Un réglage permet d'en masquer.
- **Carte par projet** : nom, dernière version (dernier tag git `v*`, sinon titre de la
  dernière version du CHANGELOG), dernière activité (dernier commit ou dernière
  conversation, la plus récente), phase en cours et sa barre.
- **Détail d'un projet** (clic) :
  - la feuille de route complète (même affichage que la section 4, cases cliquables) ;
  - une **frise des versions** (tags git et dates) ;
  - les **tâches cochées par jour** (graphique en barres), tirées de l'historique git
    de `ROADMAP.md` (lignes passées de `[ ]` à `[x]` dans chaque commit) ;
  - pour chaque phase finie, la date de sa dernière case cochée ;
  - bouton « Ouvrir une session dans ce projet ».
- Calculs dans un fil, mis en cache par (dossier, dernier commit) ; rien de lourd à
  l'ouverture de la page.

## 6. Le design général

- Une **couleur par compte** **[choix de Claude]**, attribuée automatiquement dans une
  palette lisible en clair et en sombre, modifiable dans les Réglages, reprise
  partout : cartes, jauges, graphiques de l'Analyse, barre du chat, liste des sessions.
- **Cartes** arrondies, espacements réguliers, gros chiffres lisibles d'un coup d'œil
  (classes `title-1`… et `numeric` de libadwaita), listes en `boxed-list`.
- **Écrans vides** soignés partout où une liste peut être vide (`Adw.StatusPage` :
  icône, phrase, bouton utile).
- **Clair / sombre** suivi automatiquement ; choix forcé possible dans les Réglages
  (`Adw.StyleManager`).
- Transitions de libadwaita, icônes symboliques cohérentes, raccourcis
  Ctrl+1…Ctrl+4 pour les onglets **[choix de Claude]**.
- Chaque page existante est reprise dans ce style, sans perdre aucune information
  ni action qu'elle a aujourd'hui.

## Ordre des travaux, mémoire, données de la barre, migration

- **Essai réel du protocole en premier** : c'est la première tâche du plan et une
  porte. Le constructeur prépare un petit script d'essai (un ou deux messages écrits
  pour l'occasion, modèle le moins cher, dans un dossier temporaire, sous le compte
  actif) et **attend l'accord de Charles** avant de le lancer (CCS ne le lance jamais
  seul). Le flux enregistré, anonymisé, devient le jeu d'essai du faux `claude`.
  **[choix de Claude]** Si `--permission-prompt-tool stdio` n'existe pas ou ne marche
  pas : repli sur un petit serveur MCP d'autorisation fourni par CCS
  (`--permission-prompt-tool mcp__ccs__…`) qui relaie la demande au chat ; si cela
  échoue aussi, le chat est livré sans cartes d'autorisation, avec les droits choisis
  dans la barre (lecture seule, modifications, tout), et c'est dit dans le CHANGELOG.
  Même logique pour `/effort` : s'il ne passe pas en message, relance avec `--resume
  --effort`.
- **Pas de casse en cours de route** **[choix de Claude]** : le code du terminal Claude
  actuel reste (il sert à « Ouvrir dans un terminal »). Les briques du chat arrivent
  d'abord sans être branchées ; une seule tâche, à la fin, fait ouvrir un chat au lieu
  d'un terminal, quand toutes les fonctions listées dans « Comportements conservés »
  ont leurs tests (pas besoin de réglage caché). Pas de release intermédiaire : tout
  part en 0.10.0.
- **Mémoire** **[choix de Claude]** : le processus `claude` d'un chat reste vivant
  entre les messages (file, texte au fil de l'eau, autorisations). Après **30 min**
  sans activité (réglable, 0 = jamais), CCS l'arrête proprement et le relance avec
  `--resume` au message suivant, sans rien montrer d'autre qu'un court « Reprise de la
  conversation… ». Jamais pendant que Claude travaille, attend une autorisation, ou a
  une tâche de fond en cours. Ce n'est pas une fermeture : l'onglet, l'historique et
  la file restent. Après 30 min le cache de l'API est de toute façon froid, donc cela
  ne coûte rien de plus en quota. Cible : 10 chats ouverts sans gêne ; l'interface d'un
  chat (sans le processus `claude`) reste sous ~50 Mo.
- **Données de la barre** **[choix de Claude]** : une table intégrée à CCS (modèles
  connus, niveaux d'effort acceptés par modèle, ultracode possible ou non) sert tant
  qu'aucun processus ne tourne, par exemple pour un chat rouvert avant son premier
  message. Dès que la CLI répond à `initialize` / `system/init` (`models`,
  `capabilities`, `effort`), ses valeurs remplacent la table. Si la CLI refuse un
  réglage, le bouton revient en arrière et un message court dit pourquoi.
- **Migration des onglets enregistrés par la 0.9** **[choix de Claude]** : un ancien
  onglet Claude se rouvre en chat, sans lancer `claude`, avec l'historique lu dans le
  journal ; un onglet shell reste un shell. Une conversation dont le journal a
  disparu est sautée et signalée dans le résumé de réouverture, comme aujourd'hui
  (`_conversation_exists`). Une conversation qui tourne encore dans un autre terminal
  s'ouvre en lecture seule, avec « Cette conversation est ouverte ailleurs », et
  devient utilisable quand l'autre processus se termine.

## Laissé au constructeur

- Le découpage en modules et en fichiers, les noms internes, la structure des widgets,
  à condition que la logique sans GTK reste testable à part (comme aujourd'hui :
  `terminal.py` à côté de `gui/terminals.py`).
- Le choix entre `Gtk.ListView` et une liste plus simple pour les messages, tant que
  1 000 messages restent fluides et que la mémoire reste raisonnable.
- Le détail du rendu Markdown (widgets ou `Gtk.TextView` à balises), tant qu'il couvre
  ce que liste la section 3 et sert au chat comme à l'aperçu.
- La migration des réglages et de l'état des onglets (`terminal_store`) vers le
  nouveau format, tant que rien n'est perdu à la mise à jour.
- Les textes exacts, les icônes, les petits espacements.

## Livraison

- Phase 12 dans `ROADMAP.md` (cases cochées au fil de l'eau), avec le renommage déjà
  fait coché.
- Tests : logique sans GTK testée à part (protocole, rendu Markdown en structure,
  feuille de route, historique git, dispositions) ; tests graphiques sous Xvfb ;
  faux `claude` pour le chat ; `tests/ccs_e2e.sh` mis à jour.
- Documentation : `README.md`, `docs/utilisation.md`, `docs/architecture.md`, pages
  man (`--page`), `CHANGELOG.md`, site (`site/index.html`).
- Release mineure **0.10.0** (nouvelles fonctions compatibles), `.deb`, release GitHub,
  dépôt APT.

## Annexe — Protocole

Tiré de la documentation officielle (code.claude.com : `headless`,
`agent-sdk/streaming-vs-single-mode`, `agent-sdk/streaming-output`,
`agent-sdk/typescript`, `model-config`, `context-window`) et du code public du SDK
Python (`anthropics/claude-agent-sdk-python` : `_internal/transport/subprocess_cli.py`,
`_internal/query.py`, `types.py`), avec la CLI installée chez Charles (2.1.322).
« À vérifier » = non confirmé par la doc ni le code lu.

**Lancement** (un processus par chat, vivant entre les messages) :

```
claude -p --input-format stream-json --output-format stream-json --verbose \
  --include-partial-messages --permission-prompt-tool stdio \
  [--model <m>] [--effort <niveau>|ultracode] [--permission-mode <mode>] \
  [--resume <session_id>]
```

Dans le dossier de la session, avec l'environnement du compte (comme
`terminal.claude_launch`), sans `CLAUDECODE` hérité. Pas de `--bare` (il coupe la
connexion par abonnement). `--permission-prompt-tool stdio` : à vérifier (c'est ce que
le SDK semble passer quand il gère lui-même les autorisations).

**Entrée** (stdin, une ligne JSON par message) :

```json
{"type":"user","message":{"role":"user","content":[
  {"type":"text","text":"…"},
  {"type":"image","source":{"type":"base64","media_type":"image/png","data":"…"}}]},
 "parent_tool_use_id":null}
```

Une commande (`/compact`, `/clear`, `/model sonnet`, `/effort high`,
`/effort ultracode`, commandes personnalisées et des plugins) s'envoie comme un
message texte. Les commandes réservées au terminal répondent « isn't available in
this environment ». Un message envoyé pendant un tour est mis en file par la CLI.

**Sortie** (stdout, une ligne JSON par événement) :

- `system/init` : `session_id`, `model`, `cwd`, `permissionMode`, `effort`,
  `slash_commands` (pour l'autocomplétion de `/`), `skills`, `capabilities` (à
  utiliser pour savoir ce que la CLI sait faire, plutôt que son numéro de version) ;
- `stream_event` : événements bruts de l'API (`content_block_delta` avec
  `text_delta`…) pour le texte au fil de l'eau ;
- `assistant` : blocs de contenu (texte, `tool_use`) ; `user` : `tool_result` ;
  `parent_tool_use_id` non nul = sous-agent ;
- `system/compact_boundary`, `system/api_retry`, `system/permission_denied` ;
- `result` : un par tour (`subtype` `success` ou `error_*`, `total_cost_usd`,
  `usage`, `modelUsage[modèle].contextWindow`).

**Contrôle** : le client envoie
`{"type":"control_request","request_id":"<id>","request":{"subtype":…}}` et reçoit
`{"type":"control_response","response":{"subtype":"success"|"error","request_id":…}}`.

| Sous-type | Usage dans CCS |
|---|---|
| `initialize` | au démarrage du processus (réponse : commandes, modèles, compte…) |
| `interrupt` | bouton « Arrêter » |
| `set_model` `{"model": …}` | menu Modèle |
| `set_permission_mode` `{"mode": …}` | menu Droits (`default`/`manual` à vérifier, `acceptEdits`, `plan`, `bypassPermissions`…) |
| `get_context_usage` | jauge de contexte (`percentage`, `totalTokens`, `maxTokens`) |

Aucun sous-type pour l'effort : CCS envoie `/effort <niveau>` (et
`/effort ultracode [off]`) comme message, à vérifier ; repli : relancer le processus
avec `--resume <session_id> --effort <niveau>`, ce qui restaure toute la conversation.

**Autorisations** : la CLI envoie à CCS une `control_request` `can_use_tool`
(`tool_name`, `input`, `permission_suggestions`, `tool_use_id`, `title`,
`description`…). CCS répond `{"behavior":"allow","updatedInput":<input>}` (Autoriser),
la même chose avec `"updatedPermissions": <permission_suggestions>` (Toujours), ou
`{"behavior":"deny","message":"…"}` (Refuser).

**Arrêt** : fermer stdin, attendre 5 s, SIGTERM, 5 s, SIGKILL. Lire stderr dans un
fil (sinon la CLI peut bloquer). Une ligne de stdout peut dépasser 1 Mo (gros
résultat d'outil) : pas de limite de longueur trop basse.

**À vérifier par un essai réel** (une seule session courte, avec l'accord de
Charles, puisque cela consomme un peu de quota ; message de test écrit pour
l'occasion, jamais une vraie conversation de Charles) : forme réelle de
`can_use_tool` et de `--permission-prompt-tool stdio` ; `/effort` et
`/effort ultracode` envoyés en stream-json ; `default` ou `manual` pour le mode de
permission ; forme exacte de `updatedPermissions` pour « Toujours » ; compte choisi
par l'environnement ; détection de limite. Le constructeur enregistre ce flux
(identifiants et chemins anonymisés) comme jeu d'essai du faux `claude`.
