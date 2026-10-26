# CCS 0.3.0 — plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.

**Spec:** `docs/superpowers/specs/2026-10-26-sessions-integration-design.md`

## Global Constraints
- Lecture seule de `~/.claude/sessions/*.json` et des transcripts ; jamais les `.key`.
- `~/.claude/settings.json` modifié uniquement par `ccs integrate`, atomique + sauvegarde.
- Tests sans réseau, sans vrais jetons, HOME isolé ; git flow ; commits FR.

## Review Focus
- Fiche de session d'un pid mort ou recyclé → ignorée.
- `settings.json` absent, vide, invalide, ou avec une `statusLine` existante → pas d'écrasement.
- Hook appelé sans état / état ancien / aucun compte disponible → pas de crash, notification utile.
- Rafale de changements d'état (session qui alterne vite) → une notification, pas dix.
- Bouton de notification cliqué après que l'état a changé → bascule refusée proprement si le compte n'est plus bon.

### Task 1: `ccs_app/sessions.py` + `ccs sessions`
`Session` (dataclass), `list_sessions()`, `conversation_usage(session)`, `recent_conversations(cwd, limit=8)`, `transitions(prev, cur, now)`, `terminate(pid)`, `terminal_command(cwd, resume=None)`. Tests : fiches valides/invalides/pid mort, slug de projet, usage d'une conversation, conversations récentes avec titre, transitions (seuil 60 s, attente vs terminé), commande terminal.

### Task 2: Intégration Claude Code
`ccs_app/integration.py` : `install(settings_path)`, `uninstall`, `status` ; `statusline_text(state, now)` ; `stop_failure(payload, now)` (décision + exécution). CLI `statusline`, `hook stop-failure`, `integrate on|off|status`. Tests : fusion des réglages, pas d'écrasement, sauvegarde, ligne d'état, décision de secours.

### Task 3: Notifications actives + surveillance des sessions
`notify.send(alert) -> int | None` avec actions ; `Alert.actions` ; `desktop.Bridge` (boucle GLib : ActionInvoked, moniteur de `~/.claude/sessions`) ; daemon : actions `use:<profil>`, notifications de sessions. Tests : actions sur les alertes, traitement d'une action, anti-rafale.

### Task 4: Interface
Onglet Sessions (liste, actions, conversations récentes), sous-menu Sessions de l'indicateur, réglage `alerts.sessions`, bloc Intégration dans Réglages.

### Task 5: Docs, revue, release 0.3.0
README, utilisation, architecture, CHANGELOG, man ; revue finale ; release git flow ; push ; release GitHub.
