# Guide d'utilisation

Site : <https://mawena.github.io/CCS/>. Installation sur Ubuntu par le dépôt APT
signé (les nouvelles versions arrivent ensuite avec `sudo apt update && sudo apt
upgrade`) :

```sh
curl -fsSL https://mawena.github.io/CCS/installer.sh | sudo sh
```

Les autres façons d'installer (à la main, `.deb` d'une release GitHub, depuis
les sources) et les étapes qui suivent la première installation sont dans le
[README](../README.md#installation).

## Profils

- `ccs save <nom>` enregistre le compte actuellement connecté dans Claude Code.
- `ccs add <nom>` lance `claude auth login` : le navigateur s'ouvre, connecte-toi
  avec le compte à ajouter. CCS refuse d'ajouter deux fois le même compte.
- `ccs <nom>` (ou `ccs use <nom>`) bascule. Si le compte connecté n'est
  enregistré nulle part, CCS refuse de basculer pour ne pas le perdre : fais
  d'abord `ccs save`. Un argument en trop est refusé (usage, code 1).
- `--notifier` (avec `ccs <nom>`, `ccs use`, `ccs next`, `ccs best`,
  `ccs pause`, `ccs silence`) affiche aussi le résultat en notification passagère : « Bascule
  sur boulot » (avec l'adresse du compte et les sessions qui suivront), « Déjà
  sur perso », « Bascule impossible », « Aucun compte disponible », « Pause
  jusqu'à 14:00 », « Pause levée », « Pause impossible ». C'est l'option des
  [raccourcis clavier](#raccourcis-clavier-globaux), qui n'ont pas de terminal
  pour afficher le résultat. La notification passe par
  `claude-accounts notify`, ou `notify-send` à défaut, et ne fait jamais
  échouer la commande.
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

Pendant une [pause](#pause), aucune bascule automatique n'a lieu. Chaque
bascule, et sa raison, se retrouve dans le [journal des
bascules](#journal-des-bascules).

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

### Meilleur moment pour une grosse tâche

La carte **Meilleur moment pour une grosse tâche** de l'onglet Planning, et
`ccs moment`, répondent à « quand lancer un long travail ? ». L'unité est la
**fenêtre de 5 h disponible**, pas une durée de travail : la durée choisie
(1, 2, 3, 4, 6 ou 8 h dans la carte) sert à dire si les fenêtres couvrent la
tâche.

```sh
ccs moment                       # tâche de 3 h, sur les 24 prochaines heures
ccs moment --duree 2h30 --sur 48h
```

La durée va de 1 à 10 h (`3h`, `2h30`, `90m`, `1,5h`), l'horizon (`--sur`) de 1 à
72 h. Code de sortie 0 ; 1 sans état du service ; 2 pour un usage incorrect.

Comment c'est calculé :

- les départs testés sont **maintenant**, puis **tous les quarts d'heure**
  sur l'horizon ;
- pour chaque départ, CCS additionne, compte par compte : le **reste de la
  fenêtre en cours**, la **fenêtre neuve** à sa réinitialisation puis toutes
  les 5 h, et une **fenêtre fraîche** qui démarre au départ. Une fenêtre en
  cours n'est comptée entière que s'il en reste au moins 1 h ;
- le **plafond hebdomadaire** limite le total, avec l'hypothèse qu'**une semaine
  pleine équivaut à environ 10 fenêtres de 5 h** : c'est une estimation, pas une
  mesure ;
- les comptes en erreur sont ignorés, et une pause en cours est signalée ;
- « **Lance-la maintenant** » s'affiche quand maintenant est à 10 % du meilleur
  départ ; sinon, le meilleur moment et jusqu'à 3 alternatives espacées d'au
  moins 90 min. La carte dessine la frise des 24 h.

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
L'application ne propose pas non plus de basculer sur le [compte d'un
projet](#compte-par-projet), et « Nouvelle session… » ne le présélectionne pas.
Restent actifs : tes bascules manuelles, les alertes et les warm-up programmés.

À l'échéance, le service lève la pause de lui-même (il se réveille à l'heure
dite) et envoie « Pause terminée ». L'état est gardé dans
`~/.claude-accounts/pause.json` : une pause survit à un redémarrage.

## Journal des bascules

Section **Journal des bascules** de l'onglet **Historique**, sous les courbes,
ou `ccs journal` : chaque changement de compte, de la plus récente à la plus
ancienne, groupé par jour (*Aujourd'hui*, *Hier*, *Lundi 2 novembre*…), avec
l'heure, « compte quitté → compte choisi » et la raison en clair :

| Genre | Raison affichée |
|---|---|
| Automatique | « Bascule automatique avant la coupure (perso à 98 %) », avec « 100 % prévu avant le prochain relevé » quand c'est la projection qui a décidé |
| Anticipée | « Bascule anticipée de l'orchestrateur : boulot allait perdre 42 % de quota dans 35 min » |
| Après un blocage | « Bascule après un blocage (limite atteinte dans Portail) » : le projet de la session bloquée, sinon le compte quitté |
| Manuelle | Selon son origine : « Bascule manuelle depuis l'application » (bascule faite dans la fenêtre), « … depuis l'icône », « … depuis une notification », « … par la commande ccs », « … par un raccourci clavier », « Bascule pour une nouvelle session (compte choisi) », « Bascule vers le compte du projet Portail » ; « Bascule manuelle (application, icône ou « ccs use ») » quand l'origine n'est pas connue |
| Échec | « Échec de la bascule automatique vers boulot : … », avec le message de `ccs` |
| Limite sans bascule | « Limite atteinte dans Portail pendant une pause : pas de bascule », « … : aucun autre compte disponible » |
| Démarrage de fenêtre | « Fenêtre de 5 h démarrée par l'orchestrateur », « Warm-up de 07:00 : fenêtre de 5 h démarrée », ou son échec |
| Début du suivi | « Début du suivi : perso était le compte actif » (premier relevé du service) |

Les échecs et les limites sans bascule sont marqués (✗ dans le terminal, icône
d'erreur ou d'avertissement dans l'application) ; le texte brut de la décision
s'affiche au survol. Boutons **7 jours**, **30 jours** et **Tout** ; « Afficher
100 de plus » en bas d'une longue liste.

```sh
ccs journal              # 7 derniers jours
ccs journal --jours 30
ccs journal --tout       # tout l'historique gardé
```

Code de sortie 2 pour un nombre de jours nul, négatif ou illisible, ou
`--jours` avec `--tout` ; 1 si l'historique est illisible. Le menu de l'icône
ouvre aussi le journal (« Journal des bascules »).

Tout vient de l'historique du service (`history.db`) : bascules, échecs,
alertes du hook et démarrages de fenêtre. L'origine d'une bascule manuelle est
notée juste avant par celui qui la lance : l'application, l'icône ou `ccs`
lui-même (« ccs » à la main, « raccourci » avec `--notifier`), dans
`~/.claude-accounts/switch-origin.json` ; le service la lit en constatant la
bascule. `CCS_VIA` définie et vide empêche `ccs` de la noter (l'application,
le service et l'icône, qui notent la leur, lancent `ccs` ainsi). Le projet d'une session bloquée est
lu dans les marqueurs de limite (`~/.claude-accounts/limits/`) tant qu'ils
existent (24 h au plus). Les bascules d'avant la 0.6.0 restent lisibles,
avec moins de détails (pourcentage relu dans la raison, compte quitté déduit
de la bascule précédente).

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
- nouvelle version de CCS (voir [Mises à jour](#mises-à-jour)) ;
- **conseil de modèle** près des limites (`alerts.model_advice`,
  `alerts.model_advice_pct`) et **bilan de la semaine**
  (`alerts.weekly_report`, `alerts.weekly_report_day`,
  `alerts.weekly_report_hour`) : voir [Conseils](#conseils).

Chaque alerte n'est envoyée qu'une fois par fenêtre (une fois par semaine pour
la fin de semaine prévue et le bilan).

## Ne pas déranger

**Réglages → Ne pas déranger** (`alerts.quiet`) :

| Clé | Défaut | Rôle |
|---|---|---|
| `enabled` | `false` | Active la plage de silence |
| `start` / `end` | `22:00` / `08:00` | Début et fin, heure locale ; la plage peut passer minuit |
| `days` | `[0,1,2,3,4,5,6]` | Jours où la plage commence (0 = lundi … 6 = dimanche) : une plage du vendredi 22:00 au samedi 08:00 compte pour le vendredi |
| `allow_waiting` | `true` | Laisse passer « attend ta réponse » et son rappel |

Les bornes suivent l'heure locale réelle (changement d'heure compris).

**Silence temporaire** : `ccs silence 1h`, `4h` ou `demain` (jusqu'à la fin de
la plage de silence en cours ou prochaine, sans plage jusqu'à 08:00) ; `ccs silence off` (ou `reprendre`) lève le
silence, `ccs silence status` (défaut) affiche l'état. Alias : `ccs quiet`.
`--notifier` affiche aussi le résultat en notification passagère (« Ne pas
déranger jusqu'à 08:00 », « Silence levé »). Une durée inconnue donne le code 2.
`ccs status` rappelle le silence : « Ne pas déranger jusqu'à … (ccs silence off
pour reprendre) », ou « Ne pas déranger (plage de silence) … » pendant une plage
des réglages. Le silence temporaire est gardé dans
`~/.claude-accounts/quiet.json`.

Aussi dans le **menu principal de l'icône** (après le bloc de pause) :
« Ne pas déranger — silence jusqu'à 08:00 » (ou « plage de silence … »), avec
« 1 heure », « 4 heures », « Jusqu'à demain 08:00 » et « Reprendre les
notifications » (actif seulement pour un silence temporaire : une plage des
réglages ne se lève pas d'un clic). L'indicateur affiche 🔕 pendant un silence,
avant le symbole de pause. Le raccourci clavier « Ne pas déranger 1 h »
(`silence`, Super+Alt+D, désactivé par défaut : `ccs raccourcis on silence`) est
décrit dans [Raccourcis clavier globaux](#raccourcis-clavier-globaux).

**Pendant le silence**, les notifications sont retenues et comptées
(`~/.claude-accounts/quiet_held.json`). À la fin, **un seul résumé** « Fin du
silence » dit combien ont été retenues. Une alerte retenue n'est jamais renvoyée
après coup : elle n'est que résumée. **Jamais retenues** : « attend ta réponse »
et son rappel (si `allow_waiting`), les sessions bloquées par une limite, le
résumé lui-même et les retours des raccourcis clavier.

L'état est publié dans la clé `quiet` de `state.json` (`active`, `until`,
`source`, `held`).

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

En haut de l'onglet, deux cartes calculées à la première ouverture, l'une
après l'autre et sans figer la fenêtre (bouton « Recalculer » de chaque
carte) : le **Bilan de la semaine** et le **Conseiller de formule** (voir
[Conseils](#conseils)).

## Conseils

### Conseiller de formule

`ccs formule` (alias `ccs conseil`), ou la carte **Conseiller de formule** de
l'onglet Analyse : la combinaison de comptes Pro, Max ou Ultra la moins chère
pour ton usage réel, et pourquoi.

```
Conseiller de formule
Conseil : 2 Pro — 40 $/mois

• Relevés analysés : 4 semaines (du 9 octobre au 6 novembre).
• Usage par semaine : 1,3 Pro en moyenne, 1,6 au plus (semaine du 23 octobre) — 1 Pro = …
• Fenêtres de 5 h : jusqu'à 1,4 sessions Pro consommées en même temps, tous comptes confondus.
• Limite atteinte 3 fois, 2 semaines sur 4.
• Capacité inutilisée : 35 % en moyenne de ce que tu paies (2 Pro, 2,0 Pro par semaine) ; la semaine la plus chargée en a utilisé 80 %.
• Avec 20 % de marge : il te faut 1,9 Pro par semaine et 1,7 sessions Pro sur 5 h.
• La moins chère qui couvre ce besoin : 2 Pro — 40 $/mois (2,0 Pro par semaine, 2,0 sessions Pro sur 5 h).
• C'est ta formule actuelle : rien à changer.
• Sans bascule entre comptes : Max — 100 $/mois.
• Équivalent API : ≈ 412,30 $ sur 28 jours de journaux Claude Code de ce PC, soit ≈ 448,23 $/mois, contre 40 $/mois payés (×11). claude.ai et les autres appareils n'y figurent pas.
• Tarifs du 6 novembre 2026 (claude.com/pricing), facturation mensuelle, hors taxes : Pro 20 $, Max 100 $, Ultra 200 $.
```

- **Le besoin** se lit dans les relevés du service (`history.db`), sur les
  4 dernières semaines glissantes (`advisor.weeks`), en **unités Pro** : 1 Pro
  = la limite hebdomadaire (ou de 5 h) d'un compte Pro ; 1 % d'un Max vaut 5 %
  d'un Pro. Pour la semaine, chaque compte compte pour le plus haut pourcentage
  de ses propres fenêtres (une semaine en cours depuis plus d'un jour est
  projetée à son rythme) ; pour les fenêtres de 5 h, CCS retient le plus fort
  usage cumulé de fenêtres ouvertes en même temps sur plusieurs comptes.
- Une semaine trop peu couverte par les relevés (moins de la moitié) est
  ignorée ; il faut au moins **3 jours** de collecte pour un premier conseil.
  Une semaine où tu as été bloqué sans autre compte disponible compte 15 % de
  plus : l'usage mesuré y était bridé.
- **La combinaison** : la moins chère (puis celle qui a le moins de comptes)
  qui couvre le besoin le plus haut, **marge de 20 %** comprise
  (`advisor.margin_pct`), parmi les combinaisons d'au plus 3 comptes
  (`advisor.max_accounts`). Quand elle demande plusieurs comptes, la meilleure
  formule à un seul compte est donnée aussi (« Sans bascule entre comptes :
  … »).
- **Les formules** (claude.com/pricing, relevé le 6 novembre 2026, facturation
  mensuelle, hors taxes) : Pro 20 $/mois (17 $ en annuel), la référence ; Max
  100 $, « 5x » (5 Pro par fenêtre de 5 h et par semaine) ; Ultra 200 $ —
  l'ancien Max 20x —, sans limite de 5 h et 10 Pro par semaine. Après
  120 jours, la table est signalée « à vérifier ». Le réglage
  `advisor.plan_prices` remplace ces prix
  (`{"pro": 20, "max5": 100, "max20": 200}`, en $ par mois).
- **La formule de chaque compte** est lue dans sa connexion
  (`subscriptionType`, et `rateLimitTier` pour distinguer Max et Ultra). Un Max
  sans palier connu est supposé « 5x » (le raisonnement le dit) ; si la
  détection se trompe, `advisor.profile_plans` l'impose
  (`{"perso": "max20"}`, valeurs `pro`, `max5`, `max20`). Un compte d'une autre
  formule est ignoré.
- **L'équivalent API** : ce que tes conversations Claude Code de la période
  auraient coûté au tarif de l'API (voir [Coût d'une
  conversation](#coût-dune-conversation)), ramené au mois et comparé à ce que
  tu paies. Il ne compte que les journaux **de ce PC** : claude.ai et tes
  autres appareils n'y figurent pas.

La carte reprend le conseil, ce que tu paies, ce qui est conseillé et
l'équivalent API mensuel, puis le raisonnement complet. Dans le terminal, un
message d'attente s'affiche pendant le calcul (sur la sortie d'erreur) ; code
de sortie 1 si le calcul échoue.

**Réglages → Conseiller de formule** :

| Réglage | Clé | Valeurs |
|---|---|---|
| Semaines analysées | `advisor.weeks` | 1 à 12 (4 par défaut) |
| Marge de sécurité (%) | `advisor.margin_pct` | 0 à 100 par pas de 5 (20) |
| Comptes au plus | `advisor.max_accounts` | 1 à 5 (3) |
| Formule de « perso » | `advisor.profile_plans` | Automatique, Pro, Max ou Ultra ; la ligne n'apparaît que pour une formule non reconnue, un Max sans palier connu ou une formule déjà imposée |
| Tarifs des formules (ligne dépliable) | `advisor.plan_prices` | Pro, Max, Ultra en $/mois (0 à 2000) ; revenir au tarif publié retire la surcharge |

### Conseil de modèle près des limites

Quand le compte actif dépasse **80 %** (`alerts.model_advice_pct`) de sa
session de 5 h ou de sa semaine, CCS regarde le modèle de tes réponses des
30 dernières minutes. Si c'est surtout un modèle cher, une notification
propose la famille suivante — **Fable → Opus → Sonnet → Haiku** :

> perso : session à 86 % avec Opus — Passer à Sonnet (/model sonnet) ferait
> durer ce qui reste environ ×1,7, d'après les tarifs de l'API appliqués à tes
> réponses des 30 dernières minutes (ordre de grandeur : les limites ne suivent
> pas exactement ces tarifs).

Le gain « ×N » applique les tarifs de l'API aux tokens réellement consommés :
c'est un **ordre de grandeur** (« plus de ×5 » au-delà ; pas de notification
sous ×1,25). **Une seule notification par fenêtre de 5 h** et par compte. Dans
Claude Code, la [ligne d'état](#intégration-dans-claude-code) ajoute
« → sonnet ? » tant que la session utilise un modèle cher au-delà du seuil.
Réglages → Conseils : **Proposer un modèle moins cher près des limites**
(`alerts.model_advice`, activé par défaut) et **Seuil du conseil (%)**
(`alerts.model_advice_pct`, 50 à 99).

### Bilan de la semaine

`ccs semaine`, la carte **Bilan de la semaine** de l'onglet Analyse (menu pour
choisir la semaine en cours ou l'une des 6 précédentes, la dernière terminée
par défaut) et une **notification hebdomadaire** qui le résume :

- **Comptes** : semaine au plus haut, points consommés, fenêtres de 5 h
  entamées, limites de session atteintes, bascules vers ce compte ;
- **Activité** : conversations, sessions, réponses, tokens et équivalent au
  tarif de l'API ;
- **Modèles** et **Projets** : répartition en tokens pondérés (5 premiers) ;
- **Bascules et alertes** : par genre (automatique, anticipée, manuelle, après
  blocage), alertes par genre, blocages sur une limite ;
- **Par rapport à la semaine précédente** : tokens, équivalent API,
  conversations, fenêtres, bascules, semaine de chaque compte.

```sh
ccs semaine                 # semaine écoulée
ccs semaine --precedente 1  # celle d'avant (0 à 520)
```

Code de sortie 2 pour un nombre de semaines invalide (négatif, illisible, plus
de 520), 1 si le calcul échoue. « Bilan de la semaine » dans le menu de
l'icône ouvre l'onglet Analyse.

**Quelle semaine ?** Par défaut, elle commence quand la plupart de tes comptes
ont commencé leur nouvelle semaine (heures de réinitialisation hebdomadaires
relevées par le service ; lundi 9:00 faute de relevé). `alerts.weekly_report_day`
(0 = lundi … 6 = dimanche) et `alerts.weekly_report_hour` (9 par défaut) la
fixent à un jour et une heure. La notification part une fois par semaine, dans
les deux jours qui suivent ce début, si les relevés couvrent au moins 3 jours
de la semaine écoulée ; le bilan est calculé à part, sans retarder les
relevés. Réglages → Conseils : **Bilan de la semaine** (`alerts.weekly_report`,
activé par défaut), **Jour du bilan** (« Début de semaine des comptes » ou
Lundi … Dimanche) et **Heure du bilan** (0 à 23, pour un jour fixe).

### Rapport mensuel

`ccs mois`, la carte **Rapport mensuel** de l'onglet Analyse (le mois en cours
et les 11 précédents, le dernier mois terminé par défaut) et une
**notification** le 1er du mois :

- **Période** : mois civil en heure locale ; le mois en cours est comparé au
  même nombre de jours du mois précédent ;
- **Comptes** : semaines utilisées, pic hebdomadaire, fenêtres de 5 h entamées,
  limites atteintes, bascules vers ce compte ;
- **Activité** : conversations, sessions, tokens et équivalent au tarif de l'API,
  comparé au prix des formules payées (le « ×N » est omis sur un mois
  incomplet) ;
- **Modèles** et **10 premiers projets** (avec leur coût) ;
- **Évolution** par rapport au mois précédent et **tendance** sur 3 à 6 mois,
  affichée à partir de 3 mois d'activité.

```sh
ccs mois                  # dernier mois terminé
ccs mois --precedent 1    # celui d'avant (0 à 120 ; 0 = le mois en cours)
```

Code de sortie 2 pour un usage incorrect (nombre hors de 0 à 120, option
inconnue), 1 si le calcul échoue. La notification part le 1er du mois à
`alerts.monthly_report_hour` (9 par défaut), le 2 si le PC dormait, seulement si
les relevés couvrent au moins 7 jours du mois écoulé. Réglages → Conseils :
**Rapport mensuel** (`alerts.monthly_report`, activé par défaut) et **Heure du
rapport mensuel**. Comme le bilan de la semaine, il ne couvre que les journaux
Claude Code **de ce PC**.

Le groupe **Conseils** ne fait qu'envoyer des notifications d'aide : elles ne
partent que si les notifications sont activées (Réglages → Alertes →
**Notifications**).

Comme l'équivalent API, l'activité, les modèles et les projets ne viennent que
des journaux Claude Code **de ce PC** ; l'usage des comptes, lui, vient des
relevés (claude.ai et autres appareils compris).

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

L'onglet **Sessions** réunit les sessions ouvertes et l'historique des
conversations (il remplace les anciens onglets Sessions et Conversations) :

(L'ensemble de ce qui suit est l'onglet fixe « Toutes les sessions » de l'onglet
Sessions ; les chats ouverts s'y ajoutent en onglets, voir
[Chat graphique](#chat-graphique).)

- **En haut** : ☰ (afficher ou masquer la liste des projets), la recherche
  (titre, demandes, projet, dossier ; sans accents ni majuscules ; taper
  n'importe où sur la page la lance), le filtre d'origine (Toutes les
  origines, VS Code, Terminal) et **Nouvelle session…**, qui ouvre le
  [dialogue](#nouvelle-session). Recherche et filtre valent pour tout : les
  sessions, les conversations et la liste des projets (un projet sans
  résultat disparaît de la liste). Sans VTE, une ligne indique comment
  installer le terminal intégré.
- **À gauche, les projets** : « Tous les projets » en tête, puis chaque
  projet, ceux où une session est ouverte d'abord, puis du plus récemment
  actif au plus ancien. Un point vert signale une session ouverte, un point
  bleu une session qui attend ta réponse ; à droite, le nombre de
  conversations. La seconde ligne dit « 2 sessions ouvertes » ou « attend ta
  réponse », le [compte du projet](#compte-par-projet) (« compte boulot »), ou
  « dossier introuvable · déplacé ? ». Deux projets du même nom s'affichent
  avec leur chemin.
- **À droite, le projet choisi** :
  - un **en-tête** : nom et chemin du projet, compte du projet (ou « Aucun
    compte associé : les sessions utilisent le compte actif ») avec le bouton
    **Compte de ce projet…**, et **Nouvelle session ▾** (dans l'application ;
    la flèche propose « Avec des options… », « Dans un terminal externe »,
    « Terminal ici » et « Ouvrir le dossier ») ;
  - **Ouvertes maintenant** : une carte par session ouverte du projet ;
  - **Conversations** : l'[historique](#historique-des-conversations) du
    projet, groupé par date.

  Avec « Tous les projets », toutes les sessions ouvertes et toutes les
  conversations, et le bouton **Nouvelle session…** du haut mis en avant.

`ccs sessions` liste aussi les sessions ouvertes. Chaque carte de session
(terminal ou VS Code) montre son projet, son état — *travaille*, *attend ta
réponse* (et pourquoi : permission, question…), *au repos* —, sa durée, son
modèle, sa consommation (tokens pondérés de la conversation) et son
[coût](#coût-dune-conversation). CCS lit les fiches de `~/.claude/sessions` en
lecture seule et ignore les fichiers `.key`.

Actions d'une session : **Afficher** (son onglet du terminal intégré, si elle
y tourne), « Terminal ici », ouvrir le dossier, **Terminer** (après
confirmation : la conversation est conservée et peut être reprise),
« Aperçu… » et « Renommer… » dans son menu « ⋮ ». Reprendre une conversation
(`claude --resume`) ou démarrer une **Nouvelle session** ouvre un onglet du
[terminal intégré](#terminal-intégré) ; le menu « ⋮ » ou la flèche de
« Nouvelle session » garde le terminal externe. Une conversation ouverte
ailleurs (autre terminal, VS Code) n'est pas reprise une seconde fois.

**Fenêtre étroite** : sous 800 sp de large, la liste des projets se replie ;
☰ l'ouvre par-dessus le contenu, et choisir un projet la referme. Sous
560 sp, les boutons passent en icônes et le filtre d'origine affiche
« Toutes ».

**Depuis la ligne de commande** : `claude-accounts gui --page sessions` ouvre
l'application sur cet onglet, `claude-accounts gui --new-session` directement
sur le dialogue « Nouvelle session », que l'application soit déjà ouverte ou
non (voir [Raccourcis clavier globaux](#raccourcis-clavier-globaux)).
`--page` accepte `sessions`, `comptes`, `planning`, `historique`, `analyse`,
`terminaux` et `reglages` (accents et majuscules indifférents ; `conversations`
mène à `sessions`) ; un nom inconnu sort avec le code 2, et `terminaux` sans
onglet ouvert affiche l'onglet Sessions avec un message. Les options se
combinent entre elles et avec `--session`.

### Nouvelle session

Le bouton **Nouvelle session…** de l'onglet Sessions, l'entrée du même nom
dans le menu ☰ de la fenêtre, « Avec des options… » dans le menu de
« Nouvelle session » d'un projet, ou `claude-accounts gui --new-session`
ouvrent un dialogue :

- **Dossier** : le projet d'où tu pars, un projet récent ou un autre dossier
  (bouton dossier) ;
- **Compte Claude** : le compte du projet s'il en a un (« Compte du projet :
  boulot », « hérité de ~/Work » pour un sous-dossier), sinon le compte actif.
  Un compte choisi à la main n'est plus changé quand tu changes de dossier ;
  rien n'est présélectionné pendant une pause ni pour un projet réglé sur « Ne
  plus demander ». Un autre compte que l'actif s'affiche avec un
  avertissement : « La bascule s'applique à toutes les sessions ouvertes ».
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

### Sessions dans le menu de l'icône

Le menu de l'icône contient un sous-menu **Sessions (n)**, ou « Sessions
(1 attend ta réponse) » quand l'une t'attend : une entrée par session (titre,
état, depuis quand), celles qui attendent en premier. Un clic ouvre la session
dans l'application, comme une notification cliquable. Le sous-menu propose
aussi « Toutes les sessions… » (onglet Sessions) et « Terminal ou dossier d'une
session » pour l'ouvrir dans un terminal ou son dossier. Le libellé de
l'indicateur affiche « · 💬 n » quand n sessions attendent ta réponse.

### Notifications

« X a terminé » ou « X attend ta réponse » quand une session qui travaillait
depuis au moins une minute s'arrête (au plus une notification toutes les 2 min
par session). Réglage : **Réglages → Alertes → Sessions Claude Code**.

Un clic sur la notification (ou son bouton **Afficher**) ouvre l'application
sur la session : son onglet du terminal intégré si elle y tourne ; sinon
l'onglet Sessions choisit le projet de la session, retire la recherche ou le
filtre d'origine qui la cacherait et met sa carte en évidence. Si elle s'est
arrêtée entre-temps, « Cette session n'est plus ouverte » s'affiche et le
projet de sa conversation est choisi. L'application est lancée si elle ne
tourne pas. Le **badge** de l'onglet Sessions compte les sessions qui attendent ta
réponse (avec un point d'attention quand l'onglet n'est pas affiché).

**Rappel** : si une session attend ta réponse depuis plus de 10 min, CCS
envoie « X attend toujours ta réponse », une seule fois par attente (pas de
répétition tant qu'elle n'a pas changé d'état, pas de rappel au démarrage du
service pour une attente déjà ancienne). Il part même si les notifications de
sessions sont coupées, et s'ouvre de la même façon au clic. Réglages : **Rappel
des sessions en attente** et **Rappeler après (min)**
(`alerts.waiting_reminder`, `alerts.waiting_reminder_min`).

## Compte par projet

Un dossier de projet peut avoir un **compte préféré** : « boulot » pour
`~/Work`, « perso » pour le reste, par exemple.

- **Choisir** : bouton « Compte de ce projet… » en tête du projet choisi dans
  l'onglet Sessions (un compte, ou « Aucun » ; interrupteur **Proposer la
  bascule**), ou
  `ccs projet` :

  ```sh
  ccs projet                    # projets associés à un compte
  ccs projet ~/Work/App         # compte de ce dossier (le sien ou celui d'un parent)
  ccs projet boulot             # associe le dossier courant à « boulot »
  ccs projet ~/Work/App boulot  # associe ce dossier
  ccs projet ~/Work/App aucun   # retire l'association
  ```

- **Héritage** : un sous-dossier prend le compte du dossier associé le plus
  proche (« hérité de ~/Work »). Limite : choisir « Aucun » pour un
  sous-dossier retire seulement *son* association ; il continue d'hériter du
  compte de son parent.
- **À l'ouverture** : reprendre une conversation ou démarrer une session d'un
  projet depuis l'application, alors qu'un autre compte est actif, demande
  d'abord « Ce projet utilise le compte « boulot » — Basculer ? » :
  **Basculer et ouvrir**, **Ouvrir sans basculer** ou **Annuler**. La case
  **Ne plus demander pour ce projet** coupe la proposition (à rétablir avec
  « Proposer la bascule »). Le compte actif est **commun à toutes les
  sessions** : basculer fait passer toutes les sessions ouvertes sur ce compte
  à leur requête suivante. Si la bascule échoue, rien ne s'ouvre et un message
  l'explique.
- **Nouvelle session…** présélectionne le compte du projet (voir [Nouvelle
  session](#nouvelle-session)).
- **Pendant une [pause](#pause)**, rien n'est proposé ni présélectionné ; une
  bascule choisie explicitement dans « Nouvelle session… » reste possible.

La carte d'un projet indique « Compte du projet : boulot · bascule proposée à
l'ouverture » (mis en avant quand ce n'est pas le compte actif). CCS ne bascule
jamais de lui-même pour un projet : seulement quand tu le confirmes, et
seulement pour ce que tu ouvres depuis l'application. Les associations sont
gardées dans `~/.claude-accounts/projects.json`.

## Historique des conversations

`ccs conv`, ou la partie **Conversations** de l'onglet **Sessions** (« Tous
les projets » pour tout voir, ou un projet à gauche) : toutes les
conversations Claude Code du PC (`~/.claude/projects/*/*.jsonl`, terminal et
VS Code), de la plus récente à la plus ancienne, groupées par date. Dans
l'application, les 60 premières lignes s'affichent, puis « Afficher 60 de
plus » ; le nombre de conversations indique ce qu'un filtre cache
(« 3 conversations sur 340 »).

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
  terminal intégré (« Reprendre dans un terminal externe » et « Copier la
  commande » sont au menu « ⋮ »), et **Afficher**
  remplace les boutons d'une conversation déjà ouverte dans un onglet. Une
  conversation déjà ouverte dans une session n'est pas relancée. Si le projet a
  un [compte](#compte-par-projet) qui n'est pas le compte actif, l'application
  propose d'abord de basculer (VS Code utilise lui aussi le compte actif).
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

« Aperçu… » (menu « ⋮ » d'une conversation ou d'une session ouverte de
l'onglet Sessions) relit une conversation sans la reprendre : tes demandes, les réponses de Claude
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
« 1,2 M tokens · ≈ 3,40 $ ». Dans l'onglet Sessions (conversations et
sessions ouvertes), le montant
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

« Renommer… » (menu « ⋮ » d'une session ou d'une conversation de l'onglet
Sessions, menu d'un onglet du terminal intégré) ou `ccs title <id> <titre>` : comme `/rename` dans
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

## Navigation et apparence

La fenêtre a **quatre onglets** en haut (une barre en bas quand elle est étroite) :

| Onglet | Contenu |
|---|---|
| **Accueil** | cartes des comptes, file de tâches et meilleur moment (l'ancien Planning), fil des derniers événements (bascules, tâches finies) |
| **Sessions** | l'onglet fixe « Toutes les sessions » (projets, sessions ouvertes, conversations), puis un onglet par chat et par shell ouvert |
| **Projets** | les feuilles de route de tous tes projets (voir [Page Projets](#page-projets)) |
| **Analyse** | l'analyse et l'historique (courbes, journal des bascules), choisis par le sélecteur en haut |

**Réglages** est dans le menu ☰, en fenêtre à part. Raccourcis : **Ctrl+1** à
**Ctrl+4** pour les quatre onglets, **Ctrl+virgule** pour les réglages, F5 ou
Ctrl+R pour actualiser. Le badge de l'onglet Sessions compte les chats et les
terminaux qui attendent ta réponse.

Les anciens noms de page restent acceptés partout, y compris par
`claude-accounts gui --page`, par les raccourcis du bureau, par le menu de
l'icône et par le clic sur une notification :

| Nom | Mène à |
|---|---|
| `accueil` | Accueil |
| `comptes`, `planning` | Accueil (`--page planning --task <id>` affiche la tâche) |
| `sessions`, `conversations`, `terminaux` | Sessions |
| `projets` | Projets |
| `analyse`, `historique` | Analyse (partie Analyse ou partie Historique) |
| `reglages` | la fenêtre des réglages |

**Apparence** (Réglages → Apparence) : le **thème** suit le système (Automatique),
ou reste Clair ou Sombre. Chaque compte reçoit **une couleur** automatiquement,
lisible en clair comme en sombre ; le sélecteur de couleur de sa ligne la change,
la flèche arrière revient à la couleur automatique. Cette couleur est reprise sur
les cartes des comptes, les jauges, les courbes de l'analyse, la barre du chat et
la liste des sessions.

## Chat graphique

Une session Claude ouverte depuis CCS (reprendre une conversation, « Nouvelle
session… », « Ouvrir une session dans ce projet ») est un **chat**, dans un onglet de la
page Sessions. Le chat tourne sous le compte que CCS aurait donné à un terminal
(compte actif, ou compte du projet) et lance `claude` en arrière-plan : il n'y
a pas de terminal à regarder.

### Lire la conversation

- Tes messages sont en bulles à droite ; les réponses de Claude, à gauche, en
  Markdown mis en forme : titres, listes, tableaux, code coloré, citations,
  liens. Le texte arrive au fil de l'eau.
- Chaque action de Claude est une **carte repliable** : fichier lu, fichier
  modifié (avec `+12 −3` ; « voir le diff » ouvre la modification dans le
  [panneau Fichiers](#panneau-fichiers)), commande lancée (la sortie est
  repliée), recherche, sous-agent, outil MCP. Une roue tourne tant que
  l'action est en cours ; une action en échec est marquée.
- La **liste de tâches** de Claude s'affiche en cases à cocher qui se mettent à
  jour.
- Un chat **rouvert** (au démarrage, depuis l'historique, ou migré de l'ancien
  format) montre d'abord la conversation, lue dans son journal, **sans lancer
  `claude`** : le processus ne démarre qu'au premier message envoyé. Si la
  conversation est encore ouverte dans un autre terminal, le chat est en lecture
  seule (« Cette conversation est ouverte ailleurs ») jusqu'à ce que l'autre
  processus se termine.

### La barre sous la zone de saisie

À gauche, quatre boutons ; à droite, deux informations.

| Bouton | Choix |
|---|---|
| **Modèle** | « Par défaut » (le réglage de Claude Code) puis les modèles que Claude Code annonce : Opus, Sonnet, Haiku, Fable et les autres |
| **Effort** | Automatique, Faible, Moyen, Élevé, Très élevé, Max. Les niveaux que le modèle choisi n'accepte pas sont grisés (par exemple « Très élevé » avec un modèle 4.6) |
| **⚡ Ultracode** | bouton à bascule : Claude orchestre des workflows pour les grosses tâches. Grisé si le modèle n'accepte pas « Très élevé » |
| **Droits** | **Demander** (par défaut : une carte d'autorisation à chaque action qui le demande), **Modifications acceptées**, **Plan**, **Tout autoriser** (avec le même avertissement que l'option avancée de « Nouvelle session ») |

À droite : le **contexte utilisé** (vert, orange au-delà du seuil de
l'[alerte de contexte lourd](#alerte-de-contexte-lourd), rouge à partir de
90 %) et le **compte**, avec sa couleur.

Le modèle et les droits changent en direct. L'effort et l'ultracode passent par
la commande `/effort` de Claude Code, qui ne fait pas travailler le modèle. CCS
retient lui-même l'effort choisi, car Claude Code ne l'annonce jamais. Un
changement dit « Modèle changé » (ou « Effort changé », « Droits changés ») et
vaut pour les messages suivants. Les valeurs choisies sont gardées par onglet et
retrouvées à la réouverture. Les droits des nouveaux chats viennent du réglage
`chat.rights` (`manual`, c'est-à-dire « Demander », par défaut).

### Autorisations : Autoriser, Toujours, Refuser

Quand Claude veut faire quelque chose qui demande ta permission (une commande,
une modification de fichier selon les droits choisis), le chat affiche une
**carte** avec la commande ou le fichier en évidence, et trois boutons :

- **Autoriser** : cette fois seulement ;
- **Toujours** : autorise aussi les fois suivantes. CCS écrit la règle exacte
  que Claude Code propose (par exemple `Bash(make test)`) dans
  `.claude/settings.local.json`, à la racine du projet. Cela ne change pas les
  droits de toute la session : seuls les cas identiques ne redemanderont plus ;
- **Refuser** : avec un motif facultatif, que Claude reçoit.

Les commandes en lecture seule (`ls`, `cat`…) ne demandent rien. Tant qu'une carte
attend, l'onglet porte un point d'interrogation, le badge de l'onglet Sessions
compte, et l'alerte « attend ta réponse » part (bureau et, si tu l'as activé,
téléphone).

### Écrire à Claude

- **Entrée** envoie, **Maj+Entrée** va à la ligne.
- **`@`** propose les fichiers du projet ; **`/`** propose les commandes (celles
  que Claude Code annonce, plus tes commandes personnalisées et celles des
  plugins). Les commandes réservées au terminal répondent qu'elles ne sont pas
  disponibles ici : utilise alors « Ouvrir dans un terminal ».
- **Images** : colle une image ou glisse-la dans la zone de saisie ; une vignette
  avec ✕ s'ajoute au message. Glisser un fichier de l'arbre insère `@chemin`.
- **Arrêter** : pendant que Claude travaille, le bouton d'envoi devient
  « Arrêter » (Échap fait de même). Claude s'interrompt ; c'est un arrêt voulu,
  pas une erreur, et le message suivant reprend la conversation.
- **Sous-agents** : quand Claude lance des sous-agents (outil Task/Agent), une pastille
  par sous-agent s'affiche au-dessus du fil, avec une roue tant qu'il travaille et une
  coche quand il a fini. Un clic montre sa conversation, en lecture seule ; « Conversation
  principale » ramène au fil, où ta saisie part toujours. Une demande d'autorisation
  venue d'un sous-agent le dit dans sa carte.
- **Écrire pendant que Claude travaille** : Entrée envoie tout de suite, images
  comprises, comme dans le terminal de Claude Code. La bulle porte la mention
  « envoyé pendant que Claude travaille » ; Claude le lit en cours de route ou juste
  après sa réponse. La file de messages (voir [Messages en attente](#messages-en-attente))
  ne sert plus qu'à ce que CCS y met lui-même (reprise après une limite, onglets
  rouverts) ; « envoyer maintenant » y marche même pendant un tour.

### Mise en veille après 30 minutes

Le processus `claude` d'un chat reste vivant entre les messages. Pour ménager la
mémoire du PC, un chat resté **au repos 30 minutes** est mis **en veille** : CCS
arrête proprement ce processus. Ce n'est pas une fermeture : l'onglet,
l'historique et la file de messages restent, et au message suivant CCS relance
`claude` sur la même conversation (`--resume`), sans rien changer à ce que tu
vois. Après 30 minutes le cache de l'API est de toute façon refroidi : la reprise
ne coûte rien de plus en quota. Jamais de veille pendant que Claude travaille,
qu'il attend une autorisation ou qu'une action est en cours.

Le délai se règle avec `chat.idle_suspend_min` dans les réglages (`0` = jamais) ;
il n'a pas de bouton dans la fenêtre des Réglages.

### Ouvrir dans un terminal

Certaines commandes interactives de Claude Code (`/config`, `/login`, les menus
en plein écran…) n'existent pas dans le chat. **Ouvrir cette conversation dans
un terminal** (clic droit sur l'onglet, ou son menu « ⋮ ») arrête le chat — après
confirmation si Claude travaille — et ouvre un onglet terminal qui lance
`claude --resume` sur la même conversation, sous le même compte. Quand ce
terminal est fini, **Revenir au chat** rouvre le chat. Les onglets **shell**
(« Terminal ici ») restent de vrais terminaux.

### Ce qui reste comme dans les terminaux

Reprise automatique après une limite (bascule de compte, puis « continue » dans
le chat), onglets rouverts au démarrage, vue **côte à côte** (Ctrl+Maj+E), alertes
(« attend ta réponse », contexte lourd, budget), compte par projet, confirmation
avant de fermer un onglet pendant que Claude travaille. Une session ouverte dans
un autre terminal reste listée dans « Toutes les sessions » ; CCS ne la reprend
pas tant qu'elle tourne.

## Panneau Fichiers

Chaque onglet de session montre, à gauche, une page **Fichiers** et une page
**Feuille de route** (le sélecteur est en haut du panneau). Le panneau
Fichiers donne les fichiers du dossier de la session, sans quitter le chat.

- **Arbre** : les dossiers se chargent à l'ouverture, et la liste se met à jour
  quand des fichiers changent. Marques git à côté des fichiers : `M` modifié,
  `A` ajouté, `?` non suivi, `D` supprimé. `.git`, `node_modules` et les fichiers
  ignorés par git sont masqués ; le réglage `files.show_ignored` les affiche.
  Clic droit : **Ouvrir**, **Copier le chemin**, **Insérer @chemin dans le
  message**, **Ouvrir avec l'application par défaut**, **Afficher dans Fichiers**.
- **Dispositions** (bouton « disposition » de la page Sessions, retenue pour tous
  les onglets) : **B**, par défaut, arbre | chat | fichier, le panneau du fichier
  n'apparaissant que quand un fichier est ouvert ; **A**, arbre | fichier | chat,
  comme VS Code. Chaque séparation se tire à la souris, et les largeurs sont
  retenues pour chaque disposition. **Ctrl+B** replie ou rouvre l'arbre.
- **Fichier ouvert** : un onglet par fichier, avec numéros de ligne, coloration
  selon le langage (thème clair ou sombre suivi), **Ctrl+F** pour chercher dans le
  fichier, annuler et refaire. Les images s'affichent ; un fichier binaire est
  signalé (« Fichier binaire ») sans être affiché ; au-delà de **2 Mo**, le fichier
  s'ouvre en lecture seule avec un bandeau.
- **Markdown** : le bouton **Source / Aperçu** bascule vers un aperçu mis en forme
  (titres, listes, cases à cocher, tableaux, code coloré, citations, liens). Une
  image distante n'est jamais chargée : elle apparaît comme un lien. L'aperçu suit tes modifications.
- **Enregistrer** : **Ctrl+S**. L'écriture est atomique et les droits du fichier
  sont gardés. Un point sur l'onglet signale un fichier non enregistré ; le
  fermer demande de l'enregistrer, de ne pas l'enregistrer ou d'annuler.
- **Quand Claude modifie un fichier ouvert** : s'il n'a pas de changement de ta
  part, il se recharge tout seul. Sinon, un bandeau propose **Garder les miens**,
  **Prendre la version sur le disque** ou **Voir les différences** : rien n'est
  écrasé sans ton choix.
- **Diff** : « voir le diff » sur une carte de modification du chat ouvre, dans le
  panneau du fichier, les lignes ajoutées et supprimées de cette modification,
  avec un bouton **Fichier entier**.

## Feuille de route

La page **Feuille de route** d'un onglet de session lit `ROADMAP.md` à la racine
du dossier de la session (à défaut, en remontant jusqu'à la racine du dépôt git).
Le format est celui des feuilles de route des projets :
un titre `#`, des phases en titres `##` (« Phase 12 — Titre (0.10.0) ✅ »), des
tâches `- [ ]` / `- [x]`, éventuellement imbriquées, du texte libre entre les
deux. Les phases n'ont pas besoin d'être dans l'ordre ; la version est lue dans
les parenthèses du titre.

L'en-tête donne le projet, la dernière version et le nombre de phases finies.
Chaque phase a sa barre de progression et son compte `cochées/total` ; les phases
non finies sont dépliées, les finies repliées. **Un clic sur une case** la coche
(ou la décoche) dans `ROADMAP.md` en ne changeant que ce caractère ; si le
fichier a changé depuis sa lecture, il est relu d'abord, et jamais réécrit en
entier. Quand Claude coche une case, la tâche s'allume brièvement.

**Le projet de la conversation.** Une conversation lancée depuis ton dossier
personnel ou le Bureau travaille souvent dans un projet ailleurs : dès que Claude lit
ou modifie un `ROADMAP.md` (fichier ouvert, ou commande qui le cite, même après un
`cd`), le panneau suit cette feuille de route. **Choisir une feuille de route…** en
ouvre une autre à la main. Sans `ROADMAP.md`, **Demander à Claude d'en créer une**
n'est proposé que dans un vrai projet (un dépôt git), jamais pour ton dossier
personnel. **Dossier du projet…** (clic droit sur l'onglet) fait partir l'arbre des
fichiers et la feuille de route d'un autre dossier ; si la conversation est arrêtée,
elle y est aussi reliée, et sa reprise se fait depuis le projet. Ces choix sont
gardés quand l'onglet est rouvert.

## Page Projets

L'onglet **Projets** liste les projets où tu as déjà ouvert une session Claude et
qui ont un `ROADMAP.md`. Le réglage `projects.hidden` (liste de dossiers) en
masque certains. Chaque carte donne le nom, la dernière version (dernier tag git
`v*`), la dernière activité (dernier commit ou dernière conversation), la phase
en cours et sa barre.

Un clic sur une carte ouvre le **détail** : la feuille de route complète (cases
cliquables comme dans l'onglet de session), la **frise des versions** (tags git et
dates), les **tâches cochées par jour** sur les derniers jours, tirées de
l'historique git de `ROADMAP.md`, la date de fin de chaque phase finie, et le
bouton **Ouvrir une session dans ce projet**. Les calculs git se font en arrière-plan
et ne bloquent pas la fenêtre ; un projet hors git garde sa carte, sans versions
ni historique. CCS n'écrit jamais dans le dépôt, hors la case que tu cliques.

## Terminal intégré

Les **shells** (« Terminal ici ») et la sortie de secours « Ouvrir dans un
terminal » d'un chat s'ouvrent dans la fenêtre de l'application, dans des onglets
de la page Sessions (avec les chats ; l'ancien nom `terminaux` y mène toujours).
Les sessions Claude elles-mêmes sont des [chats](#chat-graphique) ; ce qui suit
s'applique aux onglets terminal. Il faut VTE pour GTK 4 (`gir1.2-vte-3.91`, dépendance du
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
  comptes, et `→ compte` quand un autre compte est conseillé. Avec un modèle
  cher (Fable, Opus, Sonnet) et le compte actif au-delà du seuil du [conseil de
  modèle](#conseil-de-modèle-près-des-limites) (80 %), elle ajoute
  « → sonnet ? » (la famille moins chère) : le modèle vient du contexte JSON
  que Claude Code envoie sur l'entrée standard, lu sans jamais attendre un
  terminal ni plus de 2 s. Relance tes sessions pour la voir.
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

## Raccourcis clavier globaux

Des raccourcis du bureau GNOME, qui marchent **même quand l'application est
fermée** : c'est le bureau qui lance la commande. Tous sont **désactivés par
défaut**.

| Action (`ccs raccourcis`) | Raccourci par défaut | Commande lancée |
|---|---|---|
| Ouvrir CCS (`ouvrir`) | Super+Alt+C | `claude-accounts gui` |
| Afficher les sessions (`sessions`) | Super+Alt+V | `claude-accounts gui --page sessions` |
| Nouvelle session (`nouvelle-session`) | Super+Alt+N | `claude-accounts gui --new-session` |
| Basculer sur le compte suivant (`suivant`) | Super+Alt+B | `ccs next --notifier` |
| Basculer sur le meilleur compte (`meilleur`) | Super+Alt+M | `ccs best --notifier` |
| Pause 1 h (`pause`) | Super+Alt+P | `ccs pause 1h --notifier` |
| Reprendre (lever la pause) (`reprendre`) | Super+Alt+R | `ccs pause off --notifier` |
| Ne pas déranger 1 h (`silence`) | Super+Alt+D | `ccs silence 1h --notifier` |

Super+Alt+lettre : aucune de ces combinaisons n'est prise par GNOME, le Dock ou
l'assistant de tuilage d'Ubuntu, et des lettres plutôt que des chiffres
marchent pareil en AZERTY. Avec `--notifier`, le résultat d'une bascule ou
d'une pause s'affiche en notification passagère (voir [Profils](#profils)), et
la bascule est notée « par un raccourci clavier » dans le [journal des
bascules](#journal-des-bascules).

**Dans l'application** : **Réglages → Raccourcis clavier**, une ligne par
action avec un interrupteur, le raccourci en texte (« Super+Alt+B ») et
**Modifier** : appuie sur la
nouvelle combinaison (Échap annule, Retour arrière désactive le raccourci). Une
combinaison doit comporter Super, Ctrl ou Alt (seule ou avec Maj, une touche
serait prise à toutes les applications), sauf les touches multimédia. Une
combinaison déjà utilisée par le bureau, un autre raccourci personnalisé ou
une autre action de CCS est signalée (⚠) sans être refusée. Le groupe suit les
changements faits ailleurs tant qu'il est affiché ; **Mettre à jour les
commandes** apparaît quand des raccourcis lancent une autre commande que
celle attendue (paquet installé depuis, dépôt déplacé, ou raccourci activé
avant la 0.6.0, sans `--notifier`) : ils sont signalés « à mettre à jour », et
jamais réécrits sans toi.

**Dans le terminal** :

```sh
ccs raccourcis                     # état (comme « ccs raccourcis status »)
ccs raccourcis on                  # active toutes les actions
ccs raccourcis on suivant pause    # ou seulement celles-ci
ccs raccourcis off                 # retire tous les raccourcis de CCS
ccs raccourcis set suivant Super+Alt+B
```

Alias : `ccs shortcuts`. `set` accepte « Super+Alt+B », « Ctrl+Maj+F5 » ou la
forme de GNOME « <Super><Alt>b ». `ccs raccourcis on <action>` met aussi à
jour la commande d'un raccourci signalé « à mettre à jour ». Code de sortie :
2 pour un usage incorrect, 1 si le bureau n'est pas pris en charge ou si le
raccourci est refusé.

**Ce que CCS touche** : ce sont des raccourcis personnalisés, les mêmes que
ceux de Paramètres › Clavier › Raccourcis personnalisés, où tu les retrouves
(« CCS : … »). CCS n'écrit que sous ses propres chemins
(`/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/ccs-<action>/`),
ne retire jamais un raccourci qui n'est pas à lui et garde l'ordre de la
liste, relue juste avant chaque écriture. La commande est écrite avec son
chemin complet (`/usr/bin/ccs` pour le paquet installé).

**Autre bureau que GNOME** : `ccs raccourcis` (sur la sortie normale, code 1)
et les Réglages l'indiquent et donnent les commandes (avec un bouton pour les
copier) : crée toi-même les raccourcis dans les réglages du clavier de ton
bureau.

## File de tâches

Une tâche, c'est un message que Claude exécute **sans fenêtre**, pendant que tu es
ailleurs. Tu la poses dans l'onglet **Planning** (bouton « Nouvelle tâche ») ou en
ligne de commande.

Une tâche a un message, un dossier, un modèle (facultatif), des droits et un moment.

| Moment | Quand la tâche part |
|---|---|
| `quota` (défaut) | Dès qu'un compte a du quota. |
| `nuit` | Au meilleur créneau de [Meilleur moment](#meilleur-moment-pour-une-grosse-tâche) dans la plage de nuit (23:00 à 07:00 par défaut, réglable). |
| `HH:MM` | À partir de cette heure, aujourd'hui ou demain. |

| Droits | Effet |
|---|---|
| `lecture` | Claude lit et analyse. Tout ce qui demande une permission est refusé. |
| `modifications` (défaut) | Claude peut modifier des fichiers (`acceptEdits`). |
| `tout` | Claude peut tout faire sans rien demander (`bypassPermissions`). L'application affiche le même avertissement que pour une nouvelle session avancée. À réserver à un dossier que tu peux perdre. |

```sh
ccs tache ajouter "Écris les tests de parser.py" -C ~/Work/projet --quand nuit
ccs tache ajouter "Relis le README" --droits lecture --quand 22:30
ccs tache                 # la liste
ccs tache voir 3          # suit le journal de la tâche 3
ccs tache annuler 3
ccs tache supprimer 3
```

Sans `-C`, le dossier est le dossier courant. `ccs taches` et `ccs tasks` marchent aussi.

Comment ça se passe :

- C'est le **service** qui lance les tâches, **une seule à la fois**. Si la commande
  `gagarine` existe, la tâche passe par sa file, en priorité « fond » : elle ne gêne
  pas ton travail et attend si le poste est chargé.
- Elle utilise le **compte actif**. S'il est au-dessus du seuil de bascule, CCS
  bascule d'abord, sauf pendant une [pause](#pause) : la tâche attend alors la fin
  de la pause.
- Si la limite est atteinte en cours de route, CCS bascule (hors pause), puis
  relance la tâche avec « continue » : 3 tentatives au plus (`tasks.max_attempts`).
- À la fin, une notification dit « tâche finie » ou « tâche échouée », avec la
  durée et le coût équivalent. Un clic ouvre l'application sur la tâche.
- La conversation est ensuite une conversation normale : **Reprendre dans un onglet**
  l'ouvre dans le terminal intégré.
- États : en attente, en cours, à reprendre (limite atteinte), finie, échouée, annulée.

Les tâches sont dans `~/.claude-accounts/tasks.json`, leurs journaux dans
`~/.claude-accounts/tasks/<id>.jsonl`. Interrupteur : `tasks.enabled`.

## Notifications sur le téléphone

Optionnel, **désactivé par défaut**. CCS peut t'envoyer l'état de tes sessions sur le
téléphone, par [ntfy](https://ntfy.sh), un service de notifications simple et libre.

**Activer :** Réglages → Téléphone → « Notifications sur le téléphone ». CCS tire au
hasard un **canal secret** (`ccs-…`) : quiconque le connaît peut lire les
notifications, ne le partage pas. « Nouveau canal » en tire un autre (l'ancien cesse
de marcher). Le serveur est `https://ntfy.sh` par défaut ; tu peux mettre le tien.

**S'abonner sur le téléphone :**

1. Installe l'application **ntfy** (Android : Google Play ou F-Droid ; iPhone :
   App Store).
2. Dans CCS, scanne le **QR code** des Réglages (il est affiché si
   `python3-qrcode` est installé), ou copie le **lien d'abonnement** et ouvre-le sur le
   téléphone. À la main : dans ntfy, « + », puis le nom du canal (et ton serveur s'il
   n'est pas ntfy.sh).
3. Clique sur **Essayer** (ou `ccs telephone essai`) : un message de test doit arriver.

En ligne de commande : `ccs telephone` donne l'état et le lien d'abonnement.

**Quels événements** (chacun a son interrupteur) : une session attend ta réponse, une
tâche est finie ou échouée, une bascule a eu lieu, tous les comptes sont épuisés.

**Ce qui est envoyé :** le nom du projet (le dernier élément du dossier) et l'état,
par exemple « projet : tâche finie ». **Ce qui n'est JAMAIS envoyé :** un titre de
conversation, un message, un chemin complet, un nom de compte.

[Ne pas déranger](#ne-pas-déranger) vaut aussi pour le téléphone, avec la même
exception : une session qui attend ta réponse passe toujours. L'envoi se fait en
arrière-plan ; s'il échoue, rien ne bloque et l'échec est noté dans le journal.

## Archive des conversations

Claude Code efface par défaut les conversations de plus de 30 jours. Le service en
garde une copie, **compressée**, dans `~/.local/share/ccs/archive` (dossier 700) :
les conversations qui n'ont pas bougé depuis 1 jour, puis chaque copie remise à jour
si l'original change. Le travail est léger : 20 fichiers ou 100 Mo au plus toutes les
30 minutes, donc la première archive se remplit en plusieurs passages.

Une conversation dont l'original a disparu reste dans l'onglet **Sessions**, avec la
pastille « archivée » : recherche, aperçu, export et reprise marchent comme avant.
`ccs resume <id>` la restaure avant de la lancer. À la reprise, la conversation est
remise à sa place avec la date du jour, sinon Claude Code l'effacerait de nouveau.

Réglages → Archive des conversations : interrupteur, « Archiver après N jours
d'inactivité », « Supprimer l'archive après N jours » (0 = jamais, le défaut), et la
taille de l'archive. `ccs doctor` donne aussi le nombre de conversations et la taille.

## Fiche « où j'en étais »

Tu reprends une conversation après une semaine et tu ne sais plus où tu en étais ?
La fiche le dit, **sans appeler Claude** : elle est lue dans le journal.

```sh
ccs fiche <id>
```

Elle donne la dernière demande (ce que tu avais écrit, pas les résultats d'outils), le
début de la dernière réponse, les fichiers modifiés, la dernière liste de tâches, le
dossier, la branche git, le compte actif à ce moment (s'il est connu par le
[journal des bascules](#journal-des-bascules)) et la date. Dans l'application, c'est
l'encart en haut de l'aperçu d'une conversation. Elle marche aussi pour une
conversation archivée.

## Sauvegarde chiffrée

```sh
ccs sauvegarde                       # ccs-sauvegarde-AAAA-MM-JJ.gpg dans le dossier courant
ccs sauvegarde ~/Documents/comptes.gpg
ccs restaurer ~/Documents/comptes.gpg
ccs restaurer ~/Documents/comptes.gpg --oui   # sans confirmation
```

Dans l'application : Réglages → Sauvegarde → **Sauvegarder…** et **Restaurer…**.

La sauvegarde contient les profils **avec leurs jetons**, les réglages, les comptes par
projet, les budgets et la configuration des raccourcis. Elle ne contient pas les
conversations, ni les états passagers, caches et journaux.

Elle est chiffrée par **gpg** (AES-256). La phrase de passe se saisit dans la fenêtre
de gpg, jamais en ligne de commande. **Les jetons sont chiffrés, mais garde la phrase
de passe : sans elle, la sauvegarde est perdue, et personne ne peut la retrouver.**
Le fichier est créé en 600. Garde-le hors du PC (clé USB, autre machine).

À la restauration, CCS liste le contenu et demande confirmation avant d'écraser un
profil qui existe déjà (`--oui` pour s'en passer en ligne de commande). Le compte actif
ne change pas. Les raccourcis clavier sont réinstallés.

Il faut `gnupg` (installé avec le paquet) ; `gpg-agent` et `pinentry-gnome3` sont
recommandés pour la fenêtre de phrase de passe.

## Mémoire des sessions

`ccs sessions` et l'onglet **Sessions** montrent, pour chaque session ouverte, la RAM
qu'elle occupe (avec ses processus enfants), le total, et depuis combien de temps elle
est inactive.

Une session est **inactive** quand son journal n'a pas bougé depuis plus de 2 h
(`sessions.idle_hours`). Un bandeau dit « N sessions inactives occupent X Go » et
chaque session inactive a un bouton **Fermer**, avec une confirmation.

**Rien n'est jamais fermé automatiquement.** C'est toi qui décides. Les sessions en
attente de ta réponse comptent comme inactives : vérifie avant de fermer.

## Alerte de contexte lourd

Plus le contexte d'une conversation grossit, plus chaque message coûte cher en quota.
Au-delà de **150 000 tokens** (`context_alert.threshold_tokens`), CCS envoie **une seule
notification par session**. Elle donne le coût d'un message en équivalent dollars et
le conseil : `/compact` pour résumer, ou une nouvelle session.

Un badge apparaît aussi sur la session dans l'onglet Sessions et dans la ligne
d'état de Claude Code. Interrupteur et seuil : Réglages → Alerte de contexte lourd.
La notification respecte [Ne pas déranger](#ne-pas-déranger).

## Budget par projet

Un budget par **semaine**, en équivalent dollars API, pour un dossier de projet (un
sous-dossier compte pour le projet le plus proche). La semaine est la même que dans
`ccs semaine`.

```sh
ccs budget                       # état : dépensé, budget, %, part de la consommation
ccs budget ~/Work/projet 25      # 25 $ par semaine
ccs budget ~/Work/projet aucun   # retire le budget
```

Dans l'application : onglet **Analyse** → « Budgets par projet » → « Ajouter un
budget… », puis les boutons modifier et supprimer de chaque ligne.

CCS alerte une fois à **80 %** et une fois à **100 %**, par projet et par semaine.
Le budget **ne bloque jamais rien** : ni les sessions, ni les tâches. C'est un
repère. Les budgets sont dans `~/.claude-accounts/budgets.json`.

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

### Installer en un clic

Quand le paquet est installé par `dpkg`, le bandeau de la fenêtre propose
**Installer** (le menu de l'icône : « Installer CCS x.y.z… »). Un dialogue
affiche les **notes de la release**, la progression en trois temps
(**téléchargement**, **vérification**, **installation**) et **Voir sur GitHub** ;
à la fin, **Redémarrer l'application** relance la fenêtre sur la nouvelle
version. En ligne de commande : `ccs mise-a-jour` (alias `ccs maj`) ;
`--verifier` cherche seulement la dernière version, sans rien installer. Codes
de sortie : 0 (à jour, installée, ou version signalée avec `--verifier`),
1 (échec, ou copie de développement), 2 (usage incorrect).

Ce que CCS contrôle avant d'installer :

- **origine** : seules les URL
  `github.com/mawena/CCS/releases/download/v<version>/…` ou de l'API des pièces
  jointes du dépôt sont acceptées ; une redirection n'est suivie que vers
  `objects.githubusercontent.com` ou `release-assets.githubusercontent.com`, en
  https ;
- **pièces exigées** : `ccs_<version>_all.deb` et `SHA256SUMS`, avec une limite de
  taille pour chacune ; elles sont téléchargées dans un dossier temporaire
  de droits 0700 ;
- **somme SHA-256** du paquet comparée à `SHA256SUMS` ;
- **contenu du paquet** (`dpkg-deb -f`) : paquet `ccs`, version égale à celle
  annoncée et plus récente que celle installée.

Avec le dépôt APT de CCS (ajouté par le paquet), `sudo apt update && sudo apt
upgrade` fait aussi la mise à jour ; le bouton **Installer** reste utile pour
ne pas ouvrir de terminal.

En ligne de commande, `ccs mise-a-jour` affiche chaque étape au fil de l'eau ;
le texte final va sur la sortie normale si le code est 0, sur la sortie d'erreur
sinon. Une option inconnue donne le code 2. « Installer CCS x.y.z… » du menu de
l'icône (affiché quand une version plus récente est annoncée, en plus de la ligne
« ⬆ CCS x disponible — voir la version ») ouvre l'application, dont le bandeau
propose **Installer**.

L'installation se fait par `pkexec apt-get install -y` : une fenêtre demande ton
mot de passe. Si `pkexec` manque ou si tu le refuses, le dialogue affiche la
commande `sudo apt install '<chemin>'`, à copier dans un terminal. Une **copie
de développement** (lancée depuis le dépôt) n'est pas installée par ce chemin :
elle est « mise à jour par git » (`git pull`).

Installe le nouveau paquet à la main, ou en un clic : le service se relance seul (dans les 5 min) et
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
