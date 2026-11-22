# Interfaces publiques de CCS (inventaire avant la 1.0.0)

Ce qui sera gelé en 1.0.0 : à partir de là, le casser demandera une version majeure (SemVer).
Inventaire dressé d'après le code de la 0.32.0 (branche `develop`). Les éléments marqués
*interne* servent entre les composants de CCS (services systemd, pont, hooks) : ils sont
listés pour mémoire, mais n'ont pas à être gelés.

Sommaire : 1. Commandes · 2. Pont JSON-RPC · 3. Routes HTTP · 4. Fichiers · 5. Variables
d'environnement · 6. Points à revoir avant le gel.

---

## 1. Commandes

Règle (phase 33) : ce que Charles tape est en français. Les anciens noms (commandes, options,
valeurs) restent acceptés pendant toute la 1.x, mais n'apparaissent plus dans l'aide ; ils sont
notés ci-dessous entre parenthèses, après « anciens : ».

Deux points d'entrée, une seule table des noms :

- `ccs` (`bin/ccs`, Bash) : bascule entre profils elle-même (table `own_command`), et passe
  tout le reste, tel quel et avec tous ses arguments, à `claude-accounts`.
- `claude-accounts` (`bin/claude-accounts` → `ccs_app/cli.py`, argparse) : toutes les autres
  commandes et leurs anciens noms (`build_parser`, seule table). Sans sous-commande, il ouvre
  l'application graphique (`appli`). Une commande inconnue donne « commande ou profil inconnu »
  (code 1).

`ccs <nom>` bascule sur le profil `<nom>`, sauf si `<nom>` est aussi une commande (nouveau ou
ancien nom) : la commande l'emporte, et le profil se joint par `ccs utiliser <nom>`.
`ccs enregistrer`, `ccs ajouter` et `ccs renommer` préviennent (sur la sortie d'erreur) quand le
nom choisi est masqué ainsi.

### 1.1 Commandes propres à `ccs` (Bash)

| Commande (anciens noms) | Arguments, options | Rôle |
|---|---|---|
| `ccs` / `liste` (`list`, `ls`) | — | liste les profils (● = actif) |
| `ccs <nom>` | `[--notifier]` | bascule sur le profil `<nom>` (raccourci de `utiliser`) |
| `utiliser` (`use`, `switch`, `sw`) | `<nom> [--notifier]` | bascule sur un profil |
| `suivant` (`next`, `n`) | `[--notifier]` | profil suivant utilisable |
| `enregistrer` (`save`) | `<nom>` | enregistre le compte connecté |
| `ajouter` (`add`, `login`) | `<nom> [--email A] [--console] [--sso]` | `claude auth login` puis enregistrement |
| `actuel` (`current`, `whoami`) | — | profil actif |
| `supprimer` (`rm`, `remove`, `delete`) | `<nom>` | supprime un profil |
| `renommer` (`rename`, `mv`) | `<a> <b>` | renomme un profil |
| `appli` (`gui`, `app`) | tous les arguments de `claude-accounts appli` | application graphique, détachée du terminal |
| `version` (`--version`, `-v`) | — | version |
| `aide` (`help`, `-h`, `--help`) | — | aide |

Tout le reste (y compris les anciens noms) est passé tel quel à `claude-accounts`.

### 1.2 Sous-commandes de `claude-accounts`

| Commande (anciens noms) | Arguments, options (anciens) | Rôle |
|---|---|---|
| `appli` (défaut ; `gui`, `app`) | `--session PID:ID`, `--page ONGLET`, `--tache ID` (`--task`), `--nouvelle-session` (`--new-session`) | application graphique |
| `usage` (`print`, `u` ; option `--print`) | — | usage de tous les comptes |
| `etat` (`état`, `status`, `st`) | — | compte actif, meilleur compte, capacité |
| `meilleur` (`best`, `b`) | `--voir`, `--notifier` (`--switch`, `--basculer` : sans effet) | bascule sur le meilleur compte ; `--voir` l'affiche seulement. Même comportement par `ccs` et `claude-accounts` |
| `auto` | `on\|off` | bascule automatique |
| `orchestrateur` (`orch`) | `on\|off` | orchestrateur |
| `pause` | `[1h\|4h\|demain\|manuel\|off\|etat]` (`status`), `--notifier` | suspend bascule et orchestrateur |
| `silence` (`quiet`) | `[1h\|4h\|demain\|off\|reprendre\|etat]` (`status`), `--notifier` | ne pas déranger |
| `bilan` (`doctor`) | — | bilan de santé (code 1 au moindre problème) |
| `formule` (`conseil`) | — | formule conseillée |
| `semaine` | `--precedente N` (`--precedent`) | bilan hebdomadaire |
| `mois` | `--precedent N` (`--precedente` accepté) | rapport mensuel |
| `moment` | `--duree 3h`, `--sur 24h` | meilleur moment pour une grosse tâche |
| `mise-a-jour` (`maj`) | `--verifier` | installe la dernière version |
| `journal` | `--jours N` (`--days`) \| `--tout` | journal des bascules |
| `plan` (`planning`) | — | planning des fenêtres de 5 h |
| `sessions` (`ps`) | — | sessions Claude Code ouvertes |
| `projet` | `[<dossier>] [<compte>\|aucun]` | compte par projet |
| `raccourcis` (`shortcuts`) | `etat` (`status`) \| `on\|off [action…]` \| `definir <action> <raccourci>` (`set`) | raccourcis GNOME |
| `tui` | `--serveur NOM` | plein écran dans le terminal |
| `serveur ajouter` (`server`) | `<cible> [--nom N]` | appairage avec un serveur CCS |
| `serveur liste` / `retirer <cible>` | — | serveurs appairés |
| `totp reinitialiser` | `<user>` | efface la double authentification (root) |
| `distant machines` | `--vite` | machines Ricochet, charge, outils |
| `distant lancer` | `--machine M`, `--outil O`, `--rapatrier CHEMIN`…, `--inclure CHEMIN`…, `--avec-git`, `--quand nuit\|HH:MM`, `--detache`, `-- <commande>` | commande sur une autre machine |
| `distant travaux` | — | travaux en attente, en cours, finis |
| `distant arreter` / `journal` | `<id>` | arrêt ; sortie d'un travail détaché |
| `chat effacer` | — | `/clear` à la fin du tour (appelé par Claude dans un chat CCS) |
| `conversations` (`conv`, `historique`) | `[mots…]`, `-p/--projet` (`--project`), `--vscode`\|`--terminal`, `-n/--limite N` (`--limit`), `--tous` (`--all`), `--json` | historique |
| `reprendre` (`resume`) | `<ref>`, `--vscode`\|`--nouveau-terminal` (`--new-terminal`)\|`--afficher` (`--print`), `--dossier D` (`--dir`) | reprend une conversation |
| `titre` (`title`) | `<ref> <titre…>` | renomme une conversation |
| `apercu` (`aperçu`, `preview`) | `<ref>` | aperçu d'une conversation |
| `exporter` (`export`) | `<ref> [fichier.md]` | export Markdown |
| `integration` (`integrate`) | `[on\|off\|etat]` (`status`), tous les arguments transmis | ligne d'état et hook dans Claude Code |
| `analyse` (`analyze`, `stats`) | `--jours N` (`--days`) | analyse des journaux locaux |
| `tache` (`taches`, `tasks`) | `[liste]`, `ajouter "<msg>" [-C dossier] [--modele m] [--droits D] [--quand quota\|nuit\|HH:MM]`, `voir <id>`, `annuler <id>`, `supprimer <id>`, `aide` ; anciens : `list`, `ls`, `add`, `suivre`, `show`, `cancel`, `remove`, `rm` | file de tâches |
| `budget` | `[<dossier> <montant>\|aucun]` | budget hebdomadaire par projet |
| `fiche` | `<identifiant>` | fiche « où j'en étais » |
| `sauvegarde` (`backup`) | `[fichier]` | sauvegarde chiffrée (gpg) |
| `restaurer` (`restore`) | `<fichier> [--oui]` | restauration |
| `telephone` (`phone`) | `[essai]` (`test`) | état ntfy, lien, message d'essai |
| `--version` | — | version |

*Internes*, acceptées mais absentes de l'aide et hors du gel : `daemon` (service `ccs-daemon`),
`collect`, `notify <titre> [texte]`, `statusline`, `hook stop-failure`, `tray`,
`bridge [--socket S] [--local]`, `web-serve`, `auth-serve`, `shell-distant <serveur> <cwd>`,
`est-commande <nom>` (pour `bin/ccs`), et l'option `distant lancer --travail ID`.

`--notifier` : `suivant`, `utiliser`, `meilleur`, `pause`, `silence` (notification bureau,
bascule notée « raccourci » dans le journal).

### 1.3 Droits (un seul vocabulaire)

`tache --droits` et le réglage `chat.rights` (ainsi que le paramètre `rights` de `tasks.add` et
de `chat.open`) acceptent les mêmes valeurs : les mots `lecture`, `modifications`, `tout`, ou un
mode de Claude Code (`manual`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions`),
sans tenir compte de la casse. `launch_options.convert_rights` est la seule table de passage :
`lecture` ↔ `plan` (et `manual`, `dontAsk` → `lecture` pour une tâche sans personne pour
répondre), `modifications` ↔ `acceptEdits` (et `auto`), `tout` ↔ `bypassPermissions`.
Une tâche garde le mot, un chat garde le mode.

---

## 2. Pont JSON-RPC

Transport : un objet JSON par ligne (socket Unix du pont, ou WebSocket `/api/ws` relayé par
`ccs-web`, 8 Mio au plus par ligne, `ccs_app/server/rpc.py`).

- Requête `{"id", "method", "params"}` → `{"id", "result"}` ou
  `{"id", "error": {"code", "message"}}`.
- Codes d'erreur : `refuse`, `introuvable`, `invalide`, `trop_gros`, `interne`, `conflit`,
  `occupe`.
- Événement poussé par le serveur : `{"event", "data"}`.
- `hello {ticket, session_hash, protocol}` ouvre la connexion (inutile en mode `--local`) et
  renvoie `{user, protocol, version}` : `protocol` est la version du protocole du pont (**1**
  depuis la 1.0.0), `version` celle de CCS. Le client déclare la sienne dans `protocol` (sur
  `/api/ws` : `?protocol=1`) ; sans elle, c'est un ancien client (voir § 2.3). Sur `/api/ws`,
  `hello` et `machines.attach` sont refusés au client (ils sont faits par `ccs-web`).
- Pont local (`ccs bridge --local`) : c'est lui qui tient les chats de l'application de bureau
  (le web et les autres appareils les voient par `machines.attach`). Il se relance seul sur le
  nouveau code quand la version de CCS installée change et qu'aucun travail ne tourne (ses chats
  sont fermés, les appareils les rouvrent sur la même conversation) ; un pont plus ancien que le
  client et sans chat au travail est arrêté par le client, qui en lance un neuf.

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
| `phone.test` / `phone.renew` / `phone.qr` | — | essai ntfy, nouveau canal, QR du lien |
| `analysis.report` | `days` | analyse des journaux |
| `tasks.list` | — | file de tâches |
| `tasks.add` | `cwd`, `message`, `model`, `rights`, `when`, `roadmap {path,text,phase}` | ajoute une tâche |
| `tasks.cancel` / `tasks.remove` / `tasks.log` | `id` | annule, retire, journal d'une tâche |
| `projects.list` | `cwd`, `query` | projets connus |
| `projects.add` | `cwd` \| `parent`+`name`, `git` | ajoute (ou crée) un projet |
| `projects.remove` | `cwd` | retire de la liste |
| `projects.folders` | — | dépôts git du disque |
| `projects.account` | `cwd` | comptes et compte présélectionné |
| `conversations.messages` | `path`, `before`, `limit` | messages d'une conversation ; `role` : `user`, `assistant`, `tool`, `note` |
| `conversations.rename` | `session_id`, `path`, `title` | renomme |
| `conversations.cost` | `path` | coût |
| `conversations.trash` | `path`, `session_id`, `title`, `cwd` | corbeille (30 jours) (→ `trash_id`) |
| `trash.list` | — | contenu de la corbeille : `items [{trash_id, session_id, cwd, title, trashed_at}]`, `days` |
| `trash.restore` | `trash_id` | restaure depuis la corbeille |
| `roadmap.read` | `cwd` | lit `ROADMAP.md` |
| `roadmap.toggle` | `path`, `line`, `text`, `done` | coche / décoche une tâche |
| `roadmap.prompt` | `path`, `text`, `phase` | message pour faire une tâche |
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
| `chat.list` | — | chats ouverts (`chat_id`, `cwd`, `state`, `seq`, `session_id`, `path`, `title`, `pid`, `devices`…) |
| `chat.attach` | `chat_id`, `since` | s'abonne (événements depuis `seq`) |
| `chat.send` | `chat_id`, `text`, `images`, `uuid`, `shown`, `nonce` | envoie un message |
| `chat.answer` | `chat_id`, `request_id`, `decision`, `message` | répond à une autorisation |
| `chat.questions` | `chat_id`, `request_id`, `answers` | répond à des questions |
| `chat.interrupt` / `chat.context` | `chat_id` | interrompt, usage du contexte |
| `chat.close` | `chat_id`, `keep_if_shared` | ferme (→ `closed`) ; avec `keep_if_shared`, détache seulement l'appareil si un autre suit le chat (→ `closed: false`, `devices`) |
| `chat.options` | `chat_id`, `options` | change modèle, effort, droits |
| `chat.render` | `markdown` | rend du Markdown en HTML |
| `chat.tags` | `session_id` | messages étiquetés ; `role` de chaque entrée : `user`, `assistant` ou `""` |
| `chat.tag` | `session_id`, `msg_id`, `tags`, `text`, `role` (`user` ou `assistant` ; l'ancien `utilisateur` est accepté) | pose ou retire des étiquettes |
| `work.commands` / `work.files` / `work.changes` | `chat_id` | commandes `/`, fichiers, changements du chat |
| `saved.list` | `cwd`, `scope` | messages enregistrés |
| `saved.save` | `cwd`, `scope`, `name`, `text` | enregistre un message |
| `saved.delete` | `cwd`, `scope`, `name` | supprime |
| `shell.run` | `chat_id`, `command` | commande shell (→ `run_id`) |
| `shell.poll` / `shell.stop` | `run_id` | suit, arrête |
| `work.undo` | `chat_id`, `path`, `expected` | remet un fichier comme avant |
| `rewind.plan` / `rewind.apply` | `chat_id`, `message_id` (+ `expected`) | retour en arrière |
| `term.open` | `cwd`, `command`, `cols`, `rows`, `name` | ouvre un terminal (→ `term_id`) |
| `term.input` | `term_id`, `data` | frappe |
| `term.resize` | `term_id`, `cols`, `rows` | taille |
| `term.attach` / `term.close` | `term_id` | s'abonne, ferme |
| `term.list` | — | terminaux ouverts |
| `machines.list` | — | machines Ricochet : `id, name, online, local, cores, load, mem_used, mem_total, tunnel, tools, limit, running, waiting` |
| `machines.jobs` | — | travaux distants ; `state` : `waiting`, `scheduled`, `sending`, `running`, `done`, `failed`, `stopped` |
| `machines.start` | `command`, `cwd`, `machine`, `when` | lance un travail (→ `id`) |
| `machines.stop` | `id` | arrête un travail |
| `machines.log` | `id`, `tail` | journal d'un travail |
| `machines.settings` | — | `relay, token_set, path, default_limit, limits` |
| `machines.configure` | `relay`, `token` | écrit `client.toml` |
| `machines.limit` | `machine`, `limit` | places par machine (`distant.toml`) |
| `machines.attach` | `machine` | *interne* : relaie la connexion vers le pont d'une autre machine (pousse `machines.ready`) |

### 2.2 Événements

| Événement | Données | Émetteur |
|---|---|---|
| `notice` | `text` | pont (installation de Claude Code) |
| `chat.event` | `chat_id, seq, ts, event {type, …}` | pont, chat suivi |
| `chat.tags` | `session_id, msg_id, entry` | pont, à tous |
| `term.output` / `term.exit` | `term_id, data` / `term_id, code` | pont |
| `shell.done` | sortie et fin d'une commande `shell.run` | pont |
| `machines.ready` | `machine, name` : résultat de `machines.attach` | pont (avant la réponse) |

Types de `chat.event.event.type` (`ccs_app/server/events.py`) : `Init`, `Hello`, `Status`,
`Compacting`, `LocalCommand`, `TextDelta`, `AssistantText`, `Thinking`, `ToolUse`,
`ToolResult`, `TaskNotice`, `Todos`, `PermissionRequest`, `ControlReply`, `TurnResult`,
`Compacted`, `ConversationReset`, `Retrying`, `Unknown` (`chat_protocol.py`) ;
`StateChanged`, `UserSent`, `TagsChanged`, `ContextUsage`, `OptionRefused`,
`UnhandledRequest`, `ProcessExited`, `CacheExpired` (`chat_engine.py`) ; `PermissionSettled`, `Notice`.

Depuis la 0.37.0 : `TurnResult.usage` = `{input, cache_read, cache_write, output, cost_usd,
context, cache_ttl_s, model}` (`token_use.turn_usage`, `{}` sans usage) ; `CacheExpired` =
`{context, ttl_s, rewrite_usd, text}` ; `analysis.report` renvoie aussi `top` (gros
consommateurs : `title, project, file, share, answers, avg_context, rewrite_share, causes`).

### 2.3 Compatibilité (toute la 1.x, `ccs_app/server/protocol.py`)

Le pont accepte encore les anciens noms, ramenés aux nouveaux avant tout traitement :

| Ancien nom (accepté) | Nouveau nom |
|---|---|
| `machine.attach` | `machines.attach` |
| `conversation.messages` / `.rename` / `.cost` / `.trash` | `conversations.messages` / `.rename` / `.cost` / `.trash` |
| `conversation.trash_list` | `trash.list` |
| `conversation.restore {tid}` | `trash.restore {trash_id}` |
| `roadmap.task_prompt` | `roadmap.prompt` |
| `phone.new_topic` | `phone.renew` |
| `work.saved.list` / `.save` / `.delete` | `saved.list` / `.save` / `.delete` |
| `work.shell.run` / `.poll` / `.stop` | `shell.run` / `.poll` / `.stop` |
| `work.undo_file` | `work.undo` |
| `work.rewind_plan` / `work.rewind_apply` | `rewind.plan` / `rewind.apply` |
| `machines.limit {limite}` | `machines.limit {limit}` |
| `machines.configure {relais, jeton}` | `machines.configure {relay, token}` |

Un **ancien client** (aucun `protocol` déclaré) reçoit en plus les anciennes valeurs là où elles
ont changé : événements `machine.ready` et `work.shell`, états des travaux en français dans
`machines.jobs` (`attente`, `programmé`, `envoi`, `en cours`, `fini`, `échec`, `arrêté`), rôles
`utilisateur` et `outil` dans `conversations.messages`, `utilisateur` dans `chat.tags`, `chat.tag`
et l'événement `chat.tags` (`downgrade_result`, `event_data`). Les
réponses gardent aussi les anciennes clés à côté des nouvelles : `tid` (et `id` dans
`trash.list`), et `relais, jeton_defini, chemin, limite_defaut, limites` dans
`machines.settings`. Les travaux enregistrés sur disque avec un état français sont lus avec
l'état anglais. Vers le pont d'une autre machine plus ancien (son `hello` ne renvoie pas
`protocol`), `machines.attach` relaie avec les anciens noms et l'ancien rôle `utilisateur` de
`chat.tag`, et ramène ses réponses et événements aux nouvelles valeurs (rôles des messages et des
étiquettes). Tout cela sera retiré en 2.0.

Valeurs d'état relues sous leur nouveau nom (fichiers et historique écrits avant la 1.0.0) :

| Où | Ancienne valeur (lue) | Nouvelle valeur |
|---|---|---|
| `$STORE/labels/<session>.json`, `role` | `utilisateur` | `user` |
| `history.db`, `detail.mode` des bascules (`switch`, `error`) | `anticipee`, `blocage` | `early`, `blocked` |
| `history.db`, `detail.mode` des démarrages de fenêtre (`warmup`) | `creneau`, `orchestrateur` | `slot`, `orchestrator` |
| `$CACHE/ccs/machines.json` (inventaire, cache) | `outils`, `quand` | `tools`, `checked_at` (entrée ancienne : périmée, relevée à nouveau) |

Les genres du journal des bascules (`switch_log.KINDS`, en mémoire seulement, lus par le bureau)
sont `auto`, `early`, `blocked`, `manual`, `initial`, `failed`, `limit`, `window`.

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
| `GET /api/portier` | — | `enabled, login` (+ `actif, connexion`, anciennes clés gardées en 1.x) |
| `GET /api/tokens` | — | jetons d'appareil |
| `POST /api/revoke` | `token_id` | révoque un jeton |
| `POST /api/apptoken` | `name` | jeton durable pour les applications mobiles (ancienne route `/api/app-token` acceptée en 1.x) |
| `GET /api/ws` | `?protocol=1`, `?machine=ID` (facultatifs) | WebSocket du pont (§ 2) |
| `GET /` et fichiers statiques | — | interface web (`ccs_app/web`) |

Codes de fermeture de la WebSocket : 4001 (session expirée ou révoquée), 1012 (pont perdu),
1011 (pont injoignable), 4010 (machine injoignable). Avec `?machine=`, l'événement
`machines.ready` (`machine.ready` pour un client sans `?protocol=`) arrive avant tout autre.

*Interne* : `ccs-auth` (`/run/ccs/auth.sock`, même protocole) : `login`, `enroll`, `pair`,
`check`, `check_app`, `logout`, `app_token`, `tokens`, `revoke`, `portier`.

---

## 4. Fichiers de configuration et d'état

`$STORE` = `${CCS_HOME:-~/.claude-accounts}` ; `$CLAUDE` = `${CLAUDE_CONFIG_DIR:-~/.claude}` ;
`$CONFIG`, `$CACHE`, `$DATA` = `${XDG_CONFIG_HOME:-~/.config}`, `${XDG_CACHE_HOME:-~/.cache}`,
`${XDG_DATA_HOME:-~/.local/share}` (variable prise si c'est un chemin absolu ; calcul unique :
`core.xdg_home`, `core.ccs_dir`).

Noms en anglais, mots séparés par `-`. **Compatibilité 1.x** (`ccs_app/migrate.py`, à retirer
en 2.0) : un fichier renommé l'est tout seul au premier usage, si le nouveau nom n'existe pas
encore (sinon le nouveau est gardé et l'ancien laissé tel quel) ; les anciennes clés et valeurs
sont lues et converties. Anciens noms : `projects.json` → `project-accounts.json`,
`quiet_held.json` → `quiet-held.json`, `etiquettes/` → `labels/`, `~/.config/ccs/distant.toml`
→ `$CONFIG/ccs/machines.toml`, `~/.cache/ccs/distant.json` → `$CACHE/ccs/machines.json`,
`~/.cache/ccs/distant/travaux/` → `$CACHE/ccs/machines/jobs/`, `~/.cache/ccs/effacer/` →
`$CACHE/ccs/clear/`.

### 4.1 Configuration (modifiable par l'utilisateur)

| Fichier | Clés |
|---|---|
| `$STORE/settings.json` | voir 4.2 |
| `$STORE/project-accounts.json` | compte par dossier (`ccs projet`) |
| `$STORE/budgets.json` | budget hebdomadaire par dossier |
| `$STORE/serveurs.json` (0600) | liste de `{name, url, user, token}` ; deviendra `servers.json` (voir § 6) |
| `$CONFIG/ccs/machines.toml` | `[machines.<id>]` : `user`, `port`, `limit` (anciennes clés `utilisateur`, `limite` lues) |
| `$CONFIG/ricochet/client.toml` (0600, partagé avec Ricochet) | `relais`, `jeton` (clés de Ricochet, gardées) |
| `/etc/ccs/web.json` (serveur) | `listen`, `origin`, `portier {enabled, users, url, logout}` (anciennes clés `actif`, `utilisateurs`, `deconnexion` lues) |

### 4.2 Clés de `settings.json` (`ccs_app/settings.py`)

| Section | Clés |
|---|---|
| `auto_switch` | `enabled`, `threshold`, `target_max_session`, `target_max_weekly` |
| `alerts` | `enabled`, `session_thresholds`, `eta_minutes`, `weekly_ahead_points`, `weekly_forecast`, `weekly_forecast_days`, `resets`, `auth`, `sessions`, `waiting_reminder`, `waiting_reminder_min`, `model_advice`, `model_advice_pct`, `weekly_report`, `weekly_report_day`, `weekly_report_hour`, `monthly_report`, `monthly_report_hour`, `quiet {enabled, start, end, days, allow_waiting}` |
| `poll` | `normal_s`, `fast_s` |
| `advisor` | `weeks`, `margin_pct`, `plan_prices`, `profile_plans`, `max_accounts` |
| `updates` | `enabled` |
| `warmup` | par profil, liste de créneaux `{time: "HH:MM", days: [0…6]}` (`days` facultatif, 0 = lundi) ; créneau invalide ignoré |
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
| `appearance` | `color_scheme` (`auto`\|`light`\|`dark` ; `clair`, `sombre` lus et convertis), `account_colors` |

### 4.3 État (écrit par CCS)

| Emplacement | Contenu |
|---|---|
| `$STORE/<profil>/oauth.json`, `account.json`, `usage.json` | jeton OAuth, compte, dernier usage |
| `$STORE/state.json`, `daemon.pid`, `history.db` | état du service, historique d'usage |
| `$STORE/pause.json`, `quiet.json`, `quiet-held.json` | pause, ne pas déranger, notifications retenues |
| `$STORE/switch-origin.json`, `updates.json`, `context-alerts.json` | origine de bascule, mises à jour, alertes de contexte |
| `$STORE/tasks.json`, `tasks/` | file de tâches et journaux |
| `$STORE/terminals.json`, `messages.json`, `conversations-cache.json`, `conversations-moves.json` | terminaux, messages enregistrés, caches |
| `$STORE/labels/`, `limits/`, `avatars/` | étiquettes, limites atteintes (`outcome`, `cwd`, `resume_at`, `lifted_at`), avatars |
| `$STORE/.lock`, `.tasks.lock`, `.pause.lock`, … | verrous |
| `<projet>/.ccs/messages.json` | messages enregistrés du projet |
| `$DATA/ccs/` | `projects.json` (projets ajoutés ou retirés à la main), `archive/` (+ `index.json`), `trash/` |
| `$CACHE/ccs/` | `machines.json` (inventaire : `{<machine>: {path, tools, checked_at}}`), `machines/jobs/<id>.json` et `.log`, `icons-*`, `clear/` (demandes `ccs chat effacer`) |
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
| `CCS_CHAT_TOKEN` | jeton du chat, posé par CCS pour `ccs chat effacer` (l'ancienne `CCS_CHAT_JETON` est encore lue, plus posée) |
| `CCS_SERVER_ROOT` | racine des chemins du serveur (tests) |
| `CCS_APP_ID` | identifiant d'application distinct (essais) |
| `CCS_NO_VTE` | force le terminal externe (essais) |
| `CCS_CHAT_IN_PROCESS` | `1` : chats du bureau dans l'application, sans le pont local (essais, tests) |
| `CCS_PATH`, `CCS_TOOL` | lignes de l'inventaire d'une machine distante (`CCS_TOOL=<outil>=<chemin>` ; l'ancienne `CCS_OUTIL` est encore lue) |
| `HOME`, `PATH`, `SHELL`, `TZ`, `USER`, `PYTHONPATH`, `GNUPGHOME`, `NO_COLOR`, `GIT_SSH`, `GIT_SSH_COMMAND` | usage habituel |
| `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_RUNTIME_DIR`, `XDG_CURRENT_DESKTOP` | dossiers et bureau |
| `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING` | posée pour les chats |

---

## 6. Points à revoir avant le gel

### Commandes

*Réglé en phase 33, tâche 1 : voir la section 1. Liste gardée pour mémoire ; les
numéros de ligne sont ceux de la 0.37.0.*

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

*Réglé par la phase 33, tâche 2 (voir § 2 et § 2.3), sauf les identifiants `id` de `tasks.*`,
`machines.*` et `git.show`, gardés.*

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

*Réglé par la phase 33, tâche 2 (voir § 3).*

- `/api/app-token` utilise un tiret ; les autres routes sont des mots simples (`server/web.py:370`).
- `/api/portier` répond en français (`actif`, `connexion`, `web.py:193`), les autres routes
  en anglais (`user`, `status`, `token`).

### Fichiers et variables

*Réglé par la phase 33, tâche 3 (voir § 4 et § 5).* Décisions :

- noms anglais, séparateur `-` (`quiet-held.json`) ; `$STORE/projects.json` devient
  `project-accounts.json` (l'autre `projects.json`, sous `$DATA/ccs/`, garde son nom) ;
  `~/.claude-accounts/` garde le sien ;
- XDG respecté partout (`core.xdg_home`), y compris `XDG_CONFIG_HOME` ;
- la sauvegarde (`ccs sauvegarde`) passe au format 2 : `profiles/`, `settings/`,
  `shortcuts.json`, manifeste `created` ; le format 1 reste lisible ;
- `LEGACY_KINDS` (ancien format de l'API d'usage, `core.py`) : gardé, c'est un format externe ;
- état sans `fetched_at` (`cli.py`, `_usable_best`) : gardé pendant la 1.x (un service d'avant
  la 1.0.0 peut encore tourner pendant la mise à jour), à retirer en 2.0.

Reste à faire :

- `$STORE/serveurs.json` → `servers.json` : `ccs_app/remote/servers.py`, ligne `path()`, doit
  renvoyer `migrate.store_file("servers.json", "serveurs.json")` (fichier tenu par la tâche 4) ;
- l'ancien dossier `~/.cache/ccs/distant-en-cours/` est nettoyé par `server/bridge.py` sous
  `~/.cache` en dur : à faire passer par `core.ccs_dir("cache")` ;
- ~~valeurs encore françaises dans des états~~ : faites (rôles des messages et des étiquettes,
  modes des bascules et des démarrages de fenêtre, genres du journal, inventaire des machines ;
  voir § 2.3). Restent en français, stockées dans `history.db` ou `switch-origin.json` : le
  pseudo-profil `blocage` des alertes du hook et ses clés (`blocage:<ts>`, `pause`, `deja`), et
  les origines `via` des bascules manuelles (`icone`, `projet`, `raccourci`, `nouvelle-session`) ;
  renvoyés par le pont : les choix de pause `demain` et `manuel` (`pause_choices`, `pause.set
  {choice}`, mêmes mots que `ccs pause`), et les codes d'erreur (voir plus haut).
