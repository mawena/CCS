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
  comptes). Le matin, cela donne `début de plage`, puis `+ 2 h 30`… ; dans la
  journée, l'écart se rétablit tout seul, y compris après tes propres
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
