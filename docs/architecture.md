# Architecture

```
            ┌──────────────── ~/.claude-accounts/ ─────────────────┐
            │ <profil>/oauth.json  account.json  usage.json        │
            │ history.db  settings.json  state.json  .lock         │
            │ pause.json  updates.json                             │
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
| `terminal` | Terminal intégré sans GTK (pur, testé) : commande et environnement de lancement (`Launch`), choix intégré / externe, état des onglets (`TabState`, `sync_tabs`), textes de fin et de confirmation |
| `integration` | `ccs integrate` (fusion prudente de `~/.claude/settings.json`), ligne d'état, hook `StopFailure` |
| `desktop` | Boucle GLib du service : boutons des notifications (ActionInvoked), moniteur de `~/.claude/sessions` |
| `doctor` | Bilan de santé (`ccs doctor`) : vérifications `Check(nom, statut, detail, commande)`, sondes injectables (`Probes`), texte et code de sortie |
| `gui/` | Application GTK 4 / libadwaita (onglets) ; `gui/terminals` : onglets du terminal intégré (VTE, importé à la demande) ; dialogues `gui/doctor_dialog`, `gui/preview_dialog`, `gui/new_session_dialog` (`Adw.Dialog`, libadwaita ≥ 1.5) |
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
  title=None)` et `shell_launch(cwd)` renvoient un `Launch` (`kind`, `cwd`,
  `argv`, `env`, `title`, `session_id`, `envv()`). Les variables posées par une
  session Claude Code parente (`CLAUDECODE`, `CLAUDE_CODE_SSE_PORT`…) sont
  retirées par `env -u`, VTE ne sachant qu'en ajouter.
- `ccs_app/gui/terminals.py` : `vte()` importe VTE 3.91 à la première demande
  (None s'il manque ou si `CCS_NO_VTE=1`). `TerminalsPage` (page « terminals »
  du `ViewStack`, cachée sans onglet) gère un `Adw.TabView` de `TerminalTab`.

API pour les autres fonctions de l'application (`window.terminals`) :

| Appel | Effet |
|---|---|
| `available` | VTE est là (sinon tout passe par le terminal externe) |
| `open_claude(cwd, resume=None, title=None)` → `TerminalTab` | Nouvel onglet affiché et lancé ; `open_shell(cwd)`, `open(launch)` pour un `Launch` |
| `find(pid=None, session_id=None)` → `TerminalTab` ou None | Onglet d'un processus ou d'une conversation (arrêté compris) |
| `present(tab)` | Affiche la page et l'onglet, focus clavier dans le terminal |
| `close(tab)` | Ferme l'onglet (confirmation si claude ou un programme tourne) |
| `tabs()`, `states()` | Onglets ouverts, leurs `TabState` (`kind`, `cwd`, `title`, `session_id`, `pid`, `running`, `state`, `exit_status`) |
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
  Le hook `StopFailure` et la reprise automatique du terminal intégré la
  respectent aussi (en cours de branchement, voir plus bas).

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
- **Pause partout** : le hook `StopFailure` ne bascule pas pendant une pause
  (notification « CCS est en pause jusqu'à HH:MM : pas de bascule
  automatique ») ; la ligne d'état affiche ⏸.
- **Suite du terminal intégré** : le hook `StopFailure` écrit un marqueur par
  conversation, `~/.claude-accounts/limits/<session_id>.json` (en cours,
  bascule faite, compte déjà changé, bascule impossible, aucun compte ;
  retirés après 24 h) ; `terminal.resume_decision` (pure) décide d'envoyer
  « continue » dans l'onglet (une fois par marqueur, au plus 3 par heure et
  par onglet, 2 min d'écart, jamais si l'utilisateur a écrit depuis) ;
  interrupteur gardé dans `~/.claude-accounts/terminals.json`.
  `claude_launch(..., extra_args=())` garde les options de lancement
  (`Launch.extra_args`, `TabState.extra_args`) pour les relances. Onglets
  rouverts au redémarrage, sessions côte à côte et messages en attente :
  à compléter.

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
