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
- [ ] 23. Documentation (README, guide, architecture, man, CHANGELOG, site)
- [ ] 24. Essai réel sur le VPS (DNS et lnmp par Charles)
- [ ] 25. Release mineure 0.11.0, trois `.deb`, release GitHub et dépôt APT, mise à jour du VPS

## Phase 14 — Travailler sans quitter CCS (0.12.0)

Toutes les propositions retenues le 14/11, conception validée le 15/11. Passée en phase 14 le 15/11 : la partie VPS est prioritaire. Travail sur la branche `feature/phase14`.
Conception : `docs/superpowers/specs/2026-11-15-phase-13-design.md`.
Plan détaillé (tests et interfaces de chaque tâche) : `docs/superpowers/plans/2026-11-15-phase-13.md`.

Page Git (inspirée de GiGit) :
- [x] 1. Lecture d'un dépôt : log par pages, références, branche et avance/retard, état, diff (`git_repo`)
- [x] 2. Écritures : indexation par fichier, bloc et ligne, commit et amend, annulation, `.gitignore`, fetch / pull / push (forcé avec garde), git flow, message proposé
- [x] 3. Disposition du graphe façon ungit, portée de GiGit (10 000 commits en moins de 200 ms)
- [x] 4. Avatars des auteurs en cache, réglages `git.*` et `phone.show_content`
- [x] 5. Onglet portant un widget quelconque dans la zone de droite
- [x] 6. Graphe des commits en deux densités (compact, cartes), chargé par pages
- [ ] 7. Détail d'un commit, changements en cours, indexation par ligne, Commit et Ctrl+Entrée
- [ ] 8. Page Git dans le panneau de gauche : dispositions A, B et C, bandeau d'erreur, fetch automatique, rafraîchissement

Le travail de Claude :
- [ ] 9. « Faire une tâche » de la feuille de route : chat ou file de nuit, bandeau « Tâche finie ? » si Claude n'a pas coché
- [ ] 10. Lecture des copies de Claude Code (`file_history`) : changements, plan de retour en arrière
- [ ] 11. Volet « Changements de la session », annuler un fichier, revenir avant un message, contrôle `ccs doctor`

Le chat :
- [ ] 12. Chercher dans le fil (Ctrl+F)
- [ ] 13. Messages enregistrés, communs ou par projet
- [ ] 14. Bouton « Compacter » dans l'alerte de contexte lourd
- [ ] 15. Commande `!` lancée dans le dossier du projet

Le téléphone :
- [ ] 16. Réponses signées et à usage unique (`phone_reply`)
- [ ] 17. Autoriser ou Refuser depuis la notification, réglage « Montrer la commande »

Fin de phase :
- [ ] 18. Documentation (README, guide, architecture, man, CHANGELOG, site)
- [ ] 19. Essai réel par Charles et corrections
- [ ] 20. Release mineure 0.12.0, `.deb`, release GitHub et dépôt APT
