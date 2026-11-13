# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Modifié

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
- Planning resserré : frise des fenêtres de 5 h et prochaines recharges dans une
  même carte, explications en info-bulles, « Meilleur moment » repliable avec sa
  conclusion dans l'en-tête, file de tâches vide en une ligne.

### Corrigé

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
