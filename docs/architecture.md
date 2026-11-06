# Architecture

```
            ┌──────────────── ~/.claude-accounts/ ─────────────────┐
            │ <profil>/oauth.json  account.json  usage.json        │
            │ history.db  settings.json  state.json  .lock         │
            │ pause.json  updates.json  terminals.json  limits/    │
            │ conversations-cache.json  conversations-moves.json   │
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

## Modules (`ccs_app/`)

| Module | Rôle |
|---|---|
| `core` | Chemins, profils, verrou, jetons (renouvellement), API d'usage, limites, formats, appel de `ccs` |
| `store` | SQLite : relevés `samples` et événements `events` (bascules, alertes, warm-up, erreurs) |
| `settings` | Réglages JSON fusionnés avec les valeurs par défaut |
| `forecast` | Fonctions pures : fin de session (régression linéaire), rythme hebdo, fin de semaine prévue (`weekly_forecast` : rythme moyen depuis le début de la semaine, rien avant 12 h), capacité, meilleur compte |
| `autoswitch` | Décision de bascule (pure) et exécution via `ccs use` |
| `alerts` / `notify` | Quoi notifier (pur, anti-doublon par fenêtre ; fin de semaine prévue une fois par semaine, prioritaire sur l'avance hebdomadaire) / envoi D-Bus |
| `daemon` | Boucle : relevés, prévisions, pause, décision, alertes, rappel des sessions en attente, warm-up, modules optionnels (`hooks`), écriture de `state.json` |
| `pause` | Mode pause : `pause.json` (sous verrou), `set_pause`, `pause_state`, `expire`, `until_for` (1 h, 4 h, début de la plage suivante, reprise manuelle), libellés, `command()` de `ccs pause` |
| `updates` | Nouvelle version : dernière release GitHub, comparaison SemVer, cache `updates.json`, une notification par version (module du daemon, dans un fil) |
| `orchestrator` | Fonctions pures : plage horaire, créneaux décalés, démarrages dus, bascule vers le quota qui expire, réserve, planning, prochain réveil |
| `warmup` | Créneaux fixes et requête minimale dans un `CLAUDE_CONFIG_DIR` temporaire (utilisée aussi par l'orchestrateur) |
| `transcripts` | Lecture des journaux locaux, agrégats, conseils |
| `costs` | Coût d'une conversation : tokens par type et équivalent API en dollars (table de tarifs datée), sous-agents compris, cache par chemin / taille / mtime |
| `preview` | Aperçu d'une conversation (lecture en flux du journal, messages lisibles seulement) et export Markdown |
| `conversations` | Historique de `~/.claude/projects/*/*.jsonl` : index incrémental (cache), titres, recherche, groupes par date, reprise (VS Code, terminal), projets déplacés (`relocate`), renommage (`rename` : ligne `custom-title` ajoutée en O_APPEND) |
| `launch_options` | Options d'une nouvelle session (`LaunchSpec` : dossier, compte, `--model`, `--permission-mode`), arguments de `claude`, commande à copier ; ne bascule jamais |
| `sessions` | Sessions Claude Code ouvertes (`~/.claude/sessions`), consommation d'une conversation, titre lu en fin de journal, conversations et projets récents, transitions d'état, actions (terminal externe, dossier, terminer) |
| `terminal` | Terminal intégré sans GTK (pur, testé) : commande et environnement de lancement (`Launch`, `extra_args`), choix intégré / externe, état des onglets (`TabState`, `sync_tabs`), textes de fin et de confirmation, reprise après une limite (`resume_decision`), réouverture (`tab_record`, `restore_plan`), messages en attente (`queue_next`, `queue_*`) |
| `terminal_store` | `terminals.json` : interrupteurs de la page Terminaux, onglets à rouvrir (écriture atomique, fichier illisible ignoré) |
| `limit_events` | Marqueurs « limite atteinte » par conversation (`limits/<session_id>.json`) : écrits par le hook, lus puis consommés par le terminal intégré |
| `integration` | `ccs integrate` (fusion prudente de `~/.claude/settings.json`), ligne d'état (⏸ en pause), hook `StopFailure` (bascule, sauf en pause ; marqueur de limite) |
| `desktop` | Boucle GLib du service : boutons des notifications (ActionInvoked), moniteur de `~/.claude/sessions` |
| `doctor` | Bilan de santé (`ccs doctor`) : vérifications `Check(nom, statut, detail, commande)`, sondes injectables (`Probes`), texte et code de sortie |
| `gui/` | Application GTK 4 / libadwaita (onglets) ; `gui/terminals` : onglets du terminal intégré (VTE, importé à la demande), `gui/terminal_split` : deux onglets côte à côte ; dialogues `gui/doctor_dialog`, `gui/preview_dialog`, `gui/new_session_dialog` (`Adw.Dialog`, libadwaita ≥ 1.5) |
| `tray` | Indicateur AyatanaAppIndicator (GTK 3, processus séparé) : jauge, prévisions, pause, nouvelle version ; se relance seul quand le code installé change |
| `cli` | Point d'entrée `claude-accounts` |

`ccs` (bash) reste **l'unique implémentation de la bascule** ; le service,
l'application et l'indicateur l'appellent.

## Terminal intégré

```
 Sessions / Conversations ──► Window.open_claude(cwd, resume, title, external)
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
  message) pour `ccs pause` ; l'appelant réveille ensuite le service
  (`daemon.request_refresh()`).
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

Modules sans GTK, testés, qui ne modifient rien :

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
  atomique), `suggested_filename`.
- `costs` : `conversation_cost(path, subagents=True)` → `Cost` (tokens par
  type, dollars, détail par modèle, `inconnu`). Tarifs `PRICES` datés de
  `PRICES_DATE` (2026-10-06) ; écriture du cache à 1,25 × / 2 × l'entrée,
  grille longue de Haiku 5.5, mode rapide, inférence US ; modèle inconnu →
  `None` (« tarif inconnu »), jamais d'estimation. Une réponse écrite sur
  plusieurs lignes (même identifiant) compte une fois ; sous-agents lus dans
  `<id>/subagents/*.jsonl`. Cache en mémoire (512 journaux) par chemin, taille
  et `mtime_ns`. `format_cost`, `format_details`.
- `launch_options` : `MODELS`, `PERMISSION_MODES` (d'après `claude --help`),
  `claude_args(model, permission_mode, resume, extra)` (valeurs vérifiées : un
  modèle ou un identifiant ne peut pas devenir une option), `LaunchSpec(cwd,
  profile, model, permission_mode)` avec `needs_switch(actif)`, `args()`,
  `shell_command()` ; `launch(spec)` pour un terminal externe. Rien n'y
  bascule : `NewSessionDialog` renvoie un `LaunchSpec`, l'appelant bascule
  (`ccs use`) si besoin puis ouvre la session.

Les dialogues `gui/doctor_dialog.py`, `gui/preview_dialog.py` et
`gui/new_session_dialog.py` sont des `Adw.Dialog` (libadwaita ≥ 1.5) ; le
travail lourd (bilan, lecture du journal, coût, export) tourne dans un fil
(`common.in_thread`). L'aperçu affiche d'abord les 300 derniers messages et
construit l'affichage par paquets de 150 pour ne pas figer la fenêtre.

## En cours de branchement (0.5.0)

- **Commandes** : `doctor`, `pause` (`pause.command`), `preview` (alias
  `apercu`) et `export` dans `cli.py` et `bin/ccs` ; `ccs status` affiche la
  pause.
- **Application** : « Bilan de santé… » dans le menu principal et bandeau au
  démarrage si un problème est trouvé ; état de pause dans l'en-tête et bandeau
  « nouvelle version disponible » ; « Aperçu… » et coût dans les listes de
  conversations ; « Nouvelle session… » → `NewSessionDialog` → bascule si
  `needs_switch` → onglet du terminal intégré avec `spec.args()` ;
  notifications de session cliquables (ouverture de l'onglet) ; badge du
  nombre de sessions en attente sur l'onglet Sessions.

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
fin de semaine prévue) ; suivi des sessions (fin, attente, rappel) ; modules
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
