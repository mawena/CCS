# CCS — assistant d'usage multi-comptes Claude Code

Date : 2026-10-26 · Statut : à valider

## 1. Intention

Charles utilise plusieurs comptes Claude Code (abonnements Pro/Max) sur un même
PC Ubuntu. Il veut :

- ne **jamais être coupé** en pleine session parce qu'un compte atteint sa limite ;
- **voir d'un coup d'œil** l'usage de tous les comptes sans se reconnecter ;
- **anticiper** (prévisions, rythme de la semaine) et **savoir quel compte utiliser** ;
- comprendre **où part son usage** pour mieux l'employer.

Point de départ existant (à reprendre dans le dépôt) :

- `ccs` (bash + jq) : profils dans `~/.claude-accounts/<nom>/{oauth.json,account.json}`,
  bascule en réécrivant `~/.claude/.credentials.json` (clé `claudeAiOauth` +
  `organizationUuid`, le reste comme `mcpOAuth` est conservé) et
  `~/.claude.json` (clé `oauthAccount`). Commandes : list, `<nom>`, use, next,
  save, add, rename, rm, current, usage, gui.
- `claude-accounts` (Python, GTK4/libadwaita) : cartes par compte avec usage
  session (5 h) et semaine, bascule, ajout (terminal + `claude auth login`),
  renommer/supprimer, mode `--print`.

## 2. Faits techniques établis

- Usage : `GET https://api.anthropic.com/api/oauth/usage`, en-têtes
  `Authorization: Bearer <accessToken>` et `anthropic-beta: oauth-2025-04-20`.
  Réponse : `limits[]` (`kind` ∈ session, weekly_all, …, `percent`, `resets_at`,
  `scope`) et champs historiques `five_hour`, `seven_day`, `seven_day_opus`…
- Renouvellement : `POST https://platform.claude.com/v1/oauth/token`, JSON
  `{grant_type:"refresh_token", refresh_token, client_id:"9d1c250a-e61b-44d9-88ed-5944d1962f5e", scope}` →
  `access_token`, `refresh_token` (rotation), `expires_in`,
  `refresh_token_expires_in`, `scope`. Jeton d'accès ≈ 8 h.
- **Sessions en cours** : avant chaque requête, Claude Code compare le `mtime`
  de `.credentials.json` à la dernière valeur vue ; s'il a changé, il vide son
  cache et relit le fichier. Une bascule est donc prise en compte par les
  sessions ouvertes **à leur requête suivante**, sans redémarrage.
  Conséquence : le cache de prompt n'est pas partagé entre comptes, la première
  requête après bascule renvoie tout le contexte (coût ponctuel sur le nouveau
  compte). Le libellé de compte affiché par une session ouverte peut rester
  l'ancien.
- Ne **jamais** renouveler le jeton du compte actif pendant qu'un processus
  `claude` tourne (Claude Code le fait lui-même ; double rotation = risque de
  jeton invalidé). Ne jamais appeler `claude auth logout` (révoque le jeton).
- Journaux locaux : `~/.claude/projects/<projet>/*.jsonl`, messages assistant
  avec `timestamp`, `cwd`, `message.model`, `message.usage`
  (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`).
- Poste : Ubuntu 24.04, GNOME (X11), Python 3.12, GTK 4.14, libadwaita 1.5,
  Ayatana AppIndicator (extension `ubuntu-appindicators` active), systemd
  utilisateur actif avec `DISPLAY` et `DBUS_SESSION_BUS_ADDRESS`.

## 3. Objectifs

1. **Collecte** : service d'arrière-plan qui relève l'usage de chaque compte et
   garde l'historique.
2. **Prévisions** : fin de session estimée, rythme hebdomadaire, budget/jour,
   capacité totale restante.
3. **Choix du compte** : « meilleur compte maintenant » avec explication ;
   `ccs best`.
4. **Bascule automatique** avant la coupure (seuil par défaut 98 %), y compris
   pour les sessions déjà ouvertes.
5. **Alertes** (notifications bureau).
6. **Graphiques** 24 h / semaine avec ligne de rythme idéal.
7. **Analyse locale** des journaux : projets, modèles, heures ; conseils.
8. **Indicateur** dans la barre du haut GNOME.
9. **Démarrage anticipé de fenêtre** (« warm-up ») planifiable par compte.
10. Paquet **.deb** installable, projet géré en **git flow**.

## 4. Non-objectifs

- Pas de support macOS/Windows (Keychain, etc.).
- Pas de comptes facturés à l'API (Console) pour l'usage : seulement les
  abonnements claude.ai (OAuth). Ils restent basculables s'ils sont enregistrés.
- Pas de service distant, pas de télémétrie : tout reste local.
- Pas d'utilisation simultanée de deux comptes par deux sessions différentes.

## 5. Anti-objectifs (échec même si « ça marche »)

- Perdre ou invalider un jeton (rotation mal gérée, logout, écriture concurrente).
- Basculer en boucle ou vers un compte lui-même presque épuisé.
- Spammer de notifications.
- Interroger l'API de façon agressive (au plus 1 requête/min/compte en mode
  rapproché).
- Exposer des jetons (fichiers en 600/700, jamais dans les journaux).

## 6. Conception

### 6.1 Organisation

Dépôt `~/Work/Mawena/Projects/CCS`, git flow (`main`/`develop`, préfixe de tag
`v`), commits conventionnels en français (`feat(portée): …`), CHANGELOG au
format Keep a Changelog.

```
bin/ccs                     bash, CLI de profils (existant, étendu)
bin/claude-accounts         lanceur Python (GUI, --print, daemon, tray)
ccs_app/                    paquet Python
  core.py                   profils, jetons, API, verrou (repris de l'existant)
  store.py                  historique SQLite
  forecast.py               prévisions, rythme, capacité, score de compte
  autoswitch.py             décision de bascule (pur) + exécution
  daemon.py                 boucle de collecte, bascule, alertes, warm-up
  transcripts.py            analyse des journaux locaux
  settings.py               réglages JSON
  notify.py                 notifications via D-Bus (org.freedesktop.Notifications)
  gui.py                    application GTK4/libadwaita
  tray.py                   indicateur GTK3 + AyatanaAppIndicator
data/                       .desktop, service systemd, autostart, icône SVG
debian/                     empaquetage debhelper
tests/                      unittest (logique pure)
docs/                       architecture, utilisation
```

### 6.2 Stockage (`~/.claude-accounts/`, 700)

- Profils : inchangés (`<nom>/oauth.json`, `<nom>/account.json`, `usage.json`).
- `history.db` (SQLite) :
  - `samples(ts, profile, kind, percent, resets_at)` ;
  - `events(ts, type, profile, detail)` — bascules (manuelles/auto), alertes
    envoyées, warm-ups, erreurs ;
  - `active_periods` déduites des événements de bascule (pour attribuer
    l'usage local à un compte).
- `settings.json` (voir 6.9).
- Verrou `.lock` (fcntl) pour toute lecture-renouvellement de jeton.

### 6.3 Collecte (daemon)

Service systemd utilisateur `ccs-daemon.service` (`claude-accounts daemon`).

- Cadence normale : toutes les 5 min pour chaque compte.
- Cadence rapprochée (60 s, compte actif seulement) si une limite du compte
  actif ≥ 85 % ou si la fin estimée est à moins de 15 min.
- Renouvelle les jetons des comptes **inactifs** sous verrou. Compte actif :
  lecture du fichier vivant, pas de renouvellement si `claude` tourne.
- Écrit les échantillons, met à jour `usage.json` (dernier connu).
- Expose l'état courant dans `~/.claude-accounts/state.json` (dernier usage,
  prévisions, meilleur compte, prochaine action) pour la GUI et l'indicateur.
- Détecte les bascules manuelles (changement d'`oauthAccount`) et les journalise.

### 6.4 Prévisions (`forecast.py`, logique pure testée)

- **Fin de session** : régression linéaire sur les échantillons de la fenêtre
  courante des 45 dernières minutes (≥ 2 points, ≥ 10 min d'écart) →
  vitesse %/min ; ETA = (100 − u) / vitesse. Verdict : « limite vers HH:MM
  (N min avant réinitialisation) » ou « tient jusqu'à la réinitialisation » ou
  « stable ».
- **Rythme hebdomadaire** : écoulé f = 1 − (reset − maintenant)/7 j ; idéal =
  100·f ; marge = idéal − u ; budget/jour = (100 − u) / jours restants.
  Projection fin de semaine au rythme des dernières 24 h.
- **Capacité totale** : somme sur les comptes de min(100 − session,
  100 − semaine)/100, exprimée en « sessions complètes ».

### 6.5 Meilleur compte

Candidats : session < 90 % et semaine < 95 %. Ordre :

1. comptes dont la fenêtre de 5 h est **déjà ouverte** avec de la marge,
   réinitialisation la plus proche d'abord (capacité perdue sinon) ;
2. puis comptes **au repos** (fenêtre non démarrée), plus grande marge
   hebdomadaire d'abord.

Chaque choix est accompagné d'une raison lisible
(« fenêtre ouverte, 60 % restants, perdus à 14 h »).
`ccs best` bascule vers ce compte (via `claude-accounts best --switch`).

### 6.6 Bascule automatique

Activée par défaut (Charles l'a demandée). Déclenchement si, pour le compte
actif : une limite ≥ seuil (98 % par défaut), **ou** la projection au prochain
relevé dépasse 100 %. Cible : meilleur compte (6.5) avec session < 80 % et
semaine < 95 %. Garde-fous :

- pas de retour vers un compte quitté pour épuisement avant sa réinitialisation ;
- au plus une bascule automatique par 5 min ;
- aucune cible → notification « tous les comptes sont presque épuisés,
  prochain disponible : X à HH:MM », pas de bascule ;
- profil actif non enregistré → aucune bascule (on ne perd pas un compte).

Exécution : même opération que `ccs use` (sauvegarde du jeton vivant dans le
profil actif, puis écriture atomique du profil cible). Les sessions ouvertes
suivent à la requête suivante. Notification + événement journalisé.

### 6.7 Alertes

Via D-Bus `org.freedesktop.Notifications`, une seule fois par seuil et par
fenêtre (anti-spam mémorisé dans `events`) :

- compte actif à 80 % puis 95 % (+ suggestion du meilleur compte) ;
- limite estimée dans moins de 20 min ;
- bascule automatique effectuée / impossible ;
- un compte se réinitialise (« perso est de nouveau à 0 % ») ;
- semaine en avance de plus de 15 points sur le rythme idéal ;
- connexion d'un profil expirée/révoquée.

Chaque type est désactivable dans les réglages.

### 6.8 Démarrage anticipé de fenêtre (warm-up)

Par compte, une liste d'horaires (ex. 07:00 en semaine). À l'heure dite, si la
fenêtre de 5 h du compte n'est pas ouverte, envoi d'une requête minimale :
`CLAUDE_CODE_OAUTH_TOKEN=<jeton du compte> claude -p "ok" --model haiku`
(sans toucher au compte actif). Désactivé tant qu'aucun horaire n'est saisi.
Journalisé.

### 6.9 Réglages (`settings.json`, éditables dans la GUI)

`auto_switch.enabled` (true), `auto_switch.threshold` (98),
`auto_switch.target_max_session` (80), `alerts.*` (activés),
`alerts.session_thresholds` ([80, 95]), `poll.normal_s` (300),
`poll.fast_s` (60), `warmup.<profil>` (liste `{days, time}`).

### 6.10 Interface graphique (GTK4/libadwaita)

Fenêtre « Comptes Claude », navigation par onglets (`Adw.ViewStack`) :

- **Comptes** : en tête, bandeau « Meilleur compte maintenant : X (raison) »
  + capacité totale ; cartes existantes enrichies : prévision de session,
  rythme hebdo (marge, budget/jour), sparkline 24 h.
- **Historique** : graphe par compte (24 h / 7 j), courbe semaine + ligne de
  rythme idéal, marqueurs de bascule. Dessin Cairo (`Gtk.DrawingArea`), sans
  dépendance.
- **Analyse** : tokens par projet, par modèle, par heure (7/30 j), part
  attribuée à chaque compte quand connue ; 3 à 5 conseils générés par règles
  (ex. « projet X : 60 % de ton usage, surtout Opus »).
- **Réglages** : bascule auto, seuils, alertes, warm-up par compte, état du
  service (actif/arrêté, bouton démarrer).

La GUI lit `state.json`/`history.db` ; le bouton Actualiser demande une
collecte immédiate (signal au daemon, ou collecte directe sous verrou si le
daemon est arrêté).

### 6.11 Indicateur barre du haut

Processus séparé GTK3 + AyatanaAppIndicator (autostart XDG). Libellé
« ◔ 32 % » (session du compte actif), menu : comptes avec % et bouton de
bascule, meilleur compte, prévision, « Ouvrir Comptes Claude ».

### 6.12 CLI

`ccs` conserve ses commandes ; ajoute `best`, `auto on|off`, `status`
(prévisions + meilleur compte, texte). `ccs usage` inchangé mais enrichi des
prévisions.

### 6.13 Paquet Debian

Paquet `ccs`, `Architecture: all`, construit par `dpkg-buildpackage` (debhelper
13). Installe : `/usr/bin/ccs`, `/usr/bin/claude-accounts`,
`/usr/lib/ccs/ccs_app/`, `.desktop`, icône hicolor SVG, unité systemd
utilisateur (activée par défaut pour tous les utilisateurs via
`dh_installsystemduser`), autostart de l'indicateur. Dépendances : bash, jq,
procps, python3 (≥ 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (≥ 1.4),
gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1. `claude` (Claude Code) est
recommandé, pas une dépendance (installé hors apt).

Release git flow `release/0.1.0` → tag `v0.1.0`, `.deb` dans `dist/` avec
SHA256SUMS. Après installation, les copies de `~/.local/bin` (qui masquent
`/usr/bin`) et l'ancien `.desktop` utilisateur sont retirés.

## 7. Qualité

- Tests `unittest` sur la logique pure : prévisions, rythme, capacité, score,
  décision de bascule, anti-spam, analyse de journaux, migrations de stockage.
- Tests bout en bout de `ccs` dans un HOME isolé (faux comptes).
- `shellcheck` absent du poste : `bash -n` + tests.
- Aucun test ne touche aux vrais jetons.

## 8. Laissé au constructeur

Mise en page fine, formulations, couleurs, découpage interne des modules,
format exact de `state.json`, détails d'empaquetage (lintian propre).

## 9. Décisions prises par Claude (à vérifier)

- Paquet et projet nommés `ccs`, version de départ 0.1.0.
- Bascule automatique **activée par défaut**, seuil 98 %.
- Warm-up livré mais inactif tant qu'aucun horaire n'est saisi.
- Indicateur dans un processus GTK3 séparé (AppIndicator n'existe pas en GTK4).
- Notifications via D-Bus direct (pas de dépendance `libnotify-bin`).
- Service systemd utilisateur activé par défaut à l'installation.
- Fenêtre de 5 h « au repos » = limite session sans `resets_at` ou à 0 %.
- Warm-up : vérifier pendant la construction que `CLAUDE_CODE_OAUTH_TOKEN`
  n'écrit pas dans `.credentials.json` ; sinon, lancer `claude` avec un
  `CLAUDE_CONFIG_DIR` temporaire contenant uniquement le jeton du compte.
- Bascule manuelle récente (< 5 min) : la bascule automatique la respecte et
  ne repart pas immédiatement de ce compte, sauf au-delà de 99,5 %.
