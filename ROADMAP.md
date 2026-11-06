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
- [ ] Documentation (README, guide, architecture, pages man, CHANGELOG)
- [ ] Release 0.5.0 (genre choisi par Charles), `main`, `develop` et le tag poussés

## Phase 4 — Propositions pour 0.4.0 (à choisir)

Recommandées :
- [x] `ccs doctor` : bilan de santé (service, version, extension, intégration, connexions) avec la commande qui corrige → Phase 7
- [x] Prévision de fin de semaine par compte, alerte 2 jours avant → Phase 7
- [x] Mode pause (bascule auto et orchestrateur suspendus 1 h / 4 h / jusqu'à demain) → Phase 7
- [x] Avertissement de nouvelle version et relance automatique de l'icône → Phase 7
- [ ] Conseiller de formule (2–3 Pro ou Max) avec équivalent en dollars

Autres :
- [ ] Conseil de modèle près des limites (Opus → Sonnet)
- [ ] Bilan de la semaine
- [ ] Raccourci clavier global
- [x] Rappel quand une session attend depuis plus de 10 min → Phase 7
- [ ] Journal lisible des bascules dans l'application
- [ ] Compte par projet

## Points mineurs reportés

- [ ] Réveil précis au début de la plage horaire
- [ ] Réglages invalides édités à la main : valeurs par défaut au lieu d'un échec
- [ ] Heure locale exacte (changement d'heure) pour les plages couvrant 2 h – 3 h
- [ ] `ccs best` : ignorer les comptes en erreur
- [ ] Moniteur de sessions créé même si `~/.claude/sessions` apparaît après le démarrage
