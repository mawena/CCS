# Interfaces publiques de CCS (inventaire avant la 1.0.0)

Ce qui sera gelé en 1.0.0 : à partir de là, le casser demandera une version majeure (SemVer).
Inventaire dressé d'après le code de la 0.32.0 (branche `develop`). Les éléments marqués
*interne* servent entre les composants de CCS (services systemd, pont, hooks) : ils sont
listés pour mémoire, mais n'ont pas à être gelés.

Sommaire : 1. Commandes · 2. Pont JSON-RPC · 3. Routes HTTP · 4. Fichiers · 5. Variables
d'environnement · 6. Points à revoir avant le gel.

---

## 1. Commandes

Deux points d'entrée :

- `ccs` (`bin/ccs`, Bash) : bascule entre profils elle-même, et passe le reste à
  `claude-accounts`, parfois avec des alias ou des options en plus.
- `claude-accounts` (`bin/claude-accounts` → `ccs_app/cli.py`, argparse) : toutes les autres
  commandes. Sans sous-commande, il ouvre l'application graphique (`gui`).

### 1.1 Commandes propres à `ccs` (Bash)

| Commande (alias) | Arguments, options | Rôle |
|---|---|---|
| `ccs` / `list` (`ls`) | — | liste les profils (● = actif) |
| `ccs <nom>` | `[--notifier]` | bascule sur le profil `<nom>` (raccourci de `use`) |
| `use` (`switch`, `sw`) | `<nom> [--notifier]` | bascule sur un profil |
| `next` (`n`) | `[--notifier]` | profil suivant utilisable |
| `save` | `<nom>` | enregistre le compte connecté |
| `add` (`login`) | `<nom> [--email A] [--console] [--sso]` | `claude auth login` puis enregistrement |
| `current` (`whoami`) | — | profil actif |
| `rm` (`remove`, `delete`) | `<nom>` | supprime un profil |
| `rename` (`mv`) | `<a> <b>` | renomme un profil |
| `usage` (`u`) | — | → `claude-accounts print` |
| `gui` (`app`) | — (arguments ignorés) | → `claude-accounts gui`, détaché |
| `best` (`b`) | `[--notifier]` | → `claude-accounts best --switch` (bascule toujours) |
| `version` (`--version`, `-v`) | — | version |
| `help` (`-h`, `--help`) | — | aide |

Passées telles quelles à `claude-accounts` (alias Bash entre parenthèses) : `status` (`st`),
`auto`, `pause`, `doctor` (`bilan`), `formule` (`conseil`), `semaine`, `mois`, `moment`,
`silence` (`quiet`), `mise-a-jour` (`maj`), `journal`, `tui`, `serveur` (`server`), `totp`,
`bridge`, `web-serve`, `auth-serve`, `shell-distant`, `projet`, `raccourcis` (`shortcuts`),
`orch` (`orchestrateur`), `plan` (`planning`), `sessions` (`ps`), `tache` (`taches`, `tasks`),
`distant`, `chat`, `budget`, `fiche`, `sauvegarde` (`backup`), `restaurer` (`restore`),
`telephone` (`phone`), `conversations` (`conv`, `historique`), `resume` (`reprendre`),
`title` (`titre`), `preview` (`apercu`, `aperçu`), `export` (`exporter`),
`integrate` (`integration`, 1ᵉʳ argument seulement, `status` par défaut), `analyze` (`stats`).

Non accessibles par `ccs` : `print`, `daemon`, `collect`, `notify`, `statusline`, `hook`, `tray`.

### 1.2 Sous-commandes de `claude-accounts`

| Commande (alias argparse) | Arguments, options | Rôle |
|---|---|---|
| `gui` (défaut) | `--session PID:ID`, `--page ONGLET`, `--task ID`, `--new-session` | application graphique |
| `print` (ancien : `--print`) | — | usage de tous les comptes |
| `status` | — | compte actif, meilleur compte, capacité |
| `best` | `--switch`, `--notifier` | meilleur compte maintenant |
| `auto` | `on\|off` | bascule automatique |
| `orch` | `on\|off` | orchestrateur |
| `pause` | `[1h\|4h\|demain\|manuel\|off\|status]`, `--notifier` | suspend bascule et orchestrateur |
| `silence` (`quiet`) | `[1h\|4h\|demain\|off\|reprendre\|status]`, `--notifier` | ne pas déranger |
| `doctor` | — | bilan de santé (code 1 au moindre problème) |
| `formule` (`conseil`) | — | formule conseillée |
| `semaine` | `--precedente N` | bilan hebdomadaire |
| `mois` | `--precedent N` | rapport mensuel |
| `moment` | `--duree 3h`, `--sur 24h` | meilleur moment pour une grosse tâche |
| `mise-a-jour` (`maj`) | `--verifier` | installe la dernière version |
| `journal` | `--jours N` \| `--tout` | journal des bascules |
| `plan` | — | planning des fenêtres de 5 h |
| `sessions` | — | sessions Claude Code ouvertes |
| `projet` | `[<dossier>] [<compte>\|aucun]` | compte par projet |
| `raccourcis` (`shortcuts`) | `status\|on\|off [action…]\|set <action> <raccourci>` | raccourcis GNOME |
| `tui` | `--serveur NOM` | plein écran dans le terminal |
| `serveur ajouter` | `<cible> [--nom N]` | appairage avec un serveur CCS |
| `serveur liste` / `retirer <cible>` | — | serveurs appairés |
| `totp reinitialiser` | `<user>` | efface la double authentification (root) |
| `distant machines` | `--vite` | machines Ricochet, charge, outils |
| `distant lancer` | `--machine M`, `--outil O`, `--rapatrier CHEMIN`…, `--inclure CHEMIN`…, `--avec-git`, `--quand nuit\|HH:MM`, `--detache`, `--travail ID` (caché), `-- <commande>` | commande sur une autre machine |
| `distant travaux` | — | travaux en attente, en cours, finis |
| `distant arreter` / `journal` | `<id>` | arrêt ; sortie d'un travail détaché |
| `chat effacer` | — | `/clear` à la fin du tour (appelé par Claude dans un chat CCS) |
| `conversations` | `[mots…]`, `-p/--project`, `--vscode`\|`--terminal`, `-n/--limit N`, `--all`, `--json` | historique |
| `resume` | `<ref>`, `--vscode`\|`--new-terminal`\|`--print`, `--dir D` | reprend une conversation |
| `title` | `<ref> <titre…>` | renomme une conversation |
| `preview` (`apercu`) | `<ref>` | aperçu d'une conversation |
| `export` | `<ref> [fichier.md]` | export Markdown |
| `integrate` | `on\|off\|status` | ligne d'état et hook dans Claude Code |
| `analyze` | `--days N` | analyse des journaux locaux |
| `tache` (`taches`, `tasks`) | `[liste\|list\|ls]`, `ajouter\|add "<msg>" [-C dossier] [--modele m] [--droits lecture\|modifications\|tout] [--quand quota\|nuit\|HH:MM]`, `voir\|suivre\|show <id>`, `annuler\|cancel <id>`, `supprimer\|remove\|rm <id>`, `aide` | file de tâches |
| `budget` | `[<dossier> <montant>\|aucun]` | budget hebdomadaire par projet |
| `fiche` | `<identifiant>` | fiche « où j'en étais » |
| `sauvegarde` (`backup`) | `[fichier]` | sauvegarde chiffrée (gpg) |
| `restaurer` (`restore`) | `<fichier> [--oui]` | restauration |
| `telephone` (`phone`) | `[essai\|test]` | état ntfy, lien, message d'essai |
| `--version` | — | version |

*Internes* : `daemon` (service utilisateur `ccs-daemon`), `collect`, `notify <titre> [texte]`,
`statusline`, `hook stop-failure`, `tray`, `bridge [--socket S] [--local]`, `web-serve`,
`auth-serve`, `shell-distant <serveur> <cwd>` (les quatre derniers cachés de l'aide).

`--notifier` : `next`, `use`, `best`, `pause`, `silence` (notification bureau, bascule notée
« raccourci » dans le journal).

---

## 2. Pont JSON-RPC

Transport : un objet JSON par ligne (socket Unix du pont, ou WebSocket `/api/ws` relayé par
`ccs-web`, 8 Mio au plus par ligne, `ccs_app/server/rpc.py`).

- Requête `{"id", "method", "params"}` → `{"id", "result"}` ou
  `{"id", "error": {"code", "message"}}`.
- Codes d'erreur : `refuse`, `introuvable`, `invalide`, `trop_gros`, `interne`, `conflit`,
  `occupe`.
- Événement poussé par le serveur : `{"event", "data"}`.
- `hello {ticket, session_hash}` ouvre la connexion (inutile en mode `--local`). Sur
  `/api/ws`, `hello` et `machine.attach` sont refusés au client (ils sont faits par `ccs-web`).

### 2.1 Méthodes

| Méthode | Paramètres | Rôle |
|---|---|---|
| `accounts.state` | — | comptes, usage, compte actif |
| `accounts.refresh` | — | relève l'usage maintenant |
| `accounts.switch` | `name` | bascule de compte |
| `accounts.cards` | — | cartes de l'accueil (dont `running_chats`) |
| `pause.set` | `choice` | pause de la bascule automatique |
| `settings.get` | — | réglages fusionnés |
| `settings.set` | `path`, `value` | change un réglage (`path` pointé, ex. `chat.rights`) |
| `doctor.run` | — | bilan de santé |
| `phone.test` / `phone.new_topic` / `phone.qr` | — | essai ntfy, nouveau canal, QR du lien |
| `analysis.report` | `days` | analyse des journaux |
| `tasks.list` | — | file de tâches |
| `tasks.add` | `cwd`, `message`, `model`, `rights`, `when`, `roadmap {path,text,phase}` | ajoute une tâche |
| `tasks.cancel` / `tasks.remove` / `tasks.log` | `id` | annule, retire, journal d'une tâche |
| `projects.list` | `cwd`, `query` | projets connus |
| `projects.add` | `cwd` \| `parent`+`name`, `git` | ajoute (ou crée) un projet |
| `projects.remove` | `cwd` | retire de la liste |
| `projects.folders` | — | dépôts git du disque |
| `projects.account` | `cwd` | comptes et compte présélectionné |
| `conversation.messages` | `path`, `before`, `limit` | messages d'une conversation |
| `conversation.rename` | `session_id`, `path`, `title` | renomme |
| `conversation.cost` | `path` | coût |
| `conversation.trash` | `path`, `session_id`, `title`, `cwd` | corbeille (30 jours) |
| `conversation.trash_list` | — | contenu de la corbeille |
| `conversation.restore` | `tid` | restaure depuis la corbeille |
| `roadmap.read` | `cwd` | lit `ROADMAP.md` |
| `roadmap.toggle` | `path`, `line`, `text`, `done` | coche / décoche une tâche |
| `roadmap.task_prompt` | `path`, `text`, `phase` | message pour faire une tâche |
| `files.roots` | — | dossiers de départ |
| `files.list` | `root`, `rel`, `hide_ignored` | contenu d'un dossier |
| `files.read` / `files.image` / `files.info` | `path` | texte, image, ce qu'emporterait une suppression |
| `files.write` | `path`, `text`, `stamp` | écrit (refus si changé entre-temps) |
| `files.search` | `root`, `query` | recherche de fichiers |
| `files.download` | `path`, `offset` | téléchargement par morceaux |
| `files.upload` | `dir`, `name`, `data` (base64), `offset`, `last`, `replace` | envoi par morceaux |
| `files.mkdir` / `files.create` | `dir`, `name` | nouveau dossier, nouveau fichier |
| `files.rename` | `root`, `path`, `name` | renomme |
| `files.delete` | `root`, `path` | supprime |
| `files.paste` | `path`, `dir`, `mode` (`copy`\|`move`), `root` | copie ou déplace |
| `git.status` / `git.refs` / `git.fetch` / `git.pull` | `cwd` | état, branches et tags, réseau |
| `git.log` | `cwd`, `skip`, `limit` | historique |
| `git.show` | `cwd`, `id` | un commit et son diff |
| `git.diff` | `cwd`, `path`, `staged` | diff d'un fichier |
| `git.stage` / `git.unstage` | `cwd`, `paths` | indexe, désindexe |
| `git.hunk` | `cwd`, `path`, `action`, `index`, `header` | un bloc |
| `git.lines` | `cwd`, `path`, `action`, `lines`, `headers` | des lignes choisies |
| `git.commit` | `cwd`, `message`, `amend` | commit |
| `git.push` | `cwd`, `force` | push |
| `chat.open` | `cwd`, `session_id`, `options {model, effort, ultracode, rights}` | ouvre un chat (→ `chat_id`) |
| `chat.list` | — | chats ouverts |
| `chat.attach` | `chat_id`, `since` | s'abonne (événements depuis `seq`) |
| `chat.send` | `chat_id`, `text`, `images`, `uuid`, `shown`, `nonce` | envoie un message |
| `chat.answer` | `chat_id`, `request_id`, `decision`, `message` | répond à une autorisation |
| `chat.questions` | `chat_id`, `request_id`, `answers` | répond à des questions |
| `chat.interrupt` / `chat.close` / `chat.context` | `chat_id` | interrompt, ferme, usage du contexte |
| `chat.options` | `chat_id`, `options` | change modèle, effort, droits |
| `chat.render` | `markdown` | rend du Markdown en HTML |
| `chat.tags` | `session_id` | messages étiquetés |
| `chat.tag` | `session_id`, `msg_id`, `tags`, `text`, `role` | pose ou retire des étiquettes |
| `work.commands` / `work.files` / `work.changes` | `chat_id` | commandes `/`, fichiers, changements du chat |
| `work.saved.list` | `cwd`, `scope` | messages enregistrés |
| `work.saved.save` | `cwd`, `scope`, `name`, `text` | enregistre un message |
| `work.saved.delete` | `cwd`, `scope`, `name` | supprime |
| `work.shell.run` | `chat_id`, `command` | commande shell (→ `run_id`) |
| `work.shell.poll` / `work.shell.stop` | `run_id` | suit, arrête |
| `work.undo_file` | `chat_id`, `path`, `expected` | remet un fichier comme avant |
| `work.rewind_plan` / `work.rewind_apply` | `chat_id`, `message_id` (+ `expected`) | retour en arrière |
| `term.open` | `cwd`, `command`, `cols`, `rows`, `name` | ouvre un terminal (→ `term_id`) |
| `term.input` | `term_id`, `data` | frappe |
| `term.resize` | `term_id`, `cols`, `rows` | taille |
| `term.attach` / `term.close` | `term_id` | s'abonne, ferme |
| `term.list` | — | terminaux ouverts |
| `machines.list` | — | machines Ricochet : `id, name, online, local, cores, load, mem_used, mem_total, tunnel, tools, limit, running, waiting` |
| `machines.jobs` | — | travaux distants |
| `machines.start` | `command`, `cwd`, `machine`, `when` | lance un travail (→ `id`) |
| `machines.stop` | `id` | arrête un travail |
| `machines.log` | `id`, `tail` | journal d'un travail |
| `machines.settings` | — | `relais, jeton_defini, chemin, limite_defaut, limites` |
| `machines.configure` | `relais`, `jeton` | écrit `client.toml` |
| `machines.limit` | `machine`, `limite` | places par machine (`distant.toml`) |
| `machine.attach` | `machine` | *interne* : relaie la connexion vers le pont d'une autre machine |

### 2.2 Événements

| Événement | Données | Émetteur |
|---|---|---|
| `notice` | `text` | pont (installation de Claude Code) |
| `chat.event` | `chat_id, seq, ts, event {type, …}` | pont, chat suivi |
| `chat.tags` | `session_id, msg_id, entry` | pont, à tous |
| `term.output` / `term.exit` | `term_id, data` / `term_id, code` | pont |
| `work.shell` | sortie et fin d'une commande `work.shell.run` | pont |
| `machine.ready` | résultat de `machine.attach` | `ccs-web` (`?machine=`) |

Types de `chat.event.event.type` (`ccs_app/server/events.py`) : `Init`, `Hello`, `Status`,
`Compacting`, `LocalCommand`, `TextDelta`, `AssistantText`, `Thinking`, `ToolUse`,
`ToolResult`, `TaskNotice`, `Todos`, `PermissionRequest`, `ControlReply`, `TurnResult`,
`Compacted`, `ConversationReset`, `Retrying`, `Unknown` (`chat_protocol.py`) ;
`StateChanged`, `UserSent`, `TagsChanged`, `ContextUsage`, `OptionRefused`,
`UnhandledRequest`, `ProcessExited` (`chat_engine.py`) ; `PermissionSettled`, `Notice`.

---

## 3. Routes HTTP (`ccs-web`, `ccs_app/server/web.py`)

Écoute `127.0.0.1:8420` derrière nginx. Cookies `ccs_session` et `ccs_device` (HttpOnly,
Secure, SameSite=Strict) ; jeton d'appareil en `Authorization: Bearer` ; en mode Portier,
en-tête `X-Portier-Utilisateur` (venant de nginx en local seulement). Les POST vérifient `Origin`.

| Route | Corps / requête | Rôle |
|---|---|---|
| `GET /api/health` | — | vie du service, version |
| `POST /api/login` | `user, password, code, remember` | connexion (PAM + TOTP) |
| `POST /api/enroll` | `pending, code, remember` | première activation du TOTP |
| `POST /api/pair` | `user, password, code, name` | appairage d'un appareil (jeton) |
| `POST /api/logout` | — | déconnexion |
| `GET /api/session` | — | `user` (+ `portier`) |
| `GET /api/portier` | — | `actif, connexion` |
| `GET /api/tokens` | — | jetons d'appareil |
| `POST /api/revoke` | `token_id` | révoque un jeton |
| `POST /api/app-token` | `name` | jeton durable pour l'application Android |
| `GET /api/ws` | `?machine=ID` (facultatif) | WebSocket du pont (§ 2) |
| `GET /` et fichiers statiques | — | interface web (`ccs_app/web`) |

Codes de fermeture de la WebSocket : 4001 (session expirée ou révoquée), 1012 (pont perdu),
1011 (pont injoignable), 4010 (machine injoignable).

*Interne* : `ccs-auth` (`/run/ccs/auth.sock`, même protocole) : `login`, `enroll`, `pair`,
`check`, `check_app`, `logout`, `app_token`, `tokens`, `revoke`, `portier`.

---

## 4. Fichiers de configuration et d'état

`$STORE` = `${CCS_HOME:-~/.claude-accounts}` ; `$CLAUDE` = `${CLAUDE_CONFIG_DIR:-~/.claude}`.

### 4.1 Configuration (modifiable par l'utilisateur)

| Fichier | Clés |
|---|---|
| `$STORE/settings.json` | voir 4.2 |
| `$STORE/projects.json` | compte par dossier (`ccs projet`) |
| `$STORE/budgets.json` | budget hebdomadaire par dossier |
| `$STORE/serveurs.json` (0600) | liste de `{name, url, user, token}` |
| `~/.config/ccs/distant.toml` | `[machines.<id>]` : `utilisateur`, `port`, `limite` |
| `~/.config/ricochet/client.toml` (0600, partagé avec Ricochet) | `relais`, `jeton` |
| `/etc/ccs/web.json` (serveur) | `listen`, `origin`, `portier {actif, utilisateurs, url, deconnexion}` |

### 4.2 Clés de `settings.json` (`ccs_app/settings.py`)

| Section | Clés |
|---|---|
| `auto_switch` | `enabled`, `threshold`, `target_max_session`, `target_max_weekly` |
| `alerts` | `enabled`, `session_thresholds`, `eta_minutes`, `weekly_ahead_points`, `weekly_forecast`, `weekly_forecast_days`, `resets`, `auth`, `sessions`, `waiting_reminder`, `waiting_reminder_min`, `model_advice`, `model_advice_pct`, `weekly_report`, `weekly_report_day`, `weekly_report_hour`, `monthly_report`, `monthly_report_hour`, `quiet {enabled, start, end, days, allow_waiting}` |
| `poll` | `normal_s`, `fast_s` |
| `advisor` | `weeks`, `margin_pct`, `plan_prices`, `profile_plans`, `max_accounts` |
| `updates` | `enabled` |
| `warmup` | libre (par profil) |
| `orchestrator` | `enabled`, `active_hours {start, end, days}`, `stagger`, `expiring_switch`, `expiring_within_min`, `expiring_min_left`, `expiring_cooldown_min`, `reserve_points`, `max_weekly_start` |
| `tasks` | `enabled`, `night {start, end}`, `max_attempts` |
| `phone` | `enabled`, `server`, `topic`, `events {waiting, task, switch, exhausted}`, `show_content`, `reply_topic` |
| `archive` | `enabled`, `idle_days`, `max_age_days` |
| `sessions` | `idle_hours` |
| `context_alert` | `enabled`, `threshold_tokens`, `auto_compact` |
| `limit_resume` | `enabled`, `outside` (`notify` ou `resume`) |
| `budget` | `enabled`, `alert_pcts` |
| `chat` | `idle_suspend_min`, `rights` (`manual`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`), `auto_clear` |
| `files` | `layout` (`A`\|`B`), `show_ignored` |
| `git` | `layout` (`A`\|`B`\|`C`), `fetch_minutes`, `avatars` |
| `appearance` | `color_scheme` (`auto`\|`clair`\|`sombre`), `account_colors` |

### 4.3 État (écrit par CCS)

| Emplacement | Contenu |
|---|---|
| `$STORE/<profil>/oauth.json`, `account.json`, `usage.json` | jeton OAuth, compte, dernier usage |
| `$STORE/state.json`, `daemon.pid`, `history.db` | état du service, historique d'usage |
| `$STORE/pause.json`, `quiet.json`, `quiet_held.json` | pause, ne pas déranger, notifications retenues |
| `$STORE/switch-origin.json`, `updates.json`, `context-alerts.json` | origine de bascule, mises à jour, alertes de contexte |
| `$STORE/tasks.json`, `tasks/` | file de tâches et journaux |
| `$STORE/terminals.json`, `messages.json`, `conversations-cache.json`, `conversations-moves.json` | terminaux, messages enregistrés, caches |
| `$STORE/etiquettes/`, `limits/`, `avatars/` | étiquettes, limites atteintes (`outcome`, `cwd`, `resume_at`, `lifted_at`), avatars |
| `$STORE/.lock`, `.tasks.lock`, `.pause.lock`, … | verrous |
| `<projet>/.ccs/messages.json` | messages enregistrés du projet |
| `${XDG_DATA_HOME:-~/.local/share}/ccs/` | `projects.json`, `archive/` (+ `index.json`), `trash/` |
| `~/.cache/ccs/` | `distant.json` (inventaire), `distant/travaux/<id>.json` et `.log`, `icons-*` |
| `${XDG_CACHE_HOME:-~/.cache}/ccs/effacer/` | demandes `ccs chat effacer` |
| `~/.cache/ccs-distant/` (machine distante) | copies des projets |
| `${XDG_RUNTIME_DIR:-/tmp/ccs-UID}/ccs/bridge.sock` | pont local du bureau |
| `/run/ccs/auth.sock`, `/run/ccs/bridge/<user>/{bridge.sock,key}` | serveur |
| `/var/lib/ccs/{sessions.json, keys/<user>, totp/<user>}` | serveur |
| Claude Code : `$CLAUDE/.credentials.json`, `~/.claude.json`, `$CLAUDE/settings.json`, `projects/`, `sessions/`, `file-history/` | lus ; écrits pour la bascule, l'intégration et les titres |

---

## 5. Variables d'environnement

| Variable | Rôle |
|---|---|
| `CCS_HOME` | dossier des profils (`~/.claude-accounts`) |
| `CLAUDE_CONFIG_DIR` | dossier de Claude Code (comme Claude Code) |
| `CCS_VIA` | origine d'une bascule pour le journal (`bin/ccs`) |
| `CCS_BIN` | chemin de `claude-accounts` à relancer |
| `CCS_CHAT_JETON` | jeton du chat, posé par CCS pour `ccs chat effacer` |
| `CCS_SERVER_ROOT` | racine des chemins du serveur (tests) |
| `CCS_APP_ID` | identifiant d'application distinct (essais) |
| `CCS_NO_VTE` | force le terminal externe (essais) |
| `CCS_PATH`, `CCS_OUTIL` | posées sur la machine distante par `distant lancer` |
| `HOME`, `PATH`, `SHELL`, `TZ`, `USER`, `PYTHONPATH`, `GNUPGHOME`, `NO_COLOR`, `GIT_SSH`, `GIT_SSH_COMMAND` | usage habituel |
| `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_RUNTIME_DIR`, `XDG_CURRENT_DESKTOP` | dossiers et bureau |
| `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING` | posée pour les chats |

---

## 6. Points à revoir avant le gel

### Commandes

- Deux interfaces en couches : `bin/ccs` (Bash) redéclare les alias de `cli.py`, mais pas les
  mêmes. `conv`/`historique`, `reprendre`, `titre`, `aperçu`, `exporter`, `integration`,
  `stats`, `bilan`, `orchestrateur`, `planning`, `ps`, `server` n'existent que dans `ccs` ;
  `apercu`, `conseil`, `maj` existent des deux côtés (`bin/ccs:447-493`, `ccs_app/cli.py:1159-1352`).
- `ccs best` force `--switch` alors que `claude-accounts best` n'affiche que le meilleur
  compte : même nom, deux comportements (`bin/ccs:457`).
- `ccs gui` perd ses arguments : `--page`, `--session`, `--task` et `--new-session` ne sont
  pas transmis (`bin/ccs:456`).
- `ccs integrate` ne transmet que son 1ᵉʳ argument (`bin/ccs:491`).
- `ccs <nom>` bascule sur un profil : un profil nommé comme une commande (`plan`, `budget`…)
  devient inaccessible par ce raccourci (`bin/ccs:496`).
- Noms de commandes mêlant anglais et français : `status`, `best`, `print`, `resume`,
  `title`, `preview`, `export`, `analyze`, `integrate`, `orch`, `sessions` d'un côté ;
  `formule`, `semaine`, `mois`, `journal`, `projet`, `tache`, `sauvegarde`, `distant`,
  `serveur` de l'autre (`ccs_app/cli.py:1177-1350`).
- Options incohérentes :
  - `analyze --days` contre `journal --jours` (`cli.py:1350` / `cli.py:1274`) ;
  - `semaine --precedente` contre `mois --precedent` (`cli.py:1223` /
    `monthly_report.py:420`) ;
  - `conversations` en anglais (`--project`, `--limit`, `--all`) ;
  - `resume --new-terminal --print --dir` à côté de `tui --serveur`
    (`cli.py:1311-1326`, `cli.py:1186`).
- Arguments d'état mélangés : `pause … status` et `silence … reprendre|status`
  (`cli.py:1211`, `1235`) ; `raccourcis status|on|off|set` (`cli.py:1283`) ;
  `telephone essai|test` (`cli.py:120`).
- Sous-commandes de `tache` doublées en français et en anglais : `liste|list|ls`,
  `ajouter|add`, `voir|suivre|show`, `annuler|cancel`, `supprimer|remove|rm` (`tasks.py:602-626`).
- La liste des commandes déléguées est écrite deux fois : `DELEGATED` (`cli.py:1355`) et la
  boucle de `build_parser` (`cli.py:1299-1309`).
- Compatibilité avec l'ancienne option `--print` (`cli.py:1365-1367`), à retirer ou à
  documenter.
- Option cachée `distant lancer --travail` (`cli.py:1260`) et commandes cachées `bridge`,
  `web-serve`, `auth-serve`, `shell-distant` (`cli.py:1179-1199`) : à déclarer internes,
  hors du gel.
- `notify`, `statusline`, `hook`, `tray`, `collect`, `daemon` restent visibles dans l'aide de
  `claude-accounts` alors qu'ils sont internes (`cli.py:1178`, `1206`, `1286`, `1341-1348`).
- Deux vocabulaires de droits : `tache --droits lecture|modifications|tout` (`tasks.py:33`)
  contre `chat.rights` `manual|acceptEdits|…` (`launch_options.py:31-40`). Le paramètre
  `rights` de `tasks.add` et celui de `chat.open` n'acceptent pas les mêmes valeurs.

### Pont JSON-RPC

- Singulier et pluriel mêlés :
  - `machine.attach` à côté de `machines.*` (`bridge_machines.py:121`) ;
  - `conversation.*` à côté de `projects.*`, `tasks.*` et `files.*` (`bridge_data.py`).
- Profondeur et séparateurs variables :
  - `work.saved.list` et `work.shell.run` ont trois niveaux, tout le reste en a deux ;
  - `trash_list`, `task_prompt`, `new_topic`, `undo_file` et `rewind_plan` utilisent `_`.
- Langue des paramètres et des réponses :
  - `machines.limit {machine, limite}` et `machines.configure {relais, jeton}` sont en
    français, alors que `machines.start {command, cwd, machine, when}` est en anglais
    (`bridge_machines.py:156-210`) ;
  - `machines.settings` renvoie `relais, jeton_defini, chemin, limite_defaut, limites`
    (`distant.py:759`), mais `machines.list` renvoie `limit, running, waiting`
    (`distant.py:676`) : `limit` et `limite` désignent la même chose.
- États des travaux distants en français (`attente`, `programmé`, `envoi`, `en cours`, `fini`,
  `échec`, `arrêté`, `distant_jobs.py:29-32`) contre états des tâches en anglais (`queued`,
  `running`, `waiting`, `done`…, `tasks.py:38`). L'interface web traduit les uns vers les
  autres (`web/pages-machines.js:13`).
- Identifiants nommés au cas par cas : `chat_id`, `term_id`, `run_id`, `request_id`, `msg_id`
  à côté de `id` (`tasks.*`, `machines.*`, `git.show`) et `tid` (`conversation.restore`,
  `bridge_data.py:179`).
- L'événement `machine.ready` est émis par `ccs-web` et non par le pont
  (`server/web.py:277`) : un client du socket ne le reçoit jamais.
- `machines.running` et `machines.tools` (retirés en 0.32.0) : il ne reste aucune trace dans
  le code. Seul l'ancien dossier `~/.cache/ccs/distant-en-cours/` n'est jamais nettoyé
  (CHANGELOG 0.32.0).
- Aucune méthode du pont n'est morte : toutes sont appelées par le web, le bureau ou Android.
  En revanche, les méthodes ne portent pas de numéro de version (`hello` ne renvoie que
  `user`, `bridge.py:91`) : à ajouter avant le gel pour que les clients puissent s'adapter.

### HTTP

- `/api/app-token` utilise un tiret ; les autres routes sont des mots simples (`server/web.py:370`).
- `/api/portier` répond en français (`actif`, `connexion`, `web.py:193`), les autres routes
  en anglais (`user`, `status`, `token`).

### Fichiers et variables

- Configuration dispersée sous trois racines :
  - `~/.claude-accounts/` (nom historique, `core.py:75`) ;
  - `~/.config/ccs/distant.toml` (`distant.py:101`) ;
  - `~/.local/share/ccs/` (`project_list.py:23`).
  Et deux fichiers `projects.json` de sens différent (`project_accounts.py:40` /
  `project_list.py:24`).
- XDG appliqué à moitié :
  - `XDG_CACHE_HOME` est respecté pour `effacer/` (`chat_engine.py:56`), mais pas pour
    `~/.cache/ccs` (`distant.py:105`, `distant_jobs.py:39`, `tray.py:328`) ;
  - `XDG_CONFIG_HOME` est ignoré (`distant.py:93`) ;
  - `chat_engine.py:56` lit `Path.home()` au lieu de `core.paths().home`.
- Noms de fichiers mêlés :
  - français : `serveurs.json`, `etiquettes/`, `raccourcis.json` ;
  - anglais : `budgets.json`, `limits/`, `pause.json` ;
  - `quiet_held.json` avec `_`, `switch-origin.json` et `context-alerts.json` avec `-`.
- `settings.json` :
  - clés anglaises mais valeurs françaises pour `appearance.color_scheme` (`clair|sombre`,
    `settings.py:166`) ;
  - la section `warmup` est libre, sans schéma (`settings.py:67`) ;
  - le commentaire « phase 11/12/13 » se trouve dans les défauts.
- `/etc/ccs/web.json` mêle `listen`/`origin` (anglais) et `portier.actif`/`utilisateurs`/
  `deconnexion` (français) (`server/web.py:21`, `portier.py:24`).
- Variables d'environnement : `CCS_CHAT_JETON`, `CCS_OUTIL` (français) à côté de
  `CCS_NO_VTE`, `CCS_APP_ID`, `CCS_HOME` (anglais) (`chat_engine.py:42`, `distant.py:251`).
- Compatibilités anciennes à trancher :
  - `LEGACY_KINDS`, ancien format de l'API d'usage (`core.py:38`, externe, à garder) ;
  - état sans `fetched_at` (`cli.py:507`).
