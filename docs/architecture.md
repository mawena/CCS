# Architecture

```
            ┌────────────── ~/.claude-accounts/ ──────────────┐
            │ <profil>/oauth.json account.json usage.json      │
            │ history.db  settings.json  state.json  .lock     │
            └───────▲───────────────▲──────────────▲───────────┘
                    │               │              │
  ccs (bash) ───────┤        ccs-daemon (systemd)  │      Comptes Claude (GTK 4)
  save/add/use/rm   │        collecte → décide →   ├───── lit state.json / history.db
                    │        bascule → alerte      │      Indicateur (GTK 3)
                    ▼               │              │
   ~/.claude/.credentials.json      ▼              │
   ~/.claude.json            API Anthropic (usage, jetons)
```

## Modules (`ccs_app/`)

| Module | Rôle |
|---|---|
| `core` | Chemins, profils, verrou, jetons (renouvellement), API d'usage, limites, formats, appel de `ccs` |
| `store` | SQLite : relevés `samples` et événements `events` (bascules, alertes, warm-up, erreurs) |
| `settings` | Réglages JSON fusionnés avec les valeurs par défaut |
| `forecast` | Fonctions pures : fin de session (régression linéaire), rythme hebdo, capacité, meilleur compte |
| `autoswitch` | Décision de bascule (pure) et exécution via `ccs use` |
| `alerts` / `notify` | Quoi notifier (pur, anti-doublon par fenêtre) / envoi D-Bus |
| `daemon` | Boucle : relevés, prévisions, décision, alertes, warm-up, écriture de `state.json` |
| `orchestrator` | Fonctions pures : plage horaire, créneaux décalés, démarrages dus, bascule vers le quota qui expire, réserve, planning, prochain réveil |
| `warmup` | Créneaux fixes et requête minimale dans un `CLAUDE_CONFIG_DIR` temporaire (utilisée aussi par l'orchestrateur) |
| `transcripts` | Lecture des journaux locaux, agrégats, conseils |
| `sessions` | Sessions Claude Code ouvertes (`~/.claude/sessions`), consommation d'une conversation, conversations et projets récents, transitions d'état, actions (terminal, dossier, terminer) |
| `integration` | `ccs integrate` (fusion prudente de `~/.claude/settings.json`), ligne d'état, hook `StopFailure` |
| `desktop` | Boucle GLib du service : boutons des notifications (ActionInvoked), moniteur de `~/.claude/sessions` |
| `gui/` | Application GTK 4 / libadwaita (onglets) |
| `tray` | Indicateur AyatanaAppIndicator (GTK 3, processus séparé) |
| `cli` | Point d'entrée `claude-accounts` |

`ccs` (bash) reste **l'unique implémentation de la bascule** ; le service,
l'application et l'indicateur l'appellent.

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
prochain créneau de démarrage (au plus tôt dans 30 s).

Ordre des décisions à chaque tick : bascule à seuil (98 %) ; sinon bascule
anticipée vers le quota qui expire ; puis démarrages de fenêtres ; puis alertes.
`SIGUSR1` déclenche un relevé immédiat (bouton Actualiser, `claude-accounts
collect`).

## Format de `state.json`

```json
{
  "updated_at": 1793000000.0,
  "active": "perso",
  "capacity": 1.4,
  "best": {"name": "pro", "reason": "au repos, semaine à 22 %"},
  "auto_switch": {"enabled": true, "decision": {"action": "none", "target": null, "reason": "…"},
                  "last": {"ts": 0, "profile": "perso", "mode": "manual"}},
  "orchestrator": {"enabled": true, "active_now": true, "period": ["…", "…"],
                   "reserve": ["boulot"], "next_wake": "…",
                   "plan": [{"name": "perso", "start": "…", "end": "…", "kind": "current|planned"}]},
  "accounts": [{
    "name": "perso", "email": "…", "org": "…", "plan": "pro", "active": true,
    "error": null, "fetched_at": 1793000000.0,
    "limits": [{"kind": "session", "label": "Session (5 h)", "percent": 54, "resets_at": "…"}],
    "forecast": {"verdict": "limit|ok|stable|unknown", "eta": "…", "rate_per_min": 0.4,
                 "minutes_before_reset": 35},
    "pace": {"ideal": 57.1, "margin": 5.2, "per_day_budget": 16.0, "days_left": 3.0}
  }]
}
```
