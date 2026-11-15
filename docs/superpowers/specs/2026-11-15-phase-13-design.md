# Phase 14 (0.12.0) — conception (ex-phase 13)

Passée en phase 14 le 15/11/2026 : la partie VPS (serveur, web, terminal, bureau connecté) est prioritaire et devient la phase 13 (0.11.0).

Choix de Charles le 14 et le 15/11/2026 : toutes les propositions retenues, une seule
release mineure 0.11.0 à la fin, et une page Git inspirée de GiGit
(`~/Work/perso/GiGit`) qui en fait tout ce qu'il fait.

## Intention

Travailler sans quitter CCS. Aujourd'hui, Charles sort de CCS pour gérer git (terminal
ou GiGit), pour lancer une tâche de sa feuille de route, pour défaire ce qu'a fait
Claude, et il doit être devant le PC pour répondre à une autorisation. La phase 13
ramène tout cela dans l'application.

Réussite : une journée de travail avec Claude sans ouvrir de terminal ni GiGit, et une
autorisation donnée depuis le téléphone.

## Objectifs, non-objectifs, anti-objectifs

Objectifs : les quatre chantiers ci-dessous, livrés ensemble en 0.12.0.

Non-objectifs :
- Ce que GiGit prévoit pour ses versions 0.2 et 0.3 : merge, rebase, squash,
  cherry-pick, revert, résolution de conflits, stash, sous-modules, remotes, clone,
  création ou suppression de branches et de tags hors git flow.
- La liste de dépôts de GiGit : la page Git montre le dépôt du projet de la session.
- Raccourcir la conversation quand on revient avant un message : seuls les fichiers
  reviennent en arrière.

Anti-objectifs (échec même si cela « marche ») :
- Le chat devient moins fluide (la phase « Fluidité » de 0.10.2 ne doit pas régresser).
- Une action git ou un retour en arrière détruit du travail sans confirmation.
- Une autorisation peut être donnée depuis le téléphone par quelqu'un d'autre que
  Charles, ou le contenu d'une commande sort du PC sans que Charles l'ait choisi.

## Règles communes

Celles de la phase 11 (`2026-11-11-phase-11-design.md`, « Règles communes ») restent
valables : français partout, travail lourd par la file Gagarine, aucune vraie
notification ni vrai appel réseau ni vrai `claude` dans les tests, données de Charles
jamais recopiées, commits sans attribution. En plus :
- Les tests git travaillent dans des dépôts créés dans un dossier temporaire, jamais
  dans le dépôt de CCS ni dans un projet de Charles. Jamais de vrai `fetch`/`push` réseau
  (dépôt distant local en `file://`).
- Les tests de la page Git et du téléphone n'utilisent jamais le vrai `~/.claude`.

## Chantier 1 — Page Git (inspirée de GiGit)

### Ce qui est repris de GiGit 0.1
- Graphe des commits façon ungit : ligne principale depuis HEAD, une colonne par autre
  branche, noms de branches et de tags à côté des nœuds, chargement par pages (le graphe
  reste fluide sur un gros dépôt).
- Avatars des auteurs : Gravatar, ou l'avatar GitHub pour les adresses `noreply` de
  GitHub ; cache sur disque ; initiales quand il n'y a pas d'avatar. Activés par défaut,
  désactivables dans les Réglages (comme GiGit). Le téléchargement se fait dans un fil,
  jamais dans l'interface.
- Détail d'un commit : message, auteur, date, parents cliquables, fichiers modifiés et
  leur diff.
- Indexation précise : un fichier entier (case), un bloc ou des lignes du diff ;
  Shift+clic sélectionne une plage de lignes. Le vrai index git est utilisé (ce qui est
  indexé dans un terminal apparaît dans CCS, et inversement).
- Commit et amend ; Ctrl+Entrée valide ; l'amend reprend le message du dernier commit.
- Annulation de modifications (fichier, bloc ou ligne), toujours après confirmation.
- Ajout au `.gitignore` depuis le clic droit sur un fichier.
- Fetch, pull, push ; push forcé avec confirmation, par
  `--force-with-lease --force-if-includes` ; un premier push crée la branche distante
  (`--set-upstream`).
- Fetch automatique du dépôt affiché, toutes les 5 min par défaut, réglable ; il ne
  demande jamais de mot de passe (`GIT_TERMINAL_PROMPT=0`, pas d'`askpass`).
- Rafraîchissement automatique quand le dépôt change (fichiers ou `.git`).
- Erreurs git claires : bandeau avec le message, la commande et la sortie complète
  consultables.

### En plus de GiGit
- git flow depuis le menu de la branche : démarrer ou finir une feature, une release, un
  hotfix (par `git flow`, s'il est installé ; sinon les entrées sont grisées avec la
  raison).
- Message de commit proposé d'après les changements indexés (bouton « Proposer ») : liste
  des fichiers et nature des changements, sans appel à Claude.

### Dispositions
Un seul graphe, dessiné en deux densités : **compact** (une ligne par commit : rails
colorés, titre, âge, étiquettes) et **cartes** (façon ungit : carte par commit avec
avatar, auteur, âge, hash, à côté des nœuds).

| | Graphe | Où | Détail d'un commit |
|---|---|---|---|
| A (défaut) | compact | panneau de gauche, largeur normale | zone de droite, comme un fichier ouvert |
| B | cartes | grand onglet « Historique » dans la zone de droite ; le panneau garde la branche, les changements et le commit | colonne de détail dans l'onglet |
| C | cartes | panneau de gauche, élargi tout seul (≈ 520 px) tant que la page Git est affichée, rendu à sa largeur au retour sur Fichiers ou Feuille de route | zone de droite |

Sélecteur A / B / C en haut de la page Git ; le choix est retenu (comme les dispositions
de la page Sessions, dans `terminal_store`).

Toujours dans le panneau, quelle que soit la disposition : branche courante, avance et
retard sur la branche distante, boutons rafraîchir, fetch, pull, push, menu git flow,
liste « Indexé » / « Non indexé », message et Commit.

### Construction
Python/GTK4 dans CCS, en lançant la commande `git` du système (hooks, agent SSH,
gestionnaire d'identifiants et configuration marchent comme en terminal).
- Module sans GTK `ccs_app/git_repo.py` : lecture (`log` paginé avec parents et
  références, `status --porcelain=v2`, `diff`, `show`), écritures (`apply --cached` pour
  l'indexation partielle, `commit`, `checkout`/`apply -R` pour annuler, `fetch`,
  `pull`, `push`, `flow`), erreurs typées avec commande et sortie. Tout appel tourne
  hors de l'interface (`in_thread`).
- Module sans GTK `ccs_app/git_graph.py` : portage de `layout()` de GiGit
  (`src/graph.rs`, avec ses tests). Exigence reprise : 10 000 commits linéaires en moins
  de 200 ms.
- `ccs_app/gui/git_page.py` (page du panneau), `git_graph_view.py` (dessin des deux
  densités), `git_commit_view.py` (détail), `git_changes.py` (indexation, diff
  sélectionnable). La page est ajoutée à `left_stack` dans `session_workspace.py`
  (troisième titre « Git »). Le détail et l'onglet « Historique » utilisent la zone de
  droite (`FileEditor`, qui sait déjà afficher un diff : `show_diff`).
- Avatars : `ccs_app/avatars.py` (URL, cache dans `~/.claude-accounts/avatars/`).
- Réglages : `git.layout` (A, B, C), `git.fetch_minutes` (5 ; 0 = jamais),
  `git.avatars` (vrai).

### Laissé au constructeur
Dessin exact des rails et des cartes, taille des pages du `log`, regroupement des
rafraîchissements, style du bandeau d'erreur (dans l'esprit du nouveau design 0.10).

## Chantier 2 — Le travail de Claude

### Faire une tâche de la feuille de route
- Un bouton ▶ sur chaque tâche non cochée (`roadmap_view.py`) ouvre un menu : **Faire
  maintenant** (dans le chat de l'onglet de session) ou **Mettre dans la file de nuit**
  (file de tâches `ccs tache`, `tasks.py`).
- Message envoyé : « Fais la tâche « <texte> » (phase « <titre de la phase> ») de
  `ROADMAP.md` ; coche-la quand elle est finie. »
- Claude coche la case lui-même ; la feuille de route le voit (elle surveille le
  fichier ; `roadmap.newly_done`).
- Si le tour de Claude se termine sans que la case soit cochée, un bandeau au-dessus de
  la saisie : « Tâche finie ? **Cocher** / **Pas encore** ». « Cocher » utilise
  `roadmap.toggle` (ne change que ce caractère).
- File de nuit : pas de bandeau ; une tâche finie sans case cochée est signalée dans le
  résumé de la file et dans la notification de fin.
- La tâche est retrouvée par son texte et sa phase, pas par son numéro de ligne (le
  fichier peut changer entre-temps).

### Changements de la session
- Source : les copies que Claude Code garde pour `/rewind`. Le journal de la
  conversation (`~/.claude/projects/<projet>/<session>.jsonl`) contient des lignes
  `{"type": "file-history-snapshot", "messageId": …, "snapshot": {"trackedFileBackups":
  {<chemin>: {"backupFileName": "<hash>@v<n>", "version": n, …}}}}` ; les copies sont dans
  `~/.claude/file-history/<session>/<backupFileName>`.
- Volet (bouton dans la barre de l'onglet de session, ou entrée du menu) : liste des
  fichiers modifiés par Claude dans la conversation, avec le diff cumulé (état avant la
  conversation contre état actuel).
- **Annuler ce fichier** : remet le fichier dans son état d'avant la conversation, après
  confirmation.
- **Revenir à avant ce message** (menu d'un message de l'utilisateur dans le fil) : remet
  tous les fichiers suivis dans leur état d'avant ce message, après confirmation qui liste
  les fichiers touchés. Un fichier créé par Claude après ce point est supprimé. La
  conversation n'est pas raccourcie.
- Le format n'est pas documenté par Anthropic : module `ccs_app/file_history.py` isolé,
  tests sur un jeu de données construit à la main, contrôle dans `ccs doctor` (format lu
  ou non). Si le format n'est pas reconnu, le volet le dit et n'offre aucun retour en
  arrière (jamais d'écriture approximative).
- Une modification de Charles faite après le message (fichier différent de la dernière
  copie connue et de la version actuelle attendue) est signalée dans la confirmation.

## Chantier 3 — Le chat

- **Chercher dans le fil** : Ctrl+F ouvre une barre au-dessus du fil ; cherche sans
  accents ni majuscules dans les messages et les cartes, y compris la partie élaguée
  (relue depuis le journal, comme « Afficher ») ; flèches pour aller au résultat
  suivant ou précédent, résultat mis en évidence.
- **Messages enregistrés** : communs dans `~/.claude-accounts/messages.json`, d'un
  projet dans `<projet>/.ccs/messages.json`. Proposés dans `/` sous « Mes messages » et
  dans un menu ☆ de la saisie ; ajout, modification, suppression depuis ce menu.
- **Compacter** : bouton dans l'alerte de contexte lourd (`context_alert.py`) qui envoie
  `/compact`. Le gain affiché est une estimation (taille du contexte avant, rapport
  moyen observé après) et dit qu'il l'est.
- **`!commande`** : un message qui commence par `!` lance la commande dans le dossier du
  projet (hors de l'interface, avec arrêt possible) ; la sortie s'affiche en carte. Comme
  dans Claude Code, la commande et sa sortie partent avec le message suivant pour que
  Claude les voie. Sortie tronquée au-delà d'une limite raisonnable, avec la mention.

## Chantier 4 — Répondre depuis le téléphone

- Quand une autorisation attend (`ChatEngine` en état `permission`) et que les
  notifications du téléphone sont actives, la notification ntfy porte deux boutons
  **Autoriser** / **Refuser** (actions `http` de ntfy) qui publient la réponse sur un
  **sujet de réponse secret**, distinct du canal de notification.
- L'interface de CCS (qui porte les chats) écoute ce sujet seulement tant qu'une
  autorisation attend, et transmet la réponse par `ChatEngine.answer`.
- Sécurité : chaque demande a un jeton aléatoire à usage unique, valable 10 minutes, lié à
  la demande précise ; une réponse sans jeton valide est ignorée et journalisée. Le sujet
  de réponse est tiré au hasard comme le canal. Une réponse arrivée après que la demande a
  été traitée sur le PC est ignorée.
- Contenu (réglage `phone.show_content`) :
  - par défaut, la notification ne montre que le type et le projet (« Commande dans
    CCS », « Modification de fichier dans CCS ») : rien du contenu ne sort du PC ;
  - si Charles active le réglage, elle montre la commande ou le fichier exact. Les
    Réglages conseillent alors un serveur ntfy personnel (le contenu passe en clair par le
    serveur).
- Le serveur reste celui du réglage existant (`phone.py`, `ntfy.sh` par défaut).

## Documentation et release

README (page Git, tâches, changements, chat, téléphone), guide, architecture, pages
man, CHANGELOG, site ; release mineure 0.12.0 (nouvelles fonctions compatibles),
`.deb`, release GitHub et dépôt APT, comme les phases précédentes.

## Choix faits par Claude (à vérifier par Charles)

- Messages enregistrés : emplacements `~/.claude-accounts/messages.json` et
  `<projet>/.ccs/messages.json`.
- Ctrl+F cherche aussi dans la partie élaguée du fil.
- `!commande` : sortie envoyée à Claude avec le message suivant.
- File de nuit : pas de bandeau, signalement dans le résumé et la notification.
- git flow en plus de GiGit, message de commit proposé sans appel à Claude.
- Avatars activés par défaut, comme GiGit.
