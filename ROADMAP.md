# Feuille de route — CCS

Plusieurs comptes Claude Code sur un PC Linux, comme un seul. Détails de chaque
version : `CHANGELOG.md` ; conceptions et plans : `docs/superpowers/`.

## Phase 1 — Multi-comptes et usage (0.1.0) ✅

- [x] `ccs` : profils, bascule atomique, sauvegarde du jeton renouvelé
- [x] Usage de tous les comptes sans reconnexion
- [x] Prévisions, rythme hebdomadaire, capacité, meilleur compte
- [x] Bascule automatique à 98 % avec garde-fous
- [x] Alertes bureau, warm-up planifié, analyse des journaux
- [x] Application « Comptes Claude », indicateur, service `ccs-daemon`
- [x] Paquet Debian, README, licence MIT

## Phase 2 — Orchestrateur (0.2.0 → 0.2.1) ✅

- [x] Enchaînement et décalage des fenêtres de 5 h pendant une plage horaire
- [x] Quota qui expire d'abord, réserve hebdomadaire
- [x] `ccs plan`, `ccs orch`, onglet Planning
- [x] Fenêtres à 0 % reconnues, décalage sur les démarrages réels
- [x] Erreurs 429 tolérées, relance du service après mise à jour

## Phase 3 — Sessions et intégration Claude Code (0.3.0) ✅

- [x] Sessions ouvertes : état, consommation, reprise, terminal, terminer
- [x] Notifications « a terminé » / « attend ta réponse »
- [x] `ccs integrate` : ligne d'état et bascule après blocage (hook `StopFailure`)
- [x] Boutons « Basculer sur … » dans les notifications
- [x] Icône jauge et menu d'informations

## Correctif 0.3.1 — jetons vides recopiés dans un profil

- [x] Tests qui reproduisent le bug (bascule avec jetons vivants vides, profil sans jeton, message)
- [x] `ccs` : un jeton vide compte comme « non connecté »
- [x] `ccs use` refuse d'installer un profil sans jeton
- [x] Message « connexion perdue » avec la marche à suivre pour reconnecter
- [x] Suite de tests au vert
- [x] Version 0.3.1 (changelogs, pages man)
- [x] Publication : hotfix terminé, `main`, `develop` et le tag poussés

## Correctifs suivants — orchestrateur, `ccs next`, libellé hebdomadaire

- [x] Orchestrateur : premier démarrage du matin calé sur les démarrages réels, pas sur une grille fixe depuis le début de plage
- [x] `ccs next` : sauter les profils dont la connexion est perdue
- [x] Libellé lisible pour les limites hebdomadaires par modèle (« Semaine · Fable » au lieu des données brutes)
- [x] Fusion des trois corrections dans `develop`, suite de tests au vert
- [x] Release correctif 0.3.2 (genre choisi par l'utilisateur), `main`, `develop` et le tag poussés
- [x] Paquet `.deb` construit pour l'installation (`dist/ccs_0.3.2_all.deb`)

## Phase 4 — Propositions pour 0.4.0 (à choisir)

Recommandées :
- [x] `ccs doctor` : bilan de santé (service, version, extension, intégration, connexions) avec la commande qui corrige → Phase 7
- [x] Prévision de fin de semaine par compte, alerte 2 jours avant → Phase 7
- [x] Mode pause (bascule auto et orchestrateur suspendus 1 h / 4 h / jusqu'à demain) → Phase 7
- [x] Avertissement de nouvelle version et relance automatique de l'icône → Phase 7
- [x] Conseiller de formule (2–3 Pro ou Max) avec équivalent en dollars → Phase 8

Autres :
- [x] Conseil de modèle près des limites (Opus → Sonnet) → Phase 8
- [x] Bilan de la semaine → Phase 8
- [x] Raccourci clavier global → Phase 8
- [x] Rappel quand une session attend depuis plus de 10 min → Phase 7
- [x] Journal lisible des bascules dans l'application → Phase 8
- [x] Compte par projet → Phase 8

## Phase 5 — Historique des conversations (0.4.0) ✅

Toutes les conversations Claude Code du PC, comme la liste « Past conversations »
de l'extension VS Code, et leur reprise en un clic.

- [x] `conversations` : index de `~/.claude/projects/*/*.jsonl` (titre `custom-title` > `ai-title` > première demande, projet, origine VS Code ou terminal, branche, nombre de demandes, dates), cache incrémental pour ne relire que les octets ajoutés
- [x] Recherche (titre, demandes, projet) et filtres (projet, origine), regroupement par date
- [x] Reprise dans VS Code (`vscode://anthropic.claude-code/open?session=…` après ouverture du dossier) ou dans un terminal (`claude --resume`), copie de la commande ; refus si le dossier a disparu ou si la conversation est déjà ouverte
- [x] Projets déplacés : dossier du même nom proposé (historique, puis HOME), confirmation, copie du journal dans le nouveau dossier (`relocate`)
- [x] Onglet « Conversations » de l'application (recherche, filtres, groupes par date, boutons de reprise) et lien depuis l'onglet Sessions
- [x] `claude-accounts conversations` / `ccs conv` (liste, recherche) et `claude-accounts resume` / `ccs resume` (reprise)
- [x] Tests unitaires, suite au vert
- [x] Documentation : README, `docs/utilisation.md`, `docs/architecture.md`, pages man, CHANGELOG
- [x] Release mineure 0.4.0 (genre choisi par l'utilisateur), `main`, `develop` et le tag poussés
- [x] Paquet `.deb` construit pour l'installation (`dist/ccs_0.4.0_all.deb`)

## Phase 6 — Terminal intégré (0.5.0) ✅

Les sessions Claude Code s'ouvrent dans la fenêtre de l'application, dans des
onglets de terminal, au lieu d'une fenêtre de terminal séparée.

- [x] `terminal` : commande et environnement de lancement (claude, `claude --resume`, shell), choix intégré ou externe, textes de fin, sans GTK (tests)
- [x] Terminal intégré VTE (GTK4) : onglets, copier/coller, liens Ctrl+clic, défilement arrière, police et couleurs du système, focus
- [x] Indicateur d'activité des onglets (travaille, attend ta réponse, arrêtée), bandeau de fin avec « Reprendre » et « Fermer »
- [x] Confirmation à la fermeture d'un onglet ou de la fenêtre quand claude tourne encore
- [x] Onglet Sessions : reprise, nouvelle session et « Terminal ici » dans l'application, terminal externe en option, « Afficher » pour une session déjà ouverte dans l'application
- [x] Onglet Conversations : reprise dans l'application par défaut, terminal externe dans le menu « … », « Afficher »
- [x] Repli sans VTE : terminal externe comme avant, message pour installer `gir1.2-vte-3.91`
- [x] Renommer une conversation (ligne `custom-title` ajoutée au journal) : onglets Sessions et Conversations, onglets du terminal, `ccs title`
- [x] Paquet : dépendance `gir1.2-vte-3.91`
- [x] Essais réels dans une copie de développement (terminal intégré, repli sans VTE)
- [x] Documentation : README, `docs/utilisation.md`, `docs/architecture.md`, pages man, CHANGELOG
- [x] Suite de tests au vert, feature terminée et `develop` poussée

## Phase 7 — Fonctions de la 0.5.0

Service et alertes :
- [x] Prévision de fin de semaine par compte, alerte 2 jours avant
- [x] Mode pause (bascule auto et orchestrateur suspendus 1 h / 4 h / jusqu'à demain)
- [x] Rappel quand une session attend depuis plus de 10 min
- [x] Avertissement de nouvelle version et relance automatique de l'icône

Lecture et outils :
- [x] `ccs doctor` : bilan de santé avec la commande qui corrige
- [x] Aperçu d'une conversation sans la reprendre, export Markdown
- [x] Coût par conversation (tokens, équivalent en dollars)
- [x] Nouvelle session avancée (dossier, compte, modèle, mode de permissions)

Terminal intégré, suite :
- [x] Reprise automatique après une limite (bascule puis « continue » dans l'onglet)
- [x] Notification cliquable qui ouvre l'onglet de la session, badge des sessions en attente
- [x] Onglets rouverts au redémarrage de l'application
- [x] Deux sessions côte à côte
- [x] Messages en attente envoyés quand la session est libre

Documentation et release :
- [x] Documentation (README, guide, architecture, pages man, CHANGELOG)
- [x] Release mineure 0.5.0 (genre choisi par Charles), `main`, `develop` et le tag poussés
- [x] Paquet `.deb` construit pour l'installation (`dist/ccs_0.5.0_all.deb`)

## Phase 8 — Conseils, journal et raccourcis (0.6.0)

Priorité — à faire immédiatement :
- [x] Un seul onglet « Sessions » qui réunit les sessions ouvertes et l'historique des conversations (remplace les onglets Sessions et Conversations)
  - [x] Organisation : projets à gauche (avec sessions ouvertes et nombre de conversations), à droite les sessions ouvertes du projet puis ses conversations groupées par date ; recherche et filtres communs
  - [x] Fusion des deux pages sans perte : reprise, aperçu, coût, renommage, compte du projet, badge des sessions en attente, notifications cliquables, `--page sessions`
  - [x] Tests et essais réels

Conseils :
- [x] Conseiller de formule (2–3 Pro ou Max) avec équivalent en dollars
- [x] Conseil de modèle près des limites (Opus → Sonnet)
- [x] Bilan de la semaine

Journal et projets :
- [x] Journal lisible des bascules dans l'application
- [x] Compte par projet

Bureau :
- [x] Raccourcis clavier globaux

Raccordement, documentation et release :
- [x] Commandes `ccs` (`formule`, `semaine`, `journal`, `projet`, `raccourcis`) et Réglages de l'application
- [x] Documentation (README, guide, architecture, pages man, CHANGELOG)
- [x] Release mineure 0.6.0 (genre choisi par Charles), `main`, `develop` et le tag poussés
- [x] Paquet `.deb` construit (`dist/ccs_0.6.0_all.deb`) et release GitHub v0.6.0

Releases GitHub manquantes :
- [x] Releases GitHub 0.3.1, 0.3.2 et 0.4.0, avec leurs `.deb` reconstruits depuis les tags

## Phase 9 — Points mineurs reportés (correctif)

- [x] Réveil précis au début de la plage horaire
- [x] Réglages invalides édités à la main : valeurs par défaut au lieu d'un échec
- [x] Heure locale exacte (changement d'heure) pour les plages couvrant 2 h – 3 h
- [x] `ccs best` : ignorer les comptes en erreur
- [x] Moniteur de sessions créé même si `~/.claude/sessions` apparaît après le démarrage
- [x] Suite de tests au vert, CHANGELOG et documentation
- [x] Release correctif 0.6.1 (genre choisi par Charles), `main`, `develop` et le tag poussés
- [x] Paquet `.deb` construit (`dist/ccs_0.6.1_all.deb`) et release GitHub v0.6.1

## Phase 10 — Confort et vue d'ensemble (0.7.0)

- [x] Mise à jour en un clic : téléchargement du `.deb` de la release GitHub, vérification SHA-256 et du paquet, installation après mot de passe
- [x] Ne pas déranger : plages horaires sans notifications, silence temporaire, exception « attend ta réponse », résumé à la fin
- [x] Meilleur moment pour une grosse tâche : créneau où les comptes offriront le plus de quota d'affilée (onglet Planning)
- [x] Sessions dans le menu de l'icône : afficher une session ouverte dans son onglet de l'application
- [x] Rapport mensuel : coût équivalent API, projets, modèles, évolution d'un mois à l'autre (onglet Analyse, notification)
- [x] Commandes `ccs` (`mise-a-jour`, `silence`, `moment`, `mois`), Réglages, menu de l'icône
- [x] Documentation (README, guide, architecture, pages man, CHANGELOG)
- [x] Dépôt APT signé sur GitHub Pages (`https://mawena.github.io/CCS/apt`) sur le modèle de Gagarine : clé dédiée, `make apt`, page d'accueil, source deb822 et clé installées par le paquet
- [x] Release mineure 0.7.0 (recommandée : nouvelles fonctions compatibles), `main`, `develop` et le tag poussés
- [x] Paquet `.deb` construit, release GitHub v0.7.0 et première publication dans le dépôt APT (vérifiée par `apt-get update`)

## Phase 11 — Travailler sans toi, ne rien perdre, économiser (0.8.0)

Conception : `docs/superpowers/specs/2026-11-11-phase-11-design.md`.

Travailler pendant que tu n'es pas là :
- [x] File de tâches Claude (`ccs tache`, onglet Planning) : lancement sans fenêtre au bon moment (quota libre, heure, nuit), par la file Gagarine, bascule et relance après une limite
- [x] Notifications sur le téléphone (ntfy, optionnel) : session en attente, tâche finie, bascule, comptes épuisés ; projet et état seulement

Ne rien perdre :
- [x] Archive des conversations avant leur effacement par Claude Code, toujours visibles et reprenables dans l'onglet Sessions
- [x] Fiche « où j'en étais » (`ccs fiche`, aperçu) : dernière demande, fichiers modifiés, tâches, branche, sans appel à Claude
- [x] Sauvegarde chiffrée des comptes et réglages (`ccs sauvegarde`, `ccs restaurer`, gpg)

Économiser la machine et le quota :
- [x] Mémoire des sessions : RAM et inactivité par session, fermeture des sessions inactives (jamais automatique)
- [x] Alerte de contexte lourd (seuil réglable, coût d'un message, badge et ligne d'état)
- [x] Budget par projet (`ccs budget`, onglet Analyse), alertes à 80 % et 100 %

Raccordement, documentation et release :
- [x] Service et commandes : `daemon`, `settings`, `cli`, `bin/ccs`, `doctor`, paquet
- [x] Application : Réglages, Planning, Analyse, Sessions
- [x] Documentation (README, guide, architecture, pages man, CHANGELOG)
- [x] Release mineure 0.8.0 (recommandée : nouvelles fonctions compatibles), `main`, `develop` et le tag poussés
- [x] Paquet `.deb`, release GitHub v0.8.0 et publication dans le dépôt APT (vérifiée par `apt-get update`)

## Phase 12 — CCS façon VS Code : chat, fichiers, feuille de route, nouveau design (0.10.0)

Conception : `docs/superpowers/specs/2026-11-12-phase-12-design.md`.

Déjà fait :
- [x] L'application s'appelle « CCS » partout au lieu de « Comptes Claude » (publié en 0.9.0)
- [x] Conception validée sur maquettes : chat, fichiers, feuille de route, page Projets, navigation

Le chat :
- [x] Essai réel du protocole de Claude Code (stream-json, autorisations, `/effort`, ultracode), avec l'accord de Charles (12/11, 5 messages Haiku)
- [x] Moteur du chat sans GTK et faux `claude` pour les tests
- [x] Chat graphique : bulles, Markdown, cartes d'actions, autorisations, liste de tâches, saisie avec `@`, `/` et images
- [x] Barre cliquable : modèle, effort, ultracode, droits ; contexte et compte
- [x] Fonctions des terminaux reprises : file de messages, vue partagée, réouverture, bascule sur limite, alertes, « Ouvrir dans un terminal »

Les fichiers :
- [x] Panneau Fichiers : arbre avec marques git, dispositions B (par défaut) et A, panneaux redimensionnables
- [x] Fichier ouvert : coloration, aperçu Markdown, édition, diff des modifications de Claude

Feuille de route et projets :
- [x] Feuille de route dans l'onglet de session : phases, cases cliquables, case cochée mise en avant
- [x] Page Projets : cartes des projets, frise des versions, tâches cochées par jour (retirée à l'essai le 12/11 : sans utilité)

Le design :
- [x] Navigation en 3 onglets (Accueil, Sessions, Analyse), Réglages dans le menu, anciens noms de page acceptés
- [x] Nouveau design : couleur par compte, cartes, écrans vides, clair et sombre

Retours de l'essai de Charles (12/11) :
- [x] Envoi direct pendant que Claude travaille, « Envoyer maintenant », « Tout autoriser », saisie lisible en sombre, défilement et « Nouveaux messages »
- [x] Sous-agents en pastilles et leurs autorisations, questions inconnues de la CLI, pas de mise en veille pendant un sous-agent
- [x] Feuille de route qui suit le projet de la conversation, « Dossier du projet… », conversations reliées à leur projet
- [x] Fichiers joints, bilan de chaque réponse, bouton Copier, longs messages repliés, actions regroupées dans le fil
- [x] Bandeau « Relancer » après une mise à jour, Accueil redessiné, page Projets retirée

Documentation et release :
- [x] Documentation (README, guide, architecture, pages man, CHANGELOG, site)
- [x] Release mineure 0.10.0, `.deb`, release GitHub et dépôt APT (12/11)

## Correctif 0.10.1 — Accueil lisible, dossier des conversations, documentation

- [x] Accueil : comptes côte à côte, deux jauges et une ligne d'état par carte, « Détails » repliable, texte lisible (plus teinté de la couleur du compte), planning resserré
- [x] Sous-agents finis retirés de la barre (avis de fin des sous-agents de fond), erreurs d'une fenêtre relancée gardées dans le journal
- [x] Chat proche de VS Code : tâches épinglées, réponses sans bulle, Maj+Tab pour les droits, 1/2/3 pour les autorisations
- [x] Interface plus légère : rendu de la fin seulement pendant l'écriture, détail des actions au dépliage, Accueil reconstruit seulement s'il est affiché
- [x] Questions de Claude (AskUserQuestion) affichées et répondues, « ? » réservé aux vraies demandes, fin des sous-agents de fond lue entrée par entrée dans le journal
- [x] Dossier d'une conversation : celui où elle est rangée (ou reliée), plus le premier `cwd` du journal (aperçu, archive, projets récents)
- [x] Documentation et textes : plus d'« onglet Planning / Comptes / Historique / Réglages » (onglets disparus en 0.10.0)
- [x] Release correctif 0.10.1, `.deb`, release GitHub et dépôt APT

## Fluidité (après 0.10.1)

- [x] Listes Markdown courtes en un seul label
- [x] Fil borné dans les longues sessions (élagage + « Afficher » depuis le journal), cycles de widgets cassés, mémoire rendue au système
- [x] Essai réel par Charles, puis release correctif 0.10.2 (`.deb`, release GitHub, dépôt APT)

## Phase 13 — CCS sur le VPS : serveur, web, terminal, bureau connecté (0.11.0)

Demandée le 15/11, prioritaire. Piloter CCS depuis Internet (`https://ccs.mawena.cloud`,
surtout depuis le téléphone), depuis un terminal sur le VPS, et depuis l'application GTK du
bureau. Conception : `docs/superpowers/specs/2026-11-15-phase-13-vps-design.md`.
Plan détaillé : `docs/superpowers/plans/2026-11-15-phase-13-vps.md`.
Choix de Charles : connexion par les comptes Ubuntu seulement (PAM, groupe `ccs`, `root` refusé),
double authentification obligatoire, architecture sur le modèle de Cockpit, mise en ligne par lnmp.

Briques du serveur :
- [x] 1. Protocole JSON par lignes sur socket Unix
- [x] 2. Codes TOTP et limite des essais (5 échecs en 15 min → 15 min de refus)
- [x] 3. Sessions (12 h sans activité, 7 jours au plus), appareils retenus 30 jours, jetons d'application
- [x] 4. Vérification des comptes Ubuntu par PAM, groupe `ccs`, `root` refusé
- [x] 5. Service `ccs-auth` : connexion, inscription du code par QR code, tickets des ponts

Le pont (un par utilisateur) :
- [x] 6. Serveur du pont, ticket, comptes Claude et réglages
- [x] 7. Chats dans le pont, rejouables après une coupure, partagés entre appareils
- [x] 8. Projets, fichiers, feuille de route, analyse et tâches (chemins limités au dossier de l'utilisateur)
- [x] 9. Terminaux shell
- [x] 10. Service de fond lancé par le pont, Claude Code installé s'il manque

Serveur web et version web :
- [x] 11. Service `ccs-web` (127.0.0.1:8420) : connexion, relais WebSocket, en-têtes de sécurité
- [x] 12. Version web : charpente, connexion avec code, navigation responsive, installable sur le téléphone
- [x] 13. Accueil, Analyse, Réglages (dont Appareils)
- [x] 14. Sessions et chat
- [x] 15. Fichiers, Feuille de route, terminal (xterm.js)

Terminal et bureau :
- [x] 16. Client commun (local ou par le web) et appairage (`ccs serveur ajouter`)
- [x] 17. `ccs tui` plein écran
- [x] 18. Bureau : Réglages → Serveurs
- [x] 19. Bureau : projets et chats du serveur dans l'application, shell distant

Paquets, contrôles, documentation, release :
- [x] 20. Trois paquets (`ccs`, `ccs-bureau`, `ccs-serveur`) et le métapaquet `ccs-all` qui les installe tous, services systemd, PAM, installation de Claude Code
- [x] 21. `ccs doctor` pour le serveur
- [x] 22. Revue de sécurité
- [x] 23. Documentation (README, guide, architecture, man, CHANGELOG, site)
- [x] 24. Essai réel sur le VPS (DNS et lnmp par Charles)
- [x] 25. Release mineure 0.11.0, quatre `.deb`, release GitHub et dépôt APT, mise à jour du VPS

## Phase 14 — Travailler sans quitter CCS (0.12.0)

Toutes les propositions retenues le 14/11, conception validée le 15/11. Passée en phase 14 le 15/11 : la partie VPS est prioritaire. Travail sur la branche `feature/phase14`.
Le 15/11, après l'essai sur le VPS : la version web passe au niveau du bureau (tâches 18 à 30) ; ce
qui concernait le VPS a été fait en phase 13 (0.11.0).
Conception : `docs/superpowers/specs/2026-11-15-phase-13-design.md`.
Plan détaillé (tests et interfaces de chaque tâche) : `docs/superpowers/plans/2026-11-15-phase-13.md`.

Page Git (inspirée de GiGit) :
- [x] 1. Lecture d'un dépôt : log par pages, références, branche et avance/retard, état, diff (`git_repo`)
- [x] 2. Écritures : indexation par fichier, bloc et ligne, commit et amend, annulation, `.gitignore`, fetch / pull / push (forcé avec garde), git flow, message proposé
- [x] 3. Disposition du graphe façon ungit, portée de GiGit (10 000 commits en moins de 200 ms)
- [x] 4. Avatars des auteurs en cache, réglages `git.*` et `phone.show_content`
- [x] 5. Onglet portant un widget quelconque dans la zone de droite
- [x] 6. Graphe des commits en deux densités (compact, cartes), chargé par pages
- [x] 7. Détail d'un commit, changements en cours, indexation par ligne, Commit et Ctrl+Entrée
- [x] 8. Page Git dans le panneau de gauche : dispositions A, B et C, bandeau d'erreur, fetch automatique, rafraîchissement

Le travail de Claude :
- [x] 9. « Faire une tâche » de la feuille de route : chat ou file de nuit, bandeau « Tâche finie ? » si Claude n'a pas coché
- [x] 10. Lecture des copies de Claude Code (`file_history`) : changements, plan de retour en arrière
- [x] 11. Volet « Changements de la session », annuler un fichier, revenir avant un message, contrôle `ccs doctor`

Le chat :
- [x] 12. Chercher dans le fil (Ctrl+F)
- [x] 13. Messages enregistrés, communs ou par projet
- [x] 14. Bouton « Compacter » dans l'alerte de contexte lourd
- [x] 15. Commande `!` lancée dans le dossier du projet

Le téléphone :
- [x] 16. Réponses signées et à usage unique (`phone_reply`)
- [x] 17. Autoriser ou Refuser depuis la notification, réglage « Montrer la commande »

La version web au téléphone (choisie le 15/11 : ergonomie, fonctions du bureau et phase 14 au web) :
- [x] 18. Socle du web : toasts et cartes de confirmation à la place d'`alert()` et `confirm()`, chargements et états vides, adresses par chat (`#/sessions/<chat>`, bouton Retour du téléphone), pastille « attend ta réponse », une feuille de style par zone
- [x] 19. Chat au téléphone : plein écran, titre lisible, modèle / effort / droits repliés, boutons Fichiers, Feuille de route et Git avec libellés, saisie jamais perdue (brouillon par chat, texte remis si l'envoi échoue)
- [x] 20. Sessions : section « En cours » avec l'état de chaque chat, écran Projet (conversations, fichiers, feuille de route, Git, nouveau chat, terminal)
- [x] 21. Terminal au téléphone : barre de touches (Échap, Tab, Ctrl, flèches, `|`, `~`), coller
- [x] 22. Nouvelle session complète : dossiers récents et dépôts du disque, choix du compte, du modèle et des droits
- [x] 23. Conversations : voir plus, aperçu sans ouvrir, renommer, coût
- [x] 24. Chat : modifications de Claude en diff lisible, fichier cité ouvert à la ligne, complétion `@fichier` et `/commandes`
- [x] 25. Fichiers : aperçu des images, recherche, ouverture à une ligne ; feuille de route sans perte du défilement
- [x] 26. Accueil : rythme et prévision des comptes, bilan de santé, tâches de nuit (nouvelle tâche, journal, reprise, suppression)
- [x] 27. Réglages : téléphone (ntfy, QR code, essai), réglages du bureau qui manquent (dont `git.*` et « Montrer la commande ») ; Analyse sur d'autres périodes
- [x] 28. Phase 14 au web, chat : messages enregistrés, « Compacter », commande `!`, chercher dans le fil
- [x] 29. Phase 14 au web : volet « Changements de la session » et « Faire une tâche » de la feuille de route
- [x] 30. Phase 14 au web : Git (état, diff, indexation, commit, fetch / pull / push)

Fin de phase :
- [x] 31. Documentation (README, guide, architecture, man, CHANGELOG, site)
- [x] 32. Essai réel par Charles (bureau et VPS) et corrections
- [x] 33. Release mineure 0.12.0, `.deb`, release GitHub et dépôt APT

## Correctifs 0.12.1 à 0.12.6 — essais réels sur le VPS

- [x] Changements et retour en arrière : chemins relatifs (`realParentDir`) et copie `@v1` non citée de Claude Code 2.1.3xx
- [x] Web : fil et saisie du chat dans une colonne centrée sur grand écran
- [x] Web : boutons radio des questions à leur taille, libellés à gauche
- [x] Web : actions qui se suivent regroupées, chat compact au téléphone ; message envoyé d'un appareil visible sur tous (0.12.1)
- [x] Surveillance des sessions sans bus D-Bus (serveur sans bureau) (0.12.1)
- [x] Web : le fil suit les nouveaux messages, « Claude travaille… » au-dessus de la saisie, bouton Copier (0.12.2, 0.12.4)
- [x] Web : feuille de route dans l'ordre du fichier, sections redimensionnables, liste masquable (0.12.3)
- [x] Web au téléphone : une seule barre en haut, saisie plus large (0.12.5)
- [x] Web : installer CCS comme une application (Chrome, iPhone) (0.12.6)
- [x] Releases 0.12.1 à 0.12.6 (paquets construits sur le VPS, releases GitHub)
- [x] Dépôt APT signé à jour (`make apt` depuis le PC de Charles)
- [x] Essais de Charles : page Git du web, Autoriser / Refuser (web et ntfy)

## Phase 15 — Le serveur depuis le bureau, comme Remote Control (0.13.0 : pont et web ; 0.14.0 : bureau)

Demandée le 15/11. Depuis l'application de bureau des postes de Charles : voir les chats qui
tournent sur le VPS et les piloter en direct ; ajouter et supprimer projets et sessions.
Choix de Charles : session supprimée → corbeille CCS restaurable 30 jours ; projet supprimé →
seulement retiré de la liste (dossier et conversations gardés) ; projet ajouté → dossier
existant ou nouveau (git init en option) ; au bureau et au web.

Pont :
- [x] 1. `projects.add` (dossier existant ou créé, git init en option, chemins permis seulement) et `projects.remove` (retiré de la liste, rien d'effacé)
- [x] 2. Liste des projets : projets ajoutés sans conversation inclus, projets retirés exclus
- [x] 3. `conversation.trash` (refusé si le chat tourne), `conversation.trash_list`, `conversation.restore`, purge après 30 jours par le service de fond

Bureau (page Sessions) :
- [x] 4. Page Sessions par machine : « Ce poste » puis chaque serveur appairé, chacun avec ses sessions en cours, ses projets et ses conversations (état de connexion visible, serveur injoignable sans bloquer le reste)
- [x] 5. Rejoindre un chat qui tourne sur un serveur (`chat.list`) : fil rejoué et suivi en direct, demandes de permission comprises ; un onglet distant se branche dès l'ouverture
- [x] 6. Ajouter un projet, retirer un projet, supprimer une conversation, corbeille, sur ce poste comme sur un serveur
- [x] 6b. Session distante : panneau de gauche (Fichiers, Feuille de route, Git) comme pour une session locale

Web :
- [x] 7. Ajouter un projet (dossier existant ou nouveau, git init, `~` accepté), le retirer de la liste, supprimer une conversation (corbeille, « Annuler »), Corbeille avec Restaurer

Fin de phase :
- [x] 8a. Documentation de la partie web (README, CHANGELOG) et release 0.13.0
- [x] 8. Documentation de la partie bureau (README, guide, CHANGELOG)
- [x] 9. Essai réel par Charles depuis son PC
- [x] 10. Release mineure 0.14.0 (bureau)

## Phase 16 — Compactage automatique (0.15.0)

Quand le contexte d'un chat dépasse le seuil du contexte lourd, CCS envoie `/compact` tout seul, au lieu de seulement proposer le bouton « Compacter ». Désactivé par défaut.

- [x] 1. Réglage `context_alert.auto_compact` (faux par défaut), validé dans `settings.py`
- [x] 2. Décision commune dans `context_alert.py` : compacter seulement entre deux tours (Claude au repos, aucune demande de permission en attente), une seule fois par dépassement, jamais deux fois de suite si le contexte ne redescend pas
- [x] 3. Chats du serveur (`server/bridge_chat.py`) : envoi automatique, même sans navigateur ouvert
- [x] 4. Chat du bureau : même comportement pour les chats locaux
- [x] 5. Note dans le fil (« Compactage automatique : contexte de N jetons ») à la place de l'alerte avec bouton
- [x] 6. Case « Compacter automatiquement » dans les réglages du web et du bureau
- [x] 7. Tests des modules touchés
- [x] 8. Documentation (README, CHANGELOG) et release mineure 0.15.0, dépôt APT compris

## Phase 17 — Répondre en citant un message (0.16.0)

Comme sur WhatsApp : on choisit un message du chat (le sien ou celui de Claude), il s'affiche en citation au-dessus de la saisie, et Claude le reçoit avec la réponse. Si du texte est sélectionné dans le message, seule la sélection est citée.

- [x] 1. Format commun de la citation (`chat_quote.py`, `web/chat-quote.js`) : composer le message envoyé (citation en bloc Markdown, puis la réponse), la reconnaître à la relecture, raccourcir un long message cité
- [x] 2. Web : action « Répondre » sur chaque message, bandeau de citation au-dessus de la saisie (avec « Annuler »), bulle qui montre la citation
- [x] 3. Bureau : bouton « Répondre » au survol d'une réponse, entrée « Répondre » dans le menu d'une bulle, bandeau au-dessus de la saisie, bulle qui montre la citation
- [x] 4. Conversations rouvertes : la citation est reconnue dans l'historique (web, bureau) et dans l'aperçu d'une conversation
- [x] 5. Tests des modules touchés
- [x] 6. Documentation (README, docs, CHANGELOG) et release mineure 0.16.0, dépôt APT compris

## Correctif 0.16.1 — bilan de santé depuis le web

- [x] Le bilan lancé depuis le web disait le service « hors de systemd » : le pont (service système) n'avait pas `XDG_RUNTIME_DIR` ; `doctor.user_bus_env` le remet, `doctor.in_service` vérifie l'unité du processus en secours
- [x] Release corrective 0.16.1, dépôt APT compris

## Phase 18 — Étiquettes sur les messages (0.17.0)

Poser un ou plusieurs mots-clés sur un message (« important », « à revoir »…) et retrouver ensuite les messages par étiquette.

- [x] 1. Identifiant stable d'un message, le même en direct et à la relecture du journal (réponse de Claude : identifiant de la réponse ; message de l'utilisateur : identifiant de sa ligne du journal)
- [x] 2. Stockage des étiquettes (`message_tags.py`) : par conversation, avec un extrait du message pour le retrouver sans relire le journal
- [x] 3. Pont : lire, poser et retirer les étiquettes d'un chat du serveur ; changement diffusé aux autres appareils
- [x] 4. Web : action « Étiqueter » sur chaque message, étiquettes affichées sous le message, volet « Étiquettes » (liste par étiquette, saut au message)
- [x] 5. Bureau : mêmes fonctions (chat local et chat d'un serveur)
- [x] 6. Tests des modules touchés
- [x] 7. Documentation (README, docs, CHANGELOG) et release mineure 0.17.0, dépôt APT compris

## Correctif 0.17.1 — le fil du chat web suit le bas

- [x] Le fil ne descendait plus pendant la réponse : le suivi se décrochait sur tout événement de défilement ; seul un geste vers le haut l'arrête (`scrolled`, `restick`, observateurs de taille et de contenu)
- [x] Release corrective 0.17.1, dépôt APT compris

## Bouton « Aller en bas » du chat web (0.18.0)

- [x] Bouton flottant en bas à droite du fil, visible seulement quand on est remonté ; un appui ramène en bas et reprend le suivi (`downBtn`, `offerDown`, `.thread-wrap`)
- [x] Tests, documentation, release mineure 0.18.0, dépôt APT compris

## Phase 19 — Gérer et télécharger les fichiers depuis le web (0.19.0)

- [x] 1. Pont : `bridge_files` (`files.download`, `files.upload` par morceaux, `files.mkdir`, `files.create`, `files.rename`, `files.delete`, `files.info`), chemins confinés, racines protégées
- [x] 2. Web : `files-manage.js` (transferts, feuilles de saisie et d'actions), barre « + Fichier / + Dossier / Envoyer », bouton « ⋯ » par entrée, bouton « ⤓ » du fichier ouvert
- [x] 3. Tests (pont et web), documentation, release mineure 0.19.0, dépôt APT compris
- [x] 3 bis. 0.19.1 : bouton « ⤓ » direct sur chaque fichier de l'arbre (le téléchargement n'était visible que dans le menu « ⋯ ») ; affichage vérifié dans Chromium sans tête
- [x] 3 ter. 0.19.2 : seuil par défaut du contexte lourd et du compactage automatique doublé (300 000 tokens)
- [x] 4. Essai réel : envoyer, télécharger, renommer, supprimer (19/11, Chromium en taille téléphone : envoi et téléchargement de 3 Mo identiques, renommer, copier, couper, coller, supprimer)
- [ ] 5. Plus tard, si utile : télécharger un dossier entier (archive), même gestion sur le bureau

## Phase 20 — Gestionnaire de fichiers du web (0.20.0)

Un cinquième onglet « Fichiers » dans la navigation du web : parcourir les dossiers permis du serveur, tout y faire, et ajouter un dossier aux projets de CCS.

- [x] 1. Pont : `files.roots` (dossiers de départ) et `files.paste` (copier ou déplacer, copie bornée à 2 Go, jamais un dossier dans lui-même)
- [x] 2. Web : écran `files-browser.js` (fil d'Ariane, choix de la racine, adresse `#/fichiers/<dossier>`), actions « Ouvrir ce dossier » et « Ajouter aux projets de CCS »
- [x] 3. Web : Copier, Couper, Coller dans le menu « ⋯ » et la barre d'outils (aussi dans le volet Fichiers d'un projet)
- [x] 4. Tests (pont et web), affichage vérifié dans Chromium sans tête en largeur téléphone
- [x] 5. Documentation et release mineure 0.20.0, dépôt APT compris
- [x] 6. Essai réel (19/11, Chromium en taille téléphone : ouvrir un dossier, fil d'Ariane, ajouter aux projets)

## Phase 20 bis — Passage au dépôt APT unique (0.20.1)

- [x] 1. Paquet `ccs` : plus de source `ccs.sources` ni de clé `ccs.gpg`, `Depends: mawena-depot`, retrait de l'ancienne source (`rm_conffile`, `debian/ccs.maintscript`)
- [x] 2. README, site (`index.html`, `installer.sh` qui lance l'installateur de https://apt.mawena.cloud), pages de manuel, architecture
- [x] 3. Release corrective 0.20.1, publiée aussi avec `mawena-depot` dans l'ancien dépôt (gardé jusqu'à mai 2027)
- [ ] 4. Mai 2027 : archiver l'ancien dépôt (page d'accueil qui renvoie au dépôt unique)

## Phase 21 — Calcul réparti par Ricochet (0.21.0 et suivantes)

Demande de Charles du 17/11/2026 : se servir de la puissance de toutes ses machines pour les travaux lancés depuis CCS. Exemple : un projet Flutter ouvert sur le VPS, où Flutter n'est pas installé, se construit sur `pc-bureau`, et le travail continue. Ensuite : répartir les tâches entre les machines pour gagner du temps et alléger le VPS.

Choix (17/11/2026, Charles : « fais les meilleurs choix ») : Ricochet 0.3.0 ouvre un **tunnel** vers le serveur SSH de la machine, et CCS fait le reste avec `ssh` et `rsync` (envois différentiels, sortie en direct, codes de retour : déjà éprouvés). Le premier plan (Ricochet lance lui-même les commandes et transporte les dossiers) est abandonné : plus de code à écrire et à sécuriser pour moins bien. Le droit reste donné machine par machine (`[tunnel]` dans l'agent, clé SSH autorisée), et chaque tunnel est dans l'audit de Ricochet.

Étape A — construire ailleurs (0.21.0)
- [x] 1. `distant.py` : liste des machines par l'API du relais (`~/.config/ricochet/client.toml`, jeton limité aux tunnels), charge, options SSH par le tunnel, réglages par machine (`~/.config/ccs/distant.toml`)
- [x] 2. `ccs distant machines` et `ccs distant lancer [--machine M] -- <commande>` : envoi du projet (sans ce que git ignore), commande dans le même sous-dossier, sortie au fil de l'eau, `--rapatrier`, code de retour
- [x] 3. Choix de la machine : celle qui a l'outil demandé, puis la moins chargée ; refus qui dit pourquoi (hors ligne, tunnel non activé, SSH refusé, outil absent)
- [x] 4. Envois suivants rapides : `rsync` ne renvoie que les fichiers changés ; les dossiers de build restent sur la machine (builds incrémentaux)
- [x] 5. Claude prévenu dans les chats de CCS (`--append-system-prompt` quand le calcul réparti est réglé)
- [x] 6. Tests, essai réel (relais et agent locaux, vrai `ssh` et `rsync`), documentation, release mineure 0.21.0
- [x] 7. Mise en place faite (jeton des tunnels, `client.toml`, `[tunnel]` et SSH sur `pc-bureau`) ; essai réel réussi le 18/11 : APK de Portail construit sur `pc-bureau` (Gradle 3 min 35) et rapatrié sur le VPS

Étape B — répartir et voir (0.31.0, puis 0.32.0)
- [x] 8. Web et bureau : page « Machines » (en ligne ou non, outils, charge, commandes en cours avec arrêt) et réglages (adresse du relais, jeton) — 0.31.0, refaite en 0.32.0 (journal, lancement, limites)
- [x] 9. Plusieurs commandes à la fois sur plusieurs machines (tests d'un côté, build de l'autre), limite par machine, file d'attente — 0.32.0
- [x] 10. Tâches de nuit et suites de tests longues envoyées à la machine la moins chargée ; le VPS garde ses services de production tranquilles — 0.32.0
- [x] 11. Arrêt propre de la commande distante quand on interrompt `ccs distant lancer` (0.25.1 : garde côté distant, essai réel sur `pc-bureau`)
- [x] 12. Tests, documentation, release mineure

Étape C — à décider après essai
- [ ] 13. Sessions Claude entières sur une autre machine (le pont de CCS lancé là-bas par le tunnel) : à étudier, demande Claude Code et un compte sur chaque machine

## Phase 22 — Sous-agents dans le chat web (0.22.0)

Sur le web, le travail des sous-agents se mélangeait au fil (cartes décalées, réponses du sous-agent affichées comme celles de Claude). Comme sur le bureau maintenant :

- [x] 1. Une pastille par sous-agent au-dessus du fil (« Conversation » + un par sous-agent au travail), barre cachée quand il n'y en a pas
- [x] 2. Une vue en lecture seule par sous-agent : ses outils et ses réponses n'apparaissent plus dans le fil
- [x] 3. Carte « Sous-agent » dans le fil : état (au travail, en arrière-plan, terminé, arrêté), bouton « Voir », consigne et résultat repliés
- [x] 4. Fin : résultat (premier plan) ou avis de fin (arrière-plan) ; un sous-agent fini quitte la barre ; retour au fil quand on envoie un message ou qu'une autorisation arrive
- [x] 5. Tests (faux DOM), documentation, release mineure 0.22.0

## Phase 23 — Mode Portier (0.23.0)

Connexion unique par Portier (https://portier.mawena.cloud) pour la version web, selon le contrat `Portier/docs/integration.md`.

- [x] 1. Clé `portier` de `/etc/ccs/web.json` (`actif`, `utilisateurs`, `url`, `deconnexion`), désactivée par défaut
- [x] 2. En-tête `X-Portier-Utilisateur` cru seulement depuis 127.0.0.1/::1 et pour un nom de la liste, en HTTP et WebSocket ; jeton d'appareil toujours prioritaire
- [x] 3. `ccs-auth` revérifie option, liste et groupe `ccs` avant de signer le ticket du pont
- [x] 4. Déconnexion renvoyée vers Portier ; bouton « Se connecter via Portier » sur la page de connexion
- [x] 5. Tests (en-tête accepté, nom absent, IP non locale, option désactivée), README, release mineure 0.23.0
- [x] 6. Par Charles : installer la 0.23.0, activer la clé `portier`, protéger le site par Portier dans nginx, ajouter CCS à `portier.toml` (vérifié le 19/11 : mode facultatif actif, en-tête forgé refusé)

## Correctif 0.23.1 — Indicateur « Claude réfléchit… » bloqué

- [x] 1. Cause relevée sur la vraie CLI : un message envoyé pendant un tour peut y être lu sans `result` à part ; le filet de 3 s le soldait aussi pendant un `/compact` en file (aucun signe de vie pendant le compactage), et le tour suivant arrivait moteur « au repos »
- [x] 2. Moteur : `status: compacting` suivi (pas de filet pendant le compactage), retour à « occupé » quand la CLI se remet au travail, repos au dernier `result`
- [x] 3. Tests (moteur, décodage, onglet de bureau : indicateur et bouton ■ éteints), release 0.23.1

## 0.24.0 — Nouvelle présentation du gestionnaire de fichiers

- [x] 1. Web : icônes par type, arbre, fil d'Ariane, barre d'outils, fichier ouvert, états vides (téléphone et bureau, clair et sombre)
- [x] 2. Bureau : icônes symboliques, en-têtes du dossier et du fichier, page d'état du dossier vide
- [x] 3. Release 0.24.0

## Correctif 0.23.2 — « Claude travaille » et sous-agents bloqués

- [x] 1. Cause relevée sur le pont en production : `command_lifecycle` après le `result` relançait le compteur d'activité, le filet ne remettait jamais au repos ; la fin des sous-agents de fond arrive en `system/task_notification`, non lu
- [x] 2. Moteur : les événements inconnus ne comptent plus comme activité ; avis de fin lu dans le flux, transmis une seule fois
- [x] 3. Tests (moteur, décodage), release 0.23.2

## Séparateur après `/clear` (0.25.0)

Après `/clear`, Claude Code repart d'une conversation vide, mais l'écran garde les anciens messages sans aucun signe : on croit que rien ne s'est passé.

- [x] 1. Détecter le changement de conversation : événement `conversation_reset` de Claude Code (relevé sur la vraie CLI), suivi d'un `Init` avec le nouvel identifiant
- [x] 2. Web et bureau : séparateur visible « Nouvelle conversation » dans le fil, les anciens messages restant lisibles (et citables) au-dessus, grisés
- [x] 3. Relecture : le web le retrouve dans les événements gardés par le pont ; le journal de la nouvelle conversation, lui, commence après `/clear` (rien à séparer)
- [x] 4. Tests des modules touchés, documentation, release 0.25.0 (avec les pastilles des sous-agents gardées sur le web)

## Phase 24 — `/clear` fiable et effacement automatique (0.26.0)

Charles (19/11/2026) : « pourquoi tu me proposes des /clear, alors que quand je le fais rien ne se passe ? » La CLI vide bien la conversation (vérifié au repos et pendant un tour) ; CCS pouvait gâcher la commande.

- [x] 1. Une commande `/…` part seule : citation et sorties `!` en attente gardées pour le message suivant (web et bureau)
- [x] 2. Web : une page restée ouverte pendant une mise à jour du serveur propose « Recharger »
- [x] 3. `ccs chat effacer` (lancé par Claude en fin de sujet) : demande au nom du jeton du chat, `/clear` envoyé au retour au repos, jamais pendant un sous-agent de fond ; consigne ajoutée aux chats
- [x] 4. Séparateur « Sujet terminé : Claude a effacé la conversation » (web et bureau) ; réglage `chat.auto_clear` (activé par défaut) dans les réglages du web et du bureau
- [x] 5. Tests des modules touchés, essai réel avec la vraie CLI (le mot à retenir est bien oublié)
- [x] 6. Application Android (`android-app/`, Flutter) : coquille de la version web (`flutter analyze` propre)
- [x] 6b. APK construit sur `pc-bureau` (une fois la mémoire libérée) et joint à la release v0.26.0 (`ccs-0.26.0.apk`)
- [x] 6c. Essayer l'APK sur le téléphone : envoi et téléchargement de fichiers, changement de serveur
- [x] 7. Documentation, release mineure 0.26.0


## Phase 25 — Application Android native (Kotlin + Jetpack Compose)

Charles (19/11/2026) : « je veux une application complète construite de bout en bout avec le langage le plus adéquat ». L'appli 0.26 n'était que la page web en plein écran. Choix : Kotlin + Jetpack Compose (langage officiel d'Android, meilleure intégration : notifications, partage, fond). Tout le périmètre du web. Elle remplace la coquille Flutter dans `android-app/` ; construite sur `pc-bureau` (SDK `~/Android`, JDK 17/21), installée sur le Pixel 4 XL par adb sans fil.

- [x] 1. Fondations : projet Gradle (Kotlin, Compose, Material 3, thème CCS clair/sombre), connexion (mot de passe + TOTP, Portier, appairage → jeton gardé chiffré), client WebSocket `/api/ws` (RPC + événements, reconnexion), navigation, icône adaptative dans la zone sûre (logo coupé sur le Pixel)
- [x] 2. Comptes et accueil : cartes des comptes, bascule, pause, bilan de santé, analyse
- [x] 3. Sessions et projets : liste, nouvelle session, renommer, corbeille, historique des conversations, comptes par projet
- [x] 4. Chat complet : messages en direct (markdown, code, outils, diff, sous-agents), envoi, pièces jointes, citation, questions, interruption, options (modèle, effort), `/clear` et séparateurs, étiquettes, recherche, coût
- [x] 5. Fichiers : navigation, lecture/écriture, recherche, envoi/téléchargement, images
- [x] 6. Git : état, diff, indexation par morceau, commit, journal, pull/push
- [x] 7. Feuille de route, tâches de fond, travail (changements, retour arrière), réglages, page téléphone
- [x] 8. Terminal (term.*) avec clavier adapté
- [x] 9. Notifications de fin de tour et de questions (service de fond), partage Android vers un chat, raccourcis d'appli ; sous-agents finis rangés dans « Terminés (n) »
- [x] 9b. Serveur (0.27.0) : `/api/app-token` après Portier, jeton d'appareil accepté par `/api/tokens` et `/api/revoke`
- [x] 9c. Web (0.27.0) : sous-agent fini retiré de la barre, historique « Terminés (n) »
- [x] 10. Tests (122 tests JVM), documentation, release mineure 0.28.0 (APK joint)
- [x] 11. Essai complet sur le Pixel par Charles : connexion, chat, notifications, partage, terminal ; corrections

## Phase 26 — Piloter les sessions du PC depuis le web (0.29.0)

Charles (19/11/2026) : lancer et gérer depuis la version web une session sur le PC, comme le bureau gère celles du serveur. Choix : le pont du serveur relaie la connexion du web par `ssh` dans le tunnel Ricochet (déjà réglé pour le calcul réparti) jusqu'au pont local du PC, celui de l'application de bureau ; tout le web suit la machine choisie.

- [x] 1. Pont : `machines.list` (relais Ricochet) et `machine.attach` (ssh + petit programme python3 de l'autre côté, pont local lancé s'il manque) ; connexion relayée sauf `hello`, `machine.attach`, `machines.*`
- [x] 2. `ccs-web` : `/api/ws?machine=<id>`, code 4010 et raison si la machine est injoignable
- [x] 3. Web : bouton « Machine pilotée » dans la barre du haut, fenêtre de choix, bandeau d'erreur, choix gardé
- [x] 4. Tests (relais réel en local, ws, node) et essai réel vers `pc-bureau` par le tunnel
- [x] 5. Appli Android : même choix de machine (puce dans Sessions, entrée dans Plus, bandeau sur tous les écrans, notifications qui suivent la machine ; 127 tests JVM)
- [x] 6. Documentation, release mineure 0.29.0
- [x] 7. Essai par Charles depuis son téléphone (PC allumé, CCS à jour sur le PC) : OK

## Phase 27 — Clic droit dans la version web (0.30.0)

Charles (19/11/2026) : un clic droit sur un onglet (et ailleurs) doit proposer les actions de
CCS ; renommer une session ne changeait pas son onglet. Bug d'affichage du bureau signalé en
même temps : boutons au survol posés sur le texte des réponses.

- [x] 1. Menu contextuel commun (`contextMenu`, clavier et Échap) et feuille de saisie (`promptSheet`)
- [x] 2. Onglets et « En cours » : Renommer, nouveau chat / terminal, projet, chemin, fermer, fermer les autres
- [x] 3. Projets et conversations : leurs actions au clic droit
- [x] 4. Titre des onglets : suit le renommage (événement `ccs:conv-renamed`), `chat.list` donne le titre du journal
- [x] 5. Bureau : actions au survol d'une réponse dans leur colonne, plus sur le texte
- [x] 6. Tests (titre de `chat.list`, fil GTK), essai dans Chrome sans écran, release mineure 0.30.0

## Phase 28 — Application iPhone native (Swift + SwiftUI, 0.33.0)

Charles (19/11/2026) : une appli iPhone native, gratuite, en acceptant les limites d'Apple. Swift + SwiftUI (iOS 17), même périmètre que l'appli Android (phase 25, sert de référence). Pas de Mac : projet décrit par XcodeGen (`ios-app/project.yml`), construit et testé sur **Codemagic** (offre gratuite, 500 min/mois de macOS), `.ipa` non signé. Installation par **SideStore** avec un identifiant Apple gratuit : appli à re-signer tous les 7 jours, pas de notifications push (APNs réservé au compte payant).

- [x] 0. Squelette : `ios-app/` (XcodeGen), `codemagic.yaml` (tests sur simulateur, `.ipa` non signé)
- [x] 0b. Charles : compte Codemagic relié au dépôt, jeton d'API dans `~/.config/codemagic/jeton`, SideStore sur l'iPhone ; première construction installée (19/11, connexion, comptes, sessions et chat validés sur l'iPhone 14 Pro)
- [x] 1. Fondations : connexion (mot de passe + TOTP, Portier, jeton d'appareil dans le trousseau), client WebSocket `/api/ws` (RPC + événements, reconnexion), navigation, thème clair/sombre, icône
- [x] 2. Comptes et accueil : cartes des comptes, bascule, pause, bilan de santé, analyse
- [x] 3. Sessions et projets : liste, nouvelle session, renommer, corbeille, historique, comptes par projet
- [x] 4. Chat complet : messages en direct (markdown, code, outils, diff, sous-agents), envoi, pièces jointes, citation, questions, interruption, options, `/clear`, étiquettes, recherche, coût
- [x] 5. Fichiers : navigation, lecture/écriture, recherche, envoi/téléchargement, images
- [x] 6. Git : état, diff, indexation par morceau, commit, journal, pull/push
- [x] 7. Feuille de route, tâches de fond, travail, réglages, page téléphone
- [x] 8. Terminal (term.*) avec barre de touches
- [x] 9. Notifications locales (appli ouverte ou juste en arrière-plan), feuille de partage iOS vers un chat
- [x] 10. Tests (XCTest), documentation (installation SideStore), release mineure 0.33.0 (`.ipa` joint, source SideStore pour les mises à jour)
- [x] 11. Essai par Charles sur l'iPhone 14 Pro (terminal, notifications, partage, fichiers, Git)

## Raccourci Ctrl+Page préc./suiv. dans la version web (0.34.0)

- [x] 1. Ctrl+Page préc. / Ctrl+Page suiv. : onglet précédent / suivant (chats et terminaux, en boucle), essai dans Chrome sans écran, release mineure 0.34.0

## Phase 29 — Vers la 1.0.0

Charles (19/11/2026) : passer en 1.0.0. En SemVer, la 1.0 engage à ne plus casser sans version
majeure les interfaces publiques : commandes `ccs`, pont (`machines.*`, `chat.*`…), fichiers de
configuration. Le reste des tâches ouvertes (dossier entier, sessions sur une autre machine,
archive de l'ancien dépôt) vient après.

- [x] 1. Inventaire des interfaces publiques (commandes `ccs`, méthodes du pont, fichiers de config et leurs clés) : `docs/interfaces.md`, avec les points à revoir
- [x] 2. Relecture : noms incohérents, restes d'anciennes versions, options inutiles ; corrections avant le gel
- [x] 3. Essais réels encore ouverts : APK sur le Pixel (6c de la phase 24, 11 de la phase 25), iPhone (11 de la phase 28) ; corrections
- [x] 4. Suite de tests complète, README et documentation à jour (mise à jour, pont, config)
- [x] 5. Release majeure 1.0.0, mise à jour du VPS et du PC

## Phase 38 — Réseau maillé de tous les appareils (network.mawena.cloud)

Charles (23/11/2026) : fusionner Ricochet dans CCS et relier tous ses appareils par internet comme
sur un réseau local, en passant par le LAN quand deux appareils y sont ensemble. Choix : WireGuard
en maillage avec **Headscale** (coordination, sur le VPS) et le client **tailscale** sur chaque
appareil (appli de l'App Store sur l'iPhone : pas de NetworkExtension avec SideStore). Chemin choisi
tout seul : LAN, puis direct par internet (percement de NAT), puis relais DERP du VPS. Noms de
domaine en anglais : `network.mawena.cloud`, noms des machines en `<machine>.mesh.mawena.cloud`.

- [x] 1. VPS : Headscale 0.29.7 (`network.mawena.cloud` derrière nginx, DERP intégré, STUN UDP 3478), VPS inscrit (100.64.0.1)
- [ ] 1b. Inscrire pc-bureau et laptop-maison (`ccs reseau cle --nom <machine>`, puis les deux lignes en root) — pc-bureau inscrit (`lp-work`, 100.64.0.2) ; reste laptop-maison
- [ ] 2. CCS : `ccs reseau` (fait en 1.3.0 : état, machines, chemin LAN/direct/relais, clé d'inscription jetable) ; le lien « Ajouter un PC » installe aussi tailscale et inscrit la machine
- [x] 3. Onglet « Réseau » à droite de Sessions (Charles, 23/11 : jolie DA, icônes ; web d'abord, installé, puis Android, puis iPhone)
  - [x] Web : carte du réseau, fiches (adresses publiées, trafic, ping réel, renommer, retirer), ajout PC / Android / iPhone (1.4.0)
  - [x] Android (1.5.0)
  - [x] iPhone (1.5.0)
  - [x] Web : l'ajout d'appareil ne revient plus sur « PC Linux » au rafraîchissement (1.5.1)
- [ ] 4. Fusion de Ricochet dans le dépôt CCS (crates Rust, paquets) ; `ccs distant`, root et travaux passent par les IP du réseau maillé
- [ ] 5. Pixel inscrit le 23/11 (`pixel-4-xl`, 100.64.0.3, appli Tailscale par adb) : pc-bureau ↔ Pixel passe par le LAN (10.228.2.44, 18 ms) ; VPS ↔ Pixel par relais DERP. Reste l'iPhone. (Le Pixel est sur le même réseau local que pc-bureau : leur liaison doit passer par le LAN, à vérifier avec `ccs reseau etat`.) Pixel et iPhone dans le réseau (appli Tailscale, serveur personnalisé) ; retrait de l'ancien transport du relais
- [ ] 6. Tests, README, CHANGELOG, releases
- [x] 7. Root : mot de passe gardé pour toujours, chiffré (AES-256-GCM, `root_vault`), revérifié après redémarrage ; web sans compte à rebours (1.3.0)
- [x] 8. Root « pour toujours » : plus de bandeau rouge nulle part (Charles, 23/11) ; `root.status` rend `kept: false, stored: true`, donc rien à reconstruire dans les applis (1.3.1)

## Phase 37 — Ajouter un PC en une ligne (1.2.0, Ricochet 0.6.0)

Charles (22/11/2026) : faciliter le plus possible l'ajout d'un PC au réseau de machines. Choix :
le relais garde 15 min, pour une seule lecture, le script d'installation de la machine
(`/rejoindre/<code>`) ; CCS le demande avec le jeton opérateur et donne la ligne à coller.

- [x] 1. Ricochet : `POST /api/machines` accepte `utilisateur`, `ports`, `cles_ssh` et renvoie `lien` ; `GET /rejoindre/{code}` sert le script (agent, configuration, serveur SSH, clés autorisées) une seule fois ; interface : case « Joignable en SSH », clés, ligne courte
- [x] 2. CCS : `ccs distant ajouter`, méthode `machines.add`, section « Ajouter un PC » de la page Machines du web ; tests, README, CHANGELOG
- [x] 3. Releases Ricochet 0.7.0 et CCS 1.2.0, relais mis à jour, `jeton_operateur` dans `client.toml` du VPS
- [ ] 4. Essai réel par Charles sur un nouveau PC
- [ ] 5. Plus tard : « Ajouter un PC » dans l'appli du bureau, Android et iPhone ; option qui installe aussi CCS et Claude Code (sessions entières sur la machine, piste 13 de la phase 21)

## Phase 35 — Vocal : dictée et lecture des réponses (1.1.0)

Charles (22/11/2026) : chatter à la voix sur toutes les plateformes. Choix : **dictée** (bouton
micro dans la saisie, le texte s'écrit, on relit puis on envoie) et **lecture à voix haute** des
réponses de Claude (bouton « Lire » sur chaque réponse, et un réglage « Lire les réponses » qui
lit automatiquement chaque nouvelle réponse terminée). Voix du système, en français.
Moteurs : web = Web Speech API (bouton caché si le navigateur ne la connaît pas) ; Android =
`RecognizerIntent` et `TextToSpeech` ; iPhone = `SFSpeechRecognizer` et `AVSpeechSynthesizer` ;
bureau Linux = Whisper local (`faster-whisper`, facultatif : bouton caché s'il manque) pour la
dictée et `spd-say` (speech-dispatcher) pour la lecture.

- [x] 1. Web : micro dans la saisie, « Lire » sur les réponses, réglage de lecture automatique
- [x] 2. Bureau (GTK) : dictée par Whisper local (enregistrement pw-record, parecord ou arecord), lecture par speech-dispatcher
- [x] 3. Android : micro dans la saisie, lecture des réponses, réglage
- [x] 4. iPhone : micro dans la saisie, lecture des réponses, réglage (permissions micro et reconnaissance)
- [x] 5. Tests, README, CHANGELOG ; release mineure 1.1.0 (APK et IPA sur Codemagic, installés sur le Pixel et l'iPhone)

## Phase 34 — Mot de passe root depuis les appareils (avant la 1.0.0)

Charles (22/11/2026) : ne plus être bloqué par les commandes root. Quand Claude a besoin de `sudo`,
une demande de mot de passe s'affiche sur tous ses appareils (web, bureau, Pixel, iPhone) ; le
premier qui répond gagne, les autres se ferment. Le mot de passe reste **en mémoire seulement**
une heure, puis s'efface. Choix : sudo silencieux pendant l'heure, mais chaque commande root est
notifiée avec un bouton « Révoquer ». Les services en production restent hors de portée sans
demande explicite.

Conception :
- `ccs root -- <commande>` lance `sudo -A` avec un `SUDO_ASKPASS` fourni par CCS ; les chats de
  Claude reçoivent `SUDO_ASKPASS` pour que `sudo -A` marche aussi tout seul.
- Le **gardien** (dans le pont local de chaque machine) tient le mot de passe en RAM, jamais sur
  disque ni dans un journal, derrière un socket Unix `0600` dans `$XDG_RUNTIME_DIR` (même uid
  vérifié). Expiration absolue d'une heure ; `ccs root oublier` et « Révoquer » l'effacent.
- Pas de mot de passe connu : le pont diffuse `root.ask` (`id`, machine, commande) à ses clients,
  et ntfy envoie un avis **sans secret** (« pc-bureau demande le mot de passe root »). Le client
  répond `root.answer` par le pont authentifié (TLS, ou SSH par Ricochet pour une autre machine) ;
  le mot de passe est vérifié par `sudo -S -v` avant d'être gardé ; `root.resolved` ferme les
  autres popups. Demande sans réponse : abandon après 5 min.
- Chaque commande root lancée avec le mot de passe gardé : avis `root.used` + ntfy avec
  « Révoquer » (bouton signé à usage unique, comme `phone_reply`).

- [x] 1. Gardien en mémoire, socket Unix, `ccs-askpass`, `ccs root -- …` / `ccs root etat|oublier` ; tests
- [x] 2. Pont : `root.ask`, `root.answer`, `root.resolved`, `root.used`, `root.forget` ; vérification `sudo -S -v`, délai, limite d'essais ; avis ntfy sans secret et bouton « Révoquer »
- [x] 3. `SUDO_ASKPASS` dans l'environnement des chats ; consignes de Claude (`~/.claude/CLAUDE.md`) : `ccs root -- …` au lieu de donner la commande à Charles
- [x] 4. Clients : popup de mot de passe d'abord sur Android et iPhone (Charles répond surtout du Pixel et de l'iPhone 14 Pro ; toucher l'avis ntfy ouvre la popup), puis web, bureau, TUI
- [x] 5. Essai réel sur le VPS et pc-bureau ; README, `docs/interfaces.md`, CHANGELOG (VPS OK le 22/11 : popup sur le téléphone, mot de passe gardé 1 h ; reste pc-bureau)

## Phase 33 — Harmonisation des interfaces avant le gel (1.0.0)

Charles (22/11/2026) : harmoniser d'abord, puis sortir la 1.0.0 ; les essais réels encore ouverts
ne bloquent pas (corrections en 1.0.x). Règle de nommage (`docs/interfaces.md`, section 6) :
- **Ce que Charles tape** (commandes, sous-commandes, options, valeurs d'arguments) : **français**.
  Les anciens noms restent acceptés, cachés de l'aide, pendant toute la 1.x.
- **Ce que lisent les programmes** (méthodes, paramètres et réponses du pont, événements, routes
  HTTP, clés et noms des fichiers de config, variables d'environnement, états) : **anglais**, comme
  la majorité déjà. Le pont accepte encore les anciens noms de méthode et de paramètre ; les fichiers
  sont migrés tout seuls au premier lancement.
- `~/.claude-accounts/` garde son nom (profils et historique de Claude dedans : trop risqué).

- [x] 1. Commandes : une seule table d'alias (`bin/ccs` délègue tout à `cli.py`), noms et options en français, anciens noms cachés ; `ccs gui` et `ccs integrate` transmettent leurs arguments, `best` identique des deux côtés, avertissement pour un profil masqué par une commande, commandes internes cachées, vocabulaire des droits unique
- [x] 2. Pont et HTTP : méthodes `machines.*`, séparateurs `.`, paramètres et réponses en anglais, états des travaux en anglais, `machine.ready` émis par le pont, version du protocole dans `hello`, anciens noms acceptés ; `/api/apptoken`, `/api/portier` en anglais ; vieux cache `distant-en-cours/` nettoyé
- [x] 3. Fichiers et variables : noms en anglais avec migration, XDG respecté, `color_scheme` `light|dark`, schéma de `warmup`, `web.json` en anglais (anciennes clés lues), variables `CCS_*` en anglais (anciennes lues)
- [x] 4. Clients : web, bureau, TUI, Android, iPhone : `?protocol=1`, nouveaux noms, valeurs d'état en anglais (rôles, modes, inventaire) affichées en français, raccourcis et `ccs ajouter` aux noms français
- [x] 4 bis. Bureau : les chats locaux passent par le pont local (`ccs bridge --local`), comme le web, pour que les autres appareils les voient en direct (aujourd'hui ils tournent dans `ccs-gui` : vus « arrêtés » et sans les derniers messages ailleurs) ; le pont relancé quand CCS est mis à jour
- [x] 5. Suite complète, README, `docs/interfaces.md` (contrat 1.0), CHANGELOG ; release majeure 1.0.0 ; phase 29 close

## Phase 32 — Ordre des sessions, tableaux, consommation de tokens (0.37.0)

Charles (21/11/2026) : ordonner les sessions dans la version web ; plus de vide sous les
tableaux des réponses sur le bureau ; mieux gérer la consommation de tokens partout (bureau,
web, Android, iPhone, TUI).

- [x] 1. Bureau : les cellules de tableau ne font plus mesurer au tableau la hauteur d'un mot par ligne (grand vide sous le tableau)
- [x] 2. Web : tri des sessions ouvertes (manuel, activité récente, nom, projet, état), glisser-déposer des lignes et des onglets, « Monter » / « Descendre »
- [x] 3. Cœur : `token_use` (usage de chaque tour dans `TurnResult.usage`, coût de réécriture du cache), événement `CacheExpired` du moteur à l'expiration du cache (5 min ou 1 h), seuil du contexte lourd à 150 000 et compactage automatique activé par défaut, gros consommateurs (`analysis.report` → `top`)
- [x] 4. Bureau : ligne d'usage sous chaque tour, note « cache expiré » (Compacter, Nouvelle session) et confirmation à l'envoi, jauge de contexte colorée, gros consommateurs dans Analyse
- [x] 5. Web et TUI : la même chose
- [x] 6. Android : la même chose (tests JVM)
- [x] 7. iPhone : la même chose (tests XCTest, construction Codemagic)
- [x] 8. Documentation, suite de tests complète, release 0.37.0
- [x] 9. Essai par Charles : tableaux au bureau, tri sur le web, cache expiré sur le téléphone

## Phase 31 — Relance après une limite, sur toutes les interfaces (0.36.0)

Charles (21/11/2026) : une session arrêtée par une limite de Claude Code doit repartir seule
quand la limite est levée, sur le bureau, la TUI, le web, Android et l'iPhone.

- [x] 1. `limit_resume` : heure de levée (fenêtre de 5 h, semaine, autre compte libéré), marqueurs « planned » / « lifted », verrou du hook, une bascule et une notification pour toutes les sessions bloquées
- [x] 2. Hook StopFailure : relance prévue dès la limite (aucun compte libre, bascule impossible, pause), heure dans la notification, dossier de la conversation gardé
- [x] 3. Service, application et pont font avancer les marqueurs (le premier qui a le verrou agit)
- [x] 4. Onglets du terminal et chats du bureau : bandeau « relance prévue à HH:MM », « continue » à la levée
- [x] 5. Chats du pont (web, Android, iPhone, TUI) : note dans le fil, « continue » à la levée ; marqueur de secours si le hook n'a rien écrit ; notes du pont affichées dans la TUI
- [x] 6. Terminaux de la version web : `claude` lancé à la main relancé aussi
- [x] 7. Hors de CCS : notification, ou `claude --resume … -p continue` en arrière-plan (réglage)
- [x] 8. Réglage `limit_resume` (bureau, web, Android, iPhone), tests, docs, release 0.36.0
- [x] 9. Essai réel par Charles lors d'une vraie limite (bureau, téléphone)
- [ ] 10. Plus tard : onglets shell du bureau où `claude` est lancé à la main (aujourd'hui : notification)

## Phase 30 — iPhone : machine pilotée, travaux distants, liens de fichiers (0.35.0)

Charles (20/11/2026) : piloter le PC depuis l'appli iPhone comme depuis Android et le web, et
combler ce qui manque encore à l'appli iPhone.

- [x] 1. Machine pilotée : `machines.list`, `?machine=<id>` sur le WebSocket, fermeture 4010, bouton dans Sessions, entrée dans Plus, bandeau sur tous les écrans, écrans, terminaux et notifications qui suivent la machine
- [x] 2. Page « Machines » (Plus) : machines du relais (charge, outils, places, limite), travaux distants (en cours, à venir, finis), journal relu en direct, « Arrêter », « Lancer une commande » (maintenant, cette nuit, à une heure), réglages du relais Ricochet
- [x] 3. Chat : chemins de fichiers cités par Claude cliquables (`work.files`), fichiers des diffs ouverts d'un toucher
- [x] 4. Tests XCTest (machines, travaux, liens), construction Codemagic, release mineure 0.35.0
- [x] 5. Essai par Charles sur l'iPhone (PC allumé, CCS à jour sur le PC)
