# CCS — plusieurs comptes Claude Code, comme un seul

**Pro (20 $) ne te suffit plus, mais Max (100 $) c'est trop ?** CCS fait
travailler 2 ou 3 comptes Claude Code ensemble sur ton PC Linux : une seule
commande pour basculer, l'usage de tous les comptes d'un coup d'œil, une bascule
automatique avant la coupure — les sessions déjà ouvertes continuent sur le
compte suivant — et un **orchestrateur** qui organise les fenêtres de 5 h pour
qu'un compte soit disponible quand l'autre est épuisé.

```sh
ccs save perso        # enregistre le compte connecté
ccs add boulot        # connecte et enregistre un deuxième compte
ccs orch on           # l'orchestrateur gère le reste
ccs integrate on      # l'état des comptes en bas de chaque session Claude Code
ccs status            # où j'en suis, quel compte utiliser
ccs formule           # la formule qu'il te faut, d'après ton usage réel
```

**Site :** [mawena.github.io/CCS](https://mawena.github.io/CCS/) ·
**Installation sur Ubuntu** (dépôt APT signé, mises à jour par `apt upgrade`) :

```sh
curl -fsSL https://mawena.github.io/CCS/installer.sh | sudo sh
```

Les autres façons d'installer sont dans [Installation](#installation).

## Le palier qui manque

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
respecte aussi l'interrupteur « bascule automatique ». Tout se règle dans l'onglet **Réglages**, et l'onglet
**Planning** montre la frise du jour et les recharges à venir.

## Mettre en pause

Besoin de rester sur un compte précis le temps d'une démo ou d'un gros
travail ? `ccs pause 1h` (ou `4h`, `demain` = jusqu'au début de la prochaine
plage horaire, `manuel` = jusqu'à ce que tu reprennes) suspend la bascule
automatique et l'orchestrateur. Pendant une pause, **CCS ne change plus de
compte tout seul**, même quand une session est bloquée par la limite ; les
bascules que tu fais toi-même, les alertes et les warm-up continuent. La pause
se lève seule à l'échéance (notification « Pause terminée ») ; `ccs pause off`
reprend tout de suite.

Aussi dans le menu de l'icône (« Mettre en pause ») et sur la carte **Meilleur
compte** de l'onglet Comptes. Pendant la pause, l'en-tête de la fenêtre affiche
« Auto ⏸ jusqu'à 14:00 » (un clic propose « Reprendre maintenant ») ;
`ccs status`, l'onglet Planning, l'icône et la ligne d'état de Claude Code la
rappellent aussi.

## Conseils

En haut de l'onglet **Analyse**, et dans le terminal :

- **Conseiller de formule** (`ccs formule`) : combien de comptes Pro, Max ou
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
- **Bilan de la semaine** (`ccs semaine`) : usage de chaque compte,
  conversations, sessions, tokens et équivalent API, modèles, projets, bascules
  et alertes, comparés à la semaine précédente. Une notification le résume au
  début de chaque semaine ; la carte de l'onglet Analyse laisse choisir la
  semaine (aussi « Bilan de la semaine » dans le menu de l'icône).
- **Rapport mensuel** (`ccs mois`) : le même exercice sur le mois civil, mois en
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
La carte « Meilleur moment pour une grosse tâche » de l'onglet **Planning**
(et `ccs moment --duree 3h`) compte, pour chaque heure de départ possible sur
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
Reprendre les notifications), `ccs silence 1h` et le raccourci clavier
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
ligne de commande : `ccs mise-a-jour`.

## Dans Claude Code

`ccs integrate on` ajoute deux choses à Claude Code (dans `~/.claude/settings.json`,
avec une sauvegarde ; une ligne d'état que tu aurais déjà n'est jamais remplacée) :

- **une ligne d'état** en bas de chaque session :
  `◑ perso 53 % ↻17:20 · ⏱14:21 · sem. 51 % · 2 comptes` — compte actif,
  session, recharge, limite estimée, semaine, et le meilleur compte quand il
  faut changer (« → sonnet ? » près des limites avec un modèle cher) ;
- **la bascule après blocage** : si une session atteint malgré tout la limite,
  CCS bascule aussitôt sur le meilleur autre compte et te prévient — tape
  « continue » et la session repart (dans le terminal intégré, CCS peut
  l'envoyer pour toi). En pause, la notification le dit et rien ne bascule.

`ccs integrate off` retire tout ce que CCS a ajouté, et seulement cela.

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
`claude-accounts gui --new-session`) ouvre un dialogue : dossier,
compte (celui du projet est présélectionné), modèle (`--model`) et mode de
permissions (`--permission-mode`). Si tu choisis un autre compte que le compte
actif, CCS bascule avant de lancer la session — et toutes les sessions ouvertes
suivent, le dialogue te le rappelle. Le mode « Aucune vérification »
(`bypassPermissions`) reste proposé, avec un avertissement en rouge.

## Compte par projet

Le compte « boulot » pour les projets du travail, « perso » pour le reste ?
Associe un dossier à un compte : `ccs projet ~/Work/App boulot`, ou « Compte de
ce projet… » en tête d'un projet de l'onglet Sessions. Les sous-dossiers
héritent du compte de leur dossier parent.

Quand tu ouvres une session ou reprends une conversation de ce projet depuis
l'application alors qu'un autre compte est actif, CCS demande : **Basculer et
ouvrir**, **Ouvrir sans basculer** ou **Annuler** (case « Ne plus demander pour
ce projet »). Le compte actif est commun à toutes les sessions : basculer les
fait toutes passer sur ce compte. « Nouvelle session… » présélectionne le
compte du projet. Pendant une pause, rien n'est proposé ni présélectionné.

## Terminal intégré

Reprendre une conversation ou démarrer une session l'ouvre **dans la fenêtre de
l'application**, dans un onglet de terminal, plutôt que dans une fenêtre à part.
Plusieurs sessions tiennent en onglets (page **Terminaux**, visible dès qu'un
onglet est ouvert) ; chaque onglet porte le titre de la conversation
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
- **Reprise automatique après une limite** (avec `ccs integrate on`) : quand
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

« Renommer… » (onglet Sessions, menu d'un onglet du terminal)
ou `ccs title <identifiant> <titre>` donne un titre à une conversation, comme
`/rename` dans Claude Code : le titre est enregistré dans la conversation et
s'affiche partout, VS Code compris.

## Historique des conversations

L'onglet **Sessions** (« Tous les projets » pour tout voir) et `ccs conv` listent
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
ccs conv                 # les 30 dernières conversations, groupées par date
ccs conv export csv      # recherche
ccs conv -p Portail      # un projet
ccs resume 4f3a          # reprend ici (4 premiers caractères de l'identifiant)
ccs resume 4f3a --vscode # ou dans VS Code
ccs title 4f3a Export CSV des prêts   # renomme la conversation
ccs preview 4f3a | less  # relit la conversation (Markdown, coût en en-tête)
ccs export 4f3a          # l'enregistre en Markdown (<titre>.md ici)
```

## Journal des bascules

Pourquoi CCS a-t-il changé de compte ? L'onglet **Historique** (et
`ccs journal`) raconte chaque bascule, groupée par jour, avec sa raison en
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

## Raccourcis clavier

Des raccourcis **globaux**, qui marchent même application fermée, tous
désactivés au départ : **Réglages → Raccourcis clavier**, ou
`ccs raccourcis on`.

| Action | Raccourci | Commande |
|---|---|---|
| Ouvrir CCS | Super+Alt+C | `claude-accounts gui` |
| Afficher les sessions | Super+Alt+V | `claude-accounts gui --page sessions` |
| Nouvelle session | Super+Alt+N | `claude-accounts gui --new-session` |
| Basculer sur le compte suivant | Super+Alt+B | `ccs next --notifier` |
| Basculer sur le meilleur compte | Super+Alt+M | `ccs best --notifier` |
| Pause 1 h | Super+Alt+P | `ccs pause 1h --notifier` |
| Reprendre (lever la pause) | Super+Alt+R | `ccs pause off --notifier` |
| Ne pas déranger 1 h | Super+Alt+D | `ccs silence 1h --notifier` |

Sans terminal pour le lire, le résultat s'affiche en notification passagère
(« Bascule sur boulot », « Déjà sur perso », « Pause jusqu'à 14:00 »,
« Bascule impossible »…) : c'est l'option `--notifier`. « Modifier » change la
combinaison (ou
`ccs raccourcis set suivant Super+Alt+B`) ; une combinaison déjà prise par le
bureau ou par un autre raccourci est signalée. Ce sont des raccourcis
personnalisés de GNOME (Paramètres › Clavier › Raccourcis personnalisés) : CCS
ne touche qu'aux siens, jamais aux tiens. Sur un autre bureau, CCS affiche les
commandes, à associer toi-même à un raccourci. Des raccourcis activés avec une
version précédente (sans `--notifier`) sont signalés « à mettre à jour » :
bouton **Mettre à jour les commandes** des Réglages, ou `ccs raccourcis on`.

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
| **Rapport mensuel** | Le mois civil : comptes, activité, tokens, équivalent API, modèles, projets, évolution et tendance ; carte Analyse, notification le 1er du mois, `ccs mois`. |
| **Meilleur moment** | Quand lancer une grosse tâche : fenêtres de 5 h disponibles par heure de départ, alternatives, frise des 24 h (onglet Planning, `ccs moment`). |
| **Ne pas déranger** | Plage de silence et silence temporaire : notifications retenues puis résumées en une seule ; les sessions qui attendent et les blocages passent toujours. |
| **Mise à jour en un clic** | Bouton « Installer » du bandeau : téléchargement, SHA-256, `pkexec`, redémarrage de l'application. |
| **Intégration Claude Code** | Ligne d'état dans chaque session, bascule automatique quand une session est bloquée. |
| **Sessions** | Un seul onglet : projets à gauche, sessions ouvertes et conversations du projet à droite ; consommation, reprise, nouvelle session (dossier, compte, modèle, permissions), terminal / dossier du projet. |
| **Compte par projet** | Un compte préféré par dossier (sous-dossiers compris), bascule proposée à l'ouverture d'une session, compte présélectionné dans « Nouvelle session ». |
| **Terminal intégré** | Sessions Claude Code dans des onglets de l'application : activité, reprise après arrêt ou après une limite, deux sessions côte à côte, messages en attente, onglets rouverts au redémarrage, copier/coller, liens, confirmation avant fermeture. |
| **Conversations** | Historique de toutes les conversations du PC (onglet Sessions), recherche, aperçu, export Markdown, coût, reprise dans l'application, VS Code ou un terminal externe, renommage, projets déplacés. |
| **Journal des bascules** | Chaque changement de compte avec sa raison en clair, groupé par jour (onglet Historique, `ccs journal`). |
| **Raccourcis clavier** | Raccourcis globaux GNOME, même application fermée : ouvrir, sessions, nouvelle session, compte suivant ou meilleur, pause. |
| **Analyse** | Où part l'usage : par projet, modèle, heure et compte, avec des conseils concrets ; bilan de la semaine et conseiller de formule. |
| **File de tâches** | Des tâches pour Claude quand tu n'es pas là : « dès qu'il y a du quota », « cette nuit » ou à une heure. Exécutées sans fenêtre, une à la fois, par la file de Gagarine quand elle existe ; reprise après une limite ; notification à la fin (onglet Planning, `ccs tache`). |
| **Notifications sur le téléphone** | Optionnel, désactivé par défaut : via ntfy, le nom du projet et l'état (session qui attend, tâche finie, bascule, comptes épuisés), jamais le contenu ; lien et QR code dans les Réglages, `ccs telephone`. |
| **Archive des conversations** | Claude Code efface les conversations de plus de 30 jours : CCS en garde une copie compressée, cherchable, avec aperçu, export et reprise comme les autres. |
| **Fiche « où j'en étais »** | En un coup d'œil : dernière demande, début de la dernière réponse, fichiers modifiés, liste de tâches, branche, compte. Lue dans le journal, sans appeler Claude (`ccs fiche <id>`, aperçu d'une conversation). |
| **Sauvegarde chiffrée** | Comptes (jetons compris), réglages, comptes par projet et budgets dans un seul fichier chiffré par gpg ; restauration avec confirmation (Réglages, `ccs sauvegarde`, `ccs restaurer`). |
| **Mémoire des sessions** | RAM de chaque session ouverte, total, sessions inactives, bouton « Fermer » avec confirmation ; rien n'est jamais fermé tout seul (onglet Sessions, `ccs sessions`). |
| **Alerte de contexte lourd** | Une notification par session quand son contexte dépasse 150 000 tokens (réglable), avec le coût d'un message ; badge dans l'onglet Sessions et la ligne d'état. |
| **Budget par projet** | Un budget hebdomadaire en équivalent dollars par projet, alertes à 80 % et 100 % ; ne bloque jamais rien (onglet Analyse, `ccs budget`). |
| **Bilan de santé** | `ccs doctor` : service, versions, barre du haut, intégration, comptes, Claude Code, terminal ; une commande à copier par problème. |
| **Application** | « CCS » (GTK 4) : Comptes, Planning, Sessions, Terminaux, Historique, Analyse, Réglages. |
| **Icône dans la barre du haut** | Jauge du compte actif (vert / orange / rouge, ⏸ en pause) ; au clic : comptes, recharges, prévisions, sessions, interrupteurs, pause, nouvelle version, journal des bascules, bilan de la semaine. |
| **Service** | Unité systemd utilisateur : relevé toutes les 5 min, toutes les minutes près des limites ; avec l'orchestrateur, réveil précis aux fins de fenêtre ; nouvelle version cherchée une fois par jour. |

## Installation

Ubuntu 24.04 (ou Debian/Ubuntu récent avec GTK 4, libadwaita ≥ 1.5 et, pour le
terminal intégré, VTE pour GTK 4 : `gir1.2-vte-3.91`).
Claude Code doit être installé
(`claude` dans le `PATH`).

### Par le dépôt APT (recommandé)

CCS a son dépôt APT signé, sur GitHub Pages : <https://mawena.github.io/CCS/apt>.
Une fois CCS installé, **les nouvelles versions arrivent avec les mises à jour
du système** (`sudo apt update && sudo apt upgrade`, ou la Logithèque). Trois
façons de faire la première installation :

```sh
# 1. l'installateur : ajoute la clé et le dépôt, puis installe CCS
curl -fsSL https://mawena.github.io/CCS/installer.sh | sudo sh

# 2. à la main, les mêmes étapes
sudo curl -fsSL https://mawena.github.io/CCS/apt/ccs.gpg -o /usr/share/keyrings/ccs.gpg
sudo curl -fsSL https://mawena.github.io/CCS/apt/ccs.sources -o /etc/apt/sources.list.d/ccs.sources
sudo apt update && sudo apt install ccs

# 3. le .deb d'une release GitHub : il ajoute lui-même le dépôt APT
gh release download -R mawena/CCS -p '*.deb'      # ou depuis la page Releases
sudo apt install ./ccs_*_all.deb
```

Le site <https://mawena.github.io/CCS/> donne les mêmes commandes, à copier.
Clé de signature « CCS APT (mawena) » (ed25519), empreinte
`D21A 5E7D B4D3 56E5 5961 F7C6 6568 A5B4 420A ACD2` ; le paquet installe
lui-même sa source (`/etc/apt/sources.list.d/ccs.sources`) et sa clé
(`/usr/share/keyrings/ccs.gpg`).

### Après la première installation

```sh
systemctl --user daemon-reload
systemctl --user enable --now ccs-daemon
claude-accounts tray &            # l'icône, sans attendre de te reconnecter
ccs integrate on                  # optionnel : ligne d'état et bascule après blocage dans Claude Code
ccs doctor                        # tout doit être au vert
```

Le service démarre ensuite seul à chaque session, l'icône de la barre du haut
aussi.

**Indicateur invisible ?** Active l'extension GNOME « Ubuntu AppIndicators » :
`gnome-extensions enable ubuntu-appindicators@ubuntu.com` (ou bouton dans
Réglages).

### Mettre à jour

- **Par apt** (dépôt ajouté par le paquet) : `sudo apt update && sudo apt upgrade`.
- **En un clic** : CCS te prévient quand une nouvelle version est publiée
  (notification, icône, bandeau de la fenêtre, Réglages ; vérification sur
  GitHub au plus une fois par jour). Le bouton **Installer** du bandeau, ou
  `ccs mise-a-jour`, télécharge, vérifie et installe le paquet.
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
4. **Active l'orchestrateur** : `ccs orch on`, puis règle ta plage horaire dans
   l'application (« CCS » dans le menu, ou `ccs gui`).

## Commandes

| Commande | Effet |
|---|---|
| `ccs` | Liste les profils (● = actif) |
| `ccs <nom>` | Bascule sur un profil (ou `ccs use <nom>`) |
| `ccs next` / `ccs best` | Profil suivant / meilleur compte du moment |
| `ccs status` | Compte actif, prévision, meilleur compte, capacité, orchestrateur, pause, service |
| `ccs plan` | Planning des fenêtres et recharges à venir |
| `ccs sessions` | Sessions Claude Code ouvertes : projet, état, consommation, RAM par session et totale, sessions inactives, contexte lourd |
| `ccs conv [mots]` | Historique des conversations du PC, recherche, `-p <projet>`, `--vscode`/`--terminal` |
| `ccs resume <id>` | Reprend une conversation ici, `--vscode`, `--new-terminal`, `--dir <dossier>` |
| `ccs title <id> <titre>` | Renomme une conversation (comme `/rename`) |
| `ccs preview <id>` | Affiche la conversation en Markdown, coût en en-tête (alias `ccs apercu`) |
| `ccs export <id> [fichier.md]` | Enregistre la conversation en Markdown (défaut : `<titre>.md` dans le dossier courant) |
| `ccs integrate on\|off\|status` | Ligne d'état et bascule après blocage dans Claude Code |
| `ccs usage` | Usage détaillé de tous les comptes, prévisions, rythme hebdo |
| `ccs orch on\|off` | Orchestrateur |
| `ccs auto on\|off` | Bascule automatique à 98 % |
| `ccs pause [1h\|4h\|demain\|manuel\|off\|status]` | Met en pause la bascule automatique et l'orchestrateur (`status` par défaut) |
| `ccs doctor` | Bilan de santé, avec la commande qui corrige chaque problème (alias `ccs bilan`) |
| `ccs analyze [--days N]` | Consommation par projet, modèle, heure, compte + conseils |
| `ccs formule` | Conseiller de formule : combinaison conseillée, raisonnement, équivalent API (alias `ccs conseil`) |
| `ccs semaine [--precedente N]` | Bilan de la semaine (`--precedente N` : N semaines plus tôt) |
| `ccs mois [--precedent N]` | Rapport mensuel (dernier mois terminé par défaut ; `--precedent N` : N mois plus tôt, 0 à 120) |
| `ccs moment [--duree 3h] [--sur 24h]` | Meilleur moment pour une grosse tâche (durée 1 à 10 h, horizon 1 à 72 h) |
| `ccs silence [1h\|4h\|demain\|off\|reprendre\|status]` | Ne pas déranger : silence temporaire des notifications (`status` par défaut ; alias `ccs quiet`) |
| `ccs mise-a-jour [--verifier]` | Installe la dernière version de CCS (ou seulement la vérifie) ; alias `ccs maj` |
| `ccs journal [--jours N\|--tout]` | Journal des bascules (7 derniers jours par défaut) |
| `ccs projet [<dossier>] [<compte>\|aucun]` | Compte par projet : liste, compte d'un dossier, association (`aucun` la retire) |
| `ccs raccourcis [status\|on\|off\|set]` | Raccourcis clavier globaux (GNOME) : état, activer, retirer, changer (alias `ccs shortcuts`) |
| `… --notifier` | Avec `ccs <nom>`, `ccs use`, `ccs next`, `ccs best`, `ccs pause`, `ccs silence` : résultat aussi en notification (option des raccourcis clavier) |
| `ccs save <nom>` / `ccs add <nom>` | Enregistre le compte connecté / connecte un nouveau compte |
| `ccs rename <a> <b>` / `ccs rm <nom>` | Renomme / supprime un profil |
| `ccs tache` | File de tâches pour Claude : liste ; `ajouter "<message>" [-C dossier] [--modele m] [--droits lecture\|modifications\|tout] [--quand quota\|nuit\|HH:MM]`, `voir <id>`, `annuler <id>`, `supprimer <id>` (alias `ccs taches`, `ccs tasks`) |
| `ccs budget [<dossier> <montant>\|aucun]` | Budgets hebdomadaires par projet : état, définition (en dollars, équivalent API) ou retrait |
| `ccs fiche <id>` | Fiche « où j'en étais » d'une conversation, sans appeler Claude |
| `ccs sauvegarde [fichier]` / `ccs restaurer <fichier> [--oui]` | Sauvegarde chiffrée (gpg) des comptes et réglages / restauration (alias `backup`, `restore`) |
| `ccs telephone [essai]` | Notifications sur le téléphone (ntfy) : état et lien d'abonnement, ou message d'essai (alias `ccs phone`) |
| `ccs gui` | Application graphique |

Détails : `man ccs`, `man claude-accounts`, [docs/utilisation.md](docs/utilisation.md).

## Configuration

Tout se règle dans l'onglet **Réglages** de l'application — Bascule
automatique, Orchestrateur, Alertes, Ne pas déranger, Conseils, Conseiller de formule,
Intégration, Terminal intégré, Raccourcis clavier, Warm-up, Service — ou par
les commandes `ccs auto`, `ccs orch`, `ccs pause`, `ccs integrate`,
`ccs projet`, `ccs raccourcis`, `ccs tache`, `ccs budget`, `ccs telephone`. Les réglages vivent dans
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
`events`), archive (`archive` : `enabled`, `idle_days`, `max_age_days`),
sessions inactives (`sessions.idle_hours`), alerte de contexte lourd
(`context_alert` : `enabled`, `threshold_tokens`), budgets (`budget` : `enabled`,
`alert_pcts`). Une valeur invalide (mauvais type,
hors bornes, heure impossible) ou un fichier illisible n'empêche rien : la clé
fautive reprend sa valeur par défaut, le fichier n'est pas modifié, et
`ccs doctor` la signale.
Les deux interrupteurs du terminal intégré (**Réglages → Terminal intégré**, ou
menu « ⋮ » de la page Terminaux) sont gardés dans
`~/.claude-accounts/terminals.json`, les comptes par projet dans
`~/.claude-accounts/projects.json`, les budgets dans
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
| « connexion expirée ou révoquée » | `ccs rm <nom>` puis `ccs add <nom>`. |
| Pas de bascule / pas de démarrage | `ccs status` : service en marche ? orchestrateur activé ? dans la plage horaire ? en pause (`ccs pause off`) ? |
| L'icône garde l'ancienne version après une mise à jour | Mise à jour en venant de la 0.4.0 ou d'avant : `pkill -f 'claude-accounts tray'; setsid -f claude-accounts tray`. |
| L'ancienne version s'ouvre | Supprime `~/.local/bin/ccs`, `~/.local/bin/claude-accounts` et `~/.local/share/applications/io.ccs.ClaudeAccounts.desktop`. |
| « CCS » introuvable dans le menu | Alt+F2 puis `r` (X11), ou reconnecte-toi. |
| Icône absente de la barre du haut | Extension « Ubuntu AppIndicators » (voir Installation), puis `claude-accounts tray &`. |
| Pas de ligne d'état dans Claude Code | `ccs integrate status`, puis relance la session. |
| Les sessions s'ouvrent dans un terminal externe | Terminal intégré indisponible : `sudo apt install gir1.2-vte-3.91`, puis rouvre l'application. |
| Une session bloquée n'est pas relancée dans l'onglet | `ccs integrate on` (le hook est nécessaire), interrupteur « Reprise automatique après une limite » du menu « ⋮ » de la page Terminaux, pas de pause en cours ; une touche tapée dans l'onglet après la limite annule la reprise. |
| Pas de proposition de bascule pour un projet | `ccs projet <dossier>` ; rien n'est proposé pendant une pause ni si « Ne plus demander pour ce projet » a été coché (réactive « Proposer la bascule » dans « Compte de ce projet… »). |
| Un raccourci clavier ne fait rien | `ccs raccourcis status` : activé ? combinaison déjà prise (⚠) ? Bureau GNOME seulement ; « commande à mettre à jour » (déplacement du dépôt, installation du paquet, raccourci activé avant la 0.6.0) : « Mettre à jour les commandes » (Réglages) ou `ccs raccourcis on`. |
| « Pas encore assez de relevés pour conseiller une formule » | Le conseiller a besoin d'au moins 3 jours de relevés du service. |

Journaux du service : `journalctl --user -u ccs-daemon -f`.

## Désinstallation

```sh
systemctl --user disable --now ccs-daemon
sudo apt purge ccs             # retire aussi la source APT de CCS
rm -rf ~/.claude-accounts      # optionnel : profils et historique
```

Préfère `purge` à `remove` : la source APT (`/etc/apt/sources.list.d/ccs.sources`)
est un fichier de configuration que `remove` laisse en place, alors que la clé
est retirée ; `apt update` signalerait alors une source sans clé.

## Développement

Projet en **git flow** (`main` / `develop`, tags `vX.Y.Z`), commits
conventionnels en français. Python 3 (bibliothèque standard + PyGObject) et
bash ; pas d'autre dépendance.

```
bin/ccs              commande ccs (bash) : profils et bascule
bin/claude-accounts  lanceur Python de ccs_app
ccs_app/             service, prévisions, alertes, pause, conversations, conseils, journal, raccourcis, tâches, archive, sauvegarde, budgets…
ccs_app/gui/         application GTK 4 / libadwaita et ses dialogues
data/  debian/       unité systemd, entrées de menu, icône, paquet
scripts/             construction du .deb
docs/                guide, architecture, pages man
tests/               tests unitaires et scénario de bout en bout
```

```sh
make test     # tests unitaires + scénario de bout en bout de ccs
make deb      # tests, paquet, SHA256SUMS et lintian dans dist/
```

Essayer une copie de développement sans réveiller l'application installée :
`CCS_APP_ID=io.ccs.ClaudeAccounts.Dev bin/claude-accounts gui` ;
`CCS_NO_VTE=1` force le repli sur le terminal externe.

## Licence

[MIT](LICENSE) © 2026 mawena
