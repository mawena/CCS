# Guide d'utilisation

## Profils

- `ccs save <nom>` enregistre le compte actuellement connecté dans Claude Code.
- `ccs add <nom>` lance `claude auth login` : le navigateur s'ouvre, connecte-toi
  avec le compte à ajouter. CCS refuse d'ajouter deux fois le même compte.
- `ccs <nom>` bascule. Si le compte connecté n'est enregistré nulle part, CCS
  refuse de basculer pour ne pas le perdre : fais d'abord `ccs save`.
- CCS n'appelle jamais `claude auth logout` (cela invaliderait le jeton du profil).

## Lire l'usage

`ccs usage` (ou l'onglet **Comptes**) affiche pour chaque compte :

- **Session (5 h)** : la fenêtre glissante démarre au premier message et se
  réinitialise 5 h plus tard.
- **Semaine** : limite hebdomadaire, toutes sessions confondues.
- **Prévision** : « limite estimée vers 14 h 20 » si le rythme des 45 dernières
  minutes épuise la session avant sa réinitialisation, sinon « tient jusqu'à la
  réinitialisation ».
- **Rythme de la semaine** : marge (ou avance) par rapport à un usage régulier
  sur 7 jours, et budget quotidien pour finir la semaine.

Le bandeau **Meilleur compte maintenant** et la **capacité restante** (en
sessions complètes, tous comptes confondus) résument la situation.

## Bascule automatique

Activée par défaut (`ccs auto on|off`, interrupteur « Auto » de l'application).

Elle se déclenche quand une limite du compte actif atteint le **seuil** (98 %)
ou quand le prochain relevé dépasserait 100 % au rythme actuel. Elle choisit le
meilleur compte dont la session est sous **80 %** et la semaine sous **95 %**.

Garde-fous :

- au plus une bascule automatique toutes les 5 minutes ;
- après une bascule manuelle, CCS attend 5 minutes (sauf au-delà de 99,5 %) ;
- un compte quitté parce qu'il était épuisé n'est pas repris avant sa
  réinitialisation ;
- s'il n'y a aucun compte disponible, CCS ne bascule pas et prévient avec
  l'heure du prochain compte disponible ;
- des données de plus de 10 minutes ne déclenchent jamais de bascule.

Les sessions Claude Code ouvertes suivent à leur prochaine requête. Si une
session a déjà atteint la limite avant la bascule, tape « continue ».

## Orchestrateur

Désactivé par défaut : `ccs orch on`, l'interrupteur de l'onglet **Planning**
ou **Réglages → Orchestrateur**.

Pendant la **plage horaire** (8 h → 2 h par défaut, jours réglables ; une plage
peut passer minuit), il :

- **démarre** chaque compte au repos à son créneau du jour, puis **enchaîne**
  ses fenêtres : dès qu'une fenêtre se termine, la suivante démarre (requête
  minimale à Haiku, dans un dossier de configuration temporaire) ;
- **décale** les comptes : un compte au repos ne démarre que si la dernière
  fenêtre ouverte sur un autre compte date d'au moins 5 h ÷ N (2 h 30 pour deux
  comptes). Le matin, cela donne `début de plage`, puis `+ 2 h 30`… ; si un
  compte a été ouvert avant le début de plage, l'écart part de son heure
  d'ouverture (ouvert à 07:10 → le suivant démarre à 09:40, pas à 10:30). Dans
  la journée, l'écart se rétablit tout seul, y compris après tes propres
  démarrages. Un compte au repos reste utilisable : son quota est entier, et ta
  première requête ouvre sa fenêtre ;
- **bascule vers le quota qui expire** : un compte dont la fenêtre se termine
  dans moins de 60 min avec au moins 30 % restants passe devant, si sa fin est
  plus proche que celle du compte actif (au plus une fois toutes les 30 min,
  jamais juste après une bascule manuelle, seulement dans la plage horaire et
  si la bascule automatique est activée) ;
- **met en réserve** un compte en avance de plus de 10 points sur le rythme de
  sa semaine : la bascule à seuil, la bascule anticipée et le meilleur compte
  le choisissent en dernier. Un compte à 95 % de sa semaine n'est
  plus démarré.

Un compte en erreur (connexion expirée, réseau) ou aux données de plus de
10 minutes n'est jamais démarré ni choisi par une bascule automatique. Une
tentative de démarrage par compte au plus toutes les 15 minutes ; après un
démarrage réussi, rien pendant 5 h ; après 3 échecs, une tentative par heure.
Le décalage s'aligne sur ce que tu as réellement démarré : les fenêtres déjà
ouvertes passent en premier, puis le compte actif.

**Planning.** `ccs plan` ou l'onglet **Planning** : frise par compte (fenêtre en
cours remplie selon l'usage, fenêtres prévues en pointillés, trait rouge =
maintenant) et liste des recharges à venir.

## Alertes

Réglables dans l'onglet **Réglages** : seuils 80 % / 95 % du compte actif, fin
de session estimée dans moins de 20 min, avance hebdomadaire de plus de 15
points, compte de nouveau disponible (s'il était à 80 % ou plus), connexion expirée, bascule effectuée ou
impossible. Chaque alerte n'est envoyée qu'une fois par fenêtre.

## Warm-up à heure fixe

Alternative manuelle à l'orchestrateur. Onglet **Réglages → Warm-up** : pour chaque profil, une heure (HH:MM) et des
jours. À l'heure dite, si la fenêtre de 5 h du compte n'est pas ouverte, CCS
envoie une requête minimale à Haiku avec ce compte (dans un dossier de
configuration temporaire : le compte actif n'est pas touché). La fenêtre
démarre alors et se réinitialise 5 h plus tard.

Exemple : tu travailles surtout de 9 h à 18 h → warm-up à 7 h ; la première
fenêtre se termine à 12 h, en plein milieu de ta journée, au lieu de 14 h.

## Analyse

`ccs analyze --days 30` (ou l'onglet **Analyse**) lit les journaux de Claude
Code (`~/.claude/projects`). Les volumes sont exprimés en **tokens pondérés** :
entrée + écriture de cache + sortie × 5 + lecture de cache × 0,1, une
approximation du poids de chaque réponse dans les limites. La répartition par
compte commence avec le service de collecte (« inconnu » avant).

## Service

```sh
systemctl --user status ccs-daemon
journalctl --user -u ccs-daemon -f
claude-accounts collect        # relevé immédiat
```

Sans service, l'application et `ccs usage` fonctionnent toujours, mais il n'y a
ni bascule automatique, ni alertes, ni historique.

## Sessions Claude Code

`ccs sessions` ou l'onglet **Sessions** : chaque session ouverte (terminal ou
VS Code) avec son projet, son état — *travaille*, *attend ta réponse* (et
pourquoi : permission, question…), *au repos* —, sa durée, son modèle et sa
consommation (tokens pondérés de la conversation). CCS lit les fiches de
`~/.claude/sessions` en lecture seule et ignore les fichiers `.key`.

Actions : ouvrir un terminal (« Terminal ici ») ou le dossier du projet ;
terminer une session (après confirmation : la conversation est conservée et peut
être reprise) ; **Reprendre** une conversation récente (`claude --resume`) ou
lancer une **Nouvelle session** dans un projet récent. Ces actions ouvrent un
onglet du [terminal intégré](#terminal-intégré) ; le menu « ⋮ » (ou la flèche de
« Nouvelle session ») garde le terminal externe. Une session déjà ouverte dans
l'application affiche **Afficher**, qui mène à son onglet ; une conversation
ouverte ailleurs (autre terminal, VS Code) n'est pas reprise une seconde fois.
« Renommer… » est dans le menu « ⋮ » de chaque session et conversation.

Le bouton **Tout l'historique** ouvre l'onglet Conversations.

Notifications : « X a terminé » ou « X attend ta réponse » quand une session
qui travaillait depuis au moins une minute s'arrête (au plus une notification
toutes les 2 min par session). Réglage : **Réglages → Alertes → Sessions
Claude Code**.

## Historique des conversations

`ccs conv` ou l'onglet **Conversations** : toutes les conversations Claude Code
du PC (`~/.claude/projects/*/*.jsonl`, terminal et VS Code), de la plus récente
à la plus ancienne, groupées par date.

- **Titre** : celui donné avec `/rename` ou dans VS Code, sinon le titre
  automatique de Claude Code, sinon la première demande. Le contexte ajouté par
  VS Code (fichier ouvert, sélection) et les messages injectés par Claude Code
  sont ignorés.
- **Recherche** : chaque mot doit apparaître dans le titre, la première ou la
  dernière demande, le projet, le dossier ou la branche (accents et majuscules
  ignorés). Filtres : projet (`-p <nom ou dossier>`), origine (`--vscode`,
  `--terminal`). `--all` affiche tout, `--json` pour un script.
- **Reprise** : dans VS Code (`ccs resume <id> --vscode`, ou le bouton) : CCS
  ouvre la fenêtre du projet puis passe le lien
  `vscode://anthropic.claude-code/open?session=<id>` à l'extension. Dans un
  terminal : `ccs resume <id>` reprend dans le terminal courant,
  `--new-terminal` dans une nouvelle fenêtre, `--print` affiche seulement la
  commande. Dans l'application, le bouton **Terminal** reprend dans un onglet du
  terminal intégré (le terminal externe est au menu « … »), et **Afficher**
  remplace les boutons d'une conversation déjà ouverte dans un onglet. Une
  conversation déjà ouverte dans une session n'est pas relancée.
- **Projet déplacé** : Claude Code range les conversations selon le chemin du
  projet ; après un déplacement, `claude --resume` ne les retrouve plus. CCS
  marque ces conversations « dossier introuvable », propose le dossier du même
  nom (connu de l'historique, sinon trouvé dans le dossier personnel, sur 4
  niveaux) et demande confirmation. Il copie alors le journal dans le dossier
  de projet de Claude Code correspondant au nouvel emplacement, sans toucher à
  l'original. `--dir <dossier>` choisit le dossier à la main.

Lecture : la première fois, CCS parcourt tous les journaux (quelques secondes
pour 2 Go) ; ensuite il ne relit que les lignes ajoutées depuis, grâce au cache
`~/.claude-accounts/conversations-cache.json`.

### Renommer une conversation

« Renommer… » (menus « ⋮ » des onglets Sessions et Conversations, menu d'un
onglet du terminal intégré) ou `ccs title <id> <titre>` : comme `/rename` dans
Claude Code, CCS ajoute à la fin du journal une ligne
`{"type":"custom-title","sessionId":"…","customTitle":"…"}`. Le dernier titre
l'emporte, partout : liste de l'application, `ccs conv`, `claude --resume`,
VS Code. Le titre tient sur une ligne (200 caractères au plus) ; vide, il est
refusé.

Le journal n'est jamais réécrit : la ligne part en une seule écriture en mode
ajout, qui ne peut pas se mélanger avec ce qu'une session ouverte écrit au même
moment. Une session ouverte relit la fin de son journal avant d'y réécrire ses
propres informations : elle garde le nouveau titre. CCS n'envoie pas `/rename`
dans le terminal d'une session, pour ne jamais taper dans une question ou une
demande de permission en cours.

## Terminal intégré

Les sessions Claude Code s'ouvrent dans la fenêtre de l'application, dans des
onglets (page **Terminaux**, visible tant qu'un onglet est ouvert, avec le
nombre d'onglets). Il faut VTE pour GTK 4 (`gir1.2-vte-3.91`, dépendance du
paquet) ; sans lui, tout s'ouvre dans un terminal externe comme avant et
l'onglet Sessions indique `sudo apt install gir1.2-vte-3.91`.

- **Lancement** : `claude --resume <id>` (ou `claude`) dans le dossier du
  projet, par un bash de connexion comme le terminal externe (ton profil est
  lu), avec `TERM=xterm-256color` et `COLORTERM=truecolor` ; `~/.local/bin`
  est ajouté au `PATH` si besoin. « Terminal ici » ouvre ton shell (`$SHELL`).
- **Onglets** : titre de la conversation (celui que tu lui as donné, sinon le
  titre automatique), sablier quand Claude **travaille**, point
  d'interrogation quand il **attend ta réponse**, carré quand il est arrêté ;
  un onglet en arrière-plan qui a fini de travailler est signalé. Clic droit
  sur un onglet ou bouton « ⋮ » : renommer la conversation, ouvrir le dossier,
  fermer.
- **Clavier et souris** : Ctrl+Maj+C / Ctrl+Maj+V copient et collent (aussi au
  clic droit), Ctrl+Maj+A sélectionne tout, Ctrl+clic ouvre un lien,
  Ctrl+plus / Ctrl+moins / Ctrl+0 changent la taille du texte. 100 000 lignes
  de défilement arrière. Police à chasse fixe du bureau, couleurs qui suivent
  le thème clair ou sombre.
- **Fin de Claude** : un bandeau l'indique, avec **Reprendre** (relance
  `claude --resume` de la même conversation) et **Fermer**.
- **Fermeture** : fermer un onglet où Claude tourne, ou la fenêtre avec des
  sessions ouvertes, demande confirmation (« La conversation est enregistrée :
  tu pourras la reprendre. »). La session reçoit alors le signal de fermeture
  d'un terminal (SIGHUP) et s'arrête proprement. Un shell n'est confirmé que si
  un programme y tourne au premier plan.

Pour essayer une copie de développement sans réveiller l'application ouverte :
`CCS_APP_ID=io.ccs.ClaudeAccounts.Dev bin/claude-accounts gui` ; `CCS_NO_VTE=1`
force le repli sur le terminal externe.

## Intégration dans Claude Code

`ccs integrate on` (ou **Réglages → Intégration dans Claude Code**) modifie
`~/.claude/settings.json` : sauvegarde `settings.json.ccs-backup` à la première
fois, écriture atomique ; une `statusLine` existante est conservée.

- **Ligne d'état** : `claude-accounts statusline` affiche le compte actif, la
  session et sa recharge (↻), la limite estimée (⏱), la semaine, le nombre de
  comptes, et `→ compte` quand un autre compte est conseillé. Relance tes
  sessions pour la voir.
- **Bascule après blocage** : hook `StopFailure` (erreur `rate_limit`). CCS
  rafraîchit l'usage si besoin, choisit le meilleur autre compte (données
  fraîches, sans erreur, sous 95 %), bascule et notifie « Limite atteinte dans
  X : basculé sur Y ». Tape « continue » dans la session.

`ccs integrate off` retire uniquement les entrées de CCS.

## Boutons des notifications

Les alertes 80 % / 95 % et « limite bientôt atteinte » proposent « Basculer sur
<meilleur compte> » ; le clic bascule (comme une bascule manuelle).
