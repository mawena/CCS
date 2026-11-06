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
- **Fin de semaine** : au rythme moyen depuis le début de la semaine,
  « ⚠ Semaine : limite prévue jeu. 12 nov. à 15:00 au rythme actuel (18 %/jour),
  2 j avant la réinitialisation » (mis en évidence) ou « ✓ Semaine : tient
  jusqu'à la réinitialisation ». Pas de prévision pendant les 12 premières
  heures de la semaine. Le menu de l'icône la reprend pour chaque compte qui
  s'épuisera avant sa réinitialisation.

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

Pendant une [pause](#pause), aucune bascule automatique n'a lieu.

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

## Pause

La pause suspend la bascule automatique et l'orchestrateur pour un temps, sans
toucher à tes réglages : utile pour rester sur un compte précis.

```sh
ccs pause            # état de la pause (comme « ccs pause status »)
ccs pause 1h         # ou 4h
ccs pause demain     # jusqu'au début de la prochaine plage horaire de l'orchestrateur
ccs pause manuel     # jusqu'à ce que tu reprennes
ccs pause off        # reprend tout de suite (ou « ccs pause reprendre »)
```

Un choix inconnu affiche l'usage et sort avec le code 2. Le service est réveillé
dès que l'état change, pour que l'icône et l'application suivent.

Aussi : menu de l'icône (« Mettre en pause », puis « Reprendre maintenant ») et
carte **Meilleur compte** de l'onglet Comptes (« Mettre en pause » /
« Reprendre »). Dans l'en-tête de la fenêtre, « Auto » devient « Auto ⏸ jusqu'à
14:00 » (« Auto ⏸ en pause » pour une pause sans échéance) ; un clic propose
« Reprendre maintenant ». `ccs status` affiche « En pause jusqu'à 14:00 :
bascule automatique et orchestrateur suspendus (ccs pause off pour
reprendre) » ; l'onglet Planning, l'icône (⏸ devant le pourcentage) et la ligne
d'état de Claude Code rappellent aussi la pause.

Pendant une pause, **CCS ne change plus de compte tout seul**, sans exception :
ni bascule à seuil, ni bascule anticipée, ni bascule après blocage (le hook
`StopFailure` prévient « CCS est en pause jusqu'à HH:MM : pas de bascule
automatique »), ni reprise automatique dans le terminal intégré ; l'orchestrateur
ne démarre aucune fenêtre et le planning ne montre que les fenêtres en cours.
Restent actifs : tes bascules manuelles, les alertes et les warm-up programmés.

À l'échéance, le service lève la pause de lui-même (il se réveille à l'heure
dite) et envoie « Pause terminée ». L'état est gardé dans
`~/.claude-accounts/pause.json` : une pause survit à un redémarrage.

## Alertes

Réglables dans **Réglages → Alertes** :

- seuils 80 % / 95 % du compte actif, fin de session estimée dans moins de
  20 min ;
- **fin de semaine prévue** : quand, au rythme moyen de la semaine, un compte
  atteindra sa limite hebdomadaire avant la réinitialisation, dans 2 jours ou
  moins (`alerts.weekly_forecast`, `alerts.weekly_forecast_days`). Une fois par
  semaine et par compte, avec le budget par jour pour tenir. Elle remplace
  l'alerte plus vague d'avance hebdomadaire (plus de 15 points d'avance sur le
  rythme), qui ne part que si la prévision ne dit rien ;
- compte de nouveau disponible (s'il était à 80 % ou plus), connexion expirée,
  bascule effectuée ou impossible, pause terminée ;
- sessions Claude Code terminées ou en attente (voir
  [Sessions](#sessions-claude-code)) et **rappel** d'une session qui attend ta
  réponse depuis plus de 10 min (`alerts.waiting_reminder`,
  `alerts.waiting_reminder_min`) ;
- nouvelle version de CCS (voir [Mises à jour](#mises-à-jour)).

Chaque alerte n'est envoyée qu'une fois par fenêtre (une fois par semaine pour
la fin de semaine prévue).

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

Le service se relance seul quand le paquet est mis à jour (dans les 5 min). En
cas de doute : `ccs doctor` (voir [Bilan de santé](#bilan-de-santé)).

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
« Renommer… » et « Aperçu… » sont dans le menu « ⋮ » de chaque session et
conversation. La carte d'une session ouverte et chaque conversation récente
affichent le [coût](#coût-dune-conversation) de la conversation.

Le bouton **Tout l'historique** ouvre l'onglet Conversations.

### Nouvelle session

Le bouton **Nouvelle session…** de l'onglet Sessions, l'entrée du même nom
dans le menu ☰ de la fenêtre, ou « Avec des options… » dans le menu de
« Nouvelle session » d'un projet ouvrent un dialogue :

- **Dossier** : le projet d'où tu pars, un projet récent ou un autre dossier
  (bouton dossier) ;
- **Compte Claude** : le compte actif par défaut. Un autre compte s'affiche avec
  un avertissement : « La bascule s'applique à toutes les sessions ouvertes ».
  CCS bascule (comme `ccs <nom>`) avant de lancer la session, et les sessions
  déjà ouvertes passent elles aussi sur ce compte à leur requête suivante ;
- **Modèle** (`--model`) : par défaut (réglage de Claude Code), Opus, Sonnet,
  Haiku ou Fable ;
- **Permissions** (`--permission-mode`) : par défaut, Manuel (`manual`),
  Accepter les modifications (`acceptEdits`), Plan (`plan`), Auto (`auto`),
  Sans question (`dontAsk`) ou Aucune vérification (`bypassPermissions`). Ce
  dernier mode reste proposé, avec un avertissement en rouge : « Claude pourra
  tout faire sans rien demander », à réserver à un dossier jetable ou à une
  machine isolée.

Si un autre compte est choisi, CCS bascule d'abord (« Basculé sur « X » — les
sessions ouvertes suivront à leur prochaine requête ») ; si la bascule échoue,
un message l'explique et rien ne s'ouvre. La session s'ouvre ensuite dans un
onglet du terminal intégré (terminal externe sans VTE), avec
`claude --model … --permission-mode …` lancé dans le dossier choisi ; l'onglet
garde ces options pour Reprendre et la réouverture.

### Notifications

« X a terminé » ou « X attend ta réponse » quand une session qui travaillait
depuis au moins une minute s'arrête (au plus une notification toutes les 2 min
par session). Réglage : **Réglages → Alertes → Sessions Claude Code**.

Un clic sur la notification (ou son bouton **Afficher**) ouvre l'application
sur la session : son onglet du terminal intégré si elle y tourne, sinon sa carte
dans l'onglet Sessions, mise en évidence ; « Cette session n'est plus ouverte »
si elle s'est arrêtée entre-temps. L'application est lancée si elle ne tourne
pas. Le **badge** de l'onglet Sessions compte les sessions qui attendent ta
réponse (avec un point d'attention quand l'onglet n'est pas affiché).

**Rappel** : si une session attend ta réponse depuis plus de 10 min, CCS
envoie « X attend toujours ta réponse », une seule fois par attente (pas de
répétition tant qu'elle n'a pas changé d'état, pas de rappel au démarrage du
service pour une attente déjà ancienne). Il part même si les notifications de
sessions sont coupées, et s'ouvre de la même façon au clic. Réglages : **Rappel
des sessions en attente** et **Rappeler après (min)**
(`alerts.waiting_reminder`, `alerts.waiting_reminder_min`).

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

### Aperçu et export

« Aperçu… » (menu « ⋮ » d'une conversation de l'onglet Conversations, d'une
conversation récente ou d'une session ouverte de l'onglet Sessions) relit une
conversation sans la reprendre : tes demandes, les réponses de Claude
(un seul bloc par réponse), chaque appel d'outil résumé en une ligne (outil et
cible : fichier, commande, recherche…) avec son résultat raccourci, et deux
repères (conversation compactée, demande interrompue). La réflexion de Claude,
le contexte ajouté par VS Code, les rappels et messages injectés par Claude Code
et les fils des sous-agents sont laissés de côté. L'en-tête donne le projet et
le [coût](#coût-dune-conversation).

Le dialogue affiche d'abord les 300 derniers messages (« Afficher 300 messages
de plus » pour remonter) ; **Copier** met toute la conversation en Markdown dans
le presse-papiers, **Exporter en Markdown…** l'enregistre avec son coût (nom
tiré du titre, dossier Documents proposé). Le journal est lu en flux, une ligne à la fois :
même une conversation de plusieurs centaines de Mo s'ouvre sans tout charger.

```sh
ccs preview 4f3a | less        # la conversation en Markdown, coût en en-tête
ccs apercu 4f3a                # même chose
ccs export 4f3a                # <titre-simplifié>.md dans le dossier courant
ccs export 4f3a prets.md       # dans ce fichier (remplacé s'il existe)
ccs export 4f3a ~/Documents    # dans ce dossier, sous le nom tiré du titre
```

L'identifiant s'écrit comme pour `ccs resume` : complet, ou ses 4 premiers
caractères au moins. `ccs export` affiche le chemin absolu du fichier écrit ;
les deux commandes sortent avec le code 1 si l'identifiant est inconnu ou
ambigu, ou si la lecture ou l'écriture échoue.

Le Markdown contient un titre, le projet, la branche, les dates, l'identifiant
et le coût (« - Coût : 1,2 M tokens · ≈ 3,40 $ (équivalent API) »), puis les
échanges (« Toi », « Claude », outils en liste).

### Coût d'une conversation

Chaque conversation affiche son coût : le nombre de tokens consommés (entrée,
sortie, écriture et lecture du cache), **sous-agents compris**, et
l'**équivalent en dollars au tarif de l'API Anthropic**, par exemple
« 1,2 M tokens · ≈ 3,40 $ ». Dans les listes (onglet Conversations,
conversations récentes et sessions ouvertes de l'onglet Sessions), le montant
« ≈ 3,40 $ » s'ajoute à chaque ligne une fois la liste affichée (lignes visibles
d'abord), avec le nombre de tokens au survol ; l'aperçu, l'export et
`ccs preview` le donnent en en-tête.

Ton abonnement (Pro, Max…) **ne facture pas au token** : ce montant dit
seulement ce que la même conversation aurait coûté par l'API, pour comparer
les conversations entre elles. Les tarifs sont ceux de la table du
2026-10-06 (écriture du cache à 1,25 × l'entrée pour 5 min, 2 × pour 1 h ;
mode rapide et inférence limitée aux États-Unis pris en compte). Un modèle dont
le tarif n'est pas connu est compté en tokens et signalé « tarif inconnu »,
jamais estimé au hasard (« ≥ … $ » quand seule une partie est connue).

Les tokens viennent des réponses enregistrées dans le journal ; une réponse
écrite sur plusieurs lignes n'est comptée qu'une fois. Le résultat est gardé en
mémoire tant que le journal ne change pas (même taille, même date de
modification).

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
  est ajouté au `PATH` si besoin. Les options choisies dans « Nouvelle
  session… » (`--model`, `--permission-mode`) sont gardées par l'onglet et
  réutilisées par Reprendre et à la réouverture. « Terminal ici » ouvre ton
  shell (`$SHELL`).
- **Onglets** : titre de la conversation (celui que tu lui as donné, sinon le
  titre automatique), sablier quand Claude **travaille**, point
  d'interrogation quand il **attend ta réponse**, carré quand il est arrêté ;
  un onglet en arrière-plan qui a fini de travailler est signalé. Clic droit
  sur un onglet ou bouton « ⋮ » : renommer la conversation, ouvrir le dossier,
  côte à côte, messages en attente, fermer ; le bouton « ⋮ » porte aussi les
  interrupteurs de la page.
- **Clavier et souris** : Ctrl+Maj+C / Ctrl+Maj+V copient et collent (aussi au
  clic droit), Ctrl+Maj+A sélectionne tout, Ctrl+clic ouvre un lien,
  Ctrl+plus / Ctrl+moins / Ctrl+0 changent la taille du texte, Ctrl+Maj+E met
  deux sessions côte à côte, Ctrl+Maj+M ouvre les messages en attente.
  100 000 lignes de défilement arrière. Police à chasse fixe du bureau,
  couleurs qui suivent le thème clair ou sombre.
- **Fin de Claude** : un bandeau l'indique, avec **Reprendre** (relance
  `claude --resume` de la même conversation) et **Fermer**.
- **Fermeture** : fermer un onglet où Claude tourne, ou la fenêtre avec des
  sessions ouvertes, demande confirmation (« La conversation est enregistrée :
  tu pourras la reprendre. »). La session reçoit alors le signal de fermeture
  d'un terminal (SIGHUP) et s'arrête proprement. Un shell n'est confirmé que si
  un programme y tourne au premier plan.

### Reprise automatique après une limite

Quand la session d'un onglet est bloquée par la limite, le hook de CCS bascule
sur le meilleur autre compte (voir [Intégration](#intégration-dans-claude-code))
et laisse un marqueur pour cette conversation. La page Terminaux tape alors
« continue » puis Entrée dans l'onglet, **une seule fois par limite**, dès que
Claude attend une nouvelle demande, et l'indique par un bandeau « Limite
atteinte sur X : bascule sur Y, conversation relancée. ».

Garde-fous :

- jamais pendant une demande de permission (Entrée y validerait un choix) :
  seulement quand Claude est au repos ou attend une saisie libre ;
- au plus 3 reprises par heure et par onglet, espacées d'au moins 2 min ;
- rien n'est envoyé si quelqu'un a tapé dans l'onglet depuis la limite (toute
  touche compte), si la limite date de plus de 15 min ou d'avant le lancement
  de l'onglet ;
- bascule impossible, aucun compte disponible ou CCS en [pause](#pause) : un
  bandeau l'explique, rien n'est envoyé.

Interrupteur **Reprise automatique après une limite** (activé par défaut) dans
le menu « ⋮ » de la page Terminaux ou **Réglages → Terminal intégré** ; désactivé, le bandeau te dit seulement de
taper « continue ». Il faut `ccs integrate on` : sans le hook, aucun marqueur
n'est écrit et rien n'est relancé. Les marqueurs
(`~/.claude-accounts/limits/<conversation>.json`) sont retirés une fois lus, ou
au bout de 24 h.

### Côte à côte

**Ctrl+Maj+E**, ou « Côte à côte » dans le menu d'un onglet ou le menu « ⋮ » :
l'onglet s'affiche à côté de celui qui est affiché (ou de son voisin), avec une
séparation que tu peux déplacer. Les terminaux ne sont pas relancés : ce sont
les mêmes sessions. La moitié active est bordée de la couleur d'accent ; chaque
moitié a ses boutons « Afficher seul » et « Fermer l'onglet ». Ctrl+Maj+E de
nouveau (ou « Revenir aux onglets »), choisir un troisième onglet ou fermer
une moitié ramène à la vue par onglets.

### Messages en attente

**Ctrl+Maj+M**, ou « Messages en attente… » dans le menu d'un onglet : le
panneau « Envoyer quand Claude sera libre » s'ouvre sous le terminal. Tape la
suite pendant que Claude travaille : la file se modifie (clic sur un message),
se réordonne, se vide message par message, et « Envoyer maintenant » force
l'envoi d'un message. Replié, le panneau laisse un bandeau « N messages en
attente — raison ».

Un message part **par tour** : quand Claude a fini de travailler, ou tout de
suite s'il est déjà libre. Jamais pendant un tour, une demande de permission
ou une limite pas encore reprise, ni si quelqu'un a tapé dans l'onglet depuis
le début du dernier tour (le texte se mélangerait). Un message tient sur une
ligne. La file est gardée avec les onglets. Un tour très court (moins de 3 s)
peut retarder le message suivant jusqu'à 30 s.

### Onglets rouverts au redémarrage

Les onglets ouverts sont enregistrés (une seconde après chaque changement et à
la fermeture) dans `~/.claude-accounts/terminals.json`, avec leurs options de
lancement et leurs messages en attente. Au lancement suivant, un bandeau en
haut de la page Terminaux demande « Rouvrir les N sessions de la dernière
fois ? » (**Rouvrir** / **Ignorer**), et un message avec un bouton « Rouvrir »
s'affiche dans la fenêtre. Sans réponse, la liste reste enregistrée pour la
fois suivante.

Interrupteur **Rouvrir les onglets au démarrage** (désactivé par défaut) dans
le menu « ⋮ » de la page Terminaux ou **Réglages → Terminal intégré** : les
onglets sont rouverts sans question.
Chaque conversation reprend avec `claude --resume` et ses options (`--model`,
`--permission-mode`) ; un shell rouvre dans son dossier de départ. Ne sont pas
rouverts : un dossier disparu, une conversation ouverte ailleurs ou déjà dans un
onglet ; un message récapitule ce qui l'a été.

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
  X : basculé sur Y ». Tape « continue » dans la session (dans le terminal
  intégré, la [reprise automatique](#reprise-automatique-après-une-limite)
  peut le faire : le hook laisse pour cela un marqueur par conversation).
- **En pause**, la ligne d'état commence par ⏸ et le hook ne bascule pas : la
  notification indique « CCS est en pause jusqu'à HH:MM : pas de bascule
  automatique. » (une seule pour plusieurs sessions bloquées en même temps).

`ccs integrate off` retire uniquement les entrées de CCS.

## Bilan de santé

`ccs doctor` (alias `ccs bilan`, ou `claude-accounts doctor`, ou **Bilan de
santé…** dans le menu ☰ de l'application) passe tout en revue :

| Vérification | Ce qui est regardé |
|---|---|
| Service ccs-daemon | Actif sous systemd, en échec, arrêté, ou lancé à la main |
| Relevés | Date du dernier relevé (`state.json`) |
| Version installée | Paquet `ccs` installé et version du code |
| Code du service | Version que fait tourner le service, relancé depuis la mise à jour ? |
| Extension AppIndicator | Extension GNOME « Ubuntu AppIndicators » présente, activée, chargée |
| Indicateur | Icône de la barre du haut lancée |
| Intégration Claude Code | Ligne d'état et hook installés |
| Comptes | Connexion de chaque profil : présente, expirée ou qui expire dans 3 jours, dernier relevé refusé |
| Commande claude | `claude` trouvé (`PATH` ou `~/.local/bin`) et sa version |
| Outils de ccs | `jq` présent |
| Terminal intégré | VTE pour GTK 4 disponible |

Chaque ligne est ✔, ⚠ ou ✖ ; sous chaque problème, **la commande qui le
corrige**, à copier (par exemple `systemctl --user restart ccs-daemon`,
`ccs integrate on`, `ccs rm perso && ccs add perso`). Le bilan n'exécute jamais
rien à ta place. Code de sortie : **0** si tout va bien, **1** au moindre
avertissement ou erreur.

Dans l'application, chaque correctif a son bouton « Copier la commande », et un
bouton copie tout le bilan. L'application fait aussi le bilan en arrière-plan
4 s après son ouverture : s'il trouve une **erreur** (un simple avertissement
ne suffit pas), un **bandeau** « Un problème a été détecté : <vérification> »
(ou « N problèmes ont été détectés ») propose **Voir le bilan** ; il disparaît
quand tu ouvres le bilan. Le bilan ne lit des jetons de connexion que leur présence
et leurs dates d'expiration.

## Mises à jour

Le service regarde la dernière version publiée sur GitHub
(`api.github.com/repos/mawena/CCS/releases/latest`, sans authentification) au
plus une fois par jour, une heure plus tard si GitHub n'a pas répondu ; une
erreur réseau ou un refus de GitHub n'est jamais bloquant. Quand une version
plus récente existe (comparaison SemVer), il prévient **une seule fois par
version**, avec le lien de la version ; l'icône affiche « ⬆ CCS x.y.z
disponible — voir la version », la fenêtre un bandeau « CCS x.y.z est
disponible » avec **Voir** (une fois par lancement, seulement si cette version
est plus récente que celle installée) et **Réglages → Service de collecte** la
version installée et le lien. Interrupteur **Nouvelles
versions** (`updates.enabled`) ; cache `~/.claude-accounts/updates.json`.

Installe le nouveau paquet : le service se relance seul (dans les 5 min) et
l'icône aussi, dès que les fichiers installés ne bougent plus (10 s). En venant
de la 0.4.0 ou d'avant, l'icône ne sait pas encore se relancer : fais-le une
fois avec `pkill -f 'claude-accounts tray'; setsid -f claude-accounts tray`.

## Boutons des notifications

Les alertes 80 % / 95 % et « limite bientôt atteinte » proposent « Basculer sur
<meilleur compte> » ; le clic bascule (comme une bascule manuelle). Un clic sur
une notification de session (« a terminé », « attend ta réponse », rappel), ou
son bouton **Afficher**, ouvre l'application sur cette session (voir
[Notifications](#notifications)). Si l'application n'était pas ouverte, elle
est lancée dans sa propre unité systemd : redémarrer le service ne la ferme
pas.
