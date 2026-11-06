# Architecture

```
            ┌──────────────── ~/.claude-accounts/ ─────────────────┐
            │ <profil>/oauth.json  account.json  usage.json        │
            │ history.db  settings.json  state.json  .lock         │
            │ pause.json  updates.json  terminals.json  limits/    │
            │ conversations-cache.json  conversations-moves.json   │
            │ projects.json  switch-origin.json                    │
            └───────▲───────────────▲──────────────▲───────────────┘
                    │               │              │
  ccs (bash) ───────┤        ccs-daemon (systemd)  │      Comptes Claude (GTK 4)
  save/add/use/rm   │        collecte → décide →   ├───── lit state.json / history.db
                    │        bascule → alerte      │      Indicateur (GTK 3)
                    ▼               │              │
   ~/.claude/.credentials.json      ▼              │
   ~/.claude.json            API Anthropic (usage, jetons)
                             GitHub (dernière version, 1 fois par jour)
```

Autour : les journaux de Claude Code (`~/.claude/projects`, lus seulement, sauf
renommage et projet déplacé) pour l'historique, le coût, l'analyse et les
conseils ; les réglages de GNOME (dconf), où CCS n'écrit que ses propres
raccourcis clavier.

## Modules (`ccs_app/`)

| Module | Rôle |
|---|---|
| `core` | Chemins, profils, verrou, jetons (renouvellement), API d'usage, limites, formats, appel de `ccs` (`run_ccs`, avec `CCS_VIA` vide : l'appelant note lui-même l'origine d'une bascule) |
| `store` | SQLite : relevés `samples` et événements `events` (bascules, alertes, warm-up, erreurs) ; `events(since, types=…)` pour plusieurs types, `last_event(type, before=…)`, détail illisible lu comme `{}` |
| `settings` | Réglages JSON fusionnés avec les valeurs par défaut |
| `forecast` | Fonctions pures : fin de session (régression linéaire), rythme hebdo, fin de semaine prévue (`weekly_forecast` : rythme moyen depuis le début de la semaine, rien avant 12 h), capacité, meilleur compte |
| `autoswitch` | Décision de bascule (pure) et exécution via `ccs use` ; `Decision.detail` (pourcentage, seuil, projection, quota qui expire) gardé dans l'événement pour le journal |
| `alerts` / `notify` | Quoi notifier (pur, anti-doublon par fenêtre ; fin de semaine prévue une fois par semaine, prioritaire sur l'avance hebdomadaire ; conseil de modèle et bilan de la semaine, qui ne font jamais échouer un relevé ; `Alert.default` : action d'un clic sur la notification) / envoi D-Bus (`actions_for`, `send(…, transient=)` ; `message(titre, texte)` : notification passagère de `claude-accounts notify`) |
| `switch_log` | Journal des bascules : entrées lisibles d'après les événements (`build`, pur), groupes par jour, texte de `ccs journal` ; note d'origine d'une bascule manuelle (`note_origin`, `take_origin`), échec d'une bascule lancée par l'application (`record_failure`) |
| `project_accounts` | Compte par projet : `projects.json` (sous verrou), héritage par dossier parent (`resolve`), décisions pures (`proposal`, `preferred_profile`, `origin_for`), textes, `command()` de `ccs projet` |
| `advisor` | Conseiller de formule : formules et tarifs datés, formule de chaque compte, besoin mesuré en unités Pro (fenêtres hebdomadaires et de 5 h), combinaison la moins chère, raisonnement, équivalent API (`compute`, `analyze` pur, `format_text`) |
| `model_advice` | Conseil de modèle près des limites : usage des 30 dernières minutes (fin des journaux, cache), famille moins chère, gain « ×N », notification une fois par fenêtre, indice de la ligne d'état |
| `weekly_report` | Bilan de la semaine : début de semaine (majorité des comptes ou jour fixe), agrégats (`aggregate`, pur), textes, notification hebdomadaire calculée dans un fil |
| `shortcuts` | Raccourcis clavier globaux GNOME : actions, lecture et validation des raccourcis, moteurs `GioBackend` / `MemoryBackend`, installation sous les seuls chemins de CCS, conflits, `command()` de `ccs raccourcis` ; `NOTIFIER` (`--notifier` des commandes de bascule et de pause) |
| `daemon` | Boucle : relevés, prévisions, pause, décision, alertes, rappel des sessions en attente, warm-up, modules optionnels (`hooks`), écriture de `state.json` |
| `pause` | Mode pause : `pause.json` (sous verrou), `set_pause`, `pause_state`, `expire`, `until_for` (1 h, 4 h, début de la plage suivante, reprise manuelle), libellés, `command()` de `ccs pause` |
| `updates` | Nouvelle version : dernière release GitHub, comparaison SemVer, cache `updates.json`, une notification par version (module du daemon, dans un fil) |
| `orchestrator` | Fonctions pures : plage horaire, créneaux décalés, démarrages dus, bascule vers le quota qui expire, réserve, planning, prochain réveil |
| `warmup` | Créneaux fixes et requête minimale dans un `CLAUDE_CONFIG_DIR` temporaire (utilisée aussi par l'orchestrateur) |
| `transcripts` | Lecture des journaux locaux, agrégats, conseils ; `weighted_tokens`, `project_label` (réutilisés par le bilan) |
| `costs` | Coût d'une conversation : tokens par type et équivalent API en dollars (table de tarifs datée), sous-agents compris, cache par chemin / taille / mtime ; `Loader` pour les listes de l'application ; réponses d'une période (`period_answers`, `period_cost`), mêmes tokens au tarif d'un autre modèle (`reprice`) |
| `preview` | Aperçu d'une conversation (lecture en flux du journal, messages lisibles seulement) et export Markdown, coût en en-tête |
| `conversations` | Historique de `~/.claude/projects/*/*.jsonl` : index incrémental (cache), titres, recherche, groupes par date, reprise (VS Code, terminal), projets déplacés (`relocate`), renommage (`rename` : ligne `custom-title` ajoutée en O_APPEND), conversation d'un seul journal (`from_journal`), texte sans accents ni casse (`fold`) |
| `launch_options` | Options d'une nouvelle session (`LaunchSpec` : dossier, compte, `--model`, `--permission-mode`, `origin`), arguments de `claude`, commande à copier, bascule préalable (`switch_if_needed`, qui note l'origine pour le journal et enregistre un échec) et ouverture (`open_session`) |
| `sessions` | Sessions Claude Code ouvertes (`~/.claude/sessions`), consommation d'une conversation, titre lu en fin de journal, conversations et projets récents, transitions d'état, actions (terminal externe, dossier, terminer) |
| `session_hub` | Onglet Sessions sans GTK (pur, testé) : liste des projets, projet choisi, sessions et conversations à afficher, recherche et origine communes, tri, projet d'une session désignée par une notification |
| `terminal` | Terminal intégré sans GTK (pur, testé) : commande et environnement de lancement (`Launch`, `extra_args`), choix intégré / externe, état des onglets (`TabState`, `sync_tabs`), textes de fin et de confirmation, reprise après une limite (`resume_decision`), réouverture (`tab_record`, `restore_plan`), messages en attente (`queue_next`, `queue_*`) |
| `terminal_store` | `terminals.json` : interrupteurs de la page Terminaux, onglets à rouvrir (écriture atomique, fichier illisible ignoré) |
| `limit_events` | Marqueurs « limite atteinte » par conversation (`limits/<session_id>.json`) : écrits par le hook, lus puis consommés par le terminal intégré |
| `integration` | `ccs integrate` (fusion prudente de `~/.claude/settings.json`), ligne d'état (⏸ en pause, « → sonnet ? » près des limites avec un modèle cher), hook `StopFailure` (bascule, sauf en pause ; marqueur de limite) ; `read_stdin_json(timeout)` : contexte JSON de Claude Code, jamais lu sur un terminal, 2 s d'attente au plus |
| `desktop` | Boucle GLib du service : clics sur les notifications (ActionInvoked, ActivationToken), moniteur de `~/.claude/sessions` ; `show_session` : ouvrir l'application sur une session ; onglets acceptés par `gui --page` (`PAGES`, `page_name`) |
| `attention` | Ce qui demande l'attention dans la fenêtre (pur) : libellé de pause de l'en-tête, bandeaux nouvelle version et bilan, badge des sessions en attente, référence de session (`<pid>:<id>`) et cible d'un clic sur une notification |
| `doctor` | Bilan de santé (`ccs doctor`) : vérifications `Check(nom, statut, detail, commande)`, sondes injectables (`Probes`), texte et code de sortie |
| `gui/` | Application GTK 4 / libadwaita (onglets) ; `gui/sessions_page` : onglet Sessions, avec `gui/project_list` (projets), `gui/session_cards` (sessions ouvertes) et `gui/conversation_list` (conversations) ; `gui/terminals` : onglets du terminal intégré (VTE, importé à la demande), `gui/terminal_split` : deux onglets côte à côte ; dialogues `gui/doctor_dialog`, `gui/preview_dialog`, `gui/new_session_dialog` (`Adw.Dialog`, libadwaita ≥ 1.5) ; `gui/history` : courbes et journal des bascules (`Reflow` : légende et en-tête qui se replient, onglet utilisable dès 252 px) ; `gui/project_account_dialog` : bascule proposée avant d'ouvrir, « Compte de ce projet… » ; `gui/advisor_cards` : cartes du bilan et du conseiller (onglet Analyse) ; `gui/shortcuts_group` : groupe « Raccourcis clavier » des Réglages |
| `tray` | Indicateur AyatanaAppIndicator (GTK 3, processus séparé) : jauge, prévisions, pause, nouvelle version ; `APP_ENTRIES` (« Journal des bascules » → `gui --page historique`, « Bilan de la semaine » → `gui --page analyse`, « Ouvrir Comptes Claude ») ; `switch_to` (bascule notée « icone ») ; se relance seul quand le code installé change |
| `cli` | Point d'entrée `claude-accounts` (dont `doctor`, `pause`, `preview` / `apercu`, `export`, `formule` / `conseil`, `semaine`, `journal`, `projet`, `raccourcis` / `shortcuts`, `notify`, `best --notifier`, `pause --notifier`, `gui --session`, `--page`, `--new-session`) |

`ccs` (bash) reste **l'unique implémentation de la bascule** ; le service,
l'application et l'indicateur l'appellent.

## Terminal intégré

```
 onglet Sessions ───────────► Window.open_claude(cwd, resume, title, external)
                                 │  terminal.choose(VTE présent ?, external)
                 ┌───────────────┴───────────────┐
            « integre »                      « externe »
   TerminalsPage.open_claude()           sessions.open_terminal()
   terminal.claude_launch() → Launch       (gnome-terminal, comme avant)
   TerminalTab : Vte.Terminal.spawn_async(argv, cwd, envv)
        │ toutes les 3 s : sessions.list_sessions() → terminal.sync_tabs()
        ▼ (pid de l'onglet = pid de claude : bash -lc "exec claude …")
   identifiant de conversation, état (busy / waiting / idle), titre du journal
```

- `ccs_app/terminal.py` ne dépend pas de GTK. `claude_launch(cwd, resume=None,
  title=None, environ=None, extra_args=())` et `shell_launch(cwd)` renvoient un
  `Launch` (`kind`, `cwd`, `argv`, `env`, `title`, `session_id`, `extra_args`,
  `envv()`) ; les arguments supplémentaires (`--model`, `--permission-mode`)
  suivent `claude` (et `--resume <id>`), échappés dans `bash -lc "exec …"`, et
  l'onglet les garde pour Reprendre et la réouverture. Les variables posées par une
  session Claude Code parente (`CLAUDECODE`, `CLAUDE_CODE_SSE_PORT`…) sont
  retirées par `env -u`, VTE ne sachant qu'en ajouter.
- `ccs_app/gui/terminals.py` : `vte()` importe VTE 3.91 à la première demande
  (None s'il manque ou si `CCS_NO_VTE=1`). `TerminalsPage` (page « terminals »
  du `ViewStack`, cachée sans onglet) gère un `Adw.TabView` de `TerminalTab`.
  Chaque onglet garde son contenu (bandeau, terminal, file de messages, barre
  de fin) dans `tab.panel`, que la vue côte à côte emprunte.

API pour les autres fonctions de l'application (`window.terminals`) :

| Appel | Effet |
|---|---|
| `available` | VTE est là (sinon tout passe par le terminal externe) |
| `open_claude(cwd, resume=None, title=None, extra_args=())` → `TerminalTab` | Nouvel onglet affiché et lancé ; `open_shell(cwd)`, `open(launch, present=True)` pour un `Launch` |
| `find(pid=None, session_id=None)` → `TerminalTab` ou None | Onglet d'un processus ou d'une conversation (arrêté compris) |
| `present(tab)` | Affiche la page et l'onglet, focus clavier dans le terminal |
| `close(tab)` | Ferme l'onglet (confirmation si claude ou un programme tourne) |
| `tabs()`, `states()` | Onglets ouverts, leurs `TabState` (`kind`, `cwd`, `title`, `session_id`, `pid`, `running`, `state`, `exit_status`, `extra_args`, `waiting_for`, `queue`…) |
| `split_with(tab)`, `unsplit(keep=None)`, `toggle_split()` | Vue côte à côte (avec l'onglet affiché ou son voisin) / retour aux onglets |
| `tab.toggle_queue(show=None)`, `send_queue(tab)` | Panneau des messages en attente ; envoi du premier message si claude est libre |
| `tab.send_text(text, enter=False)` | Écrit dans le terminal comme au clavier (`\r` pour Entrée) ; False si arrêté |
| `tab.set_title(title)`, `tab.relaunch()`, `tab.hang_up()` | Titre de l'onglet ; relance après arrêt ; SIGHUP au processus et au programme au premier plan |
| signal `tab-started` (tab) | Processus lancé (aussi à chaque relance) |
| signal `tab-exited` (tab, statut) | Processus arrêté (statut `waitpid`) ; l'onglet reste ouvert avec son bandeau |
| signal `tab-state-changed` (tab) | Identifiant de conversation ou état appris des fiches de session |
| signal `tab-closed` (tab) | Onglet fermé |

`Window.open_claude(...)` / `Window.open_shell(...)` choisissent entre onglet et
terminal externe et renvoient « integre » ou « externe » ;
`Window.rename_conversation(session_id, cwd=None, path=None, current="")` ouvre
le dialogue de renommage.

### Reprise après une limite

```
 claude (onglet) ─ limite ─► hook StopFailure (integration.stop_failure)
                               limit_events.record(session_id, ts, from, to, switched, outcome)
                               ~/.claude-accounts/limits/<session_id>.json (600, dossier 700)
 TerminalsPage, toutes les 3 s : limit_events.load_all() → terminal.resume_decision(tab, event, now)
     « resume » → tab.send_auto("continue") + Entrée, bandeau ; « drop » → bandeau éventuel ;
     « wait » → marqueur gardé (et file de messages bloquée) ; puis limit_events.consume()
```

- `outcome` : `pending` (le hook décide encore), `switched`, `already` (compte
  déjà changé par une autre session ou le service), `failed` (`ccs use` en
  échec), `exhausted` (aucun autre compte), `paused` (CCS en pause : ni bascule
  ni reprise). Le hook écrit `pending` d'abord, puis le résultat ; un marqueur
  impossible à écrire ne fait jamais échouer le hook ; les marqueurs de plus
  de 24 h sont retirés.
- `resume_decision` (pure) : un marqueur ne concerne que l'onglet de la même
  conversation ; il est abandonné si l'onglet est arrêté, si la limite a plus
  de 15 min ou précède le lancement de l'onglet, si quelqu'un a tapé dans
  l'onglet depuis (`typed_at`), si l'interrupteur est coupé ; il attend tant
  que claude n'est pas libre (`free_for_input` : repos, ou attente d'une
  saisie, jamais une demande de permission) ; au plus 3 reprises par heure et
  par onglet (`resumes`), espacées de 2 min. Un événement n'est traité qu'une
  fois (`limits_done`, clé `(session_id, ts)`).

### Messages en attente

`TabState.queue` (messages d'une ligne) ; `queue_add`, `queue_edit`,
`queue_remove`, `queue_move` (purs). `terminal.queue_next(tab, now, blocked)`
renvoie le message à envoyer ou la raison d'attendre : un message par tour
(tour commencé après le dernier envoi, ou message ajouté pendant que claude
était libre), après 2 s de repos ; jamais pendant un tour (`busy`), une
demande de permission, une limite non reprise (`limit_at`, ou marqueur en
attente), ni si une touche a été tapée depuis le début du dernier tour. Si un
envoi ne semble lancer aucun tour (tour plus court que le relevé de 3 s), le
message suivant attend 30 s. `TerminalsPage` l'appelle à chaque relevé et à
chaque changement de file.

### Onglets rouverts et options

`terminal_store` gère `~/.claude-accounts/terminals.json` (600, écriture
atomique ; fichier illisible ou d'un autre format ignoré puis remplacé, entrée
d'onglet inattendue sautée) :

```json
{"version": 1,
 "options": {"auto_resume": true, "reopen_at_start": false},
 "saved_at": 1793000000.0, "selected": 0,
 "tabs": [{"kind": "claude", "cwd": "/home/u/Work/App", "title": "Export CSV",
           "session_id": "0f3c…", "extra_args": ["--model", "opus"],
           "queue": ["lance les tests"]}]}
```

- Enregistrement 1 s après chaque changement (onglet ouvert, fermé, déplacé,
  file modifiée) et à la fermeture de la fenêtre : `terminal.tab_record`.
- Au lancement (`TerminalsPage.startup`), `terminal.restore_plan` écarte les
  dossiers disparus, les conversations ouvertes dans une session Claude Code
  (`conversations.open_ids`) ou déjà dans un onglet, les doublons ; une
  conversation jamais écrite repart en nouvelle session. Avec
  `reopen_at_start`, réouverture directe ; sinon bandeau et toast « Rouvrir »,
  et tant qu'on n'a pas répondu, `merge_records` garde la liste de la dernière
  fois en plus des nouveaux onglets. `restore_summary` donne le message final.

### Côte à côte

`gui/terminal_split.SplitView` : un `Gtk.Paned` dont chaque moitié (`Half`)
emprunte le `tab.panel` de son onglet (un widget GTK n'a qu'un parent) et le
rend au retour à la vue par onglets ; processus et `Vte.Terminal` ne sont
jamais recréés. La page bascule entre `tabs`, `split` et `empty` (page de la
proposition de réouverture) dans un `Gtk.Stack`. Raccourcis de la page :
Ctrl+Maj+E (côte à côte / retour), Ctrl+Maj+M (messages en attente).

## Pause

```
 ccs pause / indicateur / application ──► pause.set_pause(until) / clear_pause()
                                            ~/.claude-accounts/pause.json (0600, verrou .pause.lock)
                                            {"since": ts, "until": ts | null}
 daemon, à chaque relevé : pause.expire(now) ─► « Pause terminée » (une fois)
                            pause.pause_state(now) ─► en pause ?
```

- `pause.until_for(choix, now)` : « 1h », « 4h », « demain » (début de la
  prochaine plage horaire, `orchestrator.next_period_start`), « manuel »
  (`None` : jusqu'à reprise). `pause.command(choix)` renvoie (code de sortie,
  message) pour `ccs pause` (2 pour un choix inconnu, « reprendre » = « off ») ;
  `cli.cmd_pause` réveille le service (`daemon.request_refresh()`) seulement si
  l'état a changé. `ccs status` ajoute une ligne de pause.
- L'en-tête de la fenêtre lit `pause.json` directement (plus frais que
  `state.json`) : `attention.pause_header` donne « Auto ⏸ jusqu'à 14:00 » ou
  « Auto ⏸ en pause » ; l'indicateur et les cartes de l'application posent ou
  lèvent la pause puis réveillent le service.
- En pause, le daemon remplace la décision par `autoswitch.none("en pause …")`,
  ne fait ni bascule anticipée ni démarrage de fenêtre, et ne publie que les
  fenêtres en cours dans `orchestrator.plan` ; la réserve reste calculée (elle
  oriente la recommandation). Il se réveille à l'échéance (+ 1 s). Une pause
  impossible à lever (fichier non supprimable) ne compte plus et n'interrompt
  jamais le relevé.
- Bascules manuelles, alertes et warm-up programmés ne regardent pas la pause.
- Le hook `StopFailure` relit la pause (une pause illisible ne le fait jamais
  échouer) : pas de bascule, marqueur `paused`, une seule notification « CCS
  est en pause jusqu'à HH:MM : pas de bascule automatique. » pour des sessions
  bloquées en même temps. La ligne d'état ajoute « ⏸ » devant son texte quand
  `state.json` contient une pause.

## Nouvelles versions

- `updates.hook` est un module du daemon (`Daemon.hooks`) : à chaque relevé,
  si `check_due` (24 h depuis la dernière vérification, 1 h si GitHub n'avait
  pas répondu), un fil interroge
  `api.github.com/repos/mawena/CCS/releases/latest` (sans authentification,
  User-Agent « ccs », 5 s, 1 Mo au plus) ; sinon seul le cache est lu. Aucune
  erreur n'est fatale (hors ligne, 403, 429, réponse illisible).
- Cache `~/.claude-accounts/updates.json` : dernière vérification, dernière
  version publiée, dernière version annoncée (une seule notification par
  version). Comparaison SemVer avec `ccs_app.__version__` ; seul un lien vers
  la page du projet est retenu.
- `state.json` → `update` lit le cache (aucun accès réseau) ; l'indicateur et
  les Réglages l'affichent.
- Relance après une mise à jour : le service s'arrête avec le code 75 quand son
  code change (systemd le relance) ; l'indicateur relit `daemon.code_stamp()`
  toutes les 10 s et se relance par `os.execv` (même interpréteur, mêmes
  arguments) quand l'empreinte a changé puis n'a plus bougé, ou s'arrête si le
  paquet a été désinstallé.

## Outils de lecture

Modules sans GTK, testés, qui ne font que lire (sauf
`launch_options.switch_if_needed`, qui change le compte actif) :

- `doctor` : `run_checks(probes)` enchaîne les vérifications dans l'ordre
  d'affichage ; chacune renvoie un ou plusieurs `Check(nom, statut, detail,
  commande)` (`ok`, `avertissement`, `erreur` ; `commande` est à copier, jamais
  exécutée). Toutes les sondes (systemctl, dpkg-query, /proc, D-Bus, `claude
  --version`…) passent par `Probes`, que les tests remplacent ; une sonde qui
  plante donne « vérification impossible » sans arrêter le bilan. `token_info()`
  ne renvoie d'une connexion que `present` et ses dates d'expiration ; les
  messages d'erreur affichés sont expurgés de tout ce qui ressemble à un jeton.
  `main()` imprime le bilan et renvoie le code de sortie (0 si tout est `ok`).
- `preview` : `read_messages(path, limit=None, results=True)` lit le journal
  en flux (ligne par ligne, dernière ligne inachevée ignorée, tri rapide sur le
  type de ligne avant décodage, résultats d'outils de plus de 4 Mo non décodés)
  et ne garde que les demandes tapées, le texte des réponses, les appels
  d'outils résumés (avec leur résultat raccourci) et deux repères (compactage,
  interruption). `to_markdown`, `markdown_for`, `export_markdown` (écriture
  atomique) acceptent `cost=` (texte de `costs.format_cost`, ligne « Coût » de
  l'en-tête) ; `suggested_filename` donne `<titre-simplifié>.md`.
  `ccs export` écrit dans le dossier courant par défaut, dans un dossier donné
  sous ce nom, ou dans le fichier donné (remplacé), et affiche le chemin absolu.
- `costs` : `conversation_cost(path, subagents=True)` → `Cost` (tokens par
  type, dollars, détail par modèle, `inconnu`). Tarifs `PRICES` datés de
  `PRICES_DATE` (2026-10-06) ; écriture du cache à 1,25 × / 2 × l'entrée,
  grille longue de Haiku 5.5, mode rapide, inférence US ; modèle inconnu →
  `None` (« tarif inconnu »), jamais d'estimation. Une réponse écrite sur
  plusieurs lignes (même identifiant) compte une fois ; sous-agents lus dans
  `<id>/subagents/*.jsonl`. Cache en mémoire (512 journaux) par chemin, taille
  et `mtime_ns`. `format_cost` (« 1,2 M tokens · ≈ 3,40 $ »), `format_short`
  (« ≈ 3,40 $ » pour une ligne de liste), `format_details` (par modèle).
  `Loader` calcule les coûts d'une liste dans un fil, un journal après l'autre,
  lignes visibles d'abord ; une nouvelle demande remplace la précédente et
  chaque résultat revient dans l'interface par `GLib.idle_add`.
- `launch_options` : `MODELS`, `PERMISSION_MODES` (d'après `claude --help`),
  `claude_args(model, permission_mode, resume, extra)` (valeurs vérifiées : un
  modèle ou un identifiant ne peut pas devenir une option), `LaunchSpec(cwd,
  profile, model, permission_mode)` avec `needs_switch(actif)`, `args()`,
  `shell_command()` ; `launch(spec)` pour un terminal externe.
  `NewSessionDialog` renvoie un `LaunchSpec` sans rien basculer ;
  `switch_if_needed(spec)` lance `ccs use <profil>` si le compte diffère de
  l'actif (renvoie (a basculé, erreur)) et `open_session(spec, embedded,
  open_claude)` ouvre l'onglet avec `extra_args=spec.args()` ou, sans VTE, un
  terminal externe.

Les dialogues `gui/doctor_dialog.py`, `gui/preview_dialog.py` et
`gui/new_session_dialog.py` sont des `Adw.Dialog` (libadwaita ≥ 1.5) ; le
travail lourd (bilan, lecture du journal, coût, export) tourne dans un fil
(`common.in_thread`). L'aperçu affiche d'abord les 300 derniers messages et
construit l'affichage par paquets de 150 pour ne pas figer la fenêtre.

## Fenêtre de l'application

`gui/app.py` (`App`, instance unique, et `Window`) assemble les onglets et ce
qui demande l'attention :

- **Menu ☰** : « Nouvelle session… » (`win.new-session`) et « Bilan de santé… »
  (`win.doctor`).
- **En-tête** : « Auto », remplacé pendant une pause par le bouton
  `attention.pause_header` (popover « Reprendre maintenant ») ; l'en-tête
  s'élargit, le seuil de la fenêtre étroite (onglets en bas) en tient compte :
  1100 sp, 1220 sp quand la page Terminaux est visible (`NARROW_SP`).
- **Bandeaux** : nouvelle version (`attention.update_banner` d'après
  `state["update"]`, seulement si plus récente que la version installée, une
  fois par lancement, bouton « Voir ») ; bilan de santé (`doctor.run_checks`
  dans un fil 4 s après l'ouverture, `attention.doctor_banner` seulement en
  cas d'erreur, « Voir le bilan », retiré quand le bilan est ouvert).
- **Onglet Sessions** (`gui/sessions_page.SessionsPage`, page `sessions`,
  unique : `gui/conversations_page.py` a disparu) — voir plus bas.
  Badge = `attention.waiting_count` (avec attention si l'onglet n'est pas
  affiché).
- **Onglet Historique** : courbes, puis journal des bascules
  (`switch_log.load`, groupes par jour, 7 jours / 30 jours / tout, 100 entrées
  de plus à la demande).
- **Onglet Analyse** : cartes `WeeklyReportCard` puis `AdvisorCard` (calculées
  l'une après l'autre dans un fil, à la première ouverture), puis l'analyse.
- **Réglages** : groupe « Terminal intégré » (les deux interrupteurs, qui
  passent par les actions de la page Terminaux, seule à écrire
  `terminals.json`) ; groupes « Conseils » (conseil de modèle, bilan de la
  semaine : `alerts.*`) et « Conseiller de formule » (`advisor.*`, formule
  d'un compte affichée seulement si la détection hésite, tarifs dans une ligne
  dépliable) ; groupe « Raccourcis clavier » (`ShortcutsGroup`, raccourci
  affiché en texte). Ordre : Bascule automatique, Orchestrateur, Alertes,
  Conseils, Conseiller de formule, Intégration, Terminal intégré, Raccourcis
  clavier, Warm-up, Service.
- **Ligne de commande** : `claude-accounts gui --page <onglet>` ouvre un
  onglet, `--new-session` le dialogue « Nouvelle session » (commandes des
  raccourcis clavier) ; voir [Onglets et dialogue à
  l'ouverture](#onglets-et-dialogue-à-louverture).

API de la fenêtre pour les autres pages :

| Appel | Effet |
|---|---|
| `new_session(cwd=None)` | Ouvre `NewSessionDialog` (dossier proposé : `cwd`, sinon celui de l'onglet Sessions ; compte du projet présélectionné) |
| `start_spec(spec)` | Bascule si besoin (`switch_if_needed`, dans un fil ; échec : message, rien n'est ouvert), puis `open_spec` (`open_session`) |
| `show_session(ref)` | Onglet du terminal intégré de la session, sinon sa carte dans l'onglet Sessions, projet choisi et filtres retirés (`attention.focus_target`, `SessionsPage.highlight`) |
| `show_page(name)` | Affiche un onglet (`desktop.page_name`) ; Terminaux sans onglet ouvert : Sessions et un message |
| `switch(name)` | Bascule depuis la fenêtre (`ccs use`), origine « application » notée pour le journal |
| `preview(conv)` | Dialogue d'aperçu |
| `show_doctor()` | Dialogue du bilan (retire le bandeau) |
| `reveal_terminals()` | Rend la page Terminaux visible sans l'afficher |

### Onglet Sessions

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ [☰] [Rechercher…] [Toutes les origines ▾] [Nouvelle session…]           │
 ├──────────────────────┬──────────────────────────────────────────────────┤
 │ ProjectList          │ en-tête du projet (compte, Nouvelle session ▾)   │
 │ (barre latérale      │ SessionCards : « Ouvertes maintenant »           │
 │  de OverlaySplitView)│ ConversationList : « Conversations » par date    │
 └──────────────────────┴──────────────────────────────────────────────────┘
```

- `session_hub` (pur, testé) : `build(convs, found, selected, query, origin,
  titles, suggestions, associations)` → `View` (entrées `ProjectEntry` avec
  « Tous les projets » en tête, entrée choisie, sessions et conversations à
  afficher, totaux). Tri : projets avec une session ouverte d'abord, puis
  dernière activité. Recherche (`conversations.fold` : sans accents ni casse)
  et origine (`session_origin` pour une session) s'appliquent aux
  conversations, aux sessions et à la liste des projets (un projet sans
  résultat en sort, sauf celui qui est choisi). `entry_detail`, `count_text`,
  `project_for_ref` (projet d'une session désignée par une notification).
- `gui/project_list.ProjectList` : la colonne de gauche (point
  `ouverte` / `attention`, nombre de conversations, seconde ligne d'après
  `entry_detail`), reconstruite seulement quand `entries_signature` change.
- `gui/session_cards.SessionCards` : une carte par session ouverte (état,
  consommation, coût, Afficher, terminal ici, dossier, Aperçu, Renommer,
  Terminer).
- `gui/conversation_list.ConversationList` : conversations groupées par
  date, 60 lignes puis « Afficher 60 de plus », coût calculé ensuite pour
  les lignes affichées ; reprise dans l'application, un terminal externe ou
  VS Code, aperçu, renommage, copie de la commande, dossier, projet déplacé.
- Deux lectures dans des fils : sessions ouvertes, consommation, titres et
  comptes par projet toutes les 15 s quand l'onglet est affiché ; historique
  (`conversations.scan`) toutes les 30 s. Toute ouverture ou reprise passe
  par `project_account_dialog.confirm_switch`.
- Points de rupture (`Adw.BreakpointBin`) : sous 800 sp, la liste des projets
  se replie en surimpression (☰ l'ouvre, choisir un projet la referme) ; sous
  560 sp, boutons en icônes et filtre d'origine abrégé « Toutes ».
- `highlight(pid, id)` (clic sur une notification) : au relevé suivant, le
  projet de la session est choisi, les filtres qui la cacheraient retirés et
  la carte mise en évidence ; session fermée : message et projet de sa
  conversation (`project_for_ref`).
- `gui/common` regroupe les briques partagées : `cap`, `error_text`,
  `short_path`, `existing_parent`, `string_factory`, `menu_button`.

### Onglets et dialogue à l'ouverture

`desktop.PAGES` (noms du `ViewStack` : `accounts`, `planning`, `sessions`,
`terminals`, `history`, `analysis`, `prefs`) ; `desktop.page_name(texte)`
accepte aussi les titres français (`comptes`, `historique`, `analyse`,
`terminaux`, `reglages`), sans accents ni casse, et `conversations` → `sessions`.
`cli` refuse un nom inconnu (code 2). `gui.app.run(session, page,
new_session)` : si l'application tourne déjà, `remote_actions` lui envoie
dans l'ordre les actions d'application `show-page` (nom), `show-session`
(réf.) et `new-session` ; sinon elles sont appliquées après l'ouverture de la
fenêtre (le dialogue une fois la fenêtre affichée). `Window.show_page(nom)` :
`terminals` sans onglet ouvert affiche l'onglet Sessions avec un message.

## Notifications cliquables

```
 daemon : session « a terminé » / « attend ta réponse » / rappel
    Alert(default="show:<pid>:<id>", actions=(("show:…", "Afficher"),))
    notify.send → Notify(actions = ["default", "Afficher", "show:…", "Afficher"…])
 desktop (service) : ActivationToken puis ActionInvoked(id, "default" | clé)
    Daemon.handle_action("show:<réf>", token) → desktop.show_session(réf, token)
        application ouverte ? ActivateAction("show-session", [réf]) sur
                              io.ccs.ClaudeAccounts (ou CCS_APP_ID), par D-Bus
        sinon  systemd-run --user --scope --slice=app.slice --
                   claude-accounts gui --session <réf>
 App : action « show-session » → Window.show_session(réf)
       (aussi « show-page » et « new-session » pour gui --page / --new-session)
```

- La référence est `<pid>:<identifiant>` (ou l'un des deux) : le pid suit le
  processus, l'identifiant retrouve la conversation si le pid est inconnu.
- Le jeton d'activation du bureau est transmis (données de plateforme ou
  `XDG_ACTIVATION_TOKEN`) pour que la fenêtre passe au premier plan. Lancée
  dans sa propre unité, la fenêtre survit à un redémarrage du service.
- Les boutons « Basculer sur … » (`use:<profil>`) passent par le même
  `handle_action`, revérifiés au moment du clic.

## Journal des bascules

```
 service, hook, application ──► history.db : événements switch / error / alert / warmup
 application, avant « ccs use » ──► switch_log.note_origin(profil, via, projet)
                                      ~/.claude-accounts/switch-origin.json (600)
 daemon.detect_manual_switch ──► switch_log.take_origin(profil)   (lue puis retirée)
                                      switch {mode: manual, from, via, project}
 onglet Historique, ccs journal ──► switch_log.load(store, jours)
                                      build(événements, marqueurs limits/, compte d'avant) ──► group_by_day
```

Champs ajoutés aux événements (rétrocompatibles : un champ absent est déduit,
jamais exigé) :

| Événement | Champs |
|---|---|
| `switch`, `mode` `auto` | `from`, `reason`, `percent`, `threshold`, `projected` (seulement quand c'est la projection qui décide) |
| `switch`, `mode` `anticipee` | `from`, `reason`, `lost`, `minutes`, `expiring` |
| `switch`, `mode` `manual` | `from` ; `via` (`application`, `icone`, `notification`, `ccs`, `raccourci`, `nouvelle-session`, `projet`) et `project` quand l'origine est connue |
| `error`, `op` `auto_switch` | `message`, `mode`, `from`, `reason` |
| `error`, `op` `notification` | `message`, `via`, `from` |
| `error`, `op` `manual` | `message`, `via`, `from`, `project` (`record_failure`, bascule lancée par l'application) |

- Note d'origine `{"profile", "via", "ts", "project"?}` : écrite juste avant
  `ccs use` par `launch_options.switch_if_needed` (nouvelle session, compte du
  projet), `Window.switch` (« application »), `tray.switch_to` (« icone ») et
  `claude-accounts best` (« ccs », ou « raccourci » avec `--notifier`), et
  effacée si la bascule échoue. `ccs use` (bash) l'écrit lui-même avec `jq`
  (« ccs » à la main, « raccourci » avec `--notifier`), sauf si `CCS_VIA` est
  définie et vide (`core.run_ccs` la vide toujours) et sans jamais écraser une
  note du même compte de moins de 60 s ; `take_origin` ne la rend
  que pour le compte constaté et pendant 10 min (une note d'un autre compte est
  gardée, une note périmée ou illisible retirée). Une bascule sans note reste
  « manuelle » sans origine.
- `build` (pur) : une entrée `Entry(ts, kind, source, target, title, reason,
  ok, detail, projects)` par bascule (`auto`, `anticipee`, `blocage`,
  `manuelle`, `initial`), échec (`echec`), limite sans bascule (`limite` :
  alertes `pause` et `blocage:<ts>` du hook, sans bascule ni échec à 5 s près)
  et démarrage de fenêtre (`fenetre`, un par compte et créneau, « sans
  réponse » au bout de 15 min). Une bascule `manual` sans origine constatée par
  le service moins de 15 s avant la bascule automatique, anticipée ou après
  blocage du même compte est un doublon, sautée. Les projets d'un blocage
  viennent des marqueurs `limits/<session_id>.json` (lus sans être consommés,
  issue `switched` / `already` / `failed` / `paused` / `exhausted`, de 5 s
  avant à 3 min après), le nom du projet du dossier noté dans le journal de la
  conversation.
- Anciens événements : pourcentage et quota relus dans `reason`, compte quitté
  déduit de la bascule précédente (`store.last_event("switch", before=…)` pour
  la première de la période).

## Compte par projet

```
 ccs projet, « Compte de ce projet… » ──► project_accounts.set(dossier, compte) / set_ask(dossier, …)
                                           ~/.claude-accounts/projects.json (600, verrou .projects.lock)
 ouverture ou reprise depuis l'application ──► confirm_switch(window, cwd, ouvrir)
     proposal(cwd, actif, profils, en pause ?) : None ──► ouvrir()
                                                 association ──► Adw.AlertDialog
        « Basculer et ouvrir »  : switch_then → switch_if_needed(LaunchSpec(…, origin="projet")) → ouvrir()
        « Ouvrir sans basculer » : ouvrir() ; « Ne plus demander pour ce projet » : set_ask(dossier, False)
```

```json
{"version": 1,
 "projects": {"/home/u/Work": {"profile": "boulot", "ask": true},
              "/home/u/Work/Perso": {"profile": "perso", "ask": false}}}
```

- `resolve(cwd, associations)` : l'association du dossier, sinon du parent le
  plus proche (plus long préfixe de chemin). Il n'existe pas d'association
  « aucun compte » : retirer celle d'un sous-dossier le laisse hériter du
  parent.
- `proposal` : rien en pause, pour « ne plus demander », pour le compte actif
  ou un compte disparu. `preferred_profile` (présélection de « Nouvelle
  session ») suit les mêmes règles, et `origin_for` donne « projet » quand le
  compte choisi est celui du projet (origine du journal).
- `set` remet `ask` à vrai quand le compte change ; fichier illisible ou d'une
  autre version : aucun projet (remplacé au prochain enregistrement), entrée
  inattendue sautée. Rien ici ne bascule : seule l'application, après
  confirmation.

## Conseils

### Conseiller de formule (`advisor`)

- **Formules** (`PLANS`, claude.com/pricing, `PLAN_PRICES_DATE` 2026-11-06) :
  `pro` « Pro » 20 $ (1 Pro par 5 h, 1 par semaine), `max5` « Max » 100 $
  (5 et 5), `max20` « Ultra » 200 $ (pas de limite de 5 h, 10 par semaine).
  `prices_stale` après 120 jours ; `advisor.plan_prices` remplace un prix
  (nombre ≥ 0, sinon ignoré).
- **Formule d'un compte** (`detect_plans`) : `advisor.profile_plans`, sinon
  `plan_key(subscriptionType, rateLimitTier)` (`rateLimitTier` est le seul
  champ lu de `<profil>/oauth.json`). Un `max` sans palier est supposé
  `max5` et signalé ; une formule inconnue est ignorée.
- **Besoin** (`week_needs`) : relevés `session` et `weekly_all` du store.
  `windows` regroupe les relevés d'une limite par fenêtre (même
  réinitialisation à 30 min près ; usage = plus haut pourcentage ; une fenêtre
  ne commence jamais avant la fin de la précédente ; semaine en cours depuis
  plus d'un jour projetée à son rythme, plafonnée à 100 %). Pour chaque semaine
  glissante (`advisor.weeks`) : besoin hebdomadaire = somme, sur les comptes,
  de l'usage moyen de leurs fenêtres × capacité de la formule ; besoin de 5 h =
  plus forte somme de fenêtres de 5 h ouvertes en même temps
  (`_concurrent_peak`). Semaine couverte à moins de 50 % : ignorée ; moins de
  3 jours de relevés : pas de conseil ; semaine bridée (alerte `exhausted:`,
  ou blocage du hook sans bascule dans les 3 min) : + 15 %.
- **Combinaison** (`recommend`) : toutes les combinaisons d'au plus
  `advisor.max_accounts` formules ; la moins chère (puis la moins nombreuse)
  dont les capacités couvrent le plus haut besoin × (1 + `advisor.margin_pct`),
  sinon la plus grande. Une alternative à un seul compte accompagne une
  combinaison de plusieurs.
- **Équivalent API** : `costs.period_cost(~/.claude/projects, début, maintenant)`
  (journaux de ce PC, sous-agents compris), ramené à 30,44 jours.
- `compute()` lit tout (store, profils, journaux) ; `analyze()` est pur ;
  `format_text` pour `ccs formule`, `AdvisorCard` dans l'onglet Analyse.

### Conseil de modèle (`model_advice`)

- `pending(compte actif, cfg, now, envoyées)`, appelé par
  `alerts.pending_alerts` : seuil d'abord (`effective_percent` de la session ou
  de la semaine ≥ `alerts.model_advice_pct`), clé
  `model_advice:<compte>:<fenêtre de 5 h>` pas encore envoyée ; alors
  seulement, `recent_usage` lit la fin (512 Ko) des journaux modifiés depuis
  30 min, avec un cache de 64 fichiers par taille et date de modification.
- Famille dominante en dollars (Fable pour Mythos) ; `stretch` = son coût /
  coût des mêmes tokens au tarif du modèle de référence de la famille moins
  chère (`CHEAPER`, `REFERENCE`, `costs.reprice`) ; notification à partir de
  × 1,25, affichée « plus de ×5 » au-delà de 5.
- `statusline_hint(state, model, settings, now)` : modèle du contexte JSON de
  Claude Code, seuil lu dans `state.json`, aucune lecture de journal.

### Bilan de la semaine (`weekly_report`)

- `week_anchor` : jour et heure fixes (`alerts.weekly_report_day`,
  `alerts.weekly_report_hour`), sinon le début de semaine de la majorité des
  comptes (réinitialisations hebdomadaires ramenées sur 7 jours, groupées à
  3 jours près), sinon lundi à l'heure réglée.
- `pending_alert`, appelé à chaque relevé : rien tant que le bilan n'est pas
  dû (dans les 2 jours qui suivent le début de semaine), ni si un bilan est
  parti à moins de 5 jours (clé `weekly_report:<date>`). Dû : `has_data`
  (relevés couvrant au moins 3 jours) puis `build_report` dans un fil
  `ccs-bilan`, qui libère ensuite le cache des coûts ; la notification part au
  relevé suivant ; un échec est retenté une heure plus tard.
- `aggregate` (pur) : comptes (pic et points de la semaine, fenêtres, limites
  de session, bascules reçues), conversations, sessions (reprise après 30 min
  d'inactivité), coût, modèles et projets en tokens pondérés, bascules par
  mode, alertes par genre, blocages ; `build_report` y ajoute la semaine
  précédente.
- `WeeklyReportCard` : `week_choices` (semaine en cours et 6 précédentes), la
  dernière terminée par défaut ; le conseiller est calculé ensuite, sur des
  journaux déjà en cache.

## Raccourcis clavier

```
 Réglages › Raccourcis clavier (ShortcutsGroup), ccs raccourcis ──► shortcuts.install / remove / set_binding
     moteur GioBackend (Gio.Settings, dconf) — MemoryBackend pour les tests
 org.gnome.settings-daemon.plugins.media-keys  custom-keybindings = [… chemins, dans l'ordre …]
 …/custom-keybindings/ccs-<action>/            name « CCS : … », command, binding
 gnome-settings-daemon ──► lance la commande, application ouverte ou non
```

- Actions (`ACTIONS`) : `ouvrir`, `sessions`, `nouvelle-session`, `suivant`,
  `meilleur`, `pause`, `reprendre` ; aucune n'est installée par défaut. La
  commande est écrite avec un chemin absolu (`/usr/bin`, sinon `bin/` du
  dépôt, sinon le `PATH`), échappée par `shlex.join` (le bureau la découpe
  sans shell). Les commandes de bascule et de pause portent `--notifier`
  (`ccs next --notifier`, `ccs best --notifier`, `ccs pause 1h --notifier`,
  `ccs pause off --notifier`) : résultat en notification passagère, bascule
  notée « raccourci ». Une commande installée différente de l'attendue (dont
  celles d'avant `--notifier`) rend l'élément `outdated` : signalé, jamais
  réécrit d'office ; `update_commands` (bouton « Mettre à jour les
  commandes ») ou `install` la réécrivent.
- Écritures : CCS n'écrit que sous `…/custom-keybindings/ccs-<id>/`. Les
  valeurs d'un raccourci sont posées avant son ajout à la liste ; la liste est
  relue juste avant d'être réécrite, en une seule écriture qui garde l'ordre ;
  un retrait enlève le chemin de la liste puis efface ses valeurs.
  `remove_all` ne retire que les chemins `ccs-*`, jamais les autres.
- `parse_binding` : « <Super><Alt>c », « Super+Alt+C », « Ctrl+Maj+F5 »…
  (Super, Ctrl ou Alt obligatoire, sauf touches XF86). `conflicts` cherche la
  combinaison dans les raccourcis du bureau (fenêtres, Shell, Mutter,
  media-keys, Dock, assistant de tuilage), les raccourcis personnalisés et les
  autres actions de CCS : signalés, jamais bloquants.
- `supported()` : `XDG_CURRENT_DESKTOP` contient GNOME et les schémas sont
  installés ; sinon un message et les commandes à associer à la main.
- `CaptureDialog` suspend les raccourcis du bureau pendant la capture
  (`inhibit_system_shortcuts`) ; le groupe suit les changements de
  `custom-keybindings` faits ailleurs tant qu'il est affiché.

## Règles de sécurité des jetons

- Tout renouvellement passe par un verrou (`fcntl` sur `.lock`) et relit le
  fichier sous verrou : pas de double rotation.
- Le jeton du compte actif n'est jamais renouvelé tant qu'un processus `claude`
  tourne : Claude Code s'en charge.
- Avant une bascule, le jeton vivant (éventuellement renouvelé par Claude Code)
  est resauvegardé dans le profil quitté.
- Écritures atomiques (fichier temporaire + `rename`), droits 600 / 700.
- `claude auth logout` n'est jamais utilisé.

## Cadence

Relevé de tous les comptes toutes les 5 min ; du seul compte actif toutes les
minutes s'il dépasse 85 % ou si la fin de session est estimée à moins de 15 min.
Orchestrateur actif : réveil 30 s après la prochaine fin de fenêtre ou le
prochain créneau de démarrage (au plus tôt dans 30 s). En pause : réveil à
l'échéance de la pause. Session en attente de réponse : réveil à l'heure du
prochain rappel (au plus tôt dans 5 s).

Ordre des décisions à chaque tick : levée d'une pause échue ; en pause, aucune
bascule ni démarrage ; sinon bascule à seuil (98 %), puis bascule anticipée
vers le quota qui expire, puis démarrages de fenêtres ; puis alertes (dont la
fin de semaine prévue, le conseil de modèle et le bilan de la semaine) ; suivi
des sessions (fin, attente, rappel) ; modules
optionnels (`hooks` : nouvelle version) ; écriture de `state.json`.
`SIGUSR1` déclenche un relevé immédiat (bouton Actualiser, `claude-accounts
collect`).

## Format de `state.json`

```json
{
  "updated_at": 1793000000.0,
  "active": "perso",
  "capacity": 1.4,
  "best": {"name": "pro", "reason": "au repos, semaine à 22 %"},
  "auto_switch": {"enabled": true, "paused": false,
                  "decision": {"action": "none", "target": null, "reason": "…"},
                  "last": {"ts": 0, "profile": "perso", "mode": "manual"}},
  "orchestrator": {"enabled": true, "paused": false, "active_now": true, "period": ["…", "…"],
                   "reserve": ["boulot"], "next_wake": "…",
                   "plan": [{"name": "perso", "start": "…", "end": "…", "kind": "current|planned"}]},
  "pause": {"since": "…", "until": "… | null", "label": "jusqu'à 14:00"},
  "update": {"version": "0.5.0", "url": "https://github.com/mawena/CCS/releases/…", "name": "…"},
  "accounts": [{
    "name": "perso", "email": "…", "org": "…", "plan": "pro", "active": true,
    "error": null, "fetched_at": 1793000000.0,
    "limits": [{"kind": "session", "label": "Session (5 h)", "percent": 54, "resets_at": "…"}],
    "forecast": {"verdict": "limit|ok|stable|unknown", "eta": "…", "rate_per_min": 0.4,
                 "minutes_before_reset": 35},
    "pace": {"ideal": 57.1, "margin": 5.2, "per_day_budget": 16.0, "days_left": 3.0},
    "weekly_forecast": {"verdict": "limit|ok|unknown", "eta": "…", "rate_per_day": 18.5,
                        "days_before_reset": 1.6}
  }]
}
```

`pause` et `update` valent `null` hors pause / sans nouvelle version (ou
vérification désactivée) ; `until` vaut `null` pour une pause jusqu'à reprise
manuelle. `auto_switch.paused` et `orchestrator.paused` reprennent l'état de
pause ; en pause, `decision.reason` vaut « en pause jusqu'à … » et `plan` ne
contient que les fenêtres en cours. `weekly_forecast` vaut `null` sans limite
hebdomadaire connue ; `eta` est la date où la semaine sera épuisée au rythme
moyen (`rate_per_day`, % par jour), `days_before_reset` l'avance sur la
réinitialisation quand `verdict` vaut `limit`.
