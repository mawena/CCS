# CCS — Claude Code partout : tous tes appareils, toutes tes machines, tous tes comptes

CCS est un **poste de travail complet autour de Claude Code** :

- **Partout** : application de bureau GNOME (chat graphique, fichiers, feuille de route,
  Git, terminal), version web et applications **Android** et **iPhone** pour piloter les
  sessions de tes PC et de ton serveur depuis le téléphone, notifications, vocal
  (dictée et lecture des réponses).
- **Toutes tes machines** : un **réseau maillé** privé relie PC, serveur et téléphones
  comme sur un réseau local (fichiers, son partagé), le **calcul réparti** envoie
  un build ou une longue suite de tests sur une autre machine, les commandes **root**
  se valident depuis le téléphone.
- **Tous tes comptes** : 2 ou 3 comptes Claude Code travaillent comme un seul — bascule
  en une commande, usage de tous les comptes d'un coup d'œil, bascule automatique avant
  la coupure, **orchestrateur** des fenêtres de 5 h.
- **Des outils autour** : assistant vocal Jarvis, Market (recherche sur Facebook
  Marketplace au Togo).

```sh
ccs save perso        # enregistre le compte connecté
ccs add boulot        # connecte et enregistre un deuxième compte
ccs orchestrator on        # l'orchestrateur gère le reste
ccs integration on      # l'état des comptes en bas de chaque session Claude Code
ccs status            # où j'en suis, quel compte utiliser
ccs advisor           # la formule qu'il te faut, d'après ton usage réel
```

**Site :** [mawena.github.io/CCS](https://mawena.github.io/CCS/) ·
**Installation sur Ubuntu** (dépôt APT signé [apt.mawena.cloud](https://apt.mawena.cloud/), mises à jour par `apt upgrade`) :

```sh
curl -fsSL https://apt.mawena.cloud/installer.sh | sudo sh -s -- ccs
```

Les autres façons d'installer sont dans [Installation](#installation).

CCS est aussi une **application de bureau** (GTK 4 / libadwaita) : les sessions
Claude s'y travaillent dans un **chat graphique** (modèle, effort, ultracode et droits
en un clic), à côté des **fichiers** du projet et de sa **feuille de route**, avec une
couleur par compte. Voir [Chat graphique](#chat-graphique).

## Plusieurs comptes : le palier qui manque

**Pro (20 $) ne te suffit plus, mais Max (100 $) c'est trop ?** CCS fait
travailler 2 ou 3 comptes Claude Code ensemble.

| Formule | Prix / mois* | Capacité (Pro = 1×) |
|---|---|---|
| 1 compte Pro | 20 $ | 1× |
| **2 comptes Pro + CCS** | **40 $** | **≈ 2×** |
| **3 comptes Pro + CCS** | **60 $** | **≈ 3×** |
| Max | 100 $ | 5× |
| Ultra (l'ancien Max 20×) | 200 $ | 10× par semaine, sans limite de 5 h |

\* Facturation mensuelle, hors taxes, relevée sur claude.com/pricing le
6 novembre 2026 (Pro : 17 $/mois en annuel). Les prix peuvent changer :
vérifie-les avant de t'abonner.

Soyons clairs : à capacité égale, Max n'est pas plus cher que plusieurs comptes
Pro. CCS sert quand ton besoin se situe **entre** les formules — deux ou trois
fois Pro — ou quand tu as déjà plusieurs comptes (perso et travail, par
exemple). Pas sûr de ton palier ? Le [conseiller de formule](#conseils) mesure
ton usage et te dit quelle combinaison prendre. Ce que CCS apporte, c'est que
ces comptes se comportent comme un seul :

- tu ne te reconnectes jamais, tu ne surveilles rien ;
- la bascule se fait **avant** la coupure, sans interrompre les sessions ouvertes ;
- l'orchestrateur évite les temps morts : avec 2 comptes décalés, une recharge
  arrive toutes les 2 h 30 au lieu de toutes les 5 h ;
- le quota qui va expirer est utilisé en premier, pour en perdre le moins possible.

> **À lire avant de multiplier les comptes.** Les conditions d'utilisation
> d'Anthropic peuvent encadrer l'usage de plusieurs comptes par une même
> personne : vérifie qu'elles autorisent ton usage. CCS ne relève aucune
> limite : chaque compte garde ses propres limites, CCS aide seulement à bien
> les utiliser. CCS n'est pas un produit Anthropic ; il s'appuie sur les
> fichiers et l'API d'usage de Claude Code, qui peuvent évoluer.

## L'orchestrateur

Pendant ta plage horaire (par défaut 8 h → 2 h), il applique quatre règles :

1. **Enchaîner** — chaque compte a toujours une fenêtre de 5 h ouverte : dès
   qu'une fenêtre se termine, une requête minimale (Haiku) démarre la suivante.
2. **Décaler** — les fenêtres des comptes sont espacées de 5 h ÷ nombre de
   comptes : un compte au repos attend que l'écart avec la dernière fenêtre
   démarrée soit atteint (il reste utilisable à tout moment entre-temps) :

   ```
   perso   08:00 ━━━━━━━━━ 13:00 ━━━━━━━━━ 18:00 ━━━━━━━━━ 23:00 ━━━
   boulot        10:30 ━━━━━━━━━ 15:30 ━━━━━━━━━ 20:30 ━━━━━━━━━ 01:30
   recharges           13:00     15:30     18:00     20:30     23:00
   ```

3. **Quota qui expire d'abord** — si un compte va perdre plus de 30 % de son
   quota dans moins d'une heure, CCS bascule dessus avant (au plus toutes les
   30 min).
4. **Répartir la semaine** — un compte en avance sur son rythme hebdomadaire
   passe en réserve : les bascules le choisissent en dernier. Un compte à 95 %
   de sa semaine n'est plus démarré.

Le service se réveille pile à chaque fin de fenêtre. Hors plage horaire, rien
n'est démarré et aucune bascule anticipée n'a lieu ; la bascule anticipée
respecte aussi l'interrupteur « bascule automatique ». Tout se règle dans la fenêtre **Réglages** (menu ☰), et la section
**Planning** de l'Accueil montre la frise du jour et les recharges à venir.

## Mettre en pause

Besoin de rester sur un compte précis le temps d'une démo ou d'un gros
travail ? `ccs pause 1h` (ou `4h`, `demain` = jusqu'au début de la prochaine
plage horaire, `manuel` = jusqu'à ce que tu reprennes) suspend la bascule
automatique et l'orchestrateur. Pendant une pause, **CCS ne change plus de
compte tout seul**, même quand une session est bloquée par la limite ; les
bascules que tu fais toi-même, les alertes et les warm-up continuent. La pause
se lève seule à l'échéance (notification « Pause terminée ») ; `ccs pause off`
reprend tout de suite.

Aussi dans le menu de l'icône (« Mettre en pause ») et par le bouton **Pause** du
bandeau **Meilleur compte** de l'Accueil. Pendant la pause, l'en-tête de la fenêtre affiche
« Auto ⏸ jusqu'à 14:00 » (un clic propose « Reprendre maintenant ») ;
`ccs status`, la section Planning de l'Accueil, l'icône et la ligne d'état de Claude Code la
rappellent aussi.

## Conseils

En haut de l'onglet **Analyse**, et dans le terminal :

- **Conseiller de formule** (`ccs advisor`) : combien de comptes Pro, Max ou
  Ultra pour ton usage réel. CCS mesure ton besoin sur les 4 dernières semaines
  de relevés, en « unités Pro » (1 = la limite d'un compte Pro), ajoute 20 % de
  marge et cherche la combinaison la moins chère qui le couvre, jusqu'à
  3 comptes. Il montre son raisonnement — usage moyen et maximal, limites
  atteintes, capacité inutilisée, économie ou surcoût par rapport à ce que tu
  paies — et ce que le même usage aurait coûté **au tarif de l'API** :

  ```
  Conseil : 2 Pro — 40 $/mois
  ```

- **Conseil de modèle près des limites** : quand le compte actif dépasse 80 %
  (session ou semaine) avec un modèle cher, une notification — une par fenêtre
  de 5 h — propose la famille suivante (Fable → Opus → Sonnet → Haiku) et le
  gain en ordre de grandeur (« ferait durer ce qui reste environ ×1,7 ») ; la
  ligne d'état de Claude Code ajoute « → sonnet ? ».
- **Bilan de la semaine** (`ccs week`) : usage de chaque compte,
  conversations, sessions, tokens et équivalent API, modèles, projets, bascules
  et alertes, comparés à la semaine précédente. Une notification le résume au
  début de chaque semaine ; la carte de l'onglet Analyse laisse choisir la
  semaine (aussi « Bilan de la semaine » dans le menu de l'icône).
- **Rapport mensuel** (`ccs month`) : le même exercice sur le mois civil, mois en
  cours comparé au même nombre de jours du mois précédent, avec les 10 premiers
  projets et, à partir de 3 mois d'activité, la tendance sur 3 à 6 mois. Une
  notification le résume le 1er du mois ; la carte **Rapport mensuel** de
  l'onglet Analyse laisse choisir le mois.

Tout se règle dans **Réglages → Conseils** (conseil de modèle et son seuil,
bilan, jour et heure du bilan, rapport mensuel et son heure) et **Réglages → Conseiller de formule**
(semaines analysées, marge, nombre de comptes, formule d'un compte mal
reconnue, tarifs). Les prix des formules sont ceux du 6 novembre 2026, signalés
« à vérifier » après 120 jours. Le bilan et l'équivalent API ne voient que les
journaux Claude Code **de ce PC** : claude.ai et tes autres appareils n'y
figurent pas.

## Meilleur moment pour une grosse tâche

Une refonte, une migration, une longue session d'agents : **quand la lancer ?**
La carte « Meilleur moment pour une grosse tâche » de la section **Planning** de l'Accueil
(et `ccs best-time --duration 3h`) compte, pour chaque heure de départ possible sur
24 h, les **fenêtres de 5 h** disponibles tous comptes confondus (le reste de la
fenêtre en cours, une fenêtre neuve à chaque réinitialisation, une fenêtre
fraîche démarrée au départ), plafond hebdomadaire compris. Elle dit « Lance-la
maintenant » quand maintenant est à 10 % du meilleur départ, sinon le meilleur
moment et jusqu'à 3 alternatives espacées de 90 min, avec une frise des 24 h. Le
plafond hebdomadaire est une **estimation** (une semaine pleine vaut environ
10 fenêtres) ; les comptes en erreur sont ignorés et la pause est signalée.

## Ne pas déranger

**Réglages → Ne pas déranger** : une plage de silence (22:00 à 08:00 par défaut,
jours au choix, passage de minuit) pendant laquelle les notifications sont
retenues, puis un seul résumé « Fin du silence » dit combien il y en a eu. Le
menu de l'icône (« Ne pas déranger » : 1 heure, 4 heures, Jusqu'à demain 08:00,
Reprendre les notifications), `ccs quiet 1h` et le raccourci clavier
Super+Alt+D (désactivé au départ) posent un silence temporaire ; l'indicateur
affiche 🔕 pendant un silence. Restent **toujours** affichées : une session qui attend ta réponse
(sauf si tu le décides dans les Réglages), une session bloquée par une limite, le
résumé et les retours des raccourcis. Une alerte retenue n'est pas renvoyée
après : seulement résumée.

## Mise à jour en un clic

Quand une nouvelle version est annoncée, le bandeau de la fenêtre (et l'entrée
« Installer CCS x.y.z… » de l'icône) ouvre un dialogue : notes de la release,
téléchargement, **vérification de la somme SHA-256**, installation (fenêtre de
mot de passe de `pkexec`), puis « Redémarrer l'application ». Détails et
sécurité : [docs/utilisation.md](docs/utilisation.md#mises-à-jour) ; en
ligne de commande : `ccs update`.

## Dans Claude Code

`ccs integration on` ajoute deux choses à Claude Code (dans `~/.claude/settings.json`,
avec une sauvegarde ; une ligne d'état que tu aurais déjà n'est jamais remplacée) :

- **une ligne d'état** en bas de chaque session :
  `◑ perso 53 % ↻17:20 · ⏱14:21 · sem. 51 % · 2 comptes` — compte actif,
  session, recharge, limite estimée, semaine, et le meilleur compte quand il
  faut changer (« → sonnet ? » près des limites avec un modèle cher) ;
- **la bascule après blocage** : si une session atteint malgré tout la limite,
  CCS bascule aussitôt sur le meilleur autre compte et te prévient — tape
  « continue » et la session repart (dans le terminal intégré, CCS peut
  l'envoyer pour toi). En pause, la notification le dit et rien ne bascule.
- **la relance quand la limite est levée** : si aucun autre compte n'est libre
  (ou pendant une pause), CCS calcule quand la limite se lève (fin de la fenêtre
  de 5 h ou de la semaine, ou retour d'un autre compte sous les seuils) et
  affiche « relance prévue à HH:MM » dans l'onglet ou le chat. À l'heure dite,
  il vérifie, change de compte si c'est un autre qui s'est libéré, et envoie
  « continue » : onglets du terminal et chats du bureau, chats du web,
  d'Android, de l'iPhone et de la TUI, et `claude` lancé à la main dans un
  terminal de la version web. Une seule bascule et une seule notification pour
  toutes les sessions bloquées ensemble, un seul « continue » par session (au
  plus 3 par heure), rien si tu as écrit dans la session entre-temps. Une
  session ouverte ailleurs reçoit une notification ; une conversation fermée
  peut être relancée en arrière-plan (`claude --resume … -p continue`, sortie
  dans `~/.claude-accounts/limits/<id>.log`). Réglages : « Relance après une
  limite » (bureau) ou « Chat et sessions » (web, téléphone), clé
  `limit_resume` de `settings.json` :
  `{"enabled": true, "outside": "notify"}` (`"resume"` pour la relance en
  arrière-plan).

`ccs integration off` retire tout ce que CCS a ajouté, et seulement cela.

## Sessions Claude sur le PC

L'onglet **Sessions** réunit les sessions ouvertes et l'historique des
conversations. À gauche, tes projets (« Tous les projets » en tête, ceux où une
session tourne d'abord) : un point vert quand une session y est ouverte, bleu
quand elle attend ta réponse, le nombre de conversations et le compte du
projet. À droite, le projet choisi : les sessions **ouvertes maintenant** —
terminal ou VS Code : état (*travaille*, *attend ta réponse*, *au repos*),
depuis quand, modèle, consommation et coût — puis **ses conversations**,
groupées par date. La recherche et le filtre d'origine (VS Code ou terminal),
en haut, valent pour tout, liste des projets comprise ; ☰ masque ou affiche
les projets (repliés d'office en fenêtre étroite). `ccs sessions` et le
sous-menu de l'icône listent aussi les sessions ouvertes.

Tu peux ouvrir un terminal ou le dossier du projet, terminer une session
oubliée, reprendre une conversation ou en démarrer une nouvelle dans un
projet. Une notification te prévient quand une session **a terminé** ou
**attend ta réponse** — pratique quand plusieurs tournent en parallèle ; un clic
dessus (ou « Afficher ») ouvre l'application sur l'onglet de la session, et un
rappel unique part si ta réponse se fait attendre plus de 10 min. Le badge de
l'onglet Sessions compte les sessions qui t'attendent.

Le menu de l'icône a aussi un sous-menu **Sessions** (« Sessions (1 attend ta
réponse) » ou « Sessions (n) ») : une entrée par session (titre, état, depuis
quand), celles qui attendent d'abord ; un clic l'ouvre dans l'application. Il
propose aussi « Toutes les sessions… » et « Terminal ou dossier d'une
session », et l'indicateur affiche « · 💬 n » quand n sessions attendent.

**Nouvelle session…** (bouton de l'onglet Sessions, menu ☰ de la fenêtre,
« Avec des options… » dans le menu « Nouvelle session » d'un projet, ou
`claude-accounts app --new-session`) ouvre un dialogue : dossier,
compte (celui du projet est présélectionné), modèle (`--model`) et mode de
permissions (`--permission-mode`). Si tu choisis un autre compte que le compte
actif, CCS bascule avant de lancer la session — et toutes les sessions ouvertes
suivent, le dialogue te le rappelle. Le mode « Aucune vérification »
(`bypassPermissions`) reste proposé, avec un avertissement en rouge.

## Compte par projet

Le compte « boulot » pour les projets du travail, « perso » pour le reste ?
Associe un dossier à un compte : `ccs project ~/Work/App boulot`, ou « Compte de
ce projet… » en tête d'un projet de l'onglet Sessions. Les sous-dossiers
héritent du compte de leur dossier parent.

Quand tu ouvres une session ou reprends une conversation de ce projet depuis
l'application alors qu'un autre compte est actif, CCS demande : **Basculer et
ouvrir**, **Ouvrir sans basculer** ou **Annuler** (case « Ne plus demander pour
ce projet »). Le compte actif est commun à toutes les sessions : basculer les
fait toutes passer sur ce compte. « Nouvelle session… » présélectionne le
compte du projet. Pendant une pause, rien n'est proposé ni présélectionné.

## Chat graphique

Une session Claude de CCS est un **chat** : tes messages à droite, les réponses
de Claude à gauche en Markdown mis en forme (titres, listes, tableaux, code
coloré, liens), qui arrivent au fil de l'eau. Chaque action de Claude (fichier
lu ou modifié avec son `+12 −3`, commande lancée, recherche, sous-agent) est une
**carte repliable** ; sa liste de tâches reste épinglée au-dessus de la saisie, comme
dans l'extension VS Code. Quand Claude lance des **sous-agents**, chacun a sa pastille
au-dessus du fil et sa propre vue (ce qu'il lit, lance et répond), sur le bureau comme
sur le web. Au bureau, la pastille reste avec ✓ quand il a fini ; sur le web, elle quitte
la barre et le bouton « Terminés (n) » garde l'historique des sous-agents finis. Sa carte
dans le fil garde un bouton « Voir ».

- **Barre cliquable** sous la zone de saisie : **modèle**, **effort** (faible à
  max ; les niveaux que le modèle n'accepte pas sont grisés), **ultracode**
  (bouton à bascule) et **droits** (Demander, Modifications acceptées, Plan,
  Tout autoriser, ce dernier avec un avertissement). À droite : le contexte
  utilisé et le compte, avec sa couleur.
- **Autorisations** : quand Claude demande la permission, une carte propose
  **Autoriser**, **Toujours** (écrit la règle exacte dans le
  `.claude/settings.local.json` du projet) ou **Refuser** (motif facultatif).
  Le badge de l'onglet et l'alerte « attend ta réponse » se déclenchent.
- **Saisie** : Entrée envoie, Maj+Entrée va à la ligne, Maj+Tab change les droits,
  1 / 2 / 3 répondent à une autorisation, `@` propose les fichiers
  du projet, `/` les commandes de Claude Code, une image collée ou glissée
  s'ajoute au message, un fichier glissé depuis l'arbre insère `@chemin`.
  **Arrêter** (ou Échap) interrompt Claude ; un message écrit pendant qu'il
  travaille rejoint la **file de messages** et part quand il a fini.
- **Répondre en citant** : comme dans une messagerie, « Répondre » sur un message (le tien
  ou celui de Claude) le cite au-dessus de la saisie ; Claude le reçoit avec ta réponse. Si
  du texte est sélectionné dans le message, seul ce passage est cité.
- **Étiquettes sur les messages** : « Étiqueter » pose un ou plusieurs mots-clés
  (« important », « à revoir »…) sur un message ; ils s'affichent sous le message, et le
  volet « Étiquettes » liste les messages par étiquette et ramène à chacun.
- **Chercher dans le fil** : Ctrl+F ouvre une barre de recherche dans la conversation.
- **Aller en bas** (web) : le fil suit la réponse tant que tu restes en bas ; si tu remontes lire,
  un bouton rond apparaît en bas à droite pour y revenir d'un appui.
- **Messages enregistrés** : des textes que tu envoies souvent, communs à tous les projets
  ou propres au projet ; le menu ☆ de la saisie les insère, et `/` les propose aussi.
- **Compacter** : l'alerte de contexte lourd du chat a un bouton « Compacter » qui envoie
  `/compact`. Avec le réglage **Compacter automatiquement** (désactivé par défaut), CCS
  l'envoie tout seul au-delà du seuil, entre deux tours, et le dit dans le fil.
- **`/clear`** : une ligne « Nouvelle conversation » sépare les anciens messages, gardés
  lisibles mais grisés (Claude ne les voit plus). Une commande `/…` part toujours seule : une
  citation ou la sortie d'une commande `!` en attente restent pour le message suivant (sinon
  Claude Code n'y verrait que du texte).
- **Effacement automatique** (réglage `chat.auto_clear`, activé par défaut) : quand un sujet
  est vraiment fini (travail commité et publié, mémoire et feuille de route à jour), Claude
  lance `ccs chat clear` ; CCS envoie `/clear` dès la fin de son tour (jamais pendant qu'un
  sous-agent de fond tourne), et le séparateur dit « Sujet terminé : Claude a effacé la
  conversation ». Moins de contexte, donc moins de quota par message.
- **Nouvelle version du serveur** (web) : une page restée ouverte pendant une mise à jour
  propose « Recharger », pour ne pas garder l'ancien code.
- **Commande `!`** : un message qui commence par `!` lance la commande dans le dossier du
  projet (elle ne part pas chez Claude). Sa sortie s'affiche dans une carte et s'ajoute en
  tête du prochain message envoyé à Claude.
- Un chat qui reste **30 minutes** au repos met son processus `claude` en veille
  (réglage `chat.idle_suspend_min`, 0 = jamais) ; il repart tout seul au message
  suivant, sur la même conversation. Rien n'est fermé : l'onglet, l'historique
  et la file restent.
- **Ouvrir cette conversation dans un terminal** (menu de l'onglet) : sortie de
  secours pour les commandes interactives de Claude Code ; « Revenir au chat »
  rouvre le chat ensuite. Les onglets **shell** restent de vrais terminaux.

## Fichiers et feuille de route d'un projet

Chaque onglet de session a, à gauche, deux pages : **Fichiers** et **Feuille de
route**. L'arbre montre le dossier du projet avec les marques git (`M`, `A`, `?`,
`D`) et se met à jour quand des fichiers changent. Un clic ouvre le fichier à
côté du chat : coloration, numéros de ligne, recherche (Ctrl+F), images, et pour
le Markdown une bascule **Source / Aperçu**. Ctrl+S enregistre. Quand Claude
modifie un fichier ouvert, il se recharge ; si tu avais des changements non
enregistrés, un bandeau te laisse choisir. « Voir le diff » sur une carte de
modification montre ce que Claude a changé. Deux dispositions (bouton de la
page Sessions) : **B**, arbre | chat | fichier (par défaut), ou **A**, arbre |
fichier | chat, comme VS Code. Les séparations se tirent à la souris ; Ctrl+B
replie l'arbre.

Dans la **version web**, le volet Fichiers sert aussi à gérer les fichiers du projet :

- **+ Fichier**, **+ Dossier** et **Envoyer** (un ou plusieurs fichiers du téléphone ou du PC)
  agissent à la racine du projet ;
- le bouton **⋯** d'un fichier propose Télécharger, Renommer et Supprimer ; celui d'un dossier
  propose d'y créer un fichier ou un dossier, d'y envoyer un fichier, de le télécharger en entier
  (.zip), de le renommer ou de le supprimer ;
- chaque fichier de l'arbre, et le fichier ouvert, a son bouton **⤓** pour le télécharger d'un appui ;
- **Copier** ou **Couper** dans le menu **⋯**, puis **Coller ici** sur le dossier de destination
  (ou le bouton **Coller** en haut) : copie ou déplace un fichier ou un dossier.

L'onglet **Fichiers** de la barre de navigation est un **gestionnaire de fichiers** : il parcourt
ton dossier personnel et les dossiers web du serveur (`/var/www`, `/srv`) avec les mêmes actions,
sans passer par un projet. Le bouton **Ajouter aux projets** (ou « Ajouter aux projets de CCS »
dans le menu **⋯** d'un dossier) met un dossier dans la liste des projets de CCS.

**Tous les appareils** : en haut de l'onglet, une puce par appareil — le serveur CCS et chaque PC
du réseau maillé où CCS est installé (grisé s'il est hors ligne). Choisir un PC ouvre ses dossiers
par une connexion à part, relayée par le serveur (SSH par le réseau maillé, Ricochet en secours),
sans changer la machine pilotée. Le dernier appareil choisi est gardé ; adresse
`#/fichiers/@<machine>/<chemin>`. Les téléphones n'ont pas de CCS : on n'y parcourt pas de
dossiers. Le trafic est chiffré de bout en bout (WireGuard, puis SSH ou TLS par-dessus).

Un transfert va jusqu'à 200 Mo. Une suppression demande toujours confirmation et elle est
définitive (pas de corbeille) ; le dossier du projet lui-même ne peut être ni renommé ni
supprimé d'ici.

La **feuille de route** lit le `ROADMAP.md` du projet : phases avec barre de
progression, tâches en cases à cocher. Un clic sur une case la coche dans le
fichier, en ne changeant que ce caractère. Le bouton ▶ d'une tâche propose **Faire
maintenant** (Claude la fait dans le chat) ou **Mettre dans la file de nuit**. Si Claude
finit son tour sans avoir coché la case, un bandeau « Tâche finie ? » propose de la cocher.

Le bouton « Changements de la session » ouvre le volet des **fichiers que Claude a modifiés**
depuis le début de la conversation, d'après les copies que Claude Code garde de chaque
fichier. Tu y vois le diff de chaque fichier, tu peux **annuler un fichier** ou **revenir à
avant un message**. Ces copies n'ont pas de format documenté : si Claude Code le change, le
volet n'offre plus rien et `ccs doctor` le signale (ligne « Historique des fichiers »).

## Page Git

Une troisième page à gauche, **Git**, inspirée de GiGit :
elle montre la branche (avance / retard) et les changements en cours du dépôt du projet.

- **Indexer** un fichier, un bloc ou des lignes choisies ; **Tout indexer** ; annuler les
  modifications d'un fichier ou des lignes choisies (après confirmation) ; ajouter au
  `.gitignore`.
- **Commit** (Ctrl+Entrée), avec **Proposer** pour un message suggéré et « Modifier le dernier
  commit » (amend).
- **Fetch**, **Pull** et **Push** par la commande `git` de ton système (ta configuration, tes
  clés SSH et tes hooks comptent comme dans un terminal). Le **push forcé** est gardé : il
  demande confirmation et refuse d'écraser un commit distant que tu n'as pas vu.
- **git flow** : démarrer et finir une `feature`, une `release` ou un `hotfix` depuis le menu de
  la branche (grisé si git flow n'est pas installé).
- **Graphe des commits**, chargé par pages ; un clic ouvre le détail d'un commit (diff,
  parents). Avatars des auteurs d'après GitHub ou Gravatar, gardés en cache.
- **Trois dispositions** : A (changements puis graphe compact à gauche), B (changements à
  gauche, graphe en cartes dans l'onglet « Historique » à droite) et C (comme A avec le
  graphe en cartes, panneau de gauche élargi).

Réglages dans `settings.json` (`git`) : `layout` (`A`, `B` ou `C`), `fetch_minutes` (fetch
automatique, 5 par défaut, 0 = jamais) et `avatars` (faux : aucune image demandée sur le
réseau).

## Navigation et apparence

Six onglets en haut, comme la version web : **Accueil** (comptes, derniers événements,
planning et file de tâches), **Sessions**, **Réseau** (appareils du réseau maillé, machines,
travaux distants, secours Ricochet), **Fichiers** (arbre d'un dossier et éditeur), **Jarvis**
(ouvre la page Jarvis du serveur CCS dans le navigateur) et **Analyse** (analyse et historique) ;
**Réglages** est dans le menu ☰. Raccourcis : Ctrl+1 à Ctrl+6 pour les onglets,
Ctrl+virgule pour les réglages. Le thème suit le système (ou clair, sombre au
choix) et chaque compte a **sa couleur**, reprise sur les cartes, les jauges, les
courbes et la barre du chat (Réglages → Apparence). Les anciens noms de page
(`comptes`, `planning`, `terminaux`, `historique`…) restent acceptés par
`claude-accounts app --page`.

## Terminal intégré et onglets de session

Reprendre une conversation ou démarrer une session l'ouvre **dans la fenêtre de
l'application**, dans un onglet de l'onglet Sessions : un chat pour Claude (voir
plus haut), un terminal pour un shell (« Terminal ici ») ou pour « Ouvrir cette
conversation dans un terminal ». Plusieurs sessions tiennent en onglets ; chaque onglet porte le titre de la conversation
et montre si Claude **travaille**, **attend ta réponse** ou s'est arrêté.

- **Ctrl+Maj+C / Ctrl+Maj+V** pour copier et coller (ou clic droit),
  **Ctrl+clic** sur un lien (adresse de connexion de Claude, par exemple),
  Ctrl+plus / Ctrl+moins pour la taille du texte ; police à chasse fixe du
  bureau, couleurs qui suivent le thème clair ou sombre.
- Quand Claude s'arrête, un bandeau propose **Reprendre** (la même
  conversation) ou **Fermer**. Fermer un onglet ou la fenêtre pendant qu'une
  session tourne demande confirmation : la conversation est enregistrée, tu
  pourras la reprendre.
- Une session déjà ouverte dans l'application se retrouve par **Afficher**
  depuis l'onglet Sessions. Le terminal externe reste
  disponible dans les menus « ⋮ », et « Terminal ici » ouvre un shell dans un
  onglet.
- **Reprise automatique après une limite** (avec `ccs integration on`) : quand
  une session d'un onglet est bloquée, CCS bascule sur un autre compte puis
  tape « continue » à ta place, une seule fois, dès que Claude attend une
  nouvelle demande — jamais si tu as écrit dans l'onglet entre-temps, ni
  pendant une pause. Interrupteur dans le menu « ⋮ » de la page Terminaux.
- **Côte à côte** (Ctrl+Maj+E) : deux sessions dans la même vue, séparation
  réglable.
- **Messages en attente** (Ctrl+Maj+M) : prépare la suite pendant que Claude
  travaille ; chaque message part quand il a fini son tour, un par tour.
- **Onglets rouverts** : au redémarrage de l'application, un bandeau propose de
  rouvrir les sessions de la dernière fois (conversations reprises avec leurs
  options et leurs messages en attente), ou c'est automatique si tu l'as
  choisi dans le menu « ⋮ ».

Le terminal intégré utilise VTE (`gir1.2-vte-3.91`, dépendance du paquet). S'il
manque, tout s'ouvre dans un terminal externe comme avant et l'onglet Sessions
indique la commande à lancer : `sudo apt install gir1.2-vte-3.91`.

## Renommer une conversation

« Renommer… » (onglet Sessions, menu d'un onglet du terminal, clic droit sur un onglet de la
version web)
ou `ccs title <identifiant> <titre>` donne un titre à une conversation, comme
`/rename` dans Claude Code : le titre est enregistré dans la conversation et
s'affiche partout, VS Code compris.

## Historique des conversations

L'onglet **Sessions** (« Tous les projets » pour tout voir) et `ccs conversations` listent
**toutes** les conversations Claude Code du PC, comme la liste des conversations
passées de l'extension VS Code, mais tous projets confondus : titre (celui que
tu as donné, sinon le titre automatique de Claude Code, sinon ta première
demande), projet, origine (VS Code ou terminal), branche, nombre de demandes,
date. Recherche sans accents ni majuscules, filtres par projet et par origine,
groupes *Aujourd'hui*, *Hier*, *7 derniers jours*…

Un clic reprend la conversation **dans VS Code** (la fenêtre du projet s'ouvre et
l'extension Claude Code y rouvre la conversation) ou **dans l'application**
(`claude --resume` dans un onglet du terminal intégré ; un terminal externe reste
au menu « … »). Une conversation déjà ouverte ailleurs n'est pas relancée
une seconde fois. Si le projet a été **déplacé**, CCS propose le dossier du même
nom qu'il retrouve et, après confirmation, y copie le journal de la conversation
pour qu'elle reprenne depuis là (l'original reste en place).

**Aperçu…** (menu « ⋮ » d'une conversation ou d'une session) relit une
conversation sans la reprendre : tes demandes, les réponses de Claude, les
outils utilisés en une ligne. Tu peux la copier ou l'**exporter en Markdown**.
Chaque conversation affiche aussi son **coût** (« ≈ 3,40 $ », tokens au
survol) : tokens consommés (sous-agents compris) et ce qu'elle aurait coûté au
tarif de l'API. Ton abonnement ne facture pas au token : ce montant sert
seulement à comparer les conversations.

```bash
ccs conversations                 # les 30 dernières conversations, groupées par date
ccs conversations export csv      # recherche
ccs conversations -p Portail      # un projet
ccs resume 4f3a          # reprend ici (4 premiers caractères de l'identifiant)
ccs resume 4f3a --vscode # ou dans VS Code
ccs title 4f3a Export CSV des prêts   # renomme la conversation
ccs preview 4f3a | less  # relit la conversation (Markdown, coût en en-tête)
ccs export 4f3a          # l'enregistre en Markdown (<titre>.md ici)
```

## Journal des bascules

Pourquoi CCS a-t-il changé de compte ? L'onglet **Historique** (et
`ccs log`) raconte chaque bascule, groupée par jour, avec sa raison en
clair :

```
Aujourd'hui
  16:40    boulot → perso  Bascule après un blocage (limite atteinte dans Portail)
  14:02    perso → boulot  Bascule automatique avant la coupure (perso à 98 %)
  11:30    boulot → perso  Bascule anticipée de l'orchestrateur : perso allait perdre 42 % de quota dans 35 min
  09:15  ✗ perso → boulot  Échec de la bascule manuelle vers boulot : …
```

Bascules automatiques, anticipées par l'orchestrateur, après un blocage (avec
le projet de la session bloquée), manuelles (et d'où elles viennent :
application, icône, notification, commande `ccs`, raccourci clavier, nouvelle
session, compte du projet), échecs, limites atteintes sans bascule et
démarrages de fenêtre. Filtre 7 jours, 30 jours ou tout ; aussi « Journal des
bascules » dans le menu de l'icône.

## Vocal : dicter et écouter les réponses

Sur toutes les interfaces, un **micro** dans la saisie dicte le message : le texte
s'écrit dans la saisie, tu relis puis tu envoies. **« Lire »** sur une réponse de
Claude la lit à voix haute (sans le code ni les adresses) ; un second appui arrête.
Le réglage **« Lire les réponses à voix haute »** lit chaque réponse à la fin du
tour de Claude.

| Interface | Dictée | Lecture | Réglage |
|---|---|---|---|
| Web | reconnaissance du navigateur (Chrome, Edge, Safari ; pas Firefox) | voix du système | Réglages → Voix (gardé dans le navigateur) |
| Bureau | Whisper en local (`pip install --user faster-whisper` ; modèle `small` téléchargé à la première dictée, `CCS_WHISPER_MODEL` pour en changer) | speech-dispatcher (`spd-say`) | Réglages → Chat et fichiers (`chat.read_aloud`) |
| Android | reconnaissance vocale du téléphone | voix française d'Android | Réglages → Vocal |
| iPhone | reconnaissance d'iOS (autorisations micro et reconnaissance) | voix française d'iOS | Réglages → Voix |

Au bureau, le bouton micro n'apparaît que si `faster-whisper` et un outil
d'enregistrement (`pw-record`, `parecord` ou `arecord`) sont présents ; rien ne
quitte la machine.

## Commandes root sans terminal

Claude (ou toi) lance une commande root par CCS, sans rester bloqué sur une invite de `sudo` :

```bash
ccs root -- apt install ripgrep
ccs root status       # mot de passe gardé ? combien de temps encore ?
ccs root forget    # l'effacer tout de suite
```

- Si CCS n'a pas le mot de passe, une fenêtre le demande sur **tous tes appareils** connectés :
  version web, application de bureau, TUI, Android, iPhone. Une notification ntfy prévient
  (sans aucun secret) ; la toucher ouvre la fenêtre dans l'appli, sur la bonne machine. Le premier
  appareil qui répond l'emporte, les autres fenêtres se ferment. « Refuser » abandonne la commande.
- Le mot de passe est vérifié par `sudo`, puis gardé **pour toujours, chiffré** (AES-256-GCM) par
  le pont de la machine : clé dans `~/.config/ccs/root.key`, chiffré dans
  `~/.local/state/ccs/root.vault` (0600 tous les deux, dossiers séparés), lié à la machine
  (`/etc/machine-id`) et au compte. Il survit aux redémarrages ; relu, il est revérifié par `sudo`
  avant le premier usage (redemandé s'il a changé). Jamais en clair sur disque ni dans un journal.
  Limite : un programme lancé sous ton compte peut lire la clé ; le chiffrement protège le disque,
  les sauvegardes et les copies. 3 essais par demande ; une demande sans réponse abandonne après
  5 minutes.
- Chaque commande root est signalée sur tes appareils, avec un bouton « Révoquer » qui efface le
  mot de passe et le coffre (`ccs root forget` aussi).
- Chaque machine (VPS, PC…) garde son propre mot de passe. Les chats lancés par CCS ont
  `SUDO_ASKPASS` : `sudo -A` y marche aussi, mais `ccs root` reste préférable (chaque commande
  y est signalée).

## Autres fournisseurs de modèles (OpenRouter, DeepSeek…)

Claude Code peut tourner sur un autre service que Claude, pour des modèles ouverts moins filtrés
ou moins chers. CCS le lance avec `claude --settings '<json>' --model <id>` : adresse du service
(`ANTHROPIC_BASE_URL`), même modèle derrière opus, sonnet, haiku et les sous-agents, et
`apiKeyHelper` qui lit la clé dans son fichier. La clé n'apparaît jamais dans la ligne de commande.
Les comptes Claude ne sont pas concernés (pas de bascule ni de quota pour ces sessions).

```sh
ccs provider                      # fournisseurs connus et état de leur clé
ccs provider key openrouter       # enregistre la clé (sans écho) dans ~/.config/openrouter/cle, droits 600
ccs provider test openrouter      # envoie « ok » au modèle par défaut (quelques jetons)
ccs provider models openrouter glm   # catalogue du moment, filtré (« free » : gratuits)
ccs task add "…" --provider openrouter --model x-ai/grok-4.7
```

Dans l'appli (Nouvelle session) et sur le web (nouvelle session, options du chat), choisir le
fournisseur puis le modèle. Un fournisseur sans clé est signalé et refusé avant le lancement.

Préréglages (modèles avec appel d'outils, indispensable à Claude Code ; prix du 24/11/2026,
$ par million de jetons entrée/sortie) :

| Fournisseur | Modèles | Clé |
|---|---|---|
| `openrouter` (compatible Anthropic) | DeepSeek V4.1 Flash 1017 `:floor` (défaut, le moins cher : hébergeur le moins cher choisi par OpenRouter, ~0,03-0,05/0,10-0,50 avec cache), GLM 5.3 (~1,40/4,40 selon l'hébergeur), Grok 4.7 (2/6), Kimi K3.1 Pro, Qwen3 Coder Next… | `~/.config/openrouter/cle` |
| `deepseek` (API directe compatible Anthropic) | `deepseek-flash` (0,30/1,20, -50 % en heures creuses), `deepseek-v4-pro` | `~/.config/deepseek/cle` |
| `venice` (compatible OpenAI, par le proxy intégré) | `deepseek-v4-1-flash-1017-uncensored` (défaut), `qwen-3-6-plus`, `glm-5-3-flash-uncensored`, `venice-uncensored` | `~/.config/venice/cle` |

Budget : plafonner la clé chez le fournisseur (sur OpenRouter, « limit » de la clé, par exemple
50 $). Claude Code réserve 32 000 jetons de sortie par requête : avec très peu de crédit, une
requête peut être refusée (402) ; `ccs provider test` se limite à 256.

Ajouter ou modifier un fournisseur : `~/.config/ccs/providers.json`, par exemple

```json
{"ollama": {"label": "Ollama", "base_url": "http://100.64.0.5:11434", "key_file": null,
            "models": [["Qwen3 Coder 30B", "qwen3-coder:30b"]]},
 "openrouter": {"default_model": "x-ai/grok-4.7"}}
```

`key_file` null : service sans clé. Le service doit parler l'API Anthropic (`/v1/messages`),
ou, avec `"api": "openai"`, l'API OpenAI (`/chat/completions`, `base_url` sans `/chat/completions`) ;
`extra_body` ajoute des champs à chaque requête (Venice : `venice_parameters`).

Services compatibles OpenAI (Venice…) : CCS lance à la demande un petit proxy local
(`ccs_app/openai_proxy.py`, sans dépendance) sur `127.0.0.1:47447` (variable
`CCS_OPENAI_PROXY_PORT`), qui traduit `/v1/messages` en `/chat/completions` (outils et streaming
compris). La clé n'est jamais lue par le proxy : Claude l'envoie, le proxy la transmet. Il s'arrête
seul 90 s après la dernière session qui l'utilise. `ccs provider proxy` : état ;
`ccs provider proxy stop` : l'arrêter. Journal : `~/.cache/ccs/openai-proxy.log`.

## Raccourcis clavier

Des raccourcis **globaux**, qui marchent même application fermée, tous
désactivés au départ : **Réglages → Raccourcis clavier**, ou
`ccs shortcuts on`.

| Action | Raccourci | Commande |
|---|---|---|
| Ouvrir CCS | Super+Alt+C | `claude-accounts app` |
| Afficher les sessions | Super+Alt+V | `claude-accounts app --page sessions` |
| Nouvelle session | Super+Alt+N | `claude-accounts app --new-session` |
| Basculer sur le compte suivant | Super+Alt+B | `ccs next --notify` |
| Basculer sur le meilleur compte | Super+Alt+M | `ccs best --notify` |
| Pause 1 h | Super+Alt+P | `ccs pause 1h --notify` |
| Reprendre (lever la pause) | Super+Alt+R | `ccs pause off --notify` |
| Ne pas déranger 1 h | Super+Alt+D | `ccs quiet 1h --notify` |

Dans la fenêtre : Ctrl+1 à Ctrl+3 (onglets), Ctrl+virgule (réglages), Ctrl+B
(replie l'arbre des fichiers), Ctrl+S (enregistre le fichier ouvert), Ctrl+F
(cherche dans le fichier), Ctrl+Maj+E (côte à côte), Ctrl+Maj+M (messages en attente).

Sans terminal pour le lire, le résultat s'affiche en notification passagère
(« Bascule sur boulot », « Déjà sur perso », « Pause jusqu'à 14:00 »,
« Bascule impossible »…) : c'est l'option `--notifier`. « Modifier » change la
combinaison (ou
`ccs shortcuts set suivant Super+Alt+B`) ; une combinaison déjà prise par le
bureau ou par un autre raccourci est signalée. Ce sont des raccourcis
personnalisés de GNOME (Paramètres › Clavier › Raccourcis personnalisés) : CCS
ne touche qu'aux siens, jamais aux tiens. Sur un autre bureau, CCS affiche les
commandes, à associer toi-même à un raccourci. Des raccourcis activés avec une
version précédente (sans `--notifier`) sont signalés « à mettre à jour » :
bouton **Mettre à jour les commandes** des Réglages, ou `ccs shortcuts on`.

## Bilan de santé

Quelque chose ne marche pas ? `ccs doctor` (ou « Bilan de santé… » dans le menu
☰ de l'application) vérifie le service et ses relevés, la version installée et
celle qui tourne, l'extension et l'icône de la barre du haut, l'intégration
dans Claude Code, la connexion de chaque compte, `claude`, `jq` et le terminal
intégré. Pour chaque problème, il donne **la commande à copier** ; il ne
l'exécute jamais à ta place. Code de sortie : 0 si tout va bien, 1 au moindre
avertissement. L'application fait le bilan à chaque ouverture et affiche un
bandeau « Un problème a été détecté… — Voir le bilan » en cas d'erreur.

## Fonctionnalités

| | |
|---|---|
| **Profils** | Un profil par compte claude.ai. Bascule instantanée ; réglages, historique, plugins et serveurs MCP restent communs. |
| **Usage de tous les comptes** | Session de 5 h et limites hebdomadaires de chaque compte, sans basculer. |
| **Prévisions** | Fin de session estimée au rythme actuel, fin de semaine prévue au rythme moyen de la semaine, marge sur le rythme de la semaine, budget par jour, capacité restante tous comptes confondus. |
| **Meilleur compte** | Recommandation expliquée : d'abord le quota qui expire le plus tôt, les comptes en réserve en dernier. |
| **Bascule automatique** | À 98 % (réglable) ou si le prochain relevé dépasserait 100 %, vers un compte sous 80 % aux données fraîches. Pas de va-et-vient, bascule manuelle récente respectée. |
| **Orchestrateur** | Enchaînement et décalage des fenêtres, quota qui expire d'abord, réserve hebdomadaire (voir plus haut). |
| **Pause** | Bascule automatique et orchestrateur suspendus 1 h, 4 h, jusqu'à la prochaine plage horaire ou jusqu'à reprise ; levée automatique. |
| **Alertes** | 80 % et 95 % (avec un bouton « Basculer sur … »), fin de session imminente, semaine épuisée dans 2 jours ou moins, bascule effectuée, tous comptes épuisés, compte réinitialisé, connexion expirée, session terminée ou en attente (avec un rappel après 10 min), pause terminée, nouvelle version, conseil de modèle près des limites, bilan de la semaine. Une fois par seuil et par fenêtre. |
| **Conseils** | Conseiller de formule (combinaison Pro / Max / Ultra la moins chère pour ton usage, équivalent API), conseil de modèle près des limites, bilan de la semaine. |
| **Rapport mensuel** | Le mois civil : comptes, activité, tokens, équivalent API, modèles, projets, évolution et tendance ; carte Analyse, notification le 1er du mois, `ccs month`. |
| **Meilleur moment** | Quand lancer une grosse tâche : fenêtres de 5 h disponibles par heure de départ, alternatives, frise des 24 h (section Planning de l'Accueil, `ccs best-time`). |
| **Ne pas déranger** | Plage de silence et silence temporaire : notifications retenues puis résumées en une seule ; les sessions qui attendent et les blocages passent toujours. |
| **Mise à jour en un clic** | Bouton « Installer » du bandeau : téléchargement, SHA-256, `pkexec`, redémarrage de l'application. |
| **Intégration Claude Code** | Ligne d'état dans chaque session, bascule automatique quand une session est bloquée. |
| **Sessions** | Un onglet « Toutes les sessions » : projets à gauche, sessions ouvertes et conversations du projet à droite ; consommation, reprise, nouvelle session (dossier, compte, modèle, permissions), terminal / dossier du projet. |
| **Compte par projet** | Un compte préféré par dossier (sous-dossiers compris), bascule proposée à l'ouverture d'une session, compte présélectionné dans « Nouvelle session ». |
| **Chat graphique** | Les sessions Claude dans des chats : réponses en Markdown, cartes d'actions repliables, demandes d'autorisation (Autoriser / Toujours / Refuser), barre modèle / effort / ultracode / droits, `@` fichiers, `/` commandes, images, file de messages, bouton Arrêter, mise en veille après 30 min, « Ouvrir dans un terminal ». |
| **Panneau Fichiers** | Arbre du projet avec marques git, fichiers ouverts à côté du chat (coloration, aperçu Markdown, édition Ctrl+S, diff des modifications de Claude, conflits signalés), dispositions A et B, volets redimensionnables, Ctrl+B. |
| **Feuille de route** | Le `ROADMAP.md` du projet dans l'onglet de session : phases, barres de progression, cases cliquables ; la case que Claude coche s'allume. |
| **Terminal intégré** | Onglets shell (VTE) et sortie de secours des chats ; deux sessions côte à côte, messages en attente, onglets rouverts au redémarrage (chats compris), reprise après une limite (aussi quand `claude` est lancé à la main dans un onglet shell), copier/coller, liens, confirmation avant fermeture. |
| **Conversations** | Historique de toutes les conversations du PC (onglet Sessions), recherche, aperçu, export Markdown, coût, reprise dans l'application, VS Code ou un terminal externe, renommage, projets déplacés. |
| **Journal des bascules** | Chaque changement de compte avec sa raison en clair, groupé par jour (partie Historique de l'onglet Analyse, `ccs log`). |
| **Raccourcis clavier** | Raccourcis globaux GNOME, même application fermée : ouvrir, sessions, nouvelle session, compte suivant ou meilleur, pause. |
| **Analyse** | Où part l'usage : par projet, modèle, heure et compte, avec des conseils concrets ; gros consommateurs (conversations et cause probable) ; bilan de la semaine et conseiller de formule. |
| **Tokens de chaque réponse** | Sous chaque réponse d'un chat : tokens lus, écrits, produits et coût du tour ; indicateur de contexte coloré ; à l'expiration du cache (5 min ou 1 h), note « Cache expiré » avec Compacter / Nouvelle session et confirmation avant d'envoyer. Bureau, web, Android, iPhone, TUI. |
| **File de tâches** | Des tâches pour Claude quand tu n'es pas là : « dès qu'il y a du quota », « cette nuit » ou à une heure. Exécutées sans fenêtre, une à la fois, par la file de Gagarine quand elle existe ; reprise après une limite ; notification à la fin (section Planning de l'Accueil, `ccs task`). |
| **Notifications sur le téléphone** | Optionnel, désactivé par défaut : via ntfy, le nom du projet et l'état (session qui attend, tâche finie, bascule, comptes épuisés), jamais le contenu ; lien et QR code dans les Réglages, `ccs phone`. Une demande d'autorisation du chat porte les boutons **Autoriser** et **Refuser** (réponse signée, à usage unique, valable 10 min). |
| **Archive des conversations** | Claude Code efface les conversations de plus de 30 jours : CCS en garde une copie compressée, cherchable, avec aperçu, export et reprise comme les autres. |
| **Fiche « où j'en étais »** | En un coup d'œil : dernière demande, début de la dernière réponse, fichiers modifiés, liste de tâches, branche, compte. Lue dans le journal, sans appeler Claude (`ccs recap <id>`, aperçu d'une conversation). |
| **Sauvegarde chiffrée** | Comptes (jetons compris), réglages, comptes par projet et budgets dans un seul fichier chiffré par gpg ; restauration avec confirmation (Réglages, `ccs backup`, `ccs restore`). |
| **Mémoire des sessions** | RAM de chaque session ouverte, total, sessions inactives, bouton « Fermer » avec confirmation ; rien n'est jamais fermé tout seul (onglet Sessions, `ccs sessions`). |
| **Alerte de contexte lourd** | Une notification par session quand son contexte dépasse 150 000 tokens (réglable), avec le coût d'un message ; badge dans l'onglet Sessions et la ligne d'état. **Compactage automatique** des chats au-delà du seuil (activé par défaut, désactivable). |
| **Budget par projet** | Un budget hebdomadaire en équivalent dollars par projet, alertes à 80 % et 100 % ; ne bloque jamais rien (onglet Analyse, `ccs budget`). |
| **Bilan de santé** | `ccs doctor` : service, versions, barre du haut, intégration, comptes, Claude Code, terminal ; une commande à copier par problème. |
| **CCS sur un serveur** | Paquet `ccs-serveur` : version web pour le téléphone (`https://ccs.mawena.cloud`), `ccs tui` dans le terminal, bureau GTK connecté ; connexion par compte Ubuntu et double authentification (TOTP), appareil retenu 30 jours (voir plus haut). |
| **Page Git** | Indexation par fichier, bloc ou ligne, commit et amend, fetch / pull / push (forcé avec garde), git flow, graphe des commits, trois dispositions (voir plus haut). |
| **Changements de la session** | Les fichiers que Claude a modifiés, diff, annulation d'un fichier, retour à avant un message ; « Faire une tâche » depuis la feuille de route. |
| **Application** | « CCS » (GTK 4 / libadwaita) : trois onglets (Accueil, Sessions, Analyse), Réglages dans le menu ☰ ; thème clair ou sombre, couleur par compte. |
| **Icône dans la barre du haut** | Jauge du compte actif (vert / orange / rouge, ⏸ en pause) ; au clic : comptes, recharges, prévisions, sessions, interrupteurs, pause, nouvelle version, journal des bascules, bilan de la semaine. |
| **Service** | Unité systemd utilisateur : relevé toutes les 5 min, toutes les minutes près des limites ; avec l'orchestrateur, réveil précis aux fins de fenêtre ; nouvelle version cherchée une fois par jour. |

## CCS sur un serveur (VPS)

CCS peut tourner sur un serveur pour piloter Claude Code sans être devant le PC :

- **depuis le téléphone ou n'importe quel navigateur** : `https://ccs.mawena.cloud` (version web, installable sur l'écran d'accueil) ; elle fait presque tout ce que fait le bureau (voir plus bas) ;
- **depuis un terminal** : `ccs tui`, par SSH sur le serveur, ou `ccs tui --server <nom>` depuis un autre poste ;
- **depuis l'application GTK du bureau**, connectée aux projets du serveur.

Le même chat, les mêmes sessions : on les retrouve d'un écran à l'autre.

### Ce que fait la version web

Elle est pensée pour le téléphone (chat en plein écran, bouton Retour du téléphone qui
revient d'un chat à la liste, confirmations par cartes, messages brefs en bas) et couvre les
mêmes fonctions que le bureau :

- **Accueil** : comptes avec rythme, prévision et statut lisible, bascule avec confirmation,
  pause, **bilan de santé** (`ccs doctor` avec la commande qui corrige et un bouton Copier),
  **tâches de nuit** (nouvelle tâche, journal, reprise dans un chat, annulation, suppression).
- **Sessions** : section « En cours » (la pastille « attend ta réponse » signale une
  autorisation en attente), écran **Projet** (conversations, fichiers, feuille de route, Git,
  nouveau chat, terminal), **nouvelle session** complète (dossiers récents, dépôts du disque,
  compte, modèle, droits), conversations avec aperçu, renommage, coût et « voir plus ».
  **Projets** : « + Ajouter » (dossier existant ou nouveau, `git init` en option), « ✕ » retire
  un projet de la liste sans rien effacer. **Supprimer** (menu « ⋯ » d'une conversation) la met
  à la **Corbeille** (en bas de la liste) : restaurable 30 jours, puis effacée.
  **Clic droit** (grand écran) sur un onglet ou une ligne « En cours » : Renommer, nouveau chat
  ou terminal dans le projet, ouvrir le projet, copier le chemin, fermer, fermer les autres ;
  sur un projet ou une conversation : ses actions habituelles. Renommer un chat renomme sa
  conversation, et l'onglet suit (titre automatique de Claude Code compris).
  **Arbre des machines** : quand d'autres machines sont connues, la liste devient un arbre, les
  machines à la racine (la machine pilotée d'abord, dépliée ; puis « Ce serveur » et les autres).
  Déplier une machine montre ses projets et conversations ; « + » y ouvre une nouvelle session.
  Les onglets de plusieurs machines restent ouverts côte à côte, chacun sur sa propre connexion
  et marqué du nom de sa machine, sans changer la machine pilotée. Les nœuds dépliés sont gardés
  dans le navigateur.
- **Chat** : options (modèle, effort, droits) repliées, brouillon gardé par chat, diff
  lisible des modifications de Claude, chemins cités ouverts dans le volet Fichiers, complétion
  `@` et `/`, messages enregistrés, Compacter, commande `!`, recherche dans le fil, volet
  « Changements de la session », **répondre en citant un message** (touche le message, puis
  « Répondre »), **étiquettes sur les messages** (« Étiqueter », volet « Étiquettes »).
- **Terminal** : barre de touches (Échap, Tab, Ctrl, flèches, symboles), Coller et Copier.
- **Fichiers** : images, recherche par nom, ouverture à une ligne, édition simple ; **feuille
  de route** avec « Faire une tâche » (dans ce chat, un nouveau chat ou la file de nuit).
- **Git** : état, diff, indexation par fichier et par bloc, commit (amend), derniers commits,
  fetch, pull et push (le push forcé demande confirmation).
- **Analyse** sur 24 heures, 7, 30 ou 90 jours, avec les **gros consommateurs**.
- **Ordre des sessions** : tri de « En cours » et des onglets (ordre manuel, activité récente,
  nom, projet, état), glisser-déposer, « Monter » / « Descendre ».
- **Réglages** : les réglages du bureau, le **téléphone** (ntfy, QR code, essai, « Montrer la
  commande »), le thème et les appareils connectés.
- **Installer comme une application** : un bandeau le propose (bouton Installer sur Chrome ;
  sur iPhone, Partager puis « Sur l'écran d'accueil »), rappelé dans Réglages → Application.

### Installer sur le serveur

```sh
sudo apt install --no-install-recommends ccs-serveur   # sans les paquets graphiques
sudo adduser <utilisateur> ccs                          # qui a le droit de se connecter
```

Seuls les comptes Ubuntu du groupe `ccs` peuvent se connecter ; `root` jamais. Le paquet
installe Claude Code pour l'utilisateur qui installe (jamais en root ; s'il manque
encore, le pont le reprend au premier démarrage). Les services `ccs-auth`, `ccs-web` et
`ccs-bridge@` démarrent seuls.

### Mettre en ligne

1. DNS (Hostinger) : un enregistrement `A`, nom `ccs`, valeur l'adresse IP du serveur.
2. Le site et le certificat, avec lnmp :

   ```sh
   sudo lnmp add --id ccs --domain mawena.cloud --sub ccs --proxy 8420
   sudo lnmp add-ssl ccs
   ```

3. Si le domaine est autre, `/etc/ccs/web.json` : `listen` (par défaut `127.0.0.1:8420`,
   à ne pas ouvrir sur Internet) et `origin` (l'adresse du site, par défaut
   `https://ccs.mawena.cloud`). Puis `sudo systemctl restart ccs-web`.

`ccs doctor` vérifie le tout : services, port, `/api/health`, certificat, groupe `ccs`, Claude Code.

### Première connexion

Ouvre le site, connecte-toi avec ton compte Ubuntu (mot de passe), puis scanne le **QR code**
avec une application d'authentification (TOTP) et saisis le premier code. Ensuite : mot de
passe puis code ; la case « Retenir cet appareil 30 jours » dispense du code, jamais du
mot de passe.

> **Fais cette première connexion juste après l'installation.** Tant qu'aucun code n'est
> enregistré pour un utilisateur, le premier qui se connecte avec son mot de passe l'inscrit.

Code perdu ou téléphone changé : `sudo ccs totp reset <utilisateur>` efface le code,
le prochain accès affiche un nouveau QR code.

### Mode Portier (connexion unique)

Derrière [Portier](https://portier.mawena.cloud) (connexion unique et double facteur pour les
services de mawena.cloud), la version web peut se passer de sa propre page de connexion :
nginx vérifie l'identité auprès de Portier et transmet le nom dans l'en-tête
`X-Portier-Utilisateur`. **Désactivé par défaut.** Dans `/etc/ccs/web.json`, ajoute la clé
`portier` :

```json
{
  "listen": "127.0.0.1:8420",
  "origin": "https://ccs.mawena.cloud",
  "portier": {
    "enabled": true,
    "users": ["charles-gamligo"],
    "url": "https://portier.mawena.cloud",
    "logout": "https://portier.mawena.cloud/"
  }
}
```

| Clé | Rôle |
|---|---|
| `enabled` | `true` pour activer (tout autre valeur : désactivé) |
| `users` | comptes Ubuntu acceptés par l'en-tête (ils doivent aussi être dans le groupe `ccs`, jamais `root`) |
| `url` | adresse de Portier : bouton « Se connecter via Portier » sur la page de connexion, vers `<url>/connexion?retour=<adresse de CCS>` |
| `logout` | facultatif : où renvoie « Déconnexion » (par défaut `<url>/`) |

Les anciennes clés (`actif`, `utilisateurs`, `deconnexion`, avant la 1.0.0) sont encore lues
pendant toute la 1.x.

Puis `sudo systemctl restart ccs-auth ccs-web`. Une requête (HTTP ou WebSocket) est alors
authentifiée sans la page de CCS **seulement si** elle arrive de nginx (`127.0.0.1` / `::1`) et
que l'en-tête porte un nom de la liste ; `ccs-auth` revérifie l'option et la liste avant
d'ouvrir le pont. Sinon, la connexion habituelle (mot de passe et code) reste là : rien ne
casse si Portier est retiré. Les jetons d'appareil (`Authorization: Bearer`, appairage du
bureau et du terminal) passent toujours avant l'en-tête.

Côté nginx, chaque `location` de la version web inclut `snippets/portier-proteger.conf`, qui
écrase l'en-tête : un client ne peut pas le forger. Contrat complet :
`docs/integration.md` du projet Portier.

### Depuis un terminal

```sh
ccs tui                        # sur le serveur (par SSH) : projets, chat, feuille de route, comptes
ccs tui --server <nom>        # depuis un autre poste, serveur appairé
ccs server add ccs.mawena.cloud   # appairage (mot de passe et code) ; ccs server list, ccs server remove <nom>
```

### Depuis le bureau

Réglages → **Serveurs CCS** : ajouter le serveur (adresse, identifiant, mot de passe, code).
La page Sessions a alors une liste de machines en haut à gauche : **Ce poste**, puis chaque
serveur. Sur un serveur :
- **En cours** : les chats qui tournent (lancés du téléphone, du web ou d'un autre PC) ;
  « Rejoindre » ouvre l'onglet, rejoue le fil et le suit en direct, autorisations comprises ;
- **Projets** : Chat, Terminal, « − » pour retirer de la liste ; « + » en haut pour en ajouter
  un (dossier existant ou nouveau, `git init` en option) ;
- **Conversations récentes** : Reprendre, ou la corbeille pour la supprimer ;
- la corbeille du serveur (icône en haut) : restaurer pendant 30 jours.

Sur **Ce poste**, mêmes outils : « Ajouter un projet » et « Corbeille » dans la barre,
« Retirer de la liste… » dans le menu de « Nouvelle session », « Supprimer… » dans le menu
« ⋮ » d'une conversation. Un onglet distant a le panneau de gauche (Fichiers, Feuille de route,
Git) comme un onglet local.

Réseau coupé : un bandeau l'indique, la reconnexion est automatique et les messages tapés
attendent. Après un redémarrage du serveur (mise à jour), l'onglet se rebranche tout seul ;
une autorisation donnée ailleurs (web, téléphone) se fige aussi au bureau.

### Piloter le PC depuis le web

Avec le [calcul réparti](#calcul-réparti--lancer-un-travail-sur-une-autre-machine) réglé sur le
serveur, le bouton **☁ Ce serveur** de la barre du haut de la version web ouvre « Machine
pilotée » : ce serveur, puis les autres machines du relais Ricochet (en ligne ou non, charge).
Choisir le PC fait passer **tout** le web sur lui : sessions et chats, fichiers, feuille de
route, Git, terminal. Le bouton prend alors la couleur d'accent et le nom du PC ; le choix est
gardé dans le navigateur. Retour au serveur : même bouton, « Ce serveur ».

Comment : le pont du serveur ouvre `ssh` par le tunnel Ricochet et branche la connexion sur le
pont CCS local du PC (celui de l'application de bureau, lancé s'il ne tourne pas) : les chats
sont donc les mêmes qu'au bureau. Il faut le PC allumé, CCS installé dessus et le tunnel SSH
du calcul réparti. Si le PC ne répond pas, un bandeau donne la raison et le web réessaie seul.

### Parler à Jarvis

La page **Jarvis** (🎙) de la version web parle à [Jarvis](https://github.com/mawena/Jarvis),
l'assistant vocal de la maison, d'où qu'on soit : le pont du serveur ouvre le tunnel Ricochet
vers la machine du cerveau (`laptop-maison`, port 7341 par défaut) et relaie le son.

1. Sur la machine de Jarvis : le port 7341 autorisé dans le `[tunnel]` de l'agent Ricochet,
   puis `jarvis pair`.
2. Dans la page Jarvis : colle l'adresse `jarvis://pair?…` affichée (ou le code et l'empreinte),
   puis **Appairer**. Le jeton reste dans ce navigateur ; l'empreinte est gardée sur le serveur.
3. **Parler à Jarvis** : maintiens le bouton pendant que tu parles, ou touche-le une fois
   (l'écoute s'arrête quand tu te tais). La réponse s'affiche et la voix de Jarvis est jouée.

Machine et port du cerveau : « Où est le cerveau de Jarvis ? » en bas de la page (réglages
`jarvis.machine` et `jarvis.port`). Retirer un appareil : `jarvis unpair <nom>` sur la machine
de Jarvis.

Dans les applis **Android** et **iPhone** : Plus → **Parler à Jarvis** (même bouton, même
relais, jeton de l'appli). L'appareil photo du téléphone ouvre directement CCS sur le QR code de
`jarvis pair` (lien `jarvis://pair?…`) ; un raccourci « Parler à Jarvis » (raccourci d'appli
Android, App Intent sur iPhone) ouvre l'écran déjà en écoute.

Dans l'appli du **bureau** : menu principal → **Parler à Jarvis…** ouvre cette page web sur le
premier serveur CCS appairé (le micro passe par le navigateur).

Pour une autre oreille : WebSocket `wss://<serveur>/api/jarvis/oreille?fp=<empreinte>`
avec la session CCS ou `Authorization: Bearer <jeton d'application>`. Le premier message
(`pair` ou `hello` du protocole des oreilles de Jarvis) doit partir dès l'ouverture ; tout est
ensuite relayé tel quel dans les deux sens (texte JSON, trames de son binaires `0x01` + phrase
u32 + PCM 16 kHz i16, 16 000 échantillons au plus par trame). Une oreille « bouton » envoie
`wake` avec `score: 2.0`, `level_db: 0`, `muted: false`, le son, puis `listen_end`. Jarvis
injoignable : message `{"type": "relay_error", "message": …}` puis fermeture 4011.

Jarvis peut aussi piloter tout le réseau CCS (sessions et sous-agents de toutes les machines,
arrêt avec confirmation, lancement d'une session, machines et travaux) par les méthodes
`jarvis.state`, `jarvis.sessions`, `jarvis.subagents`, `jarvis.stop_subagent`,
`jarvis.stop_session` et `jarvis.start_session` du pont : voir [docs/jarvis.md](docs/jarvis.md).

### Limites à connaître

- Retirer un serveur dans le bureau **ne révoque pas** son jeton sur le serveur : fais-le dans la version web, Réglages → Appareils.
- La Git de la version web liste les derniers commits sans graphe ni avatars, et indexe par fichier et par bloc (pas par ligne) ; git flow, l'annulation d'un fichier et le `.gitignore` restent au bureau.

Fonctionnement et sécurité : [docs/architecture.md](docs/architecture.md) ; pas à pas : [docs/utilisation.md](docs/utilisation.md).

## Réseau : tous les appareils comme sur un réseau local

Tous les appareils (VPS, PC, téléphones) sont reliés par un réseau maillé WireGuard. Le serveur de
coordination est **Headscale**, sur le VPS (`https://network.mawena.cloud`), et chaque appareil
fait tourner le client `tailscale`. Chacun reçoit une adresse fixe (100.64.x.x) et un nom
`<appareil>.mesh.mawena.cloud`.

Chaque liaison prend toute seule le meilleur chemin, et le revoit quand un appareil change de
réseau :
1. **réseau local**, si les deux appareils y sont ensemble ;
2. sinon **direct par internet** (percement de NAT) ;
3. sinon le **relais** du VPS (DERP, STUN sur UDP 3478).

**Onglet « Réseau »** (version web à droite de Sessions, même contenu dans l'appli de bureau, qui
demande l'état au serveur CCS comme le web) :
- une carte du réseau, avec un trait par liaison coloré selon le chemin (web) ;
- une fiche par appareil : adresse, adresses publiées (locales, publiques, IPv6), trafic, ping
  réel (chemin et latence), renommer, retirer ; la machine de calcul Ricochet s'y rattache ;
- « Ajouter un appareil » :
  - **PC Linux** : une ligne à coller, avec une clé jetable valable 15 min (ou le lien Ricochet,
    si le jeton opérateur est enregistré) ;
  - **Android et iPhone** : l'appli Tailscale avec le serveur personnalisé
    `https://network.mawena.cloud`, puis la clé `hskey-authreq-…` affichée, à valider dans
    l'onglet.

**En ligne de commande** :

```bash
ccs network                 # appareils et chemin de chaque liaison
ccs network ping pc-bureau  # chemin et latence réels
ccs network key --name pc-x  # clé jetable et lignes d'inscription (sur le VPS)
ccs network server         # appareils connus du serveur
```

Sur le VPS, le compte qui fait tourner CCS doit être dans le groupe `headscale` (clés, renommage,
retrait).

## Son partagé : le son d'un appareil joué sur un autre

Chaque appareil CCS du réseau maillé qui sait jouer du son devient une **sortie audio** pour les
autres, et le son part dans tous les sens : iPhone → PC, PC → Pixel, Pixel → iPhone… Le serveur CCS
ne fait que la mise en relation ; le son passe en direct entre les appareils (RTP/Opus en UDP sur
les adresses 100.64.x, 48 kHz stéréo, 100 à 200 ms de retard en direct, plus par un relais).
Protocole : [`docs/audio.md`](docs/audio.md).

- **PC Linux** : `ccs audio enable` (ou l’interrupteur « Son partagé sur ce PC » de l’onglet
  Son du bureau) lance le service utilisateur `ccs-audio`. Le PC est annoncé, et chaque autre
  appareil apparaît comme une **vraie sortie son** (« iPhone de Charles ») dans les réglages du son
  de Linux : choisis-la pour une appli et le son part vers l'appareil ; muette 10 s, l'envoi
  s'arrête. Il faut GStreamer et pactl (`gstreamer1.0-tools gstreamer1.0-plugins-good
  gstreamer1.0-pulseaudio pulseaudio-utils`, recommandés par `ccs-bureau`).
- **Android** (10 ou plus pour envoyer) et **iPhone** : onglet « Son » de l'appli (après Réseau). Le téléphone
  reçoit dès que CCS est ouvert ; pour envoyer son propre son, « Envoyer le son de ce téléphone
  vers… » (Android demande l'accord de capture à chaque fois ; l'iPhone passe par la diffusion
  d'écran ReplayKit, et les contenus protégés comme Apple Music ou Netflix y restent muets).
- **Web et bureau** : onglet « Son » (après Réseau) : appareils, flux en cours,
  « Envoyer le son de … vers … » entre deux appareils quelconques.
- **Lecteurs** : les lecteurs audio des PC Linux (VLC, Firefox… par MPRIS) se pilotent depuis
  tous les clients (section « Lecteurs » de l'écran Son) : lecture/pause, précédent, suivant,
  ±10 s, volume.

```bash
ccs audio players pc-bureau      # lecteurs d'un appareil (sans nom : ce PC)
ccs audio control --device pc-bureau vlc toggle   # ou : seek -10, volume 40, next, prev
ccs audio list                    # appareils annoncés et flux en cours
ccs audio send here iphone       # le son de ce PC vers l'iPhone
ccs audio send pixel pc-bureau   # télécommande : du Pixel vers pc-bureau
ccs audio stop                   # arrête les flux de ce PC (ou : ccs audio stop a3)
ccs audio receive                  # sans le service : au premier plan, pour essayer
ccs audio status                   # diagnostic : outils, serveur de son, sorties, service
ccs audio disable
```

## Chat riche

Dans le chat (web et bureau), les réponses de Claude peuvent contenir :
- des **images** : sur le web, elles s'ouvrent en grand d'un clic ;
- des **lecteurs** pour les liens et chemins de sons et de vidéos ;
- des **composants** écrits en blocs de code `ccs` (JSON) :
  - `choix` : boutons qui envoient un message ;
  - `carte` ou `cartes` : fiches avec photo, prix, lien et actions ;
  - `formulaire` : web seulement.

Claude en est averti à chaque lancement. Formats et limites : [docs/chat-riche.md](docs/chat-riche.md).
Les applis iOS et Android ne les rendent pas encore.

## Market : Facebook Marketplace au Togo

Option **Market (Marketplace Facebook)** de la nouvelle session (web et bureau ; il n'y a plus
d'onglet Market) : un chat où l'on pose une question — « le routeur le moins cher
compatible WireGuard à Lomé » — ou colle le lien d'un vendeur. Market cherche sur Facebook
Marketplace au Togo et répond **dans le chat** par un classement au meilleur rapport qualité-prix :
prix en CFA, lien de l'annonce, raisons (caractéristiques vérifiées sur le web), alternatives
écartées. Pas de surveillance ni d'alerte : seulement la réponse.
Le classement s'affiche en **cartes** (titre, prix, lieu, lien, photo si connue) suivies de
boutons de **choix** pour la suite (voir [Chat riche](#chat-riche)).

- C'est un chat Claude dédié (dossier `~/.local/share/ccs/market/`, avec son `CLAUDE.md`) : l'option
  ouvre la session dans ce dossier, sur tous les appareils. Claude y lance `ccs market …`.
- Les requêtes vers Facebook sortent **toujours par pc-bureau**, par le réseau maillé : `ssh -D`
  vers 100.64.0.2, adresse de sortie vérifiée avant chaque recherche (jamais celle du VPS), puis un
  Chrome sans interface du VPS (navigateurs de Playwright) branché sur ce tunnel. **Pas de repli** :
  si pc-bureau ne répond pas, Market le dit et n'envoie rien.
- Rythme humain (6 à 8 s par page, peu de pages par question), images bloquées, Chrome fermé après
  chaque commande. Messenger n'est jamais lu.
- Compte Facebook personnel. La lecture automatique est contraire aux conditions de Facebook.

**Première fois** : `ccs market login` (sur le VPS). Google Chrome s'ouvre sur l'écran de pc-bureau
(profil dédié) ; connecte-toi à Facebook : les cookies sont exportés et gardés dans
`~/.config/ccs/market/session.json` (600, jamais affichés), puis ce Chrome se referme. À refaire si
Market dit que la session a expiré.

```bash
ccs market status                                   # session, Chrome, tunnel et adresse de sortie
ccs market search "routeur wireguard" --max 30000   # prix | titre | ville | lien
ccs market seller https://www.facebook.com/marketplace/profile/100058059515617/
ccs market item https://www.facebook.com/marketplace/item/2421778705023492/
```

Réglages facultatifs dans `~/.config/ccs/market/config.json` (ville par défaut, chemin de Chrome,
pauses, limites).

## Calcul réparti : lancer un travail sur une autre machine

Avec [Ricochet](https://github.com/mawena/Ricochet) (0.3.0 ou plus), CCS se sert des autres
machines : un build Flutter part sur le PC de bureau quand Flutter n'est pas sur le VPS, une
longue suite de tests tourne ailleurs pendant que le VPS reste tranquille.

```sh
ccs remote machines                       # machines en ligne, charge, outils trouvés
ccs remote run -- flutter build apk    # la machine qui a flutter, la moins chargée
ccs remote run --machine pc-bureau --fetch build/app/outputs -- flutter build apk
```

`ccs remote run`, depuis le dossier du projet :

1. choisit la machine : `--machine`, sinon celle qui a l'outil (le premier mot de la commande,
   ou `--outil`), la moins chargée d'abord ;
2. y copie le projet avec `rsync` (seuls les fichiers changés repartent ; ce que git ignore et
   `.git` restent ici, sauf `--inclure <chemin>` et `--avec-git`) dans
   `~/.cache/ccs-distant/<projet>` ;
3. lance la commande dans le même sous-dossier, avec le `PATH` d'un terminal de la machine ;
   la sortie s'affiche au fil de l'eau et le code de retour est celui de la commande ;
4. rapporte ici chaque `--rapatrier <chemin>` si la commande a réussi.

**Par le réseau maillé d'abord** : si la machine est en ligne dans le réseau maillé (voir
« Réseau » plus haut), SSH va directement à son adresse 100.64.x, par le réseau local quand les
deux machines y sont ensemble ; sinon le tunnel Ricochet sert comme avant. Nom cherché dans le
réseau : `reseau = "lp-work"` dans `[machines.<id>]` de `machines.toml` (`reseau = false` pour
toujours passer par Ricochet), puis l'identifiant de la machine. `ccs remote machines` affiche
le chemin pris.

Interrompre `ccs remote run` (Ctrl+C, arrêt de Claude, connexion perdue) arrête aussi la
commande sur l'autre machine, avec tout ce qu'elle a lancé : signal TERM, puis KILL 5 s plus
tard. Le code de retour est alors 130.

Les chats de CCS le savent : quand le calcul réparti est réglé, Claude reçoit la consigne de
passer par `ccs remote run` si un outil manque ou pour un travail lourd.

**Plusieurs travaux, file d'attente et nuit.** Chaque machine a un nombre de places (`limite`,
2 par défaut) : le choix saute les machines pleines, et quand toutes sont pleines le travail
attend qu'une place se libère. On peut lancer plusieurs commandes à la fois (tests d'un côté,
build de l'autre).

```sh
ccs remote run --detach -- npm test          # en arrière-plan, journal gardé
ccs remote run --when night -- make test-long # au début de la plage de nuit des tâches
ccs remote run --when 02:30 -- cargo bench   # à une heure donnée
ccs remote jobs                               # en cours, en attente, programmés, finis
ccs remote log <id>                          # fin du journal d'un travail
ccs remote stop <id>                          # arrêt (la commande distante s'arrête aussi)
```

Le registre des travaux est dans `~/.cache/ccs/machines/jobs/` (les 30 derniers finis et ceux
de moins de 24 h sont gardés).

**Calcul dans l'onglet « Réseau ».** Dans le web et les applis (l'ancienne page « Machines » y est
fondue ; `#/machines` y mène) : chaque fiche d'appareil montre sa charge, sa mémoire, ses outils,
ses places et sa limite ; sous les appareils, les travaux avec « Journal » et « Arrêter », le
formulaire pour lancer une commande (dossier, machine, maintenant / cette nuit / à une heure) et,
replié, « Secours Ricochet » (adresse et jeton du relais, le jeton n'est jamais réaffiché). Le
calcul se recharge toutes les 5 s tant que la page est visible. Dans l'appli du PC : onglet
Réseau (avec « Ajouter un PC »).

**Ajouter un PC au réseau** (le plus simple) : onglet Réseau → Ajouter un appareil → « PC Linux » (identifiant,
ton compte sur ce PC ; case « Installer aussi CCS et Claude Code » pour ouvrir des sessions
entières sur ce PC), ou

```sh
ccs remote add pc-salon --user charles [--name "PC du salon"] [--limit 2] [--full]
```

Avec `--complet` (ou la case), la ligne installe ensuite CCS depuis le dépôt APT et Claude Code
(`curl -fsSL https://claude.ai/install.sh | bash`).

CCS déclare la machine dans Ricochet et donne **une ligne à coller** dans un terminal du PC
(Ubuntu ou Debian) : `curl -fsSL https://<relais>/rejoindre/<code> | sudo sh`. Elle installe
l'agent Ricochet et le serveur SSH, autorise la clé SSH de ce serveur pour ce compte, ouvre le
port 22 aux tunnels, active terminal et fichiers, puis démarre l'agent : la machine apparaît en
ligne et `ccs remote` peut s'en servir tout de suite. Lancée depuis le serveur du réseau
maillé (le VPS), la ligne inscrit aussi le PC au réseau maillé sous son identifiant (clé jetable,
15 min). Le lien ne sert qu'une fois, pendant
15 minutes, et le jeton de la machine n'est jamais affiché. Il faut Ricochet 0.6.0 ou plus et
le jeton opérateur du relais dans `~/.config/ricochet/client.toml` (`jeton_operateur = "…"`, son
empreinte dans `jeton_operateur_sha256` de `/etc/ricochet/serveur.toml`).

**Mise en place à la main** (une fois) :

- relais Ricochet : un jeton des tunnels (`ricochet-serveur jeton`, empreinte dans
  `jeton_tunnel_sha256`) ;
- cette machine : `ricochet-agent` 0.3.0 ou plus, et `~/.config/ricochet/client.toml`
  (droits 600) avec `relais = "https://…"`, `jeton = "…"` et, pour ajouter des PC d'ici,
  `jeton_operateur = "…"` ;
- chaque machine de calcul : `[tunnel]` avec `ports = [22]` dans `/etc/ricochet/agent.toml`, un
  serveur SSH, et la clé publique de cette machine dans son `~/.ssh/authorized_keys` ;
- si l'utilisateur ou le port SSH diffèrent : `~/.config/ccs/machines.toml` (avant la 1.0.0 :
  `distant.toml` avec `utilisateur` et `limite`, renommé et lu tout seul)

```toml
[machines.pc-bureau]
user = "charles"
port = 22
limit = 3         # travaux à la fois sur cette machine (1 à 8, 2 par défaut)
```

Ricochet ne fait que le tunnel : c'est le serveur SSH de la machine qui décide qui entre, et
chaque tunnel est dans le journal d'audit de Ricochet.

## Application Android

`android-app/` contient l'application **native** (Kotlin + Jetpack Compose, Material 3, paquet
`com.mawena.ccs`) : tout ce que fait la version web — accueil et comptes, sessions et projets,
chat complet (sous-agents, autorisations, questions, pièces jointes, `/clear`), fichiers, Git,
feuille de route, tâches de nuit, réglages, terminal (émulateur de Termux) — plus des
notifications de fin de tour et d'attente (avec Autoriser / Refuser), le partage Android vers un
chat et des raccourcis d'appli. Connexion par appairage (mot de passe + code) ou par Portier,
puis jeton d'appareil gardé chiffré, révocable dans Réglages → Appareils.

L'APK est joint à chaque release GitHub (`ccs-<version>.apk`). Pour le construire (SDK Android
sur `pc-bureau`) : voir [android-app/README.md](android-app/README.md). Il est signé avec la clé
de débogage de `pc-bureau` : construire toujours là pour installer les mises à jour par-dessus.

## Application iPhone

`ios-app/` contient l'application **native** pour iPhone (Swift + SwiftUI, iOS 17, identifiant
`com.mawena.ccs`) : le même périmètre que l'appli Android — accueil et comptes, sessions et
projets, chat complet, fichiers, Git, feuille de route, tâches de nuit, réglages, terminal
(émulateur SwiftTerm), choix de la **machine pilotée** (le PC par le relais Ricochet, comme
sur le web et Android) et page des **travaux distants** — avec des notifications **locales** de fin de tour et d'attente
(Autoriser / Refuser depuis la notification) et le partage vers un chat (« Ouvrir dans CCS »
pour les fichiers, `ccs://partager?texte=…` pour le texte et les liens).

Gratuite, sans compte développeur payant : l'`.ipa` non signé est construit sur Codemagic et
installé avec **SideStore**, qui le signe avec ton identifiant Apple. Limites d'Apple : appli à
rafraîchir dans SideStore tous les 7 jours, pas de notifications push (elles ne partent que
tant que l'appli est ouverte ou vient de passer en arrière-plan). L'`.ipa` est joint à chaque
release GitHub (`CCS-<version>.ipa`) ; installation et construction :
[ios-app/README.md](ios-app/README.md).

## Installation

Ubuntu 24.04 (ou Debian/Ubuntu récent avec GTK 4, libadwaita ≥ 1.5 et, pour le
terminal intégré, VTE pour GTK 4 : `gir1.2-vte-3.91` ; pour le chat et les fichiers,
GtkSourceView 5 : `gir1.2-gtksource-5`, et `python3-markdown-it`). Le paquet `.deb`
les installe tout seul.
Claude Code doit être installé
(`claude` dans le `PATH`).

### Par le dépôt APT (recommandé)

CCS est publié dans le dépôt APT signé unique de mawena, <https://apt.mawena.cloud/>
(un seul dépôt pour tous ses paquets Ubuntu). Une fois CCS installé, **les nouvelles
versions arrivent avec les mises à jour du système** (`sudo apt update && sudo apt upgrade`,
ou la Logithèque). Trois façons de faire la première installation :

```sh
# 1. l'installateur : ajoute la clé et le dépôt, puis installe CCS
curl -fsSL https://apt.mawena.cloud/installer.sh | sudo sh -s -- ccs

# 2. à la main, les mêmes étapes
sudo curl -fsSL -o /usr/share/keyrings/mawena-depot.gpg https://apt.mawena.cloud/mawena-depot.gpg
sudo curl -fsSL -o /etc/apt/sources.list.d/mawena-depot.sources https://apt.mawena.cloud/mawena-depot.sources
sudo apt update && sudo apt install mawena-depot ccs

# 3. en dernier recours, le .deb d'une release GitHub (avec celui de mawena-depot)
gh release download -R mawena/CCS -p '*.deb'      # ou depuis la page Releases
curl -fsSLO https://apt.mawena.cloud/pool/main/depot/mawena-depot_0.2.1_all.deb
sudo apt install ./mawena-depot_0.2.1_all.deb ./ccs_*_all.deb
```

Le site du projet <https://mawena.github.io/CCS/> et celui du dépôt
<https://apt.mawena.cloud/> donnent les mêmes commandes, à copier. Clé de signature
« mawena APT », empreinte `60A2 0BB2 21C9 1DAD F39D D55B 456B 0129 30FA 901D`.
Le paquet `ccs` dépend de `mawena-depot`, qui installe la source
(`/etc/apt/sources.list.d/mawena-depot.sources`) et la clé
(`/usr/share/keyrings/mawena-depot.gpg`).

**Machines installées avant la 0.20.1** (ancien dépôt `https://mawena.github.io/CCS/apt`) :
rien à faire, `sudo apt update && sudo apt upgrade` installe `mawena-depot` et retire
l'ancienne source `ccs.sources`. L'ancien dépôt reste en ligne jusqu'à mai 2027.

### Les paquets

CCS se découpe en quatre paquets : `ccs` (commandes, service, `ccs tui`), `ccs-bureau`
(l'application GTK, recommandée par `ccs`), `ccs-serveur` (la version web et l'accès à
distance, voir [CCS sur un serveur](#ccs-sur-un-serveur-vps)) et `ccs-all`, qui installe les
trois. Sur un poste de bureau, `sudo apt install ccs-all` suffit ; sur un serveur,
`sudo apt install --no-install-recommends ccs-serveur`.

### Après la première installation

```sh
systemctl --user daemon-reload
systemctl --user enable --now ccs-daemon
claude-accounts tray &            # l'icône, sans attendre de te reconnecter
ccs integration on                  # optionnel : ligne d'état et bascule après blocage dans Claude Code
ccs doctor                        # tout doit être au vert
```

Le service démarre ensuite seul à chaque session, l'icône de la barre du haut
aussi.

**Indicateur invisible ?** Active l'extension GNOME « Ubuntu AppIndicators » :
`gnome-extensions enable ubuntu-appindicators@ubuntu.com` (ou bouton dans
Réglages).

### Mettre à jour

- **Par apt** (dépôt ajouté par `mawena-depot`) : `sudo apt update && sudo apt upgrade`.
- **En un clic** : CCS te prévient quand une nouvelle version est publiée
  (notification, icône, bandeau de la fenêtre, Réglages ; vérification sur
  GitHub au plus une fois par jour). Le bouton **Installer** du bandeau, ou
  `ccs update`, télécharge, vérifie et installe le paquet.
- **À la main** : installe le nouveau `.deb` avec `sudo apt install ./ccs_*_all.deb`.

Le service se relance seul avec la nouvelle version (dans les 5 min), l'icône
aussi (dans les 10 s) ; ferme et rouvre la fenêtre « CCS ». En
venant de la 0.4.0 ou d'avant, l'icône ne sait pas encore le faire : relance-la
une fois (`pkill -f 'claude-accounts tray'; setsid -f claude-accounts tray`) ;
en venant d'une version antérieure à 0.2.1, lance aussi une fois
`systemctl --user restart ccs-daemon`. Tes profils sont conservés.

### Depuis les sources

```sh
git clone https://github.com/mawena/CCS.git && cd CCS
make test                 # tests unitaires + bout en bout
bin/ccs                   # utilisable directement depuis le dépôt
make deb                  # construit dist/ccs_<version>_all.deb
```

## Démarrage rapide

1. **Enregistre le compte déjà connecté** : `ccs save perso`
2. **Ajoute les autres** : `ccs add boulot` ouvre la connexion dans le
   navigateur ; choisis bien un *autre* compte (`--email` pré-remplit).
3. **Démarre le service** : `systemctl --user enable --now ccs-daemon`
4. **Active l'orchestrateur** : `ccs orchestrator on`, puis règle ta plage horaire dans
   l'application (« CCS » dans le menu, ou `ccs app`).

## Commandes

| Commande | Effet |
|---|---|
| `ccs` | Liste les profils (● = actif) |
| `ccs <nom>` | Bascule sur un profil (ou `ccs use <nom>`) |
| `ccs next` / `ccs best` | Profil suivant / meilleur compte du moment |
| `ccs status` | Compte actif, prévision, meilleur compte, capacité, orchestrateur, pause, service |
| `ccs plan` | Planning des fenêtres et recharges à venir |
| `ccs sessions` | Sessions Claude Code ouvertes : projet, état, consommation, RAM par session et totale, sessions inactives, contexte lourd |
| `ccs conversations [mots]` | Historique des conversations du PC, recherche, `-p <projet>`, `--vscode`/`--terminal` |
| `ccs resume <id>` | Reprend une conversation ici, `--vscode`, `--new-terminal`, `--dir <dossier>` |
| `ccs title <id> <titre>` | Renomme une conversation (comme `/rename`) |
| `ccs preview <id>` | Affiche la conversation en Markdown, coût en en-tête |
| `ccs export <id> [fichier.md]` | Enregistre la conversation en Markdown (défaut : `<titre>.md` dans le dossier courant) |
| `ccs integration on\|off\|status` | Ligne d'état et bascule après blocage dans Claude Code |
| `ccs usage` | Usage détaillé de tous les comptes, prévisions, rythme hebdo |
| `ccs orchestrator on\|off` | Orchestrateur |
| `ccs auto on\|off` | Bascule automatique à 98 % |
| `ccs pause [1h\|4h\|demain\|manuel\|off\|status]` | Met en pause la bascule automatique et l'orchestrateur (`status` par défaut) |
| `ccs doctor` | Bilan de santé, avec la commande qui corrige chaque problème |
| `ccs analyze [--days N]` | Consommation par projet, modèle, heure, compte + conseils |
| `ccs advisor` | Conseiller de formule : combinaison conseillée, raisonnement, équivalent API |
| `ccs week [--previous N]` | Bilan de la semaine (`--previous N` : N semaines plus tôt) |
| `ccs month [--previous N]` | Rapport mensuel (dernier mois terminé par défaut ; `--previous N` : N mois plus tôt, 0 à 120) |
| `ccs best-time [--duration 3h] [--within 24h]` | Meilleur moment pour une grosse tâche (durée 1 à 10 h, horizon 1 à 72 h) |
| `ccs quiet [1h\|4h\|demain\|off\|reprendre\|status]` | Ne pas déranger : silence temporaire des notifications (`status` par défaut) |
| `ccs update [--check]` | Installe la dernière version de CCS (ou seulement la vérifie) |
| `ccs log [--days N\|--all]` | Journal des bascules (7 derniers jours par défaut) |
| `ccs project [<dossier>] [<compte>\|aucun]` | Compte par projet : liste, compte d'un dossier, association (`aucun` la retire) |
| `ccs shortcuts [status\|on\|off\|set]` | Raccourcis clavier globaux (GNOME) : état, activer, retirer, changer |
| `… --notify` | Avec `ccs <nom>`, `ccs use`, `ccs next`, `ccs best`, `ccs pause`, `ccs quiet` : résultat aussi en notification (option des raccourcis clavier) |
| `ccs save <nom>` / `ccs add <nom>` | Enregistre le compte connecté / connecte un nouveau compte |
| `ccs rename <a> <b>` / `ccs remove <nom>` | Renomme / supprime un profil |
| `ccs task` | File de tâches pour Claude : liste ; `add "<message>" [-C dossier] [--model m] [--rights read\|edit\|all] [--when quota\|night\|HH:MM] [--provider nom]`, `show <id>`, `cancel <id>`, `remove <id>` |
| `ccs provider [list\|show\|models\|key\|test] [nom]` | Autres fournisseurs de modèles (OpenRouter, DeepSeek…) : liste, détail, catalogue, clé (600), essai |
| `ccs budget [<dossier> <montant>\|aucun]` | Budgets hebdomadaires par projet : état, définition (en dollars, équivalent API) ou retrait |
| `ccs recap <id>` | Fiche « où j'en étais » d'une conversation, sans appeler Claude |
| `ccs backup [fichier]` / `ccs restore <fichier> [--yes]` | Sauvegarde chiffrée (gpg) des comptes et réglages / restauration |
| `ccs phone [test]` | Notifications sur le téléphone (ntfy) : état et lien d'abonnement, ou message d'essai (`test`) |
| `ccs tui [--server <nom>]` | CCS en plein écran dans le terminal (ce poste, ou un serveur appairé) |
| `ccs server add <adresse> [--name n]` / `list` / `remove <nom>` | Serveurs CCS distants : appairage (mot de passe et code), liste, retrait |
| `sudo ccs totp reset <utilisateur>` | Sur le serveur : efface le code de double authentification d'un utilisateur |
| `ccs audio list` / `send <source> <sortie>` / `stop [flux\|appareil]` / `receive` / `status` / `enable [--name n]` / `disable` | Son partagé sur le réseau maillé : appareils, envois, service `ccs-audio` de ce PC |
| `ccs remote machines [--fast]` | Calcul réparti : machines du réseau Ricochet, charge et outils (`--fast` : sans les interroger) |
| `ccs remote run [--machine m] [--tool o] [--fetch chemin] [--include chemin] [--with-git] [--when night\|HH:MM] [--detach] -- <commande>` | Lance la commande sur une autre machine : envoi du projet, sortie en direct, fichiers produits rapportés |
| `ccs market search "<mots>" [--min N] [--max N] [--city lome]` / `seller <lien>` / `item <lien>` / `status` / `login` | Market : annonces de Facebook Marketplace au Togo (toujours par pc-bureau), vendeur, détails d'une annonce, état, connexion (une fois) ; `--json` |
| `ccs chat clear` | Dans un chat de CCS (lancé par Claude) : vide la conversation (`/clear`) à la fin du tour en cours |
| `ccs app` | Application graphique |

Détails : `man ccs`, `man claude-accounts`, [docs/utilisation.md](docs/utilisation.md).

## Configuration

Tout se règle dans la fenêtre **Réglages** (menu ☰) de l'application — Bascule
automatique, Orchestrateur, Alertes, Ne pas déranger, Conseils, Conseiller de formule,
Intégration, Terminal intégré, Raccourcis clavier, Warm-up, Service — ou par
les commandes `ccs auto`, `ccs orchestrator`, `ccs pause`, `ccs integration`,
`ccs project`, `ccs shortcuts`, `ccs task`, `ccs budget`, `ccs phone`. Les réglages vivent dans
`~/.claude-accounts/settings.json`, fusionnés avec les valeurs par défaut :
bascule automatique (`auto_switch`), alertes (`alerts` : seuils, fin de semaine
prévue `weekly_forecast` / `weekly_forecast_days`, rappel d'attente
`waiting_reminder` / `waiting_reminder_min`, conseil de modèle `model_advice` /
`model_advice_pct`, bilan de la semaine `weekly_report` / `weekly_report_day` /
`weekly_report_hour`, rapport mensuel `monthly_report` /
`monthly_report_hour`, ne pas déranger `quiet` : `enabled`, `start`, `end`,
`days`, `allow_waiting`…), conseiller de formule (`advisor` : semaines analysées,
marge, tarifs, formule d'un profil), orchestrateur et plage horaire
(`orchestrator`), warm-up (`warmup`), nouvelles versions (`updates.enabled`).
Depuis la 0.8.0 : file de tâches (`tasks` : `enabled`, plage de la nuit `night.start` /
`night.end`, `max_attempts`), téléphone (`phone` : `enabled`, `server`, `topic`,
`events`, `show_content` : « Montrer la commande » dans la notification d'autorisation, faux par défaut ;
`reply_topic` : canal secret des réponses, tiré par CCS), page Git (`git` : `layout`,
`fetch_minutes`, `avatars`), archive (`archive` : `enabled`, `idle_days`, `max_age_days`),
sessions inactives (`sessions.idle_hours`), alerte de contexte lourd
(`context_alert` : `enabled`, `threshold_tokens`, `auto_compact` : compactage automatique
des chats, faux par défaut), budgets (`budget` : `enabled`,
`alert_pcts`). Une valeur invalide (mauvais type,
hors bornes, heure impossible) ou un fichier illisible n'empêche rien : la clé
fautive reprend sa valeur par défaut, le fichier n'est pas modifié, et
`ccs doctor` la signale.
Les deux interrupteurs du terminal intégré (**Réglages → Terminal intégré**, ou
menu « ⋮ » de la page Terminaux) sont gardés dans
`~/.claude-accounts/terminals.json`, les comptes par projet dans
`~/.claude-accounts/project-accounts.json`, les budgets dans
`~/.claude-accounts/budgets.json`, les tâches dans `~/.claude-accounts/tasks.json`
(leurs journaux dans `~/.claude-accounts/tasks/<id>.jsonl`), les copies de
l'archive des conversations dans `~/.local/share/ccs/archive`, les raccourcis
clavier dans les réglages de GNOME. `CCS_HOME` change le dossier des profils (défaut `~/.claude-accounts`).

## Comment ça marche

**Bascule.** Chaque profil conserve le jeton OAuth et l'identité du compte dans
`~/.claude-accounts/<nom>/`. Basculer réécrit, de façon atomique et sous verrou,
la partie « compte » de `~/.claude/.credentials.json` et `~/.claude.json` ; le
reste (jetons MCP, réglages) est conservé.

**Sessions ouvertes.** Avant chaque requête, Claude Code vérifie si son fichier
de connexion a changé et le relit : une session en cours passe sur le nouveau
compte à son message suivant. La première requête après une bascule renvoie le
contexte au nouveau compte (cache non partagé) : un coût ponctuel.

**Usage sans se reconnecter.** Le service interroge l'API d'usage avec le jeton
de chaque profil et renouvelle lui-même les jetons des comptes inactifs ; celui
du compte actif est laissé à Claude Code tant qu'il tourne.

**Démarrer une fenêtre.** Une requête `claude -p` minimale sur Haiku, dans un
dossier de configuration temporaire qui ne contient que le compte visé : le
compte actif et tes sessions ne sont pas touchés.

Architecture : [docs/architecture.md](docs/architecture.md).

## Données et confidentialité

Tout reste sur la machine, dans `~/.claude-accounts/` (dossier 700, fichiers
600). CCS contacte les serveurs d'Anthropic et, au plus une fois par jour, l'API
publique de GitHub pour savoir si une nouvelle version de CCS est sortie (sans
authentification ; à couper dans **Réglages → Nouvelles versions**).
Il lit les conversations de
`~/.claude/projects` sans les modifier, à deux exceptions près : la reprise d'un
projet déplacé y ajoute une copie du journal, et renommer une conversation ajoute
une ligne de titre à la fin de son journal (comme `/rename`). L'aperçu, l'export,
le coût, les conseils et le bilan de la semaine ne font que lire. Les
raccourcis clavier s'écrivent dans les réglages de GNOME, sous les seuls
chemins de CCS. Depuis la 0.8.0, le service copie aussi les
conversations dans l'archive (`~/.local/share/ccs/archive`, dossier 700), et
les tâches lancent `claude` en ton nom. Les notifications sur le téléphone
(désactivées par défaut) n'envoient que le nom du projet et l'état, jamais un
titre, un message, un chemin ni un nom de compte. La sauvegarde contient les
jetons, mais chiffrés : garde la phrase de passe. Aucun jeton n'apparaît dans
les journaux, l'état partagé, les notifications ou le bilan de santé (qui n'en
retient que la présence et les dates d'expiration).

## Dépannage

Premier réflexe : `ccs doctor`, qui donne la commande à lancer pour chaque
problème trouvé.

| Symptôme | Solution |
|---|---|
| « le compte connecté n'est enregistré dans aucun profil » | `ccs save <nom>` avant de basculer. |
| « connexion expirée ou révoquée » | `ccs remove <nom>` puis `ccs add <nom>`. |
| Pas de bascule / pas de démarrage | `ccs status` : service en marche ? orchestrateur activé ? dans la plage horaire ? en pause (`ccs pause off`) ? |
| L'icône garde l'ancienne version après une mise à jour | Mise à jour en venant de la 0.4.0 ou d'avant : `pkill -f 'claude-accounts tray'; setsid -f claude-accounts tray`. |
| L'ancienne version s'ouvre | Supprime `~/.local/bin/ccs`, `~/.local/bin/claude-accounts` et `~/.local/share/applications/io.ccs.ClaudeAccounts.desktop`. |
| « CCS » introuvable dans le menu | Alt+F2 puis `r` (X11), ou reconnecte-toi. |
| Icône absente de la barre du haut | Extension « Ubuntu AppIndicators » (voir Installation), puis `claude-accounts tray &`. |
| Pas de ligne d'état dans Claude Code | `ccs integration status`, puis relance la session. |
| Le chat, la coloration ou l'aperçu Markdown ne marchent pas | Bibliothèques manquantes (`ccs doctor` : « Chat graphique ») : `sudo apt install gir1.2-gtksource-5 python3-markdown-it`. |
| Les sessions s'ouvrent dans un terminal externe | Terminal intégré indisponible : `sudo apt install gir1.2-vte-3.91`, puis rouvre l'application. |
| Une session bloquée n'est pas relancée dans l'onglet | `ccs integration on` (le hook est nécessaire), interrupteur « Reprise automatique après une limite » du menu « ⋮ » de la page Terminaux, pas de pause en cours ; une touche tapée dans l'onglet après la limite annule la reprise. |
| Pas de proposition de bascule pour un projet | `ccs project <dossier>` ; rien n'est proposé pendant une pause ni si « Ne plus demander pour ce projet » a été coché (réactive « Proposer la bascule » dans « Compte de ce projet… »). |
| Un raccourci clavier ne fait rien | `ccs shortcuts status` : activé ? combinaison déjà prise (⚠) ? Bureau GNOME seulement ; « commande à mettre à jour » (déplacement du dépôt, installation du paquet, raccourci activé avant la 0.6.0) : « Mettre à jour les commandes » (Réglages) ou `ccs shortcuts on`. |
| « Pas encore assez de relevés pour conseiller une formule » | Le conseiller a besoin d'au moins 3 jours de relevés du service. |

Journaux du service : `journalctl --user -u ccs-daemon -f`.

## Désinstallation

```sh
systemctl --user disable --now ccs-daemon
sudo apt purge ccs             # le dépôt reste : sudo apt purge mawena-depot pour le retirer
rm -rf ~/.claude-accounts      # optionnel : profils et historique
```

Le dépôt APT (`/etc/apt/sources.list.d/mawena-depot.sources`) appartient au paquet
`mawena-depot`, partagé par tous les paquets de mawena : le retirer seulement si plus
aucun d'eux n'est installé (`purge`, pour retirer aussi la source).

## Développement

Projet en **git flow** (`main` / `develop`, tags `vX.Y.Z`), commits
conventionnels en français. Python 3 (bibliothèque standard + PyGObject) et
bash ; hors bibliothèques GTK, seul `python3-markdown-it` (rendu Markdown) est requis.

| Dossier / module | Rôle |
|---|---|
| `bin/ccs`, `bin/claude-accounts` | commande `ccs` (bash) : profils et bascule ; lanceur Python de `ccs_app` |
| `ccs_app/` | service, prévisions, alertes, pause, conversations, conseils, journal, raccourcis, tâches, archive, sauvegarde, budgets… |
| `ccs_app/chat_protocol.py` | protocole stream-json de Claude Code : lignes de `claude` en événements, messages à lui écrire (sans GTK) |
| `ccs_app/chat_engine.py` | moteur du chat : processus `claude`, états, autorisations, veille, `--resume` (sans GTK) |
| `ccs_app/chat_options.py` | modèle, effort, ultracode, droits d'un chat (sans GTK) |
| `ccs_app/markdown_render.py` | Markdown analysé en blocs simples, pour le chat et l'aperçu (sans GTK) |
| `ccs_app/roadmap.py` | lecture et cochage de `ROADMAP.md` ; feuille de route citée par les outils de Claude (`path_in_tool`) |
| `ccs_app/file_tree.py` | marques git, type de fichier, lecture et écriture sûres (sans GTK) |
| `ccs_app/account_colors.py` | couleur de chaque compte (sans GTK) |
| `ccs_app/gui/` | application GTK 4 / libadwaita et ses dialogues |
| `ccs_app/gui/chat_tab.py`, `chat_messages.py`, `chat_composer.py`, `chat_bar.py`, `markdown_view.py` | le chat : onglet, messages et cartes, saisie, barre cliquable, rendu Markdown |
| `ccs_app/gui/session_workspace.py`, `file_panel.py`, `file_editor.py`, `roadmap_view.py` | l'espace de session : arbre des fichiers, fichiers ouverts, feuille de route |
| `ccs_app/gui/home_page.py`, `analysis_hub.py`, `prefs_dialog.py`, `style.py` | onglets Accueil, Analyse, fenêtre des Réglages, style commun |
| `data/`, `debian/` | unité systemd, entrées de menu, icône, paquet |
| `scripts/` | construction du .deb |
| `docs/` | guide, architecture, pages man |
| `tests/` | tests unitaires et scénario de bout en bout |

```sh
make test     # tests unitaires + scénario de bout en bout de ccs
make deb      # tests, paquet, SHA256SUMS et lintian dans dist/
```

Essayer une copie de développement sans réveiller l'application installée :
`CCS_APP_ID=io.ccs.ClaudeAccounts.Dev bin/claude-accounts app` ;
`CCS_NO_VTE=1` force le repli sur le terminal externe.

## Licence

[MIT](LICENSE) © 2026 mawena
