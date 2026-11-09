# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnage
[SemVer](https://semver.org/lang/fr/).

## [Non publié]

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
